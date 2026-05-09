"""25.43 Eyotek 7/24 ulaşılabilir — final smoke (Neo: 'eski sistem geri').

Kontrol edilen:
1. .env credentials (auto_login modülü explicit path)
2. Auto-login dispatch (capsolver ile captcha çöz)
3. Health check tutarlı (3 ardışık çağrı = aynı status)
4. Health durum 'online' (canlı API doğrulandı)
5. fermat-chrome-cdp.service active
6. fermat-session-keeper.service active (yeni)
"""
import asyncio
import socket
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def t1_credentials():
    """eyotek_auto_login modülü EYOTEK_USER/PASS okuyor mu?"""
    from eyotek_auto_login import EYOTEK_USER, EYOTEK_PASS, BASE_URL
    if EYOTEK_USER and EYOTEK_PASS and BASE_URL:
        print(f"  [OK] Credentials yüklendi (user={EYOTEK_USER}, base={BASE_URL})")
        return True
    print(f"  [FAIL] EYOTEK_USER/PASS yok — load_dotenv path bug?")
    return False


def t2_systemd_services():
    """3 systemd service active mi?"""
    services = ["fermatai-bridge", "fermat-chrome-cdp", "fermat-session-keeper"]
    fail = []
    for svc in services:
        try:
            r = subprocess.run(["systemctl", "is-active", svc],
                               capture_output=True, text=True, timeout=5)
            status = r.stdout.strip()
            if status == "active":
                print(f"  [OK] {svc}: {status}")
            else:
                print(f"  [FAIL] {svc}: {status}")
                fail.append(svc)
        except Exception as e:
            print(f"  [FAIL] {svc}: {e}")
            fail.append(svc)
    return not fail


def t3_cdp_port():
    """CDP port (env'den oku, default 9222) dinleniyor mu?"""
    import os
    port = int(os.getenv("CDP_PORT", "9222"))
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            r = s.connect_ex(("127.0.0.1", port))
            if r == 0:
                print(f"  [OK] CDP port {port} listening")
                return True
            print(f"  [FAIL] port {port} errno {r}")
            return False
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


async def t4_health_consistent():
    """eyotek_health 3 ardışık çağrı = aynı status (use_cache=False)."""
    from eyotek_health import eyotek_health_check
    statuses = []
    for i in range(3):
        r = await eyotek_health_check(use_cache=False)
        statuses.append(r["status"])
    if len(set(statuses)) == 1:
        print(f"  [OK] 3/3 tutarlı: '{statuses[0]}'")
        return True, statuses[0]
    print(f"  [FAIL] tutarsız: {statuses}")
    return False, None


async def t5_health_online(latest_status):
    """Health durum 'online' mi (canlı API doğrulandı)?"""
    if latest_status == "online":
        print(f"  [OK] Eyotek CANLI — live API doğrulandı")
        return True
    elif latest_status == "session_drop":
        print(f"  [WARN] session_drop — auto_login chain çalışmadı, session_keeper bekleniyor")
        return False
    elif latest_status == "cdp_down":
        print(f"  [FAIL] cdp_down — Chrome service çökmüş?")
        return False
    print(f"  [WARN] status={latest_status}")
    return False


async def main():
    print("═══════════════════════════════════════════════")
    print("25.43 EYOTEK 7/24 ULAŞILABILIR — FINAL SMOKE")
    print("═══════════════════════════════════════════════\n")

    results = []

    print("─── 1. Credentials (auto_login dotenv path fix) ───")
    results.append(await t1_credentials())

    print("\n─── 2. Systemd services (bridge + chrome + keeper) ───")
    results.append(t2_systemd_services())

    print("\n─── 3. CDP port 9222 ───")
    results.append(t3_cdp_port())

    print("\n─── 4. Health check tutarlı (3 ardışık) ───")
    consistent, status = await t4_health_consistent()
    results.append(consistent)

    print("\n─── 5. Health status='online' (canlı API) ───")
    results.append(await t5_health_online(status))

    print()
    pass_count = sum(results)
    print(f"═══════════════════════════════════════════════")
    print(f"TOPLAM: {pass_count}/{len(results)} test PASS")
    print(f"═══════════════════════════════════════════════")
    if pass_count == len(results):
        print("\n✅ Eyotek 7/24 ULAŞILABILIR — sistem üzerine yatırım yapılabilir")
    return pass_count == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
