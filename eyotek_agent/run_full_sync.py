"""
FermatAI — Tam Veri Sync
Eyotek'ten tum verileri cekip PostgreSQL'e yazar.
"""
import asyncio
import json
import os
import time

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)
from db_pool import get_pool as _get_pool


def _int(val) -> int:
    if val is None:
        return 0
    try:
        return int(str(val).strip().replace(".", "").replace(",", ""))
    except (ValueError, TypeError):
        return 0


async def main():
    from eyotek_wrapper import EyotekWrapper, get_session

    pool = await _get_pool()
    conn = await pool.acquire()
    cookies = await get_session()

    async with EyotekWrapper(cookies) as ew:
        # ═══════════════════════════════════════════════════
        # 1. ETUT RAPORLARI (ogretmen bazli)
        # ═══════════════════════════════════════════════════
        print("\n=== 1. ETUT RAPORLARI ===")
        t0 = time.time()
        reports = await ew.get_etut_reports()
        for r in reports:
            await conn.execute("""
                INSERT INTO etut_reports_cache
                    (ogretmen_id, sube, tarih_ay, full_name,
                     toplam_mesai, toplam_ders, toplam_etut, ogrenci_sayisi, basari)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (ogretmen_id, tarih_ay) DO UPDATE SET
                    full_name=EXCLUDED.full_name, toplam_mesai=EXCLUDED.toplam_mesai,
                    toplam_ders=EXCLUDED.toplam_ders, toplam_etut=EXCLUDED.toplam_etut,
                    ogrenci_sayisi=EXCLUDED.ogrenci_sayisi, basari=EXCLUDED.basari,
                    last_sync=CURRENT_TIMESTAMP
            """,
                r.get("ogretmen_id", ""), r.get("sube", ""), r.get("tarih", ""),
                r.get("full_name", ""),
                _int(r.get("toplam_mesai")), _int(r.get("toplam_ders")),
                _int(r.get("toplam_etut")), _int(r.get("ogrenci_sayisi")),
                r.get("basari", ""),
            )
        await conn.execute("UPDATE data_freshness SET last_sync=CURRENT_TIMESTAMP WHERE module='etut_reports'")
        print(f"  {len(reports)} ogretmen etut raporu ({time.time()-t0:.1f}s)")
        for r in reports:
            print(f"    {r.get('full_name','')}: ders={r.get('toplam_ders',0)}, etut={r.get('toplam_etut',0)}, ogrenci={r.get('ogrenci_sayisi',0)}")

        # ═══════════════════════════════════════════════════
        # 2. ETUT OGRENCI KONTROL
        # ═══════════════════════════════════════════════════
        print("\n=== 2. ETUT OGRENCI KONTROL ===")
        t0 = time.time()
        controls = await ew.get_etut_student_control()
        for r in controls:
            soz_no = r.get("soz_no", "")
            if not soz_no:
                continue
            await conn.execute("""
                INSERT INTO etut_student_control_cache
                    (soz_no, okul_no, ad, soyad, devre, sinif,
                     yapildi, gelmedi, kontrol_edilmedi, toplam)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (soz_no) DO UPDATE SET
                    ad=EXCLUDED.ad, soyad=EXCLUDED.soyad, sinif=EXCLUDED.sinif,
                    yapildi=EXCLUDED.yapildi, gelmedi=EXCLUDED.gelmedi,
                    kontrol_edilmedi=EXCLUDED.kontrol_edilmedi, toplam=EXCLUDED.toplam,
                    last_sync=CURRENT_TIMESTAMP
            """,
                soz_no, r.get("okul_no", ""),
                r.get("ad", ""), r.get("soyad", ""),
                r.get("devre", ""), r.get("sinif", ""),
                _int(r.get("yapildi")), _int(r.get("gelmedi")),
                _int(r.get("kontrol_edilmedi")), _int(r.get("toplam")),
            )
        await conn.execute("UPDATE data_freshness SET last_sync=CURRENT_TIMESTAMP WHERE module='etut_student_control'")
        print(f"  {len(controls)} ogrenci etut kontrol ({time.time()-t0:.1f}s)")

        # ═══════════════════════════════════════════════════
        # 3. OGRETMEN DERS PROGRAMI (timetable-staff-list)
        # ═══════════════════════════════════════════════════
        print("\n=== 3. OGRETMEN DERS PROGRAMI ===")
        t0 = time.time()
        result = await ew.get_teacher_schedule()
        print(f"  {len(result)} ogretmen bilgisi cekildi")
        for r in result:
            print(f"    id={r.get('id','')}, {r.get('full_name','')}, brans={r.get('brans','')}, saat={r.get('saat','')}")

        with open("teacher_schedule_dump.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    # ═══════════════════════════════════════════════════
    # FINAL OZET
    # ═══════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("SYNC OZET")
    print("=" * 60)
    tables = [
        "class_roster", "etut_reports_cache", "etut_student_control_cache",
        "teacher_timetable", "class_timetable", "carsaf_liste_cache",
    ]
    for tbl in tables:
        try:
            cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
            print(f"  {tbl:<35} {cnt:>6} kayit")
        except Exception:
            print(f"  {tbl:<35}    BOS")

    # data_freshness durumu
    print()
    rows = await conn.fetch(
        "SELECT module, last_sync FROM data_freshness ORDER BY module"
    )
    for r in rows:
        last = r["last_sync"].strftime("%Y-%m-%d %H:%M") if r["last_sync"] else "---"
        print(f"  {r['module']:<25} son sync: {last}")

    await conn.close()
    print("\nTamamlandi!")


if __name__ == "__main__":
    asyncio.run(main())
