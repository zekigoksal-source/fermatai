"""
Token Budget — Classroom Management Çekirdek #1
=================================================
Neo vizyonu (22 Nisan 18:00):
  "Her konuşma token. Bir öğrenci sonsuz masraf yaptırabilir.
   Bu bir EdTech — öğrenciyi eğitim sürecinde tutmalı. Sınırı olmalı
   ama sınır değil gibi hissettirmeli — doğal öğretmen gibi."

ROL BAZLI GÜNLÜK LİMİT:
  ogrenci:  20.000 token (~50 Claude mesajı)
  ogretmen: 40.000 token (analitik ağırlık)
  rehber:   40.000
  mudur:    80.000
  admin:    SINIRSIZ (None)

SINYAL YAPISI (sert kesme yok, nazik):
  %0-75:   normal çalışır, hiç uyarı yok
  %75-90:  "nazik uyarı" — Claude system prompt'a not ek: "öğrenci bugün
           çok konuştu, son konuya odaklanmasını öner, yeni konu AÇMA"
  %90-100: "son seans" — "bugünlük tamam, yarın taze bakalım" mesajı
  %100+:   sadece Ollama (basit sohbet), Claude ÇAĞRILMAZ

GECE 00:00 RESET — DB'de ayrı kayıt, eski kayıt korunur (analitik).

DEFAULT PASIF:
  TOKEN_BUDGET_ENFORCE=false (env) → sadece ölçer, engellemez.
  Neo "aktif et" diyene kadar cache öyle kalacak.
"""
from __future__ import annotations
import os
from datetime import datetime, date
from typing import Optional
from loguru import logger

# ── Ayarlar ──────────────────────────────────────────────────────────────────

ENFORCE_ACTIVE = os.getenv("TOKEN_BUDGET_ENFORCE", "false").lower() in ("1", "true", "yes")

ROLE_DAILY_LIMIT = {
    "ogrenci": 20_000,
    "ogretmen": 40_000,
    "rehber": 40_000,
    "yonetim": 60_000,
    "veli": 10_000,
    "mudur": 80_000,
    "admin": None,  # sınırsız
}

# Nazik uyarı eşikleri (oran)
WARN_THRESHOLD = 0.75
LAST_SEANS_THRESHOLD = 0.90
HARD_STOP_THRESHOLD = 1.00  # sadece ENFORCE_ACTIVE=true ise etkin

# Claude çağrısı tahmini token (gerçek sayım yerine uygulanabilir heuristic)
AVG_CLAUDE_TOKENS_PER_CALL = 400  # input+output tahmini
AVG_OLLAMA_TOKENS_PER_CALL = 150  # lokalde token sayılmaz ama yaklaşık


# ── DB Şeması ────────────────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fermat.token_budget_daily (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    role TEXT,
    gun DATE NOT NULL DEFAULT CURRENT_DATE,
    token_used INT NOT NULL DEFAULT 0,
    msg_count INT NOT NULL DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(phone, gun)
);
CREATE INDEX IF NOT EXISTS idx_token_budget_phone_gun ON fermat.token_budget_daily(phone, gun);
"""


async def ensure_schema():
    """Tablo yoksa oluştur — lifespan'de idempotent çağrılır."""
    try:
        from db_pool import db_execute
        for stmt in [s.strip() for s in CREATE_TABLE_SQL.split(";") if s.strip()]:
            await db_execute(stmt)
    except Exception as e:
        logger.warning(f"token_budget ensure_schema hatasi: {e}")


# ── API ──────────────────────────────────────────────────────────────────────

async def get_today_usage(phone: str) -> dict:
    """Bugünkü kullanım durumunu döner."""
    try:
        from db_pool import db_fetchrow
        row = await db_fetchrow(
            "SELECT token_used, msg_count, role FROM fermat.token_budget_daily "
            "WHERE phone=$1 AND gun=CURRENT_DATE",
            phone,
        )
        if row:
            return {
                "token_used": row["token_used"] or 0,
                "msg_count": row["msg_count"] or 0,
                "role": row.get("role", ""),
            }
    except Exception as e:
        logger.debug(f"token_budget get_today_usage hatasi: {e}")
    return {"token_used": 0, "msg_count": 0, "role": ""}


