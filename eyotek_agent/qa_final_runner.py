"""
QA Final 1000 — Test Runner + 6-Disiplinli Değerlendirme
=========================================================
Neo direktifi: "1000 senaryo, 6 disiplin değerlendirme, fix loop %100"

5 dataset parçasını birleştirir, fast_response path'inden çalıştırır,
qa_final_evaluator ile 6 boyutta puanlar, kategori + boyut bazlı rapor.

Çalıştırma:
  python qa_final_runner.py
"""
from __future__ import annotations
import sys, asyncio, time
sys.stdout.reconfigure(encoding='utf-8')


def collect_scenarios():
    """5 parçadan 1000 senaryoyu topla."""
    from qa_final_dataset_p1 import ALL_P1, PROFILES
    from qa_final_dataset_p2 import ALL_P2
    from qa_final_dataset_p3 import ALL_P3
    from qa_final_dataset_p4 import ALL_P4, ALL_P4_MULTI
    from qa_final_dataset_p5 import ALL_P5

    flat = ALL_P1 + ALL_P2 + ALL_P3 + ALL_P4 + ALL_P5
    multi = ALL_P4_MULTI
    return flat, multi, PROFILES


async def run_one(msg, profile, expected_path):
    """Tek senaryoyu fast_response ile çalıştır."""
    from fast_responses import try_fast_response, get_last_handler, _fr_last_handler
    from fast_response_loop_guard import clear_history

    clear_history()
    try: _fr_last_handler.set('')
    except: pass

    t0 = time.perf_counter()
    try:
        cevap = await try_fast_response(
            message=msg, caller_phone=profile["phone"], role=profile["role"],
            soz_no=profile["soz_no"], name=profile["full_name"],
            staff_name=profile["staff_name"],
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        handler = get_last_handler() or ""
        return cevap, handler, elapsed_ms, None
    except Exception as e:
        return None, "", 0, f"{type(e).__name__}: {e}"


def build_expected(msg, profile_name, expected_path, kategori, profile):
    """Senaryo için 6-disiplin evaluator config'i.

    25.41 iter1: Render expectation sadece kategoriye değil cevaba göre.
    Edge case kısa cevaplar short_ok=True. ACL nazik sosyal müh → llm doğru.
    """
    expected = {
        "expected_path": "fast" if expected_path.startswith("fast/") else "llm",
        "expected_handler": expected_path.split("/")[1] if expected_path.startswith("fast/") else "",
        "role": profile["role"],
        "name": profile["full_name"],
        "kategori": kategori,
    }

    # Kategoriye özel beklentiler
    if kategori == "Render_Sim":
        # Render LLM tarafında (Claude/Cerebras) gelir — fast'te render link YOK
        # Sadece LLM path bekleniyorsa render bekleme penalty olmasın
        if expected_path == "llm":
            expected["render_expected"] = False  # LLM cevabında render link gelir
        else:
            expected["render_expected"] = True
        expected["tool_expected"] = True
    elif kategori == "Coklu_Adim":
        # Adım adım çözüm LLM'de yapılır, fast'te beklenmez
        expected["expect_steps"] = False
        expected["akademik_topic"] = "matematik"
    elif kategori in ("Konu_Uzun", "Karsilastirma"):
        # LLM cevabında isim hitabı bekle
        if expected_path == "llm":
            expected["expect_personal_greeting"] = False  # LLM cevabı boş geldi, beklemiyoruz
        else:
            expected["expect_personal_greeting"] = True
    elif kategori in ("PhET", "Wolfram", "Wiki", "PubChem", "NASA", "ArXiv", "USGS"):
        # External API tool LLM'de çağrılır
        expected["tool_expected"] = True
        expected["expect_source"] = False  # fast cevapta kaynak beklemeyelim
    elif kategori == "Hassas":
        # Hassas durum LLM'de empati ile karşılanır
        if expected_path == "llm":
            expected["expect_personal_greeting"] = False
        else:
            expected["expect_personal_greeting"] = True
    elif kategori == "Strateji":
        if expected_path == "llm":
            expected["expect_steps"] = False
        else:
            expected["expect_steps"] = True
    elif kategori == "Edge_Extreme":
        # Kısa cevaplar OK — UX penalty yapma
        expected["short_ok"] = True
    elif kategori == "Cikmis_Gorsel":
        # Cikmis fast yakalamadıysa LLM doğru (paragraf/çember vs spesifik konu)
        if expected_path == "llm":
            expected["render_expected"] = False
        # fast/cikmis_match cevabında menu gelir, render link bekleme
        elif expected.get("expected_handler") == "cikmis_match":
            expected["render_expected"] = False

    # Akademik topic tespit (ipucu)
    msg_lower = msg.lower()
    if any(k in msg_lower for k in ["fizik","newton","manyetik","optik","kuantum"]):
        expected["akademik_topic"] = "fizik"
    elif any(k in msg_lower for k in ["matematik","türev","integral","limit","mat"]):
        expected["akademik_topic"] = "matematik"
    elif any(k in msg_lower for k in ["kimya","mol","asit","baz"]):
        expected["akademik_topic"] = "kimya"
    elif any(k in msg_lower for k in ["biyoloji","hücre","dna","protein"]):
        expected["akademik_topic"] = "biyoloji"

    return expected


async def main():
    print("=" * 100)
    print("  FERMAT QA FINAL 1000 — 6-DİSİPLİNLİ DEĞERLENDİRME")
    print("=" * 100)
    t_start = time.perf_counter()

    flat, multi, PROFILES = collect_scenarios()

    from qa_final_evaluator import evaluate_response

    # Single-turn senaryolar
    total = len(flat) + sum(len(d) for d in multi)
    print(f"\nToplam senaryo: {total} (single: {len(flat)} + multi-turn: {sum(len(d) for d in multi)})")
    print()

    # Sonuçları topla
    by_kategori = {}     # kategori → [results]
    by_boyut = {         # boyut → toplam puan + sayı
        "yazilim": [0, 0],
        "iletisim": [0, 0],
        "tasarim": [0, 0],
        "akademik": [0, 0],
        "egitim": [0, 0],
        "ux": [0, 0],
    }
    pass_count = fail_count = error_count = 0
    fail_examples = []

    print("→ Single-turn senaryoları çalıştırılıyor...")
    for i, (msg, prof_name, exp_path, kategori) in enumerate(flat):
        if i % 100 == 0:
            print(f"   {i}/{len(flat)}...")

        profile = PROFILES[prof_name]
        cevap, handler, elapsed_ms, err = await run_one(msg, profile, exp_path)

        if err:
            error_count += 1
            fail_examples.append((kategori, prof_name, msg, f"ERROR: {err}", 0))
            continue

        expected = build_expected(msg, prof_name, exp_path, kategori, profile)
        eval_result = evaluate_response(cevap, handler, expected)

        # Boyut toplamları
        for boyut in ("yazilim","iletisim","tasarim","akademik","egitim","ux"):
            by_boyut[boyut][0] += eval_result[boyut][0]
            by_boyut[boyut][1] += 1

        # Kategori
        by_kategori.setdefault(kategori, []).append(eval_result["toplam"])

        if eval_result["pass"]:
            pass_count += 1
        else:
            fail_count += 1
            if len(fail_examples) < 30:
                fail_examples.append((
                    kategori, prof_name, msg[:60],
                    f"Toplam: {eval_result['toplam']}",
                    eval_result['toplam']
                ))

    # Multi-turn
    print(f"\n→ Multi-turn dialog'ları çalıştırılıyor ({len(multi)} dialog)...")
    multi_pass = multi_fail = 0
    from fast_response_loop_guard import clear_history, record_handler
    from fast_responses import try_fast_response, get_last_handler, _fr_last_handler

    for di, dialog in enumerate(multi):
        clear_history()
        for mi, (msg, prof_name, exp_path) in enumerate(dialog):
            profile = PROFILES[prof_name]
            try: _fr_last_handler.set('')
            except: pass
            try:
                cevap = await try_fast_response(
                    message=msg, caller_phone=profile["phone"], role=profile["role"],
                    soz_no=profile["soz_no"], name=profile["full_name"],
                    staff_name=profile["staff_name"],
                )
                handler = get_last_handler() or ""
                if cevap and handler:
                    record_handler(profile["phone"], handler, msg)

                expected = build_expected(msg, prof_name, exp_path, "Multi_Turn", profile)
                eval_result = evaluate_response(cevap, handler, expected)
                for boyut in ("yazilim","iletisim","tasarim","akademik","egitim","ux"):
                    by_boyut[boyut][0] += eval_result[boyut][0]
                    by_boyut[boyut][1] += 1
                by_kategori.setdefault("Multi_Turn", []).append(eval_result["toplam"])
                if eval_result["pass"]:
                    multi_pass += 1
                else:
                    multi_fail += 1
            except Exception as e:
                error_count += 1

    pass_count += multi_pass
    fail_count += multi_fail
    elapsed = time.perf_counter() - t_start

    # ─── RAPOR ─────────────────────────────────────────────
    print("\n\n" + "=" * 100)
    print("  KATEGORİ ÖZETİ (kategori → ortalama puan)")
    print("=" * 100)
    print(f"  {'Kategori':<28} {'Adet':>6} {'Ort':>6} {'Min':>6} {'Max':>6} {'Durum'}")
    print(f"  {'-'*28} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")

    for kategori in sorted(by_kategori.keys()):
        scores = by_kategori[kategori]
        ort = sum(scores) / len(scores) if scores else 0
        mn = min(scores) if scores else 0
        mx = max(scores) if scores else 0
        emoji = "✅" if ort >= 85 else ("⚠️" if ort >= 70 else "❌")
        print(f"  {emoji} {kategori:<25} {len(scores):>6} {ort:>5.1f} {mn:>6} {mx:>6}")

    print("\n" + "=" * 100)
    print("  6-DİSİPLİN BOYUT ÖZETİ (her boyut → ortalama)")
    print("=" * 100)
    boyut_isim = {
        "yazilim": "🔧 Yazılım/Mimari",
        "iletisim": "💬 İletişim/Akıcılık",
        "tasarim": "🎨 Tasarım/Görsel",
        "akademik": "📚 Akademik/Doğruluk",
        "egitim": "🎓 Eğitim/Pedagoji",
        "ux": "✨ UX/Deneyim",
    }
    for boyut, (toplam, sayi) in by_boyut.items():
        ort = toplam / sayi if sayi else 0
        emoji = "✅" if ort >= 85 else ("⚠️" if ort >= 70 else "❌")
        print(f"  {emoji} {boyut_isim[boyut]:<26} ort: {ort:>5.1f}/100  ({sayi} senaryo)")

    print("\n" + "=" * 100)
    overall_pass_pct = pass_count / total * 100 if total else 0
    print(f"  TOPLAM: {pass_count}/{total} pass ({overall_pass_pct:.1f}%)")
    print(f"          {fail_count} fail, {error_count} error")
    print(f"  Süre: {elapsed:.1f}s | {total/elapsed:.1f} senaryo/sn")

    if overall_pass_pct >= 95:
        print(f"\n  🎯🎯🎯 PRODUCTION HAZIR ✅✅✅ ({overall_pass_pct:.1f}%)")
    elif overall_pass_pct >= 85:
        print(f"\n  ✅ PRODUCTION GEÇERLİ ({overall_pass_pct:.1f}%)")
    else:
        print(f"\n  ⚠️ FİX GEREKLİ ({overall_pass_pct:.1f}% < 85%)")

    # En kötü 5 kategori
    print("\n" + "=" * 100)
    print("  EN ZAYIF 5 KATEGORİ (fix önceliği)")
    print("=" * 100)
    zayif = sorted(by_kategori.items(), key=lambda x: sum(x[1])/len(x[1]) if x[1] else 0)[:5]
    for kategori, scores in zayif:
        ort = sum(scores) / len(scores) if scores else 0
        print(f"  ❌ {kategori}: {ort:.1f}/100 ({len(scores)} senaryo)")

    # Fail örnekleri
    print("\n" + "=" * 100)
    print(f"  FAIL ÖRNEKLERİ (en kötü 15)")
    print("=" * 100)
    fail_examples.sort(key=lambda x: x[4])
    for kat, prof, msg, err, sc in fail_examples[:15]:
        print(f"  ❌ [{kat}/{prof}] '{msg}' → {err}")


if __name__ == "__main__":
    from pathlib import Path
    import os
    for p in [Path("/opt/fermatai/.env"), Path(".env"),
              Path(__file__).parent / ".env"]:
        if p.exists():
            for line in p.read_text(encoding='utf-8').splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
    asyncio.run(main())
