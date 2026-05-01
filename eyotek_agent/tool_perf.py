"""
Tool Performance Tracking — 25.37+ (Neo audit aksiyon #3)
==========================================================
Her Claude tool çağrısında latency + success kayıt et → optimize edilebilsin.

Kullanım:
    from tool_perf import track_tool_perf

    @track_tool_perf
    async def _tool_make_render_link(...):
        ...

    # CLI rapor:
    python tool_perf.py            → en yavaş 20 tool
    python tool_perf.py make_render_link  → spesifik tool detay
"""
from __future__ import annotations
import asyncio
import functools
import time
from typing import Any, Callable
from loguru import logger

from db_pool import db_execute, db_fetch, db_fetchval


async def ensure_table():
    """Tablo yoksa oluştur — idempotent. Çağrı: bridge boot."""
    try:
        await db_execute("""
            CREATE TABLE IF NOT EXISTS tool_usage_log (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP DEFAULT NOW(),
                tool_name TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                success BOOLEAN NOT NULL DEFAULT TRUE,
                role TEXT,
                phone TEXT,
                error_preview TEXT,
                input_size_kb INTEGER,
                output_size_kb INTEGER
            )
        """)
        await db_execute("CREATE INDEX IF NOT EXISTS idx_tool_perf_name ON tool_usage_log(tool_name, created_at)")
        await db_execute("CREATE INDEX IF NOT EXISTS idx_tool_perf_date ON tool_usage_log(created_at)")
        logger.debug("tool_usage_log tablo hazır")
    except Exception as e:
        logger.warning(f"tool_usage_log ensure_table: {e}")


async def _log_call(tool_name: str, duration_ms: int, success: bool,
                     role: str = "", phone: str = "", error: str = "",
                     input_kb: int = 0, output_kb: int = 0) -> None:
    """Async fire-and-forget log."""
    try:
        await db_execute(
            """INSERT INTO tool_usage_log
               (tool_name, duration_ms, success, role, phone, error_preview, input_size_kb, output_size_kb)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            tool_name[:60], int(duration_ms), bool(success),
            (role or "")[:20], (phone or "")[-12:],
            (error or "")[:300], int(input_kb), int(output_kb)
        )
    except Exception as e:
        logger.debug(f"tool_perf log fail [{tool_name}]: {e}")


def track_tool_perf(fn: Callable) -> Callable:
    """Decorator: async tool fonksiyonunu süre + success ile loglar.

    Tool fonksiyonunun ilk arg'ı dict ya da kwargs olabilir.
    _caller_role / _caller_phone keys varsa role/phone log edilir.
    """
    tool_name = fn.__name__.lstrip("_").replace("_tool_", "")

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        start = time.time()
        success = True
        error_msg = ""
        result = None
        # Role/phone extract
        role = kwargs.get("_caller_role", "") or ""
        phone = kwargs.get("_caller_phone", "") or ""
        # Input size estimate
        try:
            import json as _json
            input_kb = len(_json.dumps(kwargs, ensure_ascii=False, default=str).encode("utf-8")) // 1024
        except Exception:
            input_kb = 0
        try:
            result = await fn(*args, **kwargs)
            # Success kontrolü
            if isinstance(result, dict):
                success = bool(result.get("success", True))
                if not success:
                    error_msg = str(result.get("error", ""))[:300]
            return result
        except Exception as e:
            success = False
            error_msg = str(e)[:300]
            raise
        finally:
            duration_ms = int((time.time() - start) * 1000)
            output_kb = 0
            try:
                if result is not None:
                    import json as _json
                    output_kb = len(_json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")) // 1024
            except Exception:
                pass
            # Async fire-forget — caller'ı blocklamasın
            try:
                asyncio.create_task(_log_call(
                    tool_name, duration_ms, success,
                    role, phone, error_msg, input_kb, output_kb
                ))
            except Exception:
                pass

    return wrapper


# ── Reporting ──────────────────────────────────────────────────────────────
async def get_top_slow_tools(limit: int = 20, days: int = 7) -> list[dict]:
    """En yavaş tool'lar (p95 bazlı)."""
    try:
        rows = await db_fetch(
            f"""SELECT tool_name,
                       COUNT(*) AS calls,
                       ROUND(AVG(duration_ms))::int AS avg_ms,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms)::int AS p50,
                       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::int AS p95,
                       MAX(duration_ms) AS max_ms,
                       SUM(CASE WHEN success THEN 0 ELSE 1 END) AS fails
                FROM tool_usage_log
                WHERE created_at > NOW() - INTERVAL '{int(days)} days'
                GROUP BY tool_name
                ORDER BY p95 DESC
                LIMIT $1""",
            int(limit)
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"get_top_slow_tools: {e}")
        return []


async def get_tool_detail(tool_name: str, days: int = 7) -> dict:
    """Spesifik tool detay raporu."""
    try:
        row = await db_fetch(
            f"""SELECT
                  COUNT(*) AS calls,
                  ROUND(AVG(duration_ms))::int AS avg_ms,
                  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms)::int AS p50,
                  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)::int AS p95,
                  MAX(duration_ms) AS max_ms,
                  MIN(duration_ms) AS min_ms,
                  ROUND(AVG(input_size_kb)::numeric, 1) AS avg_in_kb,
                  ROUND(AVG(output_size_kb)::numeric, 1) AS avg_out_kb,
                  SUM(CASE WHEN success THEN 1 ELSE 0 END) AS ok,
                  SUM(CASE WHEN success THEN 0 ELSE 1 END) AS fail
                FROM tool_usage_log
                WHERE tool_name = $1 AND created_at > NOW() - INTERVAL '{int(days)} days'""",
            tool_name
        )
        if not row:
            return {"tool": tool_name, "calls": 0}
        d = dict(row[0])
        d["tool"] = tool_name
        # En sık fail nedenleri
        fail_rows = await db_fetch(
            """SELECT error_preview, COUNT(*) AS c
               FROM tool_usage_log
               WHERE tool_name = $1 AND success = FALSE
                 AND created_at > NOW() - INTERVAL '7 days'
               GROUP BY error_preview ORDER BY c DESC LIMIT 5""",
            tool_name
        )
        d["top_errors"] = [{"err": r["error_preview"], "count": r["c"]} for r in fail_rows]
        return d
    except Exception as e:
        return {"tool": tool_name, "error": str(e)}


# CLI
async def _cli():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] != "ensure":
        d = await get_tool_detail(sys.argv[1])
        import json as _j
        print(_j.dumps(d, indent=2, default=str, ensure_ascii=False))
    else:
        if len(sys.argv) > 1 and sys.argv[1] == "ensure":
            await ensure_table()
            print("OK tool_usage_log table hazır")
            return
        rows = await get_top_slow_tools(limit=15)
        print(f"{'Tool':<35} {'Calls':>6} {'Avg':>6} {'P50':>6} {'P95':>7} {'Max':>7} {'Fail':>5}")
        print("-" * 78)
        for r in rows:
            print(f"{r['tool_name'][:35]:<35} {r['calls']:>6} {r['avg_ms']:>5}ms "
                  f"{r['p50']:>5}ms {r['p95']:>6}ms {r['max_ms']:>6}ms {r['fails']:>5}")


if __name__ == "__main__":
    asyncio.run(_cli())
