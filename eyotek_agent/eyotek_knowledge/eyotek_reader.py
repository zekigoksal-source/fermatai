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
# Cookie file: auto_login + session_keeper kayit ediyor, bu dosyadan okuyup ctx'e enjekte ederiz
# (ortak yer: proje root/.eyotek_session.json — eyotek_auto_login + session_keeper ile ayni)
_SESSION_FILE = Path(os.getenv("SESSION_FILE") or (Path(__file__).resolve().parent.parent.parent / ".eyotek_session.json"))


def _load_site_map() -> dict:
    with open(_SITE_MAP_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _load_cookies_from_file() -> list[dict]:
    """eyotek_auto_login / session_keeper'in kaydettigi cookie'leri yukle."""
    if not _SESSION_FILE.exists():
        return []
    try:
        data = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


async def _ensure_ctx_cookies(ctx) -> int:
    """ctx'e cookie dosyasindaki cookie'leri merge et — kalici Chromium yeni tab'i icin auth.

    Returns: enjekte edilen cookie sayisi.
    """
    file_cookies = _load_cookies_from_file()
    if not file_cookies:
        return 0
    # Playwright add_cookies icin minimum sema: name, value, domain, path
    # auto_login JSON'unda bunlar olmali ama yoksa default ekle
    cookies_to_add = []
    for c in file_cookies:
        if not c.get("name") or c.get("value") is None:
            continue
        # domain bos veya ayar yoksa default eyotek
        domain = c.get("domain") or "fermat.eyotek.com"
        path = c.get("path") or "/"
        item = {
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": path,
        }
        # Optional fields
        for k in ("expires", "httpOnly", "secure", "sameSite"):
            if k in c and c[k] is not None:
                item[k] = c[k]
        cookies_to_add.append(item)
    if cookies_to_add:
        try:
            await ctx.add_cookies(cookies_to_add)
        except Exception:
            return 0
    return len(cookies_to_add)


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

        # ── COOKIE ENJEKSIYONU ─────────────────────────────────────────────────
        # Kalici Chromium'un cookie jar'i bos olabilir (auto_login ayri instance'ta
        # cozuyor + cookie'leri dosyaya yaziyor). Bu yuzden her okuma oncesi cookie
        # dosyasini ctx'e merge ederiz — yeni tab dogru auth ile acilir.
        injected = await _ensure_ctx_cookies(ctx)

        page = await ctx.new_page()

        try:
            await page.goto(f'{BASE_URL}{path}', timeout=15000)
            await page.wait_for_timeout(3000)

            # Login sayfasina dustuysek cookie ge gecersiz — net hata don
            if "login" in page.url.lower() or page.url.rstrip("/").endswith("/v1"):
                result["error"] = (
                    f"Eyotek oturumu gecersiz (cookie file: {injected} cookie enjekte edildi "
                    f"ama login'e dusulduyse cookie expired). 'eyotek baglan' komutu ile yenile."
                )
                return result

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
