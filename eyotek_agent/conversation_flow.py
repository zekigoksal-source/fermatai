"""
FermatAI — Konusma Akiciligi (UX Layer)
========================================
WhatsApp'ta "yaziyor..." gostergesi olmadigi icin uzun analizlerde
sessizlik "bot coktu/yavas" gibi algilaniyor.

ÇÖZÜM:
1. PRE-FILLER: Uzun analiz baslamadan once ZENGINLESTIRILMIS dolgu
   "Bekle, kaliteli bir analiz hazirliyorum..." tarzi
2. POST-FOLLOWUP: Uzun yanit sonrasi teyit
   "Dogru anlamis miyim, eklemek istedigin baska sey var mi?"
3. CESITLILIK: Her komut icin 5-10 varyasyon, son kullanilan tekrar etmez
4. KISISELLESTIRME: Ad + konu + komut tipine ozel

Kullanim (bridge.py icinden):
  from conversation_flow import detect_long_intent, send_pre_filler, send_post_followup
  intent = detect_long_intent(text)
  if intent:
      asyncio.create_task(send_pre_filler(phone, intent, name=name))
"""

import asyncio
import random
import re
from datetime import datetime
from typing import Optional

from loguru import logger


# ─────────────────────────────────────────
# 1. UZUN-CALISAN INTENT TESPITI
# ─────────────────────────────────────────
# Bu komutlar/desenler genelde >5sn surer (Claude API + tool_call + DB)

_LONG_INTENT_PATTERNS = {
    # Komut → (regex_pattern, ortalama_sure_sn, kategori)
    'puan_tahmin': (
        r'(puan\s*(tahmin|analiz)|yks\s*tahmin|tahmin\s*et|kac\s*puan|puan(in|i|im)?\s*ne|net(in|i)?\s*tahmin)',
        15, 'analiz'
    ),
    'etut_oneri': (
        r'(et[uü]t\s*[oö]ner|akilli\s*et[uü]t|et[uü]t\s*[oö]nce|et[uü]t\s*planla|et[uü]t\s*ihtiyac)',
        12, 'analiz'
    ),
    'pdf_rapor': (
        r'(pdf\s*rapor|rapor\s*pdf|rapor\s*[uü]ret|aylik\s*ar[sş]iv|rapor\s*olustur|pdf\s*olu[sş]tur)',
        25, 'rapor'
    ),
    'kurum_zorluk': (
        r'(zorluk\s*(haritas|analiz|rapor)|kurum\s*zay[iı]f|zay[iı]f\s*konu(lar)?\s*kurum|hangi\s*konuda\s*zay)',
        10, 'analiz'
    ),
    'deneme_analiz': (
        r'(deneme\s*(analiz|incele|yorumla|degerlendir)|denemeler(i|ini)?\s*(analiz|incele|yorumla|bak)|son\s*deneme(yi|leri|lerini)?\s*(incele|analiz|yorumla|degerlendir|ozetle|goster|bak)|sinav\s*kar[sş]ila[sş]tir|deneme(s|si|leri)?\s*nas[iı]l)',
        18, 'analiz'
    ),
    'calisma_plani': (
        r'(calisma\s*plan[iı]\s*(yap|olustur|hazirla|cikar)|haftalik\s*plan|kisisel\s*plan|gunluk\s*plan|plan\s*hazirla|nas[iı]l\s*calis)',
        20, 'plan'
    ),
    'kurum_ozet': (
        r'(kurum\s*([oö]zet|geneli|genel)|genel\s*rapor|genel\s*durum|kurumsal\s*rapor|kurum\s*neye|kurum\s*nas[iı]l)',
        15, 'rapor'
    ),
    'foto_solve': (
        r'(\[FOTO\s*SORU)',
        12, 'cozum'
    ),
    'self_diagnosis': (
        r'(\btani\b|kalite\s*raporu|son\s*hatalar|konu[sş]malar(a|i)\s*bak|hata\s*var\s*mi)',
        8, 'analiz'
    ),
    'oneri_uret': (
        r'(oneri\s*[uü]ret|oneri\s*tara|iyilestirme\s*[oö]nerileri|oneri\s*listesi)',
        10, 'analiz'
    ),
    'profil_analiz': (
        r'(profilim|durumum\s*nedir|durumum\s*nas[iı]l|durum\s*nas[iı]l|durum\s*g[oö]z[uü]k|gelisim\s*raporum|akademik\s*durumum|akademik\s*durum|nas[iı]l\s*g[oö]z[uü]k|durumu\s*nas[iı]l|icin\s*durum)',
        10, 'analiz'
    ),
    'muh_analiz': (
        r'(\b(en\s*basaril|en\s*kotuya|en\s*aktif|trend|kar[sş]ila[sş]tir|grafik|inceleme|degerlendir|yorumla|raporla|ozetle|tara|listele)\b)',
        10, 'analiz'
    ),
}

