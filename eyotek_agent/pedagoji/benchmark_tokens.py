"""
Pedagoji V2 — Token Benchmark (25.41 Neo)
==========================================

Eski sistem (pedagoji_literatur + anekdot_kutuphanesi + pedagojik_sablonlar)
vs YENI sistem (build_pedagoji_block) token karşılaştırması.

Test mesajları:
  - Selamlama (trigger yok, baseline)
  - Soru sorma (trigger yok)
  - 'yapamıyorum' (MOTIVASYON match)
  - Stres (STRES match)
  - Hafıza (HAFIZA match)
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ─── ESKI SISTEM SIMULATOR ──────────────────────────────────

async def eski_pedagoji_block(message: str, mood: str = None) -> int:
    """Eski 3 ayrı bloğun toplam token sayısını hesapla."""
    total_chars = 0

    # 1. pedagoji_literatur (max 2 kavram)
    try:
        from pedagoji_literatur import match_triggers
        matches = await match_triggers(message, limit=2)
        if matches:
            text = "\n\n📚 PEDAGOJIK KAVRAM REFERANSI (kullanicinin mesajina uyan):"
            for m in matches:
                text += f"\n• *{m.get('baslik','?')}*: {m.get('kisaca','')[:200]}"
                uo = m.get('kullanim_ornegi', '')
                if uo:
                    text += f"\n  Strateji: {uo[:240]}"
            total_chars += len(text)
    except Exception:
        pass

    # 2. anekdot_kutuphanesi
    try:
        from anekdot_kutuphanesi import get_for_mood, get_for_ders
        anekdot = None
        if mood:
            anekdot = await get_for_mood(mood)
        if not anekdot:
            for ders in ["matematik", "fizik", "kimya", "biyoloji"]:
                if ders in message.lower():
                    anekdot = await get_for_ders(ders)
                    break
        if anekdot and isinstance(anekdot, dict):
            text = (
                f"\n\n💡 ANEKDOT REFERANSI (opsiyonel kullan):"
                f"\n• *{anekdot.get('kim','?')}* ({anekdot.get('konu','')[:60]}): "
                f"{anekdot.get('metin','')[:280]}"
            )
            total_chars += len(text)
    except Exception:
        pass

    # 3. pedagojik_sablonlar
    try:
        from pedagojik_sablonlar import list_by_kategori
        SABLON_MAP = {
            "sinav_kaygisi": "KRIZ_DESTEK",
            "motivasyon_dusuk": "KRIZ_DESTEK",
            "ogrenme_bloku": "KONU_GERI_BILDIRIM",
        }
        sablon_kat = SABLON_MAP.get(mood or "", None)
        if sablon_kat:
            tpls = await list_by_kategori(sablon_kat, rol="ogrenci")
            if tpls:
                tpl = tpls[0]
                text = (
                    f"\n\n📝 SABLON ONERISI ({sablon_kat}):"
                    f"\n{(tpl.get('sablon_metin') or '')[:380]}"
                    f"\n_Uygulama: {(tpl.get('uygulama_notu') or '')[:120]}_"
                )
                total_chars += len(text)
    except Exception:
        pass

    return total_chars // 3  # Token tahmin


# ─── YENI SISTEM ────────────────────────────────────────────

async def yeni_pedagoji_block(message: str, mood: str = None) -> int:
    from pedagoji.lazy_loader import build_pedagoji_block
    block = await build_pedagoji_block(message, detected_mood=mood)
    return len(block) // 3


# ─── STATIK BLOK (system_prompts.py) ────────────────────────

ESKI_STATIK_CHARS = (
    "**ANEKDOT ENTEGRASYONU:**\n"
    "Motivasyon/zorluk anında HİKAYE ile destekle (anekdot_kutuphanesi.py):\n"
    "  - Vazgecme/basarisizlik → Edison 10k deneme / Jordan lise atıldı / Van Gogh 2 tablo\n"
    "  - Türk kimlik/ilham → Aziz Sancar (Harran→Nobel), Cahit Arf, Ali Kuşçu, Harezmi\n"
    "  - Genç yaş/hedef → İbn-i Sina 18'de hoca, Oktay Sinanoğlu 25 Yale prof, Malala\n"
    "  - Matematik korkusu → Einstein efsanesi YALAN, Cahit Arf'ın sözü\n"
    "  - Disiplin → Kobe 4:04 AM, Franklin 13 erdem, Hisaishi her sabah 5\n"
    "  - Kadın sınırları → Sabiha Gökçen, Marie Curie, Malala\n"
    "  Kural: \"Anekdotum var\" DEMEZSİN — \"Biliyor musun, Aziz Sancar...\" gibi doğal akış.\n\n"
    "**PEDAGOJİK LITERATUR (pedagoji_literatur.py — 12 kavram):**\n"
    "  - Growth Mindset (Dweck): 'yapamıyorum' → 'HENÜZ yapamıyorsun' + beyin plastisitesi\n"
    "  - Feynman: 'anlamıyorum' → 'BANA anlat, nerede takıldın'\n"
    "  - Pomodoro: 'odaklanamıyorum' → 25/5 döngüsü + telefon başka oda\n"
    "  - Spaced Repetition: 'unuttum' → 1 gün, 3 gün, 1 hafta tekrar planı\n"
    "  - Dual Coding: 'ezberleyemiyorum' → şema + görsel + anlam\n"
    "  - Deliberate Practice: 'çok çalışıyorum' → kalite vs miktar, yanlış analizi\n"
    "  - CLT (Cognitive Load): '3 ders birden' → tek kanal, üst üste ekleme\n"
    "  - ZPD (Vygotsky): 'çok zor' → birlikte ilk adım, scaffold\n"
    "  - SDT (Deci-Ryan): 'ailem zorluyor' → kendi sesini bulma, özerklik\n"
    "  - Flow (Csíkszentmihályi): 'sıkıcı' → zorluk-yetenek dengesi\n"
    "  - Metacognition: deneme sonrası → 'neden' hatası, hata tipolojisi\n"
    "  - Bloom Taksonomisi: 'ezberledim' → uygulama (L3) sorusu ile doğrula\n\n"
    "**EĞİTİM PSİKOLOJİSİ (egitim_psikoloji.py — 5 durum):**\n"
    "  - SINAV_KAYGISI → 4-7-8 nefes + CBT reframe + Yerkes-Dodson %30 optimal\n"
    "  - MOTIVASYON_DUSUK → SDT values clarification + small wins\n"
    "  - OGRENME_BLOKU → Seligman çaresizlik + spesifik trigger bul\n"
    "  - PERFEKSIYONIZM → 'yeterince iyi' + Van Gogh + Kaizen\n"
    "  - KIYAS_TRAVMASI → gerçek rakip 3 ay önceki sen\n\n"
    "**PEDAGOJIK ŞABLON KÜTÜPHANESİ (pedagojik_sablonlar.py — 27 şablon):**\n"
    "Kategoriler: SINAV_YAKIN, DENEME_SONRASI, HEDEF_BELIRLEME,\n"
    "CALISMA_PLANI_FEEDBACK, KONU_GERI_BILDIRIM, OGRETMEN_YONLENDIRME,\n"
    "ZAMAN_YONETIMI_KRIZ, DERS_CAKISMA, KRIZ_DESTEK, VELI_ILETISIM.\n"
    "Kullanım: Doğrudan kopyala-yapıştır DEĞİL — şablondan ilham al, kişiye özelle.\n"
)


def yeni_mini_index_chars():
    from pedagoji.lazy_loader import get_mini_index
    return len(get_mini_index())


# ─── BENCHMARK ──────────────────────────────────────────────

async def main():
    sys.stdout.reconfigure(encoding="utf-8")

    eski_statik = len(ESKI_STATIK_CHARS) // 3
    yeni_statik = yeni_mini_index_chars() // 3

    print("=" * 70)
    print("📊 PEDAGOJI V2 — TOKEN BENCHMARK")
    print("=" * 70)
    print()
    print("STATIK BLOCK (system_prompts.py — her çağrıda):")
    print(f"  ESKI: {eski_statik} token  (anekdot+lit+psik+sablon referans)")
    print(f"  YENI: {yeni_statik} token  (mini-index)")
    print(f"  TASARRUF: {eski_statik - yeni_statik} token (%{100*(eski_statik-yeni_statik)/eski_statik:.0f})")
    print()

    test_cases = [
        ("merhaba", None),
        ("dünya nasıl gidiyor", None),
        ("ben fizik yapamam vazgeçeceğim", "motivasyon_dusuk"),
        ("sınava 1 hafta var panikteyim donup kalıyorum", "sinav_kaygisi"),
        ("geçen ay öğrendiğimi unuttum", None),
        ("ailem zorluyor kendim için değil", None),
        ("matematik anlamıyorum çok karışık", None),
    ]

    print("DYNAMIC BLOCK (mesaj-bazlı):")
    print(f"  {'Mesaj':50s} {'ESKI':>8s} {'YENI':>8s} {'Δ':>8s}")
    print("  " + "─" * 80)

    eski_total = 0
    yeni_total = 0
    for msg, mood in test_cases:
        eski = await eski_pedagoji_block(msg, mood)
        yeni = await yeni_pedagoji_block(msg, mood)
        delta = yeni - eski
        eski_total += eski
        yeni_total += yeni
        msg_disp = msg[:50] if len(msg) > 50 else msg
        print(f"  {msg_disp:50s} {eski:>8d} {yeni:>8d} {delta:>+8d}")

    print("  " + "─" * 80)
    print(f"  {'TOPLAM (7 mesaj):':50s} {eski_total:>8d} {yeni_total:>8d} {yeni_total-eski_total:>+8d}")
    print(f"  {'ORT (mesaj başına):':50s} {eski_total//7:>8d} {yeni_total//7:>8d}")
    print()

    # Toplam (statik + dynamic ortalaması)
    eski_toplam = eski_statik + eski_total // 7
    yeni_toplam = yeni_statik + yeni_total // 7
    print(f"📈 TOPLAM ORT/MESAJ (statik + dynamic):")
    print(f"  ESKI: {eski_toplam} token")
    print(f"  YENI: {yeni_toplam} token")
    if eski_toplam > 0:
        tasarruf = (eski_toplam - yeni_toplam) / eski_toplam * 100
        print(f"  TASARRUF: %{tasarruf:.0f}")
    print()
    print("✅ Benchmark tamam.")


if __name__ == "__main__":
    asyncio.run(main())
