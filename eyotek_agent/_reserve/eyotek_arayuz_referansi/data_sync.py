"""
FermatAI — Data Sync: Eyotek → PostgreSQL Local Cache
=====================================================
Eyotek LMS'den verileri çekip PostgreSQL'e yazar.
Agent (LLM) bu cache'den hızlıca okur, Eyotek'e girmez.

Kullanım:
    python data_sync.py --all              # Tüm modülleri güncelle
    python data_sync.py --module etut_reports
    python data_sync.py --module class_roster
    python data_sync.py --stale            # Sadece bayat olanları güncelle
    python data_sync.py --list             # Modüllerin tazelik durumu

Modüller ve güncelleme sıklıkları:
    daily:   students, attendance, etut_reports, etut_student_control
    weekly:  staff, class_roster, exams, exam_results
    monthly: class_timetable, teacher_timetable, carsaf_liste
"""

import asyncio
import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from loguru import logger
import os

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai")


async def get_pool():
    return await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)


async def log_sync(pool, module: str, count: int, errors: int, duration: float):
    """Sync logunu yaz ve data_freshness tablosunu güncelle."""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO sync_log (module, count, errors, duration_s)
            VALUES ($1, $2, $3, $4)
        """, module, count, errors, duration)
        await conn.execute("""
            UPDATE data_freshness SET last_sync = CURRENT_TIMESTAMP
            WHERE module = $1
        """, module)


# ═══════════════════════════════════════════════════════════════
# SYNC: Etüt Raporları
# ═══════════════════════════════════════════════════════════════
async def sync_etut_reports(pool, ew):
    """Öğretmen bazlı etüt raporlarını çek ve cache'e yaz."""
    logger.info("== sync_etut_reports ==")
    t0 = time.time()
    records = await ew.get_etut_reports()
    count = 0
    for r in records:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO etut_reports_cache
                    (ogretmen_id, sube, tarih_ay, full_name,
                     toplam_mesai, toplam_ders, toplam_etut, ogrenci_sayisi, basari)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (ogretmen_id, tarih_ay) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    toplam_mesai = EXCLUDED.toplam_mesai,
                    toplam_ders = EXCLUDED.toplam_ders,
                    toplam_etut = EXCLUDED.toplam_etut,
                    ogrenci_sayisi = EXCLUDED.ogrenci_sayisi,
                    basari = EXCLUDED.basari,
                    last_sync = CURRENT_TIMESTAMP
            """,
                r.get("ogretmen_id", ""),
                r.get("sube", ""),
                r.get("tarih", ""),
                r.get("full_name", ""),
                _int(r.get("toplam_mesai")),
                _int(r.get("toplam_ders")),
                _int(r.get("toplam_etut")),
                _int(r.get("ogrenci_sayisi")),
                r.get("basari", ""),
            )
            count += 1
    dur = time.time() - t0
    await log_sync(pool, "etut_reports", count, 0, dur)
    logger.success(f"  etut_reports: {count} kayit, {dur:.1f}s")
    return count


# ═══════════════════════════════════════════════════════════════
# SYNC: Etüt Öğrenci Kontrol
# ═══════════════════════════════════════════════════════════════
async def sync_etut_student_control(pool, ew):
    """Öğrenci bazlı etüt katılım durumunu çek ve cache'e yaz."""
    logger.info("== sync_etut_student_control ==")
    t0 = time.time()
    records = await ew.get_etut_student_control()
    count = 0
    for r in records:
        soz_no = r.get("soz_no", "")
        if not soz_no:
            continue
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO etut_student_control_cache
                    (soz_no, okul_no, ad, soyad, devre, sinif,
                     yapildi, gelmedi, kontrol_edilmedi, toplam)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (soz_no) DO UPDATE SET
                    okul_no = EXCLUDED.okul_no,
                    ad = EXCLUDED.ad, soyad = EXCLUDED.soyad,
                    devre = EXCLUDED.devre, sinif = EXCLUDED.sinif,
                    yapildi = EXCLUDED.yapildi, gelmedi = EXCLUDED.gelmedi,
                    kontrol_edilmedi = EXCLUDED.kontrol_edilmedi,
                    toplam = EXCLUDED.toplam,
                    last_sync = CURRENT_TIMESTAMP
            """,
                soz_no, r.get("okul_no", ""),
                r.get("ad", ""), r.get("soyad", ""),
                r.get("devre", ""), r.get("sinif", ""),
                _int(r.get("yapildi")), _int(r.get("gelmedi")),
                _int(r.get("kontrol_edilmedi")), _int(r.get("toplam")),
            )
            count += 1
    dur = time.time() - t0
    await log_sync(pool, "etut_student_control", count, 0, dur)
    logger.success(f"  etut_student_control: {count} kayit, {dur:.1f}s")
    return count


# ═══════════════════════════════════════════════════════════════
# SYNC: Sınıf Kadroları (tüm sınıflar)
# ═══════════════════════════════════════════════════════════════
async def sync_class_roster(pool, ew):
    """Tüm sınıfların öğrenci kadrosunu çek ve cache'e yaz."""
    logger.info("== sync_class_roster ==")
    t0 = time.time()
    all_rosters = await ew.get_all_class_rosters()
    count = 0
    errors = 0
    async with pool.acquire() as conn:
        # Eski verileri temizle (full refresh)
        await conn.execute("DELETE FROM class_roster")
        for sinif_name, data in all_rosters.items():
            devre = data.get("devre", "")
            for st in data.get("students", []):
                try:
                    await conn.execute("""
                        INSERT INTO class_roster
                            (sinif, devre, soz_no, okul_no, ad, soyad,
                             mudur, mudur_yardimcisi, rehber, sinif_ogretmeni, danisman)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    """,
                        sinif_name, devre,
                        st.get("söz no", ""), st.get("okul no", ""),
                        st.get("adı", ""), st.get("soyadı", ""),
                        st.get("müdür", ""), st.get("müdür yardımcısı", ""),
                        st.get("rehber", ""), st.get("sınıf öğretmeni", ""),
                        st.get("danışman", ""),
                    )
                    count += 1
                except Exception as e:
                    logger.warning(f"  class_roster insert error: {e}")
                    errors += 1
    dur = time.time() - t0
    await log_sync(pool, "class_roster", count, errors, dur)
    logger.success(f"  class_roster: {count} kayit, {errors} hata, {dur:.1f}s")
    return count


