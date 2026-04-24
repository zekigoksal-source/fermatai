"""
FermatAI Ollama Response Quality Test
======================================
Yerel LLM'in (qwen2.5:7b) gercek yanıtlarını test eder.
Her yanıt Claude tarafından kalite kontrolünden geçirilir.

Test edilen:
  1. Akademik konu açıklamaları (fizik, mat, bio, edebiyat)
  2. Motivasyon/sohbet diyalogları
  3. Genel öğrenci sohbeti
  4. Tehlikeli sınır durumları (veri gerektiren ama Ollama'ya düşen)
"""

import asyncio
import io
import json
import os
import re
import sys
import time

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, '.')


# ═══════════════════════════════════════════════════════════════════
# YERELE GIDECEK SORULAR
# ═══════════════════════════════════════════════════════════════════

OLLAMA_TESTS = [
    # ── Akademik Konu Açıklama ──
    {
        "msg": "kaldirma kuvveti nedir kisaca acikla",
        "role": "ogrenci", "name": "Ali",
        "category": "konu_aciklama",
        "desc": "Fizik - kaldırma kuvveti",
    },
    {
        "msg": "turev nasil alinir basit bi sekilde anlat",
        "role": "ogrenci", "name": "Zeynep",
        "category": "konu_aciklama",
        "desc": "Mat - turev",
    },
    {
        "msg": "mitoz ve mayoz arasindaki fark ne",
        "role": "ogrenci", "name": "Ece",
        "category": "konu_aciklama",
        "desc": "Bio - mitoz/mayoz",
    },
    {
        "msg": "newton'un hareket yasalarini acikla",
        "role": "ogrenci", "name": "Burak",
        "category": "konu_aciklama",
        "desc": "Fizik - Newton yasalari",
    },
    {
        "msg": "logaritma ne ise yarar gercek hayatta",
        "role": "ogrenci", "name": "Selin",
        "category": "konu_aciklama",
        "desc": "Mat - logaritma",
    },
    {
        "msg": "osmanlida duraklama donemi neden basladi",
        "role": "ogrenci", "name": "Mert",
        "category": "konu_aciklama",
        "desc": "Tarih - Osmanlı duraklama",
    },
    {
        "msg": "paragraf sorularini nasil cozerim taktik ver",
        "role": "ogrenci", "name": "Ayse",
        "category": "konu_aciklama",
        "desc": "Turkce - paragraf taktik",
    },

    # ── Motivasyon / Duygusal ──
    {
        "msg": "canim ders calismak istemiyor ne yapmaliyim",
        "role": "ogrenci", "name": "Defne",
        "category": "motivasyon",
        "desc": "Motivasyon dusuk - ders istememe",
    },
    {
        "msg": "sinav stresi cok fazla bunalimdayim",
        "role": "ogrenci", "name": "Kaan",
        "category": "motivasyon",
        "desc": "Stres - bunalim",
    },
    {
        "msg": "arkadaslarim cok iyi yapiyor ben yapamiyorum",
        "role": "ogrenci", "name": "Elif",
        "category": "motivasyon",
        "desc": "Karsilastirma kaygi",
    },

    # ── Genel Sohbet ──
    {
        "msg": "bugun hava cok guzel di mi",
        "role": "ogrenci", "name": "Can",
        "category": "sohbet",
        "desc": "Sohbet - hava durumu",
    },
    {
        "msg": "en sevdigim ders fizik",
        "role": "ogrenci", "name": "Arda",
        "category": "sohbet",
        "desc": "Sohbet - favori ders",
    },
    {
        "msg": "hocam siz robot musunuz gercek mi",
        "role": "ogrenci", "name": "Yusuf",
        "category": "sohbet",
        "desc": "Sohbet - robot mu sorusu",
    },
    {
        "msg": "bugun okul cok yorucuydu",
        "role": "ogrenci", "name": "Beren",
        "category": "sohbet",
        "desc": "Sohbet - yorgunluk",
    },

    # ── Ogretmen sohbet ──
    {
        "msg": "bugun cok verimli bi gun gecirdim",
        "role": "ogretmen", "name": "Vedat Hoca",
        "category": "sohbet",
        "desc": "Ogretmen sohbet - olumlu",
    },
    {
        "msg": "ogrencilerim cok sikiliyor derslerde ne yapmaliyim",
        "role": "ogretmen", "name": "Kardelen Hoca",
        "category": "sohbet",
        "desc": "Ogretmen danismanlik - ogrenci sikintisi",
    },
]


