"""
FermatAI — Haftalik Sinav Sync
================================
TYT + AYT sinavlarini Eyotek'ten ceker ve DB'ye import eder.
Yeni deneme var mi kontrol eder, varsa otomatik gunceller.

Playwright CDP ile — Chrome port 9222'de acik olmali.

Kullanim:
  python sync_exams.py          # Yeni sinavlari kontrol et ve import et
  python sync_exams.py --full   # Tum ogrencileri bastan tara
  python sync_exams.py 5        # Sadece ilk 5 ogrenci (test)
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, date
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright, Page
from db_pool import get_pool as _get_pool
CDP_URL = "http://localhost:9222"
BASE_URL = "https://fermat.eyotek.com/v1"
EXPORT_DIR = Path("sync_export")
EXPORT_DIR.mkdir(exist_ok=True)


async def open_student_list(page: Page) -> int:
    """Ogrenci listesine git, ARA yap, kayit sayisi don."""
    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    if "login" in page.url.lower() or await page.evaluate("() => !!document.getElementById('btnLogin')"):
        logger.error("Login gerekli!")
        return 0

    # ARA modal ac
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('a, button');
        for (const b of btns) {
            if ((b.innerText||'').trim() === 'ARA' && b.offsetParent) { b.click(); return; }
        }
    }""")
    await asyncio.sleep(2)

    # Filtreleri temizle
    await page.evaluate("""() => {
        ['txtAd','txtSoyad','txtOgNo','txtOkulNo','txtTcKimlik'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.value = ''; }
        });
    }""")
    await asyncio.sleep(0.5)

    # btnControl tikla
    await page.evaluate("() => { const b = document.getElementById('btnControl'); if (b) b.click(); }")
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(3)

    # Kayit sayisi
    count = await page.evaluate("""() => {
        const m = document.body.innerText.match(/BULUNAN KAYIT SAYISI\\s*:\\s*(\\d+)/);
        return m ? parseInt(m[1]) : 0;
    }""")
    logger.info(f"Toplam kayit: {count}")
    return count


async def get_page_count(page: Page) -> int:
    return await page.evaluate("""() => {
        const pagers = document.querySelectorAll('a[href*="Page$"]');
        let max = 1;
        for (const p of pagers) {
            const m = (p.getAttribute('href') || '').match(/Page\\$(\\d+)/);
            if (m) max = Math.max(max, parseInt(m[1]));
        }
        return max;
    }""")


async def get_students_on_page(page: Page) -> list[dict]:
    return await page.evaluate("""() => {
        const students = [];
        const rows = document.querySelectorAll('#GridView1 tr');
        for (let i = 2; i < rows.length; i++) {
            const cells = rows[i].querySelectorAll('td');
            if (cells.length < 8) continue;
            const sozNo = (cells[4]?.innerText || '').trim();
            const ad = (cells[6]?.innerText || '').trim();
            const soyad = (cells[7]?.innerText || '').trim();
            if (!sozNo || !/^\\d+$/.test(sozNo)) continue;
            const ctl = i < 10 ? '0' + i : '' + i;
            students.push({sozNo, name: ad + ' ' + soyad, ctl});
        }
        return students;
    }""")


