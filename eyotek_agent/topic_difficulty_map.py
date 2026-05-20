"""
FermatAI — Konu Zorluk Haritası
================================
Kurum geneli hangi konularda zorluk yaşanıyor analiz eder.
Öğretmen toplantısı, müfredat planlaması ve etüt önerisi için altyapı.

Kullanım:
  python topic_difficulty_map.py              # Genel rapor
  python topic_difficulty_map.py --ders Matematik
  python topic_difficulty_map.py --top 20
"""

import asyncio
import sys
from pathlib import Path

from loguru import logger
from db_pool import db_fetch


async def get_kurum_zorluk_haritasi(ders_filtre: str = "", top: int = 15, min_ogrenci: int = 3) -> list:
    """Kurum geneli en zayıf konular — ders bazlı."""
    where = "WHERE 1=1"
    params = []
    if ders_filtre:
        params.append(f"%{ders_filtre}%")
        where += f" AND ders ILIKE ${len(params)}"

    # "TYT X" / "AYT X" gibi generic etiketleri filtrele
    where += " AND konu NOT LIKE 'Ortalama %' AND LENGTH(konu) > 5"

    rows = await db_fetch(f"""
        SELECT
            ders,
            konu,
            COUNT(DISTINCT soz_no) as ogrenci_sayisi,
            AVG(sinav_hata_yuzdesi) as avg_basari,
            SUM(sinav_hata_sayisi) as toplam_hata,
            COUNT(*) FILTER (WHERE status='calisiyor') as calisan,
            COUNT(*) FILTER (WHERE tamamlandi=TRUE) as tamamlandi
        FROM student_topic_tracker
        {where}
        GROUP BY ders, konu
        HAVING COUNT(DISTINCT soz_no) >= ${len(params) + 1}
        ORDER BY avg_basari ASC, COUNT(DISTINCT soz_no) DESC
        LIMIT ${len(params) + 2}
    """, *params, min_ogrenci, top)

    return rows


async def get_ogretmen_oneri(konu: str, ders: str) -> list:
    """Belirli bir konu için müsait öğretmen + boş slot önerisi."""
    return await db_fetch("""
        SELECT t.ogretmen_ad, t.brans, COUNT(*) as ders_sayisi
        FROM teacher_timetable t
        WHERE t.ders ILIKE $1 OR t.brans ILIKE $2
        GROUP BY t.ogretmen_ad, t.brans
        ORDER BY ders_sayisi DESC LIMIT 5
    """, f"%{ders}%", f"%{ders}%")


async def get_konu_basari_dagilimi(ders: str, konu: str) -> dict:
    """Belirli bir konuda başarı dağılımı (kim iyi, kim zayıf)."""
    # sinav_hata_yuzdesi = HATA % → basari = 100 - hata. Dusuk hata = iyi → ASC = en iyiden.
    rows = await db_fetch("""
        SELECT t.soz_no, s.full_name, s.class_name,
               (100 - t.sinav_hata_yuzdesi) as basari, t.sinav_hata_sayisi as hata
        FROM student_topic_tracker t
        LEFT JOIN students s ON s.soz_no::text = t.soz_no::text
        WHERE t.ders ILIKE $1 AND t.konu ILIKE $2
          AND t.sinav_hata_yuzdesi IS NOT NULL
        ORDER BY t.sinav_hata_yuzdesi ASC
    """, f"%{ders}%", f"%{konu}%")
    return {
        'toplam_ogrenci': len(rows),
        'iyi': [r for r in rows if (r['basari'] or 0) >= 60],
        'zayif': [r for r in rows if (r['basari'] or 100) < 40],
        'orta': [r for r in rows if 40 <= (r['basari'] or 0) < 60],
    }


async def format_kurum_raporu(ders_filtre: str = "", top: int = 15) -> str:
    """WhatsApp formatında kurum zorluk raporu."""
    konular = await get_kurum_zorluk_haritasi(ders_filtre, top)
    if not konular:
        return "Kurum geneli zorluk verisi henüz yetersiz."

    lines = []
    if ders_filtre:
        lines.append(f"📊 *KURUM GENELI ZORLUK HARITASI — {ders_filtre.upper()}*\n")
    else:
        lines.append("📊 *KURUM GENELI ZORLUK HARITASI*\n")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_(En çok zorlanılan konular)_\n")

    for i, k in enumerate(konular[:top], 1):
        basari = k['avg_basari'] or 0
        if basari < 20:
            emoji = "🔴"
        elif basari < 40:
            emoji = "🟠"
        elif basari < 60:
            emoji = "🟡"
        else:
            emoji = "🟢"

        lines.append(
            f"*{i}.* {emoji} *{k['ders']}* — _{k['konu'][:35]}_"
        )
        lines.append(
            f"    %{basari:.0f} başarı | {k['ogrenci_sayisi']} öğrenci | "
            f"{k['toplam_hata']} hata"
        )
        if k['calisan']:
            lines.append(f"    ✍️ {k['calisan']} öğrenci şu an çalışıyor")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 *Stratejik Aksiyon:*")
    en_zayif = konular[0]
    lines.append(
        f"*{en_zayif['ders']}* dersinde *{en_zayif['konu'][:30]}* konusu acil — "
        f"{en_zayif['ogrenci_sayisi']} öğrenci ortalama %{en_zayif['avg_basari']:.0f} başarıda."
    )
    lines.append(f"\n_Öğretmen toplantısında bu konuyu gündeme getirilmesi önerilir._")

    return "\n".join(lines)


async def main():
    ders_filtre = ""
    top = 15
    if "--ders" in sys.argv:
        ders_filtre = sys.argv[sys.argv.index("--ders") + 1]
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])

    rapor = await format_kurum_raporu(ders_filtre, top)
    print(rapor)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
