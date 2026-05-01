"""
Render Templates Seed Script — 25.37+ (Neo audit #4)
======================================================
En kaliteli archived render'ları render_templates'e promote eder.
Bot yeni isteklerde get_top_templates(konu) ile pattern'leri referans alır.

Çalıştırma: python seed_render_templates.py
"""
from __future__ import annotations
import asyncio
import re
from loguru import logger

from db_pool import db_fetch, db_execute, db_fetchval


# Konu → ders eşleştirme (otomatik kategorize için)
KONU_TO_DERS = {
    'karadelik': 'Fizik', 'kara delik': 'Fizik', 'olay ufku': 'Fizik',
    'wormhole': 'Fizik', 'solucan': 'Fizik', 'morris-thorne': 'Fizik',
    'compton': 'Fizik', 'fotoelektrik': 'Fizik', 'planck': 'Fizik',
    'evren': 'Fizik', 'gözlemlenebilir': 'Fizik', 'kozmoloji': 'Fizik',
    'atom': 'Fizik', 'bohr': 'Fizik', 'kuantum': 'Fizik',
    'fiber optik': 'Fizik', 'optik': 'Fizik', 'lazer': 'Fizik',
    'kara cisim': 'Fizik', 'isima': 'Fizik', 'spektrum': 'Fizik',
    'fay': 'Coğrafya', 'deprem': 'Coğrafya', 'jeoloji': 'Coğrafya',
    'uzay zaman': 'Fizik', 'görelilik': 'Fizik', 'einstein': 'Fizik',
    'zeeman': 'Fizik', 'manyetik': 'Fizik', 'spin': 'Fizik',
    'schwarzschild': 'Fizik', 'kütleçekim': 'Fizik', 'gravitasyonel': 'Fizik',
    'de broglie': 'Fizik', 'madde dalgası': 'Fizik', 'parçacık': 'Fizik',
    'quark': 'Fizik', 'lepton': 'Fizik', 'standart model': 'Fizik',
    'mitoz': 'Biyoloji', 'mayoz': 'Biyoloji', 'hücre': 'Biyoloji',
    'dna': 'Biyoloji', 'protein': 'Biyoloji', 'gen': 'Biyoloji',
    'fotosentez': 'Biyoloji', 'solunum': 'Biyoloji',
    'elektrik': 'Fizik', 'devre': 'Fizik', 'akim': 'Fizik',
    'türev': 'Matematik', 'integral': 'Matematik', 'limit': 'Matematik',
    'fonksiyon': 'Matematik', 'logaritma': 'Matematik',
    'periyodik': 'Kimya', 'element': 'Kimya', 'molekül': 'Kimya',
    'tepkime': 'Kimya', 'asit': 'Kimya', 'baz': 'Kimya',
}


def detect_ders(title: str) -> str:
    """Title'dan ders tahmin et."""
    title_lower = (title or "").lower()
    for keyword, ders in KONU_TO_DERS.items():
        if keyword in title_lower:
            return ders
    return "Genel"


def extract_konu(title: str) -> str:
    """Title'dan konu adı çıkar (emoji, paranthese vs temizle)."""
    s = (title or "").strip()
    # Emoji + simgeleri temizle (basit: sadece harfleri ve birkaç sembolü tut)
    s = re.sub(r'[^\w\s\-çğıöşüÇĞİÖŞÜ]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # "İnteraktif Simulasyon" gibi suffixleri kaldır
    s = re.sub(r'\b(simulasyon|simülasyon|interaktif|3d|model)\b', '', s, flags=re.IGNORECASE)
    s = s.strip(' -—·')
    return s[:60]


async def main():
    print("=" * 60)
    print("Render Templates Seed — En kaliteli 5+ render'ı promote et")
    print("=" * 60)

    # En kaliteli archived render'ları al (quality_score DESC)
    rows = await db_fetch(
        """SELECT uuid, title, quality_score, html, creator_phone, created_at
           FROM render_artifacts
           WHERE archived = TRUE AND quality_score >= 70
           ORDER BY quality_score DESC, created_at DESC
           LIMIT 10"""
    )
    print(f"\nQuality >= 70 archived render: {len(rows)}\n")

    if not rows:
        print("Promote edilecek render yok. Önce kullanıcı arşive ekleyince çalıştır.")
        return

    promoted = 0
    skipped = 0
    for r in rows:
        title = r["title"] or "Başlıksız"
        konu = extract_konu(title)
        ders = detect_ders(title)
        score = r["quality_score"]
        size_kb = len((r["html"] or "").encode("utf-8")) // 1024

        # Zaten promote edildi mi?
        existing = await db_fetchval(
            "SELECT id FROM render_templates WHERE source_uuid = $1",
            r["uuid"]
        )
        if existing:
            print(f"  ⏭️  Zaten template: {title[:50]} (id={existing})")
            skipped += 1
            continue

        # Approach summary üret
        approach = (
            f"Compton-altın standart örneği: {ders} dersinde {konu} konusu için "
            f"~{size_kb}KB zengin HTML. Quality {score}/100. "
            f"Bu pattern'i referans al — multi-panel, slider, formül, gerçek bilim verisi."
        )

        try:
            await db_execute(
                """INSERT INTO render_templates
                   (konu, ders, title, source_uuid, approach_summary, quality_score, approved)
                   VALUES ($1, $2, $3, $4, $5, $6, TRUE)""",
                konu[:120], ders[:60], title[:200], r["uuid"], approach[:500], score
            )
            promoted += 1
            print(f"  ✅  Promote: [{ders}] {konu} (score={score}/100, {size_kb}KB)")
        except Exception as e:
            print(f"  ❌  Hata: {title[:50]} — {e}")

    # Sonuç
    total = await db_fetchval("SELECT COUNT(*) FROM render_templates WHERE approved = TRUE")
    print(f"\n{'='*60}")
    print(f"Yeni promote: {promoted}, atlandı: {skipped}")
    print(f"Toplam approved template: {total}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
