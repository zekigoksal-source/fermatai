"""
FermatAI — Self-Observation Layer (Faz 1)
==========================================
Her bot cevabı sonrası gerçek zamanlı kalite değerlendirmesi.
Halüsinasyon, context kaybı, kalite skor — quality_log tablosuna kaydeder.

Self-improvement framework'ün ilk katmanı:
  Faz 1: GÖZLEM         ← BURADA (kendini izler)
  Faz 2: TANI           (hataları kök nedenle bulur)
  Faz 3: ÖNERİ          (düzeltme önerir)
  Faz 4: KISMI OTONOMI  (düşük riskli kendi yapar)
  Faz 5: TAM ADAPTIVE   (öğrenci bazlı kişiselleşir)
"""

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger
from db_pool import get_pool as _get_pool, db_fetch, db_fetchval, db_execute


# ── KALITE METRIKLERI ──────────────────────────────────────────────────

# Halüsinasyon riski — SADECE uydurma içerik göstergeleri
# 19 Nisan kalibrasyon (Oturum 22.1g): Format hatalari ayri skora tasindi, halusinasyondan cikarildi
_HALLUC_PATTERNS = [
    # Sayı uydurma sinyalleri (GERCEK halusinasyon)
    (r'\b(yaklaşık|civarı|ortalama|tahmini)\s*\d+', 'tahmini_sayi', 0.4),
    (r'\b\d+\s*ogrenci(?!.*\?)', 'kesin_ogrenci_sayisi', 0.3),
    # Soru metni uydurma (tarihsel halusinasyon ornegi — Taha, ova hucreleri)
    (r'(ova\s*hücreleri|sörfü|çoğalma|dönme).*işlemi', 'soru_metni_uyduruk', 0.9),
    (r'aşağıdaki\s*bitkilerden\s*hangisi', 'soru_metni_uyduruk', 0.8),
    # ToolUseBlock sızıntısı (GERCEK hata — teknik detay kullaniciya)
    (r'\[ToolUseBlock|TextBlock|toolu_', 'tool_block_sizma', 1.0),
    # Generic fallbacks (yetersiz cevap)
    (r'(bu\s*soruyu\s*doğrudan\s*yanıtlayamam|bilgime\s*ulaşamadım|verim\s*yok)', 'generic_fallback', 0.5),
    # Kimlik karışıklığı (gercek hata)
    (r'(merhaba\s*neo|sen\s*neo|sen\s*admin)', 'kimlik_karisma', 0.7),
    # META LEAK — Claude/AI/prompt sizintisi (Oturum 22.1g yeni)
    (r'\b(ben\s+bir\s+AI|dil\s+modeli|claude\s+olarak|ollama|promptta)\b', 'meta_leak', 0.6),
]

# FORMAT HATALARI — halusinasyon DEGIL, ayri skor (22.1g kalibrasyon)
# Icerik dogru ama sunumu bozuk → kalite skoruna yansir, halusinasyon'a GIRMEZ
_FORMAT_PATTERNS = [
    (r'\*\*[^*]+\*\*', 'cift_yildiz_bold', 0.3),   # WhatsApp bold yanlis
    (r'^#{1,6}\s', 'markdown_baslik', 0.2),          # ## baslik — WP desteklemiyor
    (r'\|[\s\-:]+\|', 'markdown_tablo', 0.4),        # Tablo WP'de bozuk
]

# Kalite pozitif sinyalleri
_QUALITY_PATTERNS = [
    (r'━━━━', 'ayirici_cizgi', 0.1),  # Görsel
    (r'\n\n\*[^*]+\*', 'baslik_yapi', 0.1),  # Bold başlık
    (r'(istersen|ister misin|nereden başlayalım)', 'eylem_cagirisi', 0.15),  # Yönlendirme
    (r'(\d+\.\d+|\d+%|\d+/\d+)', 'somut_veri', 0.1),  # Sayısal veri
    (r'_[^_]+_', 'italik_vurgu', 0.05),
    (r'(📊|🎯|📚|📅|💡|✅|⚡|🧪|🧬|⚛️|🌱)', 'emoji_yapi', 0.05),
]


