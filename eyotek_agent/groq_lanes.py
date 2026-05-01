"""
Groq-Safe Lanes (Oturum 25.10 — Neo karari)
=================================================
70B Llama 3.3 Groq'un GUVENLE yapabilecegi mesaj lane'leri.

Ana fikir: Claude'a giden trafiğin %50'si aslında Groq ile %95+ kalitede
yanitlanabilir. Sadece DOĞRU lane'leri belirlemek lazım.

Lane tipleri (Groq-SAFE):
  1. KAVRAMSAL_KISA  — "X nedir", formül, tanım (kısa, kişiselleştirilmemiş)
  2. SOHBET         — selam/teşekkür/günlük muhabbet (kurum dışı)
  3. META_DIREKTIF  — "emoji koymadan konuş", "İngilizce devam", "sade"
  4. KIBARLIK       — kibar reaksyon, vedalaşma, onay
  5. EGITIM_ICERIK  — formülü, kuralı, örnek soru (kişi-gnostik değil)
  6. RED_GENERIK    — KVKK reddi gibi tek-cümle reddetme
  7. KISA_MOTIVASYON — "yapamayacağım" basit motivasyon (kriz değil!)

Groq-NO-GO (Claude zorunlu):
  - personal_data    — benim netim, X öğrencinin durumu
  - tool_required    — etüt yaz, foto soru, deneme analizi
  - duygu_kriz       — kriz seviye duygu (intihar, depresyon, ağır stres)
  - multi_step       — 5 öğrenciyi kıyasla, rapor üret
  - identity_locked  — KVKK lock aktif
  - frustration      — bot anlamadıysa
  - admin_complex    — admin'in çoklu sorgu/analiz isteği
  - data_query       — DB sorgusu gerektiren

KULLANIM:
  from groq_lanes import classify_lane, is_groq_safe
  lane = classify_lane(message, role, phone)  # → "kavramsal_kisa"|"sohbet"|...|None
  if lane and is_groq_safe(lane):
      → Groq'a yolla
"""
from __future__ import annotations
import re
from typing import Optional, Literal


# ── Pattern Library ────────────────────────────────────────────────────────

# Kişisel veri (Claude zorunlu)
_PERSONAL_DATA = re.compile(
    r'\b(benim\s+(net|deneme|sinav|sınav|puan|durum|notum|devamsiz|devamsız|borç|borc|hocam|programim|programım))|'
    r'\b(ben(de|im)\s+(nasil|nasıl|ne|kim))|'
    r'\b(hangi\s+(öğrenci|ogrenci|hoca|sinif|sınıf))|'
    r'\b(\w+\s+(adli|adlı|isimli)\s+(öğrenci|ogrenci))',
    re.IGNORECASE,
)

# Tool gerektiren açık istek
_TOOL_REQUIRED = re.compile(
    r'\b(etut\s+yaz|etüt\s+yaz|rehberlik\s+notu|foto\s+çöz|cöz\s+(şu|bu)\s+(soru|sayfa))|'
    r'\b(rapor\s+(getir|olustur|olustur|hazirla))|'
    r'\b(kayd?et|sil|guncelle|update)\s+(öğrenci|ogrenci|etut|not|borç)',
    re.IGNORECASE,
)

# Duygu/kriz keyword'leri (Claude zorunlu)
_KRIZ_PATTERN = re.compile(
    r'\b(intihar|olmek\s+istiyorum|ölmek\s+istiyorum|hayata\s+küs|hayata\s+kus|bitkin|'
    r'depresyon|panik\s+atak|kendime\s+zarar|vazgect|vazgeçt|her\s+ş?ey\s+anlamsiz|anlamsız|'
    r'yapamiy?orum\s+art[iı]k|tukendim|tükendim|daya?nam[iı]y?orum)',
    re.IGNORECASE,
)

# 1. KAVRAMSAL_KISA — saf bilgi sorusu
# "midir/mıdır/müdür/mudur" sonu da kavramsal (X Y midir? gibi)
_KAVRAMSAL_PATTERN = re.compile(
    r'\b(nedir\??|ne\s+demek\??|nasil\s+çalış|nasıl\s+çalış|açıkla|aciklа|anlat|formul[üu]?|formül[üu]?|'
    r'tan[iı]m[iı]?|tanım[iı]?|kuralı?|kanunu?|prensibi?|yasası?|kavram[iı]?|teoremi?|özelliği?|özellikleri)|'
    r'(m[iıuü]d[iıuü]r\??|midir\??|mıdır\??|müdür\??|mudur\??)\s*$',
    re.IGNORECASE,
)

