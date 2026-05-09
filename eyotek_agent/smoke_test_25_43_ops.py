"""25.43-OPS 3 task smoke test — Chrome CDP + Cerebras + routing.

Test edilen 3 ops senaryo:
1. fermat-chrome-cdp.service — port 9222 listening + eyotek_health
2. Cerebras tool-calling enabled — eligible roles + SAFE_GROQ_TOOLS coverage
3. Routing dağılımı baseline — real_user_routing_stats query ok
"""
import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def task1_chrome_cdp_listening():
    """Chrome CDP port 9222 dinliyor mu?"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            r = s.connect_ex(("127.0.0.1", 9222))
            ok = (r == 0)
        if ok:
            print(f"  [OK] CDP port 9222 dinliyor")
            return True
        print(f"  [FAIL] CDP port 9222 KAPALI (errno {r})")
        return False
    except Exception as e:
        print(f"  [FAIL] CDP socket: {e}")
        return False


async def task1_eyotek_health_consistent():
    """eyotek_health şimdi tutarlı cevap veriyor mu?"""
    try:
        from eyotek_health import eyotek_health_check
        # 3 ardışık çağrı → aynı status?
        results = []
        for i in range(3):
            r = await eyotek_health_check(use_cache=False)
            results.append(r["status"])
        if len(set(results)) == 1:
            print(f"  [OK] eyotek_health 3/3 tutarlı: '{results[0]}'")
            return True
        print(f"  [FAIL] tutarsız: {results}")
        return False
    except Exception as e:
        print(f"  [SKIP] eyotek_health import/run fail: {e}")
        return False


def task2_safe_groq_tools_count():
    """SAFE_GROQ_TOOLS 16 tool (4 eski + 12 yeni)?"""
    from llm_router import SAFE_GROQ_TOOLS, ENABLE_GROQ_TOOLS
    new_apis = ['tdk_sozluk', 'nist_constant', 'oeis_search', 'open_meteo_climate',
                'wikidata_lookup', 'cern_open_data', 'huggingface_search_models',
                'tuik_dataset', 'alphafold_lookup', 'nist_webbook',
                'crossref_search', 'osm_lookup']
    in_safe = [a for a in new_apis if a in SAFE_GROQ_TOOLS]
    if len(in_safe) == 12 and ENABLE_GROQ_TOOLS:
        print(f"  [OK] SAFE_GROQ_TOOLS 12/12 yeni API mevcut, ENABLE_GROQ_TOOLS=True")
        return True
    print(f"  [FAIL] in_safe={len(in_safe)}/12, enable={ENABLE_GROQ_TOOLS}")
    return False


def task2_role_expansion():
    """Cerebras+Groq tool-calling staff rollerine genişledi mi?"""
    src = Path(__file__).parent.joinpath("fermat_core_agent.py").read_text(encoding='utf-8')
    checks = [
        ("Cerebras eligible roles set",
         '_CB_ELIGIBLE_ROLES = {"ogrenci", "ogretmen", "rehber", "mudur", "yonetim"}' in src),
        ("Cerebras role check yeni",
         "role in _CB_ELIGIBLE_ROLES" in src),
        ("Groq role expansion",
         'role in {"ogrenci", "ogretmen", "rehber", "mudur", "yonetim"}' in src),
    ]
    fail = [n for n, ok in checks if not ok]
    if fail:
        print(f"  [FAIL] role expansion eksik: {fail}")
        return False
    print(f"  [OK] Role expansion: ogrenci+ogretmen+rehber+mudur+yonetim (admin haric)")
    return True


async def task3_routing_baseline():
    """Routing dağılımı baseline — real_user_routing_stats query çalışıyor."""
    import os
    if not os.environ.get("DATABASE_URL"):
        print(f"  [SKIP] DATABASE_URL yok")
        return True
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            "SELECT response_source, COUNT(*) AS n FROM real_user_routing_stats "
            "WHERE created_at > NOW() - INTERVAL '7 days' "
            "GROUP BY response_source ORDER BY n DESC"
        )
        if not rows:
            print(f"  [WARN] real_user_routing_stats boş (7 gün)")
            return True
        total = sum(r["n"] for r in rows)
        claude_n = next((r["n"] for r in rows if r["response_source"] == "claude"), 0)
        claude_pct = round(claude_n * 100 / total, 1) if total else 0
        print(f"  [OK] Routing baseline alındı — toplam {total}, claude {claude_n} ({claude_pct}%)")
        for r in rows[:5]:
            pct = round(r["n"] * 100 / total, 1)
            print(f"      {r['response_source']:18}: {r['n']:>5} ({pct}%)")
        return True
    except Exception as e:
        print(f"  [SKIP] routing query: {e}")
        return False


async def main():
    print("═══════════════════════════════════════════════")
    print("25.43-OPS SMOKE — 3 task end-to-end")
    print("═══════════════════════════════════════════════\n")

    results = []
    print("─── Task 1: Chrome CDP service ───")
    results.append(task1_chrome_cdp_listening())
    results.append(await task1_eyotek_health_consistent())
    print("\n─── Task 2: Cerebras tool-calling activation ───")
    results.append(task2_safe_groq_tools_count())
    results.append(task2_role_expansion())
    print("\n─── Task 3: Routing dağılımı baseline ───")
    results.append(await task3_routing_baseline())

    print()
    pass_count = sum(results)
    print(f"═══════════════════════════════════════════════")
    print(f"TOPLAM: {pass_count}/{len(results)} test PASS")
    print(f"═══════════════════════════════════════════════")
    return pass_count == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
