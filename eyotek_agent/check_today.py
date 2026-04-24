"""Bugünkü tüm kullanıcı konuşmalarını oku (admin hariç)."""
import asyncio, asyncpg, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv; load_dotenv()

async def main():
    conn = await asyncpg.connect(
        (os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL') or (_ for _ in ()).throw(RuntimeError('DATABASE_URL .env de tanimli degil')))
    )
    rows = await conn.fetch("""
        SELECT created_at, phone, role, message_role, content
        FROM agent_conversations
        WHERE created_at > NOW() - INTERVAL '24 hours'
          AND phone != '905051256802'
        ORDER BY phone, created_at ASC
    """)
    print(f'TOPLAM: {len(rows)} mesaj (son 24h, admin haric)')
    current_phone = ''
    for r in rows:
        if r['phone'] != current_phone:
            current_phone = r['phone']
            print(f"\n--- {r['role']} ...{r['phone'][-4:]} ---")
        prefix = 'USER' if r['message_role'] == 'user' else 'BOT '
        c = r['content'] or ''
        if prefix == 'BOT ' and len(c) > 500:
            c = c[:500] + '...[K]'
        ts = r['created_at'].strftime('%H:%M')
        print(f'  [{ts}] {prefix}: {c}')
    await conn.close()

asyncio.run(main())
