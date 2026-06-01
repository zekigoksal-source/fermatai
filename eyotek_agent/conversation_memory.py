"""
FermatAI Konuşma Hafızası
==========================
Öğrenci bazlı kısa dönem context cache.
Her öğrenci için son konuşma özeti ve aktif konu takibi.

Amaç: Claude'a her mesajda öğrencinin bağlamını vererek
daha tutarlı ve kişisel diyaloglar kurmak.
"""

import asyncio
import json
import time
from typing import Optional
from datetime import datetime

from loguru import logger

import os
from dotenv import load_dotenv as _lde
_lde(override=True)

from db_pool import (
    get_pool as _get_pool,
    db_fetch as _fetch,
    db_fetchrow as _fetchrow,
    db_fetchval as _fetchval,
)

# Bellek içi cache — phone → context
# Oturum 18: TTL 1h -> 3h (ogrenci verisi gunluk bazda degisir) + memory leak guard
_CONTEXT_CACHE: dict[str, dict] = {}
_CACHE_TTL = 10800  # 3 saat gecerlilik (cache hit orani artar)
_CACHE_MAX_AGE = 86400  # 24 saat sonra entry otomatik silinir


async def get_student_context(phone: str) -> Optional[dict]:
    """
    Öğrenci bağlamını getir. Cache varsa cache'den, yoksa DB'den oluştur.

    Returns:
        {
            "name": "Ali Küçükuysal",
            "class": "11 SAY",
            "last_topic": "fizik - kaldırma kuvveti",
            "mood": "normal",  # positive/negative/stressed/normal
            "recent_summary": "Son denemede 80 net yaptı, fizik zayıf...",
            "session_messages": 5,
            "last_active": "2026-04-11 20:00",
        }
    """
    phone_clean = phone.replace("+", "")

    # Memory leak guard: %1 sampling ile 24h+ eski entry'leri temizle
    import random
    if random.random() < 0.01:
        _now = time.time()
        for _k in [k for k, v in list(_CONTEXT_CACHE.items())
                   if _now - v.get("_ts", 0) > _CACHE_MAX_AGE]:
            _CONTEXT_CACHE.pop(_k, None)

    # Cache kontrol
    cached = _CONTEXT_CACHE.get(phone_clean)
    if cached and time.time() - cached.get("_ts", 0) < _CACHE_TTL:
        return cached

    # DB'den olustur — YEREL POOL kullan, gather ile paralel query
    try:
        # 1. Ogrenci profili — diger query'ler soz_no'ya bagli, once bu calisir
        profile = await _fetchrow("""
            SELECT s.full_name, s.class_name, s.soz_no,
                   a.role
            FROM students s
            LEFT JOIN acl_users a ON REPLACE(a.phone,'+','') = $1
            WHERE REPLACE(s.phone,'+','') = $1
            LIMIT 1
        """, phone_clean)

        if not profile:
            return None

        soz_no = int(profile['soz_no']) if profile['soz_no'] else None
        name = profile['full_name'] or "?"

        if not soz_no:
            return None

        # Query 2-7: PARALEL (asyncio.gather) - Oturum 18
        # Her query pool'dan kendi connection'ini alir, 6 sorgu gercek paralel calisir
        exam, recent_msgs, devam, weak_rows, trend_rows, ayt_row = await asyncio.gather(
            _fetchrow("""
                SELECT exam_name, toplam, exam_date
                FROM student_exams WHERE soz_no = $1
                ORDER BY exam_date DESC NULLS LAST LIMIT 1
            """, soz_no),
            # Oturum 23 (Neo UX): 200 -> 1200 char. 200 char bot'un kendi onceki
            # uzun pedagojik cevaplarinin SADECE basini gormesine yol aciyordu.
            # Oturum 24 (Neo bug): 3 saat INTERVAL kaldirildi. WhatsApp ogrencileri
            # gunde 1-2 kez yaziyor; 3h filtre cogu zaman bos sonuc donduruyordu.
            # LIMIT 6 ile en yeni 6 mesaj cekilir, tarih farki prompt'ta belirtilir.
            _fetch("""
                SELECT message_role, LEFT(content, 1200) as content, created_at
                FROM agent_conversations
                WHERE phone = $1 AND message_role IN ('user','assistant')
                AND content NOT LIKE '[tool_calls%'
                ORDER BY created_at DESC LIMIT 6
            """, phone_clean),
            _fetchval(
                "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1", soz_no),
            _fetch("""
                SELECT ders, konu, sinav_hata_yuzdesi
                FROM student_topic_tracker
                WHERE soz_no = $1
                  AND status = 'onerilen'
                  AND sinav_hata_yuzdesi >= 50
                ORDER BY sinav_hata_yuzdesi DESC
                LIMIT 5
            """, soz_no),
            _fetch("""
                SELECT DISTINCT ON (exam_date) exam_name, toplam, exam_date
                FROM student_exams
                WHERE soz_no = $1 AND exam_name NOT LIKE '[AYT]%'
                  AND toplam > 5
                ORDER BY exam_date DESC NULLS LAST
                LIMIT 3
            """, soz_no),
            _fetchrow("""
                SELECT ham_puan_ayt, yerlesme_puani_ayt, katilan_sinav_ayt, sinav_sayisi_ayt
                FROM student_exam_analysis
                WHERE soz_no::text = $1::text
            """, str(soz_no)),
            return_exceptions=True
        )
        # Exception'lari None/bos ile ikame et
        if isinstance(exam, Exception): exam = None
        if isinstance(recent_msgs, Exception): recent_msgs = []
        if isinstance(devam, Exception): devam = None
        if isinstance(weak_rows, Exception): weak_rows = []
        if isinstance(trend_rows, Exception): trend_rows = []
        if isinstance(ayt_row, Exception): ayt_row = None

        # 5. Zayif konular - kayitlari isle
        weak_topics = []
        for wr in weak_rows or []:
            try:
                weak_topics.append({
                    "ders": wr['ders'],
                    "konu": wr['konu'],
                    "hata_pct": round(wr['sinav_hata_yuzdesi'])
                })
            except Exception:
                continue

        # 6. Son 3 TYT deneme trendi
        exam_trend = []
        for tr in trend_rows or []:
            try:
                exam_trend.append({
                    "name": (tr['exam_name'] or "?")[:30],
                    "net": round(tr['toplam'], 1) if tr['toplam'] else 0,
                    "date": tr['exam_date'].strftime("%d.%m") if tr['exam_date'] else ""
                })
            except Exception:
                continue

        # 7. AYT birlestir analiz
        ayt_last = None
        if ayt_row and ayt_row.get('ham_puan_ayt'):
            ayt_last = {
                "name": "AYT Birlestir",
                "ham": ayt_row['ham_puan_ayt'],
                "yerlesme": ayt_row['yerlesme_puani_ayt'],
                "katilim": f"{ayt_row.get('katilan_sinav_ayt','?')}/{ayt_row.get('sinav_sayisi_ayt','?')}",
            }

        # Oturum 25.8 fix — KVKK identity manipulation detection
        # 25 Nisan 2026 olayi: Kayra, Deniz'in telefonundan "Deniz hasta ben Kayra"
        # diyerek bot'u kandirip Deniz'in sinav sonucunu aldi. Bir daha olmasin.
        identity_locked = False
        identity_reason = ""
        for msg in recent_msgs:
            if msg['message_role'] != 'user':
                continue
            cl = (msg['content'] or "").lower()
            # Pattern grup 1 — telefonu baskasina ait acikca soyleme
            if any(p in cl for p in [
                "telefonu bana verdi", "telefonu verdi", "telefonu aldim",
                "telefonu kullaniyorum", "telefonu bende",
                "telefon bana ait degil", "bu telefon onun",
                "ben aslinda", "ben aslında",
                "ben x degilim", "ben.*degil",
                "ben onun arkadasiyim", "ben arkadasiyim",
            ]):
                identity_locked = True
                identity_reason = "kullanici telefonun sahibinin baskasi olduğunu soyledi"
                break
            # Pattern grup 2 — hesap sahibi yok/hasta/gitti
            if any(p in cl for p in [
                "hasta", "hastalandi", "hastane",
                "gelemiyor", "yok artik", "burada degil",
                "iyilesti", "geri geldi", "kurtuldum",
                "olmus", "olmüş", "gitti geri gelmesine",
                "bir daha gelemeyecek", "bir daha donmeyecek",
            ]):
                # Bunlar yalnizca "X hasta" (3. sahis) seklinde gectiyse manipulation
                # Ogrenci kendi hakkinda "hastayim" diyebilir (bunu lock etme)
                if any(s in cl for s in [
                    " hasta", "x hasta", "deniz hasta", "ali hasta",
                    "telefonu", "arkadasiyim", "arkadasim", "verdi",
                    "iyilesti", "geri geldi", "kurtuldum",
                ]) and not (cl.startswith("hastayim") or cl.startswith("hasta oldum")):
                    identity_locked = True
                    identity_reason = "kullanici hesap sahibinin yokluğundan veya iyilesmesinden bahsetti"
                    break
            # Pattern grup 3 — kimlik degistirme manevrasi
            if "ben " in cl and any(p in cl for p in [
                " degilim", " değilim", " olmustum", " bilmiyorum kim oldugumu",
            ]):
                identity_locked = True
                identity_reason = "kullanici kimlik konusunda celiskili ifade kullandi"
                break

        # Konu çıkarımı — son mesajlardan
        last_topic = ""
        mood = "normal"
        for msg in recent_msgs:
            if msg['message_role'] == 'user':
                content_lower = msg['content'].lower()
                # Konu tespiti — Oturum 25.29 genisletildi (Mehmet bug)
                # ESKI: 7 ders, ~20 keyword. "ışık tanecik" yakalanmıyordu.
                # YENI: ~80 keyword, alt-konuları da yakalar.
                for konu, keywords in [
                    ("fizik", [
                        "fizik", "kuvvet", "newton", "hareket", "moment", "enerji",
                        "ışık", "isik", "foton", "dalga", "tanecik", "optik",
                        "manyet", "elektrik", "akım", "akim", "voltaj", "direnc", "direnç",
                        "kaldırma", "kaldirma", "basinç", "basınç", "akışkan", "akiskan",
                        "isı", "isi", "sıcaklık", "sicaklik", "termodinamik",
                        "atom", "kuantum", "rölativ", "relativ",
                    ]),
                    ("matematik", [
                        "matematik", "türev", "turev", "integral", "limit",
                        "denklem", "fonksiyon", "polinom", "logaritma", "üstel", "ustel",
                        "trigonometri", "sinüs", "sinus", "kosinüs", "kosinus",
                        "tanjant", "matris", "determinant", "olasılık", "olasilik",
                        "permutasyon", "kombinasyon", "dizi", "seri",
                        "asal", "bölünebilme", "bolunebilme",
                    ]),
                    ("kimya", [
                        "kimya", "mol", "element", "bileşik", "bilesik",
                        "asit", "baz", "tuz", "tepkime", "reaksiyon",
                        "atom", "elektron", "proton", "nötron", "notron",
                        "periyodik", "orbital", "izotop", "iyon",
                        "organik", "alkan", "alken", "alkin", "ester",
                    ]),
                    ("biyoloji", [
                        "biyoloji", "hücre", "hucre", "genetik", "mitoz", "mayoz",
                        "fotosentez", "solunum", "enzim", "protein", "dna", "rna",
                        "kromozom", "gen", "alel", "kalıtım", "kalitim",
                        "ekosistem", "tür", "sinir", "hormon", "endokrin",
                        "bitki", "hayvan", "evrim",
                    ]),
                    ("türkçe", [
                        "türkçe", "turkce", "paragraf", "anlam", "dil bilgisi", "dilbilgisi",
                        "noktalama", "yazım", "yazim", "ses", "sözcük", "sozcuk",
                        "cümle", "cumle", "fiil", "isim", "sıfat", "sifat", "zarf",
                    ]),
                    ("geometri", [
                        "geometri", "üçgen", "ucgen", "alan", "çevre", "cevre",
                        "kare", "dikdörtgen", "dikdortgen", "daire", "çember", "cember",
                        "açı", "aci", "kosüs", "kosus", "vektör", "vektor",
                        "analitik", "konik", "parabol", "elips",
                    ]),
                    ("tarih", [
                        "tarih", "osmanlı", "osmanli", "atatürk", "ataturk", "savaş", "savas",
                        "cumhuriyet", "kurtuluş", "kurtulus", "ilkçağ", "ilkcag",
                        "ortaçağ", "ortacag", "anadolu", "selçuk", "selcuk",
                        "fatih", "kanuni", "yavuz", "abdülhamit", "abdulhamit",
                    ]),
                    ("coğrafya", [
                        "coğrafya", "cografya", "iklim", "yağış", "yagis",
                        "nüfus", "nufus", "tarım", "tarim", "sanayi",
                        "akarsu", "göl", "gol", "deniz", "okyanus",
                        "kıta", "kita", "harita", "ölçek", "olcek",
                    ]),
                    ("felsefe", [
                        "felsefe", "ahlak", "siyaset", "bilgi", "varlık", "varlik",
                        "sokrates", "platon", "aristo", "kant", "nietzsche",
                    ]),
                    ("din", ["din kültürü", "din kulturu", "ibadet", "kuran", "hz."]),
                    ("ingilizce", ["ingilizce", "english", "tense", "grammar"]),
                ]:
                    if any(kw in content_lower for kw in keywords):
                        last_topic = konu
                        break

                # Duygu tespiti
                if any(w in content_lower for w in ["stres", "sıkıl", "yorul", "pes", "yapamı", "mutsuz", "kork"]):
                    mood = "stressed"
                elif any(w in content_lower for w in ["mutlu", "harika", "süper", "başardım", "güzel"]):
                    mood = "positive"

        # Özet oluştur
        summary_parts = []
        if exam and exam.get('toplam') is not None:
            summary_parts.append(f"Son deneme: {exam['exam_name'][:25]}, {exam['toplam']:.0f} net")
        elif exam:
            summary_parts.append(f"Son deneme: {exam['exam_name'][:25]} (net henuz yok)")
        if devam:
            summary_parts.append(f"Devamsızlık: {devam} saat")
        if last_topic:
            summary_parts.append(f"Son konu: {last_topic}")

        # Atlas #10: Son 14 gundeki konu hafizasi (tamamlanma degil, bahsedilen)
        recent_topics = []
        try:
            recent_topics = await get_recent_topics(soz_no, days=14, limit=8)
        except Exception:
            pass

        # 22.1n-fikir1: Aktif insight'lar (doğal sohbet çıkarımı, time-decay)
        active_insights = []
        try:
            from insight_extractor import get_active_insights
            active_insights = await get_active_insights(soz_no, limit=6)
        except Exception:
            pass

        # Oturum 25.13: Öğrenci günlük takip kompakt özeti — bot proaktif olabilsin
        # Öğrencinin web panelden girdiği bugünkü çalışma + açık to-do + mood
        daily_brief = None
        try:
            from student_daily import get_today_stats, get_todos, get_recent_notes
            # Oturum 25.29: include_test=False → admin test verileri ÇIKAR (bot
            # gerçek öğrenci verisi sanmasın). Öğrenci kendisi yazdıysa zaten
            # is_test=False (default), o veri görünmeye devam eder.
            stats_today, todos_open, notes_recent = await asyncio.gather(
                get_today_stats(soz_no, include_test=False),
                get_todos(soz_no, only_open=True, include_test=False),
                get_recent_notes(soz_no, days=2, include_test=False),
                return_exceptions=True,
            )
            if isinstance(stats_today, Exception): stats_today = {}
            if isinstance(todos_open, Exception): todos_open = []
            if isinstance(notes_recent, Exception): notes_recent = []

            today_mood = None
            today_note = None
            from datetime import date as _d
            for n in (notes_recent or []):
                if str(n.get("log_date")) == str(_d.today()):
                    today_mood = n.get("mood")
                    today_note = (n.get("note") or "")[:120]
                    break

            daily_brief = {
                "today_minutes": stats_today.get("total_minutes", 0) if isinstance(stats_today, dict) else 0,
                "today_questions": stats_today.get("questions_solved", 0) if isinstance(stats_today, dict) else 0,
                "today_ders_breakdown": stats_today.get("ders_breakdown", {}) if isinstance(stats_today, dict) else {},
                "open_todos_count": len(todos_open) if isinstance(todos_open, list) else 0,
                "open_todos_titles": [t.get("title", "") for t in (todos_open[:3] if isinstance(todos_open, list) else [])],
                "today_mood": today_mood,
                "today_note": today_note,
            }
        except Exception:
            pass

        # Oturum 24: son mesajin yasi (saat). Bot'un "bugun mu, dun mu konustuk"
        # ayrimi yapabilmesi icin prompt'a belirtilir.
        last_msg_age_h = None
        try:
            if recent_msgs:
                _latest_ts = recent_msgs[0].get('created_at')
                if _latest_ts:
                    last_msg_age_h = (datetime.now(_latest_ts.tzinfo) - _latest_ts).total_seconds() / 3600
        except Exception:
            last_msg_age_h = None

        # 25.40u — Bağlam kaybı fix: Son 3 ASSISTANT cevabının başlığı/özeti
        # Bot kendi yanıtlarını "az önce ne demiştim" diye unutuyordu (Neo 21:59
        # vakası — bot 4 dk önce listelediği 3 öneriyi tamamen unuttu).
        # Bu özet system prompt'a inject edilir → bot self-doubt yapmaz.
        recent_assistant_turns = []
        for msg in recent_msgs:
            if msg['message_role'] != 'assistant':
                continue
            cnt = (msg['content'] or "").strip()
            if not cnt or cnt.startswith('[tool_calls'):
                continue
            # İlk satır + ilk 200 char özet
            first_line = cnt.split('\n', 1)[0][:120]
            preview = cnt[:300].replace('\n', ' ')
            try:
                ts = msg['created_at']
                age_min = (datetime.now(ts.tzinfo) - ts).total_seconds() / 60
                age_str = f"{int(age_min)}dk önce" if age_min < 60 else f"{int(age_min/60)}sa önce"
            except Exception:
                age_str = ""
            recent_assistant_turns.append({
                "age": age_str,
                "title": first_line,
                "preview": preview,
            })
            if len(recent_assistant_turns) >= 3:
                break

        context = {
            "name": name,
            "class": profile.get('class_name', '?'),
            "soz_no": soz_no,
            "role": profile.get('role', 'ogrenci'),
            "last_topic": last_topic,
            "mood": mood,
            "recent_summary": ". ".join(summary_parts) if summary_parts else "",
            "weak_topics": weak_topics,       # top 5 zayıf konu
            "exam_trend": exam_trend,         # son 3 TYT deneme
            "ayt_last": ayt_last,             # son AYT deneme
            "recent_topics": recent_topics,   # Atlas #10 konu hafizasi (14 gun)
            "active_insights": active_insights,  # 22.1n-fikir1 doğal sohbet çıkarımı
            "daily_brief": daily_brief,       # Oturum 25.13: günlük panel özeti
            "session_messages": len([m for m in recent_msgs if m['message_role'] == 'user']),
            "last_active": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "last_msg_age_h": last_msg_age_h,  # Oturum 24: son mesajdan sonra gecen saat
            # Oturum 25.8 — KVKK identity lock (Deniz/Kayra olayi 25 Nisan)
            "identity_locked": identity_locked,
            "identity_reason": identity_reason,
            # 22.1n-neo: Foto context (Fatma bug fix) — varsa prompt'a eklenir
            "photo_ctx": get_photo_context(phone),
            # 25.40u — Bağlam kaybı fix: bot kendi son 3 cevabını hatırlasın
            "recent_assistant_turns": recent_assistant_turns,
            "_ts": time.time(),
        }

        _CONTEXT_CACHE[phone_clean] = context
        return context

    except Exception as e:
        logger.debug(f"Context cache hatası: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────
# 22.1n-neo: Foto soru context cache (Fatma case)
# Ogrenci foto gonderdiginde Vision cevabindan konu/ders/soru ozeti cikart,
# 30 dakika sakla — sonraki mesajda Claude'a inject et.
# ──────────────────────────────────────────────────────────────────────────
_PHOTO_CTX: dict[str, dict] = {}   # phone_clean → {ders, konu, ozet, ts}
_PHOTO_CTX_TTL = 1800              # 30 dakika


def set_photo_context(phone: str, vision_response: str) -> None:
    """Vision cevabindan ders/konu/ozet cikart, cache'e yaz.

    Vision template: '📝 *Soru Analizi* | Ders: X | Konu: Y | Zorluk: Z | ...'
    """
    phone_clean = (phone or "").replace("+", "").strip()
    if not phone_clean or not vision_response:
        return
    import re as _re
    ders = konu = ""
    m = _re.search(r"Ders:\s*([^|\n]+)", vision_response)
    if m: ders = m.group(1).strip()[:60]
    m = _re.search(r"Konu:\s*([^|\n]+)", vision_response)
    if m: konu = m.group(1).strip()[:80]
    # Son soru icerik ozeti — ilk 300 char (Verilenler/Cozum satirlari)
    ozet = vision_response[:800].strip()
    _PHOTO_CTX[phone_clean] = {
        "ders": ders, "konu": konu, "ozet": ozet, "ts": time.time(),
    }


def get_photo_context(phone: str) -> Optional[dict]:
    """Foto context varsa ve TTL icinde ise don, yoksa None."""
    phone_clean = (phone or "").replace("+", "").strip()
    ctx = _PHOTO_CTX.get(phone_clean)
    if not ctx:
        return None
    if time.time() - ctx.get("ts", 0) > _PHOTO_CTX_TTL:
        _PHOTO_CTX.pop(phone_clean, None)
        return None
    return ctx


def clear_photo_context(phone: str) -> None:
    """Ogrenci konu degistirdi/yeni foto gonderdi — cache temizle."""
    phone_clean = (phone or "").replace("+", "").strip()
    _PHOTO_CTX.pop(phone_clean, None)


def build_context_prompt(context: dict) -> str:
    """Context'i system prompt'a eklenecek string'e çevir."""
    if not context:
        return ""

    parts = ["\n\nÖĞRENCİ BAĞLAM BİLGİSİ (bu bilgileri doğrudan tool_call yapmadan kullan):"]

    # Oturum 25.8 — KVKK identity manipulation lock (en uste, Claude ilk goruyor)
    if context.get("identity_locked"):
        parts.append(
            "\n!!! KIMLIK MANIPULASYONU TESPIT EDILDI — SENSITIVE DATA LOCKED !!!\n"
            f"Sebep: {context.get('identity_reason','')}\n"
            "BU KONUSMADA YAPMAYACAKLARIN:\n"
            " • Sinav sonucu, net, deneme verisi VERME (ne hesap sahibinin ne baskasinin)\n"
            " • Devamsizlik, etut kaydi, ders programi VERME\n"
            " • Hesap sahibinin kisisel bilgisi VERME\n"
            "TEK YANIT KALIBI:\n"
            " 'Bu hesabin gercek sahibi olduguna emin olamiyorum, akademik veri\n"
            "  paylasamam. Kuruma ulasarak (+90 546 260 54 46) kimlik dogrulamasi\n"
            "  yaptirilabilir.'\n"
            "AKADEMIK KAVRAM aciklama serbest, sohbet serbest — sadece KISISEL VERI YOK.\n"
            "Kullanici 'tamam ben Xim', 'iyilestim', 'geri geldim' dese BILE LOCK KALKMIYOR.\n"
        )

    # Oturum 24: Temporal marker — bot'un "ne zaman konusmustuk" ayrimi
    age_h = context.get("last_msg_age_h")
    if age_h is not None:
        if age_h < 0.5:
            parts.append("Zaman: AKTIF oturum (son mesaj <30dk once) — ayni konusmanin devami")
        elif age_h < 3:
            parts.append(f"Zaman: GUNCEL oturum (son mesaj ~{age_h:.0f}sa once) — konusma devam ediyor")
        elif age_h < 24:
            parts.append(f"Zaman: BUGUN/DUN konusuldu (~{age_h:.0f}sa once) — hatirlatarak baglam kur")
        elif age_h < 72:
            gun = int(age_h / 24)
            parts.append(f"Zaman: {gun} GUN once konusuldu — 'gecen gunku konumuzdan devam edelim mi?' ile bagla")
        else:
            gun = int(age_h / 24)
            parts.append(f"Zaman: UZUN ARA ({gun} gun onceki konusma) — yeni baslangic gibi davran, eski konulari zorlamadan an")

    if context.get("recent_summary"):
        parts.append(f"Durum: {context['recent_summary']}")

    # 25.40u — Bağlam kaybı fix: Bot kendi son cevaplarını hatırlasın
    # Cerebras/Claude self-doubt yapmasın, "az önce ne demiştim" sorusuna
    # tekrar tool çağırmasın, kendi yanıtlarını sorgulamasın.
    rat = context.get("recent_assistant_turns") or []
    if rat:
        lines = ["\n🔁 SEN AZ ÖNCE BUNLARI YAZDIN (kendini hatırla, sorgulama):"]
        for i, t in enumerate(rat, 1):
            age = f"({t['age']}) " if t.get('age') else ""
            lines.append(f"  {i}. {age}{t['title']}")
        lines.append(
            "⚠ Kullanıcı 'az önce konuştuğumuz X' veya 'şu öneriyi açıkla' derse, "
            "yukarıdaki SENİN cevaplarına BAK. 'Hangi X?' deme, 'paylaşmadın' deme. "
            "Kullanıcı 'yanlış' derse SADECE şu an söylediğine bak — eski doğru "
            "cevaplarını da kendinden reddetme."
        )
        parts.append("\n".join(lines))

    # Zayıf konular — Claude bunu bilince "zayıf konularım ne" sorusuna direkt cevap verir
    weak = context.get("weak_topics", [])
    if weak:
        topic_lines = []
        for t in weak:
            topic_lines.append(f"  - {t['ders']}: {t['konu']} (hata %{t['hata_pct']})")
        parts.append("En zayıf konular:\n" + "\n".join(topic_lines))

    # Son 3 deneme trendi — "son denemelerim nasıl" sorusuna direkt cevap
    trend = context.get("exam_trend", [])
    if trend:
        trend_lines = []
        for t in trend:
            trend_lines.append(f"  - {t['date']}: {t['name']} → {t['net']} net")
        parts.append("Son TYT denemeleri:\n" + "\n".join(trend_lines))
        # Trend yönü
        if len(trend) >= 2:
            diff = trend[0]['net'] - trend[1]['net']
            if diff > 3:
                parts.append(f"→ Son denemede +{diff:.0f} net ARTIŞ var, tebrik et!")
            elif diff < -3:
                parts.append(f"→ Son denemede {diff:.0f} net düşüş var, destekleyici ol")

    # AYT bilgisi (birlestir analiz — resmi puan)
    ayt = context.get("ayt_last")
    if ayt:
        parts.append(
            f"AYT Birlestir: Ham {ayt.get('ham','?')} | Yerlesme {ayt.get('yerlesme','?')} "
            f"({ayt.get('katilim','?')} sinav). "
            f"Ders netleri icin get_ayt_analysis tool'unu cagir — student_exams [AYT]% YASAK."
        )

    if context.get("last_topic"):
        parts.append(f"Son konuştukları konu: {context['last_topic']} — devam ediyorsa bağlamı koru")

    # Oturum 25.13: Öğrenci günlük takip paneli özeti (PROAKTİF kullanım için)
    db = context.get("daily_brief")
    if db:
        d_lines = []
        if db.get("today_minutes") or db.get("today_questions"):
            mins = db.get("today_minutes", 0)
            qs = db.get("today_questions", 0)
            ders_bd = db.get("today_ders_breakdown") or {}
            ders_str = ""
            if ders_bd:
                top_d = sorted(ders_bd.items(), key=lambda x: -x[1])[:3]
                ders_str = " (" + ", ".join(f"{k}:{v}dk" for k, v in top_d) + ")"
            d_lines.append(f"  📊 Bugün panele girdi: {mins}dk + {qs} soru{ders_str}")
        if db.get("open_todos_count"):
            cnt = db["open_todos_count"]
            titles = db.get("open_todos_titles") or []
            t_str = ", ".join(t[:30] for t in titles[:2])
            d_lines.append(f"  ✅ Açık to-do: {cnt} tane ({t_str})")
        if db.get("today_mood"):
            d_lines.append(f"  💭 Bugünkü mood: {db['today_mood']}")
        if db.get("today_note"):
            d_lines.append(f"  📝 Bugünkü not: \"{db['today_note']}\"")
        if d_lines:
            parts.append(
                "Öğrencinin Çalışmam panelinden BUGÜNKÜ veriler (proaktif kullan!):\n" +
                "\n".join(d_lines) +
                "\nKurallar:\n"
                "  • Plan/öneri yaparken bu veriyi REFERANS al — 'bugün 30dk Mat çalıştın'\n"
                "  • Yeni öneri panele eklenebilir → 'şunu programına ekleyeyim mi?' sor\n"
                "  • Mood 'yorgun/stresli' iken ağır plan yapma, 'verimli' iken ileri sür\n"
                "  • Hiç giriş yoksa SORGULAMA — empati: 'paneli kullanmak ister misin?'"
            )

    # Atlas #10: son 14 gunde bahsedilen konular (hafiza, tamamlanma DEGIL)
    recent_topics = context.get("recent_topics", [])
    if recent_topics:
        lines = []
        for t in recent_topics[:5]:
            lines.append(f"  - {t['when']}: {t['ders']} / {t['konu']}")
        parts.append(
            "Son 14 günde konuştuğu konular (hafıza — tamamlandı değil):\n" + "\n".join(lines) +
            "\nÖğrenci aynı konuyu tekrar sorarsa: 'Geçen sefer X'i gördük, nasıl gidiyor?' diye bağlam kur."
        )

    # 22.1n-fikir1: Doğal sohbet çıkarımları (time-decay'li)
    active_insights = context.get("active_insights", [])
    if active_insights:
        lines = []
        for ins in active_insights[:6]:
            conf_str = "güçlü" if ins["guven"] > 0.7 else ("orta" if ins["guven"] > 0.5 else "hafif")
            lines.append(f"  - [{ins['tip']}] {ins['icerik']} ({conf_str}, {ins['son_gorulme']})")
        parts.append(
            "Öğrenci hakkında sohbetlerden çıkardığım sezgiler (uçucu — değişebilir, zorlama):\n" +
            "\n".join(lines) +
            "\n⚠️ Bu bilgileri ASLA doğrudan ifşa etme ('sen stresli ve ITÜ'den vazgeçiyorsun' DEME!). "
            "Sadece doğal olarak bağlam kur: öğrenci mutsuzsa empati, hedef değişmişse 'son konuştuklarımızdan sonra aklında değişen bir şey var mı?' gibi ima."
        )

    if context.get("mood") == "stressed":
        parts.append("DİKKAT: Öğrenci stresli/mutsuz görünüyor — empatik ve destekleyici ol")
    elif context.get("mood") == "positive":
        parts.append("Öğrenci pozitif modda — enerjiyi koru, motive et")

    if context.get("session_messages", 0) > 3:
        parts.append(f"Bu oturumda {context['session_messages']} mesaj yazılmış — tanışıklık var, samimi ol")

    # 22.1n-neo: Foto soru context (Fatma bug fix)
    # Ogrenci foto gonderdiyse son 30 dk icinde, devam sorusu gelirse context koru
    photo_ctx = context.get("photo_ctx")
    if photo_ctx:
        ds = photo_ctx.get("ders", "?")
        kn = photo_ctx.get("konu", "?")
        parts.append(
            f"\n📸 SON FOTO SORU BAGLAMI (son 30 dk — devam sorusu gelirse bu soruya dair):\n"
            f"Ders: {ds} | Konu: {kn}\n"
            f"Vision cikti ozeti:\n{photo_ctx.get('ozet','')[:500]}\n"
            f"→ Ogrenci 'o formul neden', 'o noktada ne oldu', 'tekrar anlat' gibi follow-up "
            f"sorarsa ASLA 'baglam eksik' deme — yukaridaki fotolu sorunun devami olarak cevapla."
        )

    parts.append("\nÖNEMLİ: Yukarıdaki bilgiler cache'den geliyor. Öğrenci basit bir veri sorusu soruyorsa (zayıf konularım, son denemem, devamsızlık) bu bilgileri doğrudan kullan, tool_call YAPMA. Sadece detaylı analiz/karşılaştırma gerekiyorsa tool_call kullan.")

    return "\n".join(parts)


def update_topic(phone: str, topic: str):
    """Aktif konuyu güncelle."""
    phone_clean = phone.replace("+", "")
    if phone_clean in _CONTEXT_CACHE:
        _CONTEXT_CACHE[phone_clean]["last_topic"] = topic
        _CONTEXT_CACHE[phone_clean]["_ts"] = time.time()


async def log_topic_discussed(soz_no: int, ders: str, konu: str, source: str = "chat") -> None:
    """
    Atlas #10 fix: konu hafizasi (her zaman yazilir, tamamlanma ayri).

    Ogrenci bir konudan bahsettiginde/cozdugunde/sorusunu sordugunda buraya yazilir.
    Bu KONU HAFIZASI — tamamlandi DEGIL. Ogrenci ayni konuyu tekrar sordugunda:
    "Gecen sefer X konusunu gormustuk" diyebilmek icin.

    Tamamlandi icin ayri: student_topic_tracker.tamamlandi=TRUE (ogrenci teyidi +
    ogretmen onayi).
    """
    if not soz_no or not konu:
        return
    # 22.1n-neo: Merkezi student_signals.log_student_signal uzerinden
    try:
        from student_signals import log_student_signal
        content = f"{(ders or '').strip()}|{konu.strip()}|source={source}"
        await log_student_signal(
            int(soz_no), "konu_konusuldu", content,
            confidence=0.8, source=source or "conversation_memory"
        )
    except Exception as e:
        logger.debug(f"log_topic_discussed error: {e}")


async def get_recent_topics(soz_no: int, days: int = 14, limit: int = 10) -> list:
    """Son N günde bahsedilen konu listesi (Atlas #10 konu hafizasi)."""
    if not soz_no:
        return []
    try:
        rows = await _fetch(
            f"""SELECT content, created_at
                FROM student_insights
                WHERE soz_no = $1 AND insight_type = 'konu_konusuldu'
                  AND created_at > NOW() - INTERVAL '{int(days)} days'
                ORDER BY created_at DESC LIMIT {int(limit)}""",
            int(soz_no),
        )
        topics = []
        seen = set()
        for r in rows:
            parts = (r["content"] or "").split("|")
            if len(parts) >= 2:
                ders, konu = parts[0].strip(), parts[1].strip()
                key = f"{ders}/{konu}".lower()
                if key in seen:
                    continue
                seen.add(key)
                topics.append({
                    "ders": ders,
                    "konu": konu,
                    "when": r["created_at"].strftime("%d.%m") if r.get("created_at") else "",
                })
        return topics
    except Exception as e:
        logger.debug(f"get_recent_topics error: {e}")
        return []


def update_mood(phone: str, mood: str):
    """Duygu durumunu güncelle."""
    phone_clean = phone.replace("+", "")
    if phone_clean in _CONTEXT_CACHE:
        _CONTEXT_CACHE[phone_clean]["mood"] = mood
        _CONTEXT_CACHE[phone_clean]["_ts"] = time.time()


# ── Bug fix 23 Nisan: Son bot cevabı getter (context bridge için) ─────────

async def get_recent_user_questions(phone: str, count: int = 3, max_age_minutes: int = 15) -> list[dict]:
    """Son N user mesajını ve tahmin edilen TOPIK'ini dön.

    25.43-INT-FIX3 (Neo bug 9 May 20:11-20:12): Neo "Eyotek bağlantısı" sordu,
    bot HuggingFace cevap verdi. Sonra bot tool sonucunu farklı konuya çevirdi.

    Çözüm: Bot cevap üretmeden önce son user mesajını + TOPIK'ini check etmeli.
    Tool sonucu farklı konudaysa kullanıcıya açıkça bildir.

    Returns:
        [
          {"content": "Eyotek bağlı mıyız", "topic_keywords": ["eyotek", "baglanti"],
           "minutes_ago": 0.5},
          ...
        ]
    """
    phone_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
    # Topic keyword extraction — basit but işe yarar
    TOPIC_MAP = {
        "eyotek": ["eyotek", "eyoteğe", "eyotekte", "lms"],
        "huggingface": ["huggingface", "hugging face", "hf", "model arama"],
        "openmeteo": ["meteo", "iklim", "hava durumu", "yagis", "sicaklik"],
        "tdk": ["tdk", "kelime anlam", "deyim"],
        "nist": ["nist", "fizik sabit", "planck", "boltzmann"],
        "oeis": ["oeis", "fibonacci", "sayi dizisi", "asal"],
        "wikidata": ["wikidata", "yapilandirilmis"],
        "cern": ["cern", "lhc", "higgs"],
        "tuik": ["tuik", "turkiye istatistik", "nufus"],
        "alphafold": ["alphafold", "protein", "uniprot"],
        "render": ["render", "grafik", "chart", "gorsel"],
        "system": ["sistem", "guncelleme", "atlas", "blueprint", "kalditim"],
        "ogrenci": ["ogrenci", "ogr no", "soz no", "deneme", "net"],
    }
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            """
            SELECT content, created_at
            FROM fermat.agent_conversations
            WHERE REPLACE(phone,'+','') = $1
              AND message_role = 'user'
              AND created_at > NOW() - make_interval(mins => $2)
            ORDER BY created_at DESC
            LIMIT $3
            """,
            phone_clean, max_age_minutes, count,
        )
        out = []
        from datetime import datetime
        now = datetime.now()
        for row in (rows or []):
            content = (row.get("content") or "").strip()
            content_low = content.lower()
            topics = []
            for tkey, kws in TOPIC_MAP.items():
                if any(kw in content_low for kw in kws):
                    topics.append(tkey)
            created = row.get("created_at")
            mins_ago = 0
            if created:
                try:
                    mins_ago = (now - created).total_seconds() / 60
                except Exception:
                    pass
            out.append({
                "content": content[:300],
                "topic_keywords": topics,
                "minutes_ago": round(mins_ago, 1),
            })
        return out
    except Exception:
        return []


