"""
FermatAI — Eksik Öğrenci Sınav Verisi Çekimi
=============================================
student_exams tablosunda hiç kaydı olmayan öğrencileri bulur,
Eyotek'te ARA ile soz_no ile arar, sınav sayfasına gider,
TYT + AYT sınavlarını çeker ve DB'ye yazar.

Kullanım:
  python sync_missing_students.py           # Tüm eksik öğrenciler
  python sync_missing_students.py 5         # İlk 5 (test)
"""

import asyncio
import os
import sys
from datetime import datetime

from loguru import logger
from playwright.async_api import async_playwright, Page
from db_pool import get_pool as _get_pool
CDP_URL = "http://localhost:9222"
BASE_URL = "https://fermat.eyotek.com/v1"


async def search_student_by_soz(page: Page, soz_no: int) -> bool:
    """Öğrenci listesinde soz_no ile arama yap."""
    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    # Login kontrolü
    if "login" in page.url.lower():
        logger.error("Login gerekli!")
        return False

    # ARA modal aç
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('a, button');
        for (const b of btns) {
            if ((b.innerText||'').trim() === 'ARA' && b.offsetParent) { b.click(); return true; }
        }
        return false;
    }""")
    await asyncio.sleep(2)

    # Soz no ile ara
    await page.evaluate(f"""() => {{
        ['txtAd','txtSoyad','txtOkulNo','txtTcKimlik'].forEach(id => {{
            const el = document.getElementById(id);
            if (el) {{ el.value = ''; }}
        }});
        const soz = document.getElementById('txtOgNo');
        if (soz) {{ soz.value = '{soz_no}'; }}
    }}""")
    await asyncio.sleep(0.5)

    # Ara butonu tıkla
    await page.evaluate("() => { const b = document.getElementById('btnControl'); if (b) b.click(); }")
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(3)

    # Kayıt bulundu mu
    count = await page.evaluate("""() => {
        const m = document.body.innerText.match(/BULUNAN KAYIT SAYISI\\s*:\\s*(\\d+)/);
        return m ? parseInt(m[1]) : 0;
    }""")

    return count > 0


async def click_student_exam_button(page: Page) -> bool:
    """Grid'deki ilk öğrencinin sınav butonuna tıkla.
    Eyotek'te satır menüsü sarı 3 noktalı butonla açılır,
    sonra Sınav linkine tıklanır."""

    # 1. Dropdown toggle butonunu aç
    await page.evaluate("""() => {
        const rows = document.querySelectorAll('#GridView1 tr');
        for (let i = 1; i < rows.length; i++) {
            const cells = rows[i].querySelectorAll('td');
            if (cells.length < 5) continue;
            // İlk cell'deki dropdown toggle
            const toggle = cells[0].querySelector('.dropdown-toggle, .custom-row-menu-button, [data-toggle=dropdown]');
            if (toggle) { toggle.click(); return true; }
            const btn = cells[0].querySelector('button, a.btn');
            if (btn) { btn.click(); return true; }
        }
        return false;
    }""")
    await asyncio.sleep(1)

    # 2. Sınav linkine tıkla
    sinav_link = await page.query_selector('#GridView1_btnSinav_0')
    if sinav_link:
        await sinav_link.evaluate('el => el.click()')
    else:
        # Fallback
        await page.evaluate("""() => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                if ((a.innerText||'').trim() === 'Sınav' && a.id && a.id.includes('btnSinav')) {
                    a.click(); return true;
                }
            }
            return false;
        }""")

    await asyncio.sleep(5)
    return "student-test" in page.url


async def scrape_exam_tab(page: Page, tab_name: str) -> list[dict]:
    """Sınav sekmesindeki verileri çek."""
    clicked = await page.evaluate(f"""() => {{
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {{
            const text = walker.currentNode.textContent.trim();
            if (text === '{tab_name}') {{
                const el = walker.currentNode.parentElement;
                if (el.tagName === 'SPAN' || el.tagName === 'A' || el.tagName === 'LI') {{
                    el.click();
                    return text;
                }}
            }}
        }}
        return null;
    }}""")

    if not clicked:
        return []

    await asyncio.sleep(2)

    exams = await page.evaluate("""() => {
        const results = [];
        const rows = document.querySelectorAll('table tr');
        for (const row of rows) {
            const cells = row.querySelectorAll('td');
            if (cells.length < 4) continue;
            let exam_code = '', exam_type = '', exam_name = '', exam_date = '', katilim = '';
            for (let i = 0; i < cells.length; i++) {
                const text = (cells[i].innerText || '').trim();
                if (/^\\d{5,}$/.test(text) && !exam_code) exam_code = text;
                else if (text === 'TYT' || text === 'YKS') exam_type = text;
                else if (/^\\d{1,2}\\.\\d{2}\\.\\d{4}$/.test(text)) exam_date = text;
                else if (text.length > 5 && !/^\\d+$/.test(text) && !['TYT','YKS'].includes(text) &&
                         !text.includes('Katılmadı') && !text.includes('Katıldı'))
                    exam_name = text;
                if (text === 'Katılmadı') katilim = 'katilmadi';
                if (text === 'Katıldı') katilim = 'katildi';
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

    pool = await _get_pool()
    conn = await pool.acquire()

    # Sınav verisi OLMAYAN öğrencileri bul (net>5 olan kaydı yok)
    missing = await conn.fetch("""
        SELECT s.soz_no::int as soz_no, s.full_name, s.class_name
        FROM students s
        LEFT JOIN student_exams se ON se.soz_no = s.soz_no::int AND se.toplam > 5
        WHERE se.soz_no IS NULL
        ORDER BY s.soz_no::int
    """)
    # Ayrıca hiç kaydı olmayan öğrencileri de ekle
    no_record = await conn.fetch("""
        SELECT s.soz_no::int as soz_no, s.full_name, s.class_name
        FROM students s
        LEFT JOIN student_exams se ON se.soz_no = s.soz_no::int
        WHERE se.soz_no IS NULL
        ORDER BY s.soz_no::int
    """)
    # Birleştir (deduplicate)
    seen = set()
    all_missing = []
    for m in list(missing) + list(no_record):
        if m['soz_no'] not in seen:
            seen.add(m['soz_no'])
            all_missing.append(m)
    missing = all_missing

    logger.info(f"Sınav verisi eksik: {len(missing)} öğrenci")
    if not missing:
        logger.info("Tüm öğrenciler tamam!")
        await conn.close()
        return

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    ctx = browser.contexts[0]
    page = ctx.pages[0]  # Mevcut sayfayı kullan — session korunur

    success = 0
    no_exam = 0
    errors = 0

    for idx, student in enumerate(missing):
        if idx >= limit:
            break

        soz_no = student['soz_no']
        name = student['full_name']
        cls = student.get('class_name', '?')
        is_12_mezun = cls and ('12' in str(cls) or 'Mez' in str(cls) or 'MEZ' in str(cls))

        logger.info(f"[{idx+1}/{min(len(missing), limit)}] {name} (soz:{soz_no}, cls:{cls})")

        try:
            # Öğrenci ara
            found = await search_student_by_soz(page, soz_no)
            if not found:
                logger.warning(f"  Bulunamadı!")
                errors += 1
                continue

            # Sınav sayfasına git
            went_exam = await click_student_exam_button(page)
            if not went_exam:
                logger.warning(f"  Sınav sayfasına gidilemedi")
                errors += 1
                continue

            # Sınıfa göre sekme belirle
            is_lgs = cls and any(x in str(cls) for x in ['7', '8', 'LGS'])
            is_9_10 = cls and any(x in str(cls) for x in ['9', '10'])

            # TYT veya LGS sınavları
            if is_lgs:
                main_exams = await scrape_exam_tab(page, "LGS")
                exam_prefix = "LGS"
            else:
                main_exams = await scrape_exam_tab(page, "TYT")
                exam_prefix = "TYT"

            # TYT bulunamazsa Tüm Sınavlar dene
            if not main_exams:
                main_exams = await scrape_exam_tab(page, "Tüm Sınavlar")
                if not exam_prefix:
                    exam_prefix = "ALL"

            main_katildi = [e for e in main_exams if e.get('katilim') != 'katilmadi']

            # AYT sınavları (12/Mezun ise)
            ayt_exams = []
            if is_12_mezun:
                ayt_exams = await scrape_exam_tab(page, "YKS")
                ayt_katildi = [e for e in ayt_exams if e.get('katilim') != 'katilmadi']
            else:
                ayt_katildi = []

            total_new = 0

            # DB'ye ana sınavları kaydet (TYT veya LGS)
            for exam in main_katildi:
                exam_name = exam.get('exam_name', '?')
                exam_date_str = exam.get('exam_date', '')
                exam_code = exam.get('exam_code', '')
                try:
                    date_obj = datetime.strptime(exam_date_str, "%d.%m.%Y").date()
                except Exception:
                    continue
                code = f"{exam_code}_{exam_date_str}" if exam_code else f"{exam_prefix}_{exam_name}_{exam_date_str}"
                try:
                    r = await conn.execute("""
                        INSERT INTO student_exams (soz_no, student_name, exam_code, exam_name, exam_date)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (soz_no, exam_code) DO NOTHING
                    """, soz_no, name, code, exam_name, date_obj)
                    if "INSERT 0 1" in r:
                        total_new += 1
                except Exception:
                    pass

            # DB'ye AYT kaydet
            for exam in ayt_katildi:
                exam_name = f"[AYT] {exam.get('exam_name', '?')}"
                exam_date_str = exam.get('exam_date', '')
                exam_code = exam.get('exam_code', '')
                try:
                    date_obj = datetime.strptime(exam_date_str, "%d.%m.%Y").date()
                except Exception:
                    continue
                code = f"AYT_{exam_code}_{exam_date_str}" if exam_code else f"AYT_{exam_name}_{exam_date_str}"
                try:
                    r = await conn.execute("""
                        INSERT INTO student_exams (soz_no, student_name, exam_code, exam_name, exam_date)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (soz_no, exam_code) DO NOTHING
                    """, soz_no, name, code, exam_name, date_obj)
                    if "INSERT 0 1" in r:
                        total_new += 1
                except Exception:
                    pass

            if total_new > 0:
                success += 1
                logger.info(f"  {exam_prefix}: {len(main_katildi)} | AYT: {len(ayt_katildi)} | Yeni: {total_new}")
            else:
                no_exam += 1
                logger.info(f"  Sınav verisi yok ({exam_prefix} sekmesi: {len(main_exams)} kayıt, katılan: {len(main_katildi)})")

        except Exception as e:
            logger.error(f"  HATA: {e}")
            errors += 1

        await asyncio.sleep(1)

    # page.close() yapmıyoruz — mevcut sayfa
    await conn.close()

    logger.info(f"\n{'='*50}")
    logger.info(f"SONUÇ: {success} başarılı, {no_exam} veri yok, {errors} hata")
    logger.info(f"Şimdi fill_missing_nets.py çalıştırarak netleri doldurun.")


if __name__ == "__main__":
    asyncio.run(main())
