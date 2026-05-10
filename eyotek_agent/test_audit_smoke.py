"""Self-audit fix-loop smoke test runner.

Test plan:
1. AUDIT MODULE — import + basic API
2. AUDIT TABLE — DB tablosu hazır mı, log_audit çalışıyor mu
3. SCREENSHOT — Playwright ile gerçek ss alabiliyor mu
4. VISION — Claude Vision API yanıt veriyor mu (mock claim)
5. DRILL HOOK — sinav_drilldown ile e2e (APOTEMI TG TYT-3)
6. STUDENT DRILL HOOK — student_drilldown ile e2e
7. NAVIGATE HOOK — eyotek_query ile e2e
8. WRITE_ETUT HOOK — DRY_RUN değil + audit (gerçek yazılmaz, sadece import path test)

Çalıştır:
    /opt/fermatai/.venv/bin/python test_audit_smoke.py
    /opt/fermatai/.venv/bin/python test_audit_smoke.py --quick   # sadece 1-4
"""
from __future__ import annotations
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
env = Path(__file__).resolve().parent.parent / ".env"
if env.exists():
    load_dotenv(env)


# ─────────────────────────────────────────────────────────────────────────
TESTS = []
RESULTS = []


def test(name: str):
    """Decorator: register a test."""
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


def _color(t, ok):
    return f"\033[92m{t}\033[0m" if ok else f"\033[91m{t}\033[0m"


# ─── 1. MODULE IMPORT ─────────────────────────────────────────────
@test("1. eyotek_self_audit module import")
async def t1():
    from eyotek_self_audit import (
        take_audit_screenshot, verify_with_vision,
        audit_action, audit_drill_completeness,
        audit_write_etut, audit_write_counsellor,
        audit_student_drill, audit_navigate_query,
        init_audit_table, log_audit,
        cleanup_old_screenshots, AUDIT_ENABLED,
    )
    assert AUDIT_ENABLED is True or AUDIT_ENABLED is False
    return {"audit_enabled": AUDIT_ENABLED, "imported": 12}


# ─── 2. DB TABLE ──────────────────────────────────────────────────
@test("2. audit_log table init + sample log")
async def t2():
    from eyotek_self_audit import init_audit_table, log_audit
    ok = await init_audit_table()
    assert ok, "init_audit_table failed"
    # Sample insert (mock)
    log_id = await log_audit(
        action="smoke_test",
        claim="Test claim",
        screenshot=None,
        page_url=None,
        vision_result={"verdict": "TRUE", "confidence": 0.9,
                       "observation": "smoke test obs", "numbers": {"x": 1}},
        expected=10, actual=10,
        extra={"smoke": True},
    )
    assert log_id and log_id > 0, f"log_audit returned {log_id}"
    # Verify
    from db_pool import db_fetchrow
    row = await db_fetchrow("SELECT * FROM audit_log WHERE id = $1", log_id)
    assert row, "audit_log row not found"
    assert row.get("action") == "smoke_test"
    # Cleanup
    from db_pool import db_execute
    await db_execute("DELETE FROM audit_log WHERE id = $1", log_id)
    return {"init": ok, "log_id": log_id, "verified": True}


