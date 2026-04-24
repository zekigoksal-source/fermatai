"""
Tek Oturum Modeli Testi — yeni OTP eski session'ları kickler (WhatsApp Web mantığı).
Neo talebi 18 Nisan 2026.
"""
import asyncio
import sys
import os
import io
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)


async def test_tek_oturum():
    import asyncpg
    from web_chat_auth import verify_otp, get_session

    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'), min_size=1, max_size=2)
    # Ogrenci rolü (tek oturum aktif) — admin/mudur multi-device izinli (A12)
    phone = '905559999991'  # fake test phone

    print("═══ TEK OTURUM MODELİ TESTİ (ogrenci rolü) ═══\n")

    # Temizlik
    await pool.execute("DELETE FROM web_sessions WHERE phone=$1", phone)

    # Test OTP'leri manuel ekle
    await pool.execute(
        "INSERT INTO web_sessions (phone, full_name, role, otp_code, otp_created_at, otp_expires_at) "
        "VALUES ($1, $2, $3, $4, NOW(), NOW() + INTERVAL '15 minutes')",
        phone, 'Test Ogrenci', 'ogrenci', '111111'
    )
    await pool.execute(
        "INSERT INTO web_sessions (phone, full_name, role, otp_code, otp_created_at, otp_expires_at) "
        "VALUES ($1, $2, $3, $4, NOW(), NOW() + INTERVAL '15 minutes')",
        phone, 'Test Ogrenci', 'ogrenci', '222222'
    )

    # 1. giriş (PC)
    r1 = await verify_otp(phone, '111111', ip='10.0.0.1', user_agent='PC-Chrome')
    print(f"1. Giriş (PC):   success={r1['success']}, kicked_previous={r1.get('kicked_previous', 0)}")
    t1 = r1.get('token', '')

    await asyncio.sleep(0.5)

    # 2. giriş (iPad) — PC'yi kicklemeli
    r2 = await verify_otp(phone, '222222', ip='10.0.0.2', user_agent='iPad-Safari')
    print(f"2. Giriş (iPad): success={r2['success']}, kicked_previous={r2.get('kicked_previous', 0)}")
    t2 = r2.get('token', '')

    # Token geçerlilik kontrolü
    pc_sess = await get_session(t1)
    ipad_sess = await get_session(t2)

    print(f"\nPC token geçerli mi: {pc_sess is not None} (beklenen: False)")
    print(f"iPad token geçerli mi: {ipad_sess is not None} (beklenen: True)")

    # Temizlik
    await pool.execute("DELETE FROM web_sessions WHERE phone=$1", phone)
    await pool.close()

    passed = (pc_sess is None) and (ipad_sess is not None) and r2.get('kicked_previous', 0) >= 1
    if passed:
        print("\n✅ TEK OTURUM MODELİ ÇALIŞIYOR — PC kickiendi, iPad aktif")
        return 0
    else:
        print("\n❌ SORUN")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(test_tek_oturum()))