# Generic fallback: mesaj long ise ve action verb iceriyorsa
_ACTION_VERBS = re.compile(
    r'\b(yap|et|olustur|hazirla|incele|analiz|yorumla|cikar|degerlendir|raporla|tara|'
    r'goster|ozetle|listele|bak|ara|sorgula|hesapla|tahmin|planla|nas[iı]l|nedir|kim|'
    r'hangi|kac|nicin|neden|nerede|acikla|anlat|ogret|cozer|coz|nasil)\b',
    re.IGNORECASE
)

# Cok kisa selamlama / onay mesajlari
_SHORT_SKIPS = {
    "merhaba", "selam", "hi", "hello", "tesekkurler", "sagol", "evet", "tamam",
    "ok", "okey", "anlad[iı]m", "iyi", "guzel", "harika", "sağ ol", "saol",
    "iyi g[uü]nler", "iyi aksamlar", "g[oö]r[uü][sş][uü]r[uü]z", "bye", "goodbye",
}


def detect_long_intent(text: str) -> Optional[dict]:
    """
    Mesaj uzun-calisan bir intent mi? Tespit et.
    Returns: {'intent': str, 'sure': int, 'kategori': str} veya None

    Strateji:
    1. Spesifik pattern'larla dene (puan_tahmin, etut_oneri vb)
    2. Yoksa: mesaj 20+ char + action verb iceriyorsa GENERIC long-intent
    3. Cok kisa selamlama mesajlari skip
    """
    if not text or len(text) < 4:
        return None
    t = text.lower().strip()
    if t in _SHORT_SKIPS:
        return None

    # 1. Spesifik pattern'lar
    for intent, (pattern, sure, kategori) in _LONG_INTENT_PATTERNS.items():
        if re.search(pattern, t, re.IGNORECASE):
            return {'intent': intent, 'sure': sure, 'kategori': kategori}

    # 2. Generic fallback: 20+ char + action verb (yap/et/incele/nasıl vb)
    # Bu ozellikle "Taha icin durum nasil gozukuyor" gibi cumleleri yakalar
    if len(t) >= 20 and _ACTION_VERBS.search(t):
        return {'intent': '_generic', 'sure': 12, 'kategori': 'analiz'}

    return None


# ─────────────────────────────────────────
# 2. DOLGU MESAJ KUTUPHANESI
# ─────────────────────────────────────────
# Her intent icin 5-10 varyasyon. Cesitlilik icin son kullanilan tekrar etmez.
# {name} → ogrenci/admin adi

