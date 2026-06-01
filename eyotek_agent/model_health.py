"""
model_health.py — LLM Vendor/Model Availability Preflight (Oturum 25.50)
========================================================================
NEDEN (Neo 1 Haz direktif): Cerebras qwen-3-235b-a22b'yi 26-31 May arası
SESSIZCE emekli etti (404). 5 GÜN boyunca "kompleks" intent'ler 404 alıp
pahalı Claude'a fallback etti — biz sadece Sentry 404 birikiminden + maliyet
sıçramasından FARK ETTİK. Reaktif yakalandık.

BU MODÜL: Yapılandırılmış HER LLM modelini (Cerebras + Groq + Claude) küçük bir
ping ile proaktif kontrol eder. Emekli/auth hatası → Neo'ya KRİTİK WP alarmı +
model_health tablosuna kayıt. Vendor bir modeli emekli ettiğinde GÜNLER değil
SAATLER içinde haberdar oluruz + hangi intent'lerin etkilendiğini biliriz.

Modeller SABİT LİSTE DEĞİL — gerçek config kaynaklarından okunur (kod/env tek
değişince monitör otomatik uyum sağlar):
  · Cerebras: cerebras_handler.CEREBRAS_MODELS + INTENT_TO_MODEL (benzersiz değerler)
  · Groq:     env GROQ_MODEL_PRIMARY + GROQ_MODEL_FAST
  · Claude:   env FERMAT_MODEL

Kullanım:
  python model_health.py              # kontrol + tablo + (kritikse) alarm
  python model_health.py --no-alert   # sadece kontrol + rapor (alarm yok)
  python model_health.py --json       # makine-okuyabilir çıktı

Cron: fermatai-model-health.timer (günde 1, 06:00) — systemd.
WP admin komutu: "model durum" / "model health" → run_health_check tetikler.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT.parent / ".env", override=True)
load_dotenv(override=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1) Yapılandırılmış modelleri GERÇEK config kaynaklarından topla
# ─────────────────────────────────────────────────────────────────────────────
def get_configured_models() -> list[dict]:
    """Şu an kullanımda olan benzersiz (provider, model_id) listesi.

    Sabit liste DEĞİL — kod + env'den okunur. Routing değişince otomatik uyum.
    Döner: [{"provider": "cerebras", "model": "gpt-oss-120b", "used_by": [...]}, ...]
    """
    models: dict[tuple, set] = {}

    def _add(provider: str, model_id: str, used_by: str):
        if not model_id:
            return
        key = (provider, model_id)
        models.setdefault(key, set()).add(used_by)

    # Cerebras — kod içi katalog + intent haritası
    try:
        from cerebras_handler import CEREBRAS_MODELS, INTENT_TO_MODEL
        for tier, mid in CEREBRAS_MODELS.items():
            _add("cerebras", mid, f"tier:{tier}")
        for intent, mid in INTENT_TO_MODEL.items():
            _add("cerebras", mid, f"intent:{intent}")
    except Exception as e:
        logger.warning(f"[MODEL_HEALTH] Cerebras config okunamadı: {e}")

    # Groq — env
    _add("groq", os.getenv("GROQ_MODEL_PRIMARY", "llama-3.3-70b-versatile"), "groq_primary")
    _add("groq", os.getenv("GROQ_MODEL_FAST", "llama-3.1-8b-instant"), "groq_fast")

    # Claude — env
    _add("claude", os.getenv("FERMAT_MODEL", "claude-sonnet-4-6"), "claude_main")

    return [
        {"provider": p, "model": m, "used_by": sorted(used)}
        for (p, m), used in sorted(models.items())
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 2) Hata sınıflandırma — vendor-bağımsız string + status analizi
# ─────────────────────────────────────────────────────────────────────────────
def _classify_error(exc: Exception) -> tuple[str, str]:
    """(durum, kısa_detay) döner.
    durum ∈ {model_not_found, auth_error, rate_limit, timeout, error}
    """
    s = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None)

    # Model emekli / yok — EN KRİTİK (qwen vakası)
    if (status == 404 or "model_not_found" in s or "does not exist" in s
            or "decommission" in s or "has been deprecated" in s
            or "not found" in s or "no longer available" in s
            or "is not a valid model" in s):
        return "model_not_found", str(exc)[:160]
    # Auth — key expire/invalid
    if (status in (401, 403) or "authentication" in s or "invalid api key"
            in s or "invalid_api_key" in s or "permission" in s
            or "unauthorized" in s):
        return "auth_error", str(exc)[:160]
    # Rate limit / TPD — beklenen (Groq free tier), kritik DEĞİL
    if (status in (429, 413) or "rate_limit" in s or "rate limit" in s
            or "tokens per day" in s or "too large" in s or "quota" in s):
        return "rate_limit", str(exc)[:160]
    # Timeout
    if "timeout" in s or "timed out" in s:
        return "timeout", str(exc)[:160]
    return "error", str(exc)[:160]


# ─────────────────────────────────────────────────────────────────────────────
# 3) Tek model ping
# ─────────────────────────────────────────────────────────────────────────────
async def check_one(provider: str, model_id: str) -> dict:
    """Tek modele 1-token ping. {"provider","model","status","detail","ms"}"""
    import time
    t0 = time.time()
    result = {"provider": provider, "model": model_id, "status": "ok", "detail": "", "ms": 0}
    try:
        if provider in ("cerebras", "groq"):
            from openai import OpenAI
            base = ("https://api.cerebras.ai/v1" if provider == "cerebras"
                    else "https://api.groq.com/openai/v1")
            key = os.getenv("CEREBRAS_API_KEY" if provider == "cerebras" else "GROQ_API_KEY", "")
            if not key:
                result.update(status="no_key", detail=f"{provider} API key env'de yok")
                return result
            client = OpenAI(api_key=key, base_url=base, timeout=20.0)
            await asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model=model_id, max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}]))
        elif provider == "claude":
            import anthropic
            key = os.getenv("ANTHROPIC_API_KEY", "")
            if not key:
                result.update(status="no_key", detail="ANTHROPIC_API_KEY env'de yok")
                return result
            client = anthropic.Anthropic(api_key=key, timeout=20.0)
            await asyncio.to_thread(
                lambda: client.messages.create(
                    model=model_id, max_tokens=1,
                    messages=[{"role": "user", "content": "ping"}]))
        else:
            result.update(status="error", detail=f"bilinmeyen provider: {provider}")
            return result
    except Exception as e:
        st, detail = _classify_error(e)
        # rate_limit aslında modelin CANLI olduğunu kanıtlar (sadece kota dolu)
        result.update(status=st, detail=detail)
    result["ms"] = int((time.time() - t0) * 1000)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4) DB tablo + persist
# ─────────────────────────────────────────────────────────────────────────────
async def _ensure_table():
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS model_health (
                id          SERIAL PRIMARY KEY,
                checked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                provider    TEXT NOT NULL,
                model       TEXT NOT NULL,
                status      TEXT NOT NULL,
                detail      TEXT,
                latency_ms  INT,
                used_by     TEXT
            )""")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS model_health_model_idx ON model_health(model, checked_at DESC)")


