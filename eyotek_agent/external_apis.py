"""
External API Entegrasyonları — CANLI (23 Nisan)
==================================================
Neo key'leri .env'e eklediğinde OTOMATIK aktive olur.
Key yoksa sessizce skip — sistem çalışmaya devam.

ENV:
  YOUTUBE_API_KEY           — YouTube Data API v3
  GCAL_SERVICE_ACCOUNT_JSON — Google Calendar service account JSON dosyası PATH
  GCAL_CALENDAR_ID          — Hangi takvim (default primary)
  OPENAI_API_KEY            — Whisper için
  ANTHROPIC_API_KEY         — Files API için (zaten var)
"""
from __future__ import annotations
import os
import json
from datetime import datetime, timedelta
from loguru import logger

# .env yükle (standalone çalışırken)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# YOUTUBE — konu anlatımı video önerisi
# ═══════════════════════════════════════════════════════════════════════════

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()


def is_youtube_ready() -> bool:
    return bool(YOUTUBE_API_KEY)


# ─── WHITELIST: Sadece güvenilir YKS/LGS kanalları (Neo 23 Nisan kararı) ────
# Rastgele YouTube sonucu kaliteyi garantilemez. Sadece bu listedeki kanallardan
# çıkan videolar önerilebilir. Liste güncellemesi Neo onayıyla yapılır.
YOUTUBE_WHITELIST_CHANNELS = [
    # Sayısal odaklı
    "Tonguç Akademi",
    "Hocalara Geldik",
    "SiberAhenk",
    "Ali Akay Matematik",
    "3D Yayınları",
    "Örnek Akademi",
    "Sınavdestek",
    "Benim Hocam",
    # MEB resmi
    "Milli Eğitim Bakanlığı",
    "EBA",
    "OGM Materyal",
    # Üniversite & akademik
    "Khan Academy Türkçe",
]

# Her kanal max 1 video — çeşitlilik (aynı kanaldan 3 video önerilmesin)
YOUTUBE_MAX_PER_CHANNEL = 1


async def youtube_search(query: str, max_results: int = 2,
                          prefer_channels: list[str] = None,
                          strict_whitelist: bool = True) -> list[dict]:
    """YouTube'da TR konu anlatımı videosu bul.

    23 Nisan (Neo kararı): SADECE whitelist kanallarından sonuç döner.
    strict_whitelist=True → whitelist dışı video ASLA önerilmez.
    Bu kanallardan hiç uygun sonuç yoksa BOŞ liste döner — "rastgele bir kaynak" gösterilmez.

    prefer_channels: Caller belirli bir kanalı öne çıkarmak isterse (opsiyonel, hâlâ whitelist içi).
    """
    if not YOUTUBE_API_KEY:
        return []
    try:
        import httpx

        # Whitelist — genişletilebilir ama Neo onayıyla
        whitelist = list(YOUTUBE_WHITELIST_CHANNELS)
        preferred = prefer_channels or whitelist
        whitelist_lower = [w.lower() for w in whitelist]

        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": f"{query} YKS konu anlatımı",
                    "type": "video",
                    "maxResults": 20,  # daha geniş al, whitelist'le filtrele
                    "relevanceLanguage": "tr",
                    "regionCode": "TR",
                    "videoEmbeddable": "true",
                    "key": YOUTUBE_API_KEY,
                },
            )
            if r.status_code != 200:
                logger.warning(f"youtube API {r.status_code}: {r.text[:200]}")
                return []
            data = r.json()
            items = data.get("items", [])

            # ─── WHITELIST FILTER ──────────────────────────
            filtered = []
            channel_counts = {}  # her kanaldan max N video
            for item in items:
                ch = item["snippet"]["channelTitle"].lower()
                # Whitelist kontrolü — substring match
                matched = None
                for w in whitelist_lower:
                    if w in ch:
                        matched = w
                        break
                if strict_whitelist and not matched:
                    continue
                # Kanal başı limit
                cnt = channel_counts.get(matched or ch, 0)
                if cnt >= YOUTUBE_MAX_PER_CHANNEL:
                    continue
                channel_counts[matched or ch] = cnt + 1

                filtered.append({
                    "baslik": item["snippet"]["title"][:100],
                    "kanal": item["snippet"]["channelTitle"],
                    "url": f"https://youtu.be/{item['id']['videoId']}",
                    "aciklama": item["snippet"].get("description", "")[:120],
                    "thumbnail": item["snippet"].get("thumbnails", {}).get("medium", {}).get("url", ""),
                    "_whitelist_match": matched,
                })
                if len(filtered) >= max_results:
                    break

            # Preferred kanalları öne al (aynı sonuç içinde ranking)
            preferred_lower = [p.lower() for p in preferred]

            def priority(v):
                ch = v["kanal"].lower()
                for i, p in enumerate(preferred_lower):
                    if p in ch:
                        return i
                return 999

            filtered.sort(key=priority)
            # _whitelist_match internal kolonu kaldır
            for v in filtered:
                v.pop("_whitelist_match", None)

            return filtered[:max_results]
    except Exception as e:
        logger.warning(f"youtube_search hata: {e}")
        return []


