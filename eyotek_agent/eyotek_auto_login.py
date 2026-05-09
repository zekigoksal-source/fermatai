"""
Eyotek Auto-Login (VPS) — Oturum 25.4 Faz 2
=============================================
Neo WhatsApp'tan "eyotek baglan" yazinca cagrilir.

Mimari (Neo brief, 24 Nisan 2026):
1. Playwright headless Chromium baslat
2. Eyotek login sayfasina git
3. Credentials (env'den) otomatik doldur
4. Submit et
5. Sonucu tespit:
   - BASARILI (URL /Pages/'a gecti) -> cookie kaydet + WA "Eyotek baglandi"
   - CAPTCHA tespit edildi -> fallback: Neo'ya "Laptop'tan BASLAT_EYOTEK.bat calistir"
   - HATA -> WA hata mesaji

Not: Cloudflare Tunnel ile remote CAPTCHA cozum ileri faz isi (cloudflared binary
kurulu olmadigi icin). Su an CAPTCHA cikarsa laptop fallback.

Saat kurallari:
- SESSIZ_SAATLER (22:00 - 08:00): bildirim gonderme, sadece log
- GUNDUZ (08:00 - 22:00): WA bildirim aktif
"""
from __future__ import annotations
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from dotenv import load_dotenv

# 25.43-OPS-FIX (10 May): Default load_dotenv() cwd'den çıkmaz — parent .env
# bulamaz. eyotek_agent cwd'sinden çağırıldığında EYOTEK_USER='' okunuyordu
# → auto-login fail. Explicit path ile parent (/opt/fermatai/) .env yüklenir.
_PARENT_ENV = Path(__file__).resolve().parent.parent / ".env"
if _PARENT_ENV.exists():
    load_dotenv(_PARENT_ENV, override=True)
else:
    # Fallback: default davranis (cwd traversal)
    load_dotenv(override=True)

BASE_URL = os.getenv("EYOTEK_URL", "https://fermat.eyotek.com/v1")
EYOTEK_USER = os.getenv("EYOTEK_USER", "")
EYOTEK_PASS = os.getenv("EYOTEK_PASS", "")
# Oturum 25.6: Proje root'unda tek dosya (bridge + keeper + auto_login hepsi ayni yere baksin)
SESSION_FILE = Path(__file__).resolve().parent.parent / ".eyotek_session.json"
QUIET_START = int(os.getenv("EYOTEK_QUIET_START", "23"))  # 23:00 (Oturum 25.7: 22 -> 23)
QUIET_END = int(os.getenv("EYOTEK_QUIET_END", "7"))        # 07:00 (Oturum 25.7: 8 -> 7)
# Oturum 25.7: Otomatik login cooldown — son denemeden min N dakika gecmeden tekrar yok
LOGIN_COOLDOWN_MIN = int(os.getenv("EYOTEK_LOGIN_COOLDOWN_MIN", "30"))
LAST_LOGIN_FILE = Path(__file__).resolve().parent.parent / ".eyotek_last_login.json"
MOBILE_FAZ3_HINT = (
    "\n\n_Eyotek her login'de Cloudflare CAPTCHA istiyor — VPS otomatik çözemez._\n"
    "_Mobil remote-login sistemi (cloudflared tunnel + headed Chromium) kurulumu_\n"
    "_sonraki oturumda yapılacak. O zamana kadar Eyotek yazma işlemleri pasif,_\n"
    "_sistem DB cache ile okuma yapar (son 18 gün veri mevcut)._"
)


def is_quiet_hour(now: Optional[datetime] = None) -> bool:
    """Gece saatinde WA bildirim gonderme (Neo trafikteyse rahatsiz etme)."""
    now = now or datetime.now()
    h = now.hour
    if QUIET_START > QUIET_END:
        # 23-07 wrap (gece)
        return h >= QUIET_START or h < QUIET_END
    return QUIET_START <= h < QUIET_END


