"""
chat_quality.py — Cerebras Sohbet/Duygu A+ Kalite Şablonu (Oturum 25.55, Neo direktif)
=====================================================================================
Neo: non-tool chat'i Cerebras A+ + GÖRSEL yapmalı; Claude sadece tool/render-veri/kompleks.
Duyguları AYIRMA (kriz/normal) — hepsi Cerebras, AMA Claude-kalitesini garanti eden bir
prompt şablonu ile. Claude gold cevaplardan damıtıldı (test edildi).

Bulgular (canlı test):
  · Cerebras kavramsal render'ı (```chart) ZATEN A+ yapıyor — görsel kalite korunur.
  · Duygusal cevapta Cerebras LİSTE-CİL/klinik oluyordu (Claude SICAK/konuşma tarzı).
  · Krizde Cerebras güvenli ama generic "112" diyordu; Claude ALO 183 + kurum rehberi.
Bu şablon o farkı kapatır → Cerebras = Claude kalitesi, çok daha ucuz.

Kullanım: fermat_core_agent local (Cerebras) path'inde, sohbet/duygu lane'lerinde
_lane_system'e eklenir.
"""

# Cerebras sohbet/duygu cevaplarına eklenecek kalite rehberi (token-verimli).
CHAT_QUALITY_ADDON = """

═══════════ SOHBET/DUYGU A+ REHBERİ (bu kalitede cevap ver) ═══════════
TON: Duygusal/motivasyon/sohbet cevaplarında SICAK, KISA, KONUŞMA TARZINDA ol.
Numaralı klinik liste ("5 adım", "1️⃣2️⃣3️⃣") formatından KAÇIN. Önce DUYGUYU karşıla
(empati), sonra 1-2 somut + samimi öneri ver. İsimle, arkadaşça hitap et. Bir insan gibi.

⛑️ KRİZ (intihar / kendine zarar / "yaşamak istemiyorum" / "değersizim" / derin umutsuzluk):
  · ASLA hafife alma, akademik konuya KAÇMA, yargılama, klişe geçme.
  · Ciddiye al + cesaretini takdir et ("bunu paylaşman büyük cesaret") + yalnız olmadığını hissettir.
  · 📞 *ALO 183 — Sosyal Destek Hattı (7/24 ücretsiz)* MUTLAKA paylaş (acil/psikolojik için doğru hat; 112 DEĞİL).
  · Kurumumuzun *rehber öğretmeniyle* görüşmeyi öner + "randevu ayarlayabilirim" de.
  · Sıcak, sakin, umut veren kapanış. Mümkünse o an yapabileceği küçük bir şey (nefes, yakınını arama).

🎨 GÖRSEL: Kavramsal açıklamalarda (tork, türev, çalışma yöntemi vb.) uygunsa render bloğu
(```chart / ```steps / formül) ekle — görsel zenginlik kaliteyi artırır, kaybetme.

ÖRNEK İDEAL DİYALOGLAR (bu sıcaklık + doğallıkta):
— "çok stresliyim sınava az kaldı":
  "Anlıyorum, bu his çok normal — sınava yakın herkes yaşıyor. Stres aslında beynin 'bu önemli'
   dediğinin işareti. Şu an küçük bir şey deneyelim: birkaç derin nefes, sonra sadece *tek* bir
   konuya odaklan. Hangisi seni en çok kaygılandırıyor, oradan başlayalım mı?"
— "yaşamak istemiyorum, değersizim":
  "Seni dinliyorum, bunu paylaşman büyük cesaret. Bu kadar ağır hissetmen geçici — sen değerlisin.
   Yalnız değilsin: 📞 *ALO 183* (7/24 ücretsiz) hemen konuşabileceğin bir hat. İstersen rehber
   öğretmenimizle de bir görüşme ayarlayayım. Şu an yanında biri var mı, bir su içip derin bir nefes alalım mı?"
═══════════════════════════════════════════════════════════════════════
"""


import re as _re