_PRE_FILLERS = {
    'puan_tahmin': [
        "🎯 *{name}* için denemeler masada, trend çıkarıyorum...\n_Birkaç saniye — iyi rapor geliyor_ ⏳",
        "📊 *{subject}* analizine giriyorum. Netler + katsayılar + hedef farkı — hepsi masaya geliyor ✨",
        "🏆 Yerleşme puanı hesabı için son 10 denemeye bakıyorum, dalgalanmaları da çıkartıyorum.",
        "🔍 TYT + AYT katsayılarını uyguluyorum... Birazdan *{name}* için net tablo çıkar 📈",
        "📐 Deneme-by-deneme kronolojiyi diziyorum — hangi derste artış, hangi derste düşüş — görelim ⏰",
        "🎓 YKS resmi formülü çalıştırıyorum ({name} son 3 deneme averajında). _Sabrın değecek_ 💪",
        "⚡ 12 katmanlı puan analizi başladı — ham + yerleşme + hedef gap + önceliği değerlendiriyorum.",
        "📋 Verileri inceliyorum *{name}*. Eyotek resmi hesabı da çekiyorum — biraz sonra net tablo elinde 🎯",
        "🌟 *{name}* için puan röntgeni: tarihsel seyir + bölüm hedefi + eksik net sayısı birazdan 🔬",
        "⏱️ Hesap makinesi çalışıyor, YKS puan tahmin motoru devrede. Yakında hazır ✨",
        "💼 Puan tablosu çıkıyor — gelişim bandı + hedef mesafesi + kritik dersler... _~15sn_ 📊",
    ],
    'etut_oneri': [
        "🎯 *{name}* için en verimli etüt seansını hesaplıyorum. Öğretmen + slot + eksik konu kesişimi...",
        "👨‍🏫 Uygun öğretmenleri tarıyorum, haftalık boşlukları çakıştırıyorum. Birazdan en iyi 3 öneri ⏰",
        "📋 Zayıf konu haritası hazır, şimdi *müsait öğretmen × boş slot* eşleştirmesi yapıyorum 🔥",
        "🧩 Etüt puzzle'ı: zayıflık + uzman + zaman + tutarlılık. Parçaları bir araya getiriyorum ⏳",
        "📅 Program takvimine bakıyorum, *{name}* için en uygun seansları çıkartıyorum. Biraz bekle 🎓",
        "🔎 Ders-ders öğretmen eşleşmesi aranıyor — kimin hangi slotu boş, hangisi güçlü yönde uzman...",
        "✍️ Etüt planlaması sürüyor: *{name}* için 3 ders önceliği + 3 öğretmen + 3 slot önereceğim ⚡",
    ],
    'pdf_rapor': [
        "📄 *{name}* raporu PDF'e aktarılıyor — tüm analizler tek dosyada toplanıyor ⏳",
        "🖨️ Rapor baskısı hazırlanıyor: sınav tablosu + zayıf konular + öneriler + YKS tahmin...",
        "📑 *{name}* için profesyonel PDF yazıyorum — birazdan WhatsApp'tan düşer 📤",
        "📊 Akademik karne hazırlanıyor. Veri + grafik + yorum bir arada — _~25sn_ 💼",
        "📝 Kurumsal PDF şablonunda rapor basılıyor. Birkaç saniye sabır, değerli çıktı geliyor ✨",
    ],
    'kurum_zorluk': [
        "📊 Kurum zorluk haritası çiziliyor — hangi konuda kaç öğrenci zorlanıyor, bakalım 🌡️",
        "🔬 Ders-konu ısı haritası: binlerce öğrenci-konu kaydını tarıyorum ⏳",
        "🎯 Kurum geneli darboğaz analizi çalışıyor, stratejik öncelikler çıkıyor...",
        "📉 En çok hata yapılan konular listesi geliyor — öğretmen toplantısı için altın veri 💎",
    ],
    'deneme_analiz': [
        # Isimli
        "📈 *{name}* denemelerini kronolojik inceliyorum, trend çiziliyor ⏳",
        "📊 *{name}* için sınav karşılaştırması: son denemelere derin bakış...",
        "🔎 *{name}* için deneme detayları çıkıyor, hangi derste ne olmuş bakıyorum ⏰",
        "💼 *{name}* sınav röntgeni masada — ders bazlı kıyas hazırlanıyor 🎯",
        # Isimsiz, cesitlilik
        "🔬 Ders bazlı oynaklık + artış/düşüş desenleri çıkıyor — birazdan pedagojik yorumla 🎓",
        "🎯 Deneme röntgeni: güçlü yönler + kritik düşüşler + hedef puan mesafesi ⚡",
        "📉 Net trendini ölçüyorum, sorunlu dersler filtreleniyor. Az kaldı ✨",
        "📐 Sınav-by-sınav analiz: artış/düşüş akışı çıkartılıyor 📊",
        "🧮 Net hesabı + ders bazlı varyans + ortalama bandı hesaplanıyor ⏳",
        "🎼 Denemeleri bir senfoni gibi düzenliyorum — net seyirler ortaya çıkıyor 🎵",
        "🌡️ Performans termometresini okuyorum — kritik noktalar işaretleniyor ⏰",
        # Samimi, reaction
        "🤔 Bu denemelerin ardındaki hikayeyi okuyorum, biraz sabır 📖",
        "✨ Sayılardan anlam çıkarıyorum, _hak eden bir analiz_ olacak 💪",
    ],
    'calisma_plani': [
        # Isimli, samimi
        "📅 *{name}* için kişisel plan masada — zayıflıklar + program + yöntem karışımı 🎯",
        "🧠 *{name}* için 7 günlük yol haritası çiziliyor — net kazanım hedefiyle ⚡",
        "💼 *{name}* sınıfının ders programını da hesaba katıyorum, çakışma olmasın 🗓️",
        "🎓 *{name}*, kişisel planın hazırlanıyor — şablon değil, gerçek senin için ✨",
        # Genel, çeşit
        "📚 Haftalık çalışma iskeleti çıkıyor. Ders × konu × süre × yöntem matrisi işliyor ⏳",
        "🗓️ Program hazırlanıyor: her ders için süre, öncelik, Feynman tekniği notu dahil 💪",
        "📝 Çalışma takvimi: sabah/akşam bloklar + kritik konular + mola düzeni. Az kaldı 🔬",
        "⏱️ Plan kişiselleştiriliyor, ders programıyla çakışmaları da kontrol ediyorum 🎓",
        "🧩 Plan yapboz gibi: zayıf konu + uygun saat + verimli yöntem birleştiriliyor 🎯",
        "🎵 Haftalık ritmi kurgulu — yoğun günler, dinlenme, tekrar bantları ⏰",
        "📐 Çalışma planı geometrisi: 7 gün × 6 ders × öncelik puanı. Az kaldı 🌟",
        # Reaction
        "🤔 Sağlam bir plan istiyorsan biraz sabır — şablon değil özel hazırlıyorum 💙",
        "✏️ Plan defterini açıyorum, _şu an hayalini kuruyorsun, ben yazıyorum_ ⏳",
    ],
    'kurum_ozet': [
        "📊 Kurum durumu derleniyor — öğrenci, öğretmen, risk sinyalleri 🏢",
        "🎯 Genel tablo çıkıyor: aktif öğrenci, katılım, kalite metrikleri...",
        "📈 Kurumun son hafta özeti hazırlanıyor, kritik rakamlar birazdan ⏳",
        "🔎 Panoramik bakış: öğrenci performansı + öğretmen yükü + uyarı sinyalleri bir arada",
    ],
    'foto_solve': [
        "📸 Soru ile ayna tutuyorum 🧠 — ders + konu + adım adım çözüm geliyor ⏰",
        "🔍 Fotoğraftaki soruyu inceliyorum. Doğru şık + gerekçe + ipucu birazdan 🎯",
        "📚 Vision motoru devrede — soru metni + şekil analizi + çözüm... _~10sn_ ⚡",
        "🧩 Adım adım çözüme giriyorum, bu tür soruların inceliğini de paylaşayım 🎓",
        "🤓 Soruyu çözerken _neden böyle_ kısmını da anlatmayı hedefliyorum, kaçırma! ✨",
    ],
    'self_diagnosis': [
        "🔬 Sistem tanısı başladı — son 24 saatlik hata izleri çıkıyor 📊",
        "🛠️ Diyalog kalitesi taraması: hangi kalıp sorun yaratmış, kök nedeni çıkıyor ⏳",
        "🎯 Pattern analizi çalışıyor, iyileştirme önerileri derleniyor...",
    ],
    'oneri_uret': [
        "💡 Öneri motoru çalışıyor — düzeltme fikirleri kuyruğa yazılıyor ⏳",
        "🔧 Gözlemlediğim sorunlardan düzeltme önerileri üretiyorum, biraz bekle 🎯",
    ],
    'profil_analiz': [
        "👤 *{name}* için profil derleniyor — sınavlar + konular + devamsızlık + etkileşim 📊",
        "🎓 Akademik portresi çıkıyor: güçler, gelişim alanları, trend...",
        "🔎 *{name}* üzerinde zoom — birazdan kapsamlı özet ⏳",
        "📈 Gelişim eğrisi çizilirken, tüm verileri bir arada topluyorum ✨",
    ],
    'muh_analiz': [
        "📊 Karşılaştırmalı analiz başladı, sıralamalar çıkıyor ⏳",
        "🔬 Veri taraması: filtre + skor + yorum birleşimi hazırlanıyor 🎯",
        "📉 Grafik verisi derleniyor, birazdan görsel özet ✨",
        "🏆 Sıralama tablosu yapılandırılıyor, kritik pozisyonlar netleşiyor ⚡",
    ],
    # GENEL DOLGU — kategorize edilmemis uzun durumlar
    # Oturum 18: cesitlilik genisletildi (8 -> 28 varyasyon)
    # Karisim: kisa reaction + samimi tepki + isimli + isimsiz + nadir konu metaforu
    '_generic': [
        # ── Kısa, samimi reaksiyonlar (isimsiz) ──
        "🔍 Anladım, biraz detay gerektiriyor bu. Verileri çekiyorum ⏳",
        "📊 İnceliyorum — birkaç kaynaktan veri topluyorum 🎯",
        "🔬 Sorunu adımladım, düşünüyorum... ✨",
        "💭 Birden fazla açıdan değerlendiriyorum, kaliteli yanıt için sabır 🌟",
        "🎲 Veriyle kontrol ediyorum, uydurmak istemiyorum — doğru cevap geliyor ⚡",
        "⏱️ Bir saniye, beynimi açıyorum 😅",
        "🧐 İlginç soru, dur düşüneyim doğru cevap için...",
        "🌀 Kafamı toparlıyorum, önemli soruyu acele etmeyim ⏰",
        "📖 Sağlam bir cevap için kütüphaneyi karıştırıyorum biraz ⏳",
        "🎯 İyi bir soru attın, hakkını vermeli — analiz devam ediyor 🔬",
        # ── Bekleme özürü, samimi (isimsiz) ──
        "🙏 Az daha sabır, hak ettiğin bir cevap geliyor ✨",
        "⌛ Bekletmek istemezdim ama doğruyu bulayım önce — sabır 💙",
        "🤔 Pardon, bir saniye dalmıştım — toplanıyorum 😅",
        "🫷 Dur bir saniye, böyle aceleye gelmez bu konu",
        # ── İsimli, samimi (kullanıcıyı hissettir) ──
        "⚙️ *{name}*, birkaç saniye dayan — kaliteli cevap hazırlıyorum 💪",
        "🧠 *{name}*, bu analiz için biraz konsantre oluyorum, az kaldı 🎓",
        "👋 *{name}*, seni bekletiyorum biliyorum — değecek 🌟",
        "💼 *{name}* için özel bakıyorum, jenerik cevap istemem 🔬",
        "🤝 Pardon *{name}*, bir saniye — emin olmak istiyorum ⏳",
        "✨ *{name}*, dur bekleme uzasın — net cevap geliyor ⚡",
        # ── Konuya/duruma bağlı ──
        "📚 Birden fazla kaynağı kıyaslıyorum, doğrusu bu olsun istiyorum ⏰",
        "🔧 Verileri çapraz kontrol ediyorum, _yanlış cevap verirsem ben üzülürüm_ 😄",
        "⚗️ Ham veriden yorumlu cevaba doğru distile ediyorum ⏳",
        "🎼 Verileri orkestraya çeviriyorum, az kaldı 🎵",
        # ── Kısa enerjik ──
        "🔥 Geliyor, geliyor — yakında ⚡",
        "💫 Bir tık daha sabır, kaliteli cevap çıkıyor 🎯",
        "⏰ Birkaç saniye, dolduruyorum kafayı ✨",
        "🎨 Cevabı resim gibi çiziyorum — sabret ⏳",
    ],

    # Selam + kısa soru için özel — "merhaba" sonrası tipik beklemeler
    '_kisa_sohbet': [
        "👋 Sağol, bakayım sana ne diyebilirim ⏳",
        "🙂 Hmm, dur düşüneyim doğru cevap için...",
        "⏱️ Bir saniyecik, hazırlıyorum 🎯",
        "✨ Az kaldı, yakında 💫",
        "🤔 Bakıyorum, geliyor 🌟",
    ],
}