async def add_usage(phone: str, role: str, tokens: int, from_claude: bool = True):
    """Kullanımı DB'ye kaydet — UPSERT (gün başına tek kayıt)."""
    try:
        from db_pool import db_execute
        await db_execute(
            """
            INSERT INTO fermat.token_budget_daily (phone, role, gun, token_used, msg_count, last_updated)
            VALUES ($1, $2, CURRENT_DATE, $3, 1, NOW())
            ON CONFLICT (phone, gun) DO UPDATE
              SET token_used = fermat.token_budget_daily.token_used + EXCLUDED.token_used,
                  msg_count  = fermat.token_budget_daily.msg_count + 1,
                  role       = EXCLUDED.role,
                  last_updated = NOW()
            """,
            phone, role or "", tokens,
        )
    except Exception as e:
        logger.debug(f"token_budget add_usage hatasi: {e}")


def role_limit(role: str) -> Optional[int]:
    """Rolün günlük token limiti — None = sınırsız."""
    return ROLE_DAILY_LIMIT.get((role or "").lower(), ROLE_DAILY_LIMIT["ogrenci"])


def classify_usage(used: int, limit: Optional[int]) -> str:
    """Kullanım seviyesini adlandır:
       'ok' | 'warn' | 'last_seans' | 'exceeded'"""
    if limit is None or limit <= 0:
        return "ok"
    oran = used / limit
    if oran >= HARD_STOP_THRESHOLD:
        return "exceeded"
    if oran >= LAST_SEANS_THRESHOLD:
        return "last_seans"
    if oran >= WARN_THRESHOLD:
        return "warn"
    return "ok"


async def check_budget(phone: str, role: str) -> dict:
    """Ana API — process_message başında çağrılır.

    Returns:
        dict:
          status: 'ok' | 'warn' | 'last_seans' | 'exceeded'
          used, limit, remaining, percent
          enforce: bool — True ise gerçekten engelleniyor
          advice: str — Claude prompt'a ek not (warn+ durumda)
    """
    usage = await get_today_usage(phone)
    used = usage["token_used"]
    limit = role_limit(role)
    status = classify_usage(used, limit)

    percent = 0 if limit is None else round(used / limit * 100, 1)
    remaining = None if limit is None else max(0, limit - used)

    advice = ""
    if status == "warn":
        advice = (
            "⚠ CLASSROOM_MGMT: Öğrenci bugün çok konuştu (%75+ token). "
            "YENI KONU AÇMA — mevcut konuyu bitir. Kapanışa yumuşak gir: "
            "'bugün güzel bir sohbet oldu, hedefe dönelim.'"
        )
    elif status == "last_seans":
        advice = (
            "⚠⚠ CLASSROOM_MGMT: Son seans (%90+ token). "
            "Kısa cevap ver. Yarına davet et: 'bugün yorulduk, yarın taze bakarız.'"
        )
    elif status == "exceeded":
        advice = (
            "🛑 CLASSROOM_MGMT: Günlük limit aşıldı. "
            "Tek cümlelik kapanış: 'bugünlük burada bırakalım, yarın görüşürüz.'"
        )

    return {
        "status": status,
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "percent": percent,
        "enforce": ENFORCE_ACTIVE and status == "exceeded",
        "advice": advice,
        "msg_count": usage["msg_count"],
    }


