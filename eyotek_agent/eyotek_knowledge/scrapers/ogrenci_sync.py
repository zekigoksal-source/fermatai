"""
Öğrenci listesi sync — Eyotek'ten güncel öğrenci verisi.

Kullanım:
    from eyotek_knowledge.scrapers.ogrenci_sync import sync_ogrenci
    result = await sync_ogrenci()
"""
import asyncio
import os
import sys
import io
from datetime import datetime
from pathlib import Path

# Encoding sadece __main__'de

from dotenv import load_dotenv
load_dotenv()

BASE_URL = "https://fermat.eyotek.com/v1/Pages/"
IMPORTS_DIR = Path(__file__).parent.parent.parent / "imports"
_CDP_URL = f"http://localhost:{os.getenv('CDP_PORT', '9222')}"


async def _download_ogrenci_excel() -> str | None:
    """Eyotek Öğrenciler sayfasından Excel indir."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.connect_over_cdp(_CDP_URL)
    ctx = browser.contexts[0]
    page = await ctx.new_page()

    try:
        await page.goto(f'{BASE_URL}Student/student', timeout=15000)
        await page.wait_for_timeout(3000)

        # ARA modal aç
        try:
            await page.click('a.btn-circle.yellow', timeout=5000)
            await page.wait_for_timeout(1000)
        except Exception:
            pass

        # ARA tıkla
        for sel in ['#btnSearch', '#BtnSearch']:
            try:
                if await page.is_visible(sel):
                    await page.click(sel)
                    break
            except Exception:
                continue
        await page.wait_for_timeout(5000)

        # Excel indir
        for excel_sel in ['#btnExcel', '#btnPrintExcel']:
            try:
                if await page.is_visible(excel_sel):
                    IMPORTS_DIR.mkdir(exist_ok=True)
                    async with page.expect_download(timeout=30000) as dl_info:
                        await page.click(excel_sel)
                    download = await dl_info.value
                    ts = datetime.now().strftime('%Y%m%d_%H%M')
                    save_path = str(IMPORTS_DIR / f'ogrenci_sync_{ts}.xlsx')
                    await download.save_as(save_path)
                    return save_path
            except Exception:
                continue
        return None
    finally:
        await page.close()
        await pw.stop()


async def sync_ogrenci() -> dict:
    """Öğrenci listesi sync."""
    result = {"success": False, "downloaded": None, "updated": 0, "error": None}

    try:
        file_path = await _download_ogrenci_excel()
        if not file_path:
            result["error"] = "Öğrenci Excel indirilemedi"
            return result

        result["downloaded"] = file_path
        result["success"] = True
        result["note"] = "Excel indirildi — import için import_students.py kullan"

    except Exception as e:
        result["error"] = str(e)

    return result


if __name__ == '__main__':
    r = asyncio.run(sync_ogrenci())
    print(f"Sonuç: {r}")
