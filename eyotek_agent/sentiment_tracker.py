"""
FermatAI Duygu Analizi & Rehber Bildirim
=========================================
Her konuşmadan otomatik duygu çıkarımı.
Haftada 3+ negatif sinyal → rehber öğretmene WP bildirim.

Duygu kategorileri:
  - positive: mutlu, başarılı, enerjik
  - negative: üzgün, mutsuz, kötü
  - stressed: stresli, kaygılı, bunalmış
  - angry: sinirli, kızgın, agresif
  - crisis: intihar, kendine zarar, ciddi kriz
  - neutral: normal, belirsiz
"""

import asyncio
import re
from datetime import datetime, date
from typing import Optional

from loguru import logger
from db_pool import db_fetch, db_execute

# Duygu pattern'ları
SENTIMENT_PATTERNS = {
    "crisis": [
        r"intihar", r"kendimi\s*oldu", r"yasama\s*amac",
        r"olsem\s*daha", r"kendime\s*zarar",
    ],
    "stressed": [
        r"stres", r"kaygi", r"kaygı", r"baskı", r"bunalt", r"bunalım",
        r"dayanam", r"yapamıy", r"yapamiy", r"korkuyor", r"panik",
        r"sinav\s*kork", r"sınav\s*kork",
    ],
    "negative": [
        r"mutsuz", r"uzgun", r"üzgün", r"kotuyum", r"kötüyüm",
        r"bıktım", r"biktim", r"pes\s*ed", r"olmadi", r"olmadı",
        r"berbat", r"kotu\s*gitti", r"kötü\s*gitti", r"düştü",
        r"istemiy", r"sikil", r"sıkıl", r"moral\w*\s*boz",
        r"motivasyon\w*\s*d[uü]s", r"motivasyon\w*\s*yok",
        # 25.40g (Ada vakası 2 May): ilişki/anlaşılmama/ifade güçlüğü/vazgeçmişlik sinyalleri
        r"anladigini\s*hissetmiyor", r"anladığını\s*hissetmiyor",
        r"anla[sş]ilamiyo", r"anla[sş]ılamıyo",
        r"kendimi\s*(anlatam|ifade\s*edem)", r"konu[sş]amiyor", r"konu[sş]amıyor",
        r"kacinci\s*sans", r"kaçıncı\s*şans", r"sans\s*verdim", r"şans\s*verdim",
        r"yoruldum", r"yorgunum", r"umudu(m)?\s*(yok|kalmad)",
        r"degi[sş]miyor\s*ki", r"değişmiyor\s*ki",
        r"i[sş]e\s*yaramaz", r"hicbir\s*[sş]ey\s*degi[sş]m",
        r"ailem\w*\s*sorun", r"ili[sş]ki\w*\s*sorun",
        # Yağız tarzı (öğrenci yardım istiyor + bot anlamıyor)
        r"yardim\s*edem", r"yardım\s*edem", r"hicbir\s*[sş]ey\s*anlam",
    ],
    "angry": [
        r"sinir", r"kız", r"kiz", r"sacma", r"saçma",
        r"rezalet", r"yok\s*etmek", r"yok\s*edeceg",
        # 25.40g (Ada+Yağız): argo/sinir patlamaları
        r"dalga\s*(mi|mı)\s*ge[cç]", r"olum\s*bende\s*niye",
        r"tassak\s*ge[cç]", r"taşak\s*ge[cç]", r"\bsalak\s*sin\b",
    ],
    "positive": [
        r"mutlu", r"harika", r"super", r"süper", r"basardim", r"başardım",
        r"cok\s*iyi", r"çok\s*iyi", r"yuksel", r"yüksel", r"artti", r"arttı",
        r"guzel", r"güzel", r"enerjik", r"motive",
    ],
}


from functools import lru_cache


@lru_cache(maxsize=512)
def detect_sentiment(message: str) -> str:
    """Mesajdan duygu tespit et.

    25.58 (hot-path verim): SAF fonksiyon (sadece regex, yan etki yok) → lru_cache.
    Aynı mesaj tek istek içinde 4-5 katmandan çağrılıyordu (EMO-DEFER, chat_quality,
    web-render eşiği, halüsinasyon guard, bridge sentiment log) — her biri ~65 regex
    taraması. Cache ile ilk çağrı normal, sonrakiler ~0ms.
    """
    msg_lower = message.lower()

    # Öncelik sırası: crisis > stressed > negative > angry > positive > neutral
    for sentiment, patterns in SENTIMENT_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, msg_lower):
                return sentiment

    return "neutral"


