"""
FermatAI — Eksik Netleri Sınav İstatistik Sayfasından Toplu Doldur
===================================================================
Her sınav kodu için test-transferred-statistic sayfasını açar,
ARA yapar, tablodan tüm öğrenci netlerini çeker, DB'ye yazar.

ÇOK HIZLI: Öğrenci öğrenci değil, sınav bazlı toplu çekim.
28 sınav × ~10s = ~5 dakika'da tüm eksikler dolar.
"""

import asyncio
import os
import sys
from datetime import datetime

from loguru import logger
from playwright.async_api import async_playwright
from db_pool import get_pool as _get_pool
CDP_URL = "http://localhost:9222"
BASE_URL = "https://fermat.eyotek.com/v1"


def pf(v):
    """Parse float — virgül/nokta destekli."""
    if not v or v == '-' or v.strip() == '':
        return None
    try:
        return float(str(v).replace(',', '.'))
    except (ValueError, TypeError):
        return None


async def scrape_and_import_exam(page, conn, sinav_kodu: str, sinav_turu: str, exam_date) -> int:
    """Tek sınavın istatistik sayfasından tüm netleri çek ve DB'ye yaz."""

    url = f"{BASE_URL}/Pages/Student/test-transferred-statistic?SnvTur={sinav_turu}&SnvKod={sinav_kodu}"
    await page.goto(url, wait_until="networkidle", timeout=15000)
    await asyncio.sleep(2)

    # ARA butonuna tıkla
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('a, button');
        for (const b of btns) {
            if ((b.innerText||'').trim().includes('ARA') && b.offsetParent) {
                b.click(); return;
            }
        }
    }""")
    await asyncio.sleep(4)

    # Tablodan veri çek
    data = await page.evaluate("""() => {
        const tables = document.querySelectorAll('table');
        let mainTable = null;
        let maxRows = 0;
        tables.forEach(t => {
            const rows = t.querySelectorAll('tr');
            if (rows.length > maxRows) { maxRows = rows.length; mainTable = t; }
        });
        if (!mainTable) return {headers: [], rows: []};

        const headers = [];
        mainTable.querySelectorAll('tr:first-child th, tr:first-child td').forEach(c =>
            headers.push((c.innerText||'').trim().toLowerCase()));

        const rows = [];
        const trs = mainTable.querySelectorAll('tr');
        for (let i = 1; i < trs.length; i++) {
            const cells = trs[i].querySelectorAll('td');
            rows.push(Array.from(cells).map(c => (c.innerText||'').trim()));
        }
        return {headers, rows};
    }""")

    headers = data.get('headers', [])
    rows = data.get('rows', [])

    if not rows:
        return 0

    # Header'dan NET kolon indekslerini bul
    net_cols = {}
    for i, h in enumerate(headers):
        h_lower = h.lower()
        if '_net' in h_lower:
            if 'türkçe' in h_lower or 'turkce' in h_lower:
                net_cols['turkce'] = i
            elif 'matematik' in h_lower:
                net_cols['matematik'] = i
            elif 'geometri' in h_lower:
                net_cols['geometri'] = i
            elif 'fizik' in h_lower:
                net_cols['fizik'] = i
            elif 'kimya' in h_lower:
                net_cols['kimya'] = i
            elif 'biyoloji' in h_lower:
                net_cols['biyoloji'] = i
            elif 'toplam' in h_lower:
                net_cols['toplam'] = i
            elif 'tarih' in h_lower and 'coğ' not in h_lower:
                net_cols['tarih'] = i
            elif 'coğrafya' in h_lower or 'cografya' in h_lower:
                net_cols['cografya'] = i

    # Ad/Soyad kolon indeksleri
    ad_col = None
    soyad_col = None
    for i, h in enumerate(headers):
        if h in ('adı', 'adi', 'ad'):
            ad_col = i
        elif h in ('soyadı', 'soyadi', 'soyad'):
            soyad_col = i

    if not net_cols.get('toplam'):
        logger.warning(f"  Toplam NET kolonu bulunamadi — headers: {headers[:10]}")
        return 0

    updated = 0
    for row in rows:
        if len(row) < max(net_cols.values()) + 1:
            continue

        toplam = pf(row[net_cols['toplam']]) if net_cols.get('toplam') else None
        if toplam is None:
            continue

        # Ad soyad → soz_no bul
        ad = row[ad_col].strip().upper() if ad_col and ad_col < len(row) else ''
        soyad = row[soyad_col].strip().upper() if soyad_col and soyad_col < len(row) else ''
        full_name = f"{ad} {soyad}".strip()

        if not full_name or len(full_name) < 3:
            continue

        soz = await conn.fetchval(
            "SELECT soz_no FROM students WHERE UPPER(full_name) = $1 LIMIT 1", full_name)
        if not soz:
            soz = await conn.fetchval(
                "SELECT soz_no FROM students WHERE UPPER(full_name) LIKE $1 LIMIT 1",
                f"%{ad}%{soyad}%")
        if not soz:
            continue

        soz_no = int(soz)

        turkce = pf(row[net_cols['turkce']]) if net_cols.get('turkce') else None
        matematik = pf(row[net_cols['matematik']]) if net_cols.get('matematik') else None
        geometri = pf(row[net_cols['geometri']]) if net_cols.get('geometri') else None
        fizik = pf(row[net_cols['fizik']]) if net_cols.get('fizik') else None
        kimya = pf(row[net_cols['kimya']]) if net_cols.get('kimya') else None
        biyoloji = pf(row[net_cols['biyoloji']]) if net_cols.get('biyoloji') else None

        # DB'ye INSERT veya UPDATE — soz_no + sinav_kodu + tarih
        exam_code_db = f"{sinav_kodu}_{exam_date.strftime('%d.%m.%Y')}" if exam_date else sinav_kodu
        # Sınav adını bul — önce bu öğrenciden, sonra aynı tarihteki herhangi birinden
        exam_name_db = await conn.fetchval(
            "SELECT exam_name FROM student_exams WHERE soz_no::int=$1 AND exam_date=$2 AND exam_name NOT LIKE 'Sinav %' LIMIT 1",
            soz_no, exam_date)
        if not exam_name_db:
            exam_name_db = await conn.fetchval(
                "SELECT exam_name FROM student_exams WHERE exam_date=$1 AND exam_name NOT LIKE 'Sinav %' AND exam_name NOT LIKE '[AYT]%' LIMIT 1",
                exam_date)
        if not exam_name_db:
            exam_name_db = f"Sinav {sinav_kodu}"

        r = await conn.execute("""
            INSERT INTO student_exams (soz_no, student_name, exam_code, exam_name, exam_date,
                turkce, matematik, geometri, fizik, kimya, biyoloji, toplam)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (soz_no, exam_code) DO UPDATE SET
                turkce=EXCLUDED.turkce, matematik=EXCLUDED.matematik, geometri=EXCLUDED.geometri,
                fizik=EXCLUDED.fizik, kimya=EXCLUDED.kimya, biyoloji=EXCLUDED.biyoloji,
                toplam=EXCLUDED.toplam
        """, soz_no, full_name, exam_code_db, exam_name_db, exam_date,
            turkce, matematik, geometri, fizik, kimya, biyoloji, toplam)

        if "INSERT" in r or "UPDATE" in r:
            updated += 1

    return updated


async def main():
    pool = await _get_pool()
    conn = await pool.acquire()

    # Eksik sınav kodlarını al — TYT, YKS ve LGS destekli
    missing = await conn.fetch("""
        SELECT DISTINCT
            SPLIT_PART(exam_code,'_',1) as kod,
            CASE
                WHEN exam_name LIKE '[AYT]%' OR exam_name LIKE '%YKS%' THEN 'YKS'
                WHEN exam_code LIKE 'LGS%' THEN 'LGS'
                ELSE 'TYT'
            END as tur,
            exam_date, COUNT(*) as eksik
        FROM student_exams WHERE toplam IS NULL
        AND (SPLIT_PART(exam_code,'_',1) ~ '^\d+$' OR exam_code LIKE 'LGS%')
        GROUP BY 1,2,exam_date ORDER BY exam_date DESC
    """)

    logger.info(f"{len(missing)} eksik sınav bulundu")

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    page = browser.contexts[0].pages[0]

    total_updated = 0
    total_exams = 0

    for exam in missing:
        kod = exam['kod']
        tur = exam['tur']
        exam_date = exam['exam_date']
        eksik = exam['eksik']

        logger.info(f"[{total_exams+1}/{len(missing)}] {kod} ({tur}) {exam_date} — {eksik} eksik")

        try:
            count = await scrape_and_import_exam(page, conn, kod, tur, exam_date)
            total_updated += count
            total_exams += 1
            logger.info(f"  → {count} güncellendi")
        except Exception as e:
            logger.warning(f"  → HATA: {e}")

        await asyncio.sleep(1)

    await pool.release(conn)

    logger.info(f"\n{'='*50}")
    logger.info(f"TAMAMLANDI: {total_exams} sınav tarandı, {total_updated} net güncellendi")


if __name__ == "__main__":
    asyncio.run(main())
