"""
Eyotek Browser Helper — Headless Chrome + Cookie Inject (25.41 Neo bug)
========================================================================

NEO BUG (7 May): smart_sync 3 gündür FAILED.
SEBEP: connect_over_cdp("http://localhost:9222") — VPS'te Chrome açık değil
       (CDP olarak çalışmıyor, headless launch gerekli).

ÇÖZÜM: Bu helper headless Chromium başlatır, mevcut cookie'leri inject eder,
       cookie geçersizse eyotek_auto_login ile otomatik yeniler.

Kullanım:
    from eyotek_browser_helper import open_eyotek_browser

    async with open_eyotek_browser() as (browser, ctx, page):
        # page artık authenticated, Eyotek sayfalarına gidebilir
        await page.goto("https://fermat.eyotek.com/v1/student/...")
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from loguru import logger

from playwright.async_api import async_playwright


async def _read_session_file() -> list[dict] | None:
    """SESSION_FILE'dan cookie oku (interactive get_session() yerine).

    25.41 (Neo bug 7 May): eyotek_wrapper.get_session() systemd contextinde
    input() çağırıyor → EOFError. Bu fonksiyon NON-INTERACTIVE alternatif.

    İKİ FARKLI PATH desteği:
      - eyotek_auto_login.SESSION_FILE (parent dir, /opt/fermatai/.eyotek_session.json)
      - eyotek_wrapper.SESSION_FILE (cwd-relative, .eyotek_session.json)
    Önce auto_login path'i (asıl yazan yer), sonra wrapper fallback.
    """
    import json
    paths_to_try = []
    try:
        from eyotek_auto_login import SESSION_FILE as AUTO_SESSION
        paths_to_try.append(AUTO_SESSION)
    except Exception:
        pass
    try:
        from eyotek_wrapper import SESSION_FILE as WRAPPER_SESSION
        paths_to_try.append(WRAPPER_SESSION)
    except Exception:
        pass

    for path in paths_to_try:
        try:
            if not path.exists():
                continue
            text = path.read_text(encoding='utf-8')
            cookies = json.loads(text)
            if isinstance(cookies, list) and cookies:
                logger.info(f"[BROWSER] Cookie okundu: {path} ({len(cookies)} cookie)")
                return cookies
        except Exception as e:
            logger.debug(f"[BROWSER] {path} okunamadı: {e}")
    return None


@asynccontextmanager
async def open_eyotek_browser(
    headless: bool = True,
    timeout_ms: int = 60000,
    auto_login_on_fail: bool = True,
) -> AsyncGenerator[tuple, None]:
    """Eyotek için authenticated headless Chromium oturumu aç.

    Yields:
        (browser, context, page) — page authenticated state
    """
    from eyotek_wrapper import session_is_valid, save_session

    # ─── 1. Cookie oku — NON-INTERACTIVE ───────────────────
    cookies = await _read_session_file()

    # Cookie var ama geçerli değilse, veya yoksa → auto login
    needs_login = not cookies
    if cookies and not needs_login:
        try:
            valid = await session_is_valid(cookies)
            if not valid:
                needs_login = True
                logger.info("[BROWSER] Mevcut cookie expire, auto login deneniyor")
        except Exception:
            needs_login = True

    if needs_login and auto_login_on_fail:
        try:
            from eyotek_auto_login import try_auto_login
            result = await try_auto_login(timeout_ms=timeout_ms)
            if result.get("success"):
                # Auto_login zaten doğru path'e (parent dir) yazar, save_session
                # eski wrapper path'ine yazıyor ama önemli değil — re-read aşağıda
                cookies = await _read_session_file() or []
                logger.success(f"[BROWSER] Auto login OK ({len(cookies)} cookie)")
            else:
                logger.error(f"[BROWSER] Auto login fail: {result.get('message', '?')}")
                raise RuntimeError(f"Login fail: {result.get('reason', 'unknown')}")
        except Exception as e:
            logger.error(f"[BROWSER] Auto login exception: {e}")
            raise

    if not cookies:
        raise RuntimeError("Eyotek cookie'si alınamadı")

    # ─── 2. Headless Chromium başlat ────────────────────────
    pw = await async_playwright().start()
    browser = None
    try:
        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-gpu",
            ],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="tr-TR",
        )
        # Cookie inject — Eyotek domain
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        page.set_default_timeout(timeout_ms)

        yield browser, ctx, page

    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        try:
            await pw.stop()
        except Exception:
            pass


# ─── 25.46.9 (Neo direktif): connect_over_cdp YERINE TEK NOKTA — fallback'li ───
async def connect_eyotek_or_fallback(pw, cdp_url: str = None) -> tuple:
    """Once CDP dene, yoksa headless launch (cookies inject).

    Eski batch scripts'lerin tek satirla migrasyonu icin:
        OLD: browser = await pw.chromium.connect_over_cdp(CDP_URL)
             page = browser.contexts[0].pages[0]
        NEW: browser, page, is_cdp = await connect_eyotek_or_fallback(pw, CDP_URL)

    Args:
        pw: Playwright instance (caller olusturmus)
        cdp_url: CDP URL (default: env CDP_URL veya http://localhost:9222)

    Returns: (browser, page, is_cdp)
        is_cdp=True ise CDP modu (page = mevcut tab), close ETME (laptop Chrome'a dokunma)
        is_cdp=False ise headless mod (yeni browser), browser.close() caller'da
    """
    import os
    cdp_url = cdp_url or os.getenv("CDP_URL") or f"http://localhost:{os.getenv('CDP_PORT', '9222')}"

    # 1) CDP dene
    try:
        browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=3000)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        logger.info(f"[CONNECT] CDP modu: {cdp_url}")
        return browser, page, True
    except Exception as e:
        logger.info(f"[CONNECT] CDP yok ({str(e)[:60]}), headless fallback")

    # 2) Cookie + headless fallback
    from eyotek_wrapper import session_is_valid, save_session
    cookies = await _read_session_file()
    if not cookies or not await session_is_valid(cookies):
        logger.info("[CONNECT] Cookie expire/yok, auto-login")
        from eyotek_auto_login import try_auto_login
        result = await try_auto_login()
        if not result.get("success"):
            raise RuntimeError(f"Eyotek login fail: {result.get('message', '?')}")
        cookies = await _read_session_file()
    if not cookies:
        raise RuntimeError("Eyotek cookie alinamadi")

    browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage",
              "--disable-setuid-sandbox", "--disable-gpu"],
    )
    ctx = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        locale="tr-TR",
    )
    await ctx.add_cookies(cookies)
    page = await ctx.new_page()
    logger.info("[CONNECT] Headless mod (cookie inject)")
    return browser, page, False


# ─── Backward-compatible wrapper for legacy CDP code ──────────────────
async def get_eyotek_page() -> tuple:
    """Tek seferlik authenticated page döndürür (caller close etmeli).

    Returns: (browser, context, page) — caller close etmek zorunda
    Eski kod uyumluluğu için.

    25.41: NON-INTERACTIVE — interactive get_session() yerine direkt file oku
    """
    from eyotek_wrapper import session_is_valid, save_session

    cookies = await _read_session_file()
    if not cookies or not await session_is_valid(cookies):
        logger.info("[BROWSER] Cookie eksik/expire, auto login")
        from eyotek_auto_login import try_auto_login
        result = await try_auto_login()
        if not result.get("success"):
            raise RuntimeError(f"Login fail: {result.get('message')}")
        cookies = result.get("cookies") or []
        if cookies:
            save_session(cookies)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage",
              "--disable-setuid-sandbox", "--disable-gpu"],
    )
    ctx = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        locale="tr-TR",
    )
    await ctx.add_cookies(cookies)
    page = await ctx.new_page()
    return browser, ctx, page
