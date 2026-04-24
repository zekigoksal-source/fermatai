"""
FermatAI — Kişiselleştirme Derinliği (22.1n-neo FAZ 2.3)
==========================================================

Öğrenci profil zenginleştirme — bot zamanla öğrenciyi TANIYAN bir koça dönüşür.

KATMANLAR:
  1. VARK öğrenme stili (Visual/Auditory/Reading/Kinesthetic)
     — Doğal diyalogdan çıkarım, test YOK ama bot "gör / duy / okuyarak / yaparak"
       tercihlerini izler
  2. MBTI hafif (içedönük vs dışadönük)
     — Konuşma uzunluğu, sosyal ifade sıklığı
  3. Hedef dereceleri (kısa-orta-uzun vade)
  4. Engel haritası (zaman, kaygı, motivasyon, konu bazlı)
  5. Mood history (günlük duygusal durum)

TABLO: ogrenci_profil_extra (schema zaten hazır)

KULLANIM:
  from kisisellestirme import update_vark_signal, get_profile, update_mood
  await update_vark_signal(soz_no, "visual")  # öğrenci "şema çiz" dedi
  await update_mood(soz_no, "positive")
  profile = await get_profile(soz_no)
  # → {vark_dominant, mbti_ic_dis, hedef_kisa, engel_haritasi, son_mood, ...}
"""
from __future__ import annotations

import json
import re
from datetime import datetime, date
from typing import Optional
from db_pool import db_fetch, db_fetchrow, db_execute


# ─── VARK TESPİT PATTERN'LERİ ──────────────────────────────────────────────

_VARK_PATTERNS = {
    "visual": [
        r"\b(sema|grafik|gorsel|cizerek|diyagram|renkli|harita|resim|tablo)\b",
        r"\bg[oö]ster(ir misin|sene)\b",
        r"\bresimle|gorselle\b",
        r"\bvideo izle\b",
    ],
    "auditory": [
        r"\banlatir misin|anlat bana\b",
        r"\b(ses|konus|dinle|podcast|audio)\b",
        r"\ba[cç][iı]kla bana\b",
        r"\bozet ges, [oö]zet konus\b",
    ],
    "reading": [
        r"\b(yazili|yazali|kitap|notlar|metin|okuduk)\b",
        r"\bozet yaz\b",
        r"\b(liste|madde madde)\b",
        r"\b(pdf|kaynak|makale)\b",
    ],
    "kinesthetic": [
        r"\b(yaparak|deneyerek|ugrasarak|elimle|cozerek)\b",
        r"\bhemen dene\b",
        r"\b(pratikte|gercek hayatta|ornek uzerinden)\b",
        r"\b(test|soru coz|cozum)\b",
    ],
}


# ─── MBTI HAFİF PATTERN'LERİ ───────────────────────────────────────────────

_MBTI_EXTROVERT_PATTERNS = [
    r"\bgrup calis|birlikte calis|arkada[sş]l?arim?la\b",
    r"\b(etud|ders)\s*be[gğ]eniyorum.*(ogretmen|hoca)\b",
    r"\b(konusurum|anlatirim|paylasir)\b",
    r"\bsosyal\b",
]
_MBTI_INTROVERT_PATTERNS = [
    r"\byalniz calis|kendim calis|yalniz kalmak\b",
    r"\bsessiz(ce)?|sakin bir yer\b",
    r"\b(kendi kendime|kafamda)\b",
    r"\bkalabalik zor\b",
]


# ─── MOOD KATEGORİLERİ ─────────────────────────────────────────────────────

MOOD_SIGNALS = {
    "positive": [r"\b(iyiyim|guzel|harika|mutluyum|motiveyim|ba[sş]ard[iı]m|\u2728)\b"],
    "neutral":  [r"\b(fena degil|idare eder|normal|oluyor)\b"],
    "tired":    [r"\b(yorgun|uyku|bitkin|tukenmisim|enerji yok)\b"],
    "anxious":  [r"\b(kayg[iı]|stres|panik|ender[iı]sel)\b"],
    "sad":      [r"\b(mutsuz|uzgun|moralsiz|uzuluyorum)\b"],
    "angry":    [r"\b(sinirli|sinirlendim|bikk[iı]n|cile)\b"],
    "excited":  [r"\b(heyecan|muthis|sasirt|cok guzel)\b"],
}


