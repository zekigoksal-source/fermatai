"""
FermatAI — Tum Etut Kayitlarini Cek
Etut Ara sayfasindan tarih filtresi OLMADAN tum etutleri ceker.
Her kayit: etut_kodu, tarih, ogretmen, ders, konu, saat, sure, derslik, ogrenci_sayisi, yoklama, kaydeden
10+ sayfa pagination ile tum veriler cekilir.
"""
import asyncio
import json
import os
import time

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)
from db_pool import get_pool as _get_pool


async def scrape_all_etuts(conn, ew):
    """Etut Ara sayfasindan tum etut kayitlarini cek."""
    logger.info("=== TUM ETUT KAYITLARI ===")
    t0 = time.time()

    await ew._goto("Pages/Student/individual-lesson")
    await asyncio.sleep(2)

    # ARA link tikla -> modal ac
    await ew._page.evaluate("""
        () => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                if (a.innerText.trim() === 'ARA' && a.offsetParent) {
                    a.click(); return true;
                }
            }
            return false;
        }
    """)
    await asyncio.sleep(2)

    # Tarih alanlarini TEMIZLE — txtKayitBas ve txtKayitBit
    await ew._page.evaluate("""
        () => {
            const bas = document.getElementById('txtKayitBas');
            const bit = document.getElementById('txtKayitBit');
            if (bas) { bas.value = ''; bas.dispatchEvent(new Event('change', {bubbles: true})); }
            if (bit) { bit.value = ''; bit.dispatchEvent(new Event('change', {bubbles: true})); }
        }
    """)
    await asyncio.sleep(0.5)

    # btnSearch tikla
    await ew._page.click('#btnSearch')
    await asyncio.sleep(4)

    # Tum sayfalari oku
    all_records = []
    page_num = 1

    while True:
        records = await ew._page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                for (const tbl of tables) {
                    const ths = Array.from(tbl.querySelectorAll('th'))
                        .map(h => h.innerText.trim());
                    // Etut Kodu veya Tarih header'i olan tablo
                    if (!ths.some(h => h.includes('Etüt Kodu') || h.includes('Tarih')))
                        continue;
                    if (ths.length < 5) continue;
                    const headers = ths.map(h => h.toLowerCase());
                    const rows = [];
                    tbl.querySelectorAll('tbody tr').forEach(tr => {
                        const cells = Array.from(tr.querySelectorAll('td'))
                            .map(td => td.innerText.trim());
                        if (cells.length >= 5 && cells.some(c => c)) {
                            const row = {};
                            headers.forEach((h, i) => {
                                if (cells[i] !== undefined) row[h] = cells[i];
                            });
                            rows.push(row);
                        }
                    });
                    return rows;
                }
                return [];
            }
        """)

        if not records:
            logger.info(f"  Sayfa {page_num}: 0 kayit — bitti")
            break

        all_records.extend(records)
        logger.info(f"  Sayfa {page_num}: {len(records)} kayit (toplam: {len(all_records)})")

        # Sonraki sayfa
        page_num += 1
        next_clicked = await ew._page.evaluate(f"""
            () => {{
                // Pagination linkleri — sayi veya "..." (sonraki grup)
                const pagerLinks = document.querySelectorAll('a');
                for (const a of pagerLinks) {{
                    const t = a.innerText.trim();
                    if (t === '{page_num}' && a.offsetParent) {{
                        a.click();
                        return 'sayfa';
                    }}
                }}
                // "..." linkine tikla (sonraki sayfa grubu)
                for (const a of pagerLinks) {{
                    if (a.innerText.trim() === '...' && a.offsetParent) {{
                        a.click();
                        return 'dots';
                    }}
                }}
                return null;
            }}
        """)
        if not next_clicked:
            logger.info(f"  Sayfa {page_num} bulunamadi — bitti")
            break
        await asyncio.sleep(2)

        # "..." sonrasi sayfa numarasini kontrol et
        if next_clicked == 'dots':
            # dots tiklandi, sayfa yuklenecek — tekrar sayfa numarasini dene
            await ew._page.evaluate(f"""
                () => {{
                    const links = document.querySelectorAll('a');
                    for (const a of links) {{
                        if (a.innerText.trim() === '{page_num}' && a.offsetParent) {{
                            a.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """)
            await asyncio.sleep(2)

    dur = time.time() - t0
    logger.success(f"  TOPLAM: {len(all_records)} etut kaydi ({dur:.1f}s)")

    # JSON dump
    with open("all_etuts_dump.json", "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)
    logger.info("  all_etuts_dump.json kaydedildi")

    return all_records


async def save_to_db(conn, records):
    """Etut kayitlarini DB'ye yaz."""
    logger.info(f"  {len(records)} kayit DB'ye yaziliyor...")

    # Field mapping
    fm = {
        "şube": "sube", "etüt kodu": "etut_kodu", "etüt türü": "etut_turu",
        "tarih": "tarih", "öğretmen": "ogretmen", "ders": "ders",
        "konu": "konu", "saat": "saat", "süre": "sure",
        "derslik": "derslik", "öğrenci sayısı": "ogrenci_sayisi",
        "yoklama": "yoklama", "kaydeden": "kaydeden",
        "uzaktan eğitim": "uzaktan_egitim",
    }

    # Tablo varsa temizle, yoksa olustur
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS etut_detay (
            id SERIAL PRIMARY KEY,
            etut_kodu TEXT,
            sube TEXT,
            etut_turu TEXT,
            tarih TEXT,
            ogretmen TEXT,
            ders TEXT,
            konu TEXT,
            saat TEXT,
            sure TEXT,
            derslik TEXT,
            ogrenci_sayisi TEXT,
            yoklama TEXT,
            kaydeden TEXT,
            uzaktan_egitim TEXT,
            last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(etut_kodu)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_etut_detay_tarih ON etut_detay(tarih)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_etut_detay_ogretmen ON etut_detay(ogretmen)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_etut_detay_ders ON etut_detay(ders)")

    count = 0
    for r in records:
        mapped = {}
        for k, v in r.items():
            key = fm.get(k, k.replace(" ", "_"))
            mapped[key] = v

        etut_kodu = mapped.get("etut_kodu", "")
        if not etut_kodu:
            continue

        await conn.execute("""
            INSERT INTO etut_detay
                (etut_kodu, sube, etut_turu, tarih, ogretmen, ders, konu,
                 saat, sure, derslik, ogrenci_sayisi, yoklama, kaydeden, uzaktan_egitim)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (etut_kodu) DO UPDATE SET
                tarih=EXCLUDED.tarih, ogretmen=EXCLUDED.ogretmen, ders=EXCLUDED.ders,
                yoklama=EXCLUDED.yoklama, last_sync=CURRENT_TIMESTAMP
        """,
            etut_kodu,
            mapped.get("sube", ""),
            mapped.get("etut_turu", ""),
            mapped.get("tarih", ""),
            mapped.get("ogretmen", ""),
            mapped.get("ders", ""),
            mapped.get("konu", ""),
            mapped.get("saat", ""),
            mapped.get("sure", ""),
            mapped.get("derslik", ""),
            mapped.get("ogrenci_sayisi", ""),
            mapped.get("yoklama", ""),
            mapped.get("kaydeden", ""),
            mapped.get("uzaktan_egitim", ""),
        )
        count += 1

    logger.success(f"  {count} etut kaydi DB'ye yazildi")

    # Ozet istatistikler
    total = await conn.fetchval("SELECT COUNT(*) FROM etut_detay")
    tarihs = await conn.fetch("""
        SELECT tarih, COUNT(*) as cnt FROM etut_detay
        GROUP BY tarih ORDER BY tarih DESC LIMIT 10
    """)
    print(f"\netut_detay: {total} kayit")
    print("Son tarihler:")
    for r in tarihs:
        print(f"  {r['tarih']}: {r['cnt']} etut")

    ogretmenler = await conn.fetch("""
        SELECT ogretmen, COUNT(*) as cnt FROM etut_detay
        GROUP BY ogretmen ORDER BY cnt DESC
    """)
    print("\nOgretmen bazli:")
    for r in ogretmenler:
        print(f"  {r['ogretmen']:<25} {r['cnt']} etut")

    dersler = await conn.fetch("""
        SELECT ders, COUNT(*) as cnt FROM etut_detay
        GROUP BY ders ORDER BY cnt DESC
    """)
    print("\nDers bazli:")
    for r in dersler:
        print(f"  {r['ders']:<20} {r['cnt']} etut")

    return count


async def main():
    from eyotek_wrapper import EyotekWrapper, get_session

    pool = await _get_pool()
    conn = await pool.acquire()
    cookies = await get_session()

    async with EyotekWrapper(cookies) as ew:
        records = await scrape_all_etuts(conn, ew)

    if records:
        await save_to_db(conn, records)

    await pool.release(conn)


if __name__ == "__main__":
    asyncio.run(main())
