"""
Conversation Drift — Classroom Management Çekirdek #2
=======================================================
Neo vizyonu:
  "40 dk'lık dersin girişinde öğretmen sohbet eder, 30. dakikada içeriğe
   geçer — sanki hala karşılıklı sohbet ediyoruz gibi hissettirerek.
   Classroom management dersi almış bir yapı."

Bu modül son N mesajı sınıflandırır:
  - AKADEMIK     — ders/konu/soru/çözüm
  - PEDAGOJIK    — plan/hedef/motivasyon/gelişim
  - KISISEL      — nasılsın/hava/arkadaş/aile (sağlıklı ısınma)
  - OFF_TOPIC    — oyun/film/dizi/meme/rakip uygulama

DRIFT SINYALI mantığı:
  - Son 5 mesajın 3+ off_topic → REDIRECT ÖNER (yumuşak)
  - Son 3 ardışık off_topic → REDIRECT ZORUNLU (öğretmen devreye)
  - 2 mesajda akademik + 1 kişisel → sağlıklı karışım, dokunma
  - İlk 2 mesajda off_topic → tolere et (giriş ısınması)

REDIRECT YAPMA:
  - Bu modül karar verir, redirect_templates.py mesajı seçer.
  - Claude system prompt'a "drift sinyali var" notu enjekte edilir.
  - Aşırı sık redirect yasak: aynı oturumda 10 mesajda max 2.
"""
from __future__ import annotations
import re
from typing import Optional
from loguru import logger


# ── Kategori Pattern'ları ────────────────────────────────────────────────────

# Regex stratejisi: kelime başı \b (TR'de güvenli), SON serbest (eklere tolerans).
# ör. "matem" + \w* → "matematik", "matematiği", "matemi" hepsi yakalanır.

_AKADEMIK_PATTERNS = [
    r"\b(ders|konu|soru|cozum|çözüm|formul|formül|kural|teorem|ispat)\w*",
    r"\b(turev|türev|integral|limit|fonksiyon|denklem|matrix|matris)\w*",
    r"\b(fizik|kimya|biyolog|matematik|matem\b|geometri|edebiyat|tarih|turkce|türkçe|coğraf|cografya)\w*",
    r"\b(çöz|acikla|açıkla|anlat|ogret|öğret|nedir|ne\s*demek|paragraf)\w*",
    r"\bnet(ler|im|lerim|\b)",  # net, neti, netim, netlerim (netflix DEĞİL)
    r"\b(puan|deneme|sinav|sınav|tyt|ayt|yks|lgs)\w*",
    r"\b(analiz|karne|sonuc|sonuç)\w*",
    r"\b(kaldirma|kuvvet|enerji|hiz|manyetik|elektrik|optik)\w*",
    r"\b(atom|molekul|molekül|asit|baz|reaksiyon|tepkim)\w*",
    r"\b(hucre|hücre|dna|protein|genetik|evrim|fotosentez)\w*",
]

_PEDAGOJIK_PATTERNS = [
    r"\b(hedef|plan|program|haftal|gunluk|günlük)\w*",
    r"\bçalı[şs]m\w*",  # calisma/çalışma/calismak
    r"\b(motivasyon|moral|odaklan|disiplin)\w*",
    r"\b(strateji|yöntem|teknik|pomodoro|tekrar|ogrenme|öğrenme)\w*",
    r"\b(zayif\s*konu|guclu|güçlü|gelişim|ilerl|basar|başar)\w*",
    r"\b(rehberlik|gorusme|görüşme)\w*",
    r"\b(universite|bolum|bölüm|tercih|meslek|kariyer)\w*",
]

_KISISEL_PATTERNS = [
    r"\b(nasilsin|nasılsın|ne\s*haber|iyi\s*misin|keyifler)\w*",
    r"\b(aile|anne|baba|karde|arkada)\w*",
    r"\b(hava|sicak|soguk|yagmur|güneş|kar)\w*",
    r"\b(uyku|yemek|kahvalti|aksam|gece|sabah)\w*",
    r"\b(stres|yorgun|mutlu|uzgun|üzgün|sikkin|sıkkın)\w*",
    r"\b(tatil|hafta\s*sonu|dogum\s*gun)\w*",
]

