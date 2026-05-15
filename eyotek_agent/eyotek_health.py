"""
Eyotek Health Check — Tek Doğruluk Kaynağı (25.43-INT-FIX1)
=============================================================

NEO BUG (9 May 20:09-20:14): "Eyotek bağlı mıyız" sorusuna bot 5 dk içinde
3 zıt cevap verdi:
  - 20:09:48 KAPALI (CDP port 9333 down)
  - 20:13:43 CANLI (cookie dosyası geçerli)
  - 20:14:21 DÜŞMÜŞ (gerçek API çağrı fail)

Kök neden: 3 farklı kontrol var ama bot herhangi birini kullanıp tam cevap diyor.
Tek bir ground-truth fonksiyonu yok.

ÇÖZÜM: eyotek_health_check() — port + cookie + live API'yi sırasıyla check eder,
unified status döner. Bot bu tek fonksiyona güvenmeli.

Status enum:
  "online"        — live API çağrı başarılı (en güvenilir)
  "session_drop"  — cookie var ama API session timeout (re-login gerek)
  "cdp_down"      — Chrome CDP port kapalı (browser yok)
  "no_cookie"     — Hiç cookie yok (yeni login gerek)
  "unknown"       — Beklenmedik hata
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path
from typing import Optional

from loguru import logger


# In-memory cache (15sn TTL — bot aynı oturumda peş peşe çağırırsa)
_HEALTH_CACHE: dict = {"timestamp": 0, "result": None}
_CACHE_TTL_SEC = 15


def _check_cdp_port() -> tuple[bool, str]:
    """CDP port (9222 default, 9333 fallback) socket-level erişilebilir mi?

    Returns: (ok, detail)
    """
    import os
    port = int(os.getenv("CDP_PORT", "9222"))
    fallback_port = int(os.getenv("EYOTEK_CDP_PORT", "9333"))
    for p in (port, fallback_port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                r = s.connect_ex(("127.0.0.1", p))
                if r == 0:
                    return True, f"CDP port {p} acik"
        except Exception as e:
            continue
    return False, f"CDP port {port}/{fallback_port} kapali"


def _check_cookie_file() -> tuple[bool, str, Optional[dict]]:
    """SESSION_FILE'da gecerli ASP.NET session cookie var mi?

    Returns: (ok, detail, session_info)
    """
    paths_to_try = []
    try:
        from eyotek_auto_login import SESSION_FILE as AUTO_SESSION
        paths_to_try.append(Path(AUTO_SESSION))
    except Exception:
        pass
    try:
        from eyotek_wrapper import SESSION_FILE as WRAPPER_SESSION
        paths_to_try.append(Path(WRAPPER_SESSION))
    except Exception:
        pass

    for p in paths_to_try:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(data, list) or not data:
                continue
            # ASP.NET_SessionId arıyoruz
            session_cookie = next(
                (c for c in data if c.get("name", "").lower() == "asp.net_sessionid"
                 or "session" in c.get("name", "").lower()),
                None,
            )
            mtime = p.stat().st_mtime
            age_min = (time.time() - mtime) / 60
            return True, f"Cookie dosyasi {p.name}, yas: {age_min:.0f}dk", {
                "path": str(p),
                "cookie_count": len(data),
                "age_minutes": int(age_min),
                "has_session": session_cookie is not None,
                "expire": session_cookie.get("expires") if session_cookie else None,
            }
        except Exception as e:
            logger.warning(f"Cookie file parse hata {p}: {e}")
            continue

    return False, "Hicbir cookie dosyasi bulunamadi", None


async def _check_live_api() -> tuple[bool, str]:
    """Eyotek'e gercek API call yap, ASP.NET session aktif mi gor.

    Returns: (ok, detail)
    """
    try:
        from eyotek_browser_helper import open_eyotek_browser
    except Exception as e:
        return False, f"helper yuklenemedi: {e}"

    try:
        # Hizli check: Eyotek anasayfasini fetch et, Login redirect var mi?
        async with open_eyotek_browser() as (browser, ctx, page):
            try:
                resp = await page.goto(
                    "https://fermat.eyotek.com/v1/Default.aspx",
                    timeout=8000,
                    wait_until="domcontentloaded",
                )
                if resp is None:
                    return False, "API goto None resp"
                final_url = page.url.lower()
                # Login sayfasina redirect olduysa session timeout
                if "login" in final_url or "girish" in final_url:
                    return False, f"Login redirect: {final_url[:80]} (session timeout)"
                # 200 OK ve login degil → canli
                if resp.status == 200:
                    return True, f"Live API 200 OK, url={final_url[:60]}"
                return False, f"HTTP {resp.status}"
            except Exception as e:
                return False, f"goto hata: {str(e)[:100]}"
    except Exception as e:
        emsg = str(e)[:100]
        if "ECONNREFUSED" in emsg or "connect" in emsg.lower():
            return False, f"CDP/Browser baglanti yok: {emsg}"
        return False, f"Helper hata: {emsg}"


async def eyotek_health_check(use_cache: bool = True, auto_relogin: bool = True) -> dict:
    """Tek doğruluk kaynağı — Eyotek bağlantı sağlık kontrolü.

    Sirasiyla:
      1. CDP port socket check (1sn timeout)
      2. Cookie dosyasi varlık + freshness
      3. Live API call (8sn timeout) — en güvenilir, ASP.NET session test
      4. session_drop ise (cookie var, API fail) AUTO-RELOGIN dene (25.43-EYOTEK-LAZY)

    Args:
        use_cache: 15sn cache kullan (default True)
        auto_relogin: session_drop tespit edince inline relogin dene (default True)
                       Bot artık "eyotek baglan yaz" demek zorunda değil — sistem kendi düzeltir.

    Returns:
        {
            "status": "online" | "session_drop" | "cdp_down" | "no_cookie" | "unknown",
            "is_connected": bool,
            "detail": str,
            "checks": {"cdp": {...}, "cookie": {...}, "live": {...}},
            "user_message": str  # bot bunu kullaniciya direkt gosterebilir
            "auto_relogin_attempted": bool (varsa)
        }
    """
    # Cache kontrol
    now = time.time()
    if use_cache and _HEALTH_CACHE["result"] and (now - _HEALTH_CACHE["timestamp"]) < _CACHE_TTL_SEC:
        cached = dict(_HEALTH_CACHE["result"])
        cached["_cached"] = True
        return cached

    # 1. CDP port check (sadece bilgi amacli — karar live API)
    cdp_ok, cdp_detail = _check_cdp_port()

    # 2. Cookie file check (lokal, hızlı)
    cookie_ok, cookie_detail, cookie_info = _check_cookie_file()

    # 3. Live API (yavas ama en guvenilir) — 25.46.8 (Neo bug 16 May):
    # ESKI: sadece cdp_ok AND cookie_ok ise dene
    # YENI: cookie var ise her zaman dene (open_eyotek_browser headless launch
    # destekler, CDP gerektirmez). Boylece CDP kapali ama navigator calisiyor
    # durumlarda "cdp_down" yanlis cevabi engellenir.
    live_ok = False
    live_detail = "Atlandi (cookie yok)"
    if cookie_ok:
        try:
            live_ok, live_detail = await asyncio.wait_for(_check_live_api(), timeout=15.0)
        except asyncio.TimeoutError:
            live_ok = False
            live_detail = "Live API timeout (>15s)"
        except Exception as e:
            live_ok = False
            live_detail = f"Live API exception: {str(e)[:80]}"

    # 25.43-EYOTEK-LAZY: session_drop tespit edilirse INLINE AUTO-RELOGIN dene
    # Eski "her zaman ulaşılabilir" sistem böyle çalışıyordu — bot çağrısı sırasında
    # cookie expire olunca otomatik refresh, kullanıcı farkı görmez.
    # 25.46.8: cdp_ok kosulu kaldirildi — CDP off olsa bile cookie var + auto-relogin denesin
    relogin_attempted = False
    if auto_relogin and cookie_ok and not live_ok:
        relogin_attempted = True
        try:
            from eyotek_auto_login import try_auto_login
            login_r = await asyncio.wait_for(
                try_auto_login(timeout_ms=25000, trigger_source="eyotek_health_lazy"),
                timeout=30.0,
            )
            if login_r.get("success"):
                logger.info("[HEALTH] auto_relogin BASARILI, live API tekrar test")
                # Live test tekrar
                try:
                    live_ok2, live_detail2 = await asyncio.wait_for(_check_live_api(), timeout=12.0)
                    if live_ok2:
                        live_ok = True
                        live_detail = f"Auto-relogin sonrasi: {live_detail2}"
                except Exception as e:
                    logger.warning(f"[HEALTH] post-relogin live test fail: {e}")
            else:
                logger.warning(f"[HEALTH] auto_relogin fail: {login_r.get('reason')}")
        except asyncio.TimeoutError:
            logger.warning("[HEALTH] auto_relogin timeout (>30s)")
        except Exception as e:
            logger.warning(f"[HEALTH] auto_relogin exception: {e}")

    # Karar matrisi (en güvenilir cevap) — 25.46.8 (Neo bug 16 May)
    # KARAR: live API basariliysa "online" (CDP up/down fark etmez).
    # Navigator headless launch CDP'siz çalışıyor — bot "cdp_down" yanlış mesaj
    # vermesin. CDP info sadece teşhis amaçlı kalsın.
    if live_ok:
        status = "online"
        is_connected = True
        if cdp_ok:
            msg = "✅ Eyotek bağlantısı CANLI — CDP + canlı API her ikisi doğrulandı"
        else:
            msg = "✅ Eyotek bağlantısı CANLI — navigator headless ile çalışıyor (CDP kapalı ama veri akıyor)"
        if relogin_attempted:
            msg += " (auto-relogin sonrasi)"
    elif cookie_ok and not live_ok:
        # Cookie var ama API fail (CDP up veya down fark etmez)
        # Auto-relogin denendi ama olmadi
        status = "session_drop"
        is_connected = False
        if cdp_ok:
            msg = "⚠️ Eyotek session düştü — cookie expired olabilir, admin 'eyotek tamam' gerek"
        else:
            msg = "⚠️ CDP kapalı + cookie expired — admin 'eyotek tamam' veya BASLAT_EYOTEK.bat gerek"
    elif not cookie_ok:
        status = "no_cookie"
        is_connected = False
        msg = "❌ Eyotek bağlı DEĞİL — cookie dosyası yok, yeni login gerek"
    else:
        status = "unknown"
        is_connected = False
        msg = "❓ Eyotek durumu belirsiz — manuel kontrol gerekli"

    result = {
        "status": status,
        "is_connected": is_connected,
        "detail": msg,
        "checks": {
            "cdp": {"ok": cdp_ok, "detail": cdp_detail},
            "cookie": {"ok": cookie_ok, "detail": cookie_detail, "info": cookie_info},
            "live": {"ok": live_ok, "detail": live_detail},
        },
        "user_message": msg,
        "auto_relogin_attempted": relogin_attempted,
        "checked_at": time.time(),
    }
    _HEALTH_CACHE["timestamp"] = now
    _HEALTH_CACHE["result"] = result
    return result


# CLI test
if __name__ == "__main__":
    import sys
    r = asyncio.run(eyotek_health_check(use_cache=False))
    print(json.dumps(r, indent=2, ensure_ascii=False))
    sys.exit(0 if r["is_connected"] else 1)