def format_youtube_results(query: str, videos: list[dict]) -> str:
    """WhatsApp uyumlu liste."""
    if not videos:
        return (
            f"_'{query}' için güvendiğim kaynaklardan uygun video bulamadım._\n\n"
            f"Sana rastgele bir video önermek yerine şöyle yapalım: "
            f"konuyu birlikte adım adım gidelim, sonra MEB OGM veya çıkmış sorulardan ilerleyelim. 🎯"
        )
    lines = [f"🎥 *{query}* için onaylı kaynaklardan öneri:", "━━━━━━━━━━━━━━━━━━━━━━"]
    for i, v in enumerate(videos, 1):
        lines.append(f"\n*{i}.* {v['baslik']}")
        lines.append(f"   📺 _{v['kanal']}_")
        lines.append(f"   🔗 {v['url']}")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Bu videoyu izledikten sonra birlikte soru çözelim mi?_ 🎯")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE CALENDAR — etüt → takvim senkron
# ═══════════════════════════════════════════════════════════════════════════

GCAL_CREDS_PATH = os.getenv("GCAL_SERVICE_ACCOUNT_JSON", "").strip()
GCAL_CALENDAR_ID = os.getenv("GCAL_CALENDAR_ID", "primary").strip()

_gcal_service = None  # cache


def is_gcal_ready() -> bool:
    return bool(GCAL_CREDS_PATH) and os.path.exists(GCAL_CREDS_PATH)


def _get_gcal_service():
    """Lazy init — service account ile Calendar API bağlantısı."""
    global _gcal_service
    if _gcal_service is not None:
        return _gcal_service
    if not is_gcal_ready():
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_file(
            GCAL_CREDS_PATH,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        _gcal_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return _gcal_service
    except ImportError:
        logger.warning("google-api-python-client kurulu degil — pip install google-api-python-client google-auth")
        return None
    except Exception as e:
        logger.warning(f"gcal init: {e}")
        return None


async def gcal_create_event_safe(
    summary: str,
    start_iso: str,
    duration_min: int = 45,
    description: str = "",
    timezone: str = "Europe/Istanbul",
    requester_role: str = "system",
) -> dict | None:
    """ACL guard'lı event create — sadece admin/mudur/ogretmen yazabilir."""
    if requester_role not in ("admin", "mudur", "ogretmen", "rehber", "system"):
        logger.warning(f"gcal_create: role '{requester_role}' yetkisiz")
        return None
    return await gcal_create_event(summary, start_iso, duration_min, description, timezone=timezone)


async def gcal_create_event(
    summary: str,
    start_iso: str,
    duration_min: int = 45,
    description: str = "",
    attendees: list[str] = None,
    timezone: str = "Europe/Istanbul",
) -> dict | None:
    """Event yarat. Returns: {'id': '...', 'htmlLink': '...'} veya None."""
    service = _get_gcal_service()
    if not service:
        return None
    try:
        import asyncio
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(minutes=duration_min)

        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
        }
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]

        # Senkron API'yi thread'e at
        result = await asyncio.to_thread(
            lambda: service.events().insert(calendarId=GCAL_CALENDAR_ID, body=body).execute()
        )
        return {"id": result.get("id"), "htmlLink": result.get("htmlLink"), "summary": summary}
    except Exception as e:
        logger.warning(f"gcal_create_event: {e}")
        return None


