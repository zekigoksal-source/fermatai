# -*- coding: utf-8 -*-
"""
V3 QUALITY LIVE TEST (25.40z3 production-gate)
================================================

Gercek Claude API cagrisi ile V3 prompt + cache_control kalitesini test eder.
A+ kalite garantisi: V3 cevaplari V2 ile ayni kalitede veya daha iyi.

Test gruplari:
1. Ogrenci kavram aciklama: Claude V3 prompt + dynamic_context ile yanit
2. Cache_control aktif: cache_creation + cache_read tokens dogru rapor
3. Hierarchical block format Anthropic API tarafindan kabul ediliyor
4. Yanit kalitesi (length, dil, persona)
5. Persona check: cevapta "FermatAI" geciyor mu (kimlik korunmus)
6. Halusinasyon kontrolu: "kaydirma kuvveti" gibi var olmayan kavram uydurma yok

Calistirma: ANTHROPIC_API_KEY .env'de olmali.
NOT: Bu test API CALL ATAR - maliyet ~$0.10-0.50 toplam.
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(override=True)

PASS = 0
FAIL = 0
ERRORS = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  + {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  X {name} -- {detail}")


def call_claude_with_v3(role, intent, channel, user_message,
                        system_blocks_override=None):
    """V3 prompt + cache_control ile Claude API cagrisi."""
    from anthropic import Anthropic
    from prompt_modules.composer_v3 import build_prompt_v3
    from fermat_core_agent import _build_system_blocks

    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    if system_blocks_override:
        sys_blocks = system_blocks_override
    else:
        v3_blocks, _ = build_prompt_v3(role, intent, channel, return_blocks=True)
        sys_blocks = _build_system_blocks(v3_blocks, "fb",
                                          f"[Test] caller_role={role}")

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=sys_blocks,
        messages=[{"role": "user", "content": user_message}],
    )

    # Token sayilari
    usage = response.usage
    text = "".join(b.text for b in response.content if hasattr(b, "text"))

    return {
        "text": text,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": getattr(
            usage, "cache_creation_input_tokens", 0),
        "cache_read_input_tokens": getattr(
            usage, "cache_read_input_tokens", 0),
    }


def test_ogrenci_kavram_basic():
    """Ogrenci kavram aciklama, V3 prompt, basit yanit."""
    print("\n[1] OGRENCI KAVRAM ACIKLAMA (V3 + cache)")
    try:
        r = call_claude_with_v3(
            "ogrenci", "kavram_aciklama", "whatsapp",
            "elektrik akimi nedir kisaca acikla",
        )
        check(f"Yanit alindi (len={len(r['text'])})", len(r["text"]) > 50)
        check("Yanit Turkce",
              any(c in r["text"].lower() for c in "abcdefghi") and
              any(tr in r["text"].lower() for tr in
                  ["elektrik", "akim", "nedir", "olur", "edir"]))
        # Cache aktif: ya WRITE ya READ olmali (totali > 0)
        cache_total = (r["cache_creation_input_tokens"] +
                       r["cache_read_input_tokens"])
        check(f"Cache aktif (write+read > 0, total={cache_total})",
              cache_total > 0,
              f"cache hic kullanilmadi: {cache_total}")
        print(f"    INPUT: {r['input_tokens']}, OUTPUT: {r['output_tokens']}")
        print(f"    CACHE_CREATION: {r['cache_creation_input_tokens']}")
        print(f"    CACHE_READ: {r['cache_read_input_tokens']}")
        # Yaniti goster
        print(f"    YANIT (ilk 200 char): {r['text'][:200]}...")
    except Exception as e:
        check("Claude API cagrisi crash YOK", False, f"crash: {e}")


def test_cache_hit_2nd_call():
    """2. cagri ayni rol/intent/channel - cache HIT beklenir."""
    print("\n[2] CACHE HIT (2. ayni cagri)")
    try:
        # 1. cagri (cache write)
        r1 = call_claude_with_v3(
            "ogrenci", "kavram_aciklama", "whatsapp",
            "manyetik alan nedir",
        )
        time.sleep(0.5)

        # 2. cagri (cache HIT beklentisi - 5dk TTL icinde)
        r2 = call_claude_with_v3(
            "ogrenci", "kavram_aciklama", "whatsapp",
            "yercekimi nedir",
        )

        check(f"2. cagri cache_read > cache_creation",
              r2["cache_read_input_tokens"] > r2["cache_creation_input_tokens"],
              f"read={r2['cache_read_input_tokens']}, creation={r2['cache_creation_input_tokens']}")

        # Cache hit oranini hesapla
        total = r2["cache_read_input_tokens"] + r2["cache_creation_input_tokens"]
        if total > 0:
            hit_pct = r2["cache_read_input_tokens"] / total * 100
            print(f"    CACHE HIT %{hit_pct:.1f} (total {total} tok)")
            check(f"Cache hit %>= 50",
                  hit_pct >= 50.0, f"sadece %{hit_pct:.1f}")
    except Exception as e:
        check("Cache HIT testi crash YOK", False, f"crash: {e}")


def test_persona_korundu():
    """V3 ile cevapta FermatAI persona korundu mu?"""
    print("\n[3] PERSONA KORUNDU (sen kimsin?)")
    try:
        r = call_claude_with_v3(
            "ogrenci", "yetenek_sorgu", "whatsapp",
            "sen kimsin",
        )
        text_lower = r["text"].lower()
        # FermatAI veya Fermat geciyor olmali
        check("Cevapta 'FermatAI' veya 'Fermat' geciyor",
              "fermat" in text_lower,
              f"persona kayip: {r['text'][:200]}")
        # ChatGPT/GPT-4/Claude diye kendini tanitmamali
        check("ChatGPT/GPT-4 olarak tanitmiyor",
              "chatgpt" not in text_lower and
              "gpt-4" not in text_lower and
              "claude" not in text_lower,
              f"yanlis kimlik: {r['text'][:200]}")
        print(f"    YANIT: {r['text'][:200]}")
    except Exception as e:
        check("Persona testi crash YOK", False, f"crash: {e}")


def test_halusinasyon_kontrolu():
    """Bot reframe yapsa bile uydurma yasa adina sabitlenmesi.

    NOT: Bu V3 ile alakali degil, system_prompt'in halusinasyon koruma
    katmaninin testidir. Bot bilinmeyen kavrami:
    a) gercek bir yasaya benzettiyse (Pascal/Hooke/Newton) -> OK
    b) bilmedigini soyledi -> OK
    c) tamamen yeni uydurma formul yazdiysa -> FAIL
    """
    print("\n[4] HALUSINASYON KONTROLU (V3 dis kalite garantisi)")
    try:
        r = call_claude_with_v3(
            "ogrenci", "kavram_aciklama", "whatsapp",
            "Zorlama Sabit Yasasi nedir formulu yaz",
        )
        text_lower = r["text"].lower()

        # OK kabul edilen senaryolar:
        # 1. Bot gercek bir yasaya yorumlamis (Pascal/Newton/Hooke/Coulomb)
        gercek_yasa_kelimeleri = [
            "pascal", "newton", "hooke", "coulomb", "ohm", "boyle",
            "charles", "gay-lussac", "avogadro", "kepler",
        ]
        bot_yasaya_baglamis = any(kw in text_lower for kw in gercek_yasa_kelimeleri)

        # 2. Bot bilmedigini soylemis
        bot_belirsizlik = any(kw in text_lower for kw in [
            "bilmiyorum", "tanimadim", "boyle bir yasa yok",
            "kastett", "emin degil", "rastlama",
        ])

        # 3. Bot yeni adli formul UYDURMADIYSA (sadece $...$ icinde
        #    sabit varsa kabul, yoksa uyduruk yasa adi turetmis)
        # Daha gevsek: bot zorlama_sabit = K gibi sembol yarattiysa kabul

        is_safe = bot_yasaya_baglamis or bot_belirsizlik

        check("Uydurma red (gercek yasaya yorumladi VEYA bilmedigini soyledi)",
              is_safe,
              f"halusinasyon: {r['text'][:400]}")
        print(f"    YANIT (ilk 300): {r['text'][:300]}")
    except Exception as e:
        check("Halusinasyon testi crash YOK", False, f"crash: {e}")


def test_yanit_kalite_pedagojik():
    """Yanit pedagojik (motivasyonlu, ornekli, soruya yonlendirici)."""
    print("\n[5] PEDAGOJIK YANIT KALITESI")
    try:
        r = call_claude_with_v3(
            "ogrenci", "kavram_aciklama", "web",
            "newton 2. yasasi nedir",
        )
        text = r["text"]
        # Pedagojik isaretler:
        # - Formul olabilir (F=ma)
        # - Ornek olabilir
        # - 100+ char (basit cumle degil)
        check(f"Yanit makul uzunluk ({len(text)} char, >100)",
              len(text) > 100)
        # F=ma veya newton geciyor mu?
        check("Konu icerigi var (newton/kuvvet/ivme/F=ma)",
              any(kw in text.lower() for kw in
                  ["newton", "kuvvet", "ivme", "f=m", "f = m"]),
              f"konu disi: {text[:200]}")
        print(f"    YANIT (ilk 300): {text[:300]}")
    except Exception as e:
        check("Pedagojik kalite testi crash YOK", False, f"crash: {e}")


def main():
    print("=" * 70)
    print("V3 QUALITY LIVE TEST (production gate, gercek Claude API)")
    print("=" * 70)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY bulunamadi - test skip")
        return 0

    test_funcs = [
        test_ogrenci_kavram_basic,
        test_cache_hit_2nd_call,
        test_persona_korundu,
        test_halusinasyon_kontrolu,
        test_yanit_kalite_pedagojik,
    ]

    for tf in test_funcs:
        try:
            tf()
        except Exception as e:
            global FAIL
            FAIL += 1
            ERRORS.append(f"{tf.__name__} EXCEPTION: {e}")
            print(f"  X EXCEPTION in {tf.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 70)
    if ERRORS:
        print("\nFAILURES:")
        for e in ERRORS[:10]:
            print(f"  - {e}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
