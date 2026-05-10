"""Test Runner — 500+ test sorusunu canli bridge'e gonder, paralel, metrik topla.

Cikti:
  - results.json: her test icin {id, latency_ms, response, source, error, ...}
  - summary.json: kategori bazli agg (avg latency, success rate, route dist)

Calistirma:
  python test_runner.py [--limit N] [--concurrency K] [--target URL]

Hedef:
  Default: http://localhost:8001 (VPS local) — DIRECT process_message cagrisi
  --remote: VPS uzaktan (sshtunel veya bridge HTTP API)
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Calisma dizini: tests/, parent: eyotek_agent/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Test corpus yukle
try:
    from tests.test_corpus import get_corpus, PHONES
except ImportError:
    from test_corpus import get_corpus, PHONES


async def _seed_test_users():
    """acl_users'a test kullanicilarini yaz (idempotent)."""
    from test_mode import seed_test_users, TEST_USERS
    print(f"[SEED] {len(TEST_USERS)} test kullanici acl_users'a yaziliyor...")
    await seed_test_users()
    print(f"[SEED] OK")


async def _run_single_test(test: dict, concurrency_sem: asyncio.Semaphore, idx: int, total: int, per_test_timeout: float = 60.0) -> dict:
    """Tek bir test sorusunu calistir, sonuc dictionary olarak don."""
    async with concurrency_sem:
        result = {
            "id": test["id"],
            "category": test["category"],
            "role_key": test["role_key"],
            "phone": test["phone"],
            "question_clean": test["question"],
            "expected_route": test["expected_route"],
            "expected_keywords": test["expected_keywords"],
            "forbidden_keywords": test["forbidden_keywords"],
            "notes": test["notes"],
            "ts_start": datetime.now().isoformat(),
        }
        t0 = time.monotonic()
        response_text = ""
        error_msg = ""
        try:
            from whatsapp_bridge import process_message
            # Per-test timeout — tek mesaj 60s'ten cok surerse iptal et,
            # tum batch'i bloke etmesin.
            response_text = await asyncio.wait_for(
                process_message(
                    phone=test["phone"],
                    text=test["question"],
                    channel="test",
                ),
                timeout=per_test_timeout,
            )
            if response_text is None:
                response_text = ""
        except asyncio.TimeoutError:
            error_msg = f"timeout_{per_test_timeout}s"
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)[:200]}"
        elapsed = (time.monotonic() - t0) * 1000
        result["latency_ms"] = round(elapsed, 1)
        result["response"] = response_text[:3000] if response_text else ""
        result["response_len"] = len(response_text or "")
        result["error"] = error_msg

        # Keyword check
        resp_lower = (response_text or "").lower()
        result["matched_keywords"] = [
            k for k in test["expected_keywords"] if k in resp_lower
        ]
        result["missing_keywords"] = [
            k for k in test["expected_keywords"] if k not in resp_lower
        ]
        result["found_forbidden"] = [
            k for k in test["forbidden_keywords"] if k in resp_lower
        ]

        # Routing source — routing_stats'ten last record icin yapilabilir,
        # ama buradan handler_name'i okumak guvenilir degil. Heuristic:
        if elapsed < 200:
            result["likely_source"] = "fast_response"
        elif elapsed < 2500:
            result["likely_source"] = "cerebras"  # ya da cache hit claude
        elif elapsed < 8000:
            result["likely_source"] = "claude"
        else:
            result["likely_source"] = "claude_heavy"

        if (idx + 1) % 25 == 0 or idx == total - 1:
            print(f"  [{idx+1:3d}/{total}] {test['id']:30s} | {elapsed:6.0f}ms | {result['likely_source']:14s} | err={'YES' if error_msg else 'no'}")
        return result