async def gcal_list_upcoming(max_results: int = 10, days: int = 7) -> list[dict]:
    """Önümüzdeki günlerin eventleri."""
    service = _get_gcal_service()
    if not service:
        return []
    try:
        import asyncio
        now = datetime.utcnow().isoformat() + "Z"
        until = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
        result = await asyncio.to_thread(
            lambda: service.events().list(
                calendarId=GCAL_CALENDAR_ID,
                timeMin=now, timeMax=until,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
        )
        events = result.get("items", [])
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                "link": e.get("htmlLink"),
            }
            for e in events
        ]
    except Exception as e:
        logger.warning(f"gcal_list: {e}")
        return []


async def get_user_email(phone: str = "", soz_no: int = 0, ogretmen_ad: str = "") -> str | None:
    """Kullanıcı email'i — acl_users > students > staff sırasıyla.

    Öğrenci/öğretmen Google Calendar attendee olarak eklenebilmesi için.
    Email yoksa None döner — event sadece merkezi takvime yazılır.
    """
    try:
        from db_pool import db_fetchval
        if phone:
            phone_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
            # acl_users
            e = await db_fetchval(
                "SELECT email FROM fermat.acl_users WHERE REPLACE(phone,'+','')=$1 AND email IS NOT NULL AND email != ''",
                phone_clean,
            )
            if e:
                return e
            # students
            e = await db_fetchval(
                "SELECT email FROM fermat.students WHERE REPLACE(phone,'+','')=$1 AND email IS NOT NULL AND email != ''",
                phone_clean,
            )
            if e:
                return e
        if soz_no:
            e = await db_fetchval(
                "SELECT email FROM fermat.students WHERE soz_no::text=$1 AND email IS NOT NULL AND email != ''",
                str(soz_no),
            )
            if e:
                return e
        if ogretmen_ad:
            e = await db_fetchval(
                "SELECT email FROM fermat.staff WHERE full_name ILIKE $1 AND email IS NOT NULL AND email != '' LIMIT 1",
                f"%{ogretmen_ad}%",
            )
            if e:
                return e
    except Exception as e:
        logger.debug(f"get_user_email: {e}")
    return None


async def set_user_email(phone: str, email: str, role_hint: str = "") -> bool:
    """Kullanıcı email'ini kaydet (öğrenci/ACL takvim senkron için)."""
    try:
        from db_pool import db_execute
        phone_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
        # Basit email validation
        if "@" not in email or len(email) < 5:
            return False
        await db_execute(
            "UPDATE fermat.acl_users SET email=$1 WHERE REPLACE(phone,'+','')=$2",
            email, phone_clean,
        )
        await db_execute(
            "UPDATE fermat.students SET email=$1 WHERE REPLACE(phone,'+','')=$2 AND (email IS NULL OR email='')",
            email, phone_clean,
        )
        logger.info(f"  📧 Email kaydedildi: {phone_clean[-4:]} → {email}")
        return True
    except Exception as e:
        logger.warning(f"set_user_email: {e}")
        return False


async def gcal_create_etut(
    ogrenci_ad: str, ogretmen_ad: str, ders: str, konu: str,
    tarih_iso: str, sure_dk: int = 45, ogrenci_soz_no: int = 0,
    ogrenci_email: str = "", ogretmen_email: str = "",
) -> dict | None:
    """Etüt için özel shortcut.

    23 Nisan KVKK fix:
    - Title'da öğrenci adı YOK (sadece ders + öğretmen) → başka kimse görmesin
    - Description'da soz_no meta — tool level filter için
    - Öğrenci kısaltması (Ali K.) optional context
    """
    # Öğrenci anonimleştir — Ali Küçükuysal → Ali K.
    _parts = (ogrenci_ad or "").split()
    _ogr_kisa = f"{_parts[0]} {_parts[1][0]}." if len(_parts) >= 2 else (_parts[0] if _parts else "Ö.")

    summary = f"Etüt · {ders} · {ogretmen_ad}"
    description = (
        f"ders: {ders}\n"
        f"ogretmen: {ogretmen_ad}\n"
        f"ogrenci_kisa: {_ogr_kisa}\n"
        f"ogrenci_soz_no: {ogrenci_soz_no}\n"
        f"konu: {konu}\n"
        f"sure_dk: {sure_dk}\n"
        f"---\n"
        f"_FermatAI tarafindan otomatik olusturuldu._"
    )
    # 23 Nisan: Attendee olarak öğrenci + öğretmen email'i — Google davet gönderir
    attendees = []
    if ogrenci_email and "@" in ogrenci_email:
        attendees.append(ogrenci_email)
    if ogretmen_email and "@" in ogretmen_email:
        attendees.append(ogretmen_email)
    return await gcal_create_event(summary, tarih_iso, sure_dk, description, attendees=attendees)