# ═══════════════════════════════════════════════════════════════
# SYNC: Öğretmen Ders Programı
# ═══════════════════════════════════════════════════════════════
async def sync_teacher_timetable(pool, ew):
    """Tüm öğretmenlerin haftalık ders programını çek ve cache'e yaz."""
    logger.info("== sync_teacher_timetable ==")
    t0 = time.time()
    result = await ew.get_teacher_timetable()
    teachers = result.get("teachers", [])
    count = 0

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM teacher_timetable")

        for teacher in teachers:
            tid = teacher.get("id", "")
            if not tid:
                continue
            # Her ogretmene tikla ve programini al
            detail = await ew.get_teacher_timetable(teacher_id=tid)
            tt = detail.get("timetable", {})
            if not tt.get("found"):
                continue

            headers = tt.get("headers", [])
            rows = tt.get("rows", [])
            # Headers: Saat, Pazartesi, Salı, ..., Saat, Cumartesi, Pazar
            # Her satir: saat_baslangic, ders_bilgisi_pazartesi, ..., saat_bitis, ders_cumartesi, ...
            days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
            for row in rows:
                if len(row) < 2:
                    continue
                saat = row[0].split("\n")[0].strip() if row[0] else ""
                if not saat:
                    continue
                for i, day in enumerate(days):
                    col_idx = i + 1  # Pazartesi = 1, Sali = 2, ...
                    if col_idx >= len(row):
                        # Cumartesi/Pazar sag tarafta olabilir
                        # Headers'da ikinci "Saat" sonrasi
                        saat_idx2 = None
                        for hi, h in enumerate(headers):
                            if h.strip().lower() == "saat" and hi > 0:
                                saat_idx2 = hi
                                break
                        if saat_idx2 and i >= 5:
                            alt_idx = saat_idx2 + (i - 5) + 1
                            if alt_idx < len(row) and row[alt_idx].strip():
                                cell = row[alt_idx].strip()
                                ders, ogr, drslk = _parse_timetable_cell(cell)
                                if ders or ogr:
                                    await conn.execute("""
                                        INSERT INTO teacher_timetable
                                            (ogretmen_id, ogretmen_ad, brans, haftalik_saat,
                                             gun, saat, sinif, ders, derslik)
                                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                                    """, tid, teacher.get("full_name", ""),
                                        teacher.get("brans", ""),
                                        _int(teacher.get("saat")),
                                        day, saat, ders, ogr, drslk)
                                    count += 1
                        continue
                    cell = row[col_idx].strip() if col_idx < len(row) else ""
                    if not cell:
                        continue
                    # Cell format: "[7] MEZUN SAY A\nDers: Fizik\nDerslik: D-1"
                    sinif, ders, derslik = _parse_timetable_cell(cell)
                    if sinif or ders:
                        await conn.execute("""
                            INSERT INTO teacher_timetable
                                (ogretmen_id, ogretmen_ad, brans, haftalik_saat,
                                 gun, saat, sinif, ders, derslik)
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        """, tid, teacher.get("full_name", ""),
                            teacher.get("brans", ""),
                            _int(teacher.get("saat")),
                            day, saat, sinif, ders, derslik)
                        count += 1

    dur = time.time() - t0
    await log_sync(pool, "teacher_timetable", count, 0, dur)
    logger.success(f"  teacher_timetable: {count} slot, {dur:.1f}s")
    return count


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _int(val) -> int:
    """Güvenli int dönüşümü."""
    if val is None:
        return 0
    try:
        return int(str(val).strip().replace(".", "").replace(",", ""))
    except (ValueError, TypeError):
        return 0