async def get_last_bot_response(phone: str, max_age_minutes: int = 10) -> Optional[dict]:
    """Son bot cevabını dön — kısa/belirsiz user mesajlarının bağlamı için.

    Enes vakası: "oyun kodlamamız lazım" → bot reddetti → "yazar mısın" →
    bot onboarding menüsü gönderdi (context kaybı). Bu fonksiyon fast_response'a
    son bot cevabının özünü verir → kısa follow-up'ta Claude'a yükselt.

    Returns:
        {
            'content': son bot cevabı (ilk 300 char),
            'tools': kullanılan tool'lar,
            'minutes_ago': kaç dakika önce,
            'is_question': bot cevabı soru soruyor mu,
            'is_reject': bot "kapsam dışı / yapamam" dedi mi,
            'is_offer': bot teklif sunmuş mu ("... yapayım mı?"),
        }
        None → son 10dk'da bot cevabı yok
    """
    phone_clean = phone.replace("+", "").replace(" ", "").replace("-", "")
    try:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            """
            SELECT content, tools_used, created_at
            FROM fermat.agent_conversations
            WHERE REPLACE(phone,'+','') = $1
              AND message_role = 'assistant'
              AND COALESCE(session_id,'') NOT LIKE '_test_%'
              AND created_at > NOW() - make_interval(mins => $2)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            phone_clean, max_age_minutes,
        )
        if not row:
            return None
        # Oturum 23 (Neo UX): 500→1500 char. Bot son yanıtının SONUNU görmesi
        # "is_question" ve "is_offer" kontrolü için kritik — 500 char bazen
        # sadece ortayı içeriyordu, bot kendi sorduğu soruyu göremiyordu.
        content = (row.get("content") or "")[:1500]
        content_lower = content.lower()
        from datetime import datetime
        created_at = row.get("created_at")
        minutes_ago = 0
        if created_at:
            try:
                minutes_ago = (datetime.now() - created_at).total_seconds() / 60
            except Exception:
                pass
        return {
            "content": content[:1200],  # önceden 300'dü — uzun cevabın kapanışını göster
            "tools": row.get("tools_used") or [],
            "minutes_ago": round(minutes_ago, 1),
            "is_question": "?" in content[-400:],  # önceden 120'ydi — son paragrafı kapsayıcı
            "is_reject": any(k in content_lower for k in [
                "kapsam dışı", "kapsam disi", "yapamam", "yardım edemem",
                "izin verilmiyor", "yetki yok", "bunu yapamayacağım",
            ]),
            "is_offer": bool(
                content.rstrip().endswith(("mı?", "mi?", "mu?", "mü?", "musun?", "misin?", "mıyım?"))
                or "ister misin" in content_lower
                or "bakalım mı" in content_lower
            ),
        }
    except Exception as e:
        return None


def is_short_ambiguous(message: str) -> bool:
    """Mesaj kısa ve bağlam gerektiren belirsiz bir takip sorusu mu?

    Örnek: "yazar mısın", "evet", "olur", "tamam", "peki", "ya", "bak", "öyle mi"

    25.41 (Neo bug 5 May 23:40): "bu/şu/o" referans zamiri ile başlayan kısa
    mesajlar EKLENDİ (Neo "bu problemi düzeltmiştik" → bot "yeni konuşma
    başladı" dedi). 50 char threshold + referans zamiri pattern'ı.
    """
    if not message:
        return False
    msg = message.strip().lower()
    import re

    # Kısa belirsiz mesajlar (25 char altı)
    if len(msg) <= 25:
        _short_ambiguous_patterns = [
            r"^(evet|olur|tamam|ok|peki|hadi|anladım|anladim|öyle|oyle|tabii|elbette)[.!?\s]*$",
            r"^yazar\s*m[iı]s[iı]n[.!?\s]*$",
            r"^(ne|nasıl|nası|nasıl\s*olur|neyi|nereyi)[.!?\s]*$",
            r"^(ya|bak|hmm|yani|o\s*zaman)[.!?\s]*$",
            r"^(devam|continue|go)[.!?\s]*$",
            r"^(daha|başka|baska|farklı)[.!?\s]*$",
        ]
        for pat in _short_ambiguous_patterns:
            if re.match(pat, msg):
                return True

    # 25.41 Neo bug fix: "bu/şu/o + dediğin/önerin/sıkıntı..." referans mesajı
    # 50 char altında ise muhtemelen son cevaba refer ediyor → Claude bağlam okusun
    if len(msg) <= 50:
        _reference_patterns = [
            r"^(bu|şu|o|onu|bunu|şunu)\s+(dediğin|dedigin|söylediğin|soyledigin|"
            r"önerdiğin|onerdigin|bahsettiğin|bahsettigin|gösterdiğin|gosterdigin|"
            r"problem|sorun|sıkıntı|sikinti|öneri|oneri|durum|konu|şey|sey|cevap)",
            r"^(bunu|şunu|onu)\s+(yap|söyle|soyle|göster|goster|aç|ac|kapat|sil|ekle)",
        ]
        for pat in _reference_patterns:
            if re.search(pat, msg):
                return True

    return False


# 25.49 (konuşma analizi — Yağız "teker teker özetler misin" vakası +
# quality_analyzer baglam_kaybi=1): önceki cevabı YENİDEN BİÇİMLENDİR/DETAYLANDIR
# isteyen takip soruları query_cache'te semantik eşleşip GENERIC TEKRAR üretiyordu
# (Yağız 5 turda neredeyse aynı sindirim özetini aldı). Bunlar önceki cevap bağlamı
# OLMADAN doğru cevaplanamaz → cache ATLA + Claude bağlamla cevaplasın.
_REFINEMENT_PATTERNS = [
    r"\b(teker teker|tek tek|madde madde|ayrı ayrı|ayri ayri|birer birer|tek tek tek)\b",
    r"\b(daha detaylı|daha detayli|detaylandır|detaylandir|biraz daha (aç|ac|uzat)|daha uzun)\b",
    r"\b(daha kısa|daha kisa|kısalt|kisalt|daha öz|daha sade)\b",
    r"\b(tekrar (anlat|yaz|söyle|soyle|göster|goster|et)|bir daha (anlat|yaz|göster|goster))\b",
    r"^(sadece|yalnızca|yalnizca)\s+\w+.{0,40}(anlat|özet|ozet|yaz|göster|goster|ver)",
    r"\b(şema|sema|tablo|grafik|görsel|gorsel)\s*(olarak|halinde|şeklinde|seklinde|(ile )?(göster|goster)|çiz|ciz)",
]


def is_refinement_request(message: str) -> bool:
    """Mesaj, önceki bot cevabını yeniden biçimlendir/detaylandır isteyen takip mı?

    Örnek: "teker teker özetler misin", "daha detaylı anlat", "şema olarak göster",
    "sadece sindirim sistemini özetle", "tekrar anlat".

    Bu ifadeler tek başına anlamsız — önceki cevaba refer ederler. Caller, recent
    bot cevabı (son ~15dk) varsa cache'i atlayıp Claude'a yönlendirmeli.
    """
    if not message:
        return False
    import re
    msg = message.strip().lower()
    if len(msg) > 70:
        return False
    return any(re.search(p, msg) for p in _REFINEMENT_PATTERNS)


# ════════════════════════════════════════════════════════════════════════
# 25.40j (Neo direktif) — UZUN KONUŞMA RECAP
#
# Ada (905456592707) 30+ mesaj attı, her cevapta history büyüdü, prompt
# token'ı şişti, ileride memory truncation yapılırsa kalp özet kaybolurdu.
# Çözüm: 30+ mesaj olunca Cerebras 70B ile "kalp özeti" üret, eski mesajları
# sil + recap'i system prompt'a inject et. Maliyet: ~$0.001 / her 30 mesajda.
# ════════════════════════════════════════════════════════════════════════

# Mesaj sayısı eşikleri
RECAP_THRESHOLD = 30      # Bu sayıda VEYA üstünde mesaj varsa recap üret
RECAP_KEEP_RECENT = 12    # Recap sonrası raw tutulacak son N mesaj
RECAP_PROMPT = """Asagidaki ogrenci-bot konusmasinin "kalp ozetini" 3-4 kisa cumlede yaz.
Hedef: Ileride bot bu ozeti okuyunca KIM ile NE konustugumu, hangi DUYGU/PROBLEM/HEDEF paylasildi, hangi ONEMLI ISIMLER/OLAYLAR gecti hatirlamali.
ASLA sayisal veri uydurma; sadece konusmada GECEN seyleri yaz.

KONUSMA ({turn_count} mesaj):
{transcript}

OZET (sadece duz metin, 3-4 cumle):"""


async def maybe_summarize_history(history: list, threshold: int = RECAP_THRESHOLD,
                                   keep_recent: int = RECAP_KEEP_RECENT) -> tuple[str, list]:
    """
    History uzunsa Cerebras ile özet üret + son N mesajı koru.
    Eşik altındaysa (recap, history) = ("", history) — değişiklik yok.

    Returns:
        (recap_text: str, new_history: list)
        recap_text boş ise işlem yapılmadı, history aynen kalır.
    """
    if not history or len(history) < threshold:
        return "", history

    # Eski mesajlar (özetlenecek) + yeni (raw)
    old_msgs = history[:-keep_recent] if len(history) > keep_recent else history
    recent_msgs = history[-keep_recent:] if len(history) > keep_recent else []

    # Transcript hazırla — content çok uzun olabilir, kırp
    lines = []
    for i, m in enumerate(old_msgs):
        role = "Ogr" if m.get("role") == "user" else "Bot"
        c = m.get("content", "")
        # content sadece string olmalı (Anthropic block listesi olabilir)
        if isinstance(c, list):
            # tool_use/tool_result blokları — atla
            text_parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
            c = " ".join(text_parts)
        if not isinstance(c, str):
            c = str(c)
        c = c[:300]  # Her mesaj max 300 char (bütün özet 8k içinde kalsın)
        lines.append(f"[{i}] {role}: {c}")
    transcript = "\n".join(lines)
    if len(transcript) > 8000:
        transcript = transcript[:8000] + "\n[...truncated]"

    prompt = RECAP_PROMPT.format(turn_count=len(old_msgs), transcript=transcript)

    try:
        # Cerebras-first (ucuz + hızlı), Groq fallback
        try:
            from cerebras_handler import CerebrasClient
            client = CerebrasClient()
            result = await client.complete_async(
                messages=[{"role": "user", "content": prompt}],
                system="Sen FermatAI hafiza ozetleyicisisin. Kisa ve net Turkce yaz.",
                model="gpt-oss-120b",
                max_tokens=300,
                temperature=0.2,
            )
        except Exception:
            from groq_handler import GroqClient
            client = GroqClient()
            result = await client.complete(
                messages=[{"role": "user", "content": prompt}],
                system="Sen FermatAI hafiza ozetleyicisisin. Kisa ve net Turkce yaz.",
                max_tokens=300,
                temperature=0.2,
            )
        recap = (result.get("text") or "").strip()
    except Exception as e:
        logger.warning(f"[RECAP] Hata: {e} — history aynen tutuldu")
        return "", history

    if not recap or len(recap) < 30:
        logger.warning(f"[RECAP] Cerebras bos/cok kisa cevap dondu, history aynen tutuldu")
        return "", history

    # Yeni history: synthetic user→assistant pair (recap as injected memory) + son raw
    # Anthropic API role-alternation gerektiriyor: user → assistant → user → assistant
    new_history = [
        {"role": "user", "content": f"[OTURUM OZETI — onceki {len(old_msgs)} mesaj kalp ozeti]\n{recap}"},
        {"role": "assistant", "content": "Anladim, ozeti kaydettim. Devam ediyorum."},
    ] + recent_msgs

    logger.info(f"[RECAP] {len(old_msgs)} mesaj ozetlendi → {len(recap)} char recap, "
                f"history {len(history)}→{len(new_history)} mesaj")
    return recap, new_history


# ════════════════════════════════════════════════════════════════════════
# 25.40j (Neo direktif) — TONAL TEKRAR FILTER
#
# Ada vakasi: bot 5 ust uste "Merhaba *Ada*!" ile basladi (robotik).
# Yagiz vakasi: 12 ust uste "Merhaba *Yagiz*!" tekrari.
# Prompt kuralı (DOGAL KONUSMA AKISI) eklendi (commit d184862) ama
# Claude/Cerebras prompt'a uymayabilir → POST-PROCESS yedek katman.
#
# Mantik:
#   - Bu cevap "Merhaba/Selam/Hey {ad}" ile basliyor MU?
#   - Son 2-3 bot cevabi DA hitap ile basladi MI?
#   - Evet+evet → prefix'i temizle, dogal akisa don
# ════════════════════════════════════════════════════════════════════════

import re as _re_filter

_GREETING_PREFIX_RE = _re_filter.compile(
    r'^(Merhaba|Selam|Selamlar|Hey|Ho[sş]geldin|Ho[sş]\s*geldin|Naber|Nas[iı]ls[iı]n)'
    r'(\s+[\*_]*[A-ZÇĞİÖŞÜa-zçğıöşü\.]{2,30}[\*_]*)?'
    r'[!?.,\s]*',
    _re_filter.IGNORECASE
)


def strip_redundant_greeting(response: str, history: list, max_lookback: int = 6) -> str:
    """
    Bot cevabi 'Merhaba {name}' ile basliyor + son 2 bot cevabi DA boyleyse
    prefix'i sil, dogal akisa donder.

    Args:
        response: Yeni bot cevabi (henuz history'ye eklenmemis)
        history: agent.history (son N mesaj)
        max_lookback: Son kac mesaja bakilir (default 6 = son 3 turn)

    Returns:
        Temizlenmis cevap (veya degismeden orijinal)
    """
    if not response or len(response) < 10:
        return response

    response_strip = response.lstrip()

    # Bu cevap hitap ile basliyor mu?
    m = _GREETING_PREFIX_RE.match(response_strip)
    if not m:
        return response

    # History'den son bot cevaplarini al (max_lookback mesaj icinde)
    bot_msgs = []
    for msg in reversed(history[-max_lookback:] if history else []):
        if msg.get("role") == "assistant":
            c = msg.get("content", "")
            if isinstance(c, list):
                # tool_use bloklari skip
                text_parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                c = " ".join(text_parts)
            if isinstance(c, str) and c.strip():
                bot_msgs.append(c.strip())
            if len(bot_msgs) >= 3:
                break

    if len(bot_msgs) < 2:
        # Cok az gecmis var — bu ilk veya 2. cevap olabilir, hitap KORUNUR
        return response

    # Son 2 bot cevabi da hitap ile basliyor mu?
    has_greeting_count = sum(
        1 for c in bot_msgs[:2]
        if _GREETING_PREFIX_RE.match(c)
    )

    if has_greeting_count < 2:
        # En az son 2'si hitapla baslamadi — bu cevap da OK kalsin
        return response

    # 3 ust uste hitap → bu cevabin prefix'i silinecek
    # Match end konum:
    end = m.end()
    cleaned = response_strip[end:].lstrip()
    if not cleaned or len(cleaned) < 5:
        return response  # Cleanlemek cok az text birakir, sakın

    # Ilk karakter kucuk harf ise buyut (turkce destekli)
    if cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

    logger.debug(f"[TONAL_FILTER] Hitap prefix temizlendi (son 2 cevap zaten hitap ile basliyordu)")
    return cleaned
