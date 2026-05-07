"""
FermatAI — Ders Programı Scraper v2
Mekanizma: kutucuk tikla → mavi ok tikla → sag panelde program gorulur
Tablo ID'leri:
  - Ogretmen: GridView1 (liste), GrdDersProgrami (haftalik), GrdSinifRaporu, GrdDersRaporu
  - Sinif: benzer yapi
"""
import asyncio
import json
import os
import time

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)
from db_pool import get_pool as _get_pool

DAYS_WEEKDAY = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma"]
DAYS_WEEKEND = ["Cumartesi", "Pazar"]


def parse_cell(cell: str) -> dict:
    """'[7] MEZUN SAY A\nDers: Türkçe\nDerslik: D-1' → {sinif, ders, derslik}"""
    if not cell or not cell.strip():
        return {}
    lines = [l.strip() for l in cell.split("\n") if l.strip()]
    r = {}
    for line in lines:
        low = line.lower()
        if low.startswith("ders:") and "derslik" not in low:
            r["ders"] = line.split(":", 1)[1].strip()
        elif low.startswith("derslik:"):
            r["derslik"] = line.split(":", 1)[1].strip()
        elif low.startswith("öğrt:") or low.startswith("ogrt:"):
            r["ogretmen"] = line.split(":", 1)[1].strip()
        elif not r.get("sinif"):
            r["sinif"] = line
    return r


