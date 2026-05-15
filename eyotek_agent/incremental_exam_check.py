"""
FermatAI — Incremental Exam Check (Yeni Sinav Otomatik Yakalayici)
====================================================================
Eyotek "Sinavlar" sayfasini tarayip kurum genelinde tanimli butun sinavlari
listeler. DB'de olmayan sinavlari tespit eder. Yeni sinav varsa:
1. exam_master tablosuna ekle
2. Bu sinava katilan ogrencileri tespit et (sinav istatistik sayfasindan)
3. student_exams ve student_exam_analysis guncellemesini tetikle

Akis (gunluk 06:00 cron):
  1. Eyotek Sinavlar sayfasi → tum sinavlar (kod, isim, tarih, tur)
  2. DB exam_master + student_exams ile karsilastir
  3. YENI sinav varsa → admin'e bildirim + sync_exams.py tetik
  4. Mevcut sinavlarda yeni katilim/net varsa → fill_missing_nets.py
  5. data_freshness'a sonuc yaz

Kullanim:
  python incremental_exam_check.py            # Kontrol et + rapor
  python incremental_exam_check.py --apply    # Yeni sinavlari import et
  python incremental_exam_check.py --notify   # Admin'e WP gonder
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, date

from dotenv import load_dotenv
from loguru import logger

try:
    from playwright.async_api import async_playwright, Page
except ImportError:
    async_playwright = None

load_dotenv(override=True)

from db_pool import get_pool as _get_pool, db_execute
CDP_URL = "http://localhost:9222"
BASE_URL = "https://fermat.eyotek.com/v1"


async def ensure_exam_master_table():
    """exam_master tablosu — kurum geneli sinav havuzu."""
    await db_execute("""
        CREATE TABLE IF NOT EXISTS exam_master (
            id SERIAL PRIMARY KEY,
            exam_code TEXT,
            exam_name TEXT,
            exam_date DATE,
            exam_type TEXT,
            sezon TEXT,
            first_seen TIMESTAMP DEFAULT NOW(),
            last_seen TIMESTAMP DEFAULT NOW(),
            student_exam_count INT DEFAULT 0,
            UNIQUE (exam_code, exam_date)
        )
    """)
    await db_execute("CREATE INDEX IF NOT EXISTS idx_exam_master_code ON exam_master(exam_code)")
    await db_execute("CREATE INDEX IF NOT EXISTS idx_exam_master_date ON exam_master(exam_date DESC)")


async def scrape_kurum_exams(page: "Page") -> list[dict]:
    """Eyotek 'Sinavlar' sayfasindan kurum geneli butun sinavlari listele."""
    SINAVLAR_URL = f"{BASE_URL}/Pages/Student/test"
    await page.goto(SINAVLAR_URL, wait_until="domcontentloaded", timeout=15000)
    await asyncio.sleep(3)

    # Login kontrol
    if "Login" in page.url or "Account" in page.url:
        logger.error("Login gerekli")
        return []

    # ARA modali — tum sinavlari getir (filtre temizle)
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('a, button');
        for (const b of btns) {
            if ((b.innerText||'').trim() === 'ARA' && b.offsetParent) { b.click(); return; }
        }
    }""")
    await asyncio.sleep(1.5)
    # Filtreleri temizle + listele
    await page.evaluate("""() => {
        ['txtSinavKodu','txtSinavAdi','txtBaslangicTarihi','txtBitisTarihi'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.value = ''; el.dispatchEvent(new Event('change',{bubbles:true})); }
        });
        const btn = document.getElementById('btnControl');
        if (btn) btn.click();
    }""")
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(2)

    # Tum sayfalardaki sinavlari topla
    all_exams = []
    page_num = 1
    while page_num <= 30:  # max 30 sayfa (cok abartilirsa)
        # Mevcut sayfadaki sinavlari oku
        sayfa_exams = await page.evaluate("""() => {
            const result = [];
            const rows = document.querySelectorAll('#GridView1 tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 4) continue;
                const r = {};
                for (let i = 0; i < cells.length; i++) {
                    const t = (cells[i].innerText || '').trim();
                    if (/^\\d{5,}$/.test(t) && !r.exam_code) r.exam_code = t;
                    else if (/^\\d{1,3}$/.test(t) && !r.exam_code) r.exam_code = t;
                    else if (t === 'TYT' || t === 'YKS' || t === 'LGS') r.exam_type = t;
                    else if (/^\\d{1,2}\\.\\d{2}\\.\\d{4}$/.test(t)) r.exam_date = t;
                    else if (t.length > 5 && !r.exam_name && !/^\\d+$/.test(t) && !['TYT','YKS','LGS'].includes(t)) r.exam_name = t;
                }
                if (r.exam_code && r.exam_name && r.exam_date) result.push(r);
            }
            return result;
        }""")
        all_exams.extend(sayfa_exams)
        logger.info(f"  Sayfa {page_num}: {len(sayfa_exams)} sinav (toplam {len(all_exams)})")

        # Sonraki sayfa var mi
        has_next = await page.evaluate(f"""() => {{
            const links = document.querySelectorAll('#GridView1 a');
            for (const a of links) {{
                if ((a.innerText || '').trim() === '{page_num + 1}') {{
                    a.click();
                    return true;
                }}
            }}
            return false;
        }}""")
        if not has_next:
            break
        await asyncio.sleep(2)
        page_num += 1

    return all_exams


