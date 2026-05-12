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

# 25.43-OPS-FIX: Explicit parent .env path (cwd-traversal yetersiz)
_PARENT_ENV = Path(__file__).resolve().parent.parent / ".env"
if _PARENT_ENV.exists():
    load_dotenv(_PARENT_ENV, override=True)
else:
    load_dotenv(override=True)

# Config
# Oturum 25.6: Absolute path — tüm modüller tek dosyaya baksın
SESSION_FILE = Path(os.getenv("SESSION_FILE") or (Path(__file__).resolve().parent.parent / ".eyotek_session.json"))
STATUS_FILE = Path(".eyotek_status.json")
BASE_URL = "https://fermat.eyotek.com/v1"
CHECK_INTERVAL = 180  # 3 dakika — ASP.NET session ~20-30dk timeout, 3dk yeterli
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "905xxxxxxxxx")
WP_API_URL = os.getenv("WP_API_URL", "http://localhost:8001")
# CDP port — VPS'te 9333, laptop'ta 9222. eyotek_wrapper.py ile ayni env var.
CDP_PORT = int(os.getenv("CDP_PORT", "9222"))
CDP_URL = f"http://localhost:{CDP_PORT}"


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
    """Session gecerli mi? Cookie-aware — yeni tab acip cookie inject ile test eder.

    25.27 fix: Eski versiyonda 9333'teki STUCK Turnstile tab'a bakiyordu, "OFFLINE"
    diyordu — halbuki cookie injection ile gercek API calismaktadir. Artik:
      1. CDP'ye bagli ol
      2. Cookie file'dan inject et
      3. Yeni tab ac, /Pages/Staff/home'a git
      4. Login'e dusulmedi VE protected page render ettiyse: ONLINE
    """
    cookies = load_session()
    if not cookies:
        return False

    # Yontem 1: CDP + cookie inject + yeni tab test
    pw = None
    page = None
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
            ctx = browser.contexts[0]
            # Cookie'leri ctx'e merge et (eyotek_reader gibi)
            valid_cookies = []
            for c in cookies:
                if not c.get("name") or c.get("value") is None:
                    continue
                valid_cookies.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain") or "fermat.eyotek.com",
                    "path": c.get("path") or "/",
                    **{k: c[k] for k in ("expires", "httpOnly", "secure", "sameSite")
                       if k in c and c[k] is not None},
                })
            if valid_cookies:
                try:
                    await ctx.add_cookies(valid_cookies)
                except Exception:
                    pass
            # Yeni tab + protected page navigate
            page = await ctx.new_page()
            await page.goto(f"{BASE_URL}/Pages/Staff/home",
                            timeout=10000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            url = page.url.lower()
            # Login'e redirect olduysa: false
            if "login" in url or url.rstrip("/").endswith("/v1"):
                return False
            # Protected sayfa yuklendi mi?
            has_login = await page.evaluate(
                "() => !!document.querySelector('input[type=password]') || !!document.getElementById('btnLogin')")
            return not has_login
        finally:
            try:
                if page:
                    await page.close()
            except Exception:
                pass
    except Exception:
        pass
    finally:
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass

    # Yontem 2: HTTP GET fallback (CDP erisilemezse)
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
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]

        # Eyotek tab'ini bul
        eyotek_page = None
        for page in ctx.pages:
            if "eyotek" in page.url.lower():
                eyotek_page = page
                break

        if not eyotek_page:
            # 25.44 (Neo bug 12 May 18:41 — bot self-analysis):
            # Eski: log + return False (otomatik recovery yok)
            # Yeni: yeni tab aç, Eyotek'e git, cookie inject — otomatik recovery
            logger.warning("CDP: Eyotek tab kayıp — otomatik yeniden açılıyor...")
            try:
                eyotek_page = await ctx.new_page()
                # Önce session dosyasından cookie'leri inject et
                try:
                    from pathlib import Path
                    import json as _json
                    sess_file = Path(__file__).parent / "session.json"
                    if sess_file.exists():
                        cookies = _json.loads(sess_file.read_text(encoding="utf-8"))
                        if isinstance(cookies, list):
                            await ctx.add_cookies(cookies)
                            logger.info(f"CDP: {len(cookies)} cookie inject edildi (recovery)")
                except Exception as _ce:
                    logger.debug(f"CDP recovery cookie inject skip: {_ce}")
                # Eyotek'e git
                await eyotek_page.goto("https://fermat.eyotek.com/v1/Pages/Staff/home",
                                        timeout=15000, wait_until="domcontentloaded")
                await eyotek_page.wait_for_timeout(2000)
                logger.info("CDP: Eyotek tab yeniden açıldı")
            except Exception as _re:
                logger.warning(f"CDP: Tab recovery fail: {_re}")
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


