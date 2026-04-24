"""
Eyotek Mobile Tunnel (Faz 3) — Oturum 25.4
==========================================
Mobilden remote Eyotek login + CAPTCHA cozum.

Akis:
1. Xvfb sanal ekran baslat (:99)
2. Chromium headed modda aç + DevTools port 9222 (Eyotek login sayfasi yuklü)
3. x11vnc ile ekran yayini (:99 -> VNC port 5900)
4. websockify/novnc HTTP portu (6080) uzerinden tarayici icin yayin
5. cloudflared tunnel 6080 -> geçici trycloudflare.com URL
6. URL'yi dondur -> WA'da Neo'ya gonderilir
7. Neo URL'e tarayicidan girer -> VPS Chrome goruntusunu gorur
8. Cloudflare + sifre + login -> Eyotek authenticated
9. Playwright 9222 CDP uzerinden session cookie'lerini alir
10. .eyotek_session.json kaydedilir
11. Tunnel + Xvfb + Chromium kapatilir

Bu script whatsapp_bridge'ten cagrilir:
    from eyotek_mobile_tunnel import start_tunnel_session
    tunnel_url = await start_tunnel_session(timeout_sec=900)

Gerekli paketler (VPS):
    apt install -y chromium-browser xvfb x11vnc novnc websockify fluxbox
    cloudflared (dpkg -i cloudflared-linux-amd64.deb)
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from dotenv import load_dotenv

load_dotenv(override=True)

BASE_URL = os.getenv("EYOTEK_URL", "https://fermat.eyotek.com/v1")
SESSION_FILE = Path(__file__).resolve().parent / ".eyotek_session.json"
DISPLAY_NUM = int(os.getenv("EYOTEK_XVFB_DISPLAY", "99"))
VNC_PORT = int(os.getenv("EYOTEK_VNC_PORT", "5900"))
NOVNC_PORT = int(os.getenv("EYOTEK_NOVNC_PORT", "6080"))
CDP_PORT = int(os.getenv("EYOTEK_CDP_PORT", "9333"))
SCREEN_RES = os.getenv("EYOTEK_SCREEN_RES", "1280x800x24")

# Binary yollari
XVFB_BIN = shutil.which("Xvfb") or "/usr/bin/Xvfb"
X11VNC_BIN = shutil.which("x11vnc") or "/usr/bin/x11vnc"
WEBSOCKIFY_BIN = shutil.which("websockify") or "/usr/bin/websockify"
CHROMIUM_BIN = (
    shutil.which("chromium")
    or shutil.which("chromium-browser")
    or "/usr/bin/chromium"
)
CLOUDFLARED_BIN = shutil.which("cloudflared") or "/usr/local/bin/cloudflared"
NOVNC_WEB_DIR = "/usr/share/novnc"


class TunnelSession:
    """Xvfb + Chromium + VNC + websockify + cloudflared yonetir."""

    def __init__(self):
        self.procs: list[subprocess.Popen] = []
        self.tunnel_url: Optional[str] = None
        self.display = f":{DISPLAY_NUM}"

    def _start_proc(
        self, cmd: list, env: Optional[dict] = None, stdout=subprocess.DEVNULL
    ) -> subprocess.Popen:
        """Proces baslat, self.procs'a ekle.
        stdout=PIPE verildiginde stderr de oraya merge edilir + text mode line-buffered
        (cloudflared output anlik okunabilmesi icin)."""
        full_env = {**os.environ, **(env or {})}
        is_pipe = stdout == subprocess.PIPE
        p = subprocess.Popen(
            cmd,
            env=full_env,
            stdout=stdout,
            stderr=subprocess.STDOUT if is_pipe else subprocess.DEVNULL,
            start_new_session=True,
            bufsize=1 if is_pipe else -1,
            text=True if is_pipe else False,
            encoding="utf-8" if is_pipe else None,
            errors="replace" if is_pipe else None,
        )
        self.procs.append(p)
        return p

    async def start(self, timeout_sec: int = 60) -> Optional[str]:
        """Tum stack'i baslat, cloudflared tunnel URL'sini dondur."""
        try:
            # 1. Xvfb
            logger.info(f"[TUNNEL] Xvfb baslatiliyor: {self.display}")
            self._start_proc([XVFB_BIN, self.display, "-screen", "0", SCREEN_RES, "-ac"])
            await asyncio.sleep(1.5)

            # 2. Fluxbox (minimal WM — Chrome icin gerekli degil ama iyi davranış)
            fbb = shutil.which("fluxbox")
            if fbb:
                self._start_proc([fbb], env={"DISPLAY": self.display})
                await asyncio.sleep(0.8)

            # 3. Chromium (headed, CDP port acik, Eyotek acilir)
            # systemd sandbox (PrivateTmp/RestrictNamespaces) Chromium setuid sandbox'i
            # engelliyor → --no-sandbox + --disable-dev-shm-usage zorunlu.
            logger.info(f"[TUNNEL] Chromium baslatiliyor, CDP={CDP_PORT}")
            user_data = f"/tmp/eyotek_chrome_{int(time.time())}"
            self._start_proc(
                [
                    CHROMIUM_BIN,
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    f"--user-data-dir={user_data}",
                    f"--remote-debugging-port={CDP_PORT}",
                    "--remote-debugging-address=127.0.0.1",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-translate",
                    "--disable-background-networking",
                    "--window-size=1280,800",
                    "--window-position=0,0",
                    "--start-maximized",
                    BASE_URL,
                ],
                env={"DISPLAY": self.display},
                stdout=subprocess.PIPE,  # Debug icin hata capture
            )
            await asyncio.sleep(5.0)  # Chromium + Eyotek yuklu bekle (longer for headed)

            # 4. x11vnc (ekran -> VNC port)
            logger.info(f"[TUNNEL] x11vnc baslatiliyor: {self.display} -> {VNC_PORT}")
            self._start_proc(
                [
                    X11VNC_BIN,
                    "-display", self.display,
                    "-rfbport", str(VNC_PORT),
                    "-nopw", "-forever", "-shared", "-quiet",
                ]
            )
            await asyncio.sleep(1.5)

            # 5. websockify (VNC -> noVNC HTTP port)
            logger.info(f"[TUNNEL] websockify: {NOVNC_PORT} -> localhost:{VNC_PORT}")
            self._start_proc(
                [
                    WEBSOCKIFY_BIN,
                    "--web", NOVNC_WEB_DIR,
                    str(NOVNC_PORT),
                    f"localhost:{VNC_PORT}",
                ]
            )
            await asyncio.sleep(2.0)

            # 6. cloudflared tunnel → geçici URL (native asyncio subprocess, stdout+stderr merge)
            # Oturum 25.5 fix: Popen + run_in_executor readline buffering'e takiliyordu.
            # asyncio.create_subprocess_exec + await stdout.readline() native cozum.
            logger.info(f"[TUNNEL] cloudflared tunnel --url http://localhost:{NOVNC_PORT}")
            cf_async = await asyncio.create_subprocess_exec(
                CLOUDFLARED_BIN, "tunnel",
                "--url", f"http://localhost:{NOVNC_PORT}",
                "--no-autoupdate",
                "--loglevel", "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            # Popen wrapper ekle (stop icin)
            self.cloudflared_proc = cf_async
            url = await self._wait_for_tunnel_url_async(cf_async, timeout_sec=45)
            if not url:
                raise RuntimeError("cloudflared URL alinamadi (30s timeout)")

            # noVNC iframe URL (auto-connect)
            self.tunnel_url = f"{url}/vnc.html?autoconnect=true&resize=scale"
            logger.info(f"[TUNNEL] URL: {self.tunnel_url}")
            return self.tunnel_url

        except Exception as e:
            logger.error(f"[TUNNEL] Start fail: {e}")
            self.stop()
            return None

    async def _wait_for_tunnel_url_async(
        self, proc, timeout_sec: int = 45
    ) -> Optional[str]:
        """asyncio.subprocess stdout'ta trycloudflare URL'sini yakala.

        Oturum 25.5: subprocess.Popen + run_in_executor readline buffering
        icine takiliyordu. Native asyncio StreamReader ile satir bazli oku."""
        pattern = re.compile(r"(https://[a-z0-9-]+\.trycloudflare\.com)")
        try:
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                try:
                    line = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=2.0,
                    )
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break  # EOF
                txt = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
                m = pattern.search(txt)
                if m:
                    return m.group(1)
        except Exception as e:
            logger.warning(f"[TUNNEL] URL parse hatasi: {e}")
        return None

    async def wait_for_login_and_capture(
        self, poll_interval: int = 4, timeout_sec: int = 900
    ) -> Optional[list]:
        """Neo login'ı bekle, başarıda cookie'leri Playwright ile cek."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[TUNNEL] Playwright yok")
            return None

        deadline = time.time() + timeout_sec
        async with async_playwright() as p:
            while time.time() < deadline:
                try:
                    browser = await p.chromium.connect_over_cdp(
                        f"http://localhost:{CDP_PORT}"
                    )
                    ctx = browser.contexts[0] if browser.contexts else None
                    if not ctx or not ctx.pages:
                        await browser.close()
                        await asyncio.sleep(poll_interval)
                        continue
                    page = ctx.pages[0]
                    cur = page.url or ""
                    if (
                        "fermat.eyotek.com" in cur
                        and "/Pages/" in cur
                        and "login" not in cur.lower()
                        and "default.aspx" not in cur.lower()
                    ):
                        # Login basarili
                        all_cookies = await ctx.cookies()
                        eyotek_cookies = [
                            c for c in all_cookies
                            if "eyotek" in c.get("domain", "").lower()
                        ]
                        await browser.close()
                        if eyotek_cookies:
                            SESSION_FILE.write_text(
                                json.dumps(
                                    eyotek_cookies,
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                                encoding="utf-8",
                            )
                            logger.success(
                                f"[TUNNEL] Login yakalandi: {len(eyotek_cookies)} cookie -> {SESSION_FILE.name}"
                            )
                            return eyotek_cookies
                    await browser.close()
                except Exception as e:
                    logger.debug(f"[TUNNEL] Poll fail (devam): {e}")
                await asyncio.sleep(poll_interval)
        logger.warning("[TUNNEL] Login bekleme timeout")
        return None

    def stop(self):
        """Tum procesi temizle."""
        # Async cloudflared subprocess (Oturum 25.5)
        cf = getattr(self, "cloudflared_proc", None)
        if cf is not None:
            try:
                if cf.returncode is None:
                    cf.terminate()
            except Exception:
                pass
            self.cloudflared_proc = None
        # Klasik Popen subprocess'ler
        for p in self.procs:
            try:
                if p.poll() is None:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                pass
        self.procs.clear()
        logger.info("[TUNNEL] Tum process'ler kapatildi")


# ── Ust seviye tek-seferlik yardimci ──────────────────────────────────────

async def start_tunnel_session(
    wait_login: bool = True, login_timeout_sec: int = 900
) -> dict:
    """
    Tum akisi yonet: tunnel baslat + URL dondur + login bekle + cookie kaydet.

    Returns:
        {
            "success": bool,
            "tunnel_url": str | None,
            "cookies_count": int,
            "message": str,
        }
    """
    session = TunnelSession()
    url = await session.start(timeout_sec=45)
    if not url:
        session.stop()
        return {
            "success": False,
            "tunnel_url": None,
            "cookies_count": 0,
            "message": "Tunnel baslatilamadi (cloudflared/Xvfb fail)",
        }

    if not wait_login:
        # wait_login=False tipik olarak sadece smoke test icindir. Session'i GC'ye
        # birakma — process'ler orphan kalir. Caller stop cagirmali ya da bu return
        # yolu alinmamali. Guvenlik icin hemen stop.
        session.stop()
        return {
            "success": True,
            "tunnel_url": url,
            "cookies_count": 0,
            "message": "Tunnel URL hazir (login beklenmiyor, session stop)",
        }

    cookies = await session.wait_for_login_and_capture(timeout_sec=login_timeout_sec)
    session.stop()
    if cookies:
        return {
            "success": True,
            "tunnel_url": url,
            "cookies_count": len(cookies),
            "message": f"Login basarili, {len(cookies)} cookie alindi",
        }
    return {
        "success": False,
        "tunnel_url": url,
        "cookies_count": 0,
        "message": "Login tamamlanmadi (timeout 15dk)",
    }


if __name__ == "__main__":
    async def _main():
        print("Tunnel baslatiliyor...")
        r = await start_tunnel_session(wait_login=False)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if r.get("success"):
            print("\nURL'ye tarayicidan gir, CAPTCHA cöz, login ol. Sonra tekrar calistir.")

    asyncio.run(_main())