def _read_last_login() -> Optional[datetime]:
    """Son login denemesi timestamp'ini oku (file based, restart-safe)."""
    if not LAST_LOGIN_FILE.exists():
        return None
    try:
        data = json.loads(LAST_LOGIN_FILE.read_text(encoding="utf-8"))
        ts = data.get("last_attempt")
        if ts:
            return datetime.fromisoformat(ts)
    except Exception:
        pass
    return None


def _write_last_login() -> None:
    """Son login denemesi timestamp'ini yaz."""
    try:
        LAST_LOGIN_FILE.write_text(
            json.dumps({"last_attempt": datetime.now().isoformat()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"[EYOTEK] Last-login write fail: {e}")


def _cooldown_active() -> tuple[bool, int]:
    """Son login'den bu yana LOGIN_COOLDOWN_MIN dakika gecti mi?
    Returns: (cooldown_active, kalan_dakika)"""
    last = _read_last_login()
    if not last:
        return False, 0
    elapsed_min = (datetime.now() - last).total_seconds() / 60
    if elapsed_min < LOGIN_COOLDOWN_MIN:
        return True, int(LOGIN_COOLDOWN_MIN - elapsed_min)
    return False, 0


async def _notify_admin(message: str, quiet_bypass: bool = False) -> None:
    """WA admin'e bildirim. quiet_bypass=True -> sessiz saati yoksay (kritik)."""
    if not quiet_bypass and is_quiet_hour():
        logger.info(f"[EYOTEK] Sessiz saat — WA atlandi: {message[:60]}")
        return
    try:
        from session_keeper import notify_admin
        await notify_admin(message)
    except Exception as e:
        logger.warning(f"[EYOTEK] WA bildirim fail: {e}")


async def _detect_captcha(page) -> bool:
    """Sayfada Cloudflare Turnstile / reCAPTCHA tespit et."""
    try:
        return await page.evaluate("""
            () => {
                const t = document.querySelector('[name="cf-turnstile-response"], .cf-turnstile, iframe[src*="turnstile"], iframe[src*="cloudflare"]');
                const r = document.querySelector('[id*="recaptcha"], iframe[src*="recaptcha"], .g-recaptcha');
                return !!(t || r);
            }
        """)
    except Exception:
        return False


async def _is_authenticated(page) -> bool:
    """URL /Pages/ altinda ve login form yok mu?"""
    try:
        url = page.url
        if "login" in url.lower() or "default.aspx" in url.lower():
            return False
        if "/Pages/" not in url:
            return False
        has_login_form = await page.evaluate(
            "() => !!document.getElementById('btnLogin') || !!document.querySelector('input[type=password]')"
        )
        return not has_login_form
    except Exception:
        return False


async def _extract_turnstile_sitekey(page) -> Optional[str]:
    """Sayfadaki Turnstile widget'tan data-sitekey'i cek."""
    try:
        key = await page.evaluate("""
            () => {
                const el = document.querySelector('.cf-turnstile, [data-sitekey]');
                if (el && el.getAttribute) return el.getAttribute('data-sitekey');
                // iframe src'den de parse et
                const ifr = document.querySelector('iframe[src*="turnstile"]');
                if (ifr) {
                    const m = ifr.src.match(/\\?k=([A-Za-z0-9_]+)/) || ifr.src.match(/sitekey=([A-Za-z0-9_]+)/);
                    if (m) return m[1];
                }
                return null;
            }
        """)
        return key
    except Exception:
        return None


async def _inject_turnstile_token(page, token: str) -> bool:
    """Token'i sayfaya inject et + Turnstile callback'ini tetikle."""
    try:
        await page.evaluate(f"""
            (token) => {{
                // 1. Hidden input guncelle
                const inputs = document.querySelectorAll(
                    '[name="cf-turnstile-response"], [name*="turnstile"]'
                );
                inputs.forEach(el => {{
                    el.value = token;
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                }});
                // 2. Global callback varsa cagir
                if (window.turnstile && window.turnstile.getResponse) {{
                    try {{ window._cfCallback && window._cfCallback(token); }} catch(e) {{}}
                }}
                return true;
            }}
        """, token)
        return True
    except Exception as e:
        logger.warning(f"[CAPSOLVER] Token inject fail: {e}")
        return False


async def try_auto_login(timeout_ms: int = 20000, trigger_source: str = "manual") -> dict:
    """
    Headless Chromium ile Eyotek otomatik login dene.
    CAPTCHA varsa CapSolver ile cöz (Oturum 25.6).

    Returns:
        {
            "success": bool,
            "reason": "ok" | "captcha" | "bad_credentials" | "timeout" | "error",
            "message": str,
            "cookies_count": int,
        }
    """
    if not (EYOTEK_USER and EYOTEK_PASS):
        return {
            "success": False, "reason": "error",
            "message": "EYOTEK_USER/EYOTEK_PASS .env'de yok", "cookies_count": 0,
        }

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False, "reason": "error",
            "message": "Playwright kurulu degil", "cookies_count": 0,
        }

    async with async_playwright() as p:
        try:
            # Oturum 25.4 fix: systemd hardening (PrivateTmp + RestrictNamespaces)
            # Chromium sandbox'ini engelliyor. --no-sandbox + --disable-dev-shm-usage gerekli.
            # Interactive user'da calisir ama service'te fail ediyordu.
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                ],
            )
        except Exception as e:
            return {
                "success": False, "reason": "error",
                "message": f"Chromium baslatilamadi: {str(e)[:300]}", "cookies_count": 0,
            }

        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="tr-TR",
        )
        page = await ctx.new_page()

        try:
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            await asyncio.sleep(2)

            # Zaten authenticated mi?
            if await _is_authenticated(page):
                cookies = await ctx.cookies()
                eyotek_cookies = [c for c in cookies if "eyotek" in c.get("domain", "").lower()]
                _save_cookies(eyotek_cookies)
                await browser.close()
                return {
                    "success": True, "reason": "already_authenticated",
                    "message": f"Zaten giris yapili ({len(eyotek_cookies)} cookie)",
                    "cookies_count": len(eyotek_cookies),
                }

            # CAPTCHA var mi? (Cloudflare Turnstile vb.) — Oturum 25.6 CapSolver entegrasyonu
            if await _detect_captcha(page):
                logger.info("[EYOTEK] CAPTCHA tespit edildi, CapSolver deneniyor...")
                sitekey = await _extract_turnstile_sitekey(page)
                if not sitekey:
                    await browser.close()
                    return {
                        "success": False, "reason": "captcha",
                        "message": "CAPTCHA tespit edildi ama Turnstile sitekey bulunamadi",
                        "cookies_count": 0,
                    }
                if not os.getenv("CAPSOLVER_API_KEY"):
                    await browser.close()
                    return {
                        "success": False, "reason": "captcha",
                        "message": "CAPTCHA var, CAPSOLVER_API_KEY .env'de yok (Neo eklemeli)",
                        "cookies_count": 0,
                    }
                try:
                    from capsolver_helper import solve_turnstile
                    page_url = page.url or BASE_URL
                    token = await solve_turnstile(
                        page_url, sitekey, timeout_sec=90,
                        trigger_source=trigger_source,
                    )
                except Exception as _cs_e:
                    logger.error(f"[CAPSOLVER] Cozum hatasi: {_cs_e}")
                    token = None

                if not token:
                    await browser.close()
                    return {
                        "success": False, "reason": "captcha",
                        "message": "CapSolver token uretemedi (90s timeout veya API hatasi)",
                        "cookies_count": 0,
                    }

                injected = await _inject_turnstile_token(page, token)
                if not injected:
                    await browser.close()
                    return {
                        "success": False, "reason": "error",
                        "message": "CapSolver token alindi ama sayfaya inject edilemedi",
                        "cookies_count": 0,
                    }
                logger.success("[EYOTEK] CAPTCHA otomatik cozuldu (CapSolver), login akisi devam")
                await asyncio.sleep(1.5)  # Callback'in calismasi icin

            # Kullanici adi + sifre doldur
            # Eyotek login: #txtUserName + #txtPassword + #btnLogin
            user_filled = False
            pass_filled = False
            try:
                await page.fill("#txtUserName", EYOTEK_USER, timeout=5000)
                user_filled = True
            except Exception:
                # Generic fallback
                try:
                    await page.fill("input[type='text'], input[name*='user' i]", EYOTEK_USER, timeout=3000)
                    user_filled = True
                except Exception:
                    pass

            try:
                await page.fill("#txtPassword", EYOTEK_PASS, timeout=5000)
                pass_filled = True
            except Exception:
                try:
                    await page.fill("input[type='password']", EYOTEK_PASS, timeout=3000)
                    pass_filled = True
                except Exception:
                    pass

            if not (user_filled and pass_filled):
                await browser.close()
                return {
                    "success": False, "reason": "error",
                    "message": f"Login formu bulunamadi (user={user_filled}, pass={pass_filled})",
                    "cookies_count": 0,
                }

            # Submit (btnLogin veya form submit)
            try:
                await page.click("#btnLogin", timeout=3000)
            except Exception:
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    pass

            # Login sonucu bekle (URL degisimi veya CAPTCHA cikmasi)
            await asyncio.sleep(4)

            # Submit sonrasi CAPTCHA tekrar kontrol
            if await _detect_captcha(page):
                await browser.close()
                return {
                    "success": False, "reason": "captcha",
                    "message": "Login sonrasi CAPTCHA cikti",
                    "cookies_count": 0,
                }

            # Authenticated mi?
            if await _is_authenticated(page):
                cookies = await ctx.cookies()
                eyotek_cookies = [c for c in cookies if "eyotek" in c.get("domain", "").lower()]
                _save_cookies(eyotek_cookies)
                await browser.close()
                return {
                    "success": True, "reason": "ok",
                    "message": f"Login basarili ({len(eyotek_cookies)} cookie, otomatik)",
                    "cookies_count": len(eyotek_cookies),
                }

            # Kredensiyel yanlisi mi? (login sayfasinda hata mesaji olabilir)
            err_text = await page.evaluate("""
                () => {
                    const e = document.querySelector('.alert-danger, .error, [class*="error"], #lblError');
                    return e ? (e.innerText || e.textContent || '').trim().slice(0, 120) : '';
                }
            """)
            await browser.close()
            if err_text:
                return {
                    "success": False, "reason": "bad_credentials",
                    "message": f"Login hatasi: {err_text}",
                    "cookies_count": 0,
                }
            return {
                "success": False, "reason": "timeout",
                "message": "Login denemesi sonrasi sayfa dogrulanamadi",
                "cookies_count": 0,
            }

        except Exception as e:
            try:
                await browser.close()
            except Exception:
                pass
            return {
                "success": False, "reason": "error",
                "message": f"Exception: {str(e)[:200]}",
                "cookies_count": 0,
            }


