"""
Eyotek Fix Loop — Neo direktif 11 May 20:10
=============================================

Bot konuşmasındaki Eyotek hatalarını çözmek için otomatik fix loop.
1. 14 farklı sorgu senaryosu (Neo'nun gerçek konuşmalarından türetilmiş)
2. Her birini execute_query ile çalıştır
3. Otomatik kalite skorlama
4. Hatalı senaryolar için detay rapor
5. %100 başarı oranına kadar iter

Kullanım:
  python eyotek_fix_loop.py            # tek pass
  python eyotek_fix_loop.py --watch    # her başarısızdan sonra dur
"""
from __future__ import annotations
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv("/opt/fermatai/.env", override=True)

sys.path.insert(0, str(Path(__file__).parent))

# ─── TEST SENARYOLARI ─────────────────────────────────────────────────────────
# (id, soru, kalite_kontrolu fn(result) → (pass:bool, note:str))

def expect_min_rows(n: int):
    def check(r):
        rc = r.get("row_count", 0)
        if r.get("success") and rc >= n:
            return True, f"row_count={rc} >= {n}"
        return False, f"row_count={rc} < beklenen {n} (success={r.get('success')}, err={r.get('error_code')})"
    return check

def expect_season(target_label: str):
    def check(r):
        s = (r.get("season") or {}).get("current_label", "")
        if target_label in s:
            return True, f"season={s} ✓"
        return False, f"season={s} != {target_label}"
    return check

def expect_pagination_ge(n: int):
    def check(r):
        pag = r.get("pagination") or {}
        pr = pag.get("pages_read", 0)
        if pr >= n:
            return True, f"pages_read={pr}>={n}"
        return False, f"pages_read={pr}<{n} (total_pages={pag.get('total_pages')})"
    return check

def expect_success():
    def check(r):
        if r.get("success"):
            return True, "success"
        return False, f"FAIL: {r.get('error_code')} | {r.get('error', '')[:120]}"
    return check

def expect_columns_contain(*cols):
    def check(r):
        actual = r.get("columns", [])
        for c in cols:
            if not any(c.lower() in (a or "").lower() for a in actual):
                return False, f"column '{c}' yok, mevcut: {actual[:8]}"
        return True, f"columns {list(cols)} ✓"
    return check

def combine(*checks):
    def check(r):
        notes = []
        for c in checks:
            ok, note = c(r)
            if not ok:
                return False, note
            notes.append(note)
        return True, " | ".join(notes)
    return check


SCENARIOS = [
    # ID, soru, kalite_kontrolu
    ("S01_yeni_sezon_ogrenci_count", "yeni sezonda kac ogrenci var",
        combine(expect_success(), expect_min_rows(20))),

    ("S02_yeni_sezon_ogrenci_listesi", "yeni sezonda kim kaydoldu listele",
        combine(expect_success(), expect_min_rows(20))),

    ("S03_aktif_sezon_borclular", "yeni sezonda borclu ogrenciler kim",
        combine(expect_success(), expect_min_rows(15))),

    ("S04_eski_sezon_borclular", "Aralik 2025 borclular kim",
        combine(expect_success(), expect_min_rows(1))),  # Aralik 2025'te gercekten 4 borclu var

    ("S05_dun_etutler", "dun hangi etutler vardi",
        combine(expect_success(), expect_min_rows(3))),

    ("S06_bugun_etutler", "bugun hangi etutler var",
        combine(expect_success(), expect_min_rows(1))),

    ("S07_bu_hafta_etutler", "bu hafta tum etutler listele",
        combine(expect_success(), expect_min_rows(10))),

    ("S08_son_sinavlar", "en son yapilan sinavlar listele",
        combine(expect_success(), expect_min_rows(5))),

    ("S09_rehberlik_notlari_nisan", "Nisan ayinda yazilan rehberlik notlari",
        combine(expect_success(), expect_min_rows(10))),

    ("S10_bugun_taksit", "bugun kim taksit odedi",
        expect_success()),  # bugün ödeme yoksa OK

    ("S11_son_kayit", "en son kayit yapan ogrenciler",
        combine(expect_success(), expect_min_rows(10))),

    ("S12_ogretmen_etut_listesi", "Mehmet Donmez hocanin bu hafta etutleri",
        expect_success()),

    ("S13_sezon_kayit_ozet", "bu sezon aylik kayit sayilari",
        combine(expect_success(), expect_min_rows(5))),

    ("S14_yeni_sezon_kayit_full", "2026.27 sezonu tam ogrenci listesi sayfalama dahil",
        combine(expect_success(), expect_min_rows(20))),
]


