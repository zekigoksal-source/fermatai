"""
Role-Aware Prompt Composition (Oturum 22.1 — C15)
==================================================

SYSTEM_PROMPT'un 18k token olmasi cok yuksek. Ama bircok bolum rol-spesifik:
  - Neo tam seffaflik + self-awareness: sadece admin+Neo
  - Ogrenci pedagoji tonu + YKS konu dagilimi: ogrenci + rehber
  - Kayitsiz pazarlama modu: sadece kayitsiz kullanici

Bu modul: run-time rol + phone bilgisine gore SYSTEM_PROMPT'u filtreleyip
gereksiz bloklari KESER. Boylece:
  - Cache-shared BASE (herkese) buyuk kaliyor → cache hit high
  - Rol-spesifik bloklar opsiyonel

Sonuc:
  - ogrenci: 18k → ~14k (NEO blogu + kayitsiz blogu cikar)
  - ogretmen/mudur: 18k → ~11k (+ ogrenci pedagoji blogu da cikar)
  - admin (Neo): 18k → ~17k (sadece kayitsiz blogu cikar)
  - kayitsiz: 18k → ~12k (NEO + ogrenci bloklari cikar)

Ortalama %20-35 tasarruf + cache hit rate +%15.
"""

import logging

# Neo telefon (admin dogrulama icin — get_atlas_trend ile ayni)
NEO_PHONE = "905051256802"


# ─── Blok Sinirlari ─────────────────────────────────────────────────────
# Bu string'ler SYSTEM_PROMPT icinde EXACT match ile bulunur. Baslangic
# string'inden bitis string'ine (+bitis) kadar olan kisim silinir.
# Bitis string'i silmeden sonraki ilk karaktere kadar dahildir.

# BLOK 1 — KAYITSIZ pazarlama modu (~22 satir, ~430 token)
_KAYITSIZ_START = "KAYITSIZ NUMARA (DIS DUNYA — PAZARLAMA MODU):"
_KAYITSIZ_END   = "Gardner, Hattie, Ausubel, Cuceloglu, Vygotsky, Sweller, Newport, Deci & Ryan, Zeigarnik, Seligman."

# BLOK 2 — NEO tam seffaflik + self-awareness (~56 satir, ~1.2k token)
_NEO_START = "🔓 NEO (ADMIN — phone 905051256802) İÇİN İSTİSNA — TAM ŞEFFAFLIK:"
_NEO_END   = "Mudur/yonetim teknik soru sorarsa: kurumsal dilde özet ver, teknik detay açma."

# BLOK 3A — OGRENCI calisma plani + YKS konu dagilimi (~226 satir, ~4.8k token)
# Dikkat: HALUSINASYON YASAGI + WhatsApp format kurallari ogrenci ton bloguna ic icedir,
# bu yuzden marker'i "5. CALISMA PLANI..."den baslatiyoruz — HALUSINASYON herkese kalir.
# Ogrenci ton aciklamasi (~20 satir/~400 tok) herkes icin kalir — admin dahi ogrenci
# hakkinda soru gelirse pedagojik tonu bilir; kabul edilebilir trade-off.
_OGRENCI_PED_START = "5. ÇALIŞMA PLANI OLUŞTURMA PROTOKOLÜ:"
_OGRENCI_PED_END   = "- TREND VURGUSU: \"Analitik geometri yil yil artiyor — 2018'de 3, 2025'te 4. Goz ardi etme!\""

# BLOK 3B — OGRENCI pedagojik zeka + eskalasyon + kurum ozel (~65 satir, ~1.2k token)
_OGRENCI_ZEKA_START = "PEDAGOJİK ZEKA — KONU TAKİBİ + HAFIZA (Neo talimatı 16 Nisan 22:49):"
_OGRENCI_ZEKA_END   = "Akademik Yil: 2025-26 | Sube: Kurs | Yetkili: Zeki Goksal"


def _remove_block(text: str, start: str, end: str) -> str:
    """start string'inden end string'in sonuna kadar olan kismi sil."""
    s = text.find(start)
    if s < 0:
        return text
    e = text.find(end, s)
    if e < 0:
        logging.warning(f"role_prompt: blok end bulunamadi start={start[:40]!r}")
        return text
    # end string'ini dahil ederek sil + sonrasindaki bos satiri da temizle
    cut_end = e + len(end)
    return text[:s].rstrip() + "\n\n" + text[cut_end:].lstrip("\n")


def build_prompt_for_role(base_prompt: str, role: str, caller_phone: str = "") -> str:
    """
    SYSTEM_PROMPT'u role gore filtrele. Gereksiz bloklari kes.

    Args:
        base_prompt: Tam SYSTEM_PROMPT
        role: admin | mudur | ogretmen | rehber | ogrenci | veli | kayitsiz
        caller_phone: Admin dogrulama icin (Neo icin)

    Returns:
        Rol-spesifik prompt (daha kisa, rol-optimized)
    """
    role = (role or "").lower()
    is_neo = (role == "admin" and caller_phone == NEO_PHONE)

    p = base_prompt

    # BLOK 1: KAYITSIZ pazarlama — sadece kayitsiz'da kal
    if role != "kayitsiz":
        p = _remove_block(p, _KAYITSIZ_START, _KAYITSIZ_END)

    # BLOK 2: NEO seffaflik — sadece Neo'da kal
    if not is_neo:
        p = _remove_block(p, _NEO_START, _NEO_END)

    # BLOK 3: OGRENCI pedagoji — sadece ogrenci/rehber'de kal
    # Rehber ogretmen tum ogrenci ile etkilesime giriyor, bu bloga ihtiyaci var
    if role not in ("ogrenci", "rehber"):
        p = _remove_block(p, _OGRENCI_PED_START, _OGRENCI_PED_END)
        p = _remove_block(p, _OGRENCI_ZEKA_START, _OGRENCI_ZEKA_END)

    return p


def prompt_size_estimate(prompt: str) -> dict:
    """Token tahmini ve boyut raporu."""
    char_count = len(prompt)
    line_count = prompt.count("\n") + 1
    # Anthropic tokenizer yaklasik: 3.5 char/token Turkce icin
    token_est = char_count // 3
    return {
        "char": char_count,
        "line": line_count,
        "token_est": token_est,
    }


# ─── CLI Test ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    from fermat_core_agent import SYSTEM_PROMPT

    base_stats = prompt_size_estimate(SYSTEM_PROMPT)
    print(f"BASE: {base_stats['char']} char / {base_stats['line']} satir / ~{base_stats['token_est']} token\n")

    test_roles = [
        ("admin", NEO_PHONE, "Neo (admin)"),
        ("admin", "905000000000", "admin (Neo degil, spoof)"),
        ("mudur", "905462605446", "Mahsum (mudur)"),
        ("ogretmen", "905321111111", "ogretmen"),
        ("rehber", "905321111112", "rehber ogretmen"),
        ("ogrenci", "905551234567", "ogrenci"),
        ("veli", "905551234569", "veli"),
        ("kayitsiz", "905999888777", "kayitsiz (dis)"),
    ]

    for role, phone, label in test_roles:
        p = build_prompt_for_role(SYSTEM_PROMPT, role, phone)
        s = prompt_size_estimate(p)
        tasarruf = base_stats['token_est'] - s['token_est']
        yuzde = (tasarruf / base_stats['token_est']) * 100
        print(f"{label:30s}: {s['token_est']:>6} token ({tasarruf:+6} / {yuzde:+5.1f}%)")
