"""25.49 Neo bug — öğretmen/öğrenci isim normalize (double-space + trim).

Bot dedupe presentationally yapıyordu ama DB'de "ORHAN DEMİRBULAT" +
"ORHAN  DEMİRBULAT" iki ayrı kayıt olarak duruyor → JOIN'lerde + count'larda
sapma. Bu tek seferlik temizleyici.
"""
import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv('/opt/fermatai/.env', override=True)

NORMALIZE_TABLES = [
    # (tablo, kolon[])
    ('teacher_timetable', ['ogretmen_ad', 'brans', 'sinif', 'ders']),
    ('staff', ['first_name', 'last_name']),
    ('students', ['full_name']),
]


async def main():
    dsn = os.getenv('DATABASE_URL').replace('?sslmode=disable', '')
    conn = await asyncpg.connect(dsn)
    try:
        for table, cols in NORMALIZE_TABLES:
            for col in cols:
                exists = await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name=$1 AND column_name=$2", table, col)
                if not exists:
                    print(f'[SKIP] {table}.{col} kolon yok')
                    continue
                # Anomali var mı?
                anomaly_q = (
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE {col} ~ '  ' OR {col} <> TRIM({col})"
                )
                n = await conn.fetchval(anomaly_q)
                if not n:
                    print(f'[OK]   {table}.{col}: anomali yok')
                    continue
                # Sample
                sample = await conn.fetch(
                    f"SELECT DISTINCT {col} FROM {table} "
                    f"WHERE {col} ~ '  ' OR {col} <> TRIM({col}) LIMIT 5"
                )
                print(f'[FIX]  {table}.{col}: {n} anomali')
                for r in sample:
                    print(f'         >>{r[col]}<<')
                # Update: trim + collapse spaces
                # \s+ regex Python kontrol kaçışlama -> SQL string'inde \s+ olmalı,
                # asyncpg literal Python string → SQL'e tek slash gönder
                update_q = (
                    f"UPDATE {table} "
                    f"SET {col} = REGEXP_REPLACE(TRIM({col}), '\\s+', ' ', 'g') "
                    f"WHERE {col} ~ '  ' OR {col} <> TRIM({col})"
                )
                res = await conn.execute(update_q)
                print(f'         -> {res}')
    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
