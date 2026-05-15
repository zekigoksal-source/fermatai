"""
Eksik ogrencilerin sinav analizini tek tek ceker.
ARA modalinda soz_no ile arama yaparak ogrenciyi bulur.
"""
import asyncio, json, os, re, sys
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import async_playwright

load_dotenv(override=True)
from db_pool import get_pool as _get_pool, db_fetch
BASE_URL = "https://fermat.eyotek.com/v1"
EXPORT_DIR = Path("exam_analysis_export")
EXPORT_DIR.mkdir(exist_ok=True)


async def main():
    # Eksik ogrencileri DB'den al
    missing = await db_fetch("""
        SELECT s.soz_no, s.full_name
        FROM students s
        LEFT JOIN student_exam_analysis e ON s.soz_no = e.soz_no
        WHERE e.soz_no IS NULL
        ORDER BY s.soz_no
    """)
    logger.info(f"Eksik ogrenci: {len(missing)}")

    if not missing:
        logger.info("Tum ogrenciler tamam!")
        return

    pw = await async_playwright().start()
    # 25.46.9 (Neo direktif): connect_over_cdp -> helper fallback (CDP yoksa headless)
    from eyotek_browser_helper import connect_eyotek_or_fallback
    browser, page, _is_cdp = await connect_eyotek_or_fallback(pw, "http://localhost:9222")
    ctx = page.context
    # 25.46.9: helper zaten cookie inject ediyor — manuel ekleme gerekmiyor.
    # Eski davranis korumak icin .eyotek_session.json'dan EK cookie varsa ekle:
    try:
        with open(".eyotek_session.json", "r") as f:
            await ctx.add_cookies(json.load(f))
    except Exception as _ce:
        pass  # helper'in cookie'leri yeterli
    success = 0
    skipped = 0
    errors = 0

    for idx, student in enumerate(missing):
        soz_no = student["soz_no"]
        name = student["full_name"]
        logger.info(f"[{idx+1}/{len(missing)}] {name} (soz_no={soz_no})")

        try:
            # Ogrenci listesine git
            await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # ARA modalini ac
            await page.evaluate("""() => {
                document.querySelectorAll('a,button').forEach(b => {
                    if ((b.innerText||'').trim()==='ARA' && b.offsetParent) b.click();
                });
            }""")
            await asyncio.sleep(2)

            # Filtreleri temizle + soz_no yaz
            await page.evaluate("""(sozNo) => {
                ['txtAd','txtSoyad','txtOkulNo','txtTcKimlik'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) { el.value = ''; el.dispatchEvent(new Event('change',{bubbles:true})); }
                });
                const ogNo = document.getElementById('txtOgNo');
                if (ogNo) {
                    ogNo.value = sozNo;
                    ogNo.dispatchEvent(new Event('change',{bubbles:true}));
                }
            }""", soz_no)
            await asyncio.sleep(0.5)

            # ARA tikla
            await page.evaluate("() => document.getElementById('btnControl')?.click()")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(3)

            # Grid'de ogrenci var mi?
            found = await page.evaluate("""() => {
                let count = 0;
                document.querySelectorAll('tr').forEach(r => {
                    if (r.querySelectorAll('td').length >= 8) count++;
                });
                return count;
            }""")

            if found == 0:
                logger.info(f"    Ogrenci bulunamadi — atlaniyor")
                skipped += 1
                continue

            # Sinav sayfasina git (ilk satirdaki btnSinav)
            await page.evaluate("__doPostBack('GridView1$ctl02$btnSinav','')")
            await asyncio.sleep(4)

            if "student-test" not in page.url:
                logger.info(f"    Sinav sayfasina gidilemedi — atlaniyor")
                skipped += 1
                continue

            # Katilim kontrolu
            body = await page.evaluate("() => document.body.innerText")
            katildi_m = re.search(r"KATILDI\s*:\s*(\d+)", body)
            sinav_m = re.search(r"SINAV SAYISI\s*:\s*(\d+)", body)
            katildi = int(katildi_m.group(1)) if katildi_m else 0
            sinav_sayisi = int(sinav_m.group(1)) if sinav_m else 0

            if katildi < 2:
                logger.info(f"    Katilim yetersiz ({katildi}) — atlaniyor")
                skipped += 1
                continue

            # Checkbox'lari fiziksel tikla
            boxes = await page.evaluate("""() => {
                const r = [];
                document.querySelectorAll('input[type=checkbox]').forEach(cb => {
                    if (cb.offsetParent && !cb.id && !cb.checked) {
                        const rect = cb.getBoundingClientRect();
                        r.push({x: Math.round(rect.x+rect.width/2), y: Math.round(rect.y+rect.height/2)});
                    }
                });
                return r;
            }""")

            if not boxes:
                logger.info(f"    Checkbox yok — atlaniyor")
                skipped += 1
                continue

            for b in boxes:
                await page.mouse.click(b["x"], b["y"])
                await asyncio.sleep(0.2)
            logger.info(f"    {len(boxes)} checkbox tiklandi")
            await asyncio.sleep(0.5)

            # Birlestir
            await page.evaluate("window.scrollTo(0,0)")
            await asyncio.sleep(0.3)
            btn = await page.evaluate("""() => {
                for (const a of document.querySelectorAll('a')) {
                    if ((a.innerText||'').includes('BİRLEŞTİR')) {
                        const r = a.getBoundingClientRect();
                        return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)};
                    }
                }
                return null;
            }""")
            if not btn:
                skipped += 1
                continue

            await page.mouse.click(btn["x"], btn["y"])
            await asyncio.sleep(2)

            # Diploma notu: 95
            try:
                await page.locator("#ComponentTest1_TxtHighSchoolScore").fill("95", timeout=3000)
            except Exception:
                skipped += 1
                continue
            await asyncio.sleep(0.5)

            # Devam Et
            devam = await page.evaluate("""() => {
                const el = document.getElementById('ComponentTest1_BtnBirlestir1');
                if (el) { const r = el.getBoundingClientRect(); return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}; }
                return null;
            }""")
            if not devam:
                skipped += 1
                continue

            await page.mouse.click(devam["x"], devam["y"])
            await asyncio.sleep(8)

            if "combine" not in page.url:
                logger.warning(f"    Combine sayfasina gidilemedi")
                skipped += 1
                continue

            # Rapor cek
            report = await page.evaluate("""() => {
                const r = {tables:[], fullText: document.body.innerText};
                document.querySelectorAll('table').forEach((t,i) => {
                    const h = Array.from(t.querySelectorAll('th')).map(th=>th.innerText.trim());
                    const rows = [];
                    t.querySelectorAll('tr').forEach(tr => {
                        if (tr.querySelector('th')) return;
                        const c = Array.from(tr.querySelectorAll('td')).map(td=>td.innerText.trim());
                        if (c.length>=2) rows.push(c);
                    });
                    if (rows.length>0) r.tables.push({i,h,r:rows});
                });
                return r;
            }""")

            # JSON kaydet
            fname = EXPORT_DIR / f"exam_{soz_no}_{name.replace(' ','_')}.json"
            with open(fname, "w", encoding="utf-8") as f:
                json.dump({"student": name, "sozNo": soz_no, **report}, f, ensure_ascii=False, indent=2)

            # DB'ye kaydet
            text = report.get("fullText", "")
            ham = re.search(r"TYT:\s*([\d.,]+)\s*\n*HAM PUAN", text)
            yer = re.search(r"TYT:\s*([\d.,]+)\s*\n*YERLE", text)
            osym = dict(re.findall(r"ÖSYM\s*(\d{4})\s*([\d.]+)", text))

            ders = []
            if len(report.get("tables",[])) > 1:
                for row in report["tables"][1].get("r",[])[:20]:
                    if len(row) >= 6:
                        ders.append({"ders":row[0],"soru":row[1],"dogru":row[2],"yanlis":row[3],"bos":row[4],"net":row[5]})

            onc = []
            for ti in [2,3]:
                if ti < len(report.get("tables",[])):
                    k = [{"konu":r[0],"soru":r[1],"yanlis":r[2],"bos":r[3]} for r in report["tables"][ti].get("r",[]) if len(r)>=4]
                    if k: onc.append({"level":ti-1,"konular":k})

            _pool = await _get_pool()
            async with _pool.acquire() as db:
                # 25.44 (Neo bug 14:25): sezon dinamik
                from sinav_takvimi import aktif_sezon as _aktif_fn
                _AKTIF = _aktif_fn()
                await db.execute(f"""
                    INSERT INTO student_exam_analysis
                    (eyotek_id,soz_no,full_name,sezon,diploma_notu,ham_puan,yerlesme_puani,
                     osym_2025_ham,osym_2024_ham,osym_2023_ham,ders_netleri,oncelikli_konular,
                     sinav_sayisi,katilan_sinav)
                    VALUES ($1,$2,$3,'{_AKTIF}',95,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12)
                    ON CONFLICT DO NOTHING
                """, soz_no, soz_no, name,
                    ham.group(1) if ham else "", yer.group(1) if yer else "",
                    osym.get("2025",""), osym.get("2024",""), osym.get("2023",""),
                    json.dumps(ders, ensure_ascii=False), json.dumps(onc, ensure_ascii=False),
                    sinav_sayisi, katildi)

            logger.success(f"    OK: ham={ham.group(1) if ham else '?'}, sinav={sinav_sayisi}, katildi={katildi}")
            success += 1

        except Exception as e:
            logger.error(f"    HATA: {e}")
            errors += 1

    await page.close()
    await pw.stop()

    logger.info("=" * 50)
    logger.info(f"TAMAMLANDI: {len(missing)} islendi, {success} basarili, {skipped} atlandi, {errors} hata")
    logger.info("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
