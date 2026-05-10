"""
Konu Zorluk Haritası (25.41 Neo — 7 May)
=========================================

Kurum geneli analiz:
- 90+ öğrencinin sınav verisinde hangi konu en çok yanlış yapılıyor?
- Ders bazlı sıralama
- Çıktı: Müdür/öğretmen toplantısına girdi

Veri kaynağı: student_topic_tracker (öğrenci konu takibi tablosu)
"""
from __future__ import annotations
from db_pool import db_fetch, db_fetchval
from typing import Optional


async def kurum_konu_haritasi(ders_filtre: str = "", min_ogrenci: int = 5) -> str:
    """Kurum geneli konu zorluk haritası.

    Args:
        ders_filtre: 'matematik', 'fizik' gibi (boşsa tümü)
        min_ogrenci: bir konuyu listelemek için min kaç öğrenci hata yapmış olmalı

    Returns:
        WhatsApp dostu rapor (öğretmen/müdür için).
    """
    # Ders bazlı en zor konular (en çok hata oranı)
    where_filter = ""
    params = []
    if ders_filtre:
        where_filter = "AND LOWER(ders) LIKE LOWER($1)"
        params.append(f"%{ders_filtre}%")

    # INVERSION FIX (Berf bug 10 May): sinav_hata_yuzdesi = HATA %.
    # Konu ZORLUK = YUKSEK ort hata (cok ogrenci bu konuda zorlaniyor).
    # Eski kod ASC sirayla "iyi yapilan" konulari zor diye gosteriyordu.
    rows = await db_fetch(f"""
        SELECT ders, konu,
               COUNT(DISTINCT soz_no) ogrenci_sayisi,
               ROUND(AVG(sinav_hata_yuzdesi)::numeric, 1) ort_hata,
               ROUND((100 - AVG(sinav_hata_yuzdesi))::numeric, 1) ort_basari,
               COUNT(*) FILTER (WHERE sinav_hata_yuzdesi >= 70) cok_zayif
        FROM student_topic_tracker
        WHERE LENGTH(konu) > 5
          AND konu NOT LIKE 'Ortalama %'
          AND COALESCE(status,'') != 'metadata'
          AND sinav_hata_yuzdesi IS NOT NULL
          {where_filter}
        GROUP BY ders, konu
        HAVING COUNT(DISTINCT soz_no) >= {min_ogrenci}
           AND AVG(sinav_hata_yuzdesi) >= 30
        ORDER BY ort_hata DESC NULLS LAST, ogrenci_sayisi DESC
        LIMIT 25
    """, *params)

    if not rows:
        return (
            "📊 *Konu Zorluk Haritası*\n\n"
            f"_{'Bu derste' if ders_filtre else 'Sistemde'} yeterli veri yok._\n"
            f"Min {min_ogrenci} öğrencinin denemiş olduğu konu bulunamadı."
        )

    lines = ["📊 *KURUM GENELİ — KONU ZORLUK HARİTASI*"]
    if ders_filtre:
        lines.append(f"📚 _Filtre: {ders_filtre}_")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"_(Hata oranı yüksek = konu zor — {min_ogrenci}+ öğrenci denenmiş)_\n")

    # Ders bazlı grupla
    by_ders = {}
    for r in rows:
        d = r['ders']
        if d not in by_ders:
            by_ders[d] = []
        by_ders[d].append(r)

    for ders, konular in sorted(by_ders.items(), key=lambda x: -len(x[1])):
        lines.append(f"\n📖 *{ders.upper()}* ({len(konular)} konu)")
        for r in konular[:5]:  # ders başına top 5
            # INVERSION FIX: yüksek hata = kırmızı (en zor)
            emoji = "🔴" if r['ort_hata'] >= 60 else ("🟠" if r['ort_hata'] >= 40 else "🟡")
            lines.append(
                f"  {emoji} {r['konu'][:45]}\n"
                f"     _{r['ogrenci_sayisi']} öğr · ort başarı %{r['ort_basari']:.0f} (hata %{r['ort_hata']:.0f})_"
            )

    # Toplam istatistik
    toplam_ogr = await db_fetchval("""
        SELECT COUNT(DISTINCT soz_no) FROM student_topic_tracker
    """) or 0

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📈 *Veri tabanı:* {toplam_ogr} öğrenci, son 6 ay denemeleri")
    lines.append(
        "\n💡 *Önerim:* Bu hafta tüm sınıflarda 1 numaralı kırmızı konuya odak. "
        "Tek tek öğretmenler değil, **ortak çaba** daha hızlı sonuç verir."
    )
    lines.append("\n_'matematik konu haritası' yazarak ders filtresi yapabilirsin._")

    return "\n".join(lines)


# Müdür/öğretmen icin top 3 acil konu
async def acil_konular_top3(ders: str = "") -> str:
    """En acil 3 konu — toplantıda 1 dakikalık özet için."""
    where_filter = ""
    params = []
    if ders:
        where_filter = "AND LOWER(ders) LIKE LOWER($1)"
        params.append(f"%{ders}%")

    # INVERSION FIX (Berf bug 10 May): sinav_hata_yuzdesi = HATA %.
    # ACIL konu = YUKSEK hata. Eski kod `< 35` ile basariliyi acil sayiyordu.
    rows = await db_fetch(f"""
        SELECT ders, konu,
               COUNT(DISTINCT soz_no) ogr,
               ROUND(AVG(sinav_hata_yuzdesi)::numeric, 0) hata_pct,
               ROUND((100 - AVG(sinav_hata_yuzdesi))::numeric, 0) basari
        FROM student_topic_tracker
        WHERE LENGTH(konu) > 5
          AND konu NOT LIKE 'Ortalama %'
          AND COALESCE(status,'') != 'metadata'
          AND sinav_hata_yuzdesi IS NOT NULL
          AND sinav_hata_yuzdesi >= 60
          {where_filter}
        GROUP BY ders, konu
        HAVING COUNT(DISTINCT soz_no) >= 3
        ORDER BY ogr DESC, hata_pct DESC
        LIMIT 3
    """, *params)

    if not rows:
        return "_Acil konu yok — sistem stabil görünüyor._"

    lines = [f"🚨 *ACİL 3 KONU{(' — '+ders.upper()) if ders else ''}*\n"]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"{i}. *{r['konu'][:50]}* ({r['ders']})\n"
            f"   _{r['ogr']} öğrenci · ort başarı %{r['basari']} (hata %{r['hata_pct']})_"
        )
    lines.append("\n_Bu hafta odak: bu 3 konu, tüm sınıflar._")
    return "\n".join(lines)


if __name__ == "__main__":
    import asyncio, sys
    sys.stdout.reconfigure(encoding="utf-8")
    async def main():
        print(await kurum_konu_haritasi())
        print("\n" + "="*60 + "\n")
        print(await acil_konular_top3())
    asyncio.run(main())