# ─── VARK SINYAL İZLEME ────────────────────────────────────────────────────

async def detect_vark_from_message(message: str) -> Optional[str]:
    """Mesajdaki VARK ipucunu don."""
    if not message:
        return None
    msg = message.lower()
    scores = {}
    for stil, patterns in _VARK_PATTERNS.items():
        for p in patterns:
            if re.search(p, msg):
                scores[stil] = scores.get(stil, 0) + 1
    if not scores:
        return None
    return max(scores, key=scores.get)


async def update_vark_signal(soz_no: int, signal: str) -> None:
    """VARK sinyal toplama — her tespit edilen tercihi hafızaya ekle."""
    try:
        soz_no = int(soz_no)
    except: return
    # Mevcut skorlari cek
    row = await db_fetchrow(
        "SELECT vark_scores FROM ogrenci_profil_extra WHERE soz_no=$1", soz_no
    )
    scores = {"visual": 0, "auditory": 0, "reading": 0, "kinesthetic": 0}
    if row and row.get("vark_scores"):
        try:
            existing = row["vark_scores"]
            if isinstance(existing, str):
                existing = json.loads(existing)
            scores.update(existing)
        except Exception:
            pass
    scores[signal] = scores.get(signal, 0) + 1
    # Dominant
    total = sum(scores.values())
    dominant = max(scores, key=scores.get) if total >= 3 else None

    await db_execute(
        """INSERT INTO ogrenci_profil_extra (soz_no, vark_dominant, vark_scores, updated_at)
           VALUES ($1, $2, $3::jsonb, NOW())
           ON CONFLICT (soz_no) DO UPDATE SET
             vark_dominant = EXCLUDED.vark_dominant,
             vark_scores = EXCLUDED.vark_scores,
             updated_at = NOW()""",
        soz_no, dominant, json.dumps(scores)
    )


# ─── MBTI HAFİF ─────────────────────────────────────────────────────────────

async def update_mbti_signal(soz_no: int, message: str) -> None:
    """Mesajdan içedönük/dışadönük sinyali izle."""
    try:
        soz_no = int(soz_no)
    except: return
    msg = message.lower()
    ext_score = sum(1 for p in _MBTI_EXTROVERT_PATTERNS if re.search(p, msg))
    int_score = sum(1 for p in _MBTI_INTROVERT_PATTERNS if re.search(p, msg))
    if ext_score == int_score == 0:
        return

    # Mevcut profili cek
    row = await db_fetchrow(
        "SELECT mbti_ic_dis, mbti_confidence FROM ogrenci_profil_extra WHERE soz_no=$1",
        soz_no
    )
    cur_type = row.get("mbti_ic_dis") if row else None
    cur_conf = float(row.get("mbti_confidence", 0) or 0) if row else 0.0

    if ext_score > int_score:
        new_type = "extrovert"
        delta = 0.05 * ext_score
    else:
        new_type = "introvert"
        delta = 0.05 * int_score

    if cur_type == new_type:
        new_conf = min(0.95, cur_conf + delta)
    elif cur_type and cur_conf > 0:
        # Cakis ma — guveni dustur
        new_conf = max(0.1, cur_conf - delta)
        if new_conf <= 0.2:
            cur_type = new_type
            new_conf = 0.3
    else:
        cur_type = new_type
        new_conf = 0.3 + delta

    await db_execute(
        """INSERT INTO ogrenci_profil_extra (soz_no, mbti_ic_dis, mbti_confidence, updated_at)
           VALUES ($1, $2, $3, NOW())
           ON CONFLICT (soz_no) DO UPDATE SET
             mbti_ic_dis = EXCLUDED.mbti_ic_dis,
             mbti_confidence = EXCLUDED.mbti_confidence,
             updated_at = NOW()""",
        soz_no, cur_type, round(new_conf, 2)
    )