def gcal_quick_add_link(
    summary: str, start_iso: str, duration_min: int = 60,
    description: str = "", location: str = "",
) -> str:
    """Google Calendar 'Quick Add' URL'i — kullanıcı tek tıkla kendi takvimine ekler.

    Email gerekmez. Herhangi bir Google hesabı ile açılır.
    """
    from urllib.parse import urlencode
    from datetime import datetime, timedelta
    try:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        end_dt = start_dt + timedelta(minutes=duration_min)
        # Google format: YYYYMMDDTHHMMSS (UTC'ye çevirme yok, ISO direkt)
        start_fmt = start_dt.strftime("%Y%m%dT%H%M%S")
        end_fmt = end_dt.strftime("%Y%m%dT%H%M%S")
        params = {
            "action": "TEMPLATE",
            "text": summary,
            "dates": f"{start_fmt}/{end_fmt}",
            "details": description,
            "ctz": "Europe/Istanbul",
        }
        if location:
            params["location"] = location
        return f"https://calendar.google.com/calendar/u/0/r/eventedit?{urlencode(params)}"
    except Exception as e:
        logger.debug(f"quick_add_link: {e}")
        return ""


async def gcal_create_study_plan(
    soz_no: int, ogrenci_ad: str, plan_events: list[dict],
    ogrenci_email: str = "",
) -> list[dict]:
    """Çalışma planı → çoklu calendar eventi.

    plan_events: [
      {"tarih_iso": "2026-04-24T14:00:00", "ders": "Fizik", "konu": "Kaldırma",
       "sure_dk": 90, "aciklama": "..."},
      ...
    ]

    Öğrenci email verilirse her event'e attendee eklenir.
    """
    created = []
    _parts = (ogrenci_ad or "").split()
    _kisa = f"{_parts[0]} {_parts[1][0]}." if len(_parts) >= 2 else (_parts[0] if _parts else "Ö.")

    attendees = [ogrenci_email] if ogrenci_email and "@" in ogrenci_email else []

    for ev in plan_events:
        try:
            summary = f"📚 Çalışma · {ev.get('ders', '')} · {_kisa}"
            description = (
                f"tip: calisma_plani\n"
                f"ders: {ev.get('ders', '')}\n"
                f"konu: {ev.get('konu', '')}\n"
                f"ogrenci_soz_no: {soz_no}\n"
                f"sure_dk: {ev.get('sure_dk', 60)}\n"
                f"---\n"
                f"{ev.get('aciklama', '')}\n\n"
                f"_FermatAI çalışma planı — hedef ve netlerine göre hazırlandı._"
            )
            r = await gcal_create_event(
                summary, ev["tarih_iso"], ev.get("sure_dk", 60),
                description, attendees=attendees,
            )
            if r:
                created.append(r)
        except Exception as e:
            logger.debug(f"plan event: {e}")
    return created


async def gcal_list_for_ogretmen(ogretmen_ad: str, days: int = 7) -> list[dict]:
    """Sadece o öğretmenin etütlerini listele (description filter)."""
    all_events = await gcal_list_upcoming(max_results=100, days=days)
    filtered = []
    for e in all_events:
        # Event detayına bak — description'dan öğretmen kontrolü
        # gcal_list_upcoming zaten summary ve start veriyor, description için ek API call
        summary = (e.get("summary") or "").lower()
        if ogretmen_ad.lower() in summary:
            filtered.append(e)
    return filtered