async def scrape_teacher_timetables(conn, ew):
    """14 ogretmenin haftalik ders programini cek."""
    logger.info("=== OGRETMEN DERS PROGRAMLARI ===")
    t0 = time.time()

    await ew._goto("Pages/Student/timetable-staff-list")
    await asyncio.sleep(2)

    # Ogretmen listesi (GridView1)
    teachers = await ew._page.evaluate("""
        () => {
            const tbl = document.getElementById('GridView1');
            if (!tbl) return [];
            const result = [];
            tbl.querySelectorAll('tbody tr, tr').forEach((tr, idx) => {
                const cells = Array.from(tr.querySelectorAll('td'));
                const texts = cells.map(c => c.innerText.trim());
                const idCell = texts.find(t => /^\\d{4}$/.test(t));
                if (idCell) {
                    const idIdx = texts.indexOf(idCell);
                    result.push({
                        id: idCell,
                        name: texts[idIdx+1] || '',
                        brans: texts[idIdx+2] || '',
                        saat: texts[idIdx+3] || '',
                        rowIndex: idx
                    });
                }
            });
            return result;
        }
    """)
    logger.info(f"  {len(teachers)} ogretmen bulundu")

    await conn.execute("DELETE FROM teacher_timetable")
    total_slots = 0

    for i, teacher in enumerate(teachers):
        tid = teacher["id"]
        tname = teacher["name"]
        logger.info(f"  [{i+1}/{len(teachers)}] {tname} ({teacher['brans']})...")

        # 1. Kutucuk tikla
        await ew._page.evaluate(f"""
            (targetId) => {{
                const tbl = document.getElementById('GridView1');
                const rows = tbl.querySelectorAll('tbody tr, tr');
                for (const tr of rows) {{
                    const cells = Array.from(tr.querySelectorAll('td'));
                    if (cells.some(c => c.innerText.trim() === targetId)) {{
                        const cb = tr.querySelector('input[type=checkbox]');
                        if (cb && !cb.checked) cb.click();
                        return true;
                    }}
                }}
                return false;
            }}
        """, tid)
        await asyncio.sleep(0.5)

        # 2. Mavi ok tikla
        await ew._page.evaluate(f"""
            (targetId) => {{
                const tbl = document.getElementById('GridView1');
                const rows = tbl.querySelectorAll('tbody tr, tr');
                for (const tr of rows) {{
                    const cells = Array.from(tr.querySelectorAll('td'));
                    if (cells.some(c => c.innerText.trim() === targetId)) {{
                        const arrow = tr.querySelector('a.btn-info');
                        if (arrow) {{ arrow.click(); return true; }}
                    }}
                }}
                return false;
            }}
        """, tid)
        await asyncio.sleep(2)

        # 3. GrdDersProgrami tablosunu oku
        timetable = await ew._page.evaluate("""
            () => {
                const tblId = 'ComponentStaffTimetableWatchPlace1_GrdDersProgrami';
                const tbl = document.getElementById(tblId);
                if (!tbl) return {found: false};
                const headers = Array.from(tbl.querySelectorAll('th')).map(h => h.innerText.trim());
                const rows = [];
                tbl.querySelectorAll('tbody tr').forEach(tr => {
                    const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                    if (cells.some(c => c)) rows.push(cells);
                });
                return {found: true, headers, rows};
            }
        """)

        if not timetable.get("found"):
            logger.warning(f"    Program bulunamadi")
            # Kutucugu kaldir
            await ew._page.evaluate(f"""
                (targetId) => {{
                    const tbl = document.getElementById('GridView1');
                    const rows = tbl.querySelectorAll('tbody tr, tr');
                    for (const tr of rows) {{
                        const cells = Array.from(tr.querySelectorAll('td'));
                        if (cells.some(c => c.innerText.trim() === targetId)) {{
                            const cb = tr.querySelector('input[type=checkbox]');
                            if (cb && cb.checked) cb.click();
                        }}
                    }}
                }}
            """, tid)
            continue

        headers = timetable["headers"]
        rows = timetable["rows"]
        slot_count = 0

        for row in rows:
            if len(row) < 2:
                continue
            saat = row[0].split("\n")[0].split(" ")[0].strip()
            if not saat or ":" not in saat:
                continue

            # Hafta ici (col 1-5)
            for day_idx, day_name in enumerate(DAYS_WEEKDAY):
                col = day_idx + 1
                if col >= len(row) or not row[col].strip():
                    continue
                parsed = parse_cell(row[col])
                if parsed:
                    await conn.execute("""
                        INSERT INTO teacher_timetable
                            (ogretmen_id, ogretmen_ad, brans, haftalik_saat,
                             gun, saat, sinif, ders, derslik)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT (ogretmen_id, gun, saat) DO UPDATE SET
                            sinif=EXCLUDED.sinif, ders=EXCLUDED.ders, derslik=EXCLUDED.derslik,
                            last_sync=CURRENT_TIMESTAMP
                    """,
                        tid, tname, teacher["brans"],
                        int(teacher["saat"]) if teacher["saat"].isdigit() else 0,
                        day_name, saat,
                        parsed.get("sinif", ""),
                        parsed.get("ders", ""),
                        parsed.get("derslik", ""),
                    )
                    slot_count += 1

            # Hafta sonu (col 7=Cumartesi, col 8=Pazar — Saat col 6)
            saat2_col = 6
            if saat2_col < len(row):
                saat2 = row[saat2_col].split("\n")[0].split(" ")[0].strip()
            else:
                saat2 = saat
            for day_offset, day_name in enumerate(DAYS_WEEKEND):
                col = saat2_col + day_offset + 1  # 7, 8
                if col >= len(row) or not row[col].strip():
                    continue
                parsed = parse_cell(row[col])
                if parsed:
                    await conn.execute("""
                        INSERT INTO teacher_timetable
                            (ogretmen_id, ogretmen_ad, brans, haftalik_saat,
                             gun, saat, sinif, ders, derslik)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT (ogretmen_id, gun, saat) DO UPDATE SET
                            sinif=EXCLUDED.sinif, ders=EXCLUDED.ders, derslik=EXCLUDED.derslik,
                            last_sync=CURRENT_TIMESTAMP
                    """,
                        tid, tname, teacher["brans"],
                        int(teacher["saat"]) if teacher["saat"].isdigit() else 0,
                        day_name, saat2 or saat,
                        parsed.get("sinif", ""),
                        parsed.get("ders", ""),
                        parsed.get("derslik", ""),
                    )
                    slot_count += 1

        total_slots += slot_count
        logger.info(f"    {slot_count} ders slotu")

        # Kutucugu kaldir (sonraki ogretmen icin)
        await ew._page.evaluate(f"""
            (targetId) => {{
                const tbl = document.getElementById('GridView1');
                const rows = tbl.querySelectorAll('tbody tr, tr');
                for (const tr of rows) {{
                    const cells = Array.from(tr.querySelectorAll('td'));
                    if (cells.some(c => c.innerText.trim() === targetId)) {{
                        const cb = tr.querySelector('input[type=checkbox]');
                        if (cb && cb.checked) cb.click();
                    }}
                }}
            }}
        """, tid)
        await asyncio.sleep(0.3)

    await conn.execute("UPDATE data_freshness SET last_sync=CURRENT_TIMESTAMP WHERE module='teacher_timetable'")
    logger.success(f"  TOPLAM: {total_slots} slot ({time.time()-t0:.1f}s)")
    return total_slots