async def scrape_student_exams(page: Page, tab_name: str) -> list[dict]:
    """Sinav sayfasindaki belirli sekmeden sinavlari cek.

    Eyotek DOM: UL.nav-tabs > LI > A > SPAN (text)
    Bootstrap tab — LI'nin altindaki A elementine tiklamak gerekir (SPAN degil).
    """
    # Tab tikla — Bootstrap nav-tabs structure'inda LI > A elementine tikla
    clicked_tab = await page.evaluate(f"""() => {{
        // 1. Once UL.nav-tabs > LI > A pattern dene (en spesifik)
        const tabAnchors = document.querySelectorAll('ul.nav-tabs > li > a, ul.nav > li > a');
        for (const a of tabAnchors) {{
            const txt = (a.innerText || '').trim();
            if (txt === '{tab_name}') {{
                a.click();
                return 'nav-tabs:' + txt;
            }}
        }}
        // 2. Genel A/BUTTON elementlerini dene
        const generic = document.querySelectorAll('a, button, [role="tab"]');
        for (const el of generic) {{
            const txt = (el.innerText || '').trim();
            if (txt === '{tab_name}') {{
                el.click();
                return 'generic:' + txt;
            }}
        }}
        // 3. Son care: text walker (eski yontem)
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {{
            const text = walker.currentNode.textContent.trim();
            if (text === '{tab_name}') {{
                let el = walker.currentNode.parentElement;
                // SPAN ise A parent'a yuksel
                while (el && el.tagName !== 'A' && el.tagName !== 'BUTTON' && el.tagName !== 'LI') {{
                    el = el.parentElement;
                }}
                if (el) {{
                    el.click();
                    return 'walker:' + text;
                }}
            }}
        }}
        return null;
    }}""")

    if not clicked_tab:
        logger.debug(f"    Tab bulunamadi: {tab_name}")
        return []

    logger.debug(f"    Tab tiklandi ({tab_name}): {clicked_tab}")
    await asyncio.sleep(2.5)  # tab content yuklenmesi icin biraz daha bekle

    # Sinavlari parse et — SADECE aktif tab paneli icindeki tabloyu oku
    # (Eyotek: TYT/YKS/Tum Sinavlar tab'lari ayri tab-pane DIV'lerinde)
    exams = await page.evaluate("""() => {
        const results = [];
        // Aktif tab paneli bul (Bootstrap: .tab-pane.active veya display:block)
        let activePane = document.querySelector('.tab-pane.active, .tab-pane.in.active');
        if (!activePane) {
            // Fallback: gozuken (hidden olmayan) tab-pane
            const panes = document.querySelectorAll('.tab-pane');
            for (const p of panes) {
                if (p.offsetParent !== null) {
                    activePane = p;
                    break;
                }
            }
        }
        const root = activePane || document;
        const rows = root.querySelectorAll('table tr');
        for (const row of rows) {
            const cells = row.querySelectorAll('td');
            if (cells.length < 4) continue;
            let exam_code = '', exam_type = '', exam_name = '', exam_date = '', katilim = '';
            // Karne hucresinde img (PDF icon) + a (ok ikonu) varsa katildi
            // "Katilmadi" kelimesi varsa katilmadi
            const lastCell = cells[cells.length - 1];
            const lastText = (lastCell.innerText || '').trim();
            const hasIcon = lastCell.querySelector('img, svg, i.fa, [class*="icon"], a, button');
            if (lastText.includes('Katılmadı') || lastText.includes('Katilmadi')) {
                katilim = 'katilmadi';
            } else if (hasIcon || (lastText && lastText.length === 0)) {
                katilim = 'katildi';
            }
            // Diger hucrelerdeki bilgileri parse et
            for (let i = 0; i < cells.length; i++) {
                const text = (cells[i].innerText || '').trim();
                if (/^\\d{5,}$/.test(text) && !exam_code) exam_code = text;
                else if (/^\\d{1,2}$/.test(text) && !exam_code) exam_code = text;
                else if (text === 'TYT' || text === 'YKS') exam_type = text;
                else if (/^\\d{1,2}\\.\\d{2}\\.\\d{4}$/.test(text)) exam_date = text;
                else if (text.length > 5 && !/^\\d+$/.test(text) && !['TYT','YKS'].includes(text) &&
                         !text.includes('Katılmadı') && !text.includes('Katıldı'))
                    exam_name = text;
            }
            if (exam_name && exam_date) {
                results.push({exam_code, exam_type, exam_name, exam_date, katilim});
            }
        }
        return results;
    }""")
    return exams


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 9999
    full_mode = "--full" in sys.argv

    # Mevcut DB'deki en son sinav tarihi — sadece yeni sinavlari kontrol etmek icin
    pool = await _get_pool()
    conn = await pool.acquire()
    last_exam = await conn.fetchval("SELECT MAX(exam_date) FROM student_exams")
    last_ayt = await conn.fetchval("SELECT MAX(exam_date) FROM student_exams WHERE exam_code LIKE 'AYT%'")
    tyt_count = await conn.fetchval("SELECT COUNT(DISTINCT exam_code) FROM student_exams WHERE exam_code NOT LIKE 'AYT%'")
    ayt_count = await conn.fetchval("SELECT COUNT(DISTINCT exam_code) FROM student_exams WHERE exam_code LIKE 'AYT%'")
    logger.info(f"DB durumu: TYT {tyt_count} farkli sinav, AYT {ayt_count} farkli sinav")
    logger.info(f"Son TYT: {last_exam}, Son AYT: {last_ayt}")

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    ctx = browser.contexts[0]
    page = ctx.pages[0]  # Mevcut sayfa

    # Ogrenci listesini ac
    total_records = await open_student_list(page)
    if total_records == 0:
        logger.error("Ogrenci listesi acilamadi!")
        await pool.release(conn)
        return

    total_pages = await get_page_count(page)
    logger.info(f"Toplam sayfa: {total_pages}")

    processed = 0
    new_tyt = 0
    new_ayt = 0

    for page_num in range(1, total_pages + 1):
        if processed >= limit:
            break

        if page_num > 1:
            await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
            await asyncio.sleep(3)

        students = await get_students_on_page(page)
        logger.info(f"Sayfa {page_num}: {len(students)} ogrenci")

        for student in students:
            if processed >= limit:
                break

            soz_no = int(student['sozNo'])
            name = student['name']
            ctl = student['ctl']
            processed += 1

            # 12.sinif/Mezun kontrolu — AYT icin
            cls = await conn.fetchval("SELECT class_name FROM students WHERE soz_no::int = $1", soz_no)
            is_12_mezun = cls and ('12' in str(cls) or 'Mez' in str(cls) or 'MEZ' in str(cls))

            logger.info(f"[{processed}] {name} (soz:{soz_no}, cls:{cls or '?'})")

            # Sinav sayfasina git
            try:
                await page.evaluate(f"__doPostBack('GridView1$ctl{ctl}$btnSinav','')")
                await asyncio.sleep(4)
            except Exception:
                logger.warning(f"    Sinav butonu tiklanamadi")
                # Listeye geri don
                await open_student_list(page)
                if page_num > 1:
                    await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                    await asyncio.sleep(3)
                continue

            if "student-test" not in page.url:
                logger.warning(f"    Sinav sayfasina gidilemedi")
                continue

            # TYT sinavlari — "TYT" sekmesi (herkes)
            tyt_exams = await scrape_student_exams(page, "TYT")
            tyt_katildi = [e for e in tyt_exams if e.get('katilim') == 'katildi']

            # AYT sinavlari — "YKS" sekmesi (sadece 12+Mezun)
            ayt_exams = []
            if is_12_mezun:
                ayt_exams = await scrape_student_exams(page, "YKS")
                if not ayt_exams:
                    # Fallback: "Tüm Sınavlar"
                    all_exams = await scrape_student_exams(page, "Tüm Sınavlar")
                    ayt_exams = [e for e in all_exams if e.get('exam_type') == 'YKS'
                                 or 'YKS' in (e.get('exam_name') or '')
                                 or 'AYT' in (e.get('exam_name') or '')]
                ayt_exams = [e for e in ayt_exams if e.get('katilim') == 'katildi']

            logger.info(f"    TYT: {len(tyt_katildi)} katildi | AYT: {len(ayt_exams)} katildi")

            # DB'ye yeni sinavlari kaydet
            for exam in tyt_katildi:
                exam_name = exam.get('exam_name', '?')
                exam_date_str = exam.get('exam_date', '')
                exam_code = exam.get('exam_code', '')
                try:
                    date_obj = datetime.strptime(exam_date_str, "%d.%m.%Y").date()
                except Exception:
                    continue
                code = f"{exam_code}_{exam_date_str}" if exam_code else f"TYT_{exam_name}_{exam_date_str}"
                try:
                    result = await conn.execute("""
                        INSERT INTO student_exams (soz_no, student_name, exam_code, exam_name, exam_date)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (soz_no, exam_code) DO NOTHING
                    """, soz_no, name, code, exam_name, date_obj)
                    if "INSERT 0 1" in result:
                        new_tyt += 1
                except Exception:
                    pass

            for exam in ayt_exams:
                exam_name = exam.get('exam_name', '?')
                exam_date_str = exam.get('exam_date', '')
                exam_code = exam.get('exam_code', '')
                try:
                    date_obj = datetime.strptime(exam_date_str, "%d.%m.%Y").date()
                except Exception:
                    continue
                code = f"AYT_{exam_code}_{exam_date_str}" if exam_code else f"AYT_{exam_name}_{exam_date_str}"
                try:
                    result = await conn.execute("""
                        INSERT INTO student_exams (soz_no, student_name, exam_code, exam_name, exam_date)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (soz_no, exam_code) DO NOTHING
                    """, soz_no, name, code, f"[AYT] {exam_name}", date_obj)
                    if "INSERT 0 1" in result:
                        new_ayt += 1
                except Exception:
                    pass

            # Listeye geri don — go_back ile (ARA tekrar yapmadan)
            await page.go_back()
            await asyncio.sleep(2)
            # Grid hala yuklu mu kontrol et
            grid_ok = await page.evaluate("() => document.querySelectorAll('#GridView1 tr').length > 2")
            if not grid_ok:
                # Grid bos — ARA tekrar yap (sadece gerektiginde)
                logger.debug("    Grid bos, ARA tekrar yapiliyor...")
                await open_student_list(page)
                if page_num > 1:
                    await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                    await asyncio.sleep(3)

    await pool.release(conn)

    logger.info(f"\n{'='*50}")
    logger.info(f"SYNC TAMAMLANDI")
    logger.info(f"Taranan: {processed} ogrenci")
    logger.info(f"Yeni TYT: {new_tyt} kayit")
    logger.info(f"Yeni AYT: {new_ayt} kayit")


if __name__ == "__main__":
    asyncio.run(main())
