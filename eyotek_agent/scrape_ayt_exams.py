"""
FermatAI — AYT Sinav Verisi Cekimi
====================================
Eyotek'ten YKS sekmesindeki AYT sinavlarini cekilir.
12.sinif ve Mezun ogrenciler icin.

Playwright CDP ile calisiyor — Chrome port 9222'de acik olmali.

Kullanim:
  python scrape_ayt_exams.py          # Tum 12+Mezun ogrenciler
  python scrape_ayt_exams.py 3        # Sadece ilk 3 (test)
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright, Page
from db_pool import get_pool as _get_pool, db_fetch
CDP_URL = "http://localhost:9222"
BASE_URL = "https://fermat.eyotek.com/v1"
EXPORT_DIR = Path("ayt_export")
EXPORT_DIR.mkdir(exist_ok=True)


async def get_12_mezun_students() -> list[dict]:
    """DB'den 12.sinif ve Mezun ogrencileri al."""
    return await db_fetch("""
        SELECT soz_no, full_name, class_name, eyotek_id
        FROM students
        WHERE class_name LIKE '%12%' OR class_name LIKE '%Mez%' OR class_name LIKE '%MEZ%'
        ORDER BY soz_no
    """)


async def open_student_list(page: Page) -> bool:
    """Ogrenci listesini ac — ARA akisi."""
    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="networkidle", timeout=15000)
    await asyncio.sleep(2)

    if "login" in page.url.lower():
        logger.error("Session suresi dolmus — login gerekli!")
        return False

    # Toolbar ARA tikla
    clicked = await page.evaluate("""
        () => {
            const els = document.querySelectorAll('a, button, input[type=button], input[type=submit]');
            for (const el of els) {
                const txt = (el.innerText || el.value || '').toUpperCase().trim();
                if (txt === 'ARA' && el.offsetParent !== null) { el.click(); return true; }
            }
            return false;
        }
    """)
    if not clicked:
        logger.error("ARA butonu bulunamadi!")
        return False

    await asyncio.sleep(2)

    # Popup icindeki ARA'ya tikla
    await page.evaluate("""
        () => {
            const closeBtn = document.querySelector('#btnCloseSearchModal, [id*=CloseSearchModal]');
            if (closeBtn) {
                let el = closeBtn.parentElement;
                while (el && !['BODY','HTML'].includes(el.tagName)) {
                    const btns = el.querySelectorAll('a, button, input[type=button], input[type=submit]');
                    for (const btn of btns) {
                        const t = (btn.innerText || btn.value || '').toUpperCase().trim();
                        if (t === 'ARA' || t === 'LİSTELE') { btn.click(); return true; }
                    }
                    el = el.parentElement;
                }
            }
            const btnSearch = document.getElementById('btnSearch');
            if (btnSearch) { btnSearch.click(); return true; }
            return false;
        }
    """)
    await asyncio.sleep(5)

    row_count = await page.evaluate("() => document.querySelectorAll('#GridView1 tr, table tr').length")
    logger.info(f"Ogrenci listesi yuklendi: {row_count} satir")
    return row_count > 2


async def get_student_grid_info(page: Page) -> list[dict]:
    """Sayfadaki ogrenci listesini ve sinav butonu bilgilerini cek."""
    return await page.evaluate("""
        () => {
            const students = [];
            const rows = document.querySelectorAll('#GridView1 tr');
            for (let i = 2; i < rows.length; i++) {
                const cells = rows[i].querySelectorAll('td');
                if (cells.length < 8) continue;
                const sozNo = (cells[4]?.innerText || '').trim();
                const ad = (cells[6]?.innerText || '').trim();
                const soyad = (cells[7]?.innerText || '').trim();
                if (!sozNo || !/^\\d+$/.test(sozNo)) continue;

                // Sinav butonu — row index ile ctl hesapla
                const rowIdx = i;
                const ctl = rowIdx < 10 ? '0' + rowIdx : '' + rowIdx;

                students.push({sozNo, name: ad + ' ' + soyad, ctl, rowIdx});
            }
            return students;
        }
    """)


async def click_student_exam_button(page: Page, ctl: str) -> bool:
    """Grid'deki sinav butonuna tikla."""
    try:
        await page.evaluate(f"__doPostBack('GridView1$ctl{ctl}$btnSinav','')")
        await asyncio.sleep(4)
        return "student-test" in page.url
    except Exception as e:
        logger.warning(f"Sinav butonu tiklanamadi: {e}")
        return False