# ─── HEDEF YONETIMI ────────────────────────────────────────────────────────

async def set_hedef(soz_no: int, vade: str, hedef: str) -> None:
    """vade: 'kisa' | 'orta' | 'uzun'."""
    try:
        soz_no = int(soz_no)
    except: return
    col = {"kisa": "hedef_kisa", "orta": "hedef_orta", "uzun": "hedef_uzun"}.get(vade)
    if not col:
        return
    await db_execute(
        f"""INSERT INTO ogrenci_profil_extra (soz_no, {col}, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (soz_no) DO UPDATE SET
              {col} = EXCLUDED.{col}, updated_at = NOW()""",
        soz_no, hedef[:500]
    )


# ─── ENGEL HARITASI ────────────────────────────────────────────────────────

_ENGELLER = ["zaman", "kaygi", "motivasyon", "konu_zorlugu", "uyku", "dikkat",
              "aile", "sosyal", "maddiyat", "kiyas"]


async def update_engel(soz_no: int, engel: str, siddet: int = 1) -> None:
    """Engel haritasini guncelle. siddet: 1-5."""
    try:
        soz_no = int(soz_no)
    except: return
    if engel not in _ENGELLER:
        return
    row = await db_fetchrow(
        "SELECT engel_haritasi FROM ogrenci_profil_extra WHERE soz_no=$1", soz_no
    )
    harita = {}
    if row and row.get("engel_haritasi"):
        try:
            raw = row["engel_haritasi"]
            harita = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception:
            pass
    cur = harita.get(engel, 0)
    harita[engel] = min(5, cur + siddet)
    # Son 30 gun engeli azaltmak icin timestamp
    harita[f"{engel}_last"] = datetime.now().isoformat()

    await db_execute(
        """INSERT INTO ogrenci_profil_extra (soz_no, engel_haritasi, updated_at)
           VALUES ($1, $2::jsonb, NOW())
           ON CONFLICT (soz_no) DO UPDATE SET
             engel_haritasi = EXCLUDED.engel_haritasi, updated_at = NOW()""",
        soz_no, json.dumps(harita)
    )


# ─── MOOD TRACKING ────────────────────────────────────────────────────────

async def detect_mood_from_message(message: str) -> Optional[str]:
    if not message:
        return None
    msg = message.lower()
    for mood, patterns in MOOD_SIGNALS.items():
        for p in patterns:
            if re.search(p, msg):
                return mood
    return None


async def update_mood(soz_no: int, mood: str) -> None:
    try:
        soz_no = int(soz_no)
    except: return

    row = await db_fetchrow(
        "SELECT mood_history FROM ogrenci_profil_extra WHERE soz_no=$1", soz_no
    )
    history = []
    if row and row.get("mood_history"):
        try:
            raw = row["mood_history"]
            history = json.loads(raw) if isinstance(raw, str) else list(raw or [])
        except Exception:
            pass
    today = date.today().isoformat()
    # Aynı gün duplikasyon olmasın (son mood üstüne yaz)
    if history and history[-1].get("date") == today:
        history[-1] = {"date": today, "mood": mood}
    else:
        history.append({"date": today, "mood": mood})
        history = history[-30:]  # son 30 gun

    await db_execute(
        """INSERT INTO ogrenci_profil_extra (soz_no, son_mood, mood_history, updated_at)
           VALUES ($1, $2, $3::jsonb, NOW())
           ON CONFLICT (soz_no) DO UPDATE SET
             son_mood = EXCLUDED.son_mood,
             mood_history = EXCLUDED.mood_history,
             updated_at = NOW()""",
        soz_no, mood[:30], json.dumps(history)
    )


# ─── PROFİL OKUMA + CLAUDE INJECTION ───────────────────────────────────────

