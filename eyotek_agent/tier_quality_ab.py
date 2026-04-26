"""
Tier Kalite A/B Test Framework (Oturum 25.18 — Faz 4)
========================================================

Amaç: Modüler tier (LIGHT/NORMAL) FULL'e göre kalite kaybı yapmıyor mu?

Yöntem:
1. Aynı sorgu setini 2 kez çalıştır (LIGHT vs FULL, NORMAL vs FULL)
2. conversation_quality_analyzer (Groq 70B) ile kalite skorla
3. Karşılaştır → ortalama skor farkı, kaybın hangi kategoride olduğunu göster

KULLANIM:
    python tier_quality_ab.py --baseline full --candidate light --samples 30

Çıktı: tier_quality_ab_report.html (renkli karşılaştırma)

KVKK NOT: Test içeriği gerçek kullanıcı sorguları DEĞIL, kontrollü sentetik
sorgular. Hassas veri sızdırma riski yok.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import List, Dict, Optional


# ═══════════════════════════════════════════════════════════════════
# TEST SORGU SETI — kontrollü, KVKK-güvenli
# ═══════════════════════════════════════════════════════════════════

# Her kategori için 5-10 sorgu — toplam ~50 sorgu
SORGU_SETI = {
    "kavramsal": [
        "limit nedir kısaca anlat",
        "türev formülünü ver",
        "fotosentez nasıl çalışır",
        "Osmanlı'nın kuruluş yılı ne",
        "Newton'un üçüncü yasası",
        "integral ne işe yarar",
        "mitoz bölünme aşamaları",
        "ohm yasası formülü",
    ],
    "yks_takvim": [
        "TYT ne zaman",
        "AYT'ye kaç gün kaldı",
        "LGS hangi tarihte",
        "sınava kaç gün var",
    ],
    "mufredat": [
        "TYT kaç soru",
        "AYT sayısal kaç soru",
        "AYT mat'ta hangi konular var",
        "LGS formatı nedir",
    ],
    "selamlama_sohbet": [
        "merhaba",
        "iyi günler",
        "naber",
        "teşekkür ederim",
        "görüşürüz",
    ],
    "motivasyon": [
        "moralim çok bozuk",
        "yapamayacağım gibi geliyor",
        "yorgunum çalışamıyorum",
        "çok stresliyim",
    ],
    "kurum_bilgi": [
        "fermat nerede",
        "kurum telefonu",
        "çalışma saatleri",
    ],
    "yontem": [
        "nasıl çalışmalıyım",
        "pomodoro tekniği",
        "feynman yöntemi nasıl uygulanır",
    ],
}


def get_all_queries() -> List[Dict]:
    """Düzleştirilmiş sorgu listesi: [{kategori, sorgu}]"""
    out = []
    for kat, sorgular in SORGU_SETI.items():
        for s in sorgular:
            out.append({"kategori": kat, "sorgu": s})
    return out


# ═══════════════════════════════════════════════════════════════════
# TIER KARŞILAŞTIRMA YAPMA
# ═══════════════════════════════════════════════════════════════════

async def run_query_with_tier(
    query: str,
    tier_mode: str,
    test_phone: str = "905541486884",  # test öğrenci (sorgu zaten kontrol)
) -> Dict:
    """Belirli bir tier_mode altında sorgu çalıştır.

    Returns: {tier, query, response, latency_ms, error}
    """
    from datetime import datetime as _dt
    t_start = _dt.now()

    # Geçici env override
    old_mode = os.environ.get("MODULAR_PROMPT_MODE", "disabled")
    os.environ["MODULAR_PROMPT_MODE"] = tier_mode

    try:
        # Test için process_message direkt çağrılabilir
        # NOT: Bu test framework — bridge restart ÖNCESİ env değiştirilmeli
        # Pratikte bu fonksiyon bridge'in dışında subprocess olarak çalışır
        # Şimdilik mock — gerçek aktivasyon canlı test scriptiyle
        from whatsapp_bridge import process_message
        from conversation_memory import _CONTEXT_CACHE
        _CONTEXT_CACHE.pop(test_phone, None)
        response = await process_message(test_phone, query, channel="web")
        elapsed = (_dt.now() - t_start).total_seconds() * 1000
        return {
            "tier_mode": tier_mode,
            "query": query,
            "response": response[:2000] if response else "",
            "response_len": len(response) if response else 0,
            "latency_ms": int(elapsed),
            "error": None,
        }
    except Exception as e:
        return {
            "tier_mode": tier_mode,
            "query": query,
            "response": "",
            "response_len": 0,
            "latency_ms": -1,
            "error": str(e)[:200],
        }
    finally:
        os.environ["MODULAR_PROMPT_MODE"] = old_mode


async def quality_score_with_groq(query: str, response: str) -> Dict:
    """Groq 70B ile kalite skoru (1-10 + reason).

    Returns: {score, reason}
    """
    if not response or len(response) < 5:
        return {"score": 0, "reason": "boş veya çok kısa yanıt"}

    try:
        from llm_router import LLMRouter
        router = LLMRouter()
        prompt = (
            f"Aşağıdaki kullanıcı sorusu ve bot yanıtını değerlendir.\n\n"
            f"SORU: {query}\n"
            f"YANIT: {response[:1500]}\n\n"
            f"Yanıtı 1-10 arası puanla. Şu kriterlere göre:\n"
            f"- Doğruluk (yanlış bilgi var mı?)\n"
            f"- Eksiksizlik (soru tam cevaplandı mı?)\n"
            f"- Türkçe akıcılık\n"
            f"- Format uygunluğu (WhatsApp/web'e uygun mu?)\n\n"
            f"SADECE JSON dön: {{\"score\": <1-10>, \"reason\": \"kısa açıklama\"}}"
        )
        # chat_groq sync — basit çağrı
        if hasattr(router, "chat_groq"):
            text = router.chat_groq(
                messages=[{"role": "user", "content": prompt}],
                system="Sen kalite değerlendirme uzmanısın. SADECE JSON dön.",
                model="llama-3.3-70b-versatile",
            )
        else:
            return {"score": -1, "reason": "router.chat_groq yok"}

        # JSON parse
        import re
        m = re.search(r'\{[^{}]+\}', text or "")
        if m:
            data = json.loads(m.group(0))
            return {
                "score": float(data.get("score", 0)),
                "reason": str(data.get("reason", ""))[:200],
            }
        return {"score": -1, "reason": f"JSON parse fail: {text[:100]}"}
    except Exception as e:
        return {"score": -1, "reason": f"hata: {str(e)[:150]}"}


async def compare_tiers(
    baseline: str = "full",
    candidate: str = "normal",
    samples: int = 20,
    skip_quality_score: bool = False,
) -> Dict:
    """A/B karşılaştırma çalıştır.

    Args:
        baseline: 'full' / 'normal' / 'canary' / 'disabled'
        candidate: alternatif mode
        samples: her gruptan kaç sorgu (max 30 makul)
        skip_quality_score: True → sadece response toplar, kalite skorlamaz

    Returns: rapor dict
    """
    print(f"\n=== A/B TEST: {baseline.upper()} vs {candidate.upper()} ===")
    print(f"Sample: {samples}")
    print()

    queries = get_all_queries()[:samples]
    results = {"baseline": [], "candidate": []}

    # 1. Baseline çalıştır
    print(f"[1/2] {baseline.upper()} mode'da {len(queries)} sorgu çalıştırılıyor...")
    for i, q in enumerate(queries, 1):
        r = await run_query_with_tier(q["sorgu"], baseline)
        r["kategori"] = q["kategori"]
        results["baseline"].append(r)
        print(f"  {i}/{len(queries)} [{q['kategori']}] '{q['sorgu'][:40]}' → {r['response_len']}ch ({r['latency_ms']}ms)")

    # 2. Candidate çalıştır
    print(f"\n[2/2] {candidate.upper()} mode'da {len(queries)} sorgu çalıştırılıyor...")
    for i, q in enumerate(queries, 1):
        r = await run_query_with_tier(q["sorgu"], candidate)
        r["kategori"] = q["kategori"]
        results["candidate"].append(r)
        print(f"  {i}/{len(queries)} [{q['kategori']}] '{q['sorgu'][:40]}' → {r['response_len']}ch ({r['latency_ms']}ms)")

    # 3. Kalite skorlama (opsiyonel)
    if not skip_quality_score:
        print("\n[3/3] Groq 70B ile kalite skorlama...")
        for grup in ["baseline", "candidate"]:
            for r in results[grup]:
                if r["response"]:
                    qs = await quality_score_with_groq(r["query"], r["response"])
                    r["quality_score"] = qs["score"]
                    r["quality_reason"] = qs["reason"]

    # 4. Aggregat istatistik
    def agg(arr):
        valid_lens = [r["response_len"] for r in arr if r["response_len"] > 0]
        valid_lat = [r["latency_ms"] for r in arr if r["latency_ms"] > 0]
        valid_q = [r.get("quality_score", -1) for r in arr if r.get("quality_score", -1) > 0]
        return {
            "n": len(arr),
            "errors": sum(1 for r in arr if r.get("error")),
            "avg_len": int(sum(valid_lens) / len(valid_lens)) if valid_lens else 0,
            "avg_latency_ms": int(sum(valid_lat) / len(valid_lat)) if valid_lat else 0,
            "avg_quality": round(sum(valid_q) / len(valid_q), 2) if valid_q else None,
        }

    rapor = {
        "ts": datetime.now().isoformat(),
        "baseline_mode": baseline,
        "candidate_mode": candidate,
        "samples": samples,
        "baseline_stats": agg(results["baseline"]),
        "candidate_stats": agg(results["candidate"]),
        "details": results,
    }
    return rapor


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="full", choices=["full", "normal", "canary", "disabled"])
    parser.add_argument("--candidate", default="normal", choices=["full", "normal", "canary", "disabled"])
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--no-quality", action="store_true",
                        help="Kalite skoru atla (sadece çalıştır)")
    parser.add_argument("--out", default="tier_quality_report.json")
    args = parser.parse_args()

    rapor = await compare_tiers(
        baseline=args.baseline,
        candidate=args.candidate,
        samples=args.samples,
        skip_quality_score=args.no_quality,
    )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rapor, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print(f"BASELINE ({args.baseline}):")
    print(f"  N={rapor['baseline_stats']['n']}, errors={rapor['baseline_stats']['errors']}")
    print(f"  avg_len={rapor['baseline_stats']['avg_len']}ch, avg_latency={rapor['baseline_stats']['avg_latency_ms']}ms")
    if rapor['baseline_stats'].get('avg_quality'):
        print(f"  avg_quality={rapor['baseline_stats']['avg_quality']}/10")
    print(f"\nCANDIDATE ({args.candidate}):")
    print(f"  N={rapor['candidate_stats']['n']}, errors={rapor['candidate_stats']['errors']}")
    print(f"  avg_len={rapor['candidate_stats']['avg_len']}ch, avg_latency={rapor['candidate_stats']['avg_latency_ms']}ms")
    if rapor['candidate_stats'].get('avg_quality'):
        print(f"  avg_quality={rapor['candidate_stats']['avg_quality']}/10")

    print(f"\n💾 Rapor: {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