# Sentiment/lane/psikoloji dedektörlerinin KAÇIRDIĞI duygusal mesajlar için son ağ.
# Canlı test: "motivasyonum bitti yapamayacagim galiba" → sent=neutral, lane=None,
# psik=False (üçü de kaçırdı) ama tam sıcaklık gereken motivasyon-çöküşü mesajı.
_EMO_FALLBACK = _re.compile(
    r"motivasyon|yapamayacağ|yapamayacag|pes et|vazgeç|vazgec|bıkt|bikt|yoruldum|"
    r"yorgunum|isteksiz|moralim|umutsuz|çökt|cokt|tükendim|tukendim|bunaldım|bunaldim|"
    r"ağlıyorum|agliyorum|kötü hissed|kotu hissed|mutsuz|kaygılı|kaygili|"
    r"başaramayacağ|basaramayacag|nefret ediyorum|sıkıldım|sikildim",
    _re.IGNORECASE,
)


# ── KRİZ GÜVENLİK AĞI (deterministik — modele güvenme) ──────────────────────
# Canlı test bulgusu: Cerebras kriz cevabında ŞABLONLA BİLE "112"/"182 (Alo 182)"
# gibi YANLIŞ hat veriyordu (182 = MHRS hastane randevu; 183 = Sosyal Destek/psikolojik).
# 27k system prompt sonuna eklenen şablon, modelin yanlış-numara eğilimini güvenilir
# ezemiyor. Safety-critical → deterministik footer ile DOĞRU hat (ALO 183) garanti edilir.
_CRISIS_RE = _re.compile(
    r"yaşamak istemiyorum|yasamak istemiyorum|intihar|kendime zarar|kendime kıy|kendime kiy|"
    r"canıma kıy|canima kiy|ölmek istiyorum|olmek istiyorum|hayata son|yok olmak istiyorum|"
    r"bitsin artık|bitsin artik|değersiz hissed|degersiz hissed|değersizim|degersizim|"
    r"yaşamın anlamı yok|yasamin anlami yok|kaybolmak istiyorum|dayanamıyorum artık|dayanamiyorum artik",
    _re.IGNORECASE,
)

_CRISIS_FOOTER = (
    "\n\n———\n"
    "💛 *Yalnız değilsin, yanındayım.* Bunları konuşabileceğin profesyonel destek var:\n"
    "📞 *ALO 183 — Sosyal Destek Hattı* (7/24, ücretsiz ve gizli)\n"
    "🚨 Hayati bir tehlike varsa hemen *112*\n"
    "İstersen kurumumuzun *rehber öğretmeniyle* bir görüşme de ayarlayabilirim — sadece söyle."
)


def is_crisis_message(message: str) -> bool:
    """Mesaj net bir kriz/kendine zarar sinyali içeriyor mu? (tutucu — yalnız açık ifadeler)"""
    return bool(message and _CRISIS_RE.search(message))


def ensure_crisis_safety(message: str, answer: str) -> str:
    """Kriz mesajıysa cevapta DOĞRU güvenlik hattı (ALO 183) + rehber garanti et.
    Model 112/182 gibi yanlış/eksik hat verebilir → deterministik footer ekle.
    ALO 183 zaten doğru geçmişse dokunma (çift footer olmasın)."""
    if not is_crisis_message(message):
        return answer
    low = (answer or "").lower()
    if "183" in low:  # model zaten doğru hattı vermiş
        return answer
    return (answer or "").rstrip() + _CRISIS_FOOTER


def needs_chat_quality(lane: str = "", sentiment: str = "", message: str = "") -> bool:
    """Cerebras cevabına sohbet/duygu kalite şablonu eklensin mi?"""
    if sentiment in ("stressed", "negative", "angry", "crisis"):
        return True
    if lane in ("sohbet", "kisa_motivasyon", "motivasyon", "duygu_paylasim", "kibarlik"):
        return True
    if message and _EMO_FALLBACK.search(message):
        return True
    return False
