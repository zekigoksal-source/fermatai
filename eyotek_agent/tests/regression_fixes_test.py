"""
Oturum 21 Regression Test — 3 fix verify:
1. "program" pattern — çalışma planı Claude'a gidecek (Ecrin bug)
2. Talimat #75 — sıkılma sinyali → web daveti
3. Students status — 123 aktif
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


async def test_program_pattern():
    """Ecrin'in bug'ı: 'AYT fizik 2 haftalık program' → artık Claude'a gitmeli."""
    from fast_responses import try_fast_response

    print("\n═══ TEST 1: 'program' pattern ═══")
    test_cases = [
        ("Ayt fizik bana 2 haftalık program yapar mısın", False, "Çalışma planı — Claude'a gitmeli"),
        ("AYT fizik 2 haftalık program yap", False, "Çalışma planı — Claude'a"),
        ("Bana haftalık çalışma planı yap", False, "Çalışma planı — Claude'a"),
        ("ders programı ne", True, "Ders programı — fast_response OK"),
        ("bu hafta hangi derslerim var", True, "Ders programı — fast_response OK"),
    ]

    results = []
    for msg, should_fast, desc in test_cases:
        reply = await try_fast_response(
            message=msg, role="ogrenci", caller_phone="905055556389",
            name="Ecrin Beller", soz_no=271, staff_name=""
        )
        got_fast = reply is not None
        ok = got_fast == should_fast
        status = "✅" if ok else "❌"
        print(f"{status} {msg!r}")
        print(f"   Beklenen: {'FAST' if should_fast else 'CLAUDE'} | Gerçek: {'FAST' if got_fast else 'CLAUDE'}")
        if reply:
            print(f"   Fast yanıt (ilk 120c): {reply[:120]}")
        results.append(ok)

    return sum(results), len(results)


async def test_talimat_75_web_daveti():
    """Sıkılma sinyalleri → web daveti fast response."""
    from fast_responses import try_fast_response

    print("\n═══ TEST 2: Talimat #75 — sıkılma → web daveti ═══")
    test_cases = [
        ("chatgpt'ye gidiyom", True, "Rakip platform"),
        ("sıkıcı", True, "Saf sıkıcı"),
        ("boş konuşuyorsun", True, "Boş konuşma"),
        ("sen anlamıyorsun beni", True, "Anlamıyor"),
        ("Merhaba nasılsın", False, "Normal selam — tetiklememeli"),
    ]

    results = []
    for msg, should_trigger, desc in test_cases:
        reply = await try_fast_response(
            message=msg, role="ogrenci", caller_phone="905055556389",
            name="Ecrin Beller", soz_no=271, staff_name=""
        )
        triggered = reply is not None and "fermategitimkurumlari" in (reply or "")
        ok = triggered == should_trigger
        status = "✅" if ok else "❌"
        print(f"{status} {msg!r} → {desc}")
        if reply:
            print(f"   Yanıt (ilk 120c): {reply[:120]}")
        results.append(ok)

    return sum(results), len(results)


async def test_students_aktif():
    """Students tablosunda aktif sayı doğru mu?"""
    import asyncpg
    print("\n═══ TEST 3: Students status ═══")
    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'), min_size=1, max_size=2)
    rows = await pool.fetch("SELECT status, COUNT(*) FROM students GROUP BY status")
    status_counts = {r["status"]: r["count"] for r in rows}
    await pool.close()

    print(f"Aktif: {status_counts.get('active', 0)}")
    print(f"Inactive: {status_counts.get('inactive', 0)}")
    print(f"TOPLAM: {sum(status_counts.values())}")

    # Beklenen: 123 aktif, 2 inactive, 125 toplam
    active_ok = status_counts.get('active', 0) >= 120  # 120+ olmalı (Neo'nun dediği)
    total_ok = sum(status_counts.values()) >= 120

    if active_ok and total_ok:
        print("✅ GEÇTİ")
        return 1, 1
    else:
        print("❌ Aktif sayı 120'den az")
        return 0, 1


async def main():
    print("╔═══════════════════════════════════════════════╗")
    print("║ REGRESSION TEST — Oturum 21 Fix'leri          ║")
    print("╚═══════════════════════════════════════════════╝")

    t1_pass, t1_total = await test_program_pattern()
    t2_pass, t2_total = await test_talimat_75_web_daveti()
    t3_pass, t3_total = await test_students_aktif()

    print("\n" + "═" * 50)
    print("ÖZET:")
    print(f"  Test 1 (program pattern):    {t1_pass}/{t1_total}")
    print(f"  Test 2 (Talimat #75 web):    {t2_pass}/{t2_total}")
    print(f"  Test 3 (students aktif):     {t3_pass}/{t3_total}")
    total = t1_pass + t2_pass + t3_pass
    total_max = t1_total + t2_total + t3_total
    print(f"\nTOPLAM: {total}/{total_max}")
    return 0 if total == total_max else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