async def _add_web_notification(category: str, title: str, body: str = "",
                                severity: str = "warning") -> bool:
    """notifications tablosuna kaydet — web dashboard okuyacak."""
    try:
        from db_pool import db_execute
        await db_execute(
            """INSERT INTO notifications (severity, category, title, body, created_at)
               VALUES ($1, $2, $3, $4, NOW())""",
            severity, category, title[:200], body[:2000],
        )
        return True
    except Exception as e:
        logger.debug(f"web_notification yazma hata: {e}")
        return False


async def _wp_was_sent_recently(category: str, hours: int = 12) -> bool:
    """Bu kategoriden son N saatte WP gonderilmis mi? Spam onleme."""
    try:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            """SELECT created_at FROM notifications
               WHERE category = $1 AND metadata->>'wp_sent' = 'true'
               AND created_at > NOW() - ($2 || ' hours')::interval
               ORDER BY created_at DESC LIMIT 1""",
            category, str(hours),
        )
        return bool(row)
    except Exception:
        return False


async def _mark_wp_sent(category: str, title: str) -> None:
    """En son notifications kaydina wp_sent=true ekle."""
    try:
        from db_pool import db_execute
        await db_execute(
            """UPDATE notifications
               SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"wp_sent": true}'::jsonb
               WHERE id = (
                   SELECT id FROM notifications
                   WHERE category = $1 AND title = $2
                   ORDER BY created_at DESC LIMIT 1
               )""",
            category, title[:200],
        )
    except Exception:
        pass


async def notify_admin(message: str, category: str = "eyotek_session",
                       severity: str = "warning",
                       wp_rate_limit_hours: int = 12):
    """Bildirim gonder — once web_notifications, sonra (rate-limited) WP.

    25.26 spam-fix: session-drop tarzi bildirimler her 3dk'da WP'ye gitmiyor;
    web dashboard'a yazilir, WP sadece 12 saatte 1 atilir (severity=critical
    veya rate_limit_hours=0 ise her seferinde).
    """
    # Adim 1: notifications tablosuna her zaman yaz
    title = message.split("\n")[0][:200]
    body = message[:2000]
    await _add_web_notification(category=category, title=title, body=body,
                                severity=severity)

    # Adim 2: WP gonderim kontrolu
    # Tamamen sustur flag'i:
    if os.getenv("EYOTEK_WP_NOTIFY", "true").lower() in ("false", "0", "no"):
        logger.debug(f"[NOTIFY] WP susturuldu (EYOTEK_WP_NOTIFY=false): {title[:60]}")
        return

    # Critical her zaman WP'ye gider, baska severity'ler rate-limit
    if severity != "critical" and wp_rate_limit_hours > 0:
        if await _wp_was_sent_recently(category, hours=wp_rate_limit_hours):
            logger.info(f"[NOTIFY] WP rate-limit ({category}, {wp_rate_limit_hours}h): "
                        f"sadece web'e yazildi: {title[:60]}")
            return

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
                await _mark_wp_sent(category, title)
            else:
                logger.warning(f"WP bildirim hata {r.status_code}: {r.text[:100]}")
    except Exception as e:
        logger.warning(f"WP bildirim gonderilemedi: {e}")