# ─── RUNNER ──────────────────────────────────────────────────────────────────

async def run_scenario(sid: str, question: str, check_fn) -> dict:
    from eyotek_knowledge.eyotek_planner import execute_query
    start = time.time()
    try:
        r = await execute_query(question, max_rows=80)
        elapsed = time.time() - start
        ok, note = check_fn(r)
        return {
            "id": sid,
            "question": question,
            "pass": ok,
            "note": note,
            "elapsed_sec": round(elapsed, 1),
            "page": r.get("page"),
            "row_count": r.get("row_count", 0),
            "season": (r.get("season") or {}).get("current_label"),
            "sezon_resolved": r.get("sezon_resolved"),
            "page_hint_type": (r.get("page_hint") or {}).get("type"),
            "pagination": r.get("pagination"),
            "attempts_count": len(r.get("attempts", [])),
            "error_code": r.get("error_code"),
            "error": (r.get("error") or "")[:200],
            "sample_rows": [list((row or {}).values())[:5] for row in (r.get("rows", []) or [])[:3]],
        }
    except Exception as e:
        return {
            "id": sid, "question": question, "pass": False,
            "note": f"EXCEPTION: {type(e).__name__}: {str(e)[:200]}",
            "elapsed_sec": round(time.time() - start, 1),
        }


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", help="Sadece id'si bu prefix ile başlayanları çalıştır (örn S03)")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--single", help="Tek senaryo id ile çalıştır")
    parser.add_argument("--out", default="eyotek_fix_loop_results.json")
    args = parser.parse_args()

    scenarios = SCENARIOS
    if args.single:
        scenarios = [s for s in scenarios if s[0] == args.single]
    elif args.filter:
        scenarios = [s for s in scenarios if s[0].startswith(args.filter)]

    print("=" * 80)
    print(f"EYOTEK FIX LOOP — {len(scenarios)} senaryo")
    print("=" * 80)

    results = []
    for i, (sid, question, check) in enumerate(scenarios, 1):
        print(f"\n[{i}/{len(scenarios)}] {sid}: '{question[:60]}'")
        r = await run_scenario(sid, question, check)
        results.append(r)
        status = "✅ PASS" if r["pass"] else "❌ FAIL"
        print(f"  {status} — {r['note']}")
        if not r["pass"] and not args.summary_only:
            print(f"  page: {r.get('page')}")
            print(f"  row_count: {r.get('row_count')}")
            print(f"  pagination: {r.get('pagination')}")
            print(f"  error: {r.get('error')[:120] if r.get('error') else ''}")
        print(f"  elapsed: {r['elapsed_sec']}s | page={r.get('page')} | rows={r.get('row_count')} | pag={r.get('pagination')}")
        if r.get("sample_rows"):
            for sr in r["sample_rows"][:2]:
                print(f"    sample: {sr}")

    # ÖZET
    print("\n" + "=" * 80)
    print("ÖZET")
    print("=" * 80)
    passed = [r for r in results if r["pass"]]
    failed = [r for r in results if not r["pass"]]
    print(f"PASS: {len(passed)}/{len(results)}  ({100*len(passed)/len(results):.0f}%)")
    print(f"FAIL: {len(failed)}/{len(results)}")
    total_time = sum(r["elapsed_sec"] for r in results)
    print(f"Toplam süre: {total_time:.0f}s, ortalama {total_time/len(results):.1f}s/test")
    if failed:
        print("\nBAŞARISIZ SENARYOLAR:")
        for f in failed:
            print(f"  ❌ {f['id']}: {f['note']}")

    # Dosyaya yaz
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\nDetay rapor: {args.out}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
