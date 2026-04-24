"""
Import per-exam details from JSON export files into PostgreSQL.
Each row = one student's one exam result with per-subject nets.
"""
import asyncio
import json
import glob
import re
import os
from datetime import datetime
from pathlib import Path
import asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS student_exams (
    id SERIAL PRIMARY KEY,
    soz_no INT,
    student_name TEXT,
    exam_code TEXT,
    exam_name TEXT,
    exam_date DATE,
    turkce REAL,
    tarih REAL,
    cografya REAL,
    felsefe REAL,
    din_kulturu REAL,
    matematik REAL,
    geometri REAL,
    fizik REAL,
    kimya REAL,
    biyoloji REAL,
    toplam REAL,
    UNIQUE(soz_no, exam_code)
);
CREATE INDEX IF NOT EXISTS idx_se_soz ON student_exams(soz_no);
CREATE INDEX IF NOT EXISTS idx_se_date ON student_exams(exam_date);
"""


def parse_float(val):
    """Virgul veya nokta ayirmali sayi parse et."""
    if not val or val.strip() == '':
        return None
    try:
        return float(val.replace(',', '.'))
    except (ValueError, TypeError):
        return None


def extract_date(exam_name: str):
    """Sinav adindan tarihi cikar: '... (01.04.2026)' """
    m = re.search(r'\((\d{2})\.(\d{2})\.(\d{4})\)', exam_name)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
        except ValueError:
            pass
    return None


def clean_exam_name(name: str) -> str:
    """Tarih kismini cikar, temiz isim don."""
    return re.sub(r'\s*\(\d{2}\.\d{2}\.\d{4}\)\s*', '', name).strip()


def parse_exam_file(filepath: str) -> list[dict]:
    """Tek JSON dosyasini parse et, sinav satirlarina don."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    soz_no = data.get('sozNo')
    student = data.get('student', '')
    tables = data.get('tables', [])

    if not tables:
        return []

    # Tablo 0 = sinav listesi
    exam_table = tables[0]
    headers = exam_table.get('h', [])
    rows = exam_table.get('r', [])

    if not rows:
        return []

    # Header index mapping — her dosyada farkli sirada olabilir
    header_map = {}
    for i, h in enumerate(headers):
        h_lower = h.lower().strip()
        if 'kod' in h_lower:
            header_map['kod'] = i
        elif 'sınav' in h_lower or 'sinav' in h_lower or 'ad' in h_lower:
            header_map['exam_name'] = i
        elif 'türkçe' in h_lower or 'turkce' in h_lower:
            header_map['turkce'] = i
        elif 'tarih' in h_lower and 'coğ' not in h_lower:
            header_map['tarih'] = i
        elif 'coğrafya' in h_lower or 'cografya' in h_lower:
            header_map['cografya'] = i
        elif 'felsefe' in h_lower:
            header_map['felsefe'] = i
        elif 'din' in h_lower:
            header_map['din_kulturu'] = i
        elif 'matematik' in h_lower:
            header_map['matematik'] = i
        elif 'geometri' in h_lower:
            header_map['geometri'] = i
        elif 'fizik' in h_lower:
            header_map['fizik'] = i
        elif 'kimya' in h_lower:
            header_map['kimya'] = i
        elif 'biyoloji' in h_lower:
            header_map['biyoloji'] = i
        elif 'toplam' in h_lower:
            header_map['toplam'] = i

    results = []
    for row in rows:
        exam_name_idx = header_map.get('exam_name', 2)
        if exam_name_idx >= len(row):
            continue

        exam_name_raw = row[exam_name_idx]
        if not exam_name_raw or 'toplam' in exam_name_raw.lower():
            continue

        exam_date = extract_date(exam_name_raw)
        exam_name = clean_exam_name(exam_name_raw)
        exam_code = row[header_map.get('kod', 1)] if header_map.get('kod', 1) < len(row) else ''

        def get_val(key):
            idx = header_map.get(key)
            if idx is not None and idx < len(row):
                return parse_float(row[idx])
            return None

        results.append({
            'soz_no': int(soz_no) if soz_no else None,
            'student_name': student,
            'exam_code': str(exam_code),
            'exam_name': exam_name,
            'exam_date': exam_date,
            'turkce': get_val('turkce'),
            'tarih': get_val('tarih'),
            'cografya': get_val('cografya'),
            'felsefe': get_val('felsefe'),
            'din_kulturu': get_val('din_kulturu'),
            'matematik': get_val('matematik'),
            'geometri': get_val('geometri'),
            'fizik': get_val('fizik'),
            'kimya': get_val('kimya'),
            'biyoloji': get_val('biyoloji'),
            'toplam': get_val('toplam'),
        })

    return results