# 2. SOHBET — günlük, kurum dışı, eğlenceli
_SOHBET_PATTERN = re.compile(
    r'^(selam|merhaba|hey|sa$|nbr|naber|nasilsin|nasılsın|hoşgeldin|hosgeldin|iyi\s+(gun|gün|ak[şs]am|gece))|'
    r'(teşek?k[üu]r|tesekk|sa[gğ]ol|eyvallah|ok\s|tamam$|hadi|olur|peki)|'
    r'(görüşürüz|gorusuruz|bye|hosca|hoşça)',
    re.IGNORECASE,
)

# Sohbet konuları (kurum dışı): yemek, spor, hobi, eğlence
_GENEL_SOHBET = re.compile(
    r'\b(yemek|cay|kahve|çorba|corba|kebap|pizza|hamburger|salata|tatlı|tatli|'
    r'film|dizi|mac|maç|spor|futbol|basketbol|müzik|muzik|sarki|şarkı|'
    r'eglence|eğlence|şaka|saka|fıkra|fikra|hava|kis|kış|yaz|sonbahar|ilkbahar|seyahat|'
    r'doğa|dağ|deniz|tatil|hafta\s+sonu|kütüphane|'
    r'rezillik|guzel\s+(mi|midir)|nasıl\s+olur|sever\s+misin)',
    re.IGNORECASE,
)

# 3. META_DIREKTIF — bot davranışı için talimat
# Turkce "İngilizce" lowercase issue (i̇ combining dot) → broader match
_META_DIREKTIF = re.compile(
    r'(emoji|emojı|emojisiz|emoji\s+koy|sade\s+konuş|sade\s+konus|kısa\s+konuş|kisa\s+konus|'
    r'türkçe\s+(devam|konuş|konus)|turkce\s+(devam|konus|konuş)|'
    r'i̇?ngilizce\s+(devam|konuş|konus|etsek)|japonca\s+(devam|konuş|etsek)|'
    r'formal|resmi|kibar\s+(ol|konuş|konus)|'
    r'şaka\s+yap|saka\s+yap|esprili\s+ol|robot\s+gibi)',
    re.IGNORECASE,
)

# 4. KIBARLIK / KISA REAKSIYON
_KIBARLIK = re.compile(
    r'^(çok\s+iyi|cok\s+iyi|harika|guzel|güzel|süper|super|mukemmel|mükemmel|inanılmaz|fena\s+değil|'
    r'tabii|elbette|kesinlikle|tamamen|aynen|exactly)$',
    re.IGNORECASE,
)

# 5. EGITIM_ICERIK — okul içeriği ama kişiselleştirilmemiş
_EGITIM_ICERIK = re.compile(
    r'\b(soru\s+tipi|soru\s+kalıbı|soru\s+kalibi|cevap\s+anahtar|şık\s+tahmin|sik\s+tahmin|'
    r'YKS\s+(strateji|format|sistem)|TYT\s+(strateji|format|kac\s+soru|kaç\s+soru)|'
    r'AYT\s+(strateji|format|kac|kaç)|LGS\s+(strateji|format)|sınav\s+stratej|sinav\s+stratej|'
    r'çalışma\s+yöntemi|calisma\s+yontemi|öğrenme\s+teknik|ogrenme\s+teknik|'
    r'pomodoro|feynman)',
    re.IGNORECASE,
)

# 6. RED_GENERIK — kapsam dışı eğlenceli/saçma sorular
_RED_GENERIK = re.compile(
    r'\b(galatasaray|fenerbahçe|fenerbahce|beşiktaş|besiktas|trabzonspor|messi|ronaldo|'
    r'star\s+wars|harry\s+potter|netflix|spotify|tiktok|instagram|twitter|youtube\s+kanal|'
    r'siyaset|politika|seçim|secim|cumhurbaşkan|cumhurbaskan)',
    re.IGNORECASE,
)

# 7. KISA_MOTIVASYON — basit "yapamıyorum" tipi (kriz DEĞİL)
_KISA_MOTIVASYON = re.compile(
    r'^(yapam(ı|i)yorum|olmuyor|zor\s+geliyor|kafam\s+karışık|karisik|yorgunum|'
    r'sıkıldım|sikildim|stres|stresli)$',
    re.IGNORECASE,
)