# ═══════════════════════════════════════════════════════════════════
# KALİTE KRİTERLERİ
# ═══════════════════════════════════════════════════════════════════

QUALITY_CHECKS = {
    "turkish": "Cevap tamamen Turkce mi? (Ingilizce kelime var mi?)",
    "no_hallucination": "Uydurma veri/sayı/isim var mi?",
    "formatting": "WhatsApp formatlama kullanilmis mi? (*bold*, _italic_, emoji, liste)",
    "length": "Cevap yeterli uzunlukta mi? (en az 3 cumle)",
    "pedagogical": "Egitimci tonu var mi? (soru soruyor, yonlendiriyor, destek)",
    "no_technical": "Teknik sızıntı var mı? (API, token, model, database)",
    "dialog": "Diyalog devam ettirici mi? (soru soruyor, ilgi uyandırıyor)",
}

def analyze_response(response: str, category: str) -> dict:
    """Ollama yanıtını analiz et."""
    issues = []
    resp_lower = response.lower()

    # 1. Turkce kontrolu
    # "can", "her", "ne", "an", "ok" gibi Turkce'de de kullanilan kelimeler haric
    eng_words = re.findall(r'\b(the|are|was|were|have|has|been|will|would|could|should|may|might|let|help|you|with|from|about|here|there|however|therefore|welcome|certainly|absolutely|of course|sorry|regarding|additionally|performance|optimize|insights|dive|explore|based on|i think|i can|you can|please|what|which|those)\b', resp_lower)
    if eng_words:
        issues.append(f"INGILIZCE: {', '.join(list(set(eng_words))[:5])}")

    # 2. CJK karakter (Çince karışma)
    cjk = [c for c in response[:300] if ord(c) > 0x4E00 and ord(c) < 0x9FFF]
    if cjk:
        issues.append(f"CINCE: {''.join(cjk[:10])}")

    # 3. Halüsinasyon: uydurma veri
    if category in ("konu_aciklama", "sohbet", "motivasyon"):
        if re.search(r'\b\d{2,3}[.,]\d\s*(net|puan|saat)', resp_lower):
            issues.append("HALUSINASYON: uydurma net/puan")
        if re.search(r'(1\.\s*sinif|2\.\s*sinif|3\.\s*sinif)', resp_lower):
            issues.append("HALUSINASYON: uydurma sinif listesi")

    # 4. Teknik sızıntı
    tech_leaks = [w for w in ["api", "token", "model", "database", "veritaban", "postgresql",
                               "claude", "ollama", "anthropic", "prompt", "system", "json",
                               "error", "exception", "null", "none", "undefined"]
                  if w in resp_lower and w not in ("model", "system")]  # bazıları context'te olabilir
    # "api" false positive kontrolü
    tech_leaks = [w for w in tech_leaks if not (w == "api" and "yapilmaktadir" in resp_lower)]
    if tech_leaks:
        issues.append(f"TEKNIK: {', '.join(tech_leaks)}")

    # 5. Formatlama
    has_bold = '*' in response
    has_emoji = bool(re.search(r'[\U0001F300-\U0001F9FF\U00002700-\U000027BF\U00002600-\U000026FF]', response))
    has_list = bool(re.search(r'(^|\n)\s*[-•]\s', response))
    has_newline = '\n' in response
    format_score = sum([has_bold, has_emoji, has_list, has_newline])

    # 6. Uzunluk
    sentences = len(re.findall(r'[.!?]\s', response)) + 1
    if sentences < 2:
        issues.append("COK_KISA: tek cumle")
    if len(response) < 50:
        issues.append("COK_KISA: 50 char'dan az")

    # 7. Diyalog devam ettirme
    has_question = '?' in response
    has_followup = bool(re.search(r'(ister\s*mi|ister\s*misin|baslayalim|konusalim|soyle|anlat|yazabilir|sorabilir)', resp_lower))

    # Genel skor
    score = 10
    score -= len(issues) * 2
    score -= max(0, 2 - format_score)  # format eksikliği
    if not has_question and not has_followup:
        score -= 1  # diyalog kapanık
    score = max(0, min(10, score))

    grade = "A" if score >= 8 else "B" if score >= 6 else "C" if score >= 4 else "D" if score >= 2 else "F"

    return {
        "grade": grade,
        "score": score,
        "issues": issues,
        "format": {"bold": has_bold, "emoji": has_emoji, "list": has_list, "newline": has_newline},
        "has_question": has_question,
        "has_followup": has_followup,
        "length": len(response),
        "sentences": sentences,
    }


