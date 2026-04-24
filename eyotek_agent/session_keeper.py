"""
Session Keep-Alive + Drop Detection + WP Admin Notification

Her 5 dakikada Eyotek session'i kontrol eder:
- Gecerliyse: session_status = "online", son_kontrol guncellenir
- Gecersizse: WP ile admin'e bildirim gonderir, session_status = "offline"

Admin WP'den "eyotek onayla" yazdiginda, sistem Chrome'dan taze cookie alir.
"""
import asyncio
import json
import os
import time
import httpx
from pathlib import Path
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv

load_dotenv(override=True)

# Config
SESSION_FILE = Path(os.getenv("SESSION_FILE", ".eyotek_session.json"))
STATUS_FILE = Path(".eyotek_status.json")
BASE_URL = "https://fermat.eyotek.com/v1"
CHECK_INTERVAL = 180  # 3 dakika — ASP.NET session ~20-30dk timeout, 3dk yeterli
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "905xxxxxxxxx")
WP_API_URL = os.getenv("WP_API_URL", "http://localhost:8001")


def load_session() -> list[dict] | None:
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return None


def cookies_to_header(cookies: list[dict]) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def update_status(status: str, detail: str = ""):
    data = {
        "eyotek_session": status,  # "online" | "offline" | "refreshing"
        "last_check": datetime.now().isoformat(),
        "detail": detail,
        "uptime_start": None
    }
    # Preserve uptime_start
    if STATUS_FILE.exists():
        try:
            old = json.loads(STATUS_FILE.read_text())
            if old.get("uptime_start"):
                data["uptime_start"] = old["uptime_start"]
        except Exception:
            pass
    if status == "online" and not data["uptime_start"]:
        data["uptime_start"] = datetime.now().isoformat()
    elif status == "offline":
        data["uptime_start"] = None

    STATUS_FILE.write_text(json.dumps(data, indent=2))
    return data


async def check_session() -> bool:
    """Session gecerli mi? Once CDP ile, fallback HTTP."""
    # Yontem 1: CDP — Chrome tab uzerinden kontrol (en guvenilir)
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
            ctx = browser.contexts[0]
            for page in ctx.pages:
                if "eyotek" in page.url.lower():
                    has_login = await page.evaluate(
                        "() => !!document.getElementById('btnLogin')")
                    return not has_login
        finally:
            await pw.stop()
    except Exception:
        pass

    # Yontem 2: HTTP GET fallback
    cookies = load_session()
    if not cookies:
        return False
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
            r = await client.get(
                f"{BASE_URL}/Pages/Staff/home",
                headers={
                    "Cookie": cookies_to_header(cookies),
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                },
            )
            return r.status_code == 200
    except Exception:
        return False


async def keep_session_warm():
    """Session'i canli tutmak icin hafif istek at — once CDP, fallback HTTP."""
    # Yontem 1: CDP ile Chrome tab'da gercek sayfa yenilemesi (en guvenilir)
    try:
        cdp_ok = await _cdp_keep_alive()
        if cdp_ok:
            return True
    except Exception as e:
        logger.debug(f"CDP keep-alive basarisiz: {e}")

    # Yontem 2: HTTP GET fallback
    cookies = load_session()
    if not cookies:
        return False
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            r = await client.get(
                f"{BASE_URL}/Pages/Staff/home",
                headers={
                    "Cookie": cookies_to_header(cookies),
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                },
            )
            return r.status_code == 200
    except Exception:
        return False


