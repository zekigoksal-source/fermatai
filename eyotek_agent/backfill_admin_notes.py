"""
Tek seferlik backfill: 13 Nisan 23:30 sonrası kayıp Neo "not et" komutlarını user_feedback'e geri ekle.

Sebep: fast_responses.py:2181'de admin için bypass vardı (return None → Claude → DB'ye yazma yok).
14-16 Nisan'da Neo'nun verdiği 8-10 talimat kayboldu. Bu script onları geri kazandırır.
"""
import asyncio
import asyncpg
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv()


async def main():
    conn = await asyncpg.connect(
        (os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL') or (_ for _ in ()).throw(RuntimeError('DATABASE_URL .env de tanimli degil')))
    )
    rows = await conn.fetch("""
        SELECT created_at, content
        FROM agent_conversations
        WHERE phone='905051256802'
          AND message_role='user'
          AND created_at > '2026-04-13 23:31:00'
          AND (LOWER(content) LIKE '%not et%' OR LOWER(content) LIKE '%kayda al%')
        ORDER BY created_at ASC
    """)
    print(f'Kayit edilmemis {len(rows)} admin notu:')
    print()
    inserted = 0
    skipped = 0
    for r in rows:
        existing = await conn.fetchval(
            """
            SELECT id FROM user_feedback
            WHERE phone='905051256802'
              AND created_at BETWEEN ($1::timestamp - INTERVAL '10 seconds') AND ($1::timestamp + INTERVAL '10 seconds')
              AND feedback = $2
            """,
            r['created_at'], r['content'],
        )
        if existing:
            print(f"  [ATLA - zaten var #{existing}] {r['content'][:60]}")
            skipped += 1
            continue
        msg_lower = r['content'].lower()
        is_teknik = any(w in msg_lower for w in [
            'hata', 'bug', 'sorun', 'calismıyor', 'çalışmıyor', 'aksama', 'problem',
            'yanlış', 'yanlis', 'halusinasyon', 'halüsinasyon', 'bos', 'boş',
            'saçma', 'sacma', 'yarım', 'yarim', 'düzelt', 'duzelt'
        ])
        cat = 'talimat_teknik' if is_teknik else 'talimat_genel'
        new_id = await conn.fetchval(
            """
            INSERT INTO user_feedback (phone, role, full_name, feedback, category, status, created_at)
            VALUES ('905051256802', 'admin', 'Zeki Goksal', $1, $2, 'islendi', $3)
            RETURNING id
            """,
            r['content'], cat, r['created_at'],
        )
        inserted += 1
        print(f"  [#{new_id} kaydedildi {r['created_at'].strftime('%m-%d %H:%M')}] {r['content'][:70]}")

    print()
    print(f'TOPLAM EKLENEN: {inserted} not (atlandi: {skipped})')
    total = await conn.fetchval('SELECT COUNT(*) FROM user_feedback')
    admin = await conn.fetchval(
        "SELECT COUNT(*) FROM user_feedback WHERE phone='905051256802'"
    )
    print(f'Yeni toplamlar — Genel: {total} | Admin: {admin}')
    await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
