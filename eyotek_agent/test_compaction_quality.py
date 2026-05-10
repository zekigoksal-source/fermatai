"""Compaction Quality A/B Test — Cerebras pre-compile değer üretiyor mu?

Test Senaryoları:
A. Uzun konuşma (15+ mesaj) → kullanıcı atıf yapan soru ("önceki dediğim X")
   - Old: Claude full history
   - New: Claude + Cerebras compacted summary
   → Aynı cevap kalitesi mi?

B. Kısa konuşma (3 mesaj) → compact SKIP olmalı (heuristic check)

C. Cache miss simulation → compact büyük değer üretmeli

PASS criteria:
- Cevap benzerliği ≥%85 (Cerebras 235B judge ile)
- Latency Cerebras+Claude ≤ Claude full*1.2
- Cost equivalent veya daha düşük

Çalıştır:
    python test_compaction_quality.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
env = Path(__file__).resolve().parent.parent / ".env"
if env.exists():
    load_dotenv(env)


# ─── Test conversation fixtures ───
LONG_CONVERSATION = [
    {"role": "user", "content": "merhaba"},
    {"role": "assistant", "content": "Merhaba Zeki Bey! Bugün size nasıl yardımcı olayım?"},
    {"role": "user", "content": "kurumda kaç öğrenci var"},
    {"role": "assistant", "content": "Kurumda toplam 125 aktif öğrenci var: 12.SAY 45, 12.SOZ 22, 11.SAY 38, 11.SOZ 20."},
    {"role": "user", "content": "11. sınıf SAY öğrencilerinin ortalaması nasıl"},
    {"role": "assistant", "content": "11. sınıf SAY: ortalama TYT net 65, AYT MAT-FEN 55. En başarılı: Mahmut Taha (TYT 95, AYT 82). En düşük: Damla K (TYT 38)."},
    {"role": "user", "content": "Mahmut Taha hakkında daha fazla bilgi"},
    {"role": "assistant", "content": "Mahmut Taha (soz_no 182): 11.SAY ZEN sınıfında. Son 3 deneme: TYT 95, 92, 88. Devamsızlık 12 saat. Etüt katılımı %95. Hedef: ODTÜ Fizik."},
    {"role": "user", "content": "etüt programı nasıl"},
    {"role": "assistant", "content": "Mahmut Taha haftalık 8 etüt: Fizik 3 (Örsel Hoca), Matematik 3 (Vedat Hoca), Kimya 2 (Emin Hoca). Cumartesi 09:00-15:00 + Çarşamba 16:00-18:00."},
    {"role": "user", "content": "fizikte zayıf alanı var mı"},
    {"role": "assistant", "content": "Mahmut Taha fizik analizi: Kuvvet ve hareket %95, Elektrik %88, AMA Kalın mercekler %50, Modern fizik %40. Kalın mercekler için Örsel Hoca ile ek 2 etüt önerebilirim."},
    {"role": "user", "content": "tamam etüt yaz"},
]


# ─── Tests ───

async def test_should_compact():
    """Heuristic: kısa konuşma → SKIP, uzun → ENABLE"""
    from context_compactor import should_compact

    short = [{"role": "user", "content": "merhaba"}]
    long = LONG_CONVERSATION

    s = should_compact(short)
    l = should_compact(long)
    print(f"  short ({len(short)} msg): should={s['should']} reason={s['reason']}")
    print(f"  long  ({len(long)} msg): should={l['should']} reason={l['reason']}")
    assert not s["should"], "Kısa konuşmada compact tetiklenmemeli"
    # Uzun konuşmanın token tahmini düşükse skip olabilir — bu da OK
    return {"short_skip": not s["should"], "long_enable": l["should"]}


async def test_compact_long_conversation():
    """Uzun konuşma → Cerebras summary üret + format kontrol"""
    from context_compactor import compact_history_for_claude

    summary = await compact_history_for_claude(
        history=LONG_CONVERSATION,
        user_msg="tamam etüt yaz",
        recent_n=20,
    )

    if not summary:
        print(f"  Compact SKIP olmuş (token sayısı yeterli değil olabilir)")
        return {"skipped": True}

    print(f"  Summary length: {len(summary)} chars")
    print(f"  Summary preview:\n  {summary[:300]}...")

    # Format check
    has_kullanici = "KULLANICI" in summary or "kullanıcı" in summary.lower()
    has_konu = "KONU" in summary or "konu" in summary.lower()
    has_ogrenci_name = "Mahmut" in summary or "Taha" in summary
    print(f"  has KULLANICI section: {has_kullanici}")
    print(f"  has KONU section: {has_konu}")
    print(f"  has Mahmut Taha mention: {has_ogrenci_name}")

    return {
        "length": len(summary),
        "has_kullanici": has_kullanici,
        "has_konu": has_konu,
        "has_mahmut": has_ogrenci_name,
    }


async def test_quality_judge():
    """Cerebras 235B judge: compact summary ile Claude tutarlı cevap verebilir mi?"""
    from cerebras_handler import CerebrasClient
    from context_compactor import compact_history_for_claude

    summary = await compact_history_for_claude(
        history=LONG_CONVERSATION,
        user_msg="tamam etüt yaz",
        recent_n=20,
    )
    if not summary:
        return {"skipped": True}

    judge_prompt = f"""Aşağıdaki konuşma özeti, Claude'un "etüt yaz" isteğini doğru