async def main():
    files = sorted(glob.glob('exam_analysis_export/exam_*.json'))
    print(f"Toplam {len(files)} dosya bulundu")

    all_exams = []
    for f in files:
        try:
            exams = parse_exam_file(f)
            all_exams.extend(exams)
        except Exception as e:
            print(f"  [!] {f}: {e}")

    print(f"Toplam {len(all_exams)} sinav kaydi parse edildi")

    conn = await asyncpg.connect(DB_URL)
    await conn.execute(CREATE_TABLE)

    inserted = 0
    errors = 0
    for ex in all_exams:
        try:
            await conn.execute("""
                INSERT INTO student_exams (soz_no, student_name, exam_code, exam_name, exam_date,
                    turkce, tarih, cografya, felsefe, din_kulturu, matematik, geometri,
                    fizik, kimya, biyoloji, toplam)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                ON CONFLICT (soz_no, exam_code) DO UPDATE SET
                    exam_name=EXCLUDED.exam_name, exam_date=EXCLUDED.exam_date,
                    turkce=EXCLUDED.turkce, tarih=EXCLUDED.tarih, cografya=EXCLUDED.cografya,
                    felsefe=EXCLUDED.felsefe, din_kulturu=EXCLUDED.din_kulturu,
                    matematik=EXCLUDED.matematik, geometri=EXCLUDED.geometri,
                    fizik=EXCLUDED.fizik, kimya=EXCLUDED.kimya, biyoloji=EXCLUDED.biyoloji,
                    toplam=EXCLUDED.toplam
            """,
                ex['soz_no'], ex['student_name'], ex['exam_code'], ex['exam_name'], ex['exam_date'],
                ex['turkce'], ex['tarih'], ex['cografya'], ex['felsefe'], ex['din_kulturu'],
                ex['matematik'], ex['geometri'], ex['fizik'], ex['kimya'], ex['biyoloji'], ex['toplam']
            )
            inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [!] soz={ex['soz_no']} exam={ex['exam_code']}: {e}")

    # Stats
    total = await conn.fetchval("SELECT COUNT(*) FROM student_exams")
    students = await conn.fetchval("SELECT COUNT(DISTINCT soz_no) FROM student_exams")
    date_range = await conn.fetchrow("SELECT MIN(exam_date), MAX(exam_date) FROM student_exams")

    await conn.close()

    print(f"\n=== Student Exams Import ===")
    print(f"Upserted: {inserted}, Errors: {errors}")
    print(f"Total in DB: {total}")
    print(f"Unique students: {students}")
    print(f"Date range: {date_range['min']} -> {date_range['max']}")

    # Ornek: Ali Kucukuysal son 3 sinavi
    conn = await asyncpg.connect(DB_URL)
    ali = await conn.fetch("""
        SELECT exam_name, exam_date, turkce, matematik, fizik, kimya, toplam
        FROM student_exams WHERE soz_no = 167
        ORDER BY exam_date DESC NULLS LAST LIMIT 5
    """)
    await conn.close()
    if ali:
        print(f"\n--- Ali Kucukuysal Son 5 Sinav ---")
        for r in ali:
            print(f"  {r['exam_date']} | {r['exam_name'][:35]:35s} | Tr:{r['turkce']} Mat:{r['matematik']} Fiz:{r['fizik']} Kim:{r['kimya']} Top:{r['toplam']}")


if __name__ == '__main__':
    asyncio.run(main())
