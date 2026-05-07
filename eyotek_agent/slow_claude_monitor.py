"""
Slow Claude Monitor (25.41 Neo — 7 May)
========================================

Son 24 saatte 60sn+ Claude yanıtı varsa rapor.

Çalışma: cron (saatte 1) → log_slow_responses tablosuna yaz +
gerekirse Neo'ya WP bildirim (kritik durumda).

Kullanım:
    python slow_claude_monitor.py            # Tara, rapor
    python slow_claude_monitor.py --notify   # Kritik durumda Neo'ya WP
"""
from __future__ import annotations
import asyncio
import sys
from db_pool import db_fetch, db_fetchval, db_execute


async def ensure_table():
    """Slow log tablosu (idempotent)."""
    await db_execute("""
        CREATE TABLE IF NOT EXISTS slow_response_log (
            id SERIAL PRIMARY KEY,
            taranan_at TIMESTAMP DEFAULT NOW(),
            slow_count INTEGER,
            total_count INTEGER,
            slow_pct NUMERIC(4,1),
            avg_ms INTEGER,
            max_ms INTEGER,
            notified BOOLEAN DEFAULT FALSE,
            details JSONB
        )
    """)


async def analyze_slow_claude(hours: int = 24) -> dict:
    """Son N saat Claude yanıtlarını tara.

    Returns:
        {slow_count, total_count, slow_pct, avg_ms, max_ms, top_slow}
    """
    rows = await db_fetch(f"""
        SELECT response_ms, message, phone, created_at::timestamp(0) tt
        FROM routing_stats
        WHERE created_at > NOW() - INTERVAL '{hours} hours'
          AND response_source = 'claude'
          AND response_ms IS NOT NULL AND response_ms > 0
        ORDER BY response_ms DESC LIMIT 100
    """)

    if not rows:
        return {
            "slow_count": 0, "total_count": 0,
            "slow_pct": 0, "avg_ms": 0, "max_ms": 0,
            "top_slow": [],
        }

    total_ms_arr = [r['response_ms'] for r in rows]
    slow_60 = [r for r in rows if r['response_ms'] > 60000]
    slow_120 = [r for r in rows if r['response_ms'] > 120000]

    return {
        "total_count": len(rows),
        "slow_60sn_count": len(slow_60),
        "slow_120sn_count": len(slow_120),
        "slow_60sn_pct": round(100 * len(slow_60) / len(rows), 1),
        "avg_ms": int(sum(total_ms_arr) / len(total_ms_arr)),
        "max_ms": max(total_ms_arr),
        "top_slow": [
            {"ms": r['response_ms'], "msg": (r['message'] or "")[:60], "tt": str(r['tt'])}
            for r in rows[:5]
        ],
    }


async def format_report(hours: int = 24) -> str:
    """İnsan dostu rapor."""
    data = await analyze_slow_claude(hours)
    if data["total_count"] == 0:
        return f"📊 Son {hours}h Claude yanıtı YOK."

    lines = [f"📊 *Claude Latency — Son {hours}h*\n"]
    lines.append(f"  Toplam: *{data['total_count']}* yanıt")
    lines.append(f"  Ort: *{data['avg_ms']/1000:.1f}sn* · Max: *{data['max_ms']/1000:.1f}sn*")
    lines.append(f"  >60sn: *{data['slow_60sn_count']}* (%{data['slow_60sn_pct']})")
    lines.append(f"  >120sn: *{data['slow_120sn_count']}*")

    if data['top_slow']:
        lines.append(f"\n🐢 *En yavaş 5:*")
        for s in data['top_slow']:
            lines.append(f"  {s['ms']/1000:.1f}sn — _{s['msg']}_")

    # Kritik mi?
    if data['slow_60sn_pct'] > 30:
        lines.append(f"\n⚠️ *KRITIK*: %{data['slow_60sn_pct']} yanıt 60sn üstü.")
        lines.append("Sebep: Claude tool-zinciri çok uzun olabilir.")
    elif data['slow_60sn_pct'] > 15:
        lines.append(f"\n🟡 *DİKKAT*: %{data['slow_60sn_pct']} yavaş yanıt.")

    return "\n".join(lines)


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    notify = "--notify" in sys.argv
    hours = 24
    if "--hours" in sys.argv:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])

    await ensure_table()
    data = await analyze_slow_claude(hours)
    rep = await format_report(hours)
    print(rep)

    # DB log
    await db_execute("""
        INSERT INTO slow_response_log
            (slow_count, total_count, slow_pct, avg_ms, max_ms, details)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
    """,
        data['slow_60sn_count'], data['total_count'],
        data['slow_60sn_pct'], data['avg_ms'], data['max_ms'],
        __import__('json').dumps(data['top_slow'])
    )

    # Neo'ya WP bildirim — sadece kritik durum (>30% slow)
    if notify and data['slow_60sn_pct'] > 30:
        try:
            from whatsapp_bridge import send_wa_message
            NEO_PHONE = "905051256802"
            await send_wa_message(NEO_PHONE, rep)
            print("\n[NEO] WP bildirimi gönderildi.")
        except Exception as e:
            print(f"[NEO] WP bildirim hata: {e}")


if __name__ == "__main__":
    asyncio.run(main())
