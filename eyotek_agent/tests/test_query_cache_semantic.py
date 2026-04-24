"""Query cache semantik + exact hash — full test (bge-m3)."""
import sys, io, asyncio, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from query_cache import init_db, add_to_cache, find_cached, cleanup_expired, get_stats, EMBED_DIM, SEMANTIC_ENABLED
    from db_pool import get_pool

    print(f"Model: bge-m3 | Dim: {EMBED_DIM} | Semantic: {SEMANTIC_ENABLED}")

    await init_db()

    # Temiz
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM query_cache WHERE phone LIKE $1", "9059999%")

    # Cache'e eklenecek asistan cevabi (turev)
    phone = "905999900001"
    await add_to_cache(
        phone=phone, role="ogrenci",
        query="Turev nedir kisaca anlat",
        response="Turev bir fonksiyonun anlik degisim oranidir. f(x) icin tangent egimini verir. Hiz ve ivme gunluk ornek.",
        source="claude",
    )
    print("Turev cache'e eklendi")

    # Test senaryolar
    tests = [
        # EXACT HASH beklenen (variations)
        ("Turev nedir kisaca anlat", "HIT_EXACT"),
        ("TUREV NEDIR KISACA ANLAT", "HIT_EXACT"),
        ("Turev nedir kısaca anlat?", "HIT_EXACT"),
        ("  turev nedir  kisaca  anlat  ", "HIT_EXACT"),
        # SEMANTIC beklenen (rephrase)
        ("türevi kısaca açıklar mısın", "HIT_SEM_OR_MISS"),  # uncertain
        ("turev nedir", "HIT_SEM_OR_MISS"),
        ("turev anlat bana", "HIT_SEM_OR_MISS"),
        # MISS olmali
        ("Integral nedir kisaca anlat", "MISS"),   # yapı benzer konu farklı
        ("Newton yasalari nedir kisaca", "MISS"),  # yapı benzer konu farklı
        ("Osmanli ne zaman kuruldu", "MISS"),      # tamamen farklı
        ("YKS ne zaman", "MISS"),                   # farklı domain
    ]

    print("\n-- TEST SONUCLARI --")
    fp_count = 0
    tp_count = 0
    for q, expected in tests:
        hit = await find_cached(phone, q)
        got = hit.get("match_type") if hit else "MISS"
        skor = hit.get("similarity") if hit else None
        mark = ""
        if expected == "MISS" and hit:
            mark = " ⚠ FALSE POSITIVE!"
            fp_count += 1
        elif expected.startswith("HIT") and hit:
            tp_count += 1
        elif expected == "HIT_EXACT" and not hit:
            mark = " ⚠ MISSED EXACT"
        print(f"  [{got:8s} {str(round(skor or 0, 3) if skor else ''):<6s}] {q!r} (beklenen: {expected}){mark}")

    # Isolation test
    other = await find_cached("905999900002", "Turev nedir kisaca anlat")
    print(f"\nIzolasyon (baska phone, ayni soru): {'PASS' if other is None else 'FAIL'}")

    stats = await get_stats()
    print(f"\nStats: toplam={stats['toplam']} hit={stats['toplam_hit']}")

    print(f"\n{'='*40}")
    print(f"False Positive: {fp_count} (0 olmali)")
    print(f"True Positive: {tp_count}")
    print(f"{'='*40}")

    # Cleanup
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM query_cache WHERE phone LIKE $1", "9059999%")


asyncio.run(main())
