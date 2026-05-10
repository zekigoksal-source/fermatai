"""Re-run failed tests — D/F notlu sorulari tekrar koşar, fix loop için kullanır.

Cikti:
  rerun_<original_ts>_<new_ts>.json — yeni sonuclar
  compare_<ts>.json — eski grade vs yeni grade kıyas
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("graded_path", help="graded_<ts>.json")
    p.add_argument("--grades", default="D,F,C,?",
                   help="hangi grade'ler retry edilsin (default D,F,C,?)")
    p.add_argument("--concurrency", type=int, default=3)
    args = p.parse_args()

    with open(args.graded_path, encoding="utf-8") as f:
        graded = json.load(f)

    target_grades = set(g.strip() for g in args.grades.split(","))
    failures = [g for g in graded if g.get("grade") in target_grades]
    print(f"Re-run targeting: {failures and len(failures)} / {len(graded)} (grades: {target_grades})")

    from tests.test_corpus import get_corpus
    full_corpus = {t["id"]: t for t in get_corpus()}

    # Build retry corpus
    retry_corpus = []
    for f in failures:
        tid = f["id"]
        if tid in full_corpus:
            retry_corpus.append(full_corpus[tid])

    if not retry_corpus:
        print("Hic test bulunamadi")
        return

    print(f"Retry corpus: {len(retry_corpus)} test")

    # Run them
    from tests.test_runner import _run_single_test, _seed_test_users
    await _seed_test_users()

    sem = asyncio.Semaphore(args.concurrency)
    tasks = [_run_single_test(t, sem, i, len(retry_corpus)) for i, t in enumerate(retry_corpus)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    clean = []
    for r in results:
        if isinstance(r, Exception):
            clean.append({"error": str(r)[:200], "latency_ms": 0})
        else:
            clean.append(r)

    out_dir = Path(args.graded_path).parent
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"rerun_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    print(f"\n[OUTPUT] {out_path}")

    # Compare
    old_grades = {g["id"]: g.get("grade", "?") for g in graded}
    print(f"\n=== ESKİ vs YENİ ===")
    improved = 0
    same = 0
    regressed = 0
    error_count = 0
    rank = {"F": 0, "D": 1, "C": 2, "?": 3, "B": 4, "A": 5, "A++": 6}
    for r in clean:
        if not r.get("id"):
            error_count += 1
            continue
        old_g = old_grades.get(r["id"], "?")
        # Yeni grade henuz yok — sadece response/error kontrol
        is_err = bool(r.get("error"))
        if is_err and old_g not in ("F",):
            regressed += 1
        elif not is_err and old_g in ("F", "D"):
            improved += 1
        else:
            same += 1
    print(f"Improved (response now exists): {improved}")
    print(f"Same: {same}")
    print(f"Regressed (now error): {regressed}")
    print(f"Errors in new run: {error_count}")


if __name__ == "__main__":
    asyncio.run(main())
