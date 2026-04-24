"""
FermatAI — Toplu Sinav Analizi Cekimi
======================================
Tum ogrencilerin sinav birlestirme raporlarini Eyotek'ten ceker.
Playwright CDP ile calisiyor — Chrome port 9222'de acik olmali.

Kullanim:
  python scrape_exam_analysis.py          # Tum ogrenciler
  python scrape_exam_analysis.py 5        # Sadece ilk 5 ogrenci (test)

Cikti:
  exam_analysis_export/ klasorune JSON dosyalari
  + PostgreSQL student_exam_analysis tablosuna INSERT
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import async_playwright, Page

load_dotenv(override=True)

from db_pool import get_pool as _get_pool, DB_URL as DATABASE_URL
CDP_URL = "http://localhost:9222"
BASE_URL = "https://fermat.eyotek.com/v1"
EXPORT_DIR = Path("exam_analysis_export")
EXPORT_DIR.mkdir(exist_ok=True)


async def get_student_list_from_page(page: Page) -> list[dict]:
    """Sayfadaki ogrenci listesini cek."""
    rows = await page.evaluate("""
        () => {
            const students = [];
            const allRows = document.querySelectorAll('tr');
            for (const row of allRows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 8) continue;
                // Soz No'yu bul — rakam iceren hucre
                let sozNo = '', adi = '', soyadi = '';
                for (let i = 0; i < cells.length; i++) {
                    const t = cells[i]?.innerText?.trim();
                    if (/^\d{1,4}$/.test(t) && !sozNo) { sozNo = t; }
                    // Ad ve Soyad genellikle Soz No'dan 2-3 hucre sonra
                }
                // Bilinen pozisyonlar (ARA sonrasi grid):
                // 0=menu, 1=sezon, 2=sube, 3=kayit_tar, 4=soz_no, 5=okul_no, 6=adi, 7=soyadi
                sozNo = cells[4]?.innerText?.trim();
                adi = cells[6]?.innerText?.trim();
                soyadi = cells[7]?.innerText?.trim();
                if (sozNo && /^\d+$/.test(sozNo) && adi) {
                    const idx = students.length + 2;
                    const ctl = idx < 10 ? '0' + idx : '' + idx;
                    students.push({sozNo, name: adi + ' ' + soyadi, ctl});
                }
            }
            return students;
        }
    """)
    return rows


async def get_page_count(page: Page) -> int:
    """Toplam sayfa sayisini bul."""
    return await page.evaluate("""
        () => {
            const pagers = document.querySelectorAll('a[href*="Page$"]');
            let max = 1;
            for (const p of pagers) {
                const m = (p.getAttribute('href') || '').match(/Page\\$(\\d+)/);
                if (m) max = Math.max(max, parseInt(m[1]));
            }
            return max;
        }
    """)


async def navigate_to_exam_page(page: Page, ctl: str) -> str | None:
    """Ogrencinin sinav sayfasina git ve ST_Id'yi dondur."""
    await page.evaluate(f"__doPostBack('GridView1$ctl{ctl}$btnSinav','')")
    await asyncio.sleep(4)

    url = page.url
    if "student-test" not in url:
        return None

    # ST_Id'yi URL'den cikar
    match = re.search(r'St_Id=([^&]+)', url)
    return match.group(1) if match else None