# FILLER CHOICE STRATEGY (Oturum 18: 2 -> 5)
# Son 5 kullanilan reddedilir — kullanici 5 mesaj boyunca ayni filler gormez.
# Pattern algilanma riski minimum. Cesitlilik havuzu zenginlestirildi.
_FILLER_HISTORY: dict[str, list[int]] = {}
_HISTORY_SIZE = 5


# Eski API ile uyum
_LAST_FILLER_IDX: dict[str, dict[str, int]] = {}


def pick_filler(intent: str, phone: str = "default", subject: str = "") -> str:
    """Cesitlilik garantili filler sec — son 2 kullanilan hep reddedilir."""
    import random as _r
    fillers = _PRE_FILLERS.get(intent) or _PRE_FILLERS['_generic']
    if not fillers:
        return ""
    if len(fillers) == 1:
        return fillers[0]

    key = f"{phone}:{intent}"
    recent = _FILLER_HISTORY.get(key, [])
    candidates = [i for i in range(len(fillers)) if i not in recent]
    if not candidates:
        # Tum varyasyonlar kullanilmissa en eski kaydi sil, yine sec
        candidates = list(range(len(fillers)))
        # Sadece en son kullanilani reddet
        if recent:
            candidates = [i for i in candidates if i != recent[-1]]
    chosen_idx = _r.choice(candidates) if candidates else 0

    # History guncelle (FIFO)
    recent.append(chosen_idx)
    if len(recent) > _HISTORY_SIZE:
        recent = recent[-_HISTORY_SIZE:]
    _FILLER_HISTORY[key] = recent
    # Eski API ile uyum
    if phone not in _LAST_FILLER_IDX:
        _LAST_FILLER_IDX[phone] = {}
    _LAST_FILLER_IDX[phone][intent] = chosen_idx

    msg = fillers[chosen_idx]
    # Dinamik {subject} (dersi metne yerleştir)
    if '{subject}' in msg:
        subject = subject or _r.choice(['matematik', 'fizik', 'kimya', 'biyoloji', 'türkçe', 'tarih'])
        msg = msg.replace('{subject}', subject)
    return msg