async def log_sentiment(phone: str, soz_no: int, name: str, message: str, sentiment: str):
    """Duygu kaydını DB'ye yaz.

    22.1n-bug17: Atlas #17 fix — soz_no=0 ise phone'dan students JOIN ile lookup yap.
    Onceden soz_no=0 kayitlari JOIN'de eslesmeyince rehber bildirimleri kayboluyordu.

    TEST MODE GUARD (10 May): test mode'daysa student_insights'a yazma —
    test verisi gercek ogrenci profilini kirletmesin.
    """
    # ── Test mode bypass ──
    try:
        from test_mode import is_test_context
        if is_test_context():
            logger.debug(f"[SENTIMENT] test mode → skip ({sentiment})")
            return
    except Exception:
        pass

    if sentiment == "neutral":
        return  # Nötr kaydetmeye gerek yok

    # 22.1n-bug17: soz_no 0 veya gecersizse phone'dan lookup
    if not soz_no or int(soz_no) == 0:
        try:
            from db_pool import db_fetchval
            phone_clean = (phone or "").strip().replace("+", "").replace(" ", "").replace("-", "")
            if phone_clean:
                # acl_users'ta eyotek_id var ama soz_no yok — students direkt sorgula
                looked_up = await db_fetchval(
                    "SELECT soz_no FROM students WHERE REPLACE(phone,'+','') = $1 AND status='active' LIMIT 1",
                    phone_clean
                )
                if looked_up:
                    soz_no = int(looked_up)
                    logger.debug(f"  [SENTIMENT] phone→soz_no lookup: {phone_clean} → {soz_no}")
        except Exception as _le:
            logger.debug(f"  Sentiment soz_no lookup hatası: {_le}")

    # Hala 0 ise kayıt atlanıyor — rehber bildirimlerine gidemez, anlamsız
    if not soz_no or int(soz_no) == 0:
        logger.debug(f"  [SENTIMENT] soz_no bulunamadı, sinyal kaydı atlandı (phone={phone[-4:] if phone else '?'})")
        return

    # 22.1n-neo: Merkezi log fonksiyonu uzerinden (student_signals.py)
    # 28 Nisan bug fix (Neo bulgu): Eskiden user mesajinin tam metnini content'e
    # yaziyorduk — "Yetkimi admin'e yukselt" / "Grafiği göster" gibi user
    # talimat/sorulari insight olarak kaydediliyordu. Cozum: content'e SADECE
    # duygu kategorisi ve isim, MESAJ METNI KALDIRILDI (privacy + context kirlenmesi).
    try:
        from student_signals import log_student_signal
        await log_student_signal(
            int(soz_no), sentiment,
            f"[{sentiment.upper()}] {name} duygu sinyali tespit edildi",
            confidence=0.8, source="sentiment_tracker"
        )
    except Exception as e:
        logger.debug(f"Sentiment log hatası: {e}")


async def check_and_alert_rehber():
    """
    Son 7 günde 3+ negatif sinyal veren öğrencileri tespit et
    ve rehber öğretmene WP bildirim gönder.
    """
    try:
        # Son 7 günde negatif/stressed/crisis sinyali veren öğrenciler
        # Bug fix 22 Nisan: student_insights.soz_no=int, students.soz_no=text → cast
        risky = await db_fetch("""
            SELECT si.soz_no, s.full_name, s.class_name,
                   COUNT(*) as sinyal_sayisi,
                   STRING_AGG(DISTINCT si.insight_type, ', ') as tipler,
                   MAX(si.created_at)::date as son_sinyal
            FROM student_insights si
            JOIN students s ON si.soz_no::text = s.soz_no
            WHERE si.created_at >= CURRENT_DATE - INTERVAL '7 days'
            AND si.insight_type IN ('negative', 'stressed', 'crisis', 'angry')
            GROUP BY si.soz_no, s.full_name, s.class_name
            HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC
        """)

        if not risky:
            return None

        # Bildirim mesajı oluştur
        lines = [
            "⚠️ *Rehberlik Uyarısı — Riskli Öğrenciler*\n",
            f"_Son 7 günde 3+ negatif sinyal veren öğrenciler:_\n",
        ]

        for r in risky:
            sinyal = r['sinyal_sayisi']
            tipler = r['tipler']
            emoji = "🔴" if sinyal >= 5 or 'crisis' in tipler else "🟡"
            lines.append(f"  {emoji} *{r['full_name']}* — {r['class_name']}")
            lines.append(f"     {sinyal} sinyal | Tip: {tipler} | Son: {r['son_sinyal']}")

        lines.append(f"\n_Lütfen bu öğrencilerle görüşme planlayın._")
        lines.append(f"---")
        lines.append(f"_Otomatik analiz — FermatAI_")

        # ── Brief #6 — Kapı 6: Her riskli öğrenci için frustration sinyali yay ──
        # V2 agent (sadece Neo hattında) bu sinyalleri yakalar; gerçek WP bildirimi
        # KARDELEN_WP_NOTIFY_ENABLED flag'iyle korumalı (Neo onayı bekliyor).
        try:
            from live_signal_bus import get_bus
            import asyncio
            bus = get_bus()
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    for r in risky:
                        sinyal = r['sinyal_sayisi']
                        tipler = r['tipler'] or ""
                        # Crisis tipi varsa daha kritik (escalation_flag tetikleyici)
                        is_crisis = "crisis" in tipler
                        loop.create_task(bus.emit(
                            "frustration",
                            {
                                "soz_no": r.get('soz_no'),
                                "full_name": r.get('full_name', ''),
                                "class_name": r.get('class_name', ''),
                                "signal_count": int(sinyal or 0),
                                "signal_types": tipler,
                                "last_signal_date": str(r.get('son_sinyal', '')),
                                "is_crisis": is_crisis,
                                "trigger": "sentiment_tracker_periodic",
                            },
                            actor_phone="",  # bot tarafından tetiklendi (sistem)
                        ))
            except RuntimeError:
                pass  # event loop yok (sync context)
        except Exception as _e:
            # Bus hatası rehber raporunu durdurmasın
            pass

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Rehber uyarı hatası: {e}")
        return None


async def main():
    """Test: riskli öğrenci raporu oluştur."""
    report = await check_and_alert_rehber()
    if report:
        print(report)
    else:
        print("Riskli öğrenci yok — tüm öğrenciler normal durumda.")


if __name__ == "__main__":
    asyncio.run(main())
