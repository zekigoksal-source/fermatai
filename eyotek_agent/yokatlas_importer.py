"""
YÖK Atlas Tercih Sihirbazı — Community library tabanlı scraper (C3)
=====================================================================

yokatlas-py kutuphanesi ile anti-scraping bypass (official endpoint kullanir).
Her kayit 4 yillik (2022-2025) taban+siralama+kontenjan iceriyor →
universite_taban tablosuna yila gore 4 ayri satir insert edilir.

Kullanim:
    python yokatlas_importer.py --puan-turu SAY
    python yokatlas_importer.py --all  # SAY+SOZ+EA+DIL
    python yokatlas_importer.py --all --limit 500  # ilk 500 bolum / puan turu

Sure: ~1000 bolum × 4 yil = ~4000 kayit / puan turu, 20-30 dk.
"""
import asyncio
import sys
import io
import os
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(override=True)

import asyncpg
from yokatlas_py import YOKATLASLisansTercihSihirbazi


# puan_turu eslemesi: library kucuk harf ister
PUAN_TURU_MAP = {"SAY": "say", "SOZ": "soz", "EA": "ea", "DIL": "dil"}


def _to_float(v):
    """Taban puan parse — '550.89027' tarzinda string gelir."""
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except Exception:
        return None


def _to_int(v):
    """Siralama parse — '43' veya '1.234' tarzinda."""
    if v is None or v == "" or v == "-":
        return None
    try:
        return int(str(v).replace(".", "").replace(",", "").strip())
    except Exception:
        return None


def _kontenjan_total(kontenjan_str):
    """'6+0+1+0+1' formatinda toplam — TOPLAM yerlesen icin."""
    if not kontenjan_str:
        return None
    try:
        parts = str(kontenjan_str).split("+")
        return sum(int(p.strip()) for p in parts if p.strip().isdigit())
    except Exception:
        return None


async def scrape_puan_turu(puan_turu_upper: str, pool, max_records: int = 5000):
    """
    Bir puan turu icin tum bolumleri start=0'dan itibaren paginate et.
    Her bolumun 4 yillik verisi DB'ye ayri satirlar olarak insert edilir.
    """
    pt_lower = PUAN_TURU_MAP[puan_turu_upper]
    print(f"\n🔍 {puan_turu_upper} basliyor... (max {max_records} bolum)")

    start = 0
    total_programs = 0
    total_inserted = 0
    total_updated = 0
    consecutive_empty = 0

    while start < max_records:
        try:
            api = YOKATLASLisansTercihSihirbazi({"puan_turu": pt_lower, "start": start})
            # Library sync — to_thread ile async ortama sok
            rows = await asyncio.to_thread(api.search)
        except Exception as e:
            print(f"  [!] Fetch hata start={start}: {e}")
            await asyncio.sleep(2.0)
            consecutive_empty += 1
            if consecutive_empty >= 3:
                print("  ⚠ 3 ardisik hata — dur")
                break
            continue

        if not rows:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                print("  ✅ Son sayfaya ulasildi")
                break
            await asyncio.sleep(1.0)
            continue

        consecutive_empty = 0
        # DB insert — her program × 4 yil = 4 satir
        async with pool.acquire() as conn:
            for r in rows:
                total_programs += 1
                taban = r.get("taban", {}) or {}
                tbs = r.get("tbs", {}) or {}
                kontenjan = r.get("kontenjan", {}) or {}

                # program + alt detay — bolum field
                bolum_ana = r.get("program_adi", "").strip()
                detay = r.get("program_detay", "").strip()
                bolum_full = f"{bolum_ana} {detay}".strip() if detay else bolum_ana
                # Uzun program_detay truncate (DB limit)
                bolum_full = bolum_full[:300]

                universite = r.get("uni_adi", "").strip()[:200]
                sehir = r.get("sehir_adi", "").strip()[:80]
                tur = r.get("universite_turu", "Devlet").strip()

                for yil_str in ("2022", "2023", "2024", "2025"):
                    taban_v = _to_float(taban.get(yil_str))
                    if taban_v is None:
                        continue  # o yil veri yoksa atla
                    siralama_v = _to_int(tbs.get(yil_str))
                    kontenjan_v = _kontenjan_total(kontenjan.get(yil_str))

                    try:
                        res = await conn.execute(
                            """
                            INSERT INTO universite_taban
                                (yil, universite, bolum, puan_turu, taban_puan,
                                 siralama, kontenjan, sehir, tur, created_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                            ON CONFLICT DO NOTHING
                            """,
                            int(yil_str), universite, bolum_full, puan_turu_upper,
                            taban_v, siralama_v, kontenjan_v, sehir, tur,
                        )
                        # 'INSERT 0 1' = eklendi, 'INSERT 0 0' = conflict
                        if res.endswith("1"):
                            total_inserted += 1
                        else:
                            total_updated += 1
                    except Exception as e:
                        pass  # bozuk satiri atla

        if start % 500 == 0 or len(rows) < 50:
            print(f"  start={start}: +{len(rows)} program (toplam: {total_programs}, insert: {total_inserted})")
        start += 50
        if len(rows) < 50:
            break
        await asyncio.sleep(0.3)  # rate limit

    print(f"✅ {puan_turu_upper} tamamlandi: {total_programs} program / {total_inserted} yeni kayit / {total_updated} conflict")
    return total_programs, total_inserted


async def ensure_table(pool):
    """universite_taban tablosu var mi kontrol et + unique constraint."""
    async with pool.acquire() as conn:
        # Unique constraint: (yil, universite, bolum, puan_turu) — duplicate onleme icin
        try:
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_universite_taban_unique
                ON universite_taban (yil, universite, bolum, puan_turu)
            """)
        except Exception as e:
            print(f"Index warn: {e}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--puan-turu", type=str, default="SAY",
                        choices=["SAY", "SOZ", "EA", "DIL"])
    parser.add_argument("--all", action="store_true", help="Tum puan turleri")
    parser.add_argument("--limit", type=int, default=5000, help="Max bolum / puan turu")
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL yok — .env kontrol et")
        return

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    try:
        await ensure_table(pool)

        before = await pool.fetchval("SELECT COUNT(*) FROM universite_taban")
        print(f"DB mevcut: {before} kayit")

        if args.all:
            grand_total = 0
            grand_inserted = 0
            for pt in ("SAY", "EA", "SOZ", "DIL"):
                p, i = await scrape_puan_turu(pt, pool, args.limit)
                grand_total += p
                grand_inserted += i
            print(f"\n🎉 GENEL: {grand_total} program, {grand_inserted} yeni kayit")
        else:
            await scrape_puan_turu(args.puan_turu, pool, args.limit)

        after = await pool.fetchval("SELECT COUNT(*) FROM universite_taban")
        min_p = await pool.fetchval(
            "SELECT MIN(taban_puan) FROM universite_taban WHERE taban_puan > 100"
        )
        max_p = await pool.fetchval("SELECT MAX(taban_puan) FROM universite_taban")
        yil_dist = await pool.fetch(
            "SELECT yil, COUNT(*) FROM universite_taban GROUP BY yil ORDER BY yil"
        )
        pt_dist = await pool.fetch(
            "SELECT puan_turu, COUNT(*) FROM universite_taban GROUP BY puan_turu"
        )
        print(f"\n📊 DB son durumu: {after} kayit (+{after - before})")
        print(f"   Puan araligi: {min_p} - {max_p}")
        print(f"   Yil dagilimi: {dict((r['yil'], r['count']) for r in yil_dist)}")
        print(f"   Puan turu:    {dict((r['puan_turu'], r['count']) for r in pt_dist)}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