def evaluate_response(message_user: str, response_bot: str, context: dict = None, role: str = "") -> dict:
    """
    Bot cevabını değerlendir.
    22.1k — role parametresi eklendi: admin/mudur icin meta_leak pattern atlaniyor
    (Neo teknik sohbette "Claude"/"Ollama" kelimelerini kullaniyor — false positive)
    """
    sorunlar = []
    halusinasyon_skor = 0.0
    kalite_skor = 0.0
    format_cezasi = 0.0  # 22.1g — ayri skor

    response_lower = response_bot.lower()
    msg_lower = (message_user or '').lower()

    # Halusinasyon kontrol (sadece GERCEK icerik uydurma)
    # 22.1k — admin/mudur teknik sohbette meta_leak atla
    skip_meta_leak = role in ("admin", "mudur", "yonetim")
    for pattern, name, weight in _HALLUC_PATTERNS:
        if name == "meta_leak" and skip_meta_leak:
            continue
        if re.search(pattern, response_lower, re.IGNORECASE | re.MULTILINE):
            halusinasyon_skor += weight
            sorunlar.append(name)

    # Format hatalari (ayri skor — kalite skorundan cikarilir)
    for pattern, name, weight in _FORMAT_PATTERNS:
        if re.search(pattern, response_bot, re.MULTILINE):
            format_cezasi += weight
            sorunlar.append(name)

    # Kalite pozitif
    for pattern, name, weight in _QUALITY_PATTERNS:
        if re.search(pattern, response_bot, re.MULTILINE):
            kalite_skor += weight

    # Format cezasi kalite skorunu dusurur (cumulative bu sefer)
    kalite_skor = max(0.0, kalite_skor - format_cezasi)

    # Context skor — basit: cevap kullanıcı isteğiyle ilgili mi
    context_skor = 0.5  # Default
    if msg_lower:
        # Kullanıcının kelimelerinden en az 1'i cevapta var mı?
        msg_words = set(re.findall(r'\b\w{4,}\b', msg_lower))
        resp_words = set(re.findall(r'\b\w{4,}\b', response_lower))
        if msg_words:
            overlap = len(msg_words & resp_words) / len(msg_words)
            context_skor = min(1.0, 0.3 + overlap)

    # Genel grade — 22.1g kalibrasyon: eşikler gevşetildi
    # Onceki: A %0.2, C %59 (sıkı). Yeni: A %~15, C %~40 (dağılmış)
    halusinasyon_skor = min(1.0, halusinasyon_skor)
    kalite_skor = min(1.0, kalite_skor)

    if halusinasyon_skor >= 0.7:
        grade = 'F'
    elif halusinasyon_skor >= 0.5:  # 0.4 → 0.5 (daha az D)
        grade = 'D'
    elif halusinasyon_skor < 0.2 and kalite_skor >= 0.3 and context_skor >= 0.4:
        # A eşiği yumuşatıldı: kalite 0.5 → 0.3, context 0.6 → 0.4
        grade = 'A'
    elif halusinasyon_skor < 0.3 and kalite_skor >= 0.15:
        # B eşiği yumuşatıldı: hal 0.2 → 0.3, kalite 0.3 → 0.15
        grade = 'B'
    else:
        grade = 'C'

    return {
        'halusinasyon_skor': round(halusinasyon_skor, 2),
        'kalite_skor': round(kalite_skor, 2),
        'context_skor': round(context_skor, 2),
        'sorunlar': sorunlar,
        'genel_grade': grade,
    }


async def ensure_quality_log_table():
    """quality_log tablosu oluştur."""
    await db_execute("""
        CREATE TABLE IF NOT EXISTS quality_log (
            id SERIAL PRIMARY KEY,
            session_id TEXT,
            phone TEXT,
            role TEXT,
            user_message TEXT,
            bot_response TEXT,
            response_source TEXT,
            halusinasyon_skor REAL,
            kalite_skor REAL,
            context_skor REAL,
            grade CHAR(1),
            sorunlar TEXT[],
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await db_execute("""
        CREATE INDEX IF NOT EXISTS idx_quality_grade ON quality_log (grade, created_at);
        CREATE INDEX IF NOT EXISTS idx_quality_phone ON quality_log (phone, created_at);
    """)


async def log_quality(
    session_id: str,
    phone: str,
    role: str,
    user_message: str,
    bot_response: str,
    response_source: str = 'claude',
):
    """Bir bot cevabını değerlendir ve quality_log'a yaz."""
    if not bot_response or len(bot_response.strip()) < 5:
        return  # Çok kısa cevaplar değerlendirilmez

    try:
        evaluation = evaluate_response(user_message or '', bot_response, role=role or '')
        await db_execute("""
            INSERT INTO quality_log (
                session_id, phone, role, user_message, bot_response,
                response_source, halusinasyon_skor, kalite_skor, context_skor,
                grade, sorunlar
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
            session_id or '', phone or '', role or '',
            (user_message or '')[:500],
            bot_response[:2000],
            response_source,
            evaluation['halusinasyon_skor'],
            evaluation['kalite_skor'],
            evaluation['context_skor'],
            evaluation['genel_grade'],
            evaluation['sorunlar'],
        )

        # Kritik kaliteye logger uyarı
        if evaluation['genel_grade'] in ('F', 'D'):
            logger.warning(
                f"🚨 Kalite uyarisi [{evaluation['genel_grade']}] {phone}: "
                f"halu={evaluation['halusinasyon_skor']:.2f} | sorunlar={evaluation['sorunlar']}"
            )
    except Exception as e:
        logger.debug(f"Quality log hatasi: {e}")


async def get_quality_summary(hours: int = 24) -> dict:
    """Son N saatin kalite özeti."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                grade,
                COUNT(*) as cnt,
                AVG(halusinasyon_skor) as avg_halu,
                AVG(kalite_skor) as avg_kalite
            FROM quality_log
            WHERE created_at >= NOW() - INTERVAL '{hours} hours'
            GROUP BY grade ORDER BY grade
        """)
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM quality_log WHERE created_at >= NOW() - INTERVAL '{hours} hours'"
        )
        top_sorun = await conn.fetch(f"""
            SELECT UNNEST(sorunlar) as sorun, COUNT(*) as cnt
            FROM quality_log
            WHERE created_at >= NOW() - INTERVAL '{hours} hours'
            AND array_length(sorunlar, 1) > 0
            GROUP BY sorun ORDER BY cnt DESC LIMIT 10
        """)
    return {
        'toplam': total,
        'grade_dagilim': [dict(r) for r in rows],
        'top_sorunlar': [dict(r) for r in top_sorun],
    }


async def main():
    await ensure_quality_log_table()
    summary = await get_quality_summary(24)
    print(f"\nSon 24 saat kalite raporu:")
    print(f"Toplam degerlendirme: {summary['toplam']}")
    print(f"\nGrade dagilimi:")
    for r in summary['grade_dagilim']:
        print(f"  {r['grade']}: {r['cnt']} cevap | halu={r['avg_halu']:.2f} | kalite={r['avg_kalite']:.2f}")
    print(f"\nTop 10 sorun:")
    for r in summary['top_sorunlar']:
        print(f"  {r['cnt']:3d}x | {r['sorun']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
