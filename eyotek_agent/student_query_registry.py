"""
FermatAI — Ogrenci Sorgu Kayitlari (Registry)
================================================
Son 30 gun konusmalar analiz edildi, ogrencinin sorabilecegi sorularin %80'i
burada senaryolastirildi. Her senaryo:
  - id: benzersiz ad
  - patterns: regex varyasyonlari
  - path: "fast" | "ollama_safe" | "claude_required"
  - handler: (fast icin) fonksiyon adi
  - data_sources: (Claude icin) SQL kaynagi listesi
  - quality_check: cevabin kalite kontrol kriteri

AMAC:
  1. Her sorgu icin KESIN strateji (karmasa bitti)
  2. Ortalama cevap suresi < 5sn
  3. Kalite A+ (sablondan sapma yok)
  4. Yeni dialog durumlarinda eklenebilir yapı

KULLANIM:
  fast_responses._try_registry_match(msg_lower, ...) cagirir,
  pattern hit olunca path=="fast" ise handler dispatch edilir,
  path=="claude_required"/"ollama_safe" ise None donulur (ust akisa birakilir).
"""
import re as _re

# ═══════════════════════════════════════════════════════════════════════
# OGRENCI SENARYO YELPAZESI (%80 kapsam)
# ═══════════════════════════════════════════════════════════════════════