def _save_cookies(cookies: list[dict]) -> None:
    SESSION_FILE.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"[EYOTEK] Cookie kaydedildi: {SESSION_FILE.name} ({len(cookies)} cookie)")


async def eyotek_connect_command(force: bool = False) -> str:
    """
    WhatsApp "eyotek baglan" handler.
    Dönen string: Neo'ya WA cevap olarak gonderilecek mesaj.
    """
    logger.info(f"[EYOTEK] connect command, force={force}, quiet_hour={is_quiet_hour()}")

    # Zaten aktif mi?
    if SESSION_FILE.exists() and not force:
        try:
            from session_keeper import check_session
            if await check_session():
                return "✅ *Eyotek zaten bağlı.*\n\n_Yeniden bağlanmak için: 'eyotek baglan zorla'_"
        except Exception:
            pass

    # Oturum 25.7: Cooldown guard — kredi tasarrufu, dongu engeli
    if not force:
        cd_active, cd_remain = _cooldown_active()
        if cd_active:
            return (
                f"⏳ *Eyotek bağlantı denemesi cooldown'da*\n\n"
                f"Son deneme {LOGIN_COOLDOWN_MIN-cd_remain} dk önce yapıldı.\n"
                f"_{cd_remain} dakika sonra tekrar denenebilir veya 'eyotek baglan zorla' ile geç._\n\n"
                f"_(CapSolver kredi tasarrufu için.)_"
            )

    # Quiet hours guard (manuel komuta saygi: force ile gecilebilir)
    if is_quiet_hour() and not force:
        return (
            f"🌙 *Şu an sessiz saat ({QUIET_START}:00-{QUIET_END:02d}:00)*\n\n"
            f"Otomatik login bu saatlerde devre dışı.\n"
            f"Acil ise: 'eyotek baglan zorla' ile manuel tetikle.\n\n"
            f"_(Cron job sabah {QUIET_END:02d}:00'de otomatik bağlanır.)_"
        )

    # Cooldown timestamp guncelle (basari/fail farketmez, deneme yapildi)
    _write_last_login()

    # Otomatik login dene
    result = await try_auto_login()

    if result["success"]:
        msg = (
            f"✅ *Eyotek bağlandı!*\n\n"
            f"_{result['message']}_\n"
            f"_Session süresi: ~20-30dk, keeper heartbeat ile uzar._"
        )
        # Sessiz saatte de basarili bildirim ok (kullanici zaten istemis)
        return msg

    # Basarisiz durumlar
    reason = result["reason"]
    if reason == "captcha":
        # Oturum 25.4 Faz 3: Cloudflare Tunnel ile mobil remote login
        return await _start_mobile_tunnel()
    elif reason == "bad_credentials":
        return (
            "❌ *Eyotek giriş başarısız — kimlik bilgileri hatası*\n\n"
            f"_Detay: {result['message'][:100]}_\n\n"
            ".env dosyasında EYOTEK_USER ve EYOTEK_PASS doğru mu?"
        )
    elif reason == "timeout":
        return (
            "⏱️ *Eyotek yanıt vermedi (timeout)*\n\n"
            "Geçici bağlantı sorunu olabilir. Tekrar dene: 'eyotek baglan'\n"
            + MOBILE_FAZ3_HINT
        )
    else:
        return (
            f"❌ *Eyotek bağlantı hatası*\n\n"
            f"_{result['message'][:200]}_\n"
            + MOBILE_FAZ3_HINT
        )


