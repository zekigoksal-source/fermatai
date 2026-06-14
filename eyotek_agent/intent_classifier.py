"""
Intent Classifier (Oturum 25.18 — Lane/Intent Olgunluk)
=========================================================

Mesajdan iki şey çıkarır:
- LANE: local LLM path için (groq_lanes.classify_lane — modül adı eski,
  25.22+'da gerçekte Cerebras'a yönlendiriyor)
- INTENT: Tier seçimi + tool subset için + Cerebras intent→model map

ROI: lane=None düşmeyen mesaj sayısı arttıkça, modüler tier
aktivasyonu artar = token tasarrufu artar.

Endüstri standardı: 30+ intent kategorisi (önceki 5'ten).

KULLANIM:
    from intent_classifier import classify_intent
    intent = classify_intent("son denememi açıkla")
    # → "deneme_analiz"

KVKK: Bu modül SADECE intent etiketi döner. Hassas veri sızıntısı yok,
intent etiketleri kamuya açık (plan_yap, kavram_aciklama vs.)
"""
from __future__ import annotations
import re
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# INTENT KATEGORİLERİ (30+ etiket)
# ═══════════════════════════════════════════════════════════════════
#
# Tier mapping (prompt_tiers.py'den okunacak):
# - LIGHT-uyumlu:  selamlama, veda, tesekkur, kavram_aciklama,
#                  kurum_bilgi, yks_takvim, mufredat_bilgi,
#                  motivasyon, sohbet
# - NORMAL-uyumlu: plan_yap, analiz_iste, deneme_analiz, soru_iste,
#                  kaynak_iste, yontem_iste, programa_ekle,
#                  hedef_analiz, puan_tahmin, peer_kiyas, vs.
# - FULL-zorunlu:  finans, admin_action, hassas_veri, role_change,
#                  injection_suspect

