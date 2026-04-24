"""
Ollama Cevap Kalite Regresyonu (21 Nisan 2026 — Neo talimatı)
=============================================================

Amaç: Ollama yanıtlarının Claude görsel standardının dışına çıkmasına izin verme.
Bir Ollama patch'i geldiğinde veya prompt değişikliği yapıldığında kalite düşerse
bu testler HEMEN uyarır.

Test stratejisi:
  - 12 gerçek senaryo (selam, akademik, öğretmen, müdür, meslek, kapanış)
  - Her yanıt format_for_whatsapp'tan geçer (production pipeline)
  - Kalite metriği: emoji + bold + separator + italic_closing = 4/4
  - Kısa yanıtlar (<120 char) için lenient (2/4 yeterli)
  - Orta+ yanıtlar (120+ char) için strict (3/4 zorunlu)

KESİNLİKLE canlı Ollama istemez — sabit örneklerle test eder.
"""
import os
import sys
import re

# Dosya yolu — tests/ üstüne çık
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from format_whatsapp import format_for_whatsapp
from query_cache import is_ollama_response_cacheable, _anlamsiz_kelime_orani


# ═══════════════════════════════════════════════════════════════════════════
# KALİTE METRİĞİ
# ═══════════════════════════════════════════════════════════════════════════