# ─── 3. SCREENSHOT ────────────────────────────────────────────────
@test("3. take_audit_screenshot (Eyotek live)")
async def t3():
    from playwright.async_api import async_playwright
    from eyotek_knowledge.eyotek_navigator import _navigator_browser, _BASE_URL
    from eyotek_self_audit import take_audit_screenshot
    pw = await async_playwright().start()
    browser, ctx, _ = await _navigator_browser(pw)
    page = await ctx.new_page()
    try:
        await page.goto(f"{_BASE_URL}Student/student", timeout=15000,
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        ss = await take_audit_screenshot(page, "smoke_test_3", "Test screenshot")
        assert ss.get("path"), f"ss path missing: {ss}"
        assert Path(ss["path"]).exists(), f"file not on disk: {ss['path']}"
        sz = Path(ss["path"]).stat().st_size
        assert sz > 1000, f"ss too small: {sz} bytes"
        # Cleanup
        Path(ss["path"]).unlink()
        return {"path": ss["path"], "size_kb": ss.get("size_kb")}
    finally:
        await page.close(); await ctx.close()
        await browser.close(); await pw.stop()


# ─── 4. VISION VERIFY (test image) ───────────────────────────────
@test("4. verify_with_vision (real ss)")
async def t4():
    from playwright.async_api import async_playwright
    from eyotek_knowledge.eyotek_navigator import _navigator_browser, _BASE_URL
    from eyotek_self_audit import take_audit_screenshot, verify_with_vision
    pw = await async_playwright().start()
    browser, ctx, _ = await _navigator_browser(pw)
    page = await ctx.new_page()
    try:
        await page.goto(f"{_BASE_URL}Student/student", timeout=15000,
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        ss = await take_audit_screenshot(page, "smoke_test_4_vision",
                                          "Vision API test")
        vision = await verify_with_vision(
            ss["path"],
            "Bu sayfa bir Eyotek LMS sayfası mı? Tablo, başlık, navigasyon menüsü görünüyor mu?"
        )
        assert vision.get("verdict"), f"vision verdict missing: {vision}"
        # Cleanup ss
        Path(ss["path"]).unlink()
        return {
            "verdict": vision.get("verdict"),
            "confidence": vision.get("confidence"),
            "observation_preview": (vision.get("observation") or "")[:60],
        }
    finally:
        await page.close(); await ctx.close()
        await browser.close(); await pw.stop()


# ─── 5. DRILL HOOK E2E ────────────────────────────────────────────
@test("5. sinav_drilldown audit hook (APOTEMI TG TYT-3)")
async def t5():
    from fermat_core_agent import _tool_sinav_sonuclari
    r = await _tool_sinav_sonuclari(
        "Apotemi TG TYT-3", max_rows=200, date_from_days=30, _caller_role="admin"
    )
    assert r.get("success"), f"drill failed: {r.get('error')}"
    audit = r.get("_audit")
    if not audit:
        # Completeness 0.85+ olabilir → audit tetiklenmemiş, bu OK
        return {"audit_skipped": True,
                "row_count": r.get("row_count"),
                "completeness": (r.get("data_completeness") or {}).get("ratio")}
    assert audit.get("audited"), f"audit fail: {audit}"
    v = audit.get("vision_result") or {}
    assert v.get("verdict") in ("TRUE", "FALSE", "KISMEN", "BELIRSIZ"), \
        f"verdict missing: {v}"
    return {
        "row_count": r.get("row_count"),
        "audited": True,
        "verdict": v.get("verdict"),
        "audit_log_id": audit.get("audit_log_id"),
    }


# ─── 6. STUDENT DRILL HOOK ────────────────────────────────────────
@test("6. student_drilldown audit hook (Mahmut Taha → etut)")
async def t6():
    from fermat_core_agent import _tool_ogrenci_drilldown
    # 4 satırdan az ise audit tetiklenir (varsayılan)
    r = await _tool_ogrenci_drilldown(
        student="Mahmut Taha", alt_sayfa="etut", max_rows=20,
        _caller_role="admin",
    )
    audit = r.get("_audit")
    return {
        "success": r.get("success"),
        "row_count": r.get("row_count"),
        "audited": bool(audit and audit.get("audited")),
        "verdict": (audit or {}).get("vision_result", {}).get("verdict"),
    }


# ─── 7. NAVIGATE (eyotek_query) HOOK ─────────────────────────────
@test("7. eyotek_query audit hook")
async def t7():
    from fermat_core_agent import _tool_eyotek_query
    # Boş tablo dönmeyi tetiklemek için garip filter (bilerek)
    r = await _tool_eyotek_query(
        page_path="Student/test-transferred",
        filters={"date_from": "01.01.2020", "date_to": "31.12.2020"},
        max_rows=10,
        _caller_role="admin",
    )
    audit = r.get("_audit")
    return {
        "success": r.get("success"),
        "row_count": r.get("row_count"),
        "error_code": r.get("error_code"),
        "audited": bool(audit and audit.get("audited")),
    }


# ─── 8. WRITE_ETUT (DRY_RUN, audit skip) ─────────────────────────
@test("8. write_etut DRY_RUN (audit skip — yazma yapılmıyor)")
async def t8():
    """DRY_RUN'da audit skip OLMALI (yazma yapılmadı)."""
    # eyotek_wrapper'ı doğrudan import etmek ağır — sadece import path test
    from eyotek_wrapper import EyotekClient
    # Sadece module-level import sınıf adı doğru mu kontrol — gerçek session yok
    return {"class_imported": EyotekClient.__name__, "skip_reason": "no_session"}


# ─── RUNNER ──────────────────────────────────────────────────────
async def run_all(quick=False):
    print("=" * 70)
    print("EYOTEK SELF-AUDIT SMOKE TESTS")
    print("=" * 70)

    selected = TESTS[:4] if quick else TESTS
    passed = 0
    failed = 0
    for name, fn in selected:
        print(f"\n[ {name} ]")
        try:
            res = await fn()
            print(_color("  ✓ PASS", True), "→", res)
            RESULTS.append({"name": name, "pass": True, "res": res})
            passed += 1
        except Exception as e:
            print(_color("  ✗ FAIL", False), "→", f"{type(e).__name__}: {str(e)[:200]}")
            import traceback
            traceback.print_exc(limit=3)
            RESULTS.append({"name": name, "pass": False, "err": str(e)[:300]})
            failed += 1

    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed} PASS, {failed} FAIL ({len(selected)} total)")
    print("=" * 70)
    return passed, failed


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    p, f = asyncio.run(run_all(quick=quick))
    sys.exit(0 if f == 0 else 1)