async def session_keeper_loop():
    """
    Ana dongu: her 3 dakikada session kontrol et.
    Online → keep-warm istegi at (ASP.NET timeout'u ertele).
    Offline → admin'e bildir, cookie yenilemesi icin BASLAT_EYOTEK.bat iste.

    Oturum 25.4 revize:
    - VPS HTTP-only modunda calisir (Chrome/CDP gerekmez)
    - .eyotek_session.json varsa keeper aktif (laptop'tan scp edilmis cookie'ler)
    - Yoksa dongu her 3dk'da file kontrol eder, olustugunda aktive olur

    Flag'ler (.env):
      EYOTEK_SESSION_ENABLED=true   → keeper aktif (VPS dahil, cookie file olmali)
      EYOTEK_SESSION_ENABLED=false  → tamamen kapali
      SESSION_KEEPER_NOTIFY=false   → keeper çalışır ama WP bildirim göndermez
    """
    import os
    # Tamamen kapali mod
    if os.getenv("EYOTEK_SESSION_ENABLED", "true").lower() in ("false", "0", "no"):
        logger.info("Session Keeper DEVRE DIŞI (EYOTEK_SESSION_ENABLED=false)")
        return

    # VPS modu tespit: HEADLESS=true (CDP_PORT env var ayri yonetilir)
    _vps_mode = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")

    notify_enabled = os.getenv("SESSION_KEEPER_NOTIFY", "true").lower() not in ("false", "0", "no")
    logger.info(f"Session Keeper baslatildi (notify={notify_enabled}, vps_mode={_vps_mode})")
    was_online = False
    offline_notified = False
    last_cookie_mtime = 0.0
    waiting_for_cookies_notified = False

    while True:
        try:
            # VPS modunda cookie dosyasi yoksa beklenti modu
            if _vps_mode and not SESSION_FILE.exists():
                update_status("waiting_for_cookies", "Cookie dosyasi yok — laptop'tan login bekleniyor")
                if not waiting_for_cookies_notified and notify_enabled:
                    logger.info("Cookie dosyasi yok, laptop'tan login bekleniyor (BASLAT_EYOTEK.bat)")
                    waiting_for_cookies_notified = True
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            # Cookie dosyasi yenilendi mi? (laptop'tan scp gelmiş)
            if SESSION_FILE.exists():
                mtime = SESSION_FILE.stat().st_mtime
                if mtime > last_cookie_mtime + 1:
                    logger.info(f"Cookie dosyasi yenilendi (mtime={mtime}) — session dogrulama")
                    last_cookie_mtime = mtime
                    waiting_for_cookies_notified = False
                    offline_notified = False  # yeni cookie ile tekrar dene

            is_valid = await check_session()

            if is_valid:
                update_status("online", "Session aktif")
                if not was_online:
                    logger.success("Eyotek session ONLINE")
                    # Online geri donus → web'e info, WP suskun (gurultuyu azalt)
                    if offline_notified and notify_enabled:
                        await notify_admin(
                            "✅ [FERMAT] Eyotek oturumu aktif, sistem online.",
                            category="eyotek_session_online",
                            severity="info",
                            wp_rate_limit_hours=24,  # gunde 1 kez WP
                        )
                    offline_notified = False
                was_online = True

                # Keep-warm: periyodik hafif istek (ASP.NET timeout uzat)
                await keep_session_warm()

            else:
                update_status("offline", "Session gecersiz veya suresi dolmus")
                was_online = False
                # Web'e HER 3dk yazariz (gercek durum), WP'ye 12 saatte 1
                if not offline_notified:
                    logger.warning("Eyotek session OFFLINE!")
                    # offline_notified flag bridge restart'larda resetlenir, biliyoruz —
                    # bu yuzden notify_admin icindeki rate-limit (DB-based) gercek koruma
                    if notify_enabled:
                        if _vps_mode:
                            await notify_admin(
                                "⚠️ [FERMAT] Eyotek oturumu düştü.\n\n"
                                "Mobil remote-login sistemi henüz kurulmadı "
                                "(Faz 3: cloudflared tunnel + headed Chromium).\n"
                                "Bu oturum kurulana kadar Eyotek yazma pasif, "
                                "sistem DB cache'ten okuma yapar.",
                                category="eyotek_session_offline",
                                severity="warning",
                                wp_rate_limit_hours=12,  # 12 saatte 1 WP
                            )
                        else:
                            await notify_admin(
                                "⚠️ [FERMAT] Eyotek session dustu!\n\n"
                                "Chrome'da fermat.eyotek.com adresine giris yapin.\n"
                                "Giris yaptiktan sonra 'eyotek tamam' yazin.",
                                category="eyotek_session_offline",
                                severity="warning",
                                wp_rate_limit_hours=12,
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