async def click_yks_or_all_tab(page: Page) -> bool:
    """YKS sekmesine tikla. Yoksa 'Tum Sinavlar' sekmesine tikla."""
    try:
        result = await page.evaluate("""
            () => {
                // Tum text node'lari tara
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                const targets = [];
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent.trim();
                    if (text === 'YKS' || text === 'Tüm Sınavlar') {
                        targets.push({text, el: walker.currentNode.parentElement});
                    }
                }
                // Oncelik: YKS
                for (const t of targets) {
                    if (t.text === 'YKS' && t.el.tagName === 'SPAN') {
                        t.el.click();
                        return 'YKS';
                    }
                }
                // Fallback: Tum Sinavlar
                for (const t of targets) {
                    if (t.text === 'Tüm Sınavlar') {
                        t.el.click();
                        return 'TumSinavlar';
                    }
                }
                return null;
            }
        """)
        if result:
            await asyncio.sleep(2)
            logger.info(f"    Tab tiklandi: {result}")
            return True
        logger.warning("YKS/Tum Sinavlar sekmesi bulunamadi")
        return False
    except Exception as e:
        logger.warning(f"Tab click hatasi: {e}")
        return False


async def scrape_yks_exams(page: Page) -> list[dict]:
    """YKS sekmesindeki sinav verilerini cek."""
    exams = await page.evaluate("""
        () => {
            const results = [];
            // Tum tablolardaki satirlari tara
            const rows = document.querySelectorAll('table tr, .table tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 4) continue;

                // Sinav kodu, sinav turu, sinav adi, tarih
                let exam_code = '', exam_type = '', exam_name = '', exam_date = '', karne = '';

                for (let i = 0; i < cells.length; i++) {
                    const text = (cells[i].innerText || '').trim();
                    // Sinav kodu: rakamlarla baslar (999000091 gibi)
                    if (/^\d{5,}$/.test(text) && !exam_code) exam_code = text;
                    // Kisa sayi (15, 11 gibi)
                    else if (/^\d{1,2}$/.test(text) && !exam_code) exam_code = text;
                    // YKS yazisi
                    else if (text === 'YKS') exam_type = text;
                    // Tarih (DD.MM.YYYY)
                    else if (/^\d{1,2}\.\d{2}\.\d{4}$/.test(text)) exam_date = text;
                    // Sinav adi (uzun metin)
                    else if (text.length > 5 && !/^\d+$/.test(text) && text !== 'YKS' &&
                             !text.includes('Katılmadı') && !text.includes('Katıldı'))
                        exam_name = text;
                    // Katilim durumu
                    if (text === 'Katılmadı') karne = 'katilmadi';
                }

                if (exam_name && exam_date) {
                    results.push({exam_code, exam_type, exam_name, exam_date, karne});
                }
            }
            return results;
        }
    """)
    return exams