STUDENT_QUERY_REGISTRY = [

    # ─── KATEGORI 1: SELAMLAMA & SOHBET ───────────────────────────────
    {
        "id": "selam_saf",
        "patterns": [r"^(merhaba|selam|hey|slm|sa|selamun)[.!,\s]*$",
                     r"^(iyi\s*g[uü]n|g[uü]nayd[iı]n|iyi\s*ak[sş]am)"],
        "path": "fast",
        "handler": "selamlama",
        "priority": 1,
        "freq_observed": 38,  # Son 30 gun
        "note": "Sadece saf selam. Selam + soru Claude'a.",
    },
    {
        "id": "selam_hitap",
        "patterns": [r"^(merhaba|selam)\s+(hocam|ustad|kardesim|kardeşim)[.!\s]*$"],
        "path": "fast",
        "handler": "selamlama",
        "priority": 1,
    },
    {
        "id": "selam_hal",
        "patterns": [r"^(merhaba|selam)\s+(nasilsin|nasılsın|naber|iyi\s*misin)"],
        "path": "fast",
        "handler": "sohbet",
        "priority": 1,
    },

    # ─── KATEGORI 2: DENEME ANALIZI (en kritik) ───────────────────────
    {
        "id": "son_deneme",
        "patterns": [
            r"son\s*deneme(m|n|nin)?\s*(nas[iı]l|sonuc|analiz)?",
            r"son\s*deneme\s*gecti",
            r"deneme\s*sonuc(um|larım|larim)",
            r"bu\s*deneme(m|deki|de)",
            r"netlerim\s*(ne|nedir|kaç)",
        ],
        "path": "fast",
        "handler": "ogrenci_son_deneme",
        "data_sources": ["student_exams DESC LIMIT 1"],
        "freq_observed": 8,
        "quality_check": "toplam_net > 0, turkce-mat-fen-sosyal gosterildi, renkli emoji (🟢🟡🔴), kiyaslama teklifi sonunda",
    },
    {
        "id": "son_n_deneme_kiyasla",
        "patterns": [
            r"son\s*\d+\s*denem(e|eyi|emi)\s*kiyasla",
            r"denemelerim(i|deki)\s*(kiyasla|karsilastir|farki)",
            r"gelis(im|memi)\s*nasil",
        ],
        "path": "fast",
        "handler": "ogrenci_deneme_kiyasla",
        "data_sources": ["student_exams DESC LIMIT N"],
        "freq_observed": 5,
    },
    {
        "id": "ayt_deneme",
        "patterns": [
            r"(son\s*)?ayt\s*(denem|sinav|sonuc|netler|analiz|nasil)",
            r"aytlerim",
            r"ayt\s*netleri?mi",
        ],
        "path": "fast",
        "handler": "ogrenci_ayt_deneme",
        "data_sources": [
            "student_exam_analysis (ham_puan_ayt, yerlesme_puani_ayt)",
            "student_exams WHERE exam_name LIKE '[AYT]%' ORDER BY exam_date DESC LIMIT 1",
        ],
        "quality_check": "Eyotek resmi puan ustte, sinav adi+tarih, ders netleri sinav basi ortalama",
    },
    {
        "id": "tyt_vs_ayt",
        "patterns": [r"tyt\s*(ve|vs|ile)\s*ayt", r"ayt\s*(ve|vs|ile)\s*tyt"],
        "path": "claude_required",
        "reason": "Karsilastirmali analiz — trend + gelisim yorumu gerekir",
        "tools_needed": ["get_student_analytics", "get_ayt_analysis"],
    },

    # ─── KATEGORI 3: ZAYIF/GUCLU KONULAR ────────────────────────────────
    {
        "id": "zayif_konular",
        "patterns": [
            r"zay[iı]f\s*konu(lar[iı]m|larim)?",
            r"hangi\s*konularda\s*(zayifim|kotuyum)",
            r"eksik\s*konular[iı]m",
            r"nelerde\s*(zor|kot[uü]y[uü]m)",
        ],
        "path": "fast",
        "handler": "ogrenci_zayif_konular",
        "data_sources": ["student_topic_tracker WHERE sinav_hata_yuzdesi<50 ORDER BY asc"],
        "freq_observed": 6,
    },
    {
        "id": "guclu_konular",
        "patterns": [
            r"(iyi|g[uü]c?l[uü])\s*(oldugum|oldugun|oldugumuz)?\s*konu",
            r"iyi\s*konu(lar[iı]m|larim)?",
            r"basarili\s*oldugum",
        ],
        "path": "fast",
        "handler": "ogrenci_guclu_konular",
        "data_sources": ["student_topic_tracker WHERE sinav_hata_yuzdesi>=60 DESC"],
    },

    # ─── KATEGORI 4: CIKMIS SORU (ÇOK KULLANILIYOR) ─────────────────────
    {
        "id": "ders_cikmis_soru",
        "patterns": [
            r"(fizik|matematik|kimya|biyoloji|turkce|tarih|edebiyat|cografya|geometri)\s*(cikmis|çıkmış).*soru",
            r"(cikmis|çıkmış).*soru.*(fizik|matematik|kimya|biyoloji)",
            # Konu dagilimi / soru bankasi varyasyonlari
            r"(fizik|matematik|kimya|biyoloji|turkce|tarih|edebiyat|cografya|geometri)\s*(konu\s*dagil|konu\s*dağıl|konularin|soru\s*bank|kataloğ|katalog)",
            r"yks\s*(fizik|matematik|kimya|biyoloji)\s*konu",
            r"(tyt|ayt)\s*(fizik|matematik|kimya|biyoloji)\s*konu",
        ],
        "path": "fast",
        "handler": "get_cikmis_soru_menu",
        "freq_observed": 5,
    },
    {
        "id": "konu_cikmis_soru",
        "patterns": [
            # Konu→ders mapping aktif: manyetizma → fizik, türev → matematik, vb.
            r"(manyetizma|elektrik|dalga|optik|t[uü]rev|integral|limit|fonksiyon|mitoz|mayoz|h[uü]cre|osmanli|cumhuriyet)\s*(cikmis|çıkmış)",
        ],
        "path": "fast",
        "handler": "get_cikmis_soru_menu (auto ders mapping)",
        "freq_observed": 5,
    },
    {
        "id": "soru_N_coz",
        "patterns": [
            r"soru\s*\d+",
            r"\d+\s*(nolu|numarali|numaralı)\s*soru",
            r"(soruyu|bunu)\s*c[oö]z",
            r"(onu|sunu)\s*g[oö]ster",
        ],
        "path": "claude_required",
        "reason": "Context-bagimli (onceki menu) + send_exam_image tool",
        "tools_needed": ["search_curriculum", "send_exam_image"],
        "freq_observed": 7,
    },

    # ─── KATEGORI 5: HEDEF & PUAN ───────────────────────────────────────
    {
        "id": "kisisel_hedef_analiz",
        "patterns": [
            r"(netlerim(le|ime|e\s*g[oö]re)|verilerim(e|le)\s*g[oö]re|mevcut\s*durumumla)",
            r"netlerim(le|e\s*g[oö]re)?\s*(hangi|nereye)\s*(universite|[uü]niversite|b[oö]l[uü]m)",
            r"(hangi|nereye)\s*(universite|[uü]niversite|b[oö]l[uü]m)",
            r"netlerim\s*(yeter|yetiyor|yeterli)\s*mi",
            r"bolum\w*\s*ne\s*cikar",
            r"mevcut\s*durum",
            r"su\s*anki\s*(netlerim|puan|durum)",
        ],
        "path": "claude_required",
        "reason": "Kisisel veri + yerlesme puani + bolum hedef analizi — Claude",
        "tools_needed": ["get_student_analytics", "get_ayt_analysis", "query_analytics"],
        "quality_check": "Ogrencinin yerlesme puani + hedef bolum 3 yillik taban + gereken net hesabi",
    },
    {
        "id": "puan_tahmin",
        "patterns": [
            r"puan(im|ım|imi|ımı)\s*(ne|kac|nedir)",
            r"yks\s*puan(im|ım|imi|ımı)",
            r"tahmini\s*puan",
        ],
        "path": "claude_required",
        "reason": "Puan tahmin algoritmasi + bolum hedef",
        "tools_needed": ["get_ayt_analysis"],
    },
    {
        "id": "bolum_bilgisi_generic",
        "patterns": [
            r"(tip|muhendislik|mühendislik|hukuk|diş\s*hekim|dis\s*hekim|veteriner|eczacilik|eczacılık|psikoloji)\s*(puani|puanı|hakkinda|hakkında|kac|kaç)",
        ],
        "path": "fast",
        "handler": "bolum_generic_bilgi",
        "note": "Genel bolum bilgisi — kisisel veri yoksa.",
    },

    # ─── KATEGORI 6: PROGRAM & PLAN ────────────────────────────────────
    {
        "id": "bugunku_program",
        "patterns": [
            r"bug[uü]nk[uü]\s*(ders\s*program|program|etut)",
            r"bugun\s*(ne\s*var|hangi\s*ders)",
        ],
        "path": "fast",
        "handler": "ogrenci_gun_programi",
        "data_sources": ["class_timetable WHERE gun=TODAY"],
    },
    {
        "id": "calisma_plani_iste",
        "patterns": [
            r"calisma\s*plan(im|ım|i)?",
            r"nas[iı]l\s*calis(mal[iı]|ay[iı]m)",
            r"program\s*haz[iı]rla",
        ],
        "path": "claude_required",
        "reason": "11 katmanli veri paketi — zayif konu + program + hedef",
        "tools_needed": ["build_study_plan_context"],
    },

    # ─── KATEGORI 7: MOTIVASYON & PSIKOLOJIK ───────────────────────────
    {
        "id": "stres_panik",
        "patterns": [
            r"stres(liyim|yapiyorum|oluyorum|li|teyim)?",
            r"panik",
            r"calismak\s*istemiyorum",
            r"bikt[iı]m",
            r"b[iı]rak(mak|icam)",
            r"yoruldum",
            r"tukendim",
            r"moralim\s*bozuk",
        ],
        "path": "claude_required",
        "reason": "Psikolojik iletisim — Claude pedagojik yanıt",
        "quality_check": "Empati + 5dk kurali/cin bambusu motivasyon + kucuk aksiyon onerisi",
    },
    {
        "id": "motivasyon_iste",
        "patterns": [
            r"motivasyon(um)?\s*(d[uü]s[uü]k|yok|lazim)",
            r"motiv(e\s*et|asyon\s*ver)",
            r"beni\s*(motive|coskulu)",
        ],
        "path": "fast",
        "handler": "get_motivasyon",
        "data_sources": ["motivation_library"],
    },

    # ─── KATEGORI 8: GIZLILIK & GUVENLIK ───────────────────────────────
    {
        "id": "gizlilik_sorgusu",
        "patterns": [
            r"yazd[iı]klar[iı]m[iı]?\s*kim\s*g[oö]r",
            r"(gizli|kisisel)\s*mi",
            r"konusma(m|lar[iı])\s*(kaydedil|g[oö]r[uü]l)",
            r"kvkk",
        ],
        "path": "fast",
        "handler": "GIZLILIK_CEVAP",
        "freq_observed": 2,
    },

    # ─── KATEGORI 9: HATALI DAVRANIS (Frustration) ─────────────────────
    {
        "id": "frustration",
        "patterns": [
            r"(yanlis|yanlış|hatali|hatalı|hata\s*var)",
            r"(anlamad[iı]n|beni\s*anlam|bunu\s*demedim|istemedim)",
            r"(son\s*degil|bu\s*degil)",
            r"sacmalama",
        ],
        "path": "claude_required",
        "reason": "Context analiz gerek — generic ozur yerine Claude duzeltsin",
        "quality_check": "Haklisin diyerek duzelt + dogrudan veriye don",
    },

    # ─── KATEGORI 10: KURUM/PERSONEL (ogrenciye YASAK) ─────────────────
    {
        "id": "kurum_personel_sorusu",
        "patterns": [
            r"(kurum\w*\s*ka[cç]|ka[cç]\s*ogrenci|ka[cç]\s*ogretmen)",
            r"(zeki|mahsum|duygu|orsel|kardelen|orhan|emin)\s*(hoca|bey|hanim)\s*kim",
            r"(en\s*iyi|birinci|sahib).*(hoca|dershane|kurum)",
            r"fermat\s*vip\s*(en\s*iyi|mi)",
            r"(dershane\w*\s*)(en|hakkinda|bilgi)",
            r"maas|maaş|personel\s*bilgi|kimin\s*kurum",
        ],
        "path": "fast",
        "handler": "ogrenci_kurum_bilgi_reddet",
        "freq_observed": 4,
        "note": "Ogrenciye kurum/personel bilgisi VERILMEZ. Akademik kanala yonlendir.",
    },

    # ─── KATEGORI 11: YETENEKLER ───────────────────────────────────────
    {
        "id": "yetenekler_sorgu",
        "patterns": [
            r"ne(ler)?\s*yapabilirsin",
            r"yeteneklerin",
            r"kabiliyetler\w*",
            r"ne\s*biliyorsun",
            r"(neler|ne)\s*sorabilirim",
        ],
        "path": "fast",
        "handler": "get_yetenekler",
    },

    # ─── KATEGORI 12: KAVRAMSAL AÇIKLAMA (Ollama guvenli) ──────────────
    {
        "id": "kavramsal_soru",
        "patterns": [
            r"^[\w\s]{5,50}\s*(nedir|ne\s*demek|acikla|açıkla|anlat)[.?\s]*$",
            r"^[\w\s]+\s*(formul|formül|nasil\s*hesaplanir)[.?]*$",
        ],
        "path": "ollama_safe",
        "reason": "Kavramsal bilgi — Ollama halusinasyon-safe",
        "condition": "Mesajda kisisel veri keyword'u YOK (netim, benim, isim)",
        "quality_check": "Kisa (3-4 paragraf), formula/ornekle, kapanis sorusu",
    },

    # ─── KATEGORI 13: NOT ETME (admin feedback) ───────────────────────
    {
        "id": "not_kaydet",
        "patterns": [
            r"(not\s*et|kaydet|bildir)",
            r"(admine|yonetime)\s*(ilet|bildir)",
        ],
        "path": "fast",
        "handler": "user_feedback_kaydet",
        "freq_observed": 4,
    },

    # ─── KATEGORI 14: VEDA ─────────────────────────────────────────────
    # Oturum 25.29 KRITIK FIX: word-boundary YOKKEN "bay" -> "bayatlioglu" (Kardelen
    # rehber 08:34, Goktürk Han Bayatlioglu sorgusunda bot Pomodoro/uyku motivasyonu
    # gonderdi — "bay" prefix ofnaylaniyordu). \b sınırlı haline getirildi.
    {
        "id": "veda",
        "patterns": [
            r"\b(g[oö]r[uü][sş][uü]r[uü]z|ho[sş][cç]a\s*kal|ho[sş][cç]a|bye|bay\b|baybay)\b",
            r"\b(yok\s*)?sa[ğg]\s*ol(\s*can[iı]m?|\s*hocam)?\b",
            r"\b(te[sş]ekk[uü]r(ler|ederim)?|sa[oö]l|eyvallah)\b",
        ],
        "path": "fast",
        "handler": "veda_cevap",
    },
]


