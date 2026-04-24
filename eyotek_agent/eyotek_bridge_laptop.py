"""
Eyotek Bridge (Laptop Side) — Oturum 25.4 (24 Nisan 2026)
==========================================================
Tek kullanisimlik manuel login koprusu.

Amaç:
- Cloudflare Turnstile bariyeri script'ten gecilemez (hesap blocklanma riski)
- Neo manuel login yapar -> cookie'leri VPS'e aktar -> VPS bagimsiz calisir

Akis:
1. Chrome'u CDP portu ile ac (-- remote-debugging-port=9222)
2. Eyotek login sayfasini ac
3. Neo manuel login yapar (Cloudflare + password)
4. Script URL'nin /Pages/'a geçmesini bekler -> login basarili
5. Cookie'leri extract + local kaydet (.eyotek_session.json)
6. SCP ile VPS'e transfer
7. VPS'te reload trigger (opsiyonel: servis restart)

Kullanim:
    python eyotek_bridge_laptop.py

Windows'ta Chrome yolu:
    C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe
Chrome'un ilk kullanimindaki --user-data-dir: C:\\ChromeDebug (FermatAI profili)
"""
from __future__ import annotations
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(override=True)

BASE_URL = os.getenv("EYOTEK_URL", "https://fermat.eyotek.com/v1")
CDP_PORT = int(os.getenv("CDP_PORT", "9222"))
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
VPS_HOST = os.getenv("VPS_HOST", "neo@116.203.117.106")
VPS_SSH_KEY = os.getenv("VPS_SSH_KEY", os.path.expanduser("~/.ssh/id_ed25519_fermatai"))
VPS_TARGET = os.getenv("VPS_EYOTEK_SESSION_PATH", "/opt/fermatai/.eyotek_session.json")
SESSION_FILE = Path(__file__).resolve().parent / ".eyotek_session.json"
USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", r"C:\ChromeDebug")


def _print_banner():
    print("\n" + "=" * 62)
    print("  🔐 FermatAI Eyotek Bridge — Laptop -> VPS Cookie Aktarim")
    print("=" * 62)


def _find_chrome() -> str | None:
    """Windows Chrome binary yolunu bul."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # PATH'ten dene
    import shutil
    return shutil.which("chrome")


async def _open_chrome_with_cdp() -> bool:
    """Chrome'u CDP portu ile ac (zaten aciksa skip)."""
    import socket

    def _port_open() -> bool:
        try:
            with socket.create_connection(("127.0.0.1", CDP_PORT), timeout=1):
                return True
        except Exception:
            return False

    if _port_open():
        print(f"  ✓ Chrome CDP port {CDP_PORT} zaten acik (muhtemelen daha once acildi).")
        return True

    chrome_path = _find_chrome()
    if not chrome_path:
        print(f"  ❌ Chrome bulunamadi. Elle ac: chrome.exe --remote-debugging-port={CDP_PORT}")
        return False

    print(f"  🚀 Chrome baslatiliyor: {chrome_path}")
    print(f"     --remote-debugging-port={CDP_PORT} --user-data-dir={USER_DATA_DIR}")
    Path(USER_DATA_DIR).mkdir(parents=True, exist_ok=True)
    # Chrome'u detach et, kendi surecinde calissin
    subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={USER_DATA_DIR}",
            BASE_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x00000008 if sys.platform == "win32" else 0,  # DETACHED_PROCESS
    )
    # Port acilana kadar bekle (max 10s)
    for i in range(10):
        await asyncio.sleep(1)
        if _port_open():
            print(f"  ✓ Chrome CDP port {CDP_PORT} hazir ({i+1}s)")
            return True
    print(f"  ⚠️  Chrome acildi ama CDP port {CDP_PORT} acilmadi, elle kontrol et")
    return False