async def _persist(results: list[dict]):
    try:
        from db_pool import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            for r in results:
                await conn.execute(
                    """INSERT INTO model_health
                       (provider, model, status, detail, latency_ms, used_by)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    r["provider"], r["model"], r["status"], r.get("detail", ""),
                    r.get("ms", 0), ", ".join(r.get("used_by", []))[:300])
    except Exception as e:
        logger.warning(f"[MODEL_HEALTH] persist hata: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 5) Ana akış
# ─────────────────────────────────────────────────────────────────────────────
# Kritik = model gerçekten kullanılamaz (emekli veya auth). rate_limit/timeout
# geçici → kritik değil (Groq TPD limiti her gün dolabilir, spam yapma).
_CRITICAL = {"model_not_found", "auth_error", "no_key"}


async def run_health_check(alert: bool = True) -> dict:
    """Tüm yapılandırılmış modelleri kontrol et, persist et, kritikse Neo'ya alarm."""
    configured = get_configured_models()
    logger.info(f"[MODEL_HEALTH] {len(configured)} model kontrol ediliyor...")

    results = await asyncio.gather(*[
        check_one(m["provider"], m["model"]) for m in configured])
    # used_by bilgisini geri ekle
    by_key = {(m["provider"], m["model"]): m["used_by"] for m in configured}
    for r in results:
        r["used_by"] = by_key.get((r["provider"], r["model"]), [])

    try:
        await _ensure_table()
        await _persist(results)
    except Exception as e:
        logger.warning(f"[MODEL_HEALTH] tablo/persist atlandı: {e}")

    critical = [r for r in results if r["status"] in _CRITICAL]
    degraded = [r for r in results if r["status"] in ("rate_limit", "timeout", "error")]
    healthy = [r for r in results if r["status"] == "ok"]

    summary = {
        "total": len(results), "healthy": len(healthy),
        "critical": len(critical), "degraded": len(degraded),
        "results": results,
    }

    # Konsol rapor
    for r in results:
        icon = "✅" if r["status"] == "ok" else ("🔴" if r["status"] in _CRITICAL else "🟡")
        logger.info(f"  {icon} {r['provider']:9} {r['model']:28} {r['status']:16} {r['ms']:5}ms")

    # KRİTİK alarm — sadece model_not_found / auth (qwen senaryosu)
    if alert and critical:
        await _alert_neo(critical, results)

    return summary


async def _alert_neo(critical: list[dict], all_results: list[dict]):
    """Neo'ya kritik model alarmı (mevcut notify_admin reuse, severity=critical)."""
    lines = ["🔴 *MODEL SAĞLIK ALARMI* — bir LLM modeli kullanılamıyor!\n"]
    for r in critical:
        intents = [u for u in r.get("used_by", []) if u.startswith("intent:")]
        etki = f" ({len(intents)} intent etkilendi)" if intents else ""
        lines.append(f"❌ *{r['provider']}* / `{r['model']}` → {r['status']}{etki}")
        lines.append(f"   {r['detail'][:120]}")
    lines.append("\n_Vendor modeli emekli/değiştirmiş olabilir (qwen-235b gibi)._")
    lines.append("_Routing'i çalışan modele güncelle: cerebras_handler.py / .env._")
    msg = "\n".join(lines)
    try:
        from session_keeper import notify_admin
        await notify_admin(msg, category="model_health", severity="critical")
        logger.error(f"[MODEL_HEALTH] KRİTİK: {len(critical)} model down — Neo'ya alarm gönderildi")
    except Exception as e:
        logger.error(f"[MODEL_HEALTH] alarm gönderilemedi: {e}\nMesaj:\n{msg}")


def format_report(summary: dict) -> str:
    """WP/CLI için insan-okuyabilir özet."""
    lines = [f"🩺 *Model Sağlık Raporu* — {summary['healthy']}/{summary['total']} sağlıklı"]
    if summary["critical"]:
        lines.append(f"🔴 {summary['critical']} KRİTİK (kullanılamaz)")
    if summary["degraded"]:
        lines.append(f"🟡 {summary['degraded']} geçici sorun (rate-limit/timeout)")
    lines.append("")
    for r in summary["results"]:
        icon = "✅" if r["status"] == "ok" else ("🔴" if r["status"] in _CRITICAL else "🟡")
        lines.append(f"{icon} {r['provider']}/{r['model']} — {r['status']} ({r['ms']}ms)")
    return "\n".join(lines)


async def main():
    args = sys.argv[1:]
    alert = "--no-alert" not in args
    summary = await run_health_check(alert=alert)
    if "--json" in args:
        import json
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n" + format_report(summary))
    # Exit code: kritik varsa 2 (cron/monitoring için)
    sys.exit(2 if summary["critical"] else 0)


if __name__ == "__main__":
    asyncio.run(main())