async def gcal_list_for_ogrenci(soz_no: int, days: int = 7) -> list[dict]:
    """Öğrenci için KENDI etütleri — description'da soz_no eşleşmeli.

    NOT: Bu fonksiyon Calendar API'yi ÇAĞIRIR ama RESULT'ı filtreler.
    Öğrenciye asla başka öğrencinin etüt bilgisi sızdırılmaz.

    Alternatif (tercih edilen): DB'de `etut_records` tablosundan çek.
    """
    service = _get_gcal_service()
    if not service:
        return []
    try:
        import asyncio
        from datetime import datetime, timedelta
        now = datetime.utcnow().isoformat() + "Z"
        until = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"
        result = await asyncio.to_thread(
            lambda: service.events().list(
                calendarId=GCAL_CALENDAR_ID,
                timeMin=now, timeMax=until,
                maxResults=100,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
        )
        events = result.get("items", [])
        filtered = []
        for e in events:
            desc = e.get("description", "")
            # soz_no eşleşmesi zorunlu
            if f"ogrenci_soz_no: {soz_no}" in desc:
                filtered.append({
                    "id": e.get("id"),
                    "summary": e.get("summary"),
                    "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                    # öğrenciye description VERME — sadece kendi etüt bilgisi yeterli
                    "ders": _extract_field(desc, "ders"),
                    "ogretmen": _extract_field(desc, "ogretmen"),
                    "konu": _extract_field(desc, "konu"),
                })
        return filtered
    except Exception as e:
        logger.warning(f"gcal_list_for_ogrenci: {e}")
        return []


def _extract_field(description: str, field: str) -> str:
    """Description'dan 'field: value' pattern çıkar."""
    import re
    m = re.search(rf'^{field}:\s*(.+)$', description or "", re.MULTILINE)
    return m.group(1).strip() if m else ""


# ═══════════════════════════════════════════════════════════════════════════
# ANTHROPIC FILES API — PDF/resim yükleme
# ═══════════════════════════════════════════════════════════════════════════

def is_files_ready() -> bool:
    """ANTHROPIC_API_KEY yeterli, SDK mevcut mu kontrol."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


async def upload_to_claude(file_path: str) -> str | None:
    """Anthropic Files API'ye yükle, file_id dön.

    NOT: Anthropic Files API beta, sdk versiyonuna bağlı.
    """
    if not is_files_ready() or not os.path.exists(file_path):
        return None
    try:
        import asyncio
        from anthropic import Anthropic
        client = Anthropic()
        # SDK'nın desteklediği API'ye göre değişir — try/except
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        filename = os.path.basename(file_path)
        try:
            result = await asyncio.to_thread(
                lambda: client.beta.files.upload(file=(filename, file_bytes))
            )
            return getattr(result, "id", None)
        except AttributeError:
            # Beta API henüz SDK'da yoksa
            logger.debug("Anthropic Files API sdk'da henuz yok, upgrade gerek")
            return None
    except Exception as e:
        logger.warning(f"upload_to_claude: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# WHISPER — sesli mesaj transkripsiyon
# ═══════════════════════════════════════════════════════════════════════════

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")


async def transcribe_audio(audio_bytes: bytes) -> str | None:
    """OpenAI Whisper ile Türkçe transkripsiyon.

    mevcut _transcribe_audio fonksiyonuyla uyumlu upgrade path.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from openai import AsyncOpenAI
        import tempfile
        client = AsyncOpenAI()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as f:
                tr = await client.audio.transcriptions.create(
                    model=WHISPER_MODEL,
                    file=f,
                    language="tr",
                )
            return tr.text
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        logger.warning(f"whisper: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# READY STATUS — hepsi bir yerde
# ═══════════════════════════════════════════════════════════════════════════

def status_report() -> dict:
    """Hangi API hazır?"""
    return {
        "youtube": is_youtube_ready(),
        "google_calendar": is_gcal_ready(),
        "anthropic_files": is_files_ready(),
        "whisper": bool(os.getenv("OPENAI_API_KEY")),
    }


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    async def t():
        print("=== API Status ===")
        for k, v in status_report().items():
            print(f"  {'✓' if v else '✗'} {k}: {'ready' if v else 'key yok / skip'}")

        if is_youtube_ready():
            vids = await youtube_search("türev konu anlatımı", max_results=2)
            print(f"\n🎥 YouTube test: {len(vids)} video")
            for v in vids:
                print(f"  • {v['baslik']} [{v['kanal']}]")

        if is_gcal_ready():
            upcoming = await gcal_list_upcoming(5)
            print(f"\n📅 GCal test: {len(upcoming)} upcoming event")

    asyncio.run(t())