# Pattern → intent mapping (sıralı kontrol — önce gelen kazanır)
_INTENT_PATTERNS = [
    # ── A) GÜVENLİK (FULL-zorunlu) — ÖNCE kontrol et ──
    ("injection_suspect", re.compile(
        r'(yukar[ıi]daki?\s+(\S+\s+)?(unut|gormezden|görmezden|sayma|bypass|yok\s+say)|'
        r'system\s+prompt|sistem\s+prompt|'
        r'\bignore\s+(all\s+)?(previous|prior)|talimatlari?\s+(unut|sayma|gormezden|gormez)|'
        r'kurallar[ıi]?\s+(unut|sayma|kald[ıi]r|yok\s+say|kabul\s+etme)|'
        r'\bDAN\s+mod|kuralsız\s+ol|kuralsiz\s+ol|jailbreak)',
        re.I,
    )),
    ("role_change", re.compile(
        r'(yetkimi?\s+(yukselt|yükselt|degistir|değiştir)|'
        r'rol\s+(değiş|degis|degistir|değiştir)|'
        r'admin\s+(yap|ol|panel|moduna)|ben\s+admin(im|sin|olarak)|'
        r'ben\s+(neo|kurum\s+sahibi|yönetici|yonetici))',
        re.I,
    )),
    ("hassas_veri", re.compile(
        r'(telefon\s*(numara|listele|ver)|'
        r'tc\s+(no|kimlik)|adres\s+(ver|liste)|'
        r'veli\s+(numara|telefon|iletisim|iletişim)|'
        r'anne\s+(telefon|cep|numara)|baba\s+(telefon|cep|numara)|'
        r'(başka|baska|diğer|diger)\s+(öğrenci|ogrenci|hoca)|'
        # 25.18 ek: bilinen öğrenci ismi + akademik veri istegi (KVKK)
        r'\b(taha|ecrin|damla|ada|yiğit|yigit|nazlı|nazli|doruk|ayşe|ayse|arda|mehmet\s+alp)\s*[\'’]?(n[ıi]n)?\s*'
        r'(net|notu?|s[ıi]nav|deneme|puan|durum|kac|kaç|hocas[ıi]|sinif|sınıf))',
        re.I,
    )),
    ("finans", re.compile(
        r'\b(borç|borc|ödeme|odeme|tahsilat|maaş|maas|ücret|ucret|'
        r'fiyat|kurs\s+(ücret|ucret|fiyat)|kaç\s+(tl|lira)|kac\s+(tl|lira)|'
        r'muhasebe|fatura|makbuz|borç\s+detay|borc\s+detay)',
        re.I,
    )),
    ("admin_action", re.compile(
        r'\b(blokla|engelle|sms\s+(gönder|gonder|at)|toplu\s+(mesaj|sms)|'
        r'\bACL\b|sistem\s+durum|backup\s+(al|yap)|atlas\s+(öneri|oneri))',
        re.I,
    )),

    # ── B) PLAN/ANALİZ (NORMAL tier) ──
    ("plan_yap", re.compile(
        r'(plan\s+(yap|olustur|oluştur|ver|istiyorum|hazirla|hazırla|yapsana)|'
        r'çalışma\s+plan|calisma\s+plan|haftalik\s+plan|haftalık\s+plan|'
        r'günlük\s+plan|gunluk\s+plan|program\s+(yap|olustur|oluştur))',
        re.I,
    )),
    ("deneme_analiz", re.compile(
        r'(son\s+denemem|deneme\s+(analiz|sonuc|sonuç|incele)|netim\b|netlerim|'
        r'tyt\s+netim|ayt\s+netim|denemedeki|sınav\s+sonuç|sinav\s+sonuc)',
        re.I,
    )),
    ("analiz_iste", re.compile(
        r'(analiz\s+(et|yap|ver)|kıyasla|kiyasla|karşılaştır|karsilastir|'
        r'rapor\s+(çek|cek|getir)|gidişat|gidisat|durumum|performansım|performansim|'
        r'gelişimim|gelisimim|ilerleyişim|ilerleyisim)',
        re.I,
    )),
    ("hedef_analiz", re.compile(
        r'(hedef\s+(bölüm|bolum|puan|üniversite|universite)|'
        r'hangi\s+(bölüm|bolum|üniversite|universite)\s+(girer|girebilir)|'
        r'kac\s+net\s+(yapmali|yapmalı|gerek)|kaç\s+net\s+(yapmali|yapmalı|gerek)|'
        r'\bITU\b|\bODTU\b|\bODTÜ\b|İTÜ|tıp\s+icin|tip\s+icin|mühendislik\s+icin)',
        re.I,
    )),
    ("puan_tahmin", re.compile(
        r'(puanım\s+(ne|kac|kaç|nedir)|puanim\s+(ne|kac|kaç|nedir)|'
        r'tahmini\s+puan|puan\s+tahmin|hangi\s+puan|kac\s+puan\s+(yapiyo|yapıyo|yaparim))',
        re.I,
    )),
    ("peer_kiyas", re.compile(
        r'(sınıf\s+(ortalama|kıyas|ort)|sinif\s+(ortalama|kiyas|ort)|'
        r'peer\s+(kiyas|kıyas)|akran\s+(kıyas|kiyas|karsi|karşı)|'
        r'sıralama|siralama|kacinciyim|kaçıncıyım)',
        re.I,
    )),

    # ── C) SORU/KAYNAK/PROGRAMA EKLE (NORMAL tier) ──
    # 25.40o (Neo direktif): yeni içerik üretim intent'leri gpt-oss-120b'ye gider
    # Order matters — bunlar soru_iste'den ÖNCE (üretim ≠ getir/göster)
    ("yeni_nesil_uret", re.compile(
        r'(yeni\s+nesil|maarif\s+(uyumlu|stil|m[uü]fredat)|lgs\s+tipi|yks\s+tipi|'
        r'\b\d{4}\s+(maarif|m[uü]fredat))',
        re.I,
    )),
    ("test_olusturma", re.compile(
        r'(test\s+(hazirla|hazırla|olu[sş]tur|yap|yaz)|konu\s+tarama|tarama\s+test|'
        r'de[gğ]erlendirme\s+(yazılı|yazili)|yazılı\s+(hazirla|hazırla|olu[sş]tur)|'
        r'\d{1,3}\s+soru(luk)?\s+(test|sinav|sınav)|'
        r'(haftalık|aylık|ünite)\s+(test|de[gğ]erlendirme))',
        re.I,
    )),
    ("soru_uret", re.compile(
        r'((soru|sorular)\s+(üret|uret|hazırla|hazirla|yaz|olu[sş]tur)|'
        r'\d{1,3}\s+(soru|alı[sş]tırma|al[iı]stirma)\s+(üret|uret|yaz|hazırla|hazirla)|'
        r'çalı[sş]tırma\s+(üret|uret|hazırla|hazirla)|'
        r'al[iı]ş?t[iı]rma\s+(soru|hazırla|hazirla|yaz))',
        re.I,
    )),
    ("ornek_paket_uret", re.compile(
        r'(\d{1,3}\s+örnek\s+(üret|uret|yaz|hazırla|hazirla)|'
        r'(birka[cç]|bir\s+ka[cç])\s+örnek\s+(üret|uret|yaz)|'
        r'etkinlik\s+(hazırla|hazirla|olu[sş]tur))',
        re.I,
    )),
    ("konu_anlatim_uzun", re.compile(
        r'(detayl[iı]\s+(anlat|aç[iı]kla)|'
        r'(uzun|kapsamlı|kapsamli)\s+(anlatım|anlatim|aç[iı]klama)|'
        r'(tüm|tum|bütün|butun)\s+konuyu\s+anlat|'
        r'(konuyu|konu)\s+detayl[iı]\s+anlat)',
        re.I,
    )),
    ("karsilastirma", re.compile(
        r'((kar[sş][iı]la[sş]t[iı]r)|kıyasla|kiyasla|'
        r'(arasındaki|arasindaki)\s+(fark|benzer)|'
        r'\b\w+\s+vs\.?\s+\w+|'
        r'\b\w+\s+ile\s+\w+\s+(fark|benzer|kıyas|kiyas))',
        re.I,
    )),
    ("metin_zenginlestir", re.compile(
        r'(zenginle[sş]tir|geni[sş]let|aç[iı]l[iı]ml[iı]\s+yaz|'
        r'(daha|biraz)\s+(detayl[iı]|kapsamlı|kapsamli)\s+yaz|'
        r'aç[iı]klamayı\s+(genişlet|genislet|büyüt|buyut))',
        re.I,
    )),
    ("soru_iste", re.compile(
        r'(çıkmış\s+soru|cikmis\s+soru|soru\s+(göster|goster|at|paylaş|paylas)|'
        r'\d{4}\s+(tyt|ayt)\s+sor|sorular\s+(getir|göster|goster))',
        re.I,
    )),
    ("kaynak_iste", re.compile(
        r'(kaynak\s+(öner|oner|var\s+mı|var\s+mi|tavsiye)|'
        r'video\s+(öner|oner|var)|kitap\s+(öner|oner|tavsiye)|'
        r'youtube\s+(öner|oner|video)|hangi\s+(kitap|video|kaynak))',
        re.I,
    )),
    ("yontem_iste", re.compile(
        r'(nasıl\s+(çalış|calis|öğren|ogren)|nasil\s+(çalış|calis|öğren|ogren)|'
        r'çalışma\s+yöntem|calisma\s+yontem|öğrenme\s+teknik|ogrenme\s+teknik|'
        r'pomodoro|feynman|aktif\s+öğrenme|aktif\s+ogrenme)',
        re.I,
    )),
    ("programa_ekle", re.compile(
        r'(programa\s+(ekle|koy)|çalışmama\s+ekle|calismama\s+ekle|'
        r'panele\s+(ekle|kaydet)|takvime\s+ekle|'
        r'(saat\s+)?\d{1,2}[:\.:]\d{2}\s+(ekle|koy|olarak)|'
        r'\d{1,2}[:\.:]\d{2}\s+\w+\s+(ekle|koy)|'
        r'\b\w+\s+\d{1,2}[:\.:]\d{2}\s+(ekle|koy)|'
        r'ekleyebilir\s+misin|ekle\s+lütfen|ekle\s+lutfen)',
        re.I,
    )),
    ("foto_soru", re.compile(
        r'(foto\s+(soru|çöz|coz)|fotoğraf|fotograf|resim\s+(çöz|coz)|'
        r'soru\s+çöz|soru\s+coz|şu\s+soruyu\s+çöz|su\s+soruyu\s+coz)',
        re.I,
    )),

    # ── D) KAVRAMSAL/EĞİTİM (LIGHT tier) ──
    ("kavram_aciklama", re.compile(
        r'(\bnedir\??|ne\s+demek|nasıl\s+çalış|nasil\s+calis|'
        r'\b(açıkla|acikla|anlat|öğret|ogret)|kısaca\s+anlat|kisaca\s+anlat|'
        r'tanım[ıi]?|tanim[ıi]?|formul[üu]?|formül[üu]?|'
        r'kuralı?|kanunu?|teoremi?|prensibi?|özellik|ozellik|'
        # 25.58-AA: doğal ifadeli kavramsal sorular (açık "nedir/anlat" yok ama
        # saf kavram sorusu — kişisel/veri guard yukarıda korur → güvenli Cerebras)
        r'ne\s+i[sş]e\s+yarar|neden\s+olu[rs]|neden\s+gerçekle|neden\s+gerceklesir|'
        r'nas[iı]l\s+olu[sş]|nas[iı]l\s+gerçekle|nas[iı]l\s+gerceklesir|nas[iı]l\s+meydana|'
        r'fark[ıi]\s+ne(dir)?|ne\s+gibi|hangi\s+durumda|ne\s+zaman\s+olu[rs])',
        re.I,
    )),
    ("ornek_iste", re.compile(
        r'(örnek\s+(ver|göster|goster)|ornek\s+(ver|goster)|'
        r'\d+\s+örnek|tipik\s+örnek|örnekle|orneklendir)',
        re.I,
    )),
    ("cozum_iste", re.compile(
        r'(nasıl\s+çözülür|nasil\s+cozulur|çözüm\s+(yap|göster|goster|tekni)|'
        r'cozum\s+(yap|goster|tekni)|şu\s+(soruyu|problemi)\s+(çöz|coz)|'
        r'su\s+(soruyu|problemi)\s+(çöz|coz))',
        re.I,
    )),
    ("ozet_iste", re.compile(
        r'(özet\s+(çıkar|cikar|ver|geç|gec)|ozet\s+(cikar|ver|gec)|'
        r'kısa(ca)?\s+(özet|ozet|geç|gec)|kisa(ca)?\s+(ozet|gec))',
        re.I,
    )),
    ("kurum_bilgi", re.compile(
        r'(fermat\s+(nedir|hakkında|hakkinda|kim|adres|nerede)|'
        r'kurs\s+(adres|nerede|telefon)|kurum\s+(adres|telefon|web)|'
        r'çalışma\s+saatleri|calisma\s+saatleri)',
        re.I,
    )),
    ("yks_takvim", re.compile(
        r'(yks\s+(ne\s+zaman|tarih|kaç\s+gün|kac\s+gun)|'
        r'tyt\s+(ne\s+zaman|tarih)|ayt\s+(ne\s+zaman|tarih)|'
        r'lgs\s+(ne\s+zaman|tarih)|sınava\s+kaç\s+gün|sinava\s+kac\s+gun|'
        r'kac\s+gun\s+kaldi|kaç\s+gün\s+kaldı)',
        re.I,
    )),
    ("mufredat_bilgi", re.compile(
        r'(tyt\s+(format|kaç\s+soru|kac\s+soru|hangi\s+ders)|'
        r'ayt\s+(format|kaç\s+soru|kac\s+soru|sayısal|sayisal|sözel|sozel)|'
        r'lgs\s+(format|kaç\s+soru|kac\s+soru)|'
        r'sınav\s+sistem|sinav\s+sistem|müfredat|mufredat|kazanım\s+listes|kazanim\s+listes)',
        re.I,
    )),

    # ── E) DUYGU/SOHBET (LIGHT tier) ──
    ("selamlama", re.compile(
        r'^(merhaba|selam|selamünaleyküm|hey|hi|hello|sa\b|nbr|naber|'
        r'nasılsın|nasilsin|hoş\s+geldin|hos\s+geldin|iyi\s+(gun|gün|ak[şs]am|gece|sabah))',
        re.I,
    )),
    ("veda", re.compile(
        r'^(görüşürüz|gorusuruz|hoşça|hosca|bye|by\b|hadi\s+(eyv|gor)|'
        r'iyi\s+geceler|iyi\s+aksamlar|kapan|kapanış|kapanis)',
        re.I,
    )),
    ("tesekkur", re.compile(
        r'^(teşekkür|teşekkurler|tesekkur|tesekkurler|sağol|sagol|saol|'
        r'eyvallah|tank you|thanks|tşk|cok\s+sağol|cok\s+sagol|sen\s+harikasin|sen\s+harikasın)',
        re.I,
    )),
    ("motivasyon_destek", re.compile(
        r'(yapamayacağım|yapamayacagim|yapamıyorum|yapamiyorum|'
        r'pes\s+ediyor|moralim\s+bozuk|umutsuzum|sıkıldım|sikildim|'
        r'çalışacak\s+enerjim\s+yok|calisacak\s+enerjim\s+yok|tükendim|tukendim)',
        re.I,
    )),
    ("duygu_paylasim", re.compile(
        r'(üzgünüm|uzgunum|kötü\s+hissediyorum|kotu\s+hissediyorum|'
        r'mutluyum|sevinçliyim|sevincliyim|coşkuluyum|coskuluyum|'
        r'heyecanlıyım|heyecanliyim|gerginim|stresliyim)',
        re.I,
    )),
    ("uretim_paylas", re.compile(
        r'(bitirdim|tamamladım|tamamladim|yaptım\s+\d|yaptim\s+\d|'
        r'\d+\s+net\s+(yaptım|yaptim|geldim)|full\s+(geldi|yaptım|yaptim)|'
        r'çözdüm|cozdum|başardım|basardim)',
        re.I,
    )),

    # ── F) META/SİSTEM ──
    ("meta_direktif", re.compile(
        r'(emoji(siz)?\s+(koy|kullan|olmadan)|sade\s+(konuş|konus)|'
        r'kısa\s+(konuş|konus|cevap)|kisa\s+(konus|cevap)|'
        r'türkçe\s+(devam|konuş|konus)|turkce\s+(devam|konus|konuş)|'
        r'formal|resmi\s+(ol|konuş|konus))',
        re.I,
    )),
    ("yetenek_sorgu", re.compile(
        r'(neler\s+yapabilir|ne\s+yapabilir|kabiliyetlerin|yeteneklerin|'
        r'özelliklerin\s+ne|ozelliklerin\s+ne|sen\s+kimsin|kimsin\s+sen)',
        re.I,
    )),
]