# 8. RENDER_REQUEST — simulasyon/3D/görsel istekleri (Brief #11 etkin kullanım)
# "X simülasyon yap", "interaktif göster", "3D çiz", "görselleştir", "kara delik göster"
# Cerebras'a gider, renderer hint inject olur, zengin görsel cevap üretilir
# NOT: son \b YOK — "simulasyonu", "simulasyonunu" gibi suffix'leri de yakalar
_RENDER_REQUEST = re.compile(
    r'\b(simul[aäe]?sy|simul[aäe]?sy[oö]n|interaktif|3d\s+(g[oö]ster|g[oö]st|[cç]iz|cizi|model|animasy)|'
    r'g[oö]rsel(?:l|le[sş]|lesti|leştir|lestir)|animasy[oö]n|infografik|'
    r'g[oö]ster\s+(bana|nas[iı]l)|sahnesini\s+yap|3\s*boyut|three[\.\s]?js|p5[\.\s]?js|'
    r'\d+d\s+(g[oö]ster|model|cizim|animasy))',
    re.IGNORECASE,
)

# 9. KARSILASTIRMA — X vs Y, kıyasla, fark — compare2 renderer için
_KARSILASTIRMA = re.compile(
    r'\b(kıyasla|kiyasla|karşılaştır|karsilastir|karşılaştırma|karsilastirma|'
    r'\bvs\b|\bvs\.\s|farkı?|farkı\s+nedir|farkı?\s+ne|farklı?l[ıi]k|'
    r'(arasındaki|arasindaki)\s+(fark|benzerlik|ilişki|iliski)|'
    r'mı\s+(daha\s+)?(iyi|fazla|kötü|kotu|önemli|onemli|zor|kolay)|'
    r'mi\s+(daha\s+)?(iyi|fazla|kotu|onemli|zor|kolay))',
    re.IGNORECASE,
)

# 10. QUIZ_REQUEST — interaktif test/quiz istekleri
_QUIZ_REQUEST = re.compile(
    r'\b(quiz|test|sınav|sinav|soru\s*c?ozdür|soru\s*sor|kısa\s+test|kisa\s+test|'
    r'(test|quiz|sınav|sinav|soru)(?:\s+\w+){0,3}\s+(yap|olustur|olu[sş]tur|hazırla|hazirla|haz[iı]rla|cözdür|cozdur))',
    re.IGNORECASE,
)

# 11. KONU_HARITASI — knowledge graph / bağlantı ağı
_KONU_HARITASI = re.compile(
    r'\b((konu|bilgi)\s*(harita|haritası|haritasi|ağı|agi|grafi[ğg]i)|'
    r'graph\s+(göster|olustur|oluştur)|'
    r'(bağlant|baglant|ilişki|iliski)\s*(ağı|agi|haritası|haritasi)|'
    r'kgraph|knowledge\s+graph)',
    re.IGNORECASE,
)


# ── Lane Classifier ────────────────────────────────────────────────────────

GroqSafeLane = Literal[
    "kavramsal_kisa", "sohbet", "meta_direktif", "kibarlik",
    "egitim_icerik", "red_generik", "kisa_motivasyon",
    # 25.37+ (Neo): Cerebras-safe render istekleri (renderer hint inject ile zenginleşir)
    "render_request", "karsilastirma", "quiz_request", "konu_haritasi",
]