async def diff_with_db(eyotek_exams: list[dict]) -> dict:
    """Eyotek'tekiyle DB'deki exam_master'i karsilastir."""
    await ensure_exam_master_table()
    pool = await _get_pool()
    conn = await pool.acquire()

    # Mevcut sinavlar
    existing = await conn.fetch("SELECT exam_code, exam_date FROM exam_master")
    existing_set = {(r['exam_code'], r['exam_date']) for r in existing}

    yeni = []
    seen_eyotek = set()
    for e in eyotek_exams:
        try:
            d = datetime.strptime(e['exam_date'], "%d.%m.%Y").date()
        except Exception:
            continue
        key = (e['exam_code'], d)
        seen_eyotek.add(key)
        if key not in existing_set:
            yeni.append({**e, 'exam_date_obj': d})

    # Yeni sinavlari ekle
    inserted = 0
    for e in yeni:
        try:
            await conn.execute("""
                INSERT INTO exam_master (exam_code, exam_name, exam_date, exam_type, sezon)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (exam_code, exam_date) DO UPDATE SET last_seen = NOW()
            """,
                e['exam_code'], e['exam_name'], e['exam_date_obj'],
                e.get('exam_type', ''),
                __import__('sinav_takvimi').aktif_sezon(),  # 25.44: hardcoded kaldırıldı
            )
            inserted += 1
        except Exception as ex:
            logger.warning(f"  Insert hata: {ex}")

    # Mevcutlarin last_seen guncelle
    if seen_eyotek:
        for code, d in seen_eyotek:
            try:
                await conn.execute(
                    "UPDATE exam_master SET last_seen = NOW() WHERE exam_code = $1 AND exam_date = $2",
                    code, d,
                )
            except Exception:
                pass

    # Bizim DB'de var ama Eyotek'te yok (silinmis veya farkli sezon)
    silinmis = []
    for code, d in existing_set:
        if (code, d) not in seen_eyotek:
            silinmis.append({'exam_code': code, 'exam_date': d})

    await pool.release(conn)
    return {
        'eyotek_total': len(eyotek_exams),
        'db_existing': len(existing_set),
        'yeni_sinav': yeni,
        'silinmis_olabilir': silinmis,
        'inserted': inserted,
    }


async def check_student_data_gaps() -> dict:
    """Hangi ogrenciler/sinavlarda eksik veri var?"""
    pool = await _get_pool()
    conn = await pool.acquire()
    # Son 30 gunde Eyotek'te eklenmis ama student_exams'a gelmemis
    rows = await conn.fetch("""
        SELECT em.exam_code, em.exam_name, em.exam_date, em.exam_type,
               COUNT(DISTINCT se.soz_no) FILTER (WHERE se.exam_name IS NOT NULL) as gelen_ogrenci
        FROM exam_master em
        LEFT JOIN student_exams se ON se.exam_name = em.exam_name OR se.exam_code = em.exam_code
        WHERE em.exam_date >= CURRENT_DATE - INTERVAL '30 days'
        GROUP BY em.exam_code, em.exam_name, em.exam_date, em.exam_type
        HAVING COUNT(DISTINCT se.soz_no) FILTER (WHERE se.exam_name IS NOT NULL) < 5
        ORDER BY em.exam_date DESC
    """)
    await pool.release(conn)
    return {'eksik_veri_sinavlari': [dict(r) for r in rows]}