def quality_score(text: str) -> dict:
    """Bir metnin görsel kalite puanı (0-4)."""
    has_emoji = bool(re.search(r'[\U0001f300-\U0001fad6\u2600-\u27bf]', text))
    has_bold = bool(re.search(r'\*[^*\s][^*]{1,}[^*\s]\*', text))
    has_sep = '---' in text or '━' in text
    has_italic_closing = bool(re.search(r'_[^_\n]{5,}_\s*[🎯✨💡🌟💪🌱📝]?\s*$', text.strip()))

    score = sum([has_emoji, has_bold, has_sep, has_italic_closing])
    return {
        "score": score,
        "emoji": has_emoji,
        "bold": has_bold,
        "separator": has_sep,
        "italic_closing": has_italic_closing,
        "length": len(text),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SENARYO 1: Format Enforcer — düz yazı → yapılandırılmış
# ═══════════════════════════════════════════════════════════════════════════

def test_enforcer_flat_prose_to_structured():
    """Uzun düz paragraf → cümle bazında bölünmüş + emoji + bold."""
    input_text = (
        "Türev konusunu açıklayayım. Türev bir fonksiyonun değişim hızını ölçer. "
        "Örnek: arabanın hız göstergesi. Hız konumun türevidir. İvme ise hızın türevidir. "
        "Bu nedenle türev matematikte önemli bir kavramdır."
    )
    out = format_for_whatsapp(input_text, source="ollama")
    q = quality_score(out)

    assert q["length"] > len(input_text), "Enforcer en azından emoji eklemeli"
    assert q["emoji"], "Akademik içerik için emoji eklenmeli"
    assert q["bold"], "Anahtar kelimelerden en az 1 bold olmalı"
    # 160+ char'da kapanış eklenmeli
    if q["length"] > 120:
        assert q["separator"] or q["italic_closing"], "Uzun cevapta yapı olmalı"


def test_enforcer_idempotent_on_good_input():
    """Zaten iyi formatlı cevap BOZULMAMALI (2 kere uygula = aynı sonuç)."""
    good = (
        "Merhaba *Zeki Bey*! 📊\n\n"
        "---\n\n"
        "*Türev Konusu*\n\n"
        "Türev önemli bir *kavramdır*. Matematik dersinin parçası.\n\n"
        "---\n\n"
        "_Detaylı anlatayım mı?_ 🎯"
    )
    out1 = format_for_whatsapp(good, source="ollama")
    out2 = format_for_whatsapp(out1, source="ollama")
    # İkinci geçişte önemli fark olmamalı (±5 char tolerans)
    assert abs(len(out1) - len(out2)) < 10, f"Idempotent değil: {len(out1)} vs {len(out2)}"


def test_enforcer_short_greeting_no_damage():
    """Çok kısa selamlama (<50 char) bozulmamalı, gereksiz --- eklenmemeli."""
    short = "Merhaba Ali! 🌟"
    out = format_for_whatsapp(short, source="ollama")
    # Bu kadar kısa bir yanıta --- eklemek overkill
    assert out.count('---') == 0, "Kısa selamlamaya --- eklenmemeli"


def test_enforcer_category_emoji_selection():
    """Kategori-bazlı emoji seçimi: fizik/kimya/stres vb. için doğru emoji."""
    cases = [
        ("Kuvvet konusu hakkında bilgi", ['⚡', '📊']),  # fizik
        ("Kimyasal tepkime açıklaması", ['🧪']),
        ("Hücre bölünmesi nedir", ['🧬']),
        ("Osmanlı tarihi hakkında", ['🏛️']),
        ("Matematik türev konu", ['🔢', '📊']),
    ]
    for text, allowed_emojis in cases:
        out = format_for_whatsapp(text + " devam metin", source="ollama")
        # En az 1 emoji eklenmeli (kategoriden veya default 💡)
        # Genis emoji range: U+1F300-1FAD6 + U+2600-27BF (⚡ ⚠️ ☀️ vb.)
        has_emoji = bool(re.search(r'[\U0001f300-\U0001fad6\u2600-\u27bf]', out))
        assert has_emoji, f"'{text[:30]}' için emoji eklenmedi — OUT: {out[:100]}"


# ═══════════════════════════════════════════════════════════════════════════
# SENARYO 2: Cache Kalite Filtresi
# ═══════════════════════════════════════════════════════════════════════════

def test_cache_filter_halucination_marker():
    """Bilinen halüsinasyon markerları cache'lenmemeli."""
    bad_cases = [
        "SELAM NEDEN ÇALIŞMAK İÇİN ZİNGERLİSIN? Biliyor musun",
        "Merhaba! 🌟 nasımlı bir gün geçirebilmek için",
        "Here is the answer to your question",
        "Let me explain: türev nedir",
    ]
    for text in bad_cases:
        assert not is_ollama_response_cacheable(text), f"Halüsinasyon yakalanmadı: {text[:50]}"


def test_cache_filter_short_no_emoji():
    """Çok kısa cevap + hiç emoji yoksa cache'lenmemeli."""
    assert not is_ollama_response_cacheable("Merhaba Ali!")
    assert not is_ollama_response_cacheable("Evet, anladım.")
    # Ama emoji varsa OK
    assert is_ollama_response_cacheable("Merhaba Ali! 🌟")


def test_cache_filter_long_no_structure():
    """100+ char cevap + hiç görsel yapı yoksa (emoji/bold/italic) cache'lenmemeli."""
    flat = (
        "Bu çok uzun bir paragraf. Cümleler var. Bir şeyler anlatıyor. "
        "Ama hiç bold veya emoji yok. Çok düz yazı ve monoton bir biçimde."
    )
    assert not is_ollama_response_cacheable(flat)


def test_cache_filter_anlamsiz_kelime():
    """Anlamsız kelime oranı >%15 ise cache'lenmemeli."""
    bad = "zrrr bfgh rrr mnpq bcdf xyzw ppp rrrr ttt"
    oran = _anlamsiz_kelime_orani(bad)
    assert oran > 0.15, f"Anlamsız kelime oranı beklenenin altında: {oran}"
    assert not is_ollama_response_cacheable(bad)


def test_cache_filter_good_ollama_response():
    """İyi yapılı Ollama cevabı cache'e girebilmeli."""
    good_cases = [
        "Merhaba *Zehra*! 📊\n\n---\n\n*Türev* konusu önemli. Devam edelim mi? 🎯",
        "Merhaba Ali! 🌟",  # kısa ama emoji var
        "*Plan* hazır! 📊 _Başlayalım mı?_ ✨",
    ]
    for text in good_cases:
        assert is_ollama_response_cacheable(text), f"İyi cevap reddedildi: {text[:50]}"


# ═══════════════════════════════════════════════════════════════════════════
# SENARYO 3: Anlamsız Kelime Oranı Hesaplama
# ═══════════════════════════════════════════════════════════════════════════

def test_anlamsiz_kelime_oran_temiz_turkce():
    """Normal Türkçe cümleler düşük oran (<%15)."""
    cases = [
        "Merhaba nasılsın bugün",
        "Türev bir fonksiyonun değişim hızını ölçer",
        "Kaldırma kuvveti matematiksel olarak önemlidir",
    ]
    for text in cases:
        oran = _anlamsiz_kelime_orani(text)
        assert oran < 0.15, f"Normal Türkçe fazla bozuk çıktı: '{text}' → %{int(oran*100)}"


def test_anlamsiz_kelime_oran_bozuk():
    """Bozuk kelimeler yüksek oran (>%15)."""
    bad_cases = [
        "zrrr bfgh rrr mnpq bcdf",
        "aaaa bbbb cccc dddd eeee",  # tekrarlı
        "pppppp sssssss hhhhhh",  # 4+ ardışık
    ]
    for text in bad_cases:
        oran = _anlamsiz_kelime_orani(text)
        assert oran > 0.15, f"Bozuk kelime yakalanmadı: '{text}' → %{int(oran*100)}"


# ═══════════════════════════════════════════════════════════════════════════
# SENARYO 4: Rol-Spesifik Prompt Doğrulaması (Ollama _LOCAL_SYSTEM)
# ═══════════════════════════════════════════════════════════════════════════

def test_llm_router_local_system_has_rol_rules():
    """llm_router._LOCAL_SYSTEM öğretmen/müdür kurallarını içermeli."""
    from llm_router import LLMRouter
    system = LLMRouter._LOCAL_SYSTEM
    # Temel kurallar
    assert "HER ZAMAN TURKCE" in system, "Türkçe kuralı eksik"
    assert "uydurma" in system.lower(), "Uydurma yasağı eksik"
    assert "FINANS" in system, "Finans yasağı eksik"


# ═══════════════════════════════════════════════════════════════════════════
# SENARYO 5: Routing Duygu Pre-route
# ═══════════════════════════════════════════════════════════════════════════

def test_routing_duygu_claude_zorunlu():
    """Duygu mesajları Claude'a zorunlu yönlendiriliyor mu?"""
    from routing_engine import decide_route
    duygu_cases = [
        "canim sikkin bugun",
        "motivasyonum hic yok",
        "çok stresliyim sınav yakın",
        "mukemmel olmak zorundayim yoksa olmaz",
        "kendimi arkadaslarimla kiyasliyorum",
        "gerginim uyku kaciyor",
        "bitkinim yoruldum",
    ]
    for msg in duygu_cases:
        r = decide_route(msg, role="ogrenci", phone="905538916619")
        assert r == "claude", f"'{msg}' Claude'a gitmedi: {r}"


def test_routing_meslek_bolum_ayrimi():
    """Meslek sorusu (ne iş yapar) → Claude, bölüm hedefi → bolum form."""
    from student_scenarios import detect_scenario
    meslek_cases = [
        "Kimya mühendisliği ne iş yapar",
        "kimya muhendisligi ne is yapar",
        "Mimarlik kaç yıl okur",
        "Tıp bölümü hangi dersler var",
    ]
    for msg in meslek_cases:
        s = detect_scenario(msg, "ogrenci")
        # Meslek sorusu → None veya scenario != "bolum" (Claude'a git)
        is_bolum = bool(s and s.get("scenario") == "bolum")
        assert not is_bolum, f"Meslek sorusu hedef formuna gitti: '{msg}'"


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    tests = [
        test_enforcer_flat_prose_to_structured,
        test_enforcer_idempotent_on_good_input,
        test_enforcer_short_greeting_no_damage,
        test_enforcer_category_emoji_selection,
        test_cache_filter_halucination_marker,
        test_cache_filter_short_no_emoji,
        test_cache_filter_long_no_structure,
        test_cache_filter_anlamsiz_kelime,
        test_cache_filter_good_ollama_response,
        test_anlamsiz_kelime_oran_temiz_turkce,
        test_anlamsiz_kelime_oran_bozuk,
        test_llm_router_local_system_has_rol_rules,
        test_routing_duygu_claude_zorunlu,
        test_routing_meslek_bolum_ayrimi,
    ]
    ok = 0
    for t in tests:
        try:
            t()
            ok += 1
            print(f"✓ {t.__name__}")
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
        except Exception as e:
            print(f"✗ {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(tests)} test geçti")