async def scrape_exam_detail(page: Page, exam_code: str, exam_name: str) -> dict | None:
    """Tek sinavin detay sayfasina girip netleri cek."""
    # Sinav koduna tikla (link)
    clicked = await page.evaluate(f"""
        () => {{
            const links = document.querySelectorAll('a');
            for (const a of links) {{
                if ((a.innerText || '').trim() === '{exam_code}') {{
                    a.click();
                    return true;
                }}
            }}
            return false;
        }}
    """)

    if not clicked:
        # Alternatif: yesil ok butonuna tikla
        return None

    await asyncio.sleep(3)

    # Karne sayfasindan netleri cek
    nets = await page.evaluate("""
        () => {
            const result = {};
            const body = document.body.innerText;

            // Net degerlerini regex ile cek
            const patterns = [
                ['turkce', /T[üu]rk[çc]e[:\\s]+([\\d,.]+)/i],
                ['matematik', /Matematik[:\\s]+([\\d,.]+)/i],
                ['geometri', /Geometri[:\\s]+([\\d,.]+)/i],
                ['fizik', /Fizik[:\\s]+([\\d,.]+)/i],
                ['kimya', /Kimya[:\\s]+([\\d,.]+)/i],
                ['biyoloji', /Biyoloji[:\\s]+([\\d,.]+)/i],
                ['tarih', /Tarih[:\\s]+([\\d,.]+)/i],
                ['cografya', /Co[ğg]rafya[:\\s]+([\\d,.]+)/i],
                ['felsefe', /Felsefe[:\\s]+([\\d,.]+)/i],
                ['edebiyat', /Edebiyat[:\\s]+([\\d,.]+)/i],
                ['toplam', /Toplam[:\\s]+([\\d,.]+)/i],
            ];

            for (const [key, regex] of patterns) {
                const m = body.match(regex);
                if (m) result[key] = m[1].replace(',', '.');
            }

            // Tablo bazli netleri de dene
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const rows = table.querySelectorAll('tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td, th');
                    if (cells.length >= 2) {
                        const label = (cells[0].innerText || '').trim().toLowerCase();
                        const value = (cells[1].innerText || '').trim();
                        if (label.includes('fizik') && /[\\d,.]+/.test(value)) result['fizik'] = value.replace(',','.');
                        if (label.includes('kimya') && /[\\d,.]+/.test(value)) result['kimya'] = value.replace(',','.');
                        if (label.includes('biyoloji') && /[\\d,.]+/.test(value)) result['biyoloji'] = value.replace(',','.');
                        if (label.includes('matematik') && /[\\d,.]+/.test(value)) result['matematik'] = value.replace(',','.');
                        if (label.includes('geometri') && /[\\d,.]+/.test(value)) result['geometri'] = value.replace(',','.');
                    }
                }
            }

            result.full_text = body.substring(0, 2000);
            return result;
        }
    """)

    # Geri don
    await page.go_back()
    await asyncio.sleep(2)
    # Tekrar YKS sekmesine tikla
    await click_yks_or_all_tab(page)

    return nets


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 9999

    p = await async_playwright().start()
    # 25.46.9 (Neo direktif): connect_over_cdp -> helper fallback (CDP yoksa headless)
    from eyotek_browser_helper import connect_eyotek_or_fallback
    browser, page, _is_cdp = await connect_eyotek_or_fallback(p, CDP_URL)
    context = page.context  # backward-compat icin

    # 1. Ogrenci listesini ac
    logger.info("Ogrenci listesi aciliyor...")
    ok = await open_student_list(page)
    if not ok:
        logger.error("Ogrenci listesi acilamadi!")
        return

    pool = await _get_pool()
    conn = await pool.acquire()
    total_imported = 0
    total_students = 0
    page_num = 1

    while True:
        # Bu sayfadaki ogrencileri al
        students_on_page = await get_student_grid_info(page)
        if not students_on_page:
            logger.info(f"Sayfa {page_num}: ogrenci yok, bitti.")
            break

        logger.info(f"Sayfa {page_num}: {len(students_on_page)} ogrenci")

        for student in students_on_page:
            if total_students >= limit:
                break

            soz_no = int(student['sozNo'])
            name = student['name']
            ctl = student['ctl']

            # Sadece 12.sinif ve Mezun ogrencileri isle
            # DB'den kontrol et
            cls = await conn.fetchval(
                "SELECT class_name FROM students WHERE soz_no::int = $1", soz_no)
            if not cls or not (('12' in str(cls)) or ('Mez' in str(cls)) or ('MEZ' in str(cls))):
                continue

            total_students += 1
            logger.info(f"  [{total_students}] {name} (soz:{soz_no}, cls:{cls})")

            # Sinav sayfasina git
            ok = await click_student_exam_button(page, ctl)
            if not ok:
                logger.warning(f"    Sinav sayfasina gidilemedi")
                # Listeye yeniden yukle
                await open_student_list(page)
                if page_num > 1:
                    try:
                        await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                        await asyncio.sleep(3)
                    except Exception:
                        pass
                continue

            # YKS veya Tum Sinavlar sekmesine tikla
            tab_ok = await click_yks_or_all_tab(page)
            if not tab_ok:
                logger.warning(f"    Sekme bulunamadi — atlaniyor")
            else:
                # Sinavlari listele — YKS turundeki sinavlari filtrele
                all_exams = await scrape_yks_exams(page)
                exams = [e for e in all_exams if e.get('exam_type') == 'YKS'
                         or 'YKS' in (e.get('exam_name') or '')
                         or 'AYT' in (e.get('exam_name') or '')]
                katildi_exams = [e for e in exams if e.get('karne') != 'katilmadi']
                logger.info(f"    {len(exams)} sinav ({len(katildi_exams)} katildi)")

                for exam in katildi_exams:
                    exam_name = exam.get('exam_name', '?')
                    exam_date = exam.get('exam_date', '')
                    exam_code = exam.get('exam_code', '')

                    try:
                        date_obj = datetime.strptime(exam_date, "%d.%m.%Y").date()
                    except Exception:
                        date_obj = None

                    ayt_code = f"AYT_{exam_code}_{exam_date}" if exam_code else f"AYT_{exam_name}_{exam_date}"

                    try:
                        await conn.execute("""
                            INSERT INTO student_exams (soz_no, student_name, exam_code, exam_name, exam_date,
                                turkce, matematik, geometri, fizik, kimya, biyoloji, toplam)
                            VALUES ($1, $2, $3, $4, $5, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                            ON CONFLICT (soz_no, exam_code) DO NOTHING
                        """, soz_no, name, ayt_code, f"[AYT] {exam_name}", date_obj)
                        total_imported += 1
                    except Exception as e:
                        logger.debug(f"    DB: {e}")

                # Export JSON
                export_data = {"soz_no": soz_no, "name": name, "class": cls, "exams": exams}
                safe_name = name.replace(' ', '_')[:30]
                (EXPORT_DIR / f"{soz_no}_{safe_name}_ayt.json").write_text(
                    json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")

            # Listeye yeniden yukle (go_back yerine tam reload)
            await open_student_list(page)
            if page_num > 1:
                try:
                    await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                    await asyncio.sleep(3)
                except Exception:
                    pass

        if total_students >= limit:
            break

        # Sonraki sayfa
        page_num += 1
        next_ok = await page.evaluate(f"""
            () => {{
                try {{ __doPostBack('GridView1','Page${page_num}'); return true; }}
                catch(e) {{ return false; }}
            }}
        """)
        if not next_ok:
            break
        await asyncio.sleep(3)

    await conn.close()
    logger.info(f"\n{'='*50}")
    logger.info(f"TAMAMLANDI: {total_students} ogrenci taranidi, {total_imported} AYT kaydi")
    logger.info(f"Export: {EXPORT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