def format_report(diff: dict, gaps: dict = None) -> str:
    """WP formatli rapor."""
    yeni = diff['yeni_sinav']
    lines = ["📅 *INCREMENTAL SINAV KONTROL*\n"]
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 Eyotek'te: *{diff['eyotek_total']}* sinav")
    lines.append(f"📊 DB'de: *{diff['db_existing']}* sinav")
    lines.append(f"➕ Yeni eklenen: *{diff['inserted']}* sinav")
    lines.append(f"⚠️ Eyotek'te yok: *{len(diff['silinmis_olabilir'])}*")
    lines.append("")

    if yeni:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🆕 *YENI SINAVLAR* (en yeni 10):")
        for e in sorted(yeni, key=lambda x: x.get('exam_date_obj', date.min), reverse=True)[:10]:
            t = e.get('exam_type', '?')
            d = e.get('exam_date_obj', '?')
            n = e.get('exam_name', '?')[:35]
            c = e.get('exam_code', '?')
            lines.append(f"  • [{t}] {d} — {n} (kod: {c})")

    if gaps and gaps.get('eksik_veri_sinavlari'):
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("⚠️ *Veri Eksik Sinavlar* (5'ten az ogrenci):")
        for g in gaps['eksik_veri_sinavlari'][:5]:
            lines.append(f"  • {g['exam_date']} — {g['exam_name'][:30]} ({g['gelen_ogrenci']} ogrenci)")

    if not yeni and not (gaps and gaps['eksik_veri_sinavlari']):
        lines.append("\n✅ *Sistem guncel — yeni sinav yok*")

    lines.append("\n_'sync baslat' yazarak yeni sinav verisi cekebilirsin._")
    return "\n".join(lines)


async def main():
    args = sys.argv[1:]
    apply_mode = "--apply" in args
    notify = "--notify" in args

    if async_playwright is None:
        logger.error("Playwright yok — pip install playwright")
        return

    pw = await async_playwright().start()
    from eyotek_browser_helper import connect_eyotek_or_fallback
    browser, page, _is_cdp = await connect_eyotek_or_fallback(pw, CDP_URL)
    ctx = page.context  # 25.46.9: helper kullanimi sonrasi ctx

    # Kurum geneli sinavlari cek
    logger.info("Eyotek 'Sinavlar' sayfasi taranıyor...")
    eyotek_exams = await scrape_kurum_exams(page)
    logger.info(f"Toplam {len(eyotek_exams)} sinav bulundu")

    if not eyotek_exams:
        logger.warning("Sinav listesi cekemedik — login veya selector sorunu olabilir")
        return

    # Diff
    diff = await diff_with_db(eyotek_exams)
    logger.info(f"Diff: {len(diff['yeni_sinav'])} yeni, {len(diff['silinmis_olabilir'])} olmayan")

    # Eksik veri kontrolu
    gaps = await check_student_data_gaps()

    # Rapor
    report = format_report(diff, gaps)
    print(report)

    # Admin'e WP gonder
    if notify and (diff['inserted'] > 0 or gaps['eksik_veri_sinavlari']):
        try:
            from whatsapp_bridge import send_wa_message
            ADMIN = "905051256802"
            # 22.1n-kural1
            await send_wa_message(ADMIN, report, _outreach=True, _reason="incremental_exam_check")
            logger.info("Admin'e WP gonderildi")
        except Exception as e:
            logger.error(f"WP gonderim hatasi: {e}")

    # Yeni sinav varsa sync_exams.py tetikle (apply mode)
    if apply_mode and diff['inserted'] > 0:
        logger.info("--apply: sync_exams.py tetiklenecek (yeni sinav verisi cek)")
        # Direkt subprocess yerine import + main calistir
        # Burada sadece logla, asil sync ayri proceste yapilir
        logger.info(f"  → komut: python sync_exams.py")

    # data_freshness guncelle
    try:
        await db_execute("""
            INSERT INTO data_freshness (module, last_sync, success, description)
            VALUES ('exam_master', NOW(), TRUE, $1)
            ON CONFLICT (module) DO UPDATE SET
              last_sync = NOW(), success = TRUE, description = EXCLUDED.description
        """, f"yeni:{diff['inserted']}, toplam:{diff['eyotek_total']}")
    except Exception as e:
        logger.debug(f"data_freshness guncellenemedi: {e}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
