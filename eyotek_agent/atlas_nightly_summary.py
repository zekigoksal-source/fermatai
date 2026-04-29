"""Atlas Nightly Özet (Oturum 25.29 — #4)
==========================================

Atlas observer + advisor sonrası çalışır:
  1. Son 24 saatin atlas_observations + atlas_suggestions çıktılarını JSON özetle
  2. Kritik (severity=critical) varsa admin'e WP bildirim (Neo)
  3. Stdout: JSON özet (cron log'a düşer)

Çağrılma: /opt/fermatai/.venv/bin/python atlas_nightly_summary.py
Crontab değil — vps_setup/scripts/atlas_nightly.sh içinden çağrılır.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from datetime import datetime

if os.name == "nt":
    sys.stdout.reconfigure(encoding="utf-8")


async def build_summary() -> dict:
    from db_pool import db_fetch, db_fetchval

    new_obs = await db_fetch("""
        SELECT category, severity, COUNT(*) AS n
        FROM atlas_observations
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY category, severity
        ORDER BY severity, n DESC
    """)

    new_sugs = await db_fetch("""
        SELECT category, severity, title
        FROM atlas_suggestions
        WHERE status = 'yeni'
          AND created_at > NOW() - INTERVAL '24 hours'
        ORDER BY CASE severity
                 WHEN 'critical' THEN 0
                 WHEN 'warning' THEN 1
                 ELSE 2 END
        LIMIT 10
    """)

    open_critical = await db_fetchval("""
        SELECT COUNT(*) FROM atlas_suggestions
        WHERE status = 'yeni' AND severity = 'critical'
    """) or 0

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "observations_24h": [
            {"category": r["category"], "severity": r["severity"], "count": int(r["n"])}
            for r in new_obs
        ],
        "new_suggestions_24h": [
            {"category": r["category"], "severity": r["severity"], "title": r["title"]}
            for r in new_sugs
        ],
        "open_critical_total": int(open_critical),
    }


async def notify_admin_if_critical(summary: dict) -> None:
    """Kritik var ise Neo'ya WP bildirim (sadece nightly + sıkı throttle)."""
    if summary["open_critical_total"] == 0 and not any(
        s["severity"] == "critical" for s in summary["new_suggestions_24h"]
    ):
        return

    # WP gönderim — secure_messenger varsa kullan
    try:
        from secure_messenger import send_wp_message
    except Exception:
        return

    NEO_PHONE = "905051256802"
    lines = [
        "🌙 *Atlas Gece Taraması* — kritik bulgular var",
        "",
    ]
    crit_sugs = [s for s in summary["new_suggestions_24h"] if s["severity"] == "critical"]
    if crit_sugs:
        lines.append(f"*Yeni 24h kritik öneri ({len(crit_sugs)}):*")
        for s in crit_sugs[:5]:
            lines.append(f"  🔴 [{s['category']}] {s['title'][:80]}")
        lines.append("")
    if summary["open_critical_total"] > 0:
        lines.append(f"*Açık kritik öneri toplam:* {summary['open_critical_total']}")
        lines.append("")
    lines.append("_'rapor' yazarak detaylı listeyi alabilirsin._")

    try:
        await send_wp_message(
            to=NEO_PHONE,
            message="\n".join(lines),
            reason="atlas_nightly_critical",
        )
    except Exception as e:
        print(f"[ATLAS-NIGHTLY] WP notify failed: {e}", file=sys.stderr)


async def main():
    summary = await build_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Sadece kritik varsa Neo'ya bildirim — gürültü yok
    await notify_admin_if_critical(summary)


if __name__ == "__main__":
    asyncio.run(main())
