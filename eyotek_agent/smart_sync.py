"""
FermatAI Smart Sync V2
=======================
Akıllı sınav senkronizasyonu — sadece yeni sınav olan öğrencileri günceller.

Özellikler:
  1. Incremental: Yeni sınava girmediyse ATLA (DB'deki sınav sayısı vs Eyotek karşılaştır)
  2. TYT + AYT birlikte: Aynı öğrencide hem TYT hem YKS sekmesi kontrol
  3. Hata koruması: timeout/lag tespiti, kaldığından devam
  4. Progress tracking: sync_tracking tablosunda her öğrencinin durumu
  5. Admin bildirim: tamamlandığında/hata olduğunda WP mesajı

Kullanım:
  python smart_sync.py              # Sadece yeni sınavı olanları güncelle
  python smart_sync.py --full       # Herkesi güncelle (sıfırdan)
  python smart_sync.py --resume     # Kaldığı yerden devam et
  python smart_sync.py 5            # İlk 5 öğrenci (test)
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
ADMIN_PHONE = "905051256802"


# ═══════════════════════════════════════════════════════════════════
# EYOTEK NAVIGASYON
# ═══════════════════════════════════════════════════════════════════

async def open_student_list(page: Page) -> int:
    """Öğrenci listesini aç + ARA yap."""
    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    if await page.evaluate("() => !!document.getElementById('btnLogin')"):
        logger.error("Login gerekli!")
        return 0

    # ARA
    await page.evaluate("""() => {
        document.querySelectorAll('a, button').forEach(b => {
            if ((b.innerText||'').trim() === 'ARA' && b.offsetParent) b.click();
        });
    }""")
    await asyncio.sleep(2)

    # Filtreleri temizle + ARA
    await page.evaluate("""() => {
        ['txtAd','txtSoyad','txtOgNo','txtOkulNo','txtTcKimlik'].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = '';
        });
    }""")
    await asyncio.sleep(0.5)
    await page.evaluate("() => document.getElementById('btnControl')?.click()")
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(3)

    count = await page.evaluate("""() => {
        const m = document.body.innerText.match(/BULUNAN KAYIT SAYISI\\s*:\\s*(\\d+)/);
        return m ? parseInt(m[1]) : 0;
    }""")
    return count


async def get_page_count(page: Page) -> int:
    return await page.evaluate("""() => {
        let max = 1;
        document.querySelectorAll('a[href*="Page$"]').forEach(p => {
            const m = (p.getAttribute('href')||'').match(/Page\\$(\\d+)/);
            if (m) max = Math.max(max, parseInt(m[1]));
        });
        return max;
    }""")


async def get_students_on_page(page: Page) -> list[dict]:
    return await page.evaluate("""() => {
        const result = [];
        const rows = document.querySelectorAll('#GridView1 tr');
        for (let i = 2; i < rows.length; i++) {
            const cells = rows[i].querySelectorAll('td');
            if (cells.length < 8) continue;
            const sozNo = (cells[4]?.innerText||'').trim();
            const ad = (cells[6]?.innerText||'').trim();
            const soyad = (cells[7]?.innerText||'').trim();
            if (!sozNo || !/^\\d+$/.test(sozNo)) continue;
            result.push({sozNo, name: ad+' '+soyad, ctl: (i<10?'0':'')+i});
        }
        return result;
    }""")


async def get_exam_counts(page: Page) -> dict:
    """Sınav sayfasındaki TYT ve YKS sınav+katılım sayılarını çek."""
    result = {"tyt_total": 0, "tyt_katildi": 0, "yks_total": 0, "yks_katildi": 0}

    # TYT sekmesi varsayılan açık
    body = await page.evaluate("() => document.body.innerText")
    m_sinav = re.search(r'SINAV SAYISI\s*:\s*(\d+)', body)
    m_katildi = re.search(r'KATILDI\s*:\s*(\d+)', body)
    result["tyt_total"] = int(m_sinav.group(1)) if m_sinav else 0
    result["tyt_katildi"] = int(m_katildi.group(1)) if m_katildi else 0

    # YKS sekmesi var mı?
    has_yks = await page.evaluate("""() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
            if (walker.currentNode.textContent.trim() === 'YKS' &&
                walker.currentNode.parentElement.tagName === 'SPAN') return true;
        }
        return false;
    }""")

    if has_yks:
        # YKS sekmesine tıkla
        await page.evaluate("""() => {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
                if (walker.currentNode.textContent.trim() === 'YKS' &&
                    walker.currentNode.parentElement.tagName === 'SPAN') {
                    walker.currentNode.parentElement.click(); return;
                }
            }
        }""")
        await asyncio.sleep(2)

        body2 = await page.evaluate("() => document.body.innerText")
        m2 = re.search(r'SINAV SAYISI\s*:\s*(\d+)', body2)
        m2k = re.search(r'KATILDI\s*:\s*(\d+)', body2)
        result["yks_total"] = int(m2.group(1)) if m2 else 0
        result["yks_katildi"] = int(m2k.group(1)) if m2k else 0

        # TYT'ye geri dön
        await page.evaluate("""() => {
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
                if (walker.currentNode.textContent.trim() === 'TYT' &&
                    walker.currentNode.parentElement.tagName === 'SPAN') {
                    walker.currentNode.parentElement.click(); return;
                }
            }
        }""")
        await asyncio.sleep(1)

    return result


async def needs_update(conn, soz_no: int, exam_counts: dict) -> bool:
    """Bu öğrencinin güncellenmesi gerekiyor mu?"""
    row = await conn.fetchrow(
        "SELECT tyt_sinav_sayisi, tyt_katildi, ayt_sinav_sayisi, ayt_katildi FROM sync_tracking WHERE soz_no = $1",
        soz_no)

    if not row:
        return True  # Hiç sync yapılmamış

    # Sınav sayıları değişmiş mi?
    if (row['tyt_sinav_sayisi'] != exam_counts['tyt_total'] or
        row['tyt_katildi'] != exam_counts['tyt_katildi'] or
        row['ayt_sinav_sayisi'] != exam_counts['yks_total'] or
        row['ayt_katildi'] != exam_counts['yks_katildi']):
        return True

    return False  # Değişiklik yok


async def update_tracking(conn, soz_no: int, name: str, exam_counts: dict, status: str, error: str = ""):
    """Sync tracking tablosunu güncelle."""
    await conn.execute("""
        INSERT INTO sync_tracking (soz_no, full_name, tyt_sinav_sayisi, tyt_katildi,
            ayt_sinav_sayisi, ayt_katildi, last_sync, sync_status, error_detail, needs_update)
        VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7, $8, FALSE)
        ON CONFLICT (soz_no) DO UPDATE SET
            tyt_sinav_sayisi = $3, tyt_katildi = $4,
            ayt_sinav_sayisi = $5, ayt_katildi = $6,
            last_sync = NOW(), sync_status = $7, error_detail = $8,
            needs_update = FALSE
    """, soz_no, name,
        exam_counts.get('tyt_total', 0), exam_counts.get('tyt_katildi', 0),
        exam_counts.get('yks_total', 0), exam_counts.get('yks_katildi', 0),
        status, error)


async def send_admin_notification(message: str):
    """Admin'e WP bildirim gönder."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post("http://localhost:8001/send",
                              json={"phone": ADMIN_PHONE, "message": message})
    except Exception as e:
        logger.debug(f"WP bildirim hatası: {e}")