# Eski pick_filler imzasiyla uyum icin (cesitlilik icin)
def _legacy_pick(intent: str, phone: str = "default") -> str:
    fillers = _PRE_FILLERS.get(intent) or _PRE_FILLERS['_generic']
    if not fillers:
        return ""
    if len(fillers) == 1:
        return fillers[0]
    # Son kullanilani tekrar etme
    last_idx = _LAST_FILLER_IDX.get(phone, {}).get(intent)
    candidates = list(range(len(fillers)))
    if last_idx is not None and last_idx in candidates:
        candidates.remove(last_idx)
    chosen_idx = random.choice(candidates)
    # Track
    if phone not in _LAST_FILLER_IDX:
        _LAST_FILLER_IDX[phone] = {}
    _LAST_FILLER_IDX[phone][intent] = chosen_idx
    return fillers[chosen_idx]


async def send_pre_filler(phone: str, intent: dict, name: str = "",
                          send_func=None, delay_before: float = 0.3) -> bool:
    """
    Pre-filler gonder — uzun analiz baslamadan once.
    delay_before: WhatsApp'tan ana mesajdan once filler'in gorunmesi icin
                  micro-sleep (typing illusion).
    """
    if not intent or not phone:
        return False
    intent_name = intent.get('intent') if isinstance(intent, dict) else intent
    if not intent_name:
        return False

    # Send func'i lazy import (circular import onleme)
    if send_func is None:
        from whatsapp_bridge import send_wa_message
        send_func = send_wa_message

    msg = pick_filler(intent_name, phone)
    if not msg:
        return False

    # Personalization
    msg = msg.format(name=(name.split()[0] if name else "arkadaşim"))

    # Mini delay (gercek typing hissi icin)
    if delay_before > 0:
        await asyncio.sleep(delay_before)

    try:
        await send_func(phone, msg)
        logger.debug(f"📨 Pre-filler gonderildi → {phone[-4:]}: {intent_name}")
        return True
    except Exception as e:
        logger.warning(f"Pre-filler gonderim hatasi: {e}")
        return False


