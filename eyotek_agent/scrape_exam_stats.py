"""
FermatAI — Sınav İstatistik Sayfasından Toplu Net Çekimi
=========================================================
Eyotek Sınavlar > 3 nokta > Sınav İstatistik sayfasından
tüm öğrencilerin tek sınavdaki netlerini toplu çeker.

URL: /Pages/Student/test-transferred-statistic?SnvTur=TYT&SnvKod=999000095

Bu yöntem ÇOOK daha hızlı — öğrenci öğrenci gezmeye gerek yok.
Tek sınav = tek sayfa = tüm öğrenci netleri.

Kullanım:
  python scrape_exam_stats.py              # Net eksik tüm sınavları çek
  python scrape_exam_stats.py 999000095    # Tek sınav çek
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime

from loguru import logger
from playwright.async_api import async_playwright, Page
from db_pool import db_fetch
CDP_URL = "http://localhost:9222"
BASE_URL = "https://fermat.eyotek.com/v1"


async def scrape_exam_statistic(page: Page, sinav_kodu: str, sinav_turu: str = "TYT") -> list[dict]:
    """
    Sınav istatistik sayfasından tüm öğrenci netlerini çek.
    URL: /Pages/Student/test-transferred-statistic?SnvTur=TYT&SnvKod=999000095
    """
    url = f"{BASE_URL}/Pages/Student/test-transferred-statistic?SnvTur={sinav_turu}&SnvKod={sinav_kodu}"
    await page.goto(url, wait_until="networkidle", timeout=15000)
    await asyncio.sleep(3)

    # ARA modal açılıyorsa — direkt ARA'ya bas
    has_modal = await page.evaluate("() => !!document.querySelector('.modal-content, #btnSearch')")
    if has_modal:
        # ARA butonuna tıkla
        await page.evaluate("""() => {
            const btn = document.querySelector('a.btn-info, button.btn-info, [id*=btnSearch]');
            if (btn) btn.click();
            // Alternatif: modal içindeki ARA
            document.querySelectorAll('a, button').forEach(b => {
                if ((b.innerText||'').trim() === 'ARA' && b.offsetParent) b.click();
            });
        }""")
        await asyncio.sleep(3)

    # Tablodan veri çek
    students = await page.evaluate("""() => {
        const result = [];
        const tables = document.querySelectorAll('table');

        // En büyük tabloyu bul (veri tablosu)
        let mainTable = null;
        let maxRows = 0;
        tables.forEach(t => {
            const rows = t.querySelectorAll('tr');
            if (rows.length > maxRows) { maxRows = rows.length; mainTable = t; }
        });

        if (!mainTable) return result;

        // Header'ları oku
        const headerRow = mainTable.querySelector('tr');
        const headers = [];
        if (headerRow) {
            headerRow.querySelectorAll('th, td').forEach(cell => {
                headers.push((cell.innerText || '').trim().toLowerCase());
            });
        }

        // Veri satırlarını oku
        const rows = mainTable.querySelectorAll('tr');
        for (let i = 1; i < rows.length; i++) {
            const cells = rows[i].querySelectorAll('td');
            if (cells.length < 5) continue;

            const rowData = {};
            cells.forEach((cell, j) => {
                const text = (cell.innerText || '').trim();
                if (j < headers.length) {
                    rowData[headers[j]] = text;
                }
                rowData['col_' + j] = text;
            });

            // Soz_no veya okul_no bul
            let sozNo = '';
            for (const [k, v] of Object.entries(rowData)) {
                if ((k.includes('söz') || k.includes('soz') || k.includes('no')) && /^\d{1,4}$/.test(v)) {
                    sozNo = v;
                    break;
                }
            }
            // Ad soyad bul
            let name = '';
            for (const [k, v] of Object.entries(rowData)) {
                if ((k.includes('ad') || k.includes('isim')) && v.length > 2 && !/^\d+$/.test(v)) {
                    name += v + ' ';
                }
            }

            if (sozNo || name.trim()) {
                rowData['soz_no'] = sozNo;
                rowData['name'] = name.trim();
                result.push(rowData);
            }
        }

        return result;
    }""")

    return students


async def get_missing_exam_codes() -> list[dict]:
    """Net eksik sınav kodlarını getir."""
    return await db_fetch("""
        SELECT DISTINCT
            CASE WHEN exam_code LIKE 'AYT_%' THEN SPLIT_PART(exam_code,'_',2) ELSE SPLIT_PART(exam_code,'_',1) END as sinav_kodu,
            CASE WHEN exam_code LIKE 'AYT_%' THEN 'YKS' ELSE 'TYT' END as tur,
            exam_name, exam_date,
            COUNT(*) as eksik
        FROM student_exams WHERE toplam IS NULL
        GROUP BY 1,2,exam_name,exam_date
        ORDER BY exam_date DESC
    """)


async def main():
    # Tek sınav modu
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        target_code = sys.argv[1]
        target_tur = sys.argv[2] if len(sys.argv) > 2 else "TYT"
    else:
        target_code = None
        target_tur = None

    pw = await async_playwright().start()
    from eyotek_browser_helper import connect_eyotek_or_fallback
    browser, page, _is_cdp = await connect_eyotek_or_fallback(pw, CDP_URL)
    ctx = page.context  # 25.46.9: helper kullanimi sonrasi ctx

    if target_code:
        # Tek sınav
        logger.info(f"Sınav {target_code} ({target_tur}) çekiliyor...")
        students = await scrape_exam_statistic(page, target_code, target_tur)
        logger.info(f"  {len(students)} öğrenci bulundu")
        for s in students[:3]:
            logger.info(f"  Örnek: {json.dumps(s, ensure_ascii=False)[:100]}")
    else:
        # Tüm eksik sınavlar
        missing = await get_missing_exam_codes()
        logger.info(f"{len(missing)} eksik sınav bulundu")

        for exam in missing[:5]:  # İlk 5 test
            code = exam['sinav_kodu']
            tur = exam['tur']
            name = exam['exam_name']
            logger.info(f"\n{name} ({code}, {tur}) — {exam['eksik']} eksik")

            students = await scrape_exam_statistic(page, code, tur)
            logger.info(f"  {len(students)} öğrenci çekildi")
            if students:
                logger.info(f"  Headers: {list(students[0].keys())[:10]}")


if __name__ == "__main__":
    asyncio.run(main())