async def run_exam_combine(page: Page, tab_name: str = "TYT") -> dict | None:
    """Sinav sayfasindaki belirli sekmedeki tum sinavlari birlestir ve rapor cek.

    tab_name: "TYT" veya "YKS" — onceLİ sekme geçişi yapilir.
    """

    # Önce tab geçişi — tab'a tıkla ve aktif olduğunu doğrula
    clicked = await page.evaluate(f"""() => {{
        const anchors = document.querySelectorAll('ul.nav-tabs > li > a, ul.nav > li > a');
        for (const a of anchors) {{
            if ((a.innerText || '').trim() === '{tab_name}') {{
                a.click();
                return true;
            }}
        }}
        return false;
    }}""")
    if not clicked:
        logger.warning(f"    {tab_name} sekmesi bulunamadi")
        return None

    # Polling: aktif tab pane'in {tab_name} ile uyumlu olduğunu doğrula
    # Aktif tab'in href'i veya parent LI.active text'i {tab_name} olmali
    active_tab = None
    for _ in range(15):  # max 15 × 0.4s = 6s
        await asyncio.sleep(0.4)
        active_tab = await page.evaluate("""() => {
            // Bootstrap: LI.active > A > text
            const activeLi = document.querySelector('ul.nav-tabs > li.active > a, ul.nav > li.active > a');
            return activeLi ? (activeLi.innerText || '').trim() : null;
        }""")
        if active_tab == tab_name:
            break

    if active_tab != tab_name:
        logger.warning(f"    {tab_name} aktif olmadi (su an: {active_tab})")
        # Yine de devam — bazi sayfalarda LI.active class olmayabilir

    # Ek bekleme: tab content (table rows) yüklenmesi
    # Aktif tab pane içinde en az 1 satır olana kadar bekle
    for _ in range(10):  # max 10 × 0.4s = 4s
        row_count = await page.evaluate("""() => {
            const panes = document.querySelectorAll('.tab-pane');
            for (const p of panes) {
                if (p.offsetParent !== null) {
                    return p.querySelectorAll('table tbody tr').length;
                }
            }
            return 0;
        }""")
        if row_count > 0:
            break
        await asyncio.sleep(0.4)

    # Katilim sayisini kontrol et — aktif tab pane'den
    body = await page.evaluate("""() => {
        const panes = document.querySelectorAll('.tab-pane');
        for (const p of panes) {
            if (p.offsetParent !== null) return p.innerText;
        }
        return document.body.innerText;
    }""")
    katildi_match = re.search(r'KATILDI\s*:\s*(\d+)', body)
    sinav_match = re.search(r'SINAV SAYISI\s*:\s*(\d+)', body)
    katildi = int(katildi_match.group(1)) if katildi_match else 0
    sinav_sayisi = int(sinav_match.group(1)) if sinav_match else 0
    logger.debug(f"    {tab_name} aktif: katildi={katildi}, sinav={sinav_sayisi}")

    if katildi < 1:
        logger.info(f"    {tab_name} katilim yok (0) — atlaniyor")
        return None
    # NOT: 1 sinav icin birlestirme aslinda gerekli degil ama
    # combine modal yine aciliyor, ders netleri detayi cekilebiliyor.

    # Tum checkbox'lari sec — SADECE aktif tab pane icinden
    boxes = await page.evaluate("""
        () => {
            const result = [];
            // Aktif tab pane bul
            let active = null;
            document.querySelectorAll('.tab-pane').forEach(p => {
                if (p.offsetParent !== null && !active) active = p;
            });
            const root = active || document;
            root.querySelectorAll('input[type=checkbox]').forEach(cb => {
                if (cb.offsetParent !== null && !cb.id && !cb.checked) {
                    const rect = cb.getBoundingClientRect();
                    result.push({x: Math.round(rect.x + rect.width/2), y: Math.round(rect.y + rect.height/2)});
                }
            });
            return result;
        }
    """)
    if not boxes:
        logger.info("    Checkbox bulunamadi — atlaniyor")
        return None

    for b in boxes:
        await page.mouse.click(b["x"], b["y"])
        await asyncio.sleep(0.2)
    logger.info(f"    {len(boxes)} checkbox tiklandi (fiziksel)")
    await asyncio.sleep(0.5)

    # Sayfayi yukari kaydir ve BIRLESTIR butonuna tikla
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(0.3)
    btn_pos = await page.evaluate("""
        () => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                if ((a.innerText || '').includes('Birleştir') || (a.innerText || '').includes('BİRLEŞTİR')) {
                    const rect = a.getBoundingClientRect();
                    return {x: Math.round(rect.x + rect.width/2), y: Math.round(rect.y + rect.height/2)};
                }
            }
            return null;
        }
    """)
    if not btn_pos:
        logger.warning("    Birlestir butonu bulunamadi")
        return None

    await page.mouse.click(btn_pos["x"], btn_pos["y"])
    await asyncio.sleep(2)

    # Diploma Notu: ComponentTest1_TxtHighSchoolScore inputuna 95 yaz
    diploma_input = page.locator("#ComponentTest1_TxtHighSchoolScore")
    try:
        await diploma_input.fill("95", timeout=3000)
    except Exception:
        logger.warning("    Diploma notu inputu bulunamadi")
        return None
    await asyncio.sleep(0.5)

    # DEVAM ET butonu: ComponentTest1_BtnBirlestir1
    devam_pos = await page.evaluate("""
        () => {
            const el = document.getElementById('ComponentTest1_BtnBirlestir1');
            if (el) {
                const rect = el.getBoundingClientRect();
                return {x: Math.round(rect.x + rect.width/2), y: Math.round(rect.y + rect.height/2)};
            }
            return null;
        }
    """)
    if not devam_pos:
        logger.warning("    Devam Et butonu bulunamadi")
        return None

    await page.mouse.click(devam_pos["x"], devam_pos["y"])
    await asyncio.sleep(8)

    # Combine sayfasina yonlendirildi mi?
    if "combine" not in page.url:
        logger.warning(f"    Combine sayfasina gidilemedi: {page.url.split('/')[-1][:30]}")
        return None

    # Rapor verilerini cek
    report = await page.evaluate("""
        () => {
            const result = {tables: [], fullText: document.body.innerText};
            document.querySelectorAll('table').forEach((tbl, idx) => {
                const h = Array.from(tbl.querySelectorAll('th')).map(th => th.innerText.trim());
                const r = [];
                tbl.querySelectorAll('tr').forEach(tr => {
                    if (tr.querySelector('th')) return;
                    const c = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                    if (c.length >= 2) r.push(c);
                });
                if (r.length > 0) result.tables.push({i: idx, h, r});
            });
            return result;
        }
    """)

    report["sinav_sayisi"] = sinav_sayisi
    report["katildi"] = katildi
    return report


