"""
A/B Live Test — FULL vs NORMAL gerçek karşılaştırma
======================================================

Oturum 25.19: Modüler mimarinin gerçek değerini ölçer.

KARŞILAŞTIRMA: Aynı sorgular hem FULL (mode=disabled) hem NORMAL
(mode=normal) ile çalıştırılır, kaliteler Groq 70B ile skorlanır.

Karar:
- NORMAL ≥ FULL × 0.95 → MODÜLER KALICI
- 0.90 ≤ NORMAL < 0.95 → SINIRLI ROLLOUT (sadece kavramsal)
- NORMAL < 0.90 → GERİ AL (kalite kaybı kabul edilemez)
"""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ─── Test sorgu seti (kontrollü, KVKK güvenli) ───────────────────
SORGULAR = [
    # Kavramsal — LIGHT'a düşmesi muhtemel (en büyük tasarruf alanı)
    ("kavramsal", "limit nedir kısaca anlat"),
    ("kavramsal", "türev formülünü ver"),
    ("kavramsal", "fotosentez nasıl çalışır"),
    ("kavramsal", "Newton'un üçüncü yasası"),
    ("kavramsal", "integral ne demek"),

    # YKS bilgi — LIGHT
    ("yks_bilgi", "TYT ne zaman"),
    ("yks_bilgi", "AYT'ye kaç gün kaldı"),
    ("yks_bilgi", "TYT kaç soru"),
    ("yks_bilgi", "AYT sayısal hangi dersler"),

    # Sohbet — LIGHT
    ("sohbet", "merhaba nasılsın"),
    ("sohbet", "iyi günler"),
    ("sohbet", "teşekkür ederim"),

    # Plan/Analiz — NORMAL (tool gerek)
    ("plan_analiz", "bana yarın için çalışma planı yap"),
    ("plan_analiz", "son denememdeki net ne"),
    ("plan_analiz", "hangi konularda zayıfım"),

    # Hassas (FULL'e zorlanmalı)
    ("hassas_full", "borcum kaç TL"),
    ("hassas_full", "Damla'nın notu"),

    # Yöntem — NORMAL/LIGHT
    ("yontem", "pomodoro tekniği nedir"),
    ("yontem", "nasıl daha verimli çalışırım"),

    # Kurum
    ("kurum", "Fermat'ın telefonu"),
]


async def run_with_mode(query: str, mode: str, phone: str) -> dict:
    """Verilen mode ile sorguyu çalıştır."""
    from datetime import datetime as _dt
    # Env değiştir (bridge process içinde aynı process — anında geçerli)
    old_mode = os.environ.get("MODULAR_PROMPT_MODE", "disabled")
    os.environ["MODULAR_PROMPT_MODE"] = mode

    t0 = _dt.now()
    try:
        from whatsapp_bridge import process_message
        from conversation_memory import _CONTEXT_CACHE
        _CONTEXT_CACHE.pop(phone, None)
        # Query cache temizle (her test fresh olsun)
        try:
            from db_pool import db_execute
            await db_execute("DELETE FROM query_cache WHERE phone=$1", phone)
        except Exception:
            pass

        response = await process_message(phone, query, channel="web")
        elapsed = (_dt.now() - t0).total_seconds() * 1000
        return {
            "mode": mode,
            "query": query,
            "response": response or "",
            "len": len(response or ""),
            "latency_ms": int(elapsed),
            "error": None,
        }
    except Exception as e:
        return {
            "mode": mode,
            "query": query,
            "response": "",
            "len": 0,
            "latency_ms": -1,
            "error": str(e)[:200],
        }
    finally:
        os.environ["MODULAR_PROMPT_MODE"] = old_mode


async def quality_score_with_groq(query: str, response_a: str, response_b: str) -> dict:
    """İki yanıtı karşılaştırmalı skorla (1-10 her biri + winner)."""
    if not response_a or not response_b:
        return {"score_a": 0, "score_b": 0, "winner": "n/a", "reason": "boş yanıt"}
    try:
        from llm_router import LLMRouter
        router = LLMRouter()
        prompt = (
            f"İki bot yanıtını aynı soru için karşılaştır.\n\n"
            f"SORU: {query}\n\n"
            f"YANIT_A (FULL prompt):\n{response_a[:1200]}\n\n"
            f"YANIT_B (NORMAL prompt):\n{response_b[:1200]}\n\n"
            f"Her birini 1-10 puanla. Kriterler: doğruluk, eksiksizlik, "
            f"Türkçe akıcılık, format. SADECE JSON dön:\n"
            f'{{"score_a": <1-10>, "score_b": <1-10>, "winner": "a"|"b"|"tie", "reason": "kısa"}}'
        )
        if hasattr(router, "chat_groq"):
            text = router.chat_groq(
                messages=[{"role": "user", "content": prompt}],
                system="Sen kalite değerlendirme uzmanısın. SADECE JSON dön.",
                model="llama-3.3-70b-versatile",
            )
        else:
            return {"score_a": -1, "score_b": -1, "winner": "n/a", "reason": "router yok"}
        import re
        m = re.search(r'\{[^{}]+\}', text or "")
        if m:
            data = json.loads(m.group(0))
            return {
                "score_a": float(data.get("score_a", 0)),
                "score_b": float(data.get("score_b", 0)),
                "winner": str(data.get("winner", "n/a"))[:10],
                "reason": str(data.get("reason", ""))[:200],
            }
        return {"score_a": -1, "score_b": -1, "winner": "n/a", "reason": f"parse fail: {text[:100]}"}
    except Exception as e:
        return {"score_a": -1, "score_b": -1, "winner": "n/a", "reason": str(e)[:150]}


