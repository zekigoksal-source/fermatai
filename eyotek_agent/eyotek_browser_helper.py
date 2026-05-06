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
    from eyotek_wrapper import get_session, session_is_valid, save_session

    # ─── 1. Cookie al ───────────────────────────────────────
    cookies = await get_session()

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
                cookies = result.get("cookies") or []
                if cookies:
                    save_session(cookies)
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


# ─── Backward-compatible wrapper for legacy CDP code ──────────────────
async def get_eyotek_page() -> tuple:
    """Tek seferlik authenticated page döndürür (caller close etmeli).

    Returns: (browser, context, page) — caller close etmek zorunda
    Eski kod uyumluluğu için.
    """
    from eyotek_wrapper import get_session, session_is_valid, save_session

    cookies = await get_session()
    if not cookies or not await session_is_valid(cookies):
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