def parse_report(report: dict, student_name: str, soz_no: str) -> dict:
    """Rapor verisinden DB'ye kaydedilecek yapiyi olustur.

    Hem TYT hem YKS (AYT) raporlarini destekler — etiket ne olursa olsun parse eder.
    """
    text = report.get("fullText", "")

    # Ham puan / yerleşme puanı: TYT veya AYT olabilir (sinav turune gore)
    ham = (re.search(r'(?:TYT|AYT|YKS|SAY|EA|S[ÖO]Z)[:\s]+([\d.,]+)\s*\n*HAM PUAN', text)
           or re.search(r'HAM PUAN[:\s]+([\d.,]+)', text)
           or re.search(r'([\d.,]+)\s*\n*HAM PUAN', text))
    yer = (re.search(r'(?:TYT|AYT|YKS|SAY|EA|S[ÖO]Z)[:\s]+([\d.,]+)\s*\n*YERLEŞME PUANI', text)
           or re.search(r'YERLEŞME PUANI[:\s]+([\d.,]+)', text)
           or re.search(r'([\d.,]+)\s*\n*YERLEŞME PUANI', text))
    osym = re.findall(r'ÖSYM\s*(\d{4})\s*([\d.]+)', text)
    osym_dict = {}
    for i in range(0, len(osym), 1):
        osym_dict[osym[i][0]] = osym[i][1]

    # Ders netleri (genellikle tablo 1)
    ders_netleri = []
    if len(report.get("tables", [])) > 1:
        t1 = report["tables"][1]
        for row in t1.get("r", []):
            if len(row) >= 6:
                ders_netleri.append({
                    "ders": row[0], "soru": row[1], "dogru": row[2],
                    "yanlis": row[3], "bos": row[4], "net": row[5],
                })

    # Oncelikli konular (tablo 2-3 genellikle)
    oncelikli = []
    for ti in [2, 3]:
        if ti < len(report.get("tables", [])):
            tbl = report["tables"][ti]
            konular = []
            for row in tbl.get("r", []):
                if len(row) >= 5:
                    konular.append({
                        "konu": row[0], "soru": row[1],
                        "yanlis": row[2], "bos": row[3], "yuzde": row[4],
                    })
            if konular:
                oncelikli.append({"level": ti - 1, "konular": konular})

    return {
        "full_name": student_name,
        "soz_no": soz_no,
        "ham_puan": ham.group(1) if ham else "",
        "yerlesme_puani": yer.group(1) if yer else "",
        "osym_2025_ham": osym_dict.get("2025", ""),
        "osym_2024_ham": osym_dict.get("2024", ""),
        "osym_2023_ham": osym_dict.get("2023", ""),
        "ders_netleri": ders_netleri,
        "oncelikli_konular": oncelikli,
        "sinav_sayisi": report.get("sinav_sayisi", 0),
        "katildi": report.get("katildi", 0),
    }