async def run_corpus(limit: int = None, concurrency: int = 3, out_dir: str = None, batch_size: int = 50) -> dict:
    """Tum corpus'u calistir, BATCH bazli — her batch sonunda diske kaydet
    (progressive save — bridge crash ederse sonuclar kaybolmaz)."""
    corpus = get_corpus()
    if limit:
        corpus = corpus[:limit]
    total = len(corpus)
    print(f"\n=== TEST RUNNER ===")
    print(f"Total: {total} test | Concurrency: {concurrency} | Batch: {batch_size}")
    print(f"=" * 70)

    # Once test kullanicilarini seed et
    await _seed_test_users()

    if out_dir is None:
        out_dir = Path(__file__).resolve().parent / "runs"
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = Path(out_dir) / f"results_{ts}.json"

    sem = asyncio.Semaphore(concurrency)
    clean = []
    t0 = time.monotonic()

    # Batch'ler halinde calistir + her batch sonunda progressive save
    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch = corpus[batch_start:batch_end]
        print(f"\n[BATCH] {batch_start+1}-{batch_end} basliyor...")
        bt0 = time.monotonic()
        tasks = [_run_single_test(t, sem, batch_start + i, total) for i, t in enumerate(batch)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        belapsed = time.monotonic() - bt0
        for r in batch_results:
            if isinstance(r, Exception):
                clean.append({"error": f"{type(r).__name__}: {str(r)[:200]}", "latency_ms": 0})
            else:
                clean.append(r)
        # Progressive save
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        print(f"[BATCH] {batch_start+1}-{batch_end} bitti ({belapsed:.0f}s) → progressive save ({len(clean)} kayit)")
        # Cerebras 429 cool-down
        if batch_end < total:
            await asyncio.sleep(2)

    total_elapsed = time.monotonic() - t0
    results = clean
    print(f"\n[OUTPUT] {results_path}")

    # Summary
    summary = _build_summary(clean, total_elapsed)
    summary_path = Path(out_dir) / f"summary_{ts}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    _print_summary(summary)
    return {"results_path": str(results_path), "summary_path": str(summary_path), "summary": summary}


def _build_summary(results: list, total_elapsed: float) -> dict:
    """Sonuclardan ozet cikar."""
    from collections import defaultdict
    by_cat = defaultdict(list)
    by_source = defaultdict(int)
    by_role = defaultdict(list)
    errors = []
    forbidden_hits = []

    for r in results:
        cat = r.get("category", "?")
        by_cat[cat].append(r)
        src = r.get("likely_source", "?")
        by_source[src] += 1
        by_role[r.get("role_key", "?")].append(r)
        if r.get("error"):
            errors.append({"id": r.get("id"), "error": r["error"]})
        if r.get("found_forbidden"):
            forbidden_hits.append({"id": r.get("id"), "found": r["found_forbidden"], "notes": r.get("notes")})

    cat_stats = {}
    for cat, items in by_cat.items():
        lats = [x["latency_ms"] for x in items if x.get("latency_ms", 0) > 0]
        lats.sort()
        cat_stats[cat] = {
            "count": len(items),
            "errors": sum(1 for x in items if x.get("error")),
            "empty_response": sum(1 for x in items if not x.get("response_len", 0)),
            "avg_latency_ms": round(sum(lats) / len(lats), 1) if lats else 0,
            "p50_latency_ms": round(lats[len(lats)//2], 1) if lats else 0,
            "p95_latency_ms": round(lats[int(len(lats)*0.95)], 1) if len(lats) > 1 else (lats[0] if lats else 0),
            "p99_latency_ms": round(lats[int(len(lats)*0.99)], 1) if len(lats) > 1 else (lats[0] if lats else 0),
        }

    all_lats = [r["latency_ms"] for r in results if r.get("latency_ms", 0) > 0]
    all_lats.sort()

    return {
        "total_tests": len(results),
        "total_elapsed_sec": round(total_elapsed, 2),
        "throughput_per_sec": round(len(results) / total_elapsed, 2) if total_elapsed > 0 else 0,
        "total_errors": len(errors),
        "total_empty_response": sum(1 for r in results if not r.get("response_len", 0)),
        "total_forbidden_hits": len(forbidden_hits),
        "overall_avg_ms": round(sum(all_lats) / len(all_lats), 1) if all_lats else 0,
        "overall_p50_ms": round(all_lats[len(all_lats)//2], 1) if all_lats else 0,
        "overall_p95_ms": round(all_lats[int(len(all_lats)*0.95)], 1) if len(all_lats) > 1 else 0,
        "overall_p99_ms": round(all_lats[int(len(all_lats)*0.99)], 1) if len(all_lats) > 1 else 0,
        "by_source": dict(by_source),
        "by_category": cat_stats,
        "errors": errors[:30],  # ilk 30 hata
        "forbidden_hits": forbidden_hits[:30],
    }


def _print_summary(s: dict):
    print(f"\n=" * 70)
    print(f"=== SUMMARY ===")
    print(f"=" * 70)
    print(f"Total tests:        {s['total_tests']}")
    print(f"Total elapsed:      {s['total_elapsed_sec']}s")
    print(f"Throughput:         {s['throughput_per_sec']} test/sec")
    print(f"Errors:             {s['total_errors']}")
    print(f"Empty responses:    {s['total_empty_response']}")
    print(f"Forbidden hits:     {s['total_forbidden_hits']}")
    print(f"Latency p50/p95/p99: {s['overall_p50_ms']}ms / {s['overall_p95_ms']}ms / {s['overall_p99_ms']}ms")
    print(f"\n=== ROUTE DISTRIBUTION ===")
    for src, n in sorted(s['by_source'].items(), key=lambda x: -x[1]):
        pct = n / s['total_tests'] * 100 if s['total_tests'] else 0
        print(f"  {src:18s}: {n:4d} ({pct:5.1f}%)")
    print(f"\n=== CATEGORY BREAKDOWN ===")
    for cat, st in sorted(s['by_category'].items()):
        print(f"  {cat:16s} n={st['count']:3d} err={st['errors']:2d} empty={st['empty_response']:2d} "
              f"avg={st['avg_latency_ms']:6.0f}ms p95={st['p95_latency_ms']:6.0f}ms")
    if s['errors']:
        print(f"\n=== FIRST 10 ERRORS ===")
        for e in s['errors'][:10]:
            print(f"  {e['id']}: {e['error']}")


async def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="ilk N testi calistir (smoke)")
    p.add_argument("--concurrency", type=int, default=3, help="paralel goruv sayisi (default 3 — Cerebras rate limit)")
    p.add_argument("--out", type=str, default=None, help="cikti dizini")
    args = p.parse_args()

    result = await run_corpus(
        limit=args.limit,
        concurrency=args.concurrency,
        out_dir=args.out,
    )
    return result


if __name__ == "__main__":
    asyncio.run(main())