async def _start_mobile_tunnel() -> str:
    """
    Oturum 25.4 Faz 3: Cloudflare Tunnel ile mobil remote Eyotek login.

    Akis:
    1. eyotek_mobile_tunnel.start_tunnel_session() arka planda calistir
    2. Tunnel URL'sini al, Neo'ya WA mesaj olarak gonderilecek metinde ver
    3. Neo mobilden URL'e girer -> VPS Chrome'u gorur
    4. CAPTCHA + sifre -> login
    5. Cookie VPS'te yakalanir (arka planda wait_for_login calisir)
    6. Sistem devam eder, tunnel kapanir
    """
    try:
        from eyotek_mobile_tunnel import start_tunnel_session
    except ImportError as e:
        return (
            "❌ *Mobil tunnel modülü eksik*\n\n"
            f"_Detay: {e}_\n\n"
            "Sistem yöneticisine bildirin."
        )

    # Oturum 25.5 Faz 3 revize: Tunnel start 30-45sn sürebilir, webhook 20s timeout
    # nedeniyle Meta duplicate retry gönderir. Tum tunnel flow (start + login bekle)
    # arka planda yapilir, Neo'ya iki asamali WA mesaj gonderilir:
    #   1) "Tunnel baslatiyorum, URL 30 sn'de gelecek" (hemen)
    #   2) "URL hazir: xxx" (arka planda)
    #   3) "Eyotek baglandi" (login tamamlandiginda)

    async def _fire_and_forget_tunnel():
        try:
            from eyotek_mobile_tunnel import TunnelSession
            from session_keeper import notify_admin

            session = TunnelSession()
            url = await session.start(timeout_sec=60)
            if not url:
                session.stop()
                await notify_admin(
                    "❌ *Mobil tunnel başlatılamadı*\n\n"
                    "Cloudflared / Xvfb / Chromium kurulumunda sorun olabilir.\n"
                    "`eyotek durum` komutu ile kontrol et."
                )
                return

            # URL hazır — Neo'ya gönder
            await notify_admin(
                "🔐 *Eyotek Mobil Login — Tunnel Hazır*\n\n"
                f"📱 Şu linkten gir (15 dk geçerli):\n"
                f"{url}\n\n"
                "*Adımlar:*\n"
                "1️⃣ Linke tıkla → VPS Chrome ekranını görürsün\n"
                "2️⃣ Cloudflare + kullanıcı + şifre\n"
                "3️⃣ Ana sayfa açılınca tarayıcıyı kapatabilirsin\n\n"
                "_Cookie otomatik yakalanır, sonuç WA'dan gelir._"
            )

            # Login bekle (15 dk)
            cookies = await session.wait_for_login_and_capture(timeout_sec=900)
            session.stop()

            if cookies:
                await notify_admin(
                    f"✅ *Eyotek bağlandı — {len(cookies)} cookie alındı*\n\n"
                    "Session keeper aktif, sistem çalışıyor."
                )
            else:
                await notify_admin(
                    "⏱️ *Eyotek login timeout (15 dk)*\n\n"
                    "Tunnel kapatıldı. Tekrar dene: `eyotek baglan`"
                )
        except Exception as e:
            logger.error(f"[EYOTEK-TUNNEL] Background fail: {e}")
            try:
                from session_keeper import notify_admin
                await notify_admin(
                    f"❌ *Tunnel hatası*\n\n_{str(e)[:200]}_"
                )
            except Exception:
                pass

    # Fire-and-forget: arka planda başlat, hemen döndür
    asyncio.create_task(_fire_and_forget_tunnel())

    return (
        "⏳ *Eyotek Mobil Login başlatılıyor...*\n\n"
        "VPS'te Chromium + Cloudflare Tunnel hazırlanıyor.\n"
        "30 saniye içinde sana link göndereceğim.\n\n"
        "_(Link hazır olunca ayrı bir mesaj gelecek.)_"
    )