from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=512)
def classify_intent(message: str) -> Optional[str]:
    """Mesaj içeriğine göre intent etiketi dön (None → bilinmiyor).

    25.58 (hot-path verim): SAF fonksiyon (regex + tr_normalize, yan etki yok) →
    lru_cache. Aynı mesaj için routing_engine güvenlik-guard'ı + fermat_core_agent
    iki kez çağırıyordu (~100 pattern taraması x2) — ikincisi artık ~0ms.

    Sıralı kontrol: önce güvenlik (injection/role/hassas/finans),
    sonra plan/analiz, sonra kavramsal/sohbet.

    25.21: Hem orijinal hem normalize edilmiş metinde arama yapılır
    (Türkçe karakter varyasyonları için: "kısaca" / "kisaca").

    Args:
        message: kullanıcı mesajı (raw)

    Returns:
        intent string ya da None (eşleşme yok)
    """
    if not message or not isinstance(message, str):
        return None
    text = message.strip()
    if not text:
        return None
    # 25.21: normalize edilmiş varyantı da hazırla (Türkçe karakter eşleşmesi)
    try:
        from text_normalize import tr_normalize
        text_norm = tr_normalize(text)
    except Exception:
        text_norm = text.lower()

    for intent_name, pattern in _INTENT_PATTERNS:
        try:
            if pattern.search(text) or pattern.search(text_norm):
                return intent_name
        except Exception:
            continue
    return None


