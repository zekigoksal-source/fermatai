"""
Pedagoji V2 — Kategori Meta + Trigger Pattern Sistemi (25.41 Neo)
=================================================================

8 ana kategori. Her kategori:
  - slug: kod kullanımı (PascalCase enum)
  - baslik: Türkçe insan dili
  - aciklama: kategori ne ifade ediyor
  - trigger_patterns: regex (mesaj match)
  - keyword_boost: ek kelime liste (regex'i güçlendir)
  - oneri_formul: kategori için sentez şablonu (Cerebras prompt'una input)
  - default_konum: prompt'a "ek bilgi" başlığı

Mimari amaç:
  Token bilinçli — sadece match olan kategori CTX'e yüklenir.
  Mini-index sürekli, ağır yükleme on-demand.
"""
from __future__ import annotations
from typing import Optional


# ─── 8 ANA KATEGORİ ────────────────────────────────────────────

KATEGORILER = {
    "HAFIZA": {
        "slug": "HAFIZA",
        "baslik": "Hafıza & Bilgi Tutma",
        "aciklama": "Bilgiyi kalıcı yapma, unutma eğrisi, tekrar stratejisi",
        "trigger_patterns": (
            r"unuttum|hatirlam[ıi]yorum|akl[ıi]mda kalm[ıi]yor|ezberleyem[ıi]yorum|"
            r"hep ayn[ıi]|her seferinde bastan|tekrar|hat[ıi]rlatamad[ıi]m|"
            r"akl[ıi]mdan ucuyor|kal[ıi]c[ıi] olm[ıi]yor"
        ),
        "keyword_boost": ["unutma", "tekrar", "ezber", "hatırla", "kalıcı"],
        "oneri_formul": (
            "Aralıklı tekrar (Spaced Rep) + İkili Kodlama (Dual Coding) + "
            "Retrieval Practice. Anekdot: hafıza şampiyonları veya kendi "
            "kendine tekrar eden büyük zihinler."
        ),
        "default_konum": "📚 BU MESAJDA HAFIZA SİNYALİ",
    },
    "MOTIVASYON": {
        "slug": "MOTIVASYON",
        "baslik": "Motivasyon & İçsel Sürükleme",
        "aciklama": "İçsel motivasyon, vazgeçme duygusu, 'yapamıyorum' zihinsel duvarı",
        "trigger_patterns": (
            r"yapam(?:[ıi]yorum|am|az)|beceremem|m[uü]mk[uü]n de[gğ]il|"
            r"hi[cç] olmuyor|bo[sş]una|vazge[cç]ec(?:e[gğ]i?m|eim)|"
            r"b[ıi]rak[ıi]yorum|umut(?:um)? yok|moral(?:im)? bozuk|"
            r"isteksiz(?:im)?|kendime g[uü]ven(?:emi|i)|"
            r"inan(?:c|ç)[ıi]m kalmad[ıi]|"
            r"ba[sş]ar[ıi]l[ıi] olama(?:yacam|yaca[gğ][ıi]m)|sonu yok"
        ),
        "keyword_boost": ["vazgeç", "yapamıyorum", "umut", "moral", "motivasyon"],
        "oneri_formul": (
            "Growth Mindset (Dweck) + Self-Efficacy (Bandura) + Grit (Duckworth). "
            "'Henüz' reframe + küçük somut adım + öz-inanç. Anekdot: çok denedi "
            "vazgeçmedi (Edison, Jordan, Van Gogh, Aziz Sancar)."
        ),
        "default_konum": "💪 BU MESAJDA MOTİVASYON SİNYALİ",
    },
    "ODAK": {
        "slug": "ODAK",
        "baslik": "Odak & Konsantrasyon",
        "aciklama": "Dikkat dağılması, çalışma süresi yönetimi, akış durumu",
        "trigger_patterns": (
            r"odaklanam[ıi]yorum|dikkatim da[gğ][ıi]l[ıi]yor|s[uü]reli "
            r"cal[ıi][sş]am[ıi]yorum|verimsiz|s[ıi]k[ıi]l[ıi]yorum|"
            r"sosyal medya|telefon|youtube|2 saat ge[cç]iyor|bo[sş]una "
            r"otur(?:du|uyor)um|saatlerce ama"
        ),
        "keyword_boost": ["odak", "dikkat", "verim", "sıkıldım", "konsantre"],
        "oneri_formul": (
            "Pomodoro (Cirillo) + Flow (Csíkszentmihályi) + Cognitive Load (Sweller). "
            "25/5 ritmi + zorluk-yetenek dengesi + tek kanal. Anekdot: 4:04 AM Kobe, "
            "Joe Hisaishi her sabah 5'te masada."
        ),
        "default_konum": "🎯 BU MESAJDA ODAK SİNYALİ",
    },
    "STRES": {
        "slug": "STRES",
        "baslik": "Stres, Kaygı & Sınav Korkusu",
        "aciklama": "Sınav öncesi/sırasında panik, kaygı, donup kalma",
        "trigger_patterns": (
            r"panik|kayg[ıi]l[ıi]y[ıi]m|sinav korkusu|donup kald[ıi]m|"
            r"stres(?:liyim)?|nefesim daral[ıi]yor|kalbim [cç]arp[ıi]yor|"
            r"unuttum hepsini|s[ıi]nav g[uü]n[uü] korkuyorum|gece "
            r"uyuyamad[ıi]m|titriyorum|m[ıi]de(?:m)? bul(?:an|n)[ıi]yor"
        ),
        "keyword_boost": ["stres", "kaygı", "panik", "korku", "endişe"],
        "oneri_formul": (
            "Yerkes-Dodson Law (optimal stres) + Mindfulness (Kabat-Zinn) + "
            "Test Anxiety (Liebert). Nefes egzersizi + present moment + reframe "
            "(stres düşman değil, hazırlık sinyali). Anekdot: Olimpiyat sporcular, "
            "Malala 15 yaşında konuştu."
        ),
        "default_konum": "🌊 BU MESAJDA STRES/KAYGI SİNYALİ",
    },
    "DISIPLIN": {
        "slug": "DISIPLIN",
        "baslik": "Disiplin, Alışkanlık & Erteleme",
        "aciklama": "Düzenli çalışma, erteleme (procrastination), alışkanlık inşası",
        "trigger_patterns": (
            r"d[uü]zensizim|erteliyorum|yar[ıi]n yapar[ıi]m|alka(?:nl[ıi]k)?|"
            r"ba[sş]layam[ıi]yorum|asarl(?:ı|i) bir d[uü]zenim yok|"
            r"plansiz|sabaha kal[ıi]yorum|son dakika|son g[uü]ne|tembelim"
        ),
        "keyword_boost": ["disiplin", "düzen", "alışkanlık", "erteleme", "rutin"],
        "oneri_formul": (
            "Atomic Habits (Clear) + Habit Loop (Duhigg) + Implementation Intentions "
            "(Gollwitzer). %1 kuralı + cue-routine-reward + 'X olursa Y yaparım'. "
            "Anekdot: Franklin 13 erdem, Joe Hisaishi her sabah 5, BTS 10 yıl pratik."
        ),
        "default_konum": "🔄 BU MESAJDA DİSİPLİN/ALIŞKANLIK SİNYALİ",
    },
    "KIMLIK": {
        "slug": "KIMLIK",
        "baslik": "Kimlik, Hedef & Anlam",
        "aciklama": "Ne istiyorum, neden çalışıyorum, aile baskısı, gelecek",
        "trigger_patterns": (
            r"ne istedi[gğ]imi bilmiyorum|ailem zorl[uü]yor|"
            r"kendi(?:m i[cç]in)? de[gğ]il|mecburum|gelece[gğ]im|"
            r"hedefim yok|ni[cç]in [cç]al[ıi][sş][ıi]yorum|"
            r"\banlams[ıi]z\b|"
            r"k[uü]vveti(?:m)? yok|ne olacak benim|"
            r"\bkim(?:lik|li[gğ]im)?\b"
        ),
        "keyword_boost": ["hedef", "anlam", "kimlik", "gelecek", "neden"],
        "oneri_formul": (
            "Self-Determination Theory (Deci & Ryan) + PERMA (Seligman) + "
            "Achievement Goal Theory. Özerklik soruları + iç ses + somut hedef "
            "görselleştirme. Anekdot: Aziz Sancar Harran'dan Nobel'e, "
            "İbn-i Sina 18'inde, Mustafa Kemal isminin matematiksel kökü."
        ),
        "default_konum": "🧭 BU MESAJDA KİMLİK/HEDEF SİNYALİ",
    },
    "OGRENME": {
        "slug": "OGRENME",
        "baslik": "Öğrenme Yöntemi & Anlayış",
        "aciklama": "Anlamama, ezber-anlama farkı, çalışma yöntemi seçimi",
        "trigger_patterns": (
            r"anlam[ıi]yorum|kar[ıi][sş][ıi]k|kafam kar[ıi][sş][ıi]k|"
            r"ezberled[ıi]m ama|cok cal[ıi][sş][ıi]yorum (?:ama|verim)|"
            r"y[oö]ntem nasil|ne(?:re|den) ba[sş]lay[ıi]m|ornekle ister|"
            r"farkli y[oö]ntem|hangi kaynaktan"
        ),
        "keyword_boost": ["anlama", "yöntem", "kavram", "öğrenme", "kaynak"],
        "oneri_formul": (
            "Feynman Tekniği + Bloom Taksonomi + Deliberate Practice (Ericsson) + "
            "Interleaving (Rohrer). 'Bana anlat' + L3 sorusu + kalite>miktar + "
            "konu karıştırma. Anekdot: Feynman 12 yaşına anlatma, Cahit Arf "
            "yürümek, Harezmi algoritma."
        ),
        "default_konum": "🧠 BU MESAJDA ÖĞRENME YÖNTEM SİNYALİ",
    },
    "AZIM": {
        "slug": "AZIM",
        "baslik": "Azim, Direniş & Başarısızlık",
        "aciklama": "Reddedilme, hata, başarısızlık duygusu, geri toparlanma",
        "trigger_patterns": (
            r"ba[sş]ar[ıi]s[ıi]z(?:ım)?|hata yapt[ıi]m|reddedildim|"
            r"yine yine ayn[ıi]|d[uü][sş]t[uü]m yine|kim oldum ben|"
            r"asla olmayacak|son denemem (?:c|kotuydu|berbatti)|"
            r"yıkılmı[sş] hissediyorum|[cç][oö]kt[uü]m"
        ),
        "keyword_boost": ["başarısız", "hata", "düştüm", "reddedildim", "yıkıl"],
        "oneri_formul": (
            "Self-Compassion (Neff) + Grit (Duckworth) + Learned Optimism (Seligman). "
            "Kendine şefkat + uzun vadeli azim + 'kalıcı değil, geçici' reframe. "
            "Anekdot: Edison 10K deneme, Jordan lise dışı, Van Gogh 2 tablo, "
            "Marie Curie 2 Nobel."
        ),
        "default_konum": "🔥 BU MESAJDA AZIM/BAŞARISIZLIK SİNYALİ",
    },
}


