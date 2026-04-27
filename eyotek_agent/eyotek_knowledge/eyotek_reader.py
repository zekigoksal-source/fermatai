"""
Eyotek Reader — Bot'un anlık Eyotek okuma yeteneği.

Bot "etüt yoklamaya bak" veya "bugün yoklama durumu" dediğinde
CDP ile Eyotek sayfasına gidip veri okur.

NOT: Sadece OKUMA — yazma YAPMAZ. Admin yetkisi gerekli.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

_SITE_MAP_PATH = Path(__file__).parent / "site_map.json"
BASE_URL = "https://fermat.eyotek.com/v1/Pages/"
# CDP port: VPS'te 9333, laptop'ta 9222 (env var ile, default 9222)
_CDP_PORT = int(os.getenv("CDP_PORT", "9222"))
_CDP_URL = f"http://localhost:{_CDP_PORT}"


def _load_site_map() -> dict:
    with open(_SITE_MAP_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


async def read_eyotek_page(page_key: str, max_rows: int = 20) -> dict:
    """
    Eyotek sayfasından veri oku — CDP ile.

    page_key: site_map.json'daki sync_kaynaklar key'i (örn: "etut_ara", "yoklama_kontrol")
    max_rows: döndürülecek max satır

    Döner: {"success": bool, "rows": [...], "columns": [...], "error": str}
    """
    sm = _load_site_map()
    source = sm.get("sync_kaynaklar", {}).get(page_key)
    if not source:
        return {"success": False, "error": f"Bilinmeyen sayfa: {page_key}. Geçerli: {list(sm.get('sync_kaynaklar', {}).keys())}"}

    path = source["path"]
    result = {"success": False, "page": source["label"], "rows": [], "columns": [], "error": None}

    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(_CDP_URL)
        ctx = browser.contexts[0]
        page = await ctx.new_page()

        try:
            await page.goto(f'{BASE_URL}{path}', timeout=15000)
            await page.wait_for_timeout(3000)

            # Modal aç + ARA tıkla (gerekiyorsa)
            if source.get("search_modal"):
                modal_sel = source.get("modal_open", "a.btn-circle.yellow")
                try:
                    await page.click(modal_sel, timeout=5000)
                    await page.wait_for_timeout(1000)
                except Exception:
                    pass

                search_sel = source.get("search_btn", "#btnSearch")
                try:
                    if await page.is_visible(search_sel):
                        await page.click(search_sel)
                        await page.wait_for_timeout(5000)
                except Exception:
                    pass

            # Tablo oku
            headers = []
            th_elements = await page.query_selector_all('table thead th, table tr:first-child th')
            for th in th_elements:
                headers.append(((await th.text_content()) or '').strip())

            rows_data = []
            tr_elements = await page.query_selector_all('table tbody tr')
            for tr in tr_elements[:max_rows]:
                cells = await tr.query_selector_all('td')
                row = {}
                for i, cell in enumerate(cells):
                    col_name = headers[i] if i < len(headers) else f"col_{i}"
                    row[col_name] = ((await cell.text_content()) or '').strip()
                if row:
                    rows_data.append(row)

            result["columns"] = headers
            result["rows"] = rows_data
            result["row_count"] = len(rows_data)
            result["success"] = True

        finally:
            await page.close()
            await pw.stop()

    except Exception as e:
        result["error"] = str(e)

    return result


async def read_today_etut() -> dict:
    """Bugünün etüt verilerini Eyotek'ten anlık oku."""
    return await read_eyotek_page("etut_ara", max_rows=30)