# ═══════════════════════════════════════════════════════════════════
# ANA SYNC AKIŞI
# ═══════════════════════════════════════════════════════════════════

async def main():
    limit = 9999
    full_mode = "--full" in sys.argv
    resume_mode = "--resume" in sys.argv

    for arg in sys.argv[1:]:
        if arg.isdigit():
            limit = int(arg)

    pool = await _get_pool()
    conn = await pool.acquire()

    # Resume modu — kaldığı yerden devam
    start_from = 0
    if resume_mode:
        last = await conn.fetchval(
            "SELECT COUNT(*) FROM sync_tracking WHERE sync_status IN ('completed','skipped') AND last_sync >= CURRENT_DATE")
        start_from = last or 0
        logger.info(f"Resume: {start_from} öğrenci zaten tamamlanmış, kaldığından devam")

    # Full modu — tracking'i sıfırla
    if full_mode:
        await conn.execute("UPDATE sync_tracking SET needs_update = TRUE")
        logger.info("Full mode: tüm öğrenciler yeniden taranacak")

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    ctx = browser.contexts[0]
    page = ctx.pages[0]

    total_records = await open_student_list(page)
    if total_records == 0:
        logger.error("Öğrenci listesi açılamadı!")
        await send_admin_notification("⚠️ *Sync Hatası*\n\nÖğrenci listesi açılamadı. Eyotek session kontrol edilmeli.")
        await pool.release(conn)
        return

    total_pages = await get_page_count(page)
    logger.info(f"Toplam: {total_records} öğrenci, {total_pages} sayfa")

    processed = 0
    updated = 0
    skipped = 0
    errors = 0
    skipped_no_change = 0

    # Lag/tekrar tespiti
    last_soz_no = None
    same_page_counter = 0

    try:
        for page_num in range(1, total_pages + 1):
            if processed >= limit:
                break

            if page_num > 1:
                await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                await asyncio.sleep(3)

            students = await get_students_on_page(page)
            logger.info(f"Sayfa {page_num}: {len(students)} öğrenci")

            if not students:
                same_page_counter += 1
                if same_page_counter >= 3:
                    logger.error("3 boş sayfa üst üste — sync durduruluyor")
                    break
                continue
            same_page_counter = 0

            for student in students:
                if processed >= limit:
                    break

                soz_no = int(student['sozNo'])
                name = student['name']
                ctl = student['ctl']
                processed += 1

                # Resume: zaten tamamlananları atla
                if resume_mode and processed <= start_from:
                    continue

                # Tekrar tespiti
                if soz_no == last_soz_no:
                    logger.warning(f"Tekrar tespit: soz_no={soz_no} — sayfa atlama sorunu?")
                    errors += 1
                    continue
                last_soz_no = soz_no

                logger.info(f"[{processed}/{total_records}] {name} (soz:{soz_no})")

                # Sınav sayfasına git
                try:
                    await page.evaluate(f"__doPostBack('GridView1$ctl{ctl}$btnSinav','')")
                    await asyncio.sleep(4)
                except Exception as e:
                    logger.warning(f"    Buton hatası: {e}")
                    await update_tracking(conn, soz_no, name, {}, "error", str(e))
                    errors += 1
                    # Listeye geri dön
                    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
                    await asyncio.sleep(3)
                    await page.evaluate("""() => {
                        document.querySelectorAll('a, button').forEach(b => {
                            if ((b.innerText||'').trim()==='ARA' && b.offsetParent) b.click();
                        });
                    }""")
                    await asyncio.sleep(1)
                    await page.evaluate("() => document.getElementById('btnControl')?.click()")
                    await asyncio.sleep(3)
                    if page_num > 1:
                        await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                        await asyncio.sleep(3)
                    continue

                if "student-test" not in page.url:
                    logger.warning(f"    Sınav sayfası açılmadı")
                    await update_tracking(conn, soz_no, name, {}, "error", "student-test not in URL")
                    errors += 1
                    await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
                    await asyncio.sleep(3)
                    await page.evaluate("""() => {
                        document.querySelectorAll('a, button').forEach(b => {
                            if ((b.innerText||'').trim()==='ARA' && b.offsetParent) b.click();
                        });
                    }""")
                    await asyncio.sleep(1)
                    await page.evaluate("() => document.getElementById('btnControl')?.click()")
                    await asyncio.sleep(3)
                    if page_num > 1:
                        await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                        await asyncio.sleep(3)
                    continue

                # Sınav sayılarını kontrol et (TYT + AYT)
                exam_counts = await get_exam_counts(page)
                logger.info(f"    TYT: {exam_counts['tyt_total']} sınav ({exam_counts['tyt_katildi']} katıldı) | AYT: {exam_counts['yks_total']} ({exam_counts['yks_katildi']} katıldı)")

                # Yeni sınav var mı?
                if not full_mode and not await needs_update(conn, soz_no, exam_counts):
                    logger.info(f"    → Değişiklik yok, ATLANIYOR")
                    await update_tracking(conn, soz_no, name, exam_counts, "skipped")
                    skipped_no_change += 1
                else:
                    # Güncelleme gerekli — tracking'e kaydet
                    await update_tracking(conn, soz_no, name, exam_counts, "completed")
                    updated += 1

                # Listeye geri dön
                await page.goto(f"{BASE_URL}/Pages/Student/student", wait_until="domcontentloaded")
                await asyncio.sleep(3)
                await page.evaluate("""() => {
                    document.querySelectorAll('a, button').forEach(b => {
                        if ((b.innerText||'').trim()==='ARA' && b.offsetParent) b.click();
                    });
                }""")
                await asyncio.sleep(1)
                await page.evaluate("() => document.getElementById('btnControl')?.click()")
                await asyncio.sleep(3)
                if page_num > 1:
                    await page.evaluate(f"__doPostBack('GridView1','Page${page_num}')")
                    await asyncio.sleep(3)

    except Exception as e:
        logger.error(f"SYNC HATASI: {e}")
        await send_admin_notification(
            f"⚠️ *Sync Hatası*\n\n"
            f"Hata: {str(e)[:100]}\n"
            f"İşlenen: {processed}, Güncellenen: {updated}, Hata: {errors}\n\n"
            f"_Kaldığından devam: python smart_sync.py --resume_"
        )

    await pool.release(conn)

    # Sonuç raporu
    report = (
        f"📊 *Smart Sync V2 Raporu*\n\n"
        f"---\n\n"
        f"İşlenen: *{processed}* öğrenci\n"
        f"Güncellenen: *{updated}*\n"
        f"Değişiklik yok (atlanan): *{skipped_no_change}*\n"
        f"Hata: *{errors}*\n\n"
        f"---\n"
        f"_{'Tamamlandı' if errors == 0 else 'Hatalarla tamamlandı'}_"
    )

    logger.info(f"\n{'='*50}")
    logger.info(report.replace('*', '').replace('_', ''))

    # Admin'e bildir
    await send_admin_notification(report)

    # Post-sync güncelleme
    if updated > 0:
        logger.info("Post-sync güncelleme başlatılıyor...")
        try:
            from post_sync_update import update_topic_tracker, update_exam_summaries
            await update_topic_tracker()
            await update_exam_summaries()
            logger.info("Post-sync güncelleme tamamlandı")
        except Exception as e:
            logger.warning(f"Post-sync hatası: {e}")


if __name__ == "__main__":
    asyncio.run(main())
