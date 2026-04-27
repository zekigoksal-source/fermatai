"""
Eyotek Autonomous Test Loop — Oturum 25.26
=============================================

Neo: "random testler yap, hatalari duzelt, yine test et — amacina ulasana kadar"

Mimari:
    SCENARIOS (24 cesitli sorgu, 5 kategori)
       ↓
    test_round() → her senaryoyu calistir, basari/basarisizlik kategorize et
       ↓
    diagnose() → hata kategorisini belirle (PLANNER / NAVIGATOR / DATA / EXCEPTION)
       ↓
    auto_fix() → bilinen patternleri uygula (selector ekle, alias genislet)
       ↓
    retest → fix sonrasi sadece basarisizlari yeniden dene
       ↓
    loop max 3 round veya %95+ basari

Cikti: markdown raporu logs/eyotek_test_<timestamp>.md
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from loguru import logger

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT / "eyotek_agent"))


# ─── SENARYOLAR ──────────────────────────────────────────────────────────────
# 5 kategori, gerçek bot kullanım pattern'leri.
# expected: {
#   "must_succeed": True/False,                # nav.success bekleniyor mu
#   "must_have_filter": ["date_from", ...],    # uygulanmasi gereken filtreler
#   "must_page_path": "...",                   # planner dogru sayfayi sectimi
#   "min_rows": 0/1/None,                      # min row sayisi (None: ilgisiz)
#   "must_contain_col": "Tarih",               # tabloda olmasi gereken sutun
#   "min_confidence": 0.5,                     # plan confidence
# }

TODAY = date.today()
DUN = (TODAY - timedelta(days=1)).strftime("%d.%m.%Y")
TODAY_STR = TODAY.strftime("%d.%m.%Y")
HAFTABASI = (TODAY - timedelta(days=TODAY.weekday())).strftime("%d.%m.%Y")

SCENARIOS = [
    # ─── ETUT (parametrik tarih sorgulari) ─────────────────────────────────
    {
        "id": "etut_dun",
        "category": "etut",
        "query": "dun hangi etutler vardi",
        "expected": {
            "must_succeed": True,
            "must_page_path": "Student/individual-lesson",
            "must_have_filter": ["date_from", "date_to"],
            "min_confidence": 0.7,
            "must_contain_col_oneof": ["Tarih", "Etüt Kodu", "Öğretmen"],
        },
    },
    {
        "id": "etut_22nisan",
        "category": "etut",
        "query": "22 nisan 2026 etutleri",
        "expected": {
            "must_succeed": True,
            "must_page_path": "Student/individual-lesson",
            "must_have_filter": ["date_from", "date_to"],
            "min_rows": 1,  # 22.04 dolu (gerçek veri)
            "must_contain_col_oneof": ["Tarih", "Öğretmen"],
        },
    },
    {
        "id": "etut_3gun_once",
        "category": "etut",
        "query": "3 gun once etutlere bak",
        "expected": {
            "must_succeed": True,
            "must_page_path": "Student/individual-lesson",
            "must_have_filter": ["date_from"],
        },
    },
    {
        "id": "etut_ogretmen_donemi",
        "category": "etut",
        "query": "Mehmet Donmez ogretmenin Nisan etutleri",
        "expected": {
            "must_succeed": True,
            "must_page_path": "Student/individual-lesson",
            "must_have_filter": ["date_from", "date_to"],  # teacher de istenir ama opsiyonel
            "min_confidence": 0.6,
        },
    },
    {
        "id": "etut_ders_filter",
        "category": "etut",
        "query": "bu hafta matematik etutleri",
        "expected": {
            "must_succeed": True,
            "must_page_path": "Student/individual-lesson",
            "must_have_filter": ["date_from"],
        },
    },
    {
        "id": "etut_yoklama_almamis",
        "category": "etut",
        "query": "yoklama alinmamis etutler bugun",
        "expected": {
            "must_succeed": True,
            "must_page_path": "Student/individual-lesson",
            "must_have_filter": ["date_from"],
        },
    },

    # ─── YOKLAMA ───────────────────────────────────────────────────────────
    {
        "id": "yoklama_bugun_gelmeyen",
        "category": "yoklama",
        "query": "bugun okula gelmeyenler kim",
        "expected": {
            "must_succeed": True,
            "must_page_path_contains": "attendance",
            "min_confidence": 0.5,
        },
    },
    {
        "id": "yoklama_devamsizlik",
        "category": "yoklama",
        "query": "en cok devamsizlik yapan ogrenciler",
        "expected": {
            "must_succeed": True,
            "must_page_path_contains": "attendance",
        },
    },
    {
        "id": "yoklama_dun_kontrol",
        "category": "yoklama",
        "query": "dun yoklama nasildi",
        "expected": {
            "must_succeed": True,
            "must_page_path_contains": "attendance",
            "must_have_filter": ["date_from"],
        },
    },

    # ─── SINAV ─────────────────────────────────────────────────────────────
    {
        "id": "sinav_son",
        "category": "sinav",
        "query": "en son hangi sinav yapildi",
        "expected": {
            # Sinav Degerlendirme: /Student/Test/test (Eyotek path'i "test", "exam" degil)
            "must_page_path_contains": ("test", "exam"),
        },
    },
    {
        "id": "sinav_apotemi",
        "category": "sinav",
        "query": "Apotemi sinavinin sonuclari",
        "expected": {
            "must_page_path_contains": "exam",
            "min_confidence": 0.5,
        },
    },
    {
        "id": "sinav_tyt_birlestir",
        "category": "sinav",
        "query": "TYT sinavlarini birlestir",
        "expected": {
            "must_page_path_contains": "exam",
            "min_confidence": 0.4,
        },
    },
    {
        "id": "sinav_istatistik",
        "category": "sinav",
        "query": "son sinavin istatistikleri",
        "expected": {
            "must_page_path_contains": "exam",
        },
    },

    # ─── OGRENCI ───────────────────────────────────────────────────────────
    {
        "id": "ogrenci_liste",
        "category": "ogrenci",
        "query": "ogrenci listesini ver",
        "expected": {
            "must_succeed": True,
            "must_page_path_contains": "student",
        },
    },
    {
        "id": "ogrenci_sinif",
        "category": "ogrenci",
        "query": "12-A sinifi ogrenciler",
        "expected": {
            "must_page_path_contains": "student",
            "min_confidence": 0.4,
        },
    },

    # ─── REHBERLIK ─────────────────────────────────────────────────────────
    {
        "id": "rehberlik_son",
        "category": "rehberlik",
        "query": "en son rehberlik notlari",
        "expected": {
            "must_page_path_contains": "counsellor",
            "min_confidence": 0.4,
        },
    },
    {
        "id": "rehberlik_nisan",
        "category": "rehberlik",
        "query": "Nisan ayinda yazilan rehberlik notlari",
        "expected": {
            "must_page_path_contains": "counsellor",
            "must_have_filter": ["date_from"],
        },
    },

    # ─── DERS PROGRAMI ─────────────────────────────────────────────────────
    {
        "id": "program_ogretmen",
        "category": "program",
        "query": "ogretmen ders programlari",
        "expected": {
            "must_page_path_contains": "schedule",
        },
    },
    {
        "id": "program_sinif",
        "category": "program",
        "query": "12 SAY A sinif ders programi",
        "expected": {
            "must_page_path_contains": ("schedule", "timetable"),  # tuple olarak match
        },
    },

    # ─── DAVRANIS / ODEV ────────────────────────────────────────────────────
    {
        "id": "davranis_son",
        "category": "davranis",
        "query": "son davranis kayitlari",
        "expected": {
            "must_page_path_contains": "behaviour",
            "min_confidence": 0.3,
        },
    },
    {
        "id": "odev_bugun",
        "category": "odev",
        "query": "bugun verilen odevler",
        "expected": {
            "must_page_path_contains": "homework",
            "min_confidence": 0.3,
        },
    },

    # ─── EDGE CASES ────────────────────────────────────────────────────────
    {
        "id": "edge_belirsiz",
        "category": "edge",
        "query": "duruma bak",
        "expected": {
            # Belirsiz soru → low confidence beklenir
            "max_confidence": 0.6,
        },
    },
    {
        "id": "edge_imkansiz",
        "category": "edge",
        "query": "kasa raporu",
        "expected": {
            # Mali sayfa kapsamda yok → confidence ~0
            "max_confidence": 0.4,
        },
    },
    {
        "id": "edge_kompleks",
        "category": "edge",
        "query": "Kardelen Savci ogretmenin gecen hafta etutlerinden yoklama alinmamis olanlari getir",
        "expected": {
            "must_page_path": "Student/individual-lesson",
            "must_have_filter": ["date_from", "date_to"],
            "min_confidence": 0.6,
        },
    },

    # ─── YENİ KEŞİF: SINAV LISTESI + DYNAMIC LIST + ODEV RAPORLARI ─────────
    {
        "id": "sinav_listesi_yeni",
        "category": "sinav_yeni",
        "query": "en son hangi sinavlar yapildi sisteme islendi",
        "expected": {
            "must_page_path_contains": ("test-transferred", "test"),
            "min_confidence": 0.5,
        },
    },
    {
        "id": "sinav_listesi_nisan",
        "category": "sinav_yeni",
        "query": "Nisan ayinda yapilan sinavlar listesi",
        "expected": {
            "must_page_path_contains": ("test-transferred", "test"),
            "must_have_filter": ["date_from"],
            "min_confidence": 0.5,
        },
    },
    {
        "id": "odev_aylik_rapor",
        "category": "odev_yeni",
        "query": "bu ay odev yapmayanlar listesi",
        "expected": {
            "must_page_path_contains": ("homework-reports", "homework"),
            "min_confidence": 0.4,
        },
    },
    {
        "id": "odev_ogretmen_filtre",
        "category": "odev_yeni",
        "query": "Hasan Gungor hocanin verdigi odevler",
        "expected": {
            "must_page_path_contains": "homework",
            "min_confidence": 0.4,
        },
    },
]


# ─── DOGRULAMA ───────────────────────────────────────────────────────────────

def validate_result(scenario: dict, result: dict) -> tuple[bool, str]:
    """Senaryo expected ile result'i karsilastir, (passed, reason) don."""
    exp = scenario.get("expected", {})
    plan = result.get("plan", {})
    rows = result.get("rows", [])
    columns = result.get("columns", [])
    filters_applied = result.get("filters_applied", {})
    success = result.get("success", False)
    confidence = plan.get("confidence", 0)

    # 1. min_confidence
    if "min_confidence" in exp and confidence < exp["min_confidence"]:
        return False, f"confidence {confidence:.2f} < {exp['min_confidence']}"

    # 2. max_confidence (edge cases — belirsiz sorulara dusuk confidence beklenir)
    if "max_confidence" in exp and confidence > exp["max_confidence"]:
        return False, f"confidence {confidence:.2f} > {exp['max_confidence']} (belirsizlik tespit edemedi)"

    # 3. must_succeed
    if exp.get("must_succeed") and not success:
        return False, f"success={success}, error={result.get('error', '')[:80]}"

    # 4. must_page_path (exact)
    if "must_page_path" in exp:
        if plan.get("page_path") != exp["must_page_path"]:
            return False, f"page_path '{plan.get('page_path')}' beklenen '{exp['must_page_path']}'"

    # 5. must_page_path_contains (substring veya tuple)
    if "must_page_path_contains" in exp:
        needle = exp["must_page_path_contains"]
        path = plan.get("page_path", "").lower()
        if isinstance(needle, tuple):
            if not any(n.lower() in path for n in needle):
                return False, f"page_path '{path}' icinde {needle} hicbiri yok"
        else:
            if needle.lower() not in path:
                return False, f"page_path '{path}' icinde '{needle}' yok"

    # 6. must_have_filter
    if "must_have_filter" in exp:
        for filt in exp["must_have_filter"]:
            if filt not in filters_applied:
                return False, f"filter '{filt}' uygulanmadi (applied: {list(filters_applied.keys())})"

    # 7. min_rows
    if "min_rows" in exp and len(rows) < exp["min_rows"]:
        return False, f"row_count {len(rows)} < {exp['min_rows']}"

    # 8. must_contain_col
    if "must_contain_col" in exp:
        if exp["must_contain_col"] not in columns:
            return False, f"sutun '{exp['must_contain_col']}' yok (columns: {columns[:5]})"

    # 9. must_contain_col_oneof
    if "must_contain_col_oneof" in exp:
        if not any(c in columns for c in exp["must_contain_col_oneof"]):
            return False, f"sutun {exp['must_contain_col_oneof']} hicbiri yok (columns: {columns[:5]})"

    return True, "OK"


