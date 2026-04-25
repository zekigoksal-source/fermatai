"""
CapSolver Helper (Oturum 25.6 — Talimat #85)
=============================================
Cloudflare Turnstile CAPTCHA auto-solve.

Neo'nun karari (24 Nisan 2026 15:03):
> "Tamam bu cozumu kaydet uygulayalim sonrada hep sistem online kalsin
> hic manuel mudahele gerekmeden"

Akis:
1. Eyotek login sayfasinda Turnstile widget tespit edilir
2. data-sitekey ve websiteURL CapSolver'a gonderilir
3. ~5-10sn icinde token doner
4. Token sayfaya inject edilir (cf-turnstile-response)
5. Login form submit edilir
6. Cookie yakalanir

Maliyet: ~$0.001/cozum. Haftada 2-3 CAPTCHA -> ayda ~$0.05.

API: https://docs.capsolver.com/
"""
from __future__ import annotations
import asyncio
import os
from typing import Optional

import httpx
from loguru import logger
from dotenv import load_dotenv

load_dotenv(override=True)

CAPSOLVER_API_KEY = os.getenv("CAPSOLVER_API_KEY", "")
CAPSOLVER_BASE = "https://api.capsolver.com"
DEFAULT_TIMEOUT = 90  # seconds — CAPTCHA solve genelde 5-10s, bazen 30s


class CapSolverError(Exception):
    """CapSolver API hatalari."""


async def _log_usage(
    success: bool,
    duration_ms: int,
    balance_before: Optional[float],
    balance_after: Optional[float],
    trigger_source: str = "manual",
    sitekey: str = "",
    error_msg: Optional[str] = None,
) -> None:
    """capsolver_usage tablosuna kayit ekle (Oturum 25.7 — usage tracking)."""
    try:
        from db_pool import db_execute
        await db_execute(
            """INSERT INTO capsolver_usage
               (success, error_msg, duration_ms, balance_before, balance_after,
                trigger_source, sitekey)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            success,
            (error_msg or "")[:500] if not success else None,
            duration_ms,
            balance_before,
            balance_after,
            trigger_source[:50],
            (sitekey or "")[:100],
        )
    except Exception as e:
        logger.warning(f"[CAPSOLVER] DB log fail (devam): {e}")


async def solve_turnstile(
    website_url: str,
    website_key: str,
    timeout_sec: int = DEFAULT_TIMEOUT,
    trigger_source: str = "manual",
) -> Optional[str]:
    """
    Cloudflare Turnstile challenge'i CapSolver ile cöz.

    Args:
        website_url: Turnstile widget bulunan sayfa URL'si (ornegin "https://fermat.eyotek.com/v1/")
        website_key: Widget'in data-sitekey attribute'u (ornegin "0x4AAAAAAABkMYinukE8nzYS")
        timeout_sec: Max bekleme suresi

    Returns:
        Token string (cf-turnstile-response value'sine inject edilir)
        None -> cozulemedi veya API key yok
    """
    if not CAPSOLVER_API_KEY:
        logger.warning("[CAPSOLVER] CAPSOLVER_API_KEY .env'de yok")
        return None

    import time as _time
    _t_start = _time.time()
    _balance_before = await get_balance()

    # 1. Task olustur
    create_payload = {
        "clientKey": CAPSOLVER_API_KEY,
        "task": {
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": website_url,
            "websiteKey": website_key,
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(f"{CAPSOLVER_BASE}/createTask", json=create_payload)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"[CAPSOLVER] createTask fail: {e}")
            return None

        if data.get("errorId") != 0:
            logger.error(f"[CAPSOLVER] Task error: {data.get('errorDescription', '')}")
            return None

        task_id = data.get("taskId")
        if not task_id:
            logger.error("[CAPSOLVER] Task ID yok")
            return None

        logger.info(f"[CAPSOLVER] Task created: {task_id}, token bekleniyor...")

        # 2. Token poll (her 2sn'de bir, max timeout_sec)
        deadline = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2.0)
            try:
                r = await client.post(
                    f"{CAPSOLVER_BASE}/getTaskResult",
                    json={"clientKey": CAPSOLVER_API_KEY, "taskId": task_id},
                )
                r.raise_for_status()
                result = r.json()
            except Exception as e:
                logger.warning(f"[CAPSOLVER] getTaskResult fail (devam): {e}")
                continue

            status = result.get("status")
            if status == "ready":
                solution = result.get("solution", {})
                token = solution.get("token") or solution.get("cf_turnstile_token")
                if token:
                    duration_ms = int((_time.time() - _t_start) * 1000)
                    _balance_after = await get_balance()
                    logger.success(f"[CAPSOLVER] Token alindi ({len(token)} char, {duration_ms}ms)")
                    await _log_usage(
                        success=True, duration_ms=duration_ms,
                        balance_before=_balance_before, balance_after=_balance_after,
                        trigger_source=trigger_source, sitekey=website_key,
                    )
                    return token
                err = f"Ready ama token yok: {solution}"
                logger.error(f"[CAPSOLVER] {err}")
                await _log_usage(
                    success=False, duration_ms=int((_time.time() - _t_start) * 1000),
                    balance_before=_balance_before, balance_after=None,
                    trigger_source=trigger_source, sitekey=website_key, error_msg=err,
                )
                return None
            elif status == "failed":
                err = result.get("errorDescription", "")
                logger.error(f"[CAPSOLVER] Task fail: {err}")
                await _log_usage(
                    success=False, duration_ms=int((_time.time() - _t_start) * 1000),
                    balance_before=_balance_before, balance_after=None,
                    trigger_source=trigger_source, sitekey=website_key, error_msg=err,
                )
                return None
            # status == "processing" -> devam et

        err = f"Timeout ({timeout_sec}s) — token gelmedi"
        logger.error(f"[CAPSOLVER] {err}")
        await _log_usage(
            success=False, duration_ms=int((_time.time() - _t_start) * 1000),
            balance_before=_balance_before, balance_after=None,
            trigger_source=trigger_source, sitekey=website_key, error_msg=err,
        )
        return None


async def get_balance() -> Optional[float]:
    """CapSolver hesap bakiyesi (USD). Neo izleme icin."""
    if not CAPSOLVER_API_KEY:
        return None
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.post(
                f"{CAPSOLVER_BASE}/getBalance",
                json={"clientKey": CAPSOLVER_API_KEY},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("errorId") == 0:
                return float(data.get("balance", 0))
        except Exception as e:
            logger.warning(f"[CAPSOLVER] Balance fail: {e}")
    return None


if __name__ == "__main__":
    # CLI test: python capsolver_helper.py
    async def _main():
        bal = await get_balance()
        print(f"CapSolver bakiye: ${bal}" if bal is not None else "Bakiye alinamadi (API key?)")
    asyncio.run(_main())