async def main():
    from db_pool import db_fetchval
    phone = await db_fetchval("SELECT phone FROM students WHERE soz_no='211'")
    if not phone:
        print("Test öğrenci yok, abort.")
        return

    print(f"=== A/B LIVE TEST: FULL vs NORMAL ===")
    print(f"Test: {phone[-4:]} (Nazlı, soz_no=211)")
    print(f"Sorgu sayısı: {len(SORGULAR)}")
    print(f"Her sorgu 2 modda çalıştırılacak (toplam {len(SORGULAR)*2} request)")
    print()

    results = []
    for i, (kategori, q) in enumerate(SORGULAR, 1):
        print(f"[{i}/{len(SORGULAR)}] {kategori}: {q[:50]}")

        # FULL (disabled mode = mevcut davranış)
        r_full = await run_with_mode(q, "disabled", phone)
        await asyncio.sleep(0.5)
        # NORMAL
        r_norm = await run_with_mode(q, "normal", phone)
        await asyncio.sleep(0.5)

        # Kalite skor
        if r_full["len"] > 5 and r_norm["len"] > 5:
            qs = await quality_score_with_groq(q, r_full["response"], r_norm["response"])
        else:
            qs = {"score_a": 0, "score_b": 0, "winner": "n/a", "reason": "boş yanıt"}

        result = {
            "kategori": kategori, "query": q,
            "full_len": r_full["len"], "full_lat": r_full["latency_ms"],
            "norm_len": r_norm["len"], "norm_lat": r_norm["latency_ms"],
            "score_full": qs["score_a"], "score_norm": qs["score_b"],
            "winner": qs["winner"], "reason": qs["reason"],
        }
        results.append(result)
        print(f"   FULL: {r_full['len']}ch / {r_full['latency_ms']}ms / score={qs['score_a']}")
        print(f"   NORM: {r_norm['len']}ch / {r_norm['latency_ms']}ms / score={qs['score_b']}")
        print(f"   Winner: {qs['winner']}")
        print()
        await asyncio.sleep(0.3)

    # Aggregat
    valid = [r for r in results if r["score_full"] > 0 and r["score_norm"] > 0]
    if not valid:
        print("Hiçbir geçerli sonuç yok!")
        return

    avg_full = sum(r["score_full"] for r in valid) / len(valid)
    avg_norm = sum(r["score_norm"] for r in valid) / len(valid)
    avg_full_lat = sum(r["full_lat"] for r in valid if r["full_lat"] > 0) / len(valid)
    avg_norm_lat = sum(r["norm_lat"] for r in valid if r["norm_lat"] > 0) / len(valid)

    win_a = sum(1 for r in valid if r["winner"] == "a")
    win_b = sum(1 for r in valid if r["winner"] == "b")
    win_tie = sum(1 for r in valid if r["winner"] == "tie")

    print("=" * 70)
    print("AGGREGAT SONUÇ")
    print("=" * 70)
    print(f"Geçerli ölçüm: {len(valid)}/{len(results)}")
    print()
    print(f"FULL (baseline):")
    print(f"  Ortalama kalite: {avg_full:.2f}/10")
    print(f"  Ortalama uzunluk: {sum(r['full_len'] for r in valid)//len(valid)} char")
    print(f"  Ortalama latency: {int(avg_full_lat)}ms")
    print()
    print(f"NORMAL (candidate):")
    print(f"  Ortalama kalite: {avg_norm:.2f}/10")
    print(f"  Ortalama uzunluk: {sum(r['norm_len'] for r in valid)//len(valid)} char")
    print(f"  Ortalama latency: {int(avg_norm_lat)}ms")
    print()
    print(f"WINNER: FULL={win_a} | NORMAL={win_b} | TIE={win_tie}")
    print()

    ratio = avg_norm / avg_full if avg_full > 0 else 0
    print(f"NORMAL/FULL oranı: {ratio:.3f} ({ratio*100:.1f}%)")
    if ratio >= 0.95:
        karar = "✅ MODÜLER KALICI — kalite korundu (>= 95%)"
    elif ratio >= 0.90:
        karar = "⚠️ SINIRLI ROLLOUT — sadece kavramsal/sohbet için NORMAL kullan"
    elif ratio >= 0.80:
        karar = "🟠 KAYBA UĞRADIK — prompt zenginleştir veya canary'ye geri dön"
    else:
        karar = "🔴 GERİ AL — kalite kabul edilemez seviyede"
    print(f"\nKARAR: {karar}")

    # Save
    out = {
        "ts": datetime.now().isoformat(),
        "n": len(valid),
        "avg_full": avg_full,
        "avg_normal": avg_norm,
        "ratio": ratio,
        "winners": {"full": win_a, "normal": win_b, "tie": win_tie},
        "karar": karar,
        "details": results,
    }
    with open("tier_ab_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n💾 tier_ab_results.json kaydedildi")


if __name__ == "__main__":
    asyncio.run(main())