def _estimate_tokens(text: str) -> int:
    """Hızlı tahmin: Türkçe ~3 char/token. 100 char ≈ 33 token."""
    if not text:
        return 0
    return max(10, len(text) // 3)


async def record_interaction(phone: str, role: str, user_msg: str,
                              bot_response: str, source: str = "claude") -> None:
    """Bir konuşma turu sonunda token tüketimini kaydet.

    source: 'claude' | 'ollama' | 'fast_response'
    fast_response çok az token (hook body) — sayılmaz veya 50 sayılır.
    """
    try:
        if source == "fast_response":
            tokens = 50  # minimal — sadece ölçüm için
        elif source == "ollama":
            tokens = _estimate_tokens(user_msg) + _estimate_tokens(bot_response)
        else:  # claude
            # System prompt + user + response → ~input 3000 + output (varies)
            tokens = 3000 + _estimate_tokens(user_msg) + _estimate_tokens(bot_response)
        await add_usage(phone, role, tokens, from_claude=(source == "claude"))
    except Exception as e:
        logger.debug(f"token_budget record_interaction hatasi: {e}")


async def exceeded_response(phone: str, role: str, name: str = "") -> str:
    """Limit aşıldığında gönderilecek nazik kapanış mesajı."""
    first = (name or "").split()[0] if name else ""
    usage = await get_today_usage(phone)
    msg_count = usage["msg_count"]

    return (
        f"*{first}*, bugün çok güzel bir sohbet oldu — {msg_count} mesaj kadar. 🙏\n\n"
        f"---\n\n"
        f"Birlikte verimli çalışmamız için günlük bir rutinim var: "
        f"bugünlük burada bir nokta koyalım, *yarın taze bir kafayla* devam edelim.\n\n"
        f"_Acil bir durum varsa öğretmenine veya Zeki Bey'e yazabilirsin._\n\n"
        f"---\n\n"
        f"_Yarın görüşmek üzere! Bu gece iyi dinlen, yarın daha iyi anlatırım._ 🎯"
    )


# ── Günlük temizlik/rapor ────────────────────────────────────────────────────

async def daily_report() -> str:
    """Tüm aktif kullanıcıların bugünkü token dağılımı."""
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            """
            SELECT phone, role, token_used, msg_count
            FROM fermat.token_budget_daily
            WHERE gun = CURRENT_DATE
            ORDER BY token_used DESC
            LIMIT 20
            """
        )
        if not rows:
            return "📊 Bugün token kullanımı yok"

        lines = ["📊 *Token Budget Raporu — Bugün*", "━━━━━━━━━━━━━━━━━━━━━"]
        toplam_token = 0
        toplam_msg = 0
        for r in rows:
            tok = r["token_used"] or 0
            cnt = r["msg_count"] or 0
            toplam_token += tok
            toplam_msg += cnt
            phone = (r["phone"] or "????")[-4:]
            role = r["role"] or "?"
            limit = role_limit(role)
            if limit:
                oran = round(tok / limit * 100, 0)
                bar = "🔴" if oran >= 90 else ("🟡" if oran >= 75 else "🟢")
                lines.append(f"  {bar} **{phone}** [{role}] — {tok:,} tok / {cnt} msg ({oran}%)")
            else:
                lines.append(f"  ⚪ **{phone}** [{role}] — {tok:,} tok / {cnt} msg (limitsiz)")

        lines.append("━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"*Toplam:* {toplam_token:,} token, {toplam_msg} mesaj, {len(rows)} kullanıcı")
        return "\n".join(lines)
    except Exception as e:
        return f"Rapor hatası: {e}"


if __name__ == "__main__":
    # Test
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    async def test():
        await ensure_schema()
        # Simüle
        phone = "_test_tokbud"
        for i in range(5):
            await add_usage(phone, "ogrenci", 3500)
        result = await check_budget(phone, "ogrenci")
        print(f"check_budget: {result}")
        print(f"\nDaily report:\n{await daily_report()}")
        # Temizle
        from db_pool import db_execute
        await db_execute("DELETE FROM fermat.token_budget_daily WHERE phone=$1", phone)

    asyncio.run(test())
