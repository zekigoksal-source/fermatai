"""Donanimsal Kapasite Olcumu — Concurrent stress test.

Hedef: bridge'in gercekci kapasitesini olc (CPU/RAM/p95 latency).

Senaryolar:
  C10  — 10 concurrent mesaj (light)
  C25  — 25 concurrent (normal kullanim)
  C50  — 50 concurrent (heavy)
  C100 — 100 concurrent (peak)
  BURST — 200 mesaj saniyede (instant burst)

Olcumler:
  - throughput (req/sec)
  - p50, p95, p99 latency
  - error rate
  - VPS RAM/CPU (samples via /proc)
"""
import asyncio
import json
import os
import sys
import time
import statistics
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Hizli test mesajlari — fast_response, hep ayni mesaj olmasin
QUICK_MESSAGES = [
    "selam", "merhaba", "ben kimim", "ne yapabilirsin", "yardım",
    "son denemem", "zayıf konularım", "ders programım",
    "kaç gün kaldı", "devamsızlığım", "AYT netim", "TYT netim",
    "bugün ne yapayım", "kimya çıkmış", "fizik formülü",
    "matematik nasıl", "günaydın", "iyi günler",
]

PHONES = [f"905990{i:04d}" for i in range(0, 100)]  # 9059900000..9059900099


async def _single_request(phone, text, idx):
    """Bir istek gonder, latency kaydet."""
    from test_mode import set_test_mode
    from whatsapp_bridge import process_message

    set_test_mode(True, f"cap_{idx}")
    t0 = time.monotonic()
    err = None
    try:
        resp = await process_message(
            phone=phone, text=f"[TEST:cap{idx}] {text}",
            channel="test",
        )
        ok = bool(resp)
    except Exception as e:
        ok = False
        err = f"{type(e).__name__}: {str(e)[:100]}"
    elapsed = (time.monotonic() - t0) * 1000
    return {"idx": idx, "phone": phone, "text": text, "latency_ms": elapsed,
            "ok": ok, "error": err}


async def run_scenario(name: str, concurrency: int, total: int, burst: bool = False):
    """Concurrent yuk testi."""
    print(f"\n=== {name} — concurrency={concurrency} total={total} burst={burst} ===")

    # System metrics baseline
    try:
        import psutil
        bridge_pids = [p.pid for p in psutil.process_iter(['name','cmdline'])
                       if p.info.get('cmdline') and 'whatsapp_bridge' in ' '.join(p.info['cmdline'])]
    except Exception:
        bridge_pids = []

    sem = asyncio.Semaphore(concurrency)

    async def _wrap(i):
        async with sem:
            phone = PHONES[i % len(PHONES)]
            msg = QUICK_MESSAGES[i % len(QUICK_MESSAGES)]
            return await _single_request(phone, msg, i)

    t0 = time.monotonic()
    if burst:
        # All at once, no semaphore-based throttle
        results = await asyncio.gather(*[_single_request(PHONES[i % len(PHONES)],
                                                          QUICK_MESSAGES[i % len(QUICK_MESSAGES)],
                                                          i) for i in range(total)],
                                       return_exceptions=True)
    else:
        results = await asyncio.gather(*[_wrap(i) for i in range(total)], return_exceptions=True)
    elapsed = time.monotonic() - t0

    # Clean
    clean = [r for r in results if isinstance(r, dict)]
    errors = sum(1 for r in clean if not r["ok"])
    lats = sorted([r["latency_ms"] for r in clean if r["ok"]])

    summary = {
        "scenario": name,
        "concurrency": concurrency,
        "total": total,
        "completed": len(clean),
        "errors": errors,
        "elapsed_sec": round(elapsed, 2),
        "throughput_per_sec": round(len(clean) / elapsed, 2) if elapsed > 0 else 0,
        "p50_ms": round(lats[len(lats)//2], 1) if lats else 0,
        "p95_ms": round(lats[int(len(lats)*0.95)], 1) if len(lats) > 1 else (lats[0] if lats else 0),
        "p99_ms": round(lats[int(len(lats)*0.99)], 1) if len(lats) > 1 else (lats[0] if lats else 0),
        "avg_ms": round(sum(lats)/len(lats), 1) if lats else 0,
        "min_ms": round(lats[0], 1) if lats else 0,
        "max_ms": round(lats[-1], 1) if lats else 0,
        "errors_sample": [r["error"] for r in clean if not r["ok"]][:5],
    }
    print(f"  Completed: {summary['completed']}/{total} (errors: {errors})")
    print(f"  Throughput: {summary['throughput_per_sec']} req/sec")
    print(f"  Latency: p50={summary['p50_ms']}ms p95={summary['p95_ms']}ms p99={summary['p99_ms']}ms")
    print(f"  Min/Max:  {summary['min_ms']}ms / {summary['max_ms']}ms")
    if summary['errors_sample']:
        print(f"  Errors:   {summary['errors_sample'][:3]}")
    return summary


async def main():
    print(f"\n{'='*70}")
    print(f"CAPACITY TEST — bridge kapasite olcumu")
    print(f"{'='*70}")

    out_dir = Path(__file__).resolve().parent / "runs"
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    all_results = []
    scenarios = [
        ("C10",  10, 50, False),    # warmup
        ("C25",  25, 100, False),
        ("C50",  50, 150, False),
        ("C100", 100, 200, False),
        ("BURST", 200, 200, True),  # all at once
    ]

    for name, concurrency, total, burst in scenarios:
        try:
            s = await run_scenario(name, concurrency, total, burst)
            all_results.append(s)
            # cool down to avoid cerebras 429
            print(f"  [cool down 15s]")
            await asyncio.sleep(15)
        except Exception as e:
            print(f"  Scenario {name} fail: {e}")
            all_results.append({"scenario": name, "error": str(e)})

    out_path = out_dir / f"capacity_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}")
    print(f"=== CAPACITY SUMMARY ===")
    print(f"{'='*70}")
    print(f"{'Scenario':10s} {'Conc':6s} {'Throughput':12s} {'p50':8s} {'p95':8s} {'p99':8s} {'Errors':8s}")
    for r in all_results:
        if "error" in r and "scenario" in r:
            print(f"{r['scenario']:10s} FAIL: {r['error'][:50]}")
            continue
        print(f"{r['scenario']:10s} {r['concurrency']:6d} {r['throughput_per_sec']:>10.2f}/s {r['p50_ms']:>6.0f}ms {r['p95_ms']:>6.0f}ms {r['p99_ms']:>6.0f}ms {r['errors']:>6d}")

    print(f"\n[OUTPUT] {out_path}")
    return out_path


if __name__ == "__main__":
    asyncio.run(main())