async def save_to_db(parsed: dict) -> None:
    """Parse edilmis sinav analizini DB'ye kaydet."""
    if not DATABASE_URL:
        return
    conn = await (await _get_pool()).acquire()
    try:
        await conn.execute("""
            INSERT INTO student_exam_analysis
            (eyotek_id, soz_no, full_name, sezon, diploma_notu,
             ham_puan, yerlesme_puani,
             osym_2025_ham, osym_2024_ham, osym_2023_ham,
             ders_netleri, oncelikli_konular,
             sinav_sayisi, katilan_sinav)
            VALUES ($1,$2,$3,'2025.26',95,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12)
            ON CONFLICT DO NOTHING
        """,
            parsed["soz_no"], parsed["soz_no"], parsed["full_name"],
            parsed["ham_puan"], parsed["yerlesme_puani"],
            parsed["osym_2025_ham"], parsed["osym_2024_ham"], parsed["osym_2023_ham"],
            json.dumps(parsed["ders_netleri"], ensure_ascii=False),
            json.dumps(parsed["oncelikli_konular"], ensure_ascii=False),
            parsed["sinav_sayisi"], parsed["katildi"],
        )
    finally:
        await conn.close()


async def save_ayt_to_db(parsed: dict) -> None:
    """AYT analizini ayri kolonlara yaz — TYT verisi varsa korunur."""
    if not DATABASE_URL:
        return
    conn = await (await _get_pool()).acquire()
    try:
        # Mevcut kayit var mi
        existing_id = await conn.fetchval(
            "SELECT id FROM student_exam_analysis WHERE soz_no::text = $1",
            str(parsed["soz_no"]),
        )
        if existing_id:
            # UPDATE — sadece AYT kolonlarini guncelle
            await conn.execute("""
                UPDATE student_exam_analysis SET
                  ham_puan_ayt = $1, yerlesme_puani_ayt = $2,
                  ders_netleri_ayt = $3::jsonb,
                  oncelikli_konular_ayt = $4::jsonb,
                  sinav_sayisi_ayt = $5, katilan_sinav_ayt = $6,
                  last_sync = NOW()
                WHERE id = $7
            """,
                parsed["ham_puan"], parsed["yerlesme_puani"],
                json.dumps(parsed["ders_netleri"], ensure_ascii=False),
                json.dumps(parsed["oncelikli_konular"], ensure_ascii=False),
                parsed["sinav_sayisi"], parsed["katildi"],
                existing_id,
            )
        else:
            # INSERT — TYT verisi yoksa AYT-only kayit
            await conn.execute("""
                INSERT INTO student_exam_analysis
                  (eyotek_id, soz_no, full_name, sezon, diploma_notu,
                   ham_puan_ayt, yerlesme_puani_ayt,
                   ders_netleri_ayt, oncelikli_konular_ayt,
                   sinav_sayisi_ayt, katilan_sinav_ayt, last_sync)
                VALUES ($1,$2,$3,'2025.26',95,$4,$5,$6::jsonb,$7::jsonb,$8,$9,NOW())
            """,
                parsed["soz_no"], parsed["soz_no"], parsed["full_name"],
                parsed["ham_puan"], parsed["yerlesme_puani"],
                json.dumps(parsed["ders_netleri"], ensure_ascii=False),
                json.dumps(parsed["oncelikli_konular"], ensure_ascii=False),
                parsed["sinav_sayisi"], parsed["katildi"],
            )
    finally:
        await conn.close()