async def eyotek_status_command() -> str:
    """WA 'eyotek durum' handler."""
    if not SESSION_FILE.exists():
        return (
            "🔴 *Eyotek oturumu yok*\n\n"
            "Bağlanmak için: `eyotek baglan`"
        )

    age_min = (datetime.now().timestamp() - SESSION_FILE.stat().st_mtime) / 60
    try:
        from session_keeper import check_session
        is_active = await check_session()
    except Exception:
        is_active = None

    status_icon = "🟢" if is_active else "🔴"
    status_text = "AKTİF" if is_active else ("PASİF" if is_active is False else "BİLİNMİYOR")

    return (
        f"{status_icon} *Eyotek durumu: {status_text}*\n\n"
        f"Son cookie güncelleme: ~{age_min:.0f} dakika önce\n"
        f"Session keeper: 3dk periyot HTTP heartbeat\n\n"
        f"_Yenileme: `eyotek baglan`_"
    )


async def eyotek_disconnect_command() -> str:
    """WA 'eyotek kapat' handler."""
    if SESSION_FILE.exists():
        try:
            SESSION_FILE.unlink()
            return "🔴 *Eyotek oturumu kapatıldı* (cookie dosyası silindi)"
        except Exception as e:
            return f"❌ Silinemedi: {e}"
    return "ℹ️ Zaten oturum yoktu."


if __name__ == "__main__":
    # CLI test: python eyotek_auto_login.py
    async def _main():
        print("Auto-login deneniyor...")
        r = await try_auto_login()
        print(json.dumps(r, ensure_ascii=False, indent=2))
    asyncio.run(_main())
