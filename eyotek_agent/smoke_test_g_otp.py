"""Bulgu G — Web kodu rate-limit canli VPS testi."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from web_chat_auth import request_otp
    from db_pool import db_execute

    test_phone = "905999999991"

    # ACL test phone setup
    await db_execute(
        "INSERT INTO acl_users (phone, full_name, role, is_active) "
        "VALUES ($1, 'Test User', 'ogrenci', true) "
        "ON CONFLICT (phone) DO UPDATE SET is_active=true",
        test_phone,
    )
    # Eski OTP'leri temizle
    await db_execute(
        "UPDATE web_sessions SET otp_used_at=NOW() WHERE phone=$1 AND otp_used_at IS NULL",
        test_phone,
    )

    # 1. cagri
    r1 = await request_otp(test_phone)
    print(f"1. code={r1.get('code')} dup_guard={r1.get('_dup_guard', False)}")

    # 2. cagri (hemen, ayni kod beklenir)
    r2 = await request_otp(test_phone)
    print(f"2. code={r2.get('code')} dup_guard={r2.get('_dup_guard', False)}")

    # 3. cagri (1sn sonra)
    await asyncio.sleep(1)
    r3 = await request_otp(test_phone)
    print(f"3. code={r3.get('code')} dup_guard={r3.get('_dup_guard', False)}")

    print()
    print("Mesaj icerik (2.cagri):")
    print(r2.get("message", "")[:200])

    print()
    if r1.get("code") == r2.get("code") == r3.get("code"):
        print("[OK] 3 cagri AYNI kod (Mehmet 31sn bug fixed)")
    else:
        print(f"[FAIL] kodlar FARKLI: {r1.get('code')} {r2.get('code')} {r3.get('code')}")

    # cleanup
    await db_execute(
        "UPDATE web_sessions SET otp_used_at=NOW() WHERE phone=$1 AND otp_used_at IS NULL",
        test_phone,
    )


if __name__ == "__main__":
    asyncio.run(main())
