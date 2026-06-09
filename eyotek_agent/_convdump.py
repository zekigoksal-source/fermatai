"""Son 48h öğrenci konuşmaları — bağlam kopukluğu + alakasız deneme-sonucu dayatması analizi."""
import asyncio
import sys
sys.path.insert(0, "/opt/fermatai/eyotek_agent")
from dotenv import load_dotenv
load_dotenv("/opt/fermatai/.env", override=True)


async def main():
    from db_pool import db_fetch
    # En aktif kullanıcılar (48h)
    users = await db_fetch("""SELECT phone, COUNT(*) n FROM agent_conversations
        WHERE created_at > NOW() - INTERVAL '48 hours' AND message_role IN ('user','assistant')
        GROUP BY phone ORDER BY n DESC LIMIT 5""")
    for u in users:
        ph = u['phone']
        # öğrenci adı
        nm = await db_fetch("SELECT full_name FROM students WHERE phone=$1", ph)
        name = nm[0]['full_name'] if nm else ph[-4:]
        print("\n" + "=" * 70)
        print(f"### {name} (...{ph[-4:]}) — {u['n']} mesaj")
        print("=" * 70)
        msgs = await db_fetch("""SELECT message_role, content, created_at FROM agent_conversations
            WHERE phone=$1 AND message_role IN ('user','assistant') AND content NOT LIKE '[tool_%'
              AND created_at > NOW() - INTERVAL '48 hours'
            ORDER BY created_at ASC LIMIT 30""", ph)
        for m in msgs:
            who = "👤U" if m['message_role'] == 'user' else "🤖B"
            c = ' '.join((m['content'] or '').split())
            print(f"{who} [{str(m['created_at'])[11:16]}] {c[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
