"""Live Eyotek auto-login test (VPS)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from eyotek_auto_login import try_auto_login, EYOTEK_USER, EYOTEK_PASS

    print(f"EYOTEK_USER: {EYOTEK_USER}")
    print(f"EYOTEK_PASS: {'***' if EYOTEK_PASS else 'EMPTY'}")

    if not (EYOTEK_USER and EYOTEK_PASS):
        print("[FAIL] Credentials yok")
        return False

    print("\nLogin denenıyor (30sn timeout)...")
    r = await try_auto_login(timeout_ms=30000, trigger_source="manual_smoke_25_43")

    print(f"\nSUCCESS:  {r.get('success')}")
    print(f"REASON:   {r.get('reason', '?')}")
    print(f"MESSAGE:  {r.get('message', '?')[:300]}")
    print(f"COOKIES:  {r.get('cookies_count', 0)}")
    print(f"CAPTCHA:  {r.get('captcha_detected', False)}")
    print(f"SOLVED:   {r.get('captcha_solved', False)}")
    return r.get("success", False)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
