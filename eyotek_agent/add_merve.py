"""Merve Oksas biyoloji ogretmeni telefon ekleme — one-off."""
import asyncio
import asyncpg
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv(override=True)


async def main():
    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'), min_size=1, max_size=2)

    # staff tablosuna phone kolonu var mi?
    cols = await pool.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name='staff'"
    )
    col_names = [c['column_name'] for c in cols]

    if 'phone' not in col_names:
        print('[+] staff.phone kolonu ekleniyor')
        await pool.execute("ALTER TABLE staff ADD COLUMN phone TEXT")
    else:
        print('[i] staff.phone kolonu zaten var')

    # Merve Oksas ara
    merve = await pool.fetchrow(
        "SELECT eyotek_id, full_name, brans, phone FROM staff "
        "WHERE full_name ILIKE '%MERVE%OK%'"
    )
    print(f'Mevcut Merve: {dict(merve) if merve else "staff tablosunda YOK"}')

    phone_norm = '905422898930'  # 05422898930 → 905422898930

    if merve:
        await pool.execute(
            'UPDATE staff SET phone=$1 WHERE eyotek_id=$2',
            phone_norm, merve['eyotek_id']
        )
        print(f'[+] Staff guncellendi: {merve["full_name"]} phone={phone_norm}')
    else:
        print('[!] Merve staff tablosunda yok — eklenmedi. Manuel import gerekli.')

    # ACL users kontrol/ekle
    existing = await pool.fetchrow(
        'SELECT phone, full_name, role FROM acl_users WHERE phone = $1',
        phone_norm
    )
    if existing:
        print(f'[i] ACL zaten var: {dict(existing)}')
        # Role ogretmen degilse duzelt
        if existing['role'] != 'ogretmen':
            await pool.execute(
                "UPDATE acl_users SET role='ogretmen', is_active=true WHERE phone=$1",
                phone_norm
            )
            print('[+] Role ogretmen yapildi')
    else:
        await pool.execute(
            "INSERT INTO acl_users (phone, full_name, role, is_active) "
            "VALUES ($1, $2, 'ogretmen', true)",
            phone_norm, 'Merve Okşaş'
        )
        print(f'[+] ACL eklendi: Merve Okşaş (ogretmen, {phone_norm})')

    final = await pool.fetchrow(
        'SELECT phone, full_name, role, is_active FROM acl_users WHERE phone = $1',
        phone_norm
    )
    print(f'[OK] Final ACL: {dict(final)}')

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