def classify_lane(message: str, role: str = "", phone: str = "") -> Optional[str]:
    """Mesaji Groq-safe lane'lerden birine yerlestir.

    Returns: lane name | None (None = Claude'a yolla)
    """
    if not message or not message.strip():
        return None

    text = message.strip()
    text_lower = text.lower()
    text_len = len(text)

    # ── REDDET (Claude'a yolla) ──

    # Kişisel veri
    if _PERSONAL_DATA.search(text_lower):
        return None

    # Tool gerektiren
    if _TOOL_REQUIRED.search(text_lower):
        return None

    # Kriz seviye duygu
    if _KRIZ_PATTERN.search(text_lower):
        return None

    # Frustration — "kaba", "yanlis anladin", "anlamiyorsun" → Claude eskale
    if re.search(r'\b(kaba|yanlis\s+anla|yanlış\s+anla|anlamiyorsun|anlamıyorsun|'
                 r'ne\s+saçma|ne\s+sacma|boş\s+(yapıyor|yapiyor)|bos\s+yapiyor|'
                 r'tekrar\s+söyle|tekrar\s+soyle)', text_lower):
        return None

    # Çok uzun mesaj (>250 char) — büyük ihtimal complex sorgu
    if text_len > 250:
        return None

    # Sayı + "kim/hangi" → veri sorgusu
    # 25.37+ fix: word boundary — "akImI" içindeki "kim" false positive olmasın
    if re.search(r'\b(kim|kimler|hangi|kac|kaç)\b', text_lower):
        # İstisna: kavramsal "X nedir" + "kim" geçebilir ("Newton kimdir")
        if not _KAVRAMSAL_PATTERN.search(text_lower):
            # Ek istisna: meta_direktif veya genel sohbet
            if not _META_DIREKTIF.search(text_lower) and not _GENEL_SOHBET.search(text_lower):
                return None

    # Multi-soru (5+ noktası, virgüllü uzun cümle) → complex
    if text.count(',') >= 4 or text.count('?') >= 3:
        return None

    # ── LANE ATA (Groq'a yolla) ──

    # 4. KIBARLIK (önce, çünkü çok kısa)
    if text_len < 25 and _KIBARLIK.match(text):
        return "kibarlik"

    # KUTLAMA / BAŞARI PAYLAŞIMI — "Fen full", "100 yaptım", "biti̇rdim"
    # Öğrenci pozitif paylaşıyorsa kibar tebrik (Groq yapabilir, kişisel veri sorgu değil)
    if text_len < 60 and re.search(
        r'\b(full\s+(geldi|yaptım|yaptim)|net\s+yaptım|net\s+yaptim|bitirdim|tamamlad[ıi]m|'
        r'cözdüm|çözdüm|cozdum|başard[iı]m|basard[iı]m|aldım\s+\d|cok\s+iyi\s+geçti|'
        r'mukemmel\s+geçti)',
        text_lower,
    ):
        return "kibarlik"

    # 2. SOHBET — selamlama, kapanış (kısa)
    if text_len < 50 and _SOHBET_PATTERN.search(text_lower):
        return "sohbet"

    # 7. KISA_MOTIVASYON (kriz değil, basit)
    if text_len < 50 and _KISA_MOTIVASYON.match(text):
        return "kisa_motivasyon"

    # 3. META_DIREKTIF (bot davranışı)
    if _META_DIREKTIF.search(text_lower):
        return "meta_direktif"

    # 6. RED_GENERIK (kurum dışı eğlenceli)
    if _RED_GENERIK.search(text_lower):
        return "red_generik"

    # GENEL SOHBET — KAVRAMSAL'dan ÖNCE kontrol et!
    # "Balık çorbası rezillikmidir" hem "midir" hem yemek; sohbet öncelikli
    if _GENEL_SOHBET.search(text_lower) and text_len < 150:
        return "sohbet"

    # 1. KAVRAMSAL_KISA — bilgi sorusu, kişisel değil
    if _KAVRAMSAL_PATTERN.search(text_lower) and text_len < 200:
        # Kişisel keyword check ek kat
        if not re.search(r'\b(benim|ben(de|im)|kendi|sahip\s+oldug)', text_lower):
            return "kavramsal_kisa"

    # 5. EGITIM_ICERIK (kurum metodolojisi, kişiselleşmemiş)
    if _EGITIM_ICERIK.search(text_lower) and text_len < 200:
        return "egitim_icerik"

    # ── 25.37+ (Neo): RENDER ISTEKLERI — Cerebras-safe + renderer hint inject ──
    # Bu lane'ler Cerebras'a gider, Brief #11 ile system_prompt'a renderer hint
    # eklenir, bot zenginleştirilmiş cevap üretir (chart/sim/3d/compare2/quiz/kgraph).

    # 11. KONU_HARITASI — kgraph renderer (build_knowledge_graph tool)
    if _KONU_HARITASI.search(text_lower) and text_len < 200:
        return "konu_haritasi"

    # 9. KARSILASTIRMA — compare2 renderer (yan yana matris)
    if _KARSILASTIRMA.search(text_lower) and text_len < 200:
        # Kişisel kıyas (benim X vs Y'nin) → Claude (data sorgu)
        if not re.search(r'\b(benim|kendi|ben(de|im))', text_lower):
            return "karsilastirma"

    # 10. QUIZ_REQUEST — quiz renderer (multi-choice + feedback)
    if _QUIZ_REQUEST.search(text_lower) and text_len < 200:
        return "quiz_request"

    # 8. RENDER_REQUEST — sim/3d/formula renderer (geniş kategori, en sona)
    # ÖNEMLI: kavramsal_kisa veya egitim_icerik ile çakışırsa render kazanır
    # (kullanıcı "X anlat ve göster" derse render lane'i Cerebras'a renderer hint ile gönderir)
    if _RENDER_REQUEST.search(text_lower) and text_len < 250:
        # Kişisel render istekleri (Ali'nin profili gibi) → Claude (compound karne+chart+...)
        if not re.search(r'\b(benim|kendi|\b\w+\s+(adli|adlı|isimli)\s+(öğrenci|ogrenci))', text_lower):
            return "render_request"

    # Hiçbir lane'e uymadı → Claude'a (default güvenli)
    return None