# ─────────────────────────────────────────
# 3. POST-ANALIZ FOLLOW-UP (Teyit)
# ─────────────────────────────────────────
# Uzun bir cevap sonrasi "dogru anlamis miyim?" tarzi follow-up

_POST_FOLLOWUPS = {
    'plan': [
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _Bu plani onaylıyor musun, *{name}*? Eklemek/cikarmak istedigin ders veya konu var mi?_",
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _Plani sevdin mi? Belirli bir dersi *daha çok/az* tutmamı ister misin?_",
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _*{name}*, planda kaçırdığım bir önceliğin var mı? Belirtirsen yeniden hazirlarim._",
    ],
    'analiz': [
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _Bu analiz icin *baska bir aci* dan bakmamı ister misin? (Ornek: ders bazli, hedef bolum)_",
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _Analizde *eklenmesini istedigin* bir kriter var mi?_",
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _*{name}*, raporu net buldun mu? Daha *detayli* veya *ozet* ister misin?_",
    ],
    'rapor': [
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _Rapor elinize ulastı. Belirli bir bölümü *daha detayli* incelememi ister misin?_",
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _Raporda gozune carpan bir nokta var mı? Aksiyon önerileri için detay isterim._",
    ],
    'cozum': [
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _Cozumu anladin mi *{name}*? Belirli bir adimi *tekrar acikla* desem yardim ederim._",
        "\n\n━━━━━━━━━━━━━━━━━━━━━━━\n💬 _Bu konuda *benzer bir soru* daha cozelim mi pekisim icin?_",
    ],
}