# ═══════════════════════════════════════════════════════════════════════
# CLAUDE TARAFINDAN CEKILEN VERI TIPLERI (context zenginlestirme)
# ═══════════════════════════════════════════════════════════════════════

CLAUDE_CONTEXT_DATA = {
    # Her ogrenci mesajinda Claude'a otomatik enjekte edilen bilgiler
    "ogrenci_aktif_baglam": [
        "Son 3 TYT deneme (exam_name, exam_date, toplam, ders_netleri)",
        "Son AYT birlestir analiz (ham_puan_ayt, yerlesme_puani_ayt, ortalama_netler)",
        "Top 5 zayif konu (ders, konu, sinav_hata_yuzdesi)",
        "Top 3 guclu konu",
        "Son 7 gun devamsizlik (saat)",
        "Haftalik ders programi",
        "Son 1 ay etut gecmisi",
    ],
}


# ═══════════════════════════════════════════════════════════════════════
# CEVAP KALITE STANDARTLARI (A+ icin zorunlu)
# ═══════════════════════════════════════════════════════════════════════

A_PLUS_STANDARDS = {
    "emoji_set": ["📊", "📅", "📝", "🎯", "✅", "📈", "✨", "💪", "🎓", "🔬", "📚", "💡", "🌟", "⏰", "🧠", "⚡", "🏆"],
    "emoji_forbidden": ["😈", "👻", "💀", "🖕", "🤬", "💩", "🤡"],
    "bold_usage": "Sadece *onemli terim* veya *rakam*, paragrafi komple bold yapma",
    "paragraph_length": "2-4 cumle, kisa bloklar",
    "closing": "Italik kapanis sorusu veya oneri zorunlu",
    "no_markdown_header": "# veya ## ASLA, yerine *bold*",
    "no_code_block": "``` ASLA (WhatsApp renderlemiyor)",
    "no_table": "|---| ASLA, yerine bullet",
    "data_integrity": "Sayi/isim UYDURMA YASAK — veri yoksa 'veri yok' de",
    "closing_question": "Her cevapta _kapanis sorusu_ ile diyalog surekliligi",
}