_OFF_TOPIC_PATTERNS = [
    # Oyun / eglence
    r"\b(oyun|pes|fifa|counter|minecraft|roblox|valorant|league)\w*",
    r"\bcs\b|\blol\b",  # kısa kelimeler
    r"\b(dizi|film|netflix|disney|spotify|youtube|tiktok|instagram)\w*",
    r"\b(futbol|basketbol|derbi|mesut|icardi|messi|ronaldo|madrid|galatasaray|fenerbahce|besiktas)\w*",
    r"\bma[çc]\w*",  # maç, maçı, maçlar
    # Rakip AI / platform
    r"\b(chatgpt|gpt|gemini|copilot|midjourney)\w*",
    r"\bclaude\s*ai\b",
    # Meme / saçma
    r"\b(hahah|kek|troll|meme|cringe)\w*",
    # Çok genel / boş
    r"\b(asdf|qwerty|lorem|test\s*mesaj)\w*",
]


def classify_message(text: str) -> str:
    """Tek bir mesajı sınıflandır.

    Returns: 'akademik' | 'pedagojik' | 'kisisel' | 'off_topic' | 'belirsiz'
    """
    if not text:
        return "belirsiz"
    msg = text.lower()

    # Her kategori için sayım (en güçlü kazanır)
    counts = {
        "akademik": sum(1 for p in _AKADEMIK_PATTERNS if re.search(p, msg)),
        "pedagojik": sum(1 for p in _PEDAGOJIK_PATTERNS if re.search(p, msg)),
        "kisisel": sum(1 for p in _KISISEL_PATTERNS if re.search(p, msg)),
        "off_topic": sum(1 for p in _OFF_TOPIC_PATTERNS if re.search(p, msg)),
    }

    max_cat = max(counts, key=counts.get)
    if counts[max_cat] == 0:
        # Hiç eşleşme yok — uzunluğa göre varsayılan
        if len(msg.strip()) < 20:
            return "kisisel"  # kısa mesaj muhtemelen sohbet
        return "belirsiz"
    return max_cat


async def get_recent_history(phone: str, limit: int = 5) -> list[dict]:
    """Öğrencinin son N user mesajını DB'den çek."""
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            """
            SELECT content, created_at
            FROM fermat.agent_conversations
            WHERE phone = $1
              AND message_role = 'user'
              AND COALESCE(session_id,'') NOT LIKE '_test_%'
              AND created_at > NOW() - INTERVAL '4 hours'
            ORDER BY created_at DESC
            LIMIT $2
            """,
            phone, limit
        )
        return list(rows) if rows else []
    except Exception as e:
        logger.debug(f"drift get_recent_history hatasi: {e}")
        return []