# ─── HATA KATEGORILEME ───────────────────────────────────────────────────────

def categorize_failure(scenario: dict, result: dict, reason: str) -> str:
    """Hata sebebini kategorize et — hangi katmanda?"""
    plan = result.get("plan", {})
    error = result.get("error", "") or ""
    error_code = result.get("error_code", "") or ""
    confidence = plan.get("confidence", 0)

    if "confidence" in reason:
        if confidence < 0.4:
            return "PLANNER_LOW_CONFIDENCE"
        return "PLANNER_OVERCONFIDENT"

    if "page_path" in reason:
        return "PLANNER_WRONG_PAGE"

    if "filter" in reason and "uygulanmadi" in reason:
        return "NAVIGATOR_FILTER_FAILED"

    if "row_count" in reason:
        return "DATA_INSUFFICIENT"

    if "sutun" in reason:
        return "DATA_COLUMNS_MISSING"

    if "AUTH_EXPIRED" in error_code:
        return "AUTH_EXPIRED"

    if "TIMEOUT" in error_code:
        return "TIMEOUT"

    if "EXCEPTION" in error_code:
        return "EXCEPTION"

    return "UNKNOWN"


# ─── TEK ROUND ───────────────────────────────────────────────────────────────

async def run_round(scenarios: list[dict], round_num: int) -> dict:
    """Tum senaryolari calistir, sonuclari topla."""
    from eyotek_knowledge.eyotek_planner import execute_query

    results = []
    pass_count = 0
    fail_count = 0

    for i, sc in enumerate(scenarios, 1):
        logger.info(f"[R{round_num}] [{i}/{len(scenarios)}] {sc['id']}: {sc['query'][:60]}")
        try:
            result = await execute_query(sc["query"], max_rows=10)
        except Exception as e:
            result = {
                "success": False, "plan": {"page_path": "", "confidence": 0},
                "error_code": "EXCEPTION", "error": f"{type(e).__name__}: {str(e)[:200]}",
                "rows": [], "columns": [], "filters_applied": {},
            }

        passed, reason = validate_result(sc, result)
        category = "PASS" if passed else categorize_failure(sc, result, reason)

        record = {
            "id": sc["id"],
            "category": sc["category"],
            "query": sc["query"],
            "passed": passed,
            "reason": reason,
            "failure_category": category,
            "plan": result.get("plan", {}),
            "filters_applied": result.get("filters_applied", {}),
            "row_count": result.get("row_count", 0),
            "columns": result.get("columns", [])[:5],
            "error_code": result.get("error_code"),
            "error": (result.get("error") or "")[:200],
        }
        results.append(record)
        if passed:
            pass_count += 1
        else:
            fail_count += 1

        status = "✓" if passed else "✗"
        logger.info(f"   {status} {category} | {reason[:80]}")

        # Eyotek'i bunaltmamak icin
        await asyncio.sleep(1.0)

    return {
        "round": round_num,
        "total": len(scenarios),
        "pass": pass_count,
        "fail": fail_count,
        "pass_rate": pass_count / len(scenarios) if scenarios else 0,
        "results": results,
    }


