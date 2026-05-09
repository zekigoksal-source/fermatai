"""25.43-INT 7 fix smoke test (Neo konuşma analizi düzeltmeleri).

Fix #1: eyotek_health tool — port + cookie + live API tek doğruluk
Fix #2: system_prompt U-turn kuralı + Eyotek tek doğruluk
Fix #3: conversation_memory.get_recent_user_questions
Fix #4: HF Search local fallback
Fix #5: list_dir retry + diagnostics
Fix #6: read_file recursive=True
Fix #7: read_logs default 50 → 200
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def fix1_eyotek_health():
    """eyotek_health tool — TOOL_DISPATCH + tool_definitions + ACL."""
    from tool_definitions import TOOLS_ACTIVE
    from role_access import _ACL_MATRIX
    src = Path(__file__).parent / "fermat_core_agent.py"
    text = src.read_text(encoding='utf-8')

    checks = []
    # Tool definition
    checks.append(("TOOLS_ACTIVE", any(t.get("name") == "eyotek_health" for t in TOOLS_ACTIVE)))
    # Wrapper exists
    checks.append(("_tool_eyotek_health", "async def _tool_eyotek_health(" in text))
    # Dispatch entry
    checks.append(("TOOL_DISPATCH entry", '"eyotek_health":' in text))
    # ACL grant
    checks.append(("ACL admin/mudur", "eyotek_health" in _ACL_MATRIX["admin"]))
    # Module exists
    try:
        from eyotek_health import eyotek_health_check
        checks.append(("eyotek_health_check fn", True))
    except Exception:
        checks.append(("eyotek_health_check fn", False))

    fail = [n for n, ok in checks if not ok]
    if fail:
        print(f"  [FAIL] Fix #1 eksik: {fail}")
        return False
    print(f"  [OK] Fix #1 — eyotek_health tool tam entegre ({len(checks)}/5)")
    return True


def fix2_uturn_prompt():
    """system_prompt U-turn + Eyotek tek doğruluk kuralları."""
    text = Path(__file__).parent.joinpath("system_prompts.py").read_text(encoding='utf-8')
    checks = [
        ("Eyotek tek doğruluk başlığı", "EYOTEK BAGLANTI DURUMU" in text),
        ("eyotek_health tool çağrısı kuralı", "SADECE eyotek_health tool çağır" in text),
        ("U-turn kuralı başlığı", "U-TURN KURALI" in text),
        ("U-turn ack template", 'Az önce X demiştim, hatalıydı' in text),
        ("Bağlam koruma başlığı", "BAGLAM KORUMA" in text),
    ]
    fail = [n for n, ok in checks if not ok]
    if fail:
        print(f"  [FAIL] Fix #2 prompt eksik: {fail}")
        return False
    print(f"  [OK] Fix #2 — U-turn + Eyotek + Bağlam kuralları sistem prompt'ta")
    return True


async def fix3_recent_user_questions():
    """conversation_memory.get_recent_user_questions function exists."""
    from conversation_memory import get_recent_user_questions
    # DB query yapamayız local'de ama function importable mi?
    if callable(get_recent_user_questions):
        print(f"  [OK] Fix #3 — get_recent_user_questions importable")
        return True
    print(f"  [FAIL] Fix #3 fonksiyon yok")
    return False


async def fix4_hf_fallback():
    """HF Search local fallback test."""
    from external_apis_v3 import huggingface_search_models, _HF_FALLBACK_MODELS, _hf_local_search
    # Lokal arama çalışıyor mu?
    matches = _hf_local_search("turkish bert")
    if not matches:
        print(f"  [FAIL] Fix #4 lokal fallback 'turkish bert' eslesmedi")
        return False
    if matches[0]["id"] != "dbmdz/bert-base-turkish-cased":
        print(f"  [FAIL] Fix #4 yanlis sonuc: {matches[0]}")
        return False
    # Tag-based search
    matches2 = _hf_local_search("translation")
    if not matches2:
        print(f"  [FAIL] Fix #4 tag arama 'translation' eslesmedi")
        return False
    print(f"  [OK] Fix #4 — HF lokal fallback {len(_HF_FALLBACK_MODELS)} kategori, arama OK")
    return True


def fix5_list_dir_diagnostics():
    """list_dir retry + diagnostics field."""
    text = Path(__file__).parent.joinpath("self_dev_tools.py").read_text(encoding='utf-8')
    checks = [
        ("os.scandir RETRY", "os.scandir" in text or "_os.scandir" in text),
        ("_diagnostics field", '"_diagnostics"' in text),
        ("filtered_secret tracking", "filtered_secret" in text),
        ("25.43-INT-FIX5 tag", "25.43-INT-FIX5" in text),
    ]
    fail = [n for n, ok in checks if not ok]
    if fail:
        print(f"  [FAIL] Fix #5 list_dir eksik: {fail}")
        return False
    print(f"  [OK] Fix #5 — list_dir retry + diagnostics")
    return True


def fix6_read_file_recursive():
    """read_file recursive=True opsiyonu."""
    text = Path(__file__).parent.joinpath("self_dev_tools.py").read_text(encoding='utf-8')
    checks = [
        ("recursive parametre", "recursive: bool = False" in text),
        ("rglob arama", ".rglob(" in text),
        ("auto-retry recursive", 'recursive=True' in text),
        ("_resolved_via_recursive field", '"_resolved_via_recursive"' in text),
    ]
    fail = [n for n, ok in checks if not ok]
    if fail:
        print(f"  [FAIL] Fix #6 recursive eksik: {fail}")
        return False
    print(f"  [OK] Fix #6 — read_file recursive opsiyonu")
    return True


def fix7_read_logs_default():
    """read_logs default 50 → 200."""
    text = Path(__file__).parent.joinpath("self_dev_tools.py").read_text(encoding='utf-8')
    text2 = Path(__file__).parent.joinpath("fermat_core_agent.py").read_text(encoding='utf-8')
    checks = [
        ("self_dev_tools default 200", "lines: int = 200" in text),
        ("wrapper default 200", "lines: int = 200" in text2),
        ("MAX_LOG_LINES korundu", "MAX_LOG_LINES = 1000" in text),
    ]
    fail = [n for n, ok in checks if not ok]
    if fail:
        print(f"  [FAIL] Fix #7 default eksik: {fail}")
        return False
    print(f"  [OK] Fix #7 — read_logs default 50 → 200")
    return True


async def main():
    print("═══════════════════════════════════════════════")
    print("25.43-INT 7 FIX SMOKE TEST")
    print("═══════════════════════════════════════════════\n")

    results = []
    print("─── Fix #1: eyotek_health (Eyotek tek doğruluk) ───")
    results.append(await fix1_eyotek_health())
    print("\n─── Fix #2: system_prompt U-turn + bağlam koruma ───")
    results.append(fix2_uturn_prompt())
    print("\n─── Fix #3: conversation_memory recent_user_questions ───")
    results.append(await fix3_recent_user_questions())
    print("\n─── Fix #4: HF Search local fallback ───")
    results.append(await fix4_hf_fallback())
    print("\n─── Fix #5: list_dir retry + diagnostics ───")
    results.append(fix5_list_dir_diagnostics())
    print("\n─── Fix #6: read_file recursive ───")
    results.append(fix6_read_file_recursive())
    print("\n─── Fix #7: read_logs default 200 ───")
    results.append(fix7_read_logs_default())

    print()
    pass_count = sum(results)
    print(f"═══════════════════════════════════════════════")
    print(f"TOPLAM: {pass_count}/7 fix PASS")
    print(f"═══════════════════════════════════════════════")
    return pass_count == 7


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