def is_groq_safe(lane: Optional[str]) -> bool:
    """Lane Groq/Cerebras-SAFE mi (vs None=Claude)."""
    return lane in {
        "kavramsal_kisa", "sohbet", "meta_direktif", "kibarlik",
        "egitim_icerik", "red_generik", "kisa_motivasyon",
        # 25.37+ (Neo): render istekleri Cerebras'a, renderer hint inject ile zenginleşir
        "render_request", "karsilastirma", "quiz_request", "konu_haritasi",
    }


# 25.37+ (Neo): Lane → Intent eşlemesi (Cerebras renderer hint için)
# Bu eşleşme cerebras_handler.INTENT_RENDERER_MAP key'leri ile uyumlu olmalı
LANE_TO_INTENT = {
    "kavramsal_kisa":  "kavram_aciklama",
    "egitim_icerik":   "kavram_aciklama",
    "render_request":  "kavram_aciklama",  # formula+sim/3d+steps zorunlu
    "karsilastirma":   "karsilastirma",    # compare2 zorunlu
    "quiz_request":    "kavram_aciklama",  # quiz renderer (kavram için)
    "konu_haritasi":   "plan_yap",         # kgraph
    "sohbet":          "selamlama",
    "kibarlik":        "selamlama",
    "kisa_motivasyon": "motivasyon_destek",
    "meta_direktif":   None,  # renderer YOK
    "red_generik":     None,
}


def get_intent_for_lane(lane: Optional[str]) -> Optional[str]:
    """Lane → INTENT_RENDERER_MAP key. Cerebras handler'a gönderilir."""
    if not lane:
        return None
    return LANE_TO_INTENT.get(lane)