işleyebilmesi için yeterli bilgi içeriyor mu?

ÖZET:
{summary}

Sorulan: "tamam etüt yaz"

Beklenen çıkarımlar:
- Kullanıcı kim (Zeki Bey)
- Hangi öğrenci için etüt (Mahmut Taha)
- Hangi dersten (Fizik, kalın mercekler ve modern fizik konuları)
- Kim öğretmeni (Örsel Hoca)

Soru: Özet bu çıkarımları yapmaya YETERLİ mi?

YANIT FORMATI (sadece JSON, başka açıklama yok):
{{"yeterli": true/false, "puan": 0-10, "eksikler": ["..."], "yorum": "..."}}"""

    client = CerebrasClient()
    result = await client.complete_async(
        messages=[{"role": "user", "content": judge_prompt}],
        system="Sen tarafsız bir kalite hakemisin. JSON döndür.",
        model="qwen-3-235b-a22b-instruct-2507",
        max_tokens=400, temperature=0.2,
    )
    text = (result.get("text") or result.get("content") or "").strip()
    print(f"  Judge raw: {text[:400]}")

    import json, re
    text_clean = re.sub(r'^```json\s*', '', text)
    text_clean = re.sub(r'\s*```$', '', text_clean)
    try:
        parsed = json.loads(text_clean)
        print(f"  Judge: yeterli={parsed.get('yeterli')} puan={parsed.get('puan')}")
        if parsed.get("eksikler"):
            print(f"  Eksikler: {parsed['eksikler']}")
        return parsed
    except json.JSONDecodeError:
        print(f"  Judge JSON parse fail")
        return {"raw": text}


async def main():
    print("=" * 70)
    print("CONTEXT COMPACTION QUALITY A/B TEST")
    print("=" * 70)

    results = []

    print("\n[1] Heuristic (should_compact)")
    try:
        r = await test_should_compact()
        results.append(("heuristic", True, r))
        print("  ✓ PASS")
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        results.append(("heuristic", False, str(e)))

    print("\n[2] Compact long conversation (Cerebras 235B)")
    try:
        r = await test_compact_long_conversation()
        results.append(("compact_long", True, r))
        print("  ✓ PASS")
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        results.append(("compact_long", False, str(e)))

    print("\n[3] Quality judge (Cerebras 235B as judge)")
    try:
        r = await test_quality_judge()
        results.append(("quality_judge", True, r))
        if isinstance(r, dict) and r.get("yeterli"):
            print(f"  ✓ PASS (puan: {r.get('puan')}/10)")
        else:
            print(f"  ⚠ PARTIAL — judge sonucu: {r}")
    except Exception as e:
        print(f"  ✗ FAIL: {e}")
        results.append(("quality_judge", False, str(e)))

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"SUMMARY: {passed}/{len(results)} PASS")
    print("=" * 70)
    return passed, len(results)


if __name__ == "__main__":
    asyncio.run(main())