async def _wait_for_login(timeout_sec: int = 300) -> tuple[bool, list[dict] | None]:
    """Neo manuel login yapana kadar bekle, cookie'leri dondur."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"  ❌ CDP baglanti fail: {e}")
            return False, None

        if not browser.contexts:
            print("  ❌ Browser context yok")
            return False, None
        ctx = browser.contexts[0]

        # Sayfayı bul: Eyotek page varsa onu kullan, yoksa yeni ac
        eyotek_page = None
        for pg in ctx.pages:
            if "eyotek" in (pg.url or "").lower():
                eyotek_page = pg
                break
        if not eyotek_page:
            eyotek_page = await ctx.new_page()
            await eyotek_page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)

        print(f"\n  📌 Sayfa acik: {eyotek_page.url}")
        print("\n  🔓 CHROME'DA LOGIN YAP:")
        print("     1) Cloudflare 'robot degilim' kutucugunu tıkla")
        print("     2) Kullanici adi / sifre gir")
        print("     3) Giris yap -> ana sayfa acilsin (/Pages/Staff/home)")
        print("\n  ⏳ Bekliyorum (login tamamlanana kadar, max 5 dk)...\n")

        def _is_auth(url: str) -> bool:
            return (
                "fermat.eyotek.com" in url
                and "/Pages/" in url
                and "default.aspx" not in url.lower()
                and "login" not in url.lower()
            )

        # Polling: her 2s URL kontrol
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            await asyncio.sleep(2)
            try:
                cur = eyotek_page.url
            except Exception:
                # Page kapanmış olabilir, aktif sekmeyi tekrar bul
                for pg in ctx.pages:
                    if "eyotek" in (pg.url or "").lower():
                        eyotek_page = pg
                        cur = pg.url
                        break
                else:
                    continue
            if _is_auth(cur):
                print(f"  ✅ Login basarili! URL: {cur}")
                # Cookie'leri al
                all_cookies = await ctx.cookies()
                eyotek_cookies = [c for c in all_cookies if "eyotek" in c.get("domain", "").lower()]
                await browser.close()
                return True, eyotek_cookies
        print("  ⏰ Zaman doldu (5 dk), login tespit edilemedi.")
        await browser.close()
        return False, None


def _save_local(cookies: list[dict]) -> None:
    """Cookie'leri local dosyaya kaydet."""
    SESSION_FILE.write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  💾 Local kaydedildi: {SESSION_FILE} ({len(cookies)} cookie)")


def _scp_to_vps() -> bool:
    """SCP ile VPS'e transfer et."""
    cmd = [
        "scp",
        "-i", VPS_SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        str(SESSION_FILE),
        f"{VPS_HOST}:{VPS_TARGET}",
    ]
    print(f"  📤 SCP: {SESSION_FILE.name} -> {VPS_HOST}:{VPS_TARGET}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            print(f"  ✅ VPS'e aktarıldı")
            return True
        print(f"  ❌ SCP fail: {r.stderr.strip()[:200]}")
        return False
    except Exception as e:
        print(f"  ❌ SCP exception: {e}")
        return False


def _vps_reload_signal() -> bool:
    """VPS'te cookie reload sinyali gonder (opsiyonel — Python service fs watch yok, marker dosya)."""
    cmd = [
        "ssh",
        "-i", VPS_SSH_KEY,
        "-o", "StrictHostKeyChecking=accept-new",
        VPS_HOST,
        "touch /opt/fermatai/.eyotek_session_reloaded && "
        "echo '[EYOTEK] Cookie yenilendi: '$(date '+%Y-%m-%d %H:%M:%S')",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            print(f"  ✅ VPS reload sinyali: {r.stdout.strip()}")
            return True
    except Exception:
        pass
    return False


async def main():
    _print_banner()
    print(f"  VPS hedefi: {VPS_HOST}:{VPS_TARGET}")
    print(f"  Eyotek URL: {BASE_URL}\n")

    # 1. Chrome ac
    if not await _open_chrome_with_cdp():
        print("\n  ⚠️  Chrome'u elle CDP portuyla baslat:")
        print(f"     chrome.exe --remote-debugging-port={CDP_PORT} --user-data-dir=C:\\ChromeDebug")
        print(f"     Sonra: {BASE_URL} adresine git, login yap.")
        input("\n  Login yaptiktan sonra ENTER'a bas...")

    # 2. Login bekle
    ok, cookies = await _wait_for_login(timeout_sec=300)
    if not ok or not cookies:
        print("\n  ❌ Login tamamlanmadi, islem iptal edildi.")
        sys.exit(1)

    # 3. Save local
    _save_local(cookies)

    # 4. SCP to VPS
    if not _scp_to_vps():
        print("\n  ⚠️  VPS'e aktarilamadi, cookie local'de. Elle:")
        print(f"     scp -i {VPS_SSH_KEY} {SESSION_FILE} {VPS_HOST}:{VPS_TARGET}")
        sys.exit(1)

    # 5. Signal reload (opsiyonel)
    _vps_reload_signal()

    print("\n" + "=" * 62)
    print("  🎉 TAMAM — Eyotek oturumu VPS'te aktif")
    print("=" * 62)
    print("  📅 Beklenen gecerlilik: ~20-30 dk (ASP.NET session)")
    print("     VPS session_keeper heartbeat ile uzatmaya calisacak.")
    print("     Session oldugunde WP'ye bildirim gidecek.")
    print()
    print("  ℹ️  Artik laptop'u kapatabilirsin.")
    print("     Bot Eyotek'e VPS'ten devam edecek.\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Iptal edildi (Ctrl+C)")
        sys.exit(130)