async def get_profile(soz_no: int) -> Optional[dict]:
    """Ogrenci zenginlestirilmis profili."""
    try:
        soz_no = int(soz_no)
    except: return None
    row = await db_fetchrow(
        "SELECT * FROM ogrenci_profil_extra WHERE soz_no=$1", soz_no
    )
    if not row:
        return None
    out = dict(row)
    # JSONB alanlari parse et
    for k in ("vark_scores", "engel_haritasi", "mood_history"):
        if out.get(k) and isinstance(out[k], str):
            try:
                out[k] = json.loads(out[k])
            except Exception:
                pass
    return out


async def get_context_injection(soz_no: int) -> str:
    """Claude system_prompt'a eklenecek kisisellestirme bilgisi."""
    profile = await get_profile(soz_no)
    if not profile:
        return ""
    lines = ["\n🎯 OGRENCI KISISELLESTIRME (doga konusma, direkt referans verme):"]

    if profile.get("vark_dominant"):
        vark_map = {
            "visual": "görsel (şema, grafik, resim)",
            "auditory": "işitsel (anlatma, dinleme)",
            "reading": "okuma (yazılı, liste, özet)",
            "kinesthetic": "kinestetik (yaparak, pratik)",
        }
        v = vark_map.get(profile["vark_dominant"], "")
        if v:
            lines.append(f"  - Öğrenme stili: {v} tercihi (VARK sinyali)")

    mbti = profile.get("mbti_ic_dis")
    if mbti and profile.get("mbti_confidence", 0) > 0.4:
        mbti_map = {"introvert": "içedönük (bireysel çalışmayı seviyor)",
                    "extrovert": "dışadönük (grup/sosyal tercih)"}
        lines.append(f"  - Sosyal tarz: {mbti_map.get(mbti, mbti)} (conf: {profile['mbti_confidence']})")

    for vade in ("kisa", "orta", "uzun"):
        h = profile.get(f"hedef_{vade}")
        if h:
            lines.append(f"  - Hedef ({vade} vade): {h[:150]}")

    engel = profile.get("engel_haritasi")
    if engel and isinstance(engel, dict):
        aktif = [(k, v) for k, v in engel.items()
                 if not k.endswith("_last") and isinstance(v, int) and v >= 2]
        if aktif:
            aktif.sort(key=lambda x: -x[1])
            lines.append(f"  - Aktif engeller: {', '.join(f'{k}({v})' for k, v in aktif[:3])}")

    mood = profile.get("son_mood")
    if mood:
        lines.append(f"  - Son duygusal durum: {mood}")

    if len(lines) == 1:
        return ""  # sadece baslik varsa don
    lines.append("  → Bu bilgiyi DIREKT ALINTI YAPMA ('VARK'ın visual' deme). "
                  "Dogal davran — gorselciyse sema cizmeyi oner, içedönükse grup zorlamayin.")
    return "\n".join(lines)


async def process_message(soz_no: int, message: str) -> None:
    """Mesaji dinle, profil sinyallerini izle (async fire-and-forget)."""
    if not soz_no or not message:
        return
    try:
        # VARK
        vark = await detect_vark_from_message(message)
        if vark:
            await update_vark_signal(int(soz_no), vark)
        # MBTI
        await update_mbti_signal(int(soz_no), message)
        # Mood
        mood = await detect_mood_from_message(message)
        if mood:
            await update_mood(int(soz_no), mood)
    except Exception:
        pass  # silent — kisisellestirme optional


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    async def main():
        soz_no = 999999  # test
        # Simulate conversation
        for msg in [
            "şema çizerek anlat",
            "yalnız çalışmayı seviyorum",
            "iyiyim motiveyim bugün",
            "kaygılıyım stres var",
        ]:
            await process_message(soz_no, msg)
        p = await get_profile(soz_no)
        print('Profile:', json.dumps(p, ensure_ascii=False, indent=2, default=str))
        print()
        ctx = await get_context_injection(soz_no)
        print('Context injection:')
        print(ctx)
        # Test verilerini temizle
        await db_execute("DELETE FROM ogrenci_profil_extra WHERE soz_no=$1", soz_no)
    asyncio.run(main())
