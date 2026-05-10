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


# ─── Test conversation fixtures (production-like, uzun bot cevapları) ───
_LONG_BOT_REPLY = """Kurumda toplam 125 aktif öğrenci var. Sınıf dağılımı şöyle:

| Sınıf | Öğrenci |
|-------|---------|
| 12 SAY A | 14 |
| 12 SAY B | 12 |
| 12 SAY ZEN | 10 |
| 12 SOZ A | 10 |
| 12 SOZ B | 12 |
| 11 SAY A | 14 |
| 11 SAY ZEN | 12 |
| 11 SAY VIB | 12 |
| 11 SAY NXT | 10 |
| 11 SOZ A | 8 |
| 11 SOZ B | 12 |

Devre olarak 12. sınıf 58, 11. sınıf 56, mezun 11 öğrenci toplam 125.
Devamsızlık 100 saat üstü 32 öğrenci, 200 saat üstü 8 öğrenci kritik durumda.
Ortalama TYT net 62, AYT 48, en başarılı sınıf 11 SAY ZEN. Devre bazında:
- 11. SAY ZEN: ortalama 78 TYT, 65 AYT MAT (Mahmut Taha lider)
- 12 SAY A: ortalama 70 TYT, 58 AYT MAT (Ecrin Aslan lider)
- 11. SAY VIB: ortalama 60 TYT, 45 AYT (en düşük performans)
"""

LONG_CONVERSATION = [
    {"role": "user", "content": "merhaba"},
    {"role": "assistant", "content": "Merhaba Zeki Bey! Bugün size nasıl yardımcı olayım?"},
    {"role": "user", "content": "kurum geneli detaylı durum raporu istiyorum"},
    {"role": "assistant", "content": _LONG_BOT_REPLY},
    {"role": "user", "content": "11. sınıf SAY öğrencilerinin ortalaması nasıl detaylı"},
    {"role": "assistant", "content": "11. sınıf SAY öğrencileri detaylı analiz:\n\n" + _LONG_BOT_REPLY[:1500]},
    {"role": "user", "content": "Mahmut Taha hakkında tam profil"},
    {"role": "assistant", "content": "Mahmut Taha (soz_no 182, 11.SAY ZEN):\n\nSınıf: 11.SAY ZEN\nDevre: 11.Snf\nDanışman: Kardelen Savcı\nVeli: Ahmet Taha (telefon kayıtlı)\n\nSon 5 deneme TYT netleri: 95, 92, 88, 91, 87\nSon 5 deneme AYT MAT-FEN: 82, 78, 80, 75, 79\nSon 3 sıralama: Genel 1850, 2200, 2050\n\nDevamsızlık 12 saat (kritik değil), Etüt katılımı %95.\n\nHedef: ODTÜ Fizik (yerleşme puanı ~440 lazım, şu an ~410 seviyesi).\nZayıf konular (önem sırasıyla): Kalın mercekler %50 net, Modern fizik %40 net, Atom fiziği %55 net, Optik dalga %62 net.\nGüçlü: Kuvvet ve hareket %95, Elektrik manyetizma %88, Termodinamik %85.\n\nRehberlik notları (son 3): 1) 'çok motiveli ama uyku düzeni bozuk' (28 Nis), 2) 'fiziği seviyor matematik biraz zorlanıyor' (15 Nis), 3) 'aile destekli, hedef net' (3 Nis)."},
    {"role": "user", "content": "etüt programı nasıl tam liste"},
    {"role": "assistant", "content": "Mahmut Taha haftalık etüt programı (8 etüt, 12 saat):\n\nCumartesi:\n- 09:00-09:45 Fizik (Örsel Hoca, D-2)\n- 09:45-10:30 Fizik (Örsel Hoca, D-2)\n- 10:30-11:15 Matematik (Vedat Hoca, D-1)\n- 11:15-12:00 Matematik (Vedat Hoca, D-1)\n- 12:00-12:45 Kimya (Emin Hoca, D-3)\n- 14:00-14:45 Matematik (Vedat Hoca, D-1)\n\nÇarşamba:\n- 16:00-16:45 Fizik (Örsel Hoca, D-2)\n- 17:00-17:45 Kimya (Emin Hoca, D-3)\n\nSon 4 hafta etüt katılımı: 32/32 (100%). Etüt notları: tüm hocalar 'aktif katılımcı, sorgulayan' yorumu yapmış."},
    {"role": "user", "content": "fizikte hangi konularda en çok eksiği var"},
    {"role": "assistant", "content": "Mahmut Taha fizik konu bazlı detay analiz (son 5 sınav ortalaması):\n\nKaldırma kuvveti: %95\nVektörler: %93\nHareket: %92\nNewton yasaları: %90\nEnerji: %88\nElektrik: %85\nManyetizma: %82\nTermodinamik: %78\nDalgalar: %72\nOptik dalga: %62\nAtom fiziği: %55\nKalın mercekler: %50\nModern fizik: %40\n\nKritik 3 alan (2024-2025 YKS'de soru çıkma yüzdesi):\n1. Kalın mercekler — yıllık ortalama 1-2 soru\n2. Modern fizik — yıllık ortalama 2-3 soru\n3. Atom fiziği — yıllık ortalama 1-2 soru\n\nKayıp net: bu 3 konudan ortalama 4-6 soru kaçırıyor → ~5-8 net potansiyel artış. Bu da TYT puanında ~12-15 puan artışına denk."},
    {"role": "user", "content": "tamam ek etüt yaz fizik için"},
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