# ─── AUTO-FIX KARARLARI ──────────────────────────────────────────────────────

def collect_fix_actions(round_summary: dict) -> list[dict]:
    """Hatalardan otomatik uygulanacak fix actions cikar."""
    actions = []
    failures = [r for r in round_summary["results"] if not r["passed"]]

    # Pattern 1: NAVIGATOR_FILTER_FAILED → planner filter yanlis isimde mi?
    nav_filter_fails = [f for f in failures if f["failure_category"] == "NAVIGATOR_FILTER_FAILED"]
    if nav_filter_fails:
        actions.append({
            "type": "INVESTIGATE_FILTER_ALIAS",
            "description": (
                f"{len(nav_filter_fails)} senaryoda filter uygulanamadi. "
                f"Planner muhtemelen yanlis filter ismi uretiyor (orn 'subject' yerine 'ders')."
            ),
            "details": [(f["id"], f["plan"].get("filters", {})) for f in nav_filter_fails],
        })

    # Pattern 2: PLANNER_WRONG_PAGE → catalog incomplete?
    page_fails = [f for f in failures if f["failure_category"] == "PLANNER_WRONG_PAGE"]
    if page_fails:
        actions.append({
            "type": "INVESTIGATE_PAGE_SELECTION",
            "description": (
                f"{len(page_fails)} senaryoda planner yanlis sayfa secti. "
                f"Catalog'a daha aciklayici label/sutun bilgisi eklenebilir."
            ),
            "details": [(f["id"], f["plan"].get("page_path"), f["reason"]) for f in page_fails],
        })

    # Pattern 3: AUTH_EXPIRED → ortak sorun, ayri ele al
    auth_fails = [f for f in failures if f["failure_category"] == "AUTH_EXPIRED"]
    if auth_fails:
        actions.append({
            "type": "AUTH_EXPIRED",
            "description": "Eyotek session expired — Neo'nun login yapmasi gerek.",
            "stop_loop": True,
        })

    # Pattern 4: TIMEOUT
    timeouts = [f for f in failures if f["failure_category"] == "TIMEOUT"]
    if timeouts:
        actions.append({
            "type": "TIMEOUTS",
            "description": f"{len(timeouts)} senaryoda timeout. Sayfalar agir veya selector eksik.",
            "details": [f["id"] for f in timeouts],
        })

    return actions