def _parse_timetable_cell(cell: str) -> tuple[str, str, str]:
    """
    Ders programı hücresini parse et.
    Format: "[7] MEZUN SAY A\nDers: Fizik\nDerslik: D-1"
    veya:   "Fizik\nÖğrt: ÖRSEL KOÇ\nDerslik: D-1"
    Returns: (sinif_veya_ders, ogretmen_veya_ders, derslik)
    """
    if not cell:
        return ("", "", "")
    lines = [l.strip() for l in cell.split("\n") if l.strip()]
    sinif = ""
    ders = ""
    derslik = ""
    ogretmen = ""
    for line in lines:
        low = line.lower()
        if low.startswith("ders:"):
            ders = line.split(":", 1)[1].strip()
        elif low.startswith("derslik:"):
            derslik = line.split(":", 1)[1].strip()
        elif low.startswith("öğrt:") or low.startswith("ogrt:"):
            ogretmen = line.split(":", 1)[1].strip()
        elif line.startswith("[") or any(c.isdigit() for c in line[:5]):
            sinif = line
        else:
            if not ders:
                ders = line
            elif not ogretmen:
                ogretmen = line
    return (sinif or ders, ogretmen or ders, derslik)


# ═══════════════════════════════════════════════════════════════
# STALE CHECK — hangi modüller bayat?
# ═══════════════════════════════════════════════════════════════
async def get_stale_modules(pool) -> list[str]:
    """Güncelleme zamanı geçmiş modülleri döndür."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT module, refresh_type, interval_hrs, last_sync
            FROM data_freshness
            ORDER BY module
        """)
    stale = []
    now = datetime.now()
    for row in rows:
        last = row["last_sync"]
        interval = timedelta(hours=row["interval_hrs"])
        if last is None or (now - last) > interval:
            stale.append(row["module"])
    return stale


async def list_freshness(pool):
    """Tüm modüllerin tazelik durumunu göster."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT module, refresh_type, interval_hrs, last_sync,
                   CASE WHEN last_sync IS NULL THEN 'HIC_SYNC_YOK'
                        WHEN CURRENT_TIMESTAMP - last_sync > make_interval(hours => interval_hrs)
                        THEN 'BAYAT'
                        ELSE 'TAZE'
                   END as durum
            FROM data_freshness
            ORDER BY module
        """)
    print(f"\n{'Modul':<25} {'Tip':<10} {'Aralik':<10} {'Son Sync':<22} {'Durum':<15}")
    print("-" * 82)
    for r in rows:
        last = r["last_sync"].strftime("%Y-%m-%d %H:%M") if r["last_sync"] else "---"
        print(f"{r['module']:<25} {r['refresh_type']:<10} {r['interval_hrs']}h{'':<7} {last:<22} {r['durum']:<15}")
    print()


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

# Module → sync function mapping
SYNC_MODULES = {
    "etut_reports": sync_etut_reports,
    "etut_student_control": sync_etut_student_control,
    "class_roster": sync_class_roster,
    "teacher_timetable": sync_teacher_timetable,
    # Asagidakiler eyotek_agent.py'de mevcut, buraya tasinacak:
    # "students": sync_students,
    # "staff": sync_staff,
    # "attendance": sync_attendance,
}


async def main():
    parser = argparse.ArgumentParser(description="FermatAI Data Sync")
    parser.add_argument("--all", action="store_true", help="Tüm modülleri güncelle")
    parser.add_argument("--module", type=str, help="Tek modül güncelle")
    parser.add_argument("--stale", action="store_true", help="Sadece bayat modülleri güncelle")
    parser.add_argument("--list", action="store_true", help="Tazelik durumunu göster")
    args = parser.parse_args()

    pool = await get_pool()

    if args.list:
        await list_freshness(pool)
        await pool.close()
        return

    if not (args.all or args.module or args.stale):
        print("Kullanim: python data_sync.py --all | --module <isim> | --stale | --list")
        await pool.close()
        return

    # Eyotek wrapper baslat
    from eyotek_wrapper import EyotekWrapper, get_session
    cookies = await get_session()
    async with EyotekWrapper(cookies) as ew:
        if args.module:
            fn = SYNC_MODULES.get(args.module)
            if fn:
                await fn(pool, ew)
            else:
                print(f"Bilinmeyen modul: {args.module}")
                print(f"Mevcut moduller: {', '.join(SYNC_MODULES.keys())}")
        elif args.stale:
            stale = await get_stale_modules(pool)
            if not stale:
                logger.info("Tum moduller taze!")
            else:
                logger.info(f"Bayat moduller: {stale}")
                for mod in stale:
                    fn = SYNC_MODULES.get(mod)
                    if fn:
                        await fn(pool, ew)
        elif args.all:
            for mod, fn in SYNC_MODULES.items():
                try:
                    await fn(pool, ew)
                except Exception as e:
                    logger.error(f"  {mod} hatasi: {e}")

    await pool.close()
    logger.success("Sync tamamlandi!")


if __name__ == "__main__":
    asyncio.run(main())