async def analyze_drift(phone: str, current_msg: str = "",
                         window: int = 5) -> dict:
    """Öğrencinin son N mesajını analiz et, drift var mı kararı.

    Returns:
        dict:
          window_size: kaç mesaj incelendi
          categories: [cat1, cat2, ...]
          dominant: en sık kategori
          akademik_oran: float 0-1
          off_topic_oran: float 0-1
          drift_level: 'yok' | 'hafif' | 'orta' | 'agir'
          advice: str — Claude prompt'a ek not
          should_redirect: bool
    """
    history = await get_recent_history(phone, window)
    # Mevcut mesajı da ekle (en yeni)
    categories = []
    if current_msg:
        categories.append(classify_message(current_msg))
    for r in history:
        categories.append(classify_message(r.get("content", "")))

    total = len(categories)
    if total == 0:
        return {
            "window_size": 0,
            "categories": [],
            "dominant": "belirsiz",
            "akademik_oran": 0.0,
            "off_topic_oran": 0.0,
            "drift_level": "yok",
            "advice": "",
            "should_redirect": False,
        }

    akademik_cnt = sum(1 for c in categories if c in ("akademik", "pedagojik"))
    off_topic_cnt = sum(1 for c in categories if c == "off_topic")
    kisisel_cnt = sum(1 for c in categories if c == "kisisel")

    akademik_oran = akademik_cnt / total
    off_topic_oran = off_topic_cnt / total

    # Dominant kategori
    from collections import Counter
    dominant = Counter(categories).most_common(1)[0][0]

    # Drift seviyesi
    drift_level = "yok"
    should_redirect = False
    advice = ""

    # Son 3 ardışık off_topic kontrolü (en yeni 3)
    son3_off = all(c == "off_topic" for c in categories[:3]) if len(categories) >= 3 else False

    if son3_off:
        drift_level = "agir"
        should_redirect = True
        advice = (
            "🚨 CLASSROOM_MGMT: 3 ardışık off-topic mesaj. "
            "YUMUŞAK ama net redirect yap — öğrenciyi akademik konuya çek. "
            "'Güzel sohbet ama hedefi hatırlatayım: [konu]' şeklinde."
        )
    elif off_topic_oran >= 0.6 and total >= 3:
        drift_level = "orta"
        should_redirect = True
        advice = (
            "⚠ CLASSROOM_MGMT: Son mesajların %60+ off-topic. "
            "NAZİK redirect: kısa devam sohbet + akademik soruya geçiş."
        )
    elif off_topic_oran >= 0.4:
        drift_level = "hafif"
        advice = (
            "ℹ CLASSROOM_MGMT: Sohbet akademik konudan uzaklaşıyor. "
            "Cevabı kısa tut, yumuşak bir akademik hatırlatma ekle."
        )
    # Pozitif sinyal: akademik dominant
    elif akademik_oran >= 0.6:
        advice = (
            "✅ CLASSROOM_MGMT: Öğrenci odaklı ve akademik. "
            "Merak uyandır — cevap sonuna 1 karşı-soru ekle."
        )

    return {
        "window_size": total,
        "categories": categories,
        "dominant": dominant,
        "akademik_oran": round(akademik_oran, 2),
        "off_topic_oran": round(off_topic_oran, 2),
        "drift_level": drift_level,
        "advice": advice,
        "should_redirect": should_redirect,
        "kisisel_count": kisisel_cnt,
    }


if __name__ == "__main__":
    # Test
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    tests = [
        ("selam nasılsın bugün", "kisisel"),
        ("türev nedir anlatır mısın", "akademik"),
        ("çalışma planı yap bana", "pedagojik"),
        ("valorant oynuyorum ranked düştüm", "off_topic"),
        ("chatgpt'ye sorsam daha iyi cevap verir mi", "off_topic"),
        ("fizik denemem 2.5 net, ne yapmalıyım", "akademik"),
        ("dün Real Madrid maçı süperdi", "off_topic"),
        ("türkçe paragraf sorularını karıştırıyorum", "akademik"),
    ]
    print("=== classify_message testi ===")
    ok = 0
    for text, expected in tests:
        got = classify_message(text)
        mark = "✓" if got == expected else "✗"
        if got == expected: ok += 1
        print(f"{mark} '{text[:50]}' → {got} (bekl: {expected})")
    print(f"\nClassification: {ok}/{len(tests)}")

    # Drift simulation
    async def test_drift():
        from db_pool import db_execute
        TEST_PHONE = "_test_drift_905"
        # Temizle
        await db_execute("DELETE FROM fermat.agent_conversations WHERE phone=$1", TEST_PHONE)
        # 3 ardışık off_topic simule — test_prefix DEGIL (filter hariç tutmasın)
        for msg in ["valorant oynadım", "netflix dizi izledim", "chatgpt daha iyi"]:
            await db_execute(
                "INSERT INTO fermat.agent_conversations (session_id, phone, role, message_role, content) "
                "VALUES ('drift_sim', $1, 'ogrenci', 'user', $2)",
                TEST_PHONE, msg
            )
        r = await analyze_drift(TEST_PHONE, current_msg="bugün pes oynayacağım")
        print(f"\n=== Drift testi (3 ardışık off-topic) ===")
        print(f"categories: {r['categories']}")
        print(f"drift_level={r['drift_level']}, should_redirect={r['should_redirect']}")
        print(f"advice: {r['advice']}")
        await db_execute("DELETE FROM fermat.agent_conversations WHERE phone=$1", TEST_PHONE)

    asyncio.run(test_drift())