# Intent → tier hint (prompt_tiers'a sinyal)
INTENT_TIER_HINT = {
    # FULL-zorunlu (güvenlik)
    "injection_suspect": "full",
    "role_change": "full",
    "hassas_veri": "full",
    "finans": "full",
    "admin_action": "full",
    # NORMAL-uyumlu (tool gerek)
    "plan_yap": "normal",
    "deneme_analiz": "normal",
    "analiz_iste": "normal",
    "hedef_analiz": "normal",
    "puan_tahmin": "normal",
    "peer_kiyas": "normal",
    "soru_iste": "normal",
    "kaynak_iste": "normal",
    "yontem_iste": "normal",
    "programa_ekle": "normal",
    "foto_soru": "normal",
    # 25.40o (Neo direktif): Yeni içerik üretim intent'leri NORMAL tier
    # search_curriculum tool gerekir (RAG'dan yeni nesil paket çek + adapte)
    # gpt-oss-120b modeline cerebras_handler INTENT_TO_MODEL üzerinden yönlendirilir
    "test_olusturma": "normal",
    "soru_uret": "normal",
    "yeni_nesil_uret": "normal",
    "ornek_paket_uret": "normal",
    "konu_anlatim_uzun": "normal",
    "karsilastirma": "normal",
    "metin_zenginlestir": "light",  # tool yok, sadece RAG context
    # LIGHT-uyumlu (sadece prompt yeterli, tool yok)
    "kavram_aciklama": "light",
    "ornek_iste": "light",
    "cozum_iste": "light",
    "ozet_iste": "light",
    "kurum_bilgi": "light",
    "yks_takvim": "light",
    "mufredat_bilgi": "light",
    "selamlama": "light",
    "veda": "light",
    "tesekkur": "light",
    "motivasyon_destek": "light",
    "duygu_paylasim": "light",
    "uretim_paylas": "light",
    "meta_direktif": "light",
    "yetenek_sorgu": "light",
}