def get_post_followup(kategori: str = 'analiz', name: str = "") -> str:
    """Bir sonraki mesajda ekler — kullanim cevap.append(get_post_followup(...))."""
    options = _POST_FOLLOWUPS.get(kategori, [])
    if not options:
        return ""
    msg = random.choice(options)
    return msg.format(name=(name.split()[0] if name else "arkadaşim"))


# ─────────────────────────────────────────
# 4. SOHBET OYALAMA (yan yana follow-up icin)
# ─────────────────────────────────────────
# Eger asil islem cok uzun (>20sn), 10sn sonra ikinci dolgu mesaji
_PROGRESS_MESSAGES = [
    "⏳ Hâlâ çalışıyorum — son birkaç saniye, kaliteli analiz için sabır 🙏",
    "🔍 Veri toplamayı bitirdim, şimdi yorumu derliyorum... birazdan elinde 📊",
    "⚙️ Son aşamadayım — birkaç saniye daha 💪",
    "🧠 Verileri karıştırıyorum, birazdan net tablo çıkar ✨",
    "📊 Ufak bir detay kaldı, ona bakıp hemen sunuyorum 🎯",
    "🎨 Raporu düzgün biçimlendiriyorum, birazdan göndereceğim 📝",
    "🔎 Birkaç sayı daha çapraz kontrol ediyorum — değeceğine eminim ⏰",
    "💭 Cevabı şekillendiriyorum, 10 saniye daha tahmin ediyorum ⌛",
    "📐 Son iki sorguyu bekliyorum, hazır olunca bildiririm 🙌",
    "🌟 Derin inceleme yapıyorum, Alelacele yanıt yerine doğru rapor tercih ettim 🎓",
]