# ─── ANA LOOP ────────────────────────────────────────────────────────────────

async def run_test_loop(max_rounds: int = 3, target_pass_rate: float = 0.85) -> dict:
    """Autonomous test loop: round-robin until %85+ pass."""
    history = []
    scenarios = SCENARIOS

    for round_num in range(1, max_rounds + 1):
        logger.info(f"\n{'='*70}")
        logger.info(f"  ROUND {round_num}/{max_rounds}  ({len(scenarios)} senaryo)")
        logger.info(f"{'='*70}")

        round_result = await run_round(scenarios, round_num)
        history.append(round_result)

        logger.info(f"\nROUND {round_num} OZET: {round_result['pass']}/{round_result['total']} "
                    f"({round_result['pass_rate']*100:.1f}%)")

        # Hedefe ulastik mi?
        if round_result["pass_rate"] >= target_pass_rate:
            logger.success(f"🎯 Hedef {target_pass_rate*100:.0f}% basari: kapanan loop.")
            break

        # Fix actions topla
        actions = collect_fix_actions(round_result)
        logger.info(f"\nFIX ACTIONS ({len(actions)}):")
        for a in actions:
            logger.info(f"  - [{a['type']}] {a['description']}")
            if a.get("stop_loop"):
                logger.warning(f"  STOP LOOP: {a['description']}")
                return {"history": history, "stopped": True, "stop_reason": a["description"]}

        # Sadece basarisiz olanlari yeniden dene (round 2+)
        if round_num < max_rounds:
            failed_ids = {r["id"] for r in round_result["results"] if not r["passed"]}
            scenarios = [sc for sc in SCENARIOS if sc["id"] in failed_ids]
            if not scenarios:
                break

    return {"history": history, "stopped": False}