async def _cdp_keep_alive() -> bool:
    """Chrome CDP uzerinden Eyotek tab'ini yenileyerek session'i canli tut."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]

        # Eyotek tab'ini bul
        eyotek_page = None
        for page in ctx.pages:
            if "eyotek" in page.url.lower():
                eyotek_page = page
                break

        if not eyotek_page:
            logger.debug("CDP: Eyotek tab bulunamadi")
            return False

        # Login sayfasina dusmus mu kontrol et
        has_login = await eyotek_page.evaluate(
            "() => !!document.getElementById('btnLogin')")

        if has_login:
            logger.warning("CDP: Login sayfasina dusulmus — session expired!")
            # Chrome'un diger tab/cookie'lerinden yenilemeyi dene
            await _try_cookie_refresh(ctx, eyotek_page)
            return False

        # Session gecerli — sayfa icinde hafif bir istek yap
        # ASP.NET ViewState'i korumak icin sayfayi reload etmiyoruz,
        # bunun yerine AJAX benzeri bir JS calistiriyoruz
        await eyotek_page.evaluate("""() => {
            // XMLHttpRequest ile session cookie'yi yenile
            const xhr = new XMLHttpRequest();
            xhr.open('GET', '/v1/Pages/Staff/home', true);
            xhr.send();
        }""")

        # Cookie'leri session dosyasina yaz (guncelle)
        all_cookies = await ctx.cookies()
        eyotek_cookies = [c for c in all_cookies if "eyotek" in c.get("domain", "")]
        if eyotek_cookies:
            import json as _json
            SESSION_FILE.write_text(
                _json.dumps(eyotek_cookies, indent=2), encoding="utf-8")

        logger.debug(f"CDP keep-alive OK ({len(eyotek_cookies)} cookie guncellendi)")
        return True

    except Exception as e:
        logger.debug(f"CDP keep-alive hata: {e}")
        return False
    finally:
        await pw.stop()


async def _try_cookie_refresh(ctx, page):
    """Login sayfasina dusulunce Chrome cookie'lerinden session yenilemeyi dene."""
    try:
        all_cookies = await ctx.cookies()
        eyotek_cookies = [c for c in all_cookies if "eyotek" in c.get("domain", "")]
        if eyotek_cookies:
            await ctx.add_cookies(eyotek_cookies)
            await page.reload(wait_until="domcontentloaded")
            await asyncio.sleep(3)
            # Login hala var mi?
            still_login = await page.evaluate(
                "() => !!document.getElementById('btnLogin')")
            if not still_login:
                logger.success("Cookie refresh basarili — session geri geldi!")
                import json as _json
                SESSION_FILE.write_text(
                    _json.dumps(eyotek_cookies, indent=2), encoding="utf-8")
                return True
    except Exception as e:
        logger.debug(f"Cookie refresh hata: {e}")
    return False


async def notify_admin(message: str):
    """WP ile admin'e bildirim gonder — direkt Graph API."""
    wa_token = os.getenv("WA_ACCESS_TOKEN", "")
    wa_phone_id = os.getenv("WA_PHONE_NUMBER_ID", "")
    admin_phone = os.getenv("ADMIN_PHONE", "905051256802")

    if not wa_token or not wa_phone_id:
        logger.warning(f"WP bildirim gonderilemedi — token/phone_id eksik")
        return

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://graph.facebook.com/v25.0/{wa_phone_id}/messages",
                headers={
                    "Authorization": f"Bearer {wa_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": admin_phone,
                    "type": "text",
                    "text": {"body": message[:4096]},
                },
            )
            if r.status_code == 200:
                logger.info(f"WP bildirim gonderildi: {message[:50]}...")
            else:
                logger.warning(f"WP bildirim hata {r.status_code}: {r.text[:100]}")
    except Exception as e:
        logger.warning(f"WP bildirim gonderilemedi: {e}")


async def session_keeper_loop():
    """
    Ana dongu: her 5 dakikada session kontrol et.
    Online → keep-warm istegi at.
    Offline → admin'e bildir, beklemeye gec.
    """
    logger.info("Session Keeper baslatildi")
    was_online = False
    offline_notified = False

    while True:
        try:
            is_valid = await check_session()

            if is_valid:
                update_status("online", "Session aktif")
                if not was_online:
                    logger.success("Eyotek session ONLINE")
                    if offline_notified:
                        await notify_admin(
                            "[FERMAT] Eyotek session yeniden aktif! Sistem online."
                        )
                    offline_notified = False
                was_online = True

                # Keep-warm: periyodik hafif istek
                await keep_session_warm()

            else:
                update_status("offline", "Session gecersiz veya suresi dolmus")
                was_online = False
                if not offline_notified:
                    logger.warning("Eyotek session OFFLINE!")
                    await notify_admin(
                        "[FERMAT] Eyotek session dustu!\n\n"
                        "Lutfen Chrome'da fermat.eyotek.com adresine giris yapin.\n"
                        "Giris yaptiktan sonra 'eyotek tamam' yazin."
                    )
                    offline_notified = True

        except Exception as e:
            logger.error(f"Session check hatasi: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


def get_eyotek_status() -> dict:
    """Diger moduller icin: Eyotek erisimi var mi?"""
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except Exception:
            pass
    return {"eyotek_session": "unknown", "last_check": None}


def is_eyotek_available() -> bool:
    """Eyotek session aktif mi?"""
    status = get_eyotek_status()
    return status.get("eyotek_session") == "online"


if __name__ == "__main__":
    asyncio.run(session_keeper_loop())