# 22.1n-neo fikir1: 2. asama (30s sonra) — hala bitmediyse
_PROGRESS_MESSAGES_LONG = [
    "🎯 Bu biraz karmaşık bir analiz — kapsamlı rapor için 20-40 saniye daha. Sabırla hazırlıyorum 🙏",
    "📊 Çok katmanlı sorgu (sezon + ders + konu) — özenle derliyorum. Birkaç saniye daha ⏳",
    "🧠 7 farklı veri kaynağı + paralel hesap — bitmek üzere, değerli olacak ✨",
    "⚡ Büyük bir analiz yapıyorum — sistem tam kapasite çalışıyor. Elindeki 30 saniye değer 🎓",
    "🔬 Derin çapraz kontrol — her sayıyı doğruluyorum, hatasız rapor geliyor 📋",
]


async def send_progress_after_long(phone: str, delay_sn: float = 30.0,
                                     cancel_token: asyncio.Event = None,
                                     send_func=None):
    """22.1n-neo fikir1: 2. asama progress — 30s sonra hala bitmezse.

    Claude P95 54s icin 30s bekletmek UX bozar. Ikinci mesaj "hala calisiyor" der.
    """
    try:
        if send_func is None:
            from whatsapp_bridge import send_wa_message
            send_func = send_wa_message
        if cancel_token:
            try:
                await asyncio.wait_for(cancel_token.wait(), timeout=delay_sn)
                return
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(delay_sn)
        msg = random.choice(_PROGRESS_MESSAGES_LONG)
        await send_func(phone, msg)
    except Exception as e:
        logger.debug(f"Long progress hatasi: {e}")


async def send_progress_after(phone: str, delay_sn: float = 12.0,
                              cancel_token: asyncio.Event = None,
                              send_func=None):
    """
    delay_sn sonra hala bitmemisse progress mesaji at.
    cancel_token: ana cevap geldigi anda set() yapilir, progress iptal.
    """
    try:
        if send_func is None:
            from whatsapp_bridge import send_wa_message
            send_func = send_wa_message

        # Bekle (cancel olabilir)
        if cancel_token:
            try:
                await asyncio.wait_for(cancel_token.wait(), timeout=delay_sn)
                return  # iptal edildi
            except asyncio.TimeoutError:
                pass  # zaman doldu — progress mesajini at
        else:
            await asyncio.sleep(delay_sn)

        msg = random.choice(_PROGRESS_MESSAGES)
        await send_func(phone, msg)
    except Exception as e:
        logger.debug(f"Progress mesaj hatasi: {e}")


# ─────────────────────────────────────────
# 5. TEST / DRY RUN
# ─────────────────────────────────────────

async def test_filler_variation(intent: str = 'puan_tahmin', n: int = 5):
    """Cesitlilik testi — n kere filler sec, hepsi farkli mi?"""
    print(f"\n=== {intent} icin {n} varyasyon testi ===")
    fakephone = "test123"
    seen = []
    for i in range(n):
        msg = pick_filler(intent, fakephone)
        seen.append(msg[:80])
        print(f"\n[{i+1}] {msg[:200]}")
    unique_count = len(set(seen))
    print(f"\n→ {unique_count}/{n} essiz mesaj")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    # Tum intentleri test et
    print("=" * 60)
    print("CONVERSATION FLOW — TEST")
    print("=" * 60)

    # 1. Intent detection
    test_msgs = [
        "puan tahmin yap",
        "etut oner ecrin",
        "rapor pdf damla",
        "zorluk haritasi",
        "calisma plani yap",
        "merhaba",  # short — no intent
        "tamam",  # short — no intent
        "fizik nedir",  # not long
    ]
    print("\n--- Intent Detection ---")
    for m in test_msgs:
        intent = detect_long_intent(m)
        print(f"  '{m}' → {intent}")

    # 2. Filler variation
    asyncio.run(test_filler_variation('puan_tahmin', 5))
    asyncio.run(test_filler_variation('etut_oneri', 4))

    # 3. Post-followup
    print("\n--- Post-Followup ornekleri ---")
    for kat in ['plan', 'analiz', 'rapor', 'cozum']:
        msg = get_post_followup(kat, "Ecrin")
        print(f"\n[{kat}]{msg}")
