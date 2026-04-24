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
        WHERE created_at > NOW() - INTERVAL '30 minutes'
          AND message_role IN ('user', 'assistant')
          AND content NOT LIKE '[tool_calls%'
          AND LENGTH(content) > 3
        ORDER BY phone, created_at ASC
    """)
    current = ''
    for r in rows:
        if r['phone'] != current:
            current = r['phone']
            tag = 'NEO' if current == '905051256802' else r['role']
            print(f"\n--- {tag} ...{current[-4:]} ---")
        prefix = 'USER' if r['message_role'] == 'user' else 'BOT '
        c = r['content'] or ''
        if prefix == 'BOT ' and len(c) > 800:
            c = c[:800] + '...[K]'
        ts = r['created_at'].strftime('%H:%M')
        print(f'  [{ts}] {prefix}: {c}')
    await conn.close()

asyncio.run(main())