# Intent → tool subset (Faz 4: gerçek intent-based tool routing)
# NORMAL tier alındığında bu tool'ları whitelist'le kesişime sok
# Boş set = LIGHT yeterli, hiç tool yok
INTENT_TOOL_SUBSET = {
    # Plan üretme — sadece plan tool'ları
    "plan_yap": {
        "build_study_plan_context", "plan_kaydet", "plan_getir",
        "plan_gun_guncelle", "add_to_student_program",
    },
    # Deneme analizi — sadece akademik veri tool'ları
    "deneme_analiz": {
        "get_student_analytics", "get_ayt_analysis", "ogrenci_peer_kiyas",
    },
    # Genel analiz — query_analytics + bireysel
    "analiz_iste": {
        "query_analytics", "get_student_analytics", "get_ayt_analysis",
        "ogrenci_peer_kiyas",
    },
    # Hedef analizi — YOK Atlas + puan
    "hedef_analiz": {
        "puan_tahmin", "hedef_puan_analiz", "ogrenci_nereye_girebilir",
        "hedef_bolum_ara", "calculate_yks_score",
    },
    # Puan tahmin — minimal
    "puan_tahmin": {
        "puan_tahmin", "calculate_yks_score",
    },
    # Peer kıyas
    "peer_kiyas": {
        "ogrenci_peer_kiyas", "query_analytics",
    },
    # Soru gösterimi
    "soru_iste": {
        "list_exam_questions", "send_exam_image", "search_curriculum",
    },
    # Kaynak/video — YouTube + RAG
    "kaynak_iste": {
        "konu_kaynak_paketi", "youtube_oner", "deep_research_paket",
        "ogm_yonlendir", "search_curriculum",
    },
    # Yöntem önerisi — pedagojik
    "yontem_iste": {
        "search_curriculum", "konu_kaynak_paketi",
    },
    # Programa ekleme — minimum 1 tool
    "programa_ekle": {
        "add_to_student_program",
    },
    # Foto soru — Vision (programatik, ama tool olarak)
    "foto_soru": {
        "search_curriculum",  # destek
    },
    # 25.40o (Neo direktif): Yeni icerik uretim → search_curriculum (RAG yeni nesil paket)
    # Bot RAG'dan ornek paket ceker, gpt-oss-120b ile zenginlestirir/adapte eder
    "test_olusturma": {
        "search_curriculum", "list_exam_questions", "send_exam_image",
    },
    "soru_uret": {
        "search_curriculum", "list_exam_questions",
    },
    "yeni_nesil_uret": {
        "search_curriculum",  # ana tool — RAG yeni nesil paket cek
    },
    "ornek_paket_uret": {
        "search_curriculum",
    },
    "konu_anlatim_uzun": {
        "search_curriculum",
    },
    "karsilastirma": {
        "search_curriculum", "bolum_karsilastir",  # konu kıyası + bölüm kıyası
    },
    # LIGHT — hiç tool yok (sadece prompt cevaplar)
    "kavram_aciklama": set(),
    "ornek_iste": set(),
    "cozum_iste": set(),
    "ozet_iste": set(),
    "kurum_bilgi": set(),
    "yks_takvim": set(),
    "mufredat_bilgi": set(),
    "selamlama": set(),
    "veda": set(),
    "tesekkur": set(),
    "motivasyon_destek": set(),
    "duygu_paylasim": set(),
    "uretim_paylas": set(),
    "meta_direktif": set(),
    "yetenek_sorgu": set(),
}


def get_intent_tool_subset(intent: Optional[str]) -> Optional[set]:
    """Intent'e göre izinli tool whitelist (None → tüm NORMAL whitelist)."""
    if not intent:
        return None
    return INTENT_TOOL_SUBSET.get(intent)


def get_intent_tier_hint(intent: Optional[str]) -> Optional[str]:
    """Intent'e göre tier sinyali (None → tier kendi karar versin)."""
    if not intent:
        return None
    return INTENT_TIER_HINT.get(intent)