# ═══════════════════════════════════════════════════════════════════════
# COMPILED PATTERNS — import sırasında bir kez hazirlanir
# ═══════════════════════════════════════════════════════════════════════

for _item in STUDENT_QUERY_REGISTRY:
    _item["_compiled"] = [_re.compile(p, _re.IGNORECASE) for p in _item["patterns"]]


def find_match(msg_lower: str):
    """
    Registry'yi sirayla tara, pattern hit olan ilk senaryoyu dondur.
    Dondurur: (senaryo_dict) veya None
    """
    for item in STUDENT_QUERY_REGISTRY:
        for rx in item["_compiled"]:
            if rx.search(msg_lower):
                return item
    return None


if __name__ == "__main__":
    print(f"Registry: {len(STUDENT_QUERY_REGISTRY)} senaryo")
    for cat in sorted(set(s['id'].split('_')[0] for s in STUDENT_QUERY_REGISTRY)):
        cnt = sum(1 for s in STUDENT_QUERY_REGISTRY if s['id'].startswith(cat))
        print(f"  {cat}: {cnt}")
    print()
    print("PATH DAGILIMI:")
    paths = {}
    for s in STUDENT_QUERY_REGISTRY:
        paths[s['path']] = paths.get(s['path'], 0) + 1
    for p, c in paths.items():
        print(f"  {p}: {c}")
