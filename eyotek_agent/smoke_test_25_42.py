"""25.42 Smoke test — 7 bulgu fix dogrulama (VPS uzerinde calisir).

Calistirma:
    cd /opt/fermatai/eyotek_agent
    set -a && source .env && set +a
    /opt/fermatai/.venv/bin/python smoke_test_25_42.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def smoke_a_yayinevi():
    """Bulgu A — yayinevi katalog + handler."""
    from yayinevi_katalog import detect_publisher, extract_net
    cases = [
        ("0 pozitif", "Sifir Pozitif"),
        ("sifir pozitif yayinlari'na baz al", "Sifir Pozitif"),
        ("apotemide 70 net", "Apotemi"),
        ("3d tyt-3 80 net", "3D"),
        ("0 ne demek pozitif mi", None),  # math, false positive olmamali
    ]
    fails = 0
    for text, expected in cases:
        got = detect_publisher(text)
        if got != expected:
            print(f"  FAIL A: '{text}' got={got!r} expected={expected!r}")
            fails += 1
    if fails:
        print(f"  [FAIL] Bulgu A — {fails}/{len(cases)} test")
    else:
        print(f"  [OK]   Bulgu A — yayinevi {len(cases)}/{len(cases)} PASS")
    return fails == 0


async def smoke_f_test_registry():
    """Bulgu F — test_user_registry."""
    from test_user_registry import is_test_phone
    assert is_test_phone("905309356389") is True
    assert is_test_phone("905050952398") is False
    assert is_test_phone("") is False
    print("  [OK]   Bulgu F — test_user_registry")
    return True


async def smoke_cd_profile_fallback():
    """Bulgu C+D — _get_caller_profile fallback ASLA admin DEGIL."""
    try:
        from fermat_core_agent import _get_caller_profile
    except Exception as e:
        print(f"  [SKIP] Bulgu C+D — import fail: {e}")
        return False
    p = await _get_caller_profile("905999999999")  # kayitsiz numara
    if p.get("role") == "unknown" and p.get("is_verified") is False:
        print(f"  [OK]   Bulgu C+D — unknown profile guvenli (role={p['role']}, verified={p.get('is_verified')})")
        return True
    print(f"  [FAIL] Bulgu C+D — profile beklenen unknown+verified=False, got: {p}")
    return False


async def smoke_h_loop_guard():
    """Bulgu H — fast_response_loop_guard custom windows."""
    from fast_response_loop_guard import _CUSTOM_WINDOWS
    if _CUSTOM_WINDOWS.get("puan_tahmin") == 300:
        print(f"  [OK]   Bulgu H — puan_tahmin window 300s (Mehmet 3dk16sn arayla cevap")
        return True
    print(f"  [FAIL] Bulgu H — puan_tahmin window: {_CUSTOM_WINDOWS}")
    return False


async def smoke_pattern_compile():
    """OGRENCI_PATTERNS yayinevi pattern compile + match dogrulamasi."""
    from fast_responses import OGRENCI_PATTERNS
    import re
    pattern = None
    for p, h, _ in OGRENCI_PATTERNS:
        if h == "yayinevi_denemesi":
            pattern = p
            break
    if not pattern:
        print("  [FAIL] yayinevi_denemesi pattern OGRENCI_PATTERNS'da YOK")
        return False
    if not re.search(pattern, "0 pozitif"):
        print("  [FAIL] yayinevi pattern '0 pozitif' yakalamadi")
        return False
    print("  [OK]   OGRENCI_PATTERNS — yayinevi_denemesi yakalanir")
    return True


async def smoke_dispatch_handler():
    """Handler dispatch case eklendi mi?"""
    import importlib
    src = Path(__file__).parent / "fast_responses.py"
    text = src.read_text(encoding='utf-8')
    if 'handler == "yayinevi_denemesi"' in text:
        print("  [OK]   fast_responses dispatch — yayinevi_denemesi case mevcut")
        return True
    print("  [FAIL] dispatch case YOK")
    return False


async def smoke_db_column():
    """DB: routing_stats.is_test_user kolonu eklendi mi?"""
    from db_pool import db_fetchval
    val = await db_fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='fermat' AND table_name='routing_stats' AND column_name='is_test_user')"
    )
    if val:
        print("  [OK]   routing_stats.is_test_user kolonu mevcut")
        return True
    print("  [FAIL] is_test_user kolonu YOK")
    return False


async def smoke_db_view():
    """DB: real_user_routing_stats view test_user filtreli mi?"""
    from db_pool import db_fetchval
    # View tanimini al
    val = await db_fetchval(
        "SELECT pg_get_viewdef('fermat.real_user_routing_stats'::regclass, true)"
    )
    if val and ("is_test_user" in val.lower() or "is_test_user" in (val or "")):
        print("  [OK]   real_user_routing_stats view is_test_user filtresi var")
        return True
    print(f"  [FAIL] real_user_routing_stats view tanimi: {val[:200] if val else 'NULL'}...")
    return False


async def smoke_atlas_fixed():
    """Atlas #91/#92/#94 cozum kayitlari icin not bilgisi (fixle iliskili)."""
    from db_pool import db_fetch
    rows = await db_fetch(
        "SELECT id, status FROM atlas_suggestions WHERE id IN (91, 92, 94)"
    )
    out = {r["id"]: r["status"] for r in rows or []}
    print(f"  [INFO] Atlas durum: {out} (fix yapildi, status manual update gerekli)")
    return True


async def main():
    print("═══════════════════════════════════════════════")
    print("25.42 SMOKE TEST — 7 Bulgu Fix Dogrulama")
    print("═══════════════════════════════════════════════")

    results = []
    results.append(("A — Yayinevi katalog", await smoke_a_yayinevi()))
    results.append(("F — test_user_registry", await smoke_f_test_registry()))
    results.append(("C+D — Profile fallback (asla admin)", await smoke_cd_profile_fallback()))
    results.append(("H — Loop guard custom window", await smoke_h_loop_guard()))
    results.append(("Pattern compile OGRENCI", await smoke_pattern_compile()))
    results.append(("Dispatch case yayinevi", await smoke_dispatch_handler()))
    results.append(("DB column is_test_user", await smoke_db_column()))
    results.append(("DB view real_user", await smoke_db_view()))
    await smoke_atlas_fixed()

    print()
    pass_count = sum(1 for _, ok in results if ok)
    fail_count = len(results) - pass_count
    print(f"Toplam: {pass_count}/{len(results)} PASS, {fail_count} FAIL")
    return fail_count == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