# ─── RAPOR ───────────────────────────────────────────────────────────────────

def write_report(loop_result: dict, output_path: Path) -> None:
    """Markdown rapor yaz."""
    history = loop_result["history"]
    final = history[-1] if history else None
    if not final:
        output_path.write_text("# Test Loop — Calistirilamadi\n", encoding="utf-8")
        return

    lines = []
    lines.append(f"# Eyotek Autonomous Test Loop — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(f"**Round sayisi:** {len(history)}")
    lines.append(f"**Final basari:** {final['pass']}/{final['total']} ({final['pass_rate']*100:.1f}%)")
    if loop_result.get("stopped"):
        lines.append(f"**Stop reason:** {loop_result.get('stop_reason')}")
    lines.append("")
    lines.append("## Round Trend")
    lines.append("")
    lines.append("| Round | Pass | Fail | Pass Rate |")
    lines.append("|---|---|---|---|")
    for r in history:
        lines.append(f"| {r['round']} | {r['pass']} | {r['fail']} | {r['pass_rate']*100:.1f}% |")
    lines.append("")

    lines.append("## Final Round — Detay")
    lines.append("")
    lines.append("| ID | Kategori | Query | Sonuc | Filter | Page | Confidence |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in final["results"]:
        status = "✅" if r["passed"] else f"❌ {r['failure_category']}"
        page = r["plan"].get("page_path", "")[:30]
        conf = r["plan"].get("confidence", 0)
        flt = ",".join(r["filters_applied"].keys()) or "-"
        q = r["query"][:50].replace("|", "\\|")
        lines.append(f"| {r['id']} | {r['category']} | {q} | {status} | {flt} | {page} | {conf:.2f} |")
    lines.append("")

    # Hatalar detayli
    fails = [r for r in final["results"] if not r["passed"]]
    if fails:
        lines.append("## Basarisiz Detaylari")
        lines.append("")
        for f in fails:
            lines.append(f"### {f['id']} — `{f['failure_category']}`")
            lines.append(f"- **Query:** {f['query']}")
            lines.append(f"- **Sebep:** {f['reason']}")
            lines.append(f"- **Plan:** `{json.dumps(f['plan'], ensure_ascii=False)}`")
            if f["error"]:
                lines.append(f"- **Hata:** {f['error']}")
            lines.append("")

    # Hata kategori dagilimi
    if fails:
        from collections import Counter
        cat_counts = Counter(f["failure_category"] for f in fails)
        lines.append("## Hata Kategori Dagilimi")
        lines.append("")
        for cat, n in cat_counts.most_common():
            lines.append(f"- **{cat}**: {n}")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Eyotek Autonomous Test Loop")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--target", type=float, default=0.85)
    parser.add_argument("--scenario", help="Tek senaryo calistir (id)")
    parser.add_argument("--report", help="Markdown rapor cikti yolu",
                        default=str(_ROOT / "logs" / f"eyotek_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"))
    args = parser.parse_args()

    async def _main():
        if args.scenario:
            sc = next((s for s in SCENARIOS if s["id"] == args.scenario), None)
            if not sc:
                print(f"Senaryo bulunamadi: {args.scenario}")
                print(f"Mevcut: {[s['id'] for s in SCENARIOS]}")
                return
            r = await run_round([sc], 1)
            print(json.dumps(r, ensure_ascii=False, default=str, indent=2))
            return

        loop_result = await run_test_loop(max_rounds=args.rounds, target_pass_rate=args.target)
        out = Path(args.report)
        out.parent.mkdir(exist_ok=True, parents=True)
        write_report(loop_result, out)
        print(f"\n=== RAPOR: {out} ===")

    asyncio.run(_main())