# ─── HELPER ───────────────────────────────────────────────────

def get_kategori(slug: str) -> Optional[dict]:
    return KATEGORILER.get(slug)


def list_kategoriler() -> list[str]:
    return list(KATEGORILER.keys())


def get_mini_index() -> str:
    """Claude system prompt'a eklenecek mini-index (~150 token).

    ESKİ get_prompt_injection (600 token) yerine kullanılır.
    Sadece kategori isim+kısa açıklama. Detay tool ile çekilir.
    """
    lines = ["📚 PEDAGOJI MOTORU (8 kategori, 41 kavram + 76 anekdot DB):"]
    for slug, k in KATEGORILER.items():
        # 1 satır/kategori — minimal token
        lines.append(f"  • {slug}: {k['aciklama'][:55]}")
    lines.append(
        "Trigger otomatik (mesaj→kategori→CTX paket). "
        "search_pedagoji(durum) tool ile manuel çek. "
        "Doğal anlat — 'literatür' DEME, 'biliyor musun' kullan."
    )
    return "\n".join(lines)


# Örnekleme: token saymak için
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    idx = get_mini_index()
    # Kabaca token sayısı (Türkçe ~3.5 char/token)
    char_count = len(idx)
    token_est = char_count // 3
    print(idx)
    print(f"\n[mini_index] {char_count} char ≈ {token_est} token")
    print(f"[kategori sayisi] {len(KATEGORILER)}")
    for slug, k in KATEGORILER.items():
        print(f"  {slug}: {k['baslik']}")