def get_lane_system_addon(lane: str) -> str:
    """Lane'e özel system prompt eklentisi — Groq daha tutarlı yanıtsın."""
    addons = {
        "kavramsal_kisa": (
            "BU MESAJ KISA AKADEMIK KAVRAMSAL SORU. "
            "Kisa (max 150 kelime), net, dogru aciklama yap. "
            "Formul varsa LaTeX yerine duz metin (^2 = kare). "
            "Kisilestirme YAPMA — 'sen', 'sana ozel' deme. Kavrami acikla, ornek 1-2 ver."
        ),
        "sohbet": (
            "BU MESAJ KISA SOHBET. Samimi ama kisa cevap (max 50 kelime). "
            "Akademik konuya ZORLA donme, ogrenci yonlendirirsen kabul et."
        ),
        "meta_direktif": (
            "OGRENCI BOT DAVRANISI HAKKINDA TALIMAT VERIYOR. "
            "Talimati kabul et, KISA ONAYLA (10-20 kelime). "
            "Asiri ozur dileme, asiri aciklama yapma."
        ),
        "kibarlik": (
            "OGRENCI KISA KIBAR REAKSYON YAZDI. "
            "Ayni samimiyetle KISA cevap (5-15 kelime). Yeni konu acma."
        ),
        "egitim_icerik": (
            "OGRENCI EGITIM METODOLOJISI / SINAV STRATEJISI SORUYOR. "
            "Kisilestirilmemis genel rehberlik ver (max 200 kelime). "
            "Kurumun guncel verilerine ozel cevap verme — geniş, prensip bazli yanit."
        ),
        "red_generik": (
            "OGRENCI KURUM DISI / EGLENCELI / SACMA BIR SORU SORDU. "
            "KIBAR ama NET: 'Bu konu uzmanlik alanim disinda' tarzinda. "
            "Ogretmen olarak rolunu hatirlat: 'Akademik konuda yardimci olabilirim'."
        ),
        "kisa_motivasyon": (
            "OGRENCI KISA, BASIT 'YORGUNUM/SIKILIM' MESAJI. "
            "Empati + 1 somut oneri (kisa mola, su ic, basit aktivite). "
            "ASLA kriz analizi yapma — bu basit motivasyon. Max 60 kelime."
        ),
        # 25.37+ (Neo) — Render istekleri için lane prompt'lari
        "render_request": (
            "OGRENCI BIR KAVRAMI GORSEL/SIMULASYON ISTIYOR (kara delik, dna, atom vb). "
            "Mutlaka renderer kullan (```formula + ```sim/```3d + ```steps zorunlu). "
            "Onemli formul + 1-2 paragraf aciklama + interaktif gorsel + sinav baglantisi. "
            "Compton-altin standart akis: tarih + mekanizma + formul + interaktif + AYT/TYT bagi."
        ),
        "karsilastirma": (
            "OGRENCI IKI KAVRAMI KARSILASTIRMA ISTIYOR (X vs Y, fark, mitoz vs mayoz). "
            "MUTLAKA ```compare2 renderer kullan — markdown tablo YASAK. "
            "Yan yana iki kutu (sol/sag), 4-6 satir matris (aspect/left/right), takeaway 1 satir. "
            "Renkli + pedagojik."
        ),
        "quiz_request": (
            "OGRENCI INTERAKTIF QUIZ/TEST ISTIYOR. "
            "MUTLAKA ```quiz renderer kullan: 3-5 multi-choice soru + dogru cevap + aciklama. "
            "Konu sonrasi pekiştirme dongusu (Ebbinghaus). "
            "schedule_recall tool'u da cagir (24h sonra hatirlat)."
        ),
        "konu_haritasi": (
            "OGRENCI KONULAR ARASI ILISKI/HARITA ISTIYOR. "
            "MUTLAKA build_knowledge_graph tool cagir, kgraph_block'u yapistir. "
            "D3 force layout: zayif kirmizi, gucsu yesil. Kisa pedagojik kapanis: "
            "'Hangi konuya odaklanalim?' sor."
        ),
    }
    return addons.get(lane, "")


# Smoke test
if __name__ == "__main__":
    cases = [
        ("propanoik asit IUPAC adi midir", "kavramsal_kisa"),
        ("Yks ye kac gun kaldi", None),  # data_query, kac geçti
        ("turev nedir", "kavramsal_kisa"),
        ("limit kavrami anlat", "kavramsal_kisa"),
        ("selam", "sohbet"),
        ("teşekkür ederim", "sohbet"),
        ("İngilizce devam etsek", "meta_direktif"),
        ("Emoji koymadan konuş", "meta_direktif"),
        ("Japonca devam edelim", "meta_direktif"),
        ("Balık çorbası rezillikmidir", "sohbet"),  # genel_sohbet
        ("Galatasarayın 1971 1972 yedek kadrosu analizini yap", "red_generik"),
        ("benim gelişimim sence nasıl?", None),   # personal
        ("matematikte nasılım sence", None),       # personal
        ("2+2", None),                             # kısa, lane'e uymadı (Claude'a düşer)
        ("yapamıyorum", "kisa_motivasyon"),
        ("intihar etmek istiyorum", None),  # kriz
        ("etut yaz Ali için", None),        # tool_required
        ("Newton kimdir nedir", "kavramsal_kisa"),  # nedir + kavramsal
        ("Süper", "kibarlik"),
        ("YKS stratejisi nasıl olmalı", "egitim_icerik"),
    ]

    print(f"{'Message':<50} | {'Expected':<18} | {'Got':<18} | {'OK?'}")
    print("-" * 100)
    correct = 0
    for msg, expected in cases:
        got = classify_lane(msg, role="ogrenci")
        ok = "OK" if got == expected else "MISMATCH"
        if got == expected:
            correct += 1
        print(f"{msg[:50]:<50} | {str(expected):<18} | {str(got):<18} | {ok}")
    print(f"\nScore: {correct}/{len(cases)}")