async def main():
    args = sys.argv[1:]
    ayt_mode = "--ayt" in args
    if ayt_mode:
        args = [a for a in args if a != "--ayt"]
    max_students = int(args[0]) if args and args[0].isdigit() else 9999
    tab = "YKS" if ayt_mode else "TYT"
    logger.info(f"Toplu {tab} analizi baslatiliyor (max: {max_students})")

    # AYT modunda gerekli tablolar
    if ayt_mode:
        _pool_init = await _get_pool()
        async with _pool_init.acquire() as _conn_init:
            for sql in [
                "ALTER TABLE student_exam_analysis ADD COLUMN IF NOT EXISTS ham_puan_ayt TEXT",
                "ALTER TABLE student_exam_analysis ADD COLUMN IF NOT EXISTS yerlesme_puani_ayt TEXT",
                "ALTER TABLE student_exam_analysis ADD COLUMN IF NOT EXISTS oncelikli_konular_ayt JSONB",
                "ALTER TABLE student_exam_analysis ADD COLUMN IF NOT EXISTS sinav_sayisi_ayt INT",
                "ALTER TABLE student_exam_analysis ADD COLUMN IF NOT EXISTS katilan_sinav_ayt INT",
                "ALTER TABLE student_exam_analysis ADD COLUMN IF NOT EXISTS ders_netleri_ayt JSONB",
            ]:
                try:
                    await _conn_init.execute(sql)
                except Exception:
                    pass

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    ctx = browser.contexts[0]

    # Session cookies — AYT modunda mevcut Chrome cookie'leri kullan, override etme
    if not ayt_mode:
        try:
            with open(".eyotek_session.json", "r") as f:
                cookies = json.load(f)
            await ctx.add_cookies(cookies)
        except Exception:
            pass

    # Mevcut acik sayfayi kullan — new_page login sorunu yaratir
    if ctx.pages:
        page = ctx.pages[0]
    else:
        page = await ctx.new_page()

    # Ogrenci listesine git
    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    # Login kontrolu — AYT modunda da yap ama uri-bazli (Eyotek login sayfasi)
    if "Login" in page.url or "Account" in page.url:
        logger.error(f"Login gerekli — page.url={page.url}")
        await pw.stop()
        return

    # Header'dan sezon 2025.26'ya gecis
    logger.info("Sezon 2025.26 seciliyor (header dropdown)...")
    current_season = await page.evaluate("() => document.getElementById('BtnShowSeasons')?.innerText?.trim() || ''")
    if "2025.26" not in current_season:
        # Once sezon dropdown'u ac
        await page.evaluate("() => document.getElementById('BtnShowSeasons')?.click()")
        await asyncio.sleep(1)
        # 2025.26 linkine tikla
        await page.evaluate("""() => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                if (a.innerText.trim() === '2025.26' && a.id.includes('BtnSezonSec')) {
                    a.click();
                    return true;
                }
            }
            return false;
        }""")
        await asyncio.sleep(4)
        # Sayfa yeniden yuklenir — ogrenci listesine tekrar git
        await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
        await asyncio.sleep(4)
    else:
        logger.info("  Zaten 2025.26 sezonunda")

    # ARA modal ac → tum filtreleri temizle → btnControl ile arama yap
    await page.evaluate("""() => {
        const btns = document.querySelectorAll('a, button');
        for (const b of btns) {
            if ((b.innerText||'').trim() === 'ARA' && b.offsetParent) { b.click(); return; }
        }
    }""")
    await asyncio.sleep(2)
    # Tum filtre alanlarini temizle (onceki aramadan kalan degerler)
    await page.evaluate("""() => {
        ['txtAd','txtSoyad','txtOgNo','txtOkulNo','txtTcKimlik'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.value = ''; el.dispatchEvent(new Event('change',{bubbles:true})); }
        });
    }""")
    await asyncio.sleep(0.5)
    # btnControl tikla (modal icindeki ARA butonu)
    await page.evaluate("""() => {
        const btn = document.getElementById('btnControl');
        if (btn) { btn.click(); return; }
    }""")
    # Grid yuklenene kadar bekle (PostBack sonrasi sayfa yeniden render edilir)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(3)

    # Grid yuklendi mi kontrol et
    grid_check = await page.evaluate("""() => {
        const text = document.body.innerText;
        const match = text.match(/BULUNAN KAYIT SAYISI\\s*:\\s*(\\d+)/);
        return match ? parseInt(match[1]) : 0;
    }""")
    logger.info(f"Grid yuklendi: {grid_check} kayit")

    total_pages = await get_page_count(page)
    logger.info(f"Toplam sayfa: {total_pages}")

    processed = 0
    success = 0
    skipped = 0
    errors = 0

    for page_num in range(1, total_pages + 1):
        if processed >= max_students:
            break

        if page_num > 1:
            await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
            await asyncio.sleep(3)

        students = await get_student_list_from_page(page)
        logger.info(f"Sayfa {page_num}: {len(students)} ogrenci")

        for student in students:
            if processed >= max_students:
                break

            soz_no = student["sozNo"]
            name = student["name"]
            ctl = student["ctl"]
            processed += 1

            logger.info(f"[{processed}] {name} (soz_no={soz_no})")

            try:
                # Sinav sayfasina git
                st_id = await navigate_to_exam_page(page, ctl)
                if not st_id:
                    logger.info(f"    ST_Id alinamadi — atlaniyor")
                    skipped += 1
                    # Listeye geri don
                    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
                    await asyncio.sleep(3)
                    if page_num > 1:
                        await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                        await asyncio.sleep(3)
                    continue

                # AYT modunda 12.SAY/Mezun olmayanlari atla
                if ayt_mode:
                    # asenkron with sorgusu — bridge kontrol cok hizli
                    _pool_cls = await _get_pool()
                    async with _pool_cls.acquire() as _conn_cls:
                        cls_val = await _conn_cls.fetchval(
                            "SELECT class_name FROM students WHERE soz_no::text = $1", str(soz_no))
                    is_target = cls_val and ('12' in str(cls_val) or 'mez' in str(cls_val).lower())
                    if not is_target:
                        logger.info(f"    AYT atlandi (sinif: {cls_val})")
                        skipped += 1
                        # Listeye geri don
                        await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
                        await asyncio.sleep(3)
                        if page_num > 1:
                            await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                            await asyncio.sleep(3)
                        continue

                # Sinav birlestirme — TYT veya YKS sekmesinden
                report = await run_exam_combine(page, tab_name=tab)
                if not report:
                    skipped += 1
                    # Listeye geri don
                    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
                    await asyncio.sleep(3)
                    if page_num > 1:
                        await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                        await asyncio.sleep(3)
                    continue

                # Parse et
                parsed = parse_report(report, name, soz_no)

                # JSON dosyasina kaydet
                file_prefix = "ayt" if ayt_mode else "exam"
                fname = EXPORT_DIR / f"{file_prefix}_{soz_no}_{name.replace(' ','_')}.json"
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump({"student": name, "sozNo": soz_no, **report}, f,
                              ensure_ascii=False, indent=2)

                # DB'ye kaydet — AYT veya TYT
                if ayt_mode:
                    await save_ayt_to_db(parsed)
                else:
                    await save_to_db(parsed)

                ham = parsed.get("ham_puan", "?")
                logger.success(f"    OK: ham={ham}, sinav={parsed['sinav_sayisi']}, katildi={parsed['katildi']}")
                success += 1

            except Exception as e:
                logger.error(f"    HATA: {e}")
                errors += 1

            # Listeye geri don
            await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
            await asyncio.sleep(3)
            if page_num > 1:
                await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                await asyncio.sleep(3)

    # page.close() YAPMA — mevcut Chrome sayfasi
    # await pw.stop() YAPMA

    logger.info("=" * 50)
    logger.info(f"TAMAMLANDI: {processed} islendi, {success} basarili, {skipped} atlandi, {errors} hata")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
