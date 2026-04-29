"""Decision Trace Sorgu Aracı (Oturum 25.29)
================================================

Bug'ları 5 dakikada tespit etmek için CLI:
  python decision_trace_query.py --phone 905... --limit 10
  python decision_trace_query.py --route fast_pattern --since 1h
  python decision_trace_query.py --tool execute_eyotek_action --since 24h
  python decision_trace_query.py --signal "sentiment=alarm" --limit 5

Kullanım senaryosu:
  Mehmet: "üniversite sınavında kaç soru çıktı"
  Bot yanıltıcı cevap verdi.
  → python decision_trace_query.py --phone 905xxx --limit 1
  → görürsünüz: route=fast_pattern, handler_name=hedef, signals=[]
  → "context yok" → kök neden çözüldü
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")


def _parse_since(s: str) -> int:
    """'1h', '24h', '7d', '30m' → saniye."""
    s = s.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("d"):
        return int(s[:-1]) * 86400
    return int(s)  # raw seconds


async def query(args):
    from db_pool import db_fetch

    where = ["1=1"]
    params = []
    pn = 1

    if args.phone:
        where.append(f"phone = ${pn}")
        params.append(args.phone)
        pn += 1

    if args.role:
        where.append(f"role = ${pn}")
        params.append(args.role)
        pn += 1

    if args.route:
        where.append(f"decision_trace->>'route' = ${pn}")
        params.append(args.route)
        pn += 1

    if args.tool:
        where.append(f"${pn} = ANY(tools_called)")
        params.append(args.tool)
        pn += 1

    if args.signal:
        # signal: substring match in context_signals JSON array
        where.append(f"decision_trace::text LIKE ${pn}")
        params.append(f"%{args.signal}%")
        pn += 1

    if args.since:
        secs = _parse_since(args.since)
        where.append(
            f"created_at > NOW() - INTERVAL '{secs} seconds'"
        )

    sql = f"""
        SELECT id, created_at, phone, role, response_source, response_ms,
               handler_name, message,
               decision_trace, tools_called, prompt_blocks
        FROM routing_stats
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT {int(args.limit)}
    """

    rows = await db_fetch(sql, *params)

    if not rows:
        print("[no rows]")
        return

    print(f"=== {len(rows)} sonuç ===")
    print()

    for r in rows:
        print(f"#{r['id']}  {r['created_at'].strftime('%d.%m %H:%M:%S')}  "
              f"[{r['response_source'] or '?'}/{r['response_ms'] or 0}ms]")
        print(f"  phone={r['phone']}  role={r['role']}")
        print(f"  msg: {(r['message'] or '')[:120]}")
        if r["handler_name"]:
            print(f"  handler: {r['handler_name']}")
        trace = r["decision_trace"]
        if trace:
            try:
                # asyncpg returns JSONB as dict
                t = trace if isinstance(trace, dict) else json.loads(trace)
                print(f"  route: {t.get('route', '?')}")
                sig = t.get("context_signals") or []
                if sig:
                    print(f"  signals: {sig}")
            except Exception:
                print(f"  trace: {str(trace)[:120]}")
        if r["tools_called"]:
            print(f"  tools: {r['tools_called']}")
        if r["prompt_blocks"]:
            print(f"  blocks: {r['prompt_blocks']}")
        print()


def main():
    ap = argparse.ArgumentParser(description="Decision trace sorgu — son N karari incele")
    ap.add_argument("--phone", help="Telefon filtresi")
    ap.add_argument("--role", help="Rol filtresi (ogrenci/mudur/admin/...)")
    ap.add_argument("--route", help="Route filtresi (fast_pattern, claude_tool_loop, claude_text_only, ollama, groq, cerebras_*)")
    ap.add_argument("--tool", help="Tool ismi filtresi (tools_called array içinde)")
    ap.add_argument("--signal", help="Context signal substring (örn: 'sentiment=alarm', 'last_topic=fizik')")
    ap.add_argument("--since", default="24h", help="Zaman penceresi (örn: 30m, 1h, 24h, 7d)")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    asyncio.run(query(args))


if __name__ == "__main__":
    main()
