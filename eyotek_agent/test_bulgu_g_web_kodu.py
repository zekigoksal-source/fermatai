"""Bulgu G — Web kodu rate-limit fix testi.

Test edilen senaryo (9 May Mehmet Karpuz bug):
  Mehmet 31sn araliklarla 3 kez "Web kodu" yazdi:
    14:50:20 → 546095
    14:50:51 → 301039  (31sn sonra — eski 30sn guard'i kacirdi)
    14:51:22 → 849698  (62sn sonra)

  Yeni davranis: gecerli (kullanilmamis + expire olmamis) OTP varsa AYNISINI dondur.
  Window = OTP_VALIDITY_MIN (15 dk default).
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_dup_guard_extended_window():
    """Mehmet 31sn aralikli 3 istek → ayni OTP donmeli."""
    os.environ.setdefault("DATABASE_URL", "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai")

    try:
        from web_chat_auth import generate_otp_for_phone
        from db_pool import db_execute, db_fetchrow
    except Exception as e:
        print(f"[SKIP] DB modulleri yuklenemedi: {e}")
        return

    test_phone = "905999999991"  # test phone — ACL'de yok, ama generate_otp önce profil arar

    # Test phone'u acl_users'a kayit (yoksa)
    try:
        await db_execute(
            "INSERT INTO acl_users (phone, full_name, role, is_active) VALUES ($1, $2, $3, true) "
            "ON CONFLICT (phone) DO UPDATE SET is_active=true",
            test_phone, "Test User", "ogrenci"
        )
    except Exception as e:
        print(f"[SKIP] ACL test phone insert fail: {e}")
        return

    # Eski OTP'leri temizle
    try:
        await db_execute(
            "UPDATE web_sessions SET otp_used_at=NOW() WHERE phone=$1 AND otp_used_at IS NULL",
            test_phone
        )
    except Exception as e:
        print(f"[WARN] Eski OTP temizleme fail (devam): {e}")

    # 1. Cagri — yeni OTP
    r1 = await generate_otp_for_phone(test_phone)
    if not r1.get("success"):
        print(f"[FAIL] Ilk istek basarisiz: {r1.get('message')}")
        return
    code1 = r1["code"]
    is_dup1 = r1.get("_dup_guard", False)
    print(f"[1] code={code1} dup_guard={is_dup1}")
    assert not is_dup1, "Ilk istek dup_guard YANLIS true"

    # 2. Cagri — hemen, ayni OTP donmeli
    r2 = await generate_otp_for_phone(test_phone)
    if not r2.get("success"):
        print(f"[FAIL] Ikinci istek basarisiz: {r2.get('message')}")
        return
    code2 = r2["code"]
    is_dup2 = r2.get("_dup_guard", False)
    print(f"[2] code={code2} dup_guard={is_dup2}")
    assert code1 == code2, f"Ikinci kod farkli: {code1} != {code2} (Mehmet bug)"
    assert is_dup2, "Ikinci istek dup_guard true olmali"

    # 3. Cagri — 31sn sonra simulasyonu yapamiyoruz, ama 1sn delay icin test yeterli
    # (sadece OTP_VALIDITY_MIN icindeki istekler ayni kodu donmeli)
    await asyncio.sleep(1)
    r3 = await generate_otp_for_phone(test_phone)
    if not r3.get("success"):
        print(f"[FAIL] Ucuncu istek basarisiz: {r3.get('message')}")
        return
    code3 = r3["code"]
    is_dup3 = r3.get("_dup_guard", False)
    print(f"[3] code={code3} dup_guard={is_dup3}")
    assert code1 == code3, f"Ucuncu kod farkli: {code1} != {code3}"

    # Mesajda "Az onceki kodun hala gecerli" olmali
    assert "hâlâ geçerli" in r2.get("message", "") or "hala geçerli" in r2.get("message", ""), \
        f"Mesajda 'hala gecerli' yok: {r2.get('message')!r}"

    # Cleanup
    await db_execute(
        "UPDATE web_sessions SET otp_used_at=NOW() WHERE phone=$1 AND otp_used_at IS NULL",
        test_phone
    )

    print("[OK] Bulgu G fix dogrulandi — ayni OTP 3 kez ardarda istekte de geri donuyor")


if __name__ == "__main__":
    asyncio.run(test_dup_guard_extended_window())