async def run_tests():
    from llm_router import LLMRouter

    router = LLMRouter()
    if not router.is_local_available:
        print("HATA: Ollama erisilemedi!")
        return

    print("=" * 80)
    print("  OLLAMA GERCEK YANIT KALİTE TESTİ")
    print(f"  Model: {os.getenv('OLLAMA_MODEL', 'qwen2.5:7b')}")
    print("=" * 80)

    all_results = []

    for t in OLLAMA_TESTS:
        msg = t["msg"]
        name = t["name"]
        category = t["category"]
        desc = t["desc"]

        # Basit system prompt (Ollama'nın alacağı)
        system = router._LOCAL_SYSTEM + f"\nArayan: {name}\nRol: {t['role']}"

        messages = [{"role": "user", "content": msg}]

        try:
            start = time.time()
            response = router.chat_local(messages, system)
            elapsed = time.time() - start
        except Exception as e:
            print(f"  [!!] HATA    {desc}: {e}")
            continue

        # Analiz
        analysis = analyze_response(response, category)
        grade = analysis["grade"]
        issues = analysis["issues"]
        fmt = analysis["format"]

        # Gorsel cikti
        preview = response[:120].replace('\n', ' ')
        fmt_icons = ("B" if fmt["bold"] else ".") + ("E" if fmt["emoji"] else ".") + ("L" if fmt["list"] else ".") + ("N" if fmt["newline"] else ".")
        q_icon = "?" if analysis["has_question"] else " "
        time_str = f"{elapsed:.1f}s"

        if issues:
            icon = "[!!]"
        elif grade in ("A", "B"):
            icon = "[OK]"
        else:
            icon = "[--]"

        print(f"\n  {icon} [{grade}] [{fmt_icons}] [{q_icon}] {time_str:5s} | {desc}")
        print(f"       \"{preview}...\"")
        if issues:
            for iss in issues:
                print(f"       SORUN: {iss}")

        all_results.append({
            "desc": desc,
            "msg": msg,
            "response": response,
            "grade": grade,
            "issues": issues,
            "elapsed": elapsed,
            "category": category,
        })

    # OZET
    print(f"\n{'='*80}")
    print("OZET")
    print(f"{'='*80}")

    grades = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    all_issues = []
    for r in all_results:
        grades[r["grade"]] += 1
        if r["issues"]:
            all_issues.extend([(r["desc"], iss) for iss in r["issues"]])

    total = len(all_results)
    print(f"  Toplam: {total} test")
    print(f"  A: {grades['A']} | B: {grades['B']} | C: {grades['C']} | D: {grades['D']} | F: {grades['F']}")
    avg_time = sum(r["elapsed"] for r in all_results) / max(len(all_results), 1)
    print(f"  Ortalama yanit suresi: {avg_time:.1f}s")

    if all_issues:
        print(f"\n  SORUNLAR ({len(all_issues)}):")
        for desc, iss in all_issues:
            print(f"    [{desc}] {iss}")

    # Kotu yanitlari dosyaya kaydet — sonra Claude ile iyilestirmek icin
    bad_responses = [r for r in all_results if r["grade"] in ("C", "D", "F") or r["issues"]]
    if bad_responses:
        with open("ollama_quality_issues.json", "w", encoding="utf-8") as f:
            json.dump(bad_responses, f, ensure_ascii=False, indent=2)
        print(f"\n  Kotu yanitlar ollama_quality_issues.json'a kaydedildi ({len(bad_responses)} adet)")

    return all_results


if __name__ == "__main__":
    asyncio.run(run_tests())