async def scrape_class_timetables(conn, ew):
    """13 sinifin haftalik ders programini cek."""
    logger.info("\n=== SINIF DERS PROGRAMLARI ===")
    t0 = time.time()

    await ew._goto("Pages/Student/timetable-class-list")
    await asyncio.sleep(2)

    classes = await ew._page.evaluate("""
        () => {
            const tbl = document.getElementById('GrdClasses');
            if (!tbl) return [];
            const result = [];
            tbl.querySelectorAll('tbody tr, tr').forEach((tr, idx) => {
                const cells = Array.from(tr.querySelectorAll('td'));
                const texts = cells.map(c => c.innerText.trim()).filter(t => t);
                // Devre, Sinif, Saat — sinif texts[1]'de ([ ile baslar)
                const sinifText = texts.find(t => t.startsWith('['));
                if (sinifText) {
                    const devreText = texts.find(t => t.includes('Snf') || t === 'Mezun') || '';
                    const saatText = texts.find(t => /^\\d+$/.test(t)) || '0';
                    result.push({sinif: sinifText, devre: devreText, saat: saatText, index: idx});
                }
            });
            return result;
        }
    """)
    logger.info(f"  {len(classes)} sinif bulundu")

    await conn.execute("DELETE FROM class_timetable")
    total_slots = 0

    for i, cls in enumerate(classes):
        sinif = cls["sinif"]
        logger.info(f"  [{i+1}/{len(classes)}] {sinif}...")

        # 1. Kutucuk tikla + 2. Mavi ok tikla (GrdClasses icinden)
        await ew._page.evaluate(f"""
            (targetSinif) => {{
                const tbl = document.getElementById('GrdClasses');
                if (!tbl) return false;
                const rows = tbl.querySelectorAll('tbody tr, tr');
                for (const tr of rows) {{
                    if (tr.innerText.includes(targetSinif)) {{
                        const cb = tr.querySelector('input[type=checkbox]');
                        if (cb && !cb.checked) cb.click();
                        return true;
                    }}
                }}
                return false;
            }}
        """, sinif)
        await asyncio.sleep(0.5)

        await ew._page.evaluate(f"""
            (targetSinif) => {{
                const tbl = document.getElementById('GrdClasses');
                if (!tbl) return false;
                const rows = tbl.querySelectorAll('tbody tr, tr');
                for (const tr of rows) {{
                    if (tr.innerText.includes(targetSinif)) {{
                        const arrow = tr.querySelector('a.btn-info');
                        if (arrow) {{ arrow.click(); return true; }}
                    }}
                }}
                return false;
            }}
        """, sinif)
        await asyncio.sleep(2)

        # 3. Ders programi tablosunu oku (Pazartesi header'i olan)
        timetable = await ew._page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                for (const tbl of tables) {
                    const ths = Array.from(tbl.querySelectorAll('th')).map(h => h.innerText.trim());
                    if (ths.some(h => h === 'Pazartesi')) {
                        const rows = [];
                        tbl.querySelectorAll('tbody tr').forEach(tr => {
                            const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                            if (cells.some(c => c)) rows.push(cells);
                        });
                        return {found: true, headers: ths, rows};
                    }
                }
                return {found: false};
            }
        """)

        if not timetable.get("found"):
            logger.warning(f"    Program bulunamadi")
            continue

        rows = timetable["rows"]
        slot_count = 0
        for row in rows:
            if len(row) < 2:
                continue
            saat = row[0].split("\n")[0].split(" ")[0].strip()
            if not saat or ":" not in saat:
                continue
            for day_idx, day_name in enumerate(DAYS_WEEKDAY):
                col = day_idx + 1
                if col >= len(row) or not row[col].strip():
                    continue
                parsed = parse_cell(row[col])
                if parsed:
                    await conn.execute("""
                        INSERT INTO class_timetable (sinif, gun, saat, ders, ogretmen, derslik)
                        VALUES ($1,$2,$3,$4,$5,$6)
                        ON CONFLICT (sinif, gun, saat) DO UPDATE SET
                            ders=EXCLUDED.ders, ogretmen=EXCLUDED.ogretmen, derslik=EXCLUDED.derslik,
                            last_sync=CURRENT_TIMESTAMP
                    """, sinif, day_name, saat,
                        parsed.get("ders", parsed.get("sinif", "")),
                        parsed.get("ogretmen", ""),
                        parsed.get("derslik", ""),
                    )
                    slot_count += 1
            # Hafta sonu
            saat2_col = 6
            if saat2_col < len(row):
                saat2 = row[saat2_col].split("\n")[0].split(" ")[0].strip()
            else:
                saat2 = saat
            for day_offset, day_name in enumerate(DAYS_WEEKEND):
                col = saat2_col + day_offset + 1
                if col >= len(row) or not row[col].strip():
                    continue
                parsed = parse_cell(row[col])
                if parsed:
                    await conn.execute("""
                        INSERT INTO class_timetable (sinif, gun, saat, ders, ogretmen, derslik)
                        VALUES ($1,$2,$3,$4,$5,$6)
                        ON CONFLICT (sinif, gun, saat) DO UPDATE SET
                            ders=EXCLUDED.ders, ogretmen=EXCLUDED.ogretmen, derslik=EXCLUDED.derslik,
                            last_sync=CURRENT_TIMESTAMP
                    """, sinif, day_name, saat2 or saat,
                        parsed.get("ders", parsed.get("sinif", "")),
                        parsed.get("ogretmen", ""),
                        parsed.get("derslik", ""),
                    )
                    slot_count += 1

        total_slots += slot_count
        logger.info(f"    {slot_count} ders slotu")

        # Kutucugu kaldir
        await ew._page.evaluate(f"""
            (targetSinif) => {{
                const tbl = document.getElementById('GrdClasses');
                if (!tbl) return;
                const rows = tbl.querySelectorAll('tbody tr, tr');
                for (const tr of rows) {{
                    if (tr.innerText.includes(targetSinif)) {{
                        const cb = tr.querySelector('input[type=checkbox]');
                        if (cb && cb.checked) cb.click();
                    }}
                }}
            }}
        """, sinif)
        await asyncio.sleep(0.3)

    await conn.execute("UPDATE data_freshness SET last_sync=CURRENT_TIMESTAMP WHERE module='class_timetable'")
    logger.success(f"  TOPLAM: {total_slots} slot ({time.time()-t0:.1f}s)")
    return total_slots


async def main():
    # 25.41 (Neo bug 7 May): get_session() interactive input → systemd EOF.
    # eyotek_browser_helper non-interactive yol (smart_sync ile aynı pattern).
    from eyotek_wrapper import EyotekWrapper, session_is_valid
    from eyotek_browser_helper import _read_session_file
    pool = await _get_pool()
    conn = await pool.acquire()
    cookies = await _read_session_file()
    if not cookies or not await session_is_valid(cookies):
        logger.info("[TIMETABLE] Cookie eksik/expire, auto login")
        try:
            from eyotek_auto_login import try_auto_login
            result = await try_auto_login()
            if result.get("success"):
                cookies = await _read_session_file()
        except Exception as e:
            logger.error(f"[TIMETABLE] Auto login fail: {e}")
            await pool.release(conn)
            return
    if not cookies:
        logger.error("[TIMETABLE] Cookie alinamadi, abort.")
        await pool.release(conn)
        return

    async with EyotekWrapper(cookies) as ew:
        t_slots = await scrape_teacher_timetables(conn, ew)
        c_slots = await scrape_class_timetables(conn, ew)

    # Ozet
    print("\n" + "=" * 60)
    t_cnt = await conn.fetchval("SELECT COUNT(*) FROM teacher_timetable")
    c_cnt = await conn.fetchval("SELECT COUNT(*) FROM class_timetable")
    print(f"teacher_timetable: {t_cnt} slot")
    print(f"class_timetable: {c_cnt} slot")

    rows = await conn.fetch("""
        SELECT ogretmen_ad, brans, COUNT(*) as slots,
               string_agg(DISTINCT gun, ', ' ORDER BY gun) as gunler
        FROM teacher_timetable GROUP BY ogretmen_ad, brans ORDER BY slots DESC
    """)
    print("\nOgretmen Ders Slotlari:")
    for r in rows:
        print(f"  {r['ogretmen_ad']:<25} {r['brans']:<12} {r['slots']:>3} slot  gunler: {r['gunler']}")

    rows2 = await conn.fetch("""
        SELECT sinif, COUNT(*) as slots FROM class_timetable GROUP BY sinif ORDER BY sinif
    """)
    print("\nSinif Ders Slotlari:")
    for r in rows2:
        print(f"  {r['sinif']:<25} {r['slots']:>3} slot")

    await pool.release(conn)

if __name__ == "__main__":
    asyncio.run(main())
