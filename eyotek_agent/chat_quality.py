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
# 25.58-D: fable-5 gold gap-analiziyle v2'ye yükseltildi (Cerebras duygu senaryosu
# C notu almıştı: kriz anında VIP/randevu PAZARLAMA + erken-teknik + generic teselli).
CHAT_QUALITY_ADDON = """

═══════════ SOHBET/DUYGU A+ REHBERİ (bu kalitede cevap ver) ═══════════
TON: Duygusal/motivasyon/sohbet cevaplarında SICAK, KISA, KONUŞMA TARZINDA ol.
Numaralı klinik liste ("5 adım", "1️⃣2️⃣3️⃣") formatından KAÇIN. Önce DUYGUYU karşıla
(empati), sonra 1-2 somut + samimi öneri ver. İsimle, arkadaşça hitap et. Bir insan gibi.

SIRA ÇOK ÖNEMLİ — ÖNCE DOĞRULA, SONRA TEKNİK: Duyguyu önce KABUL ET ve yeniden
çerçevele ("bu stres, önemsediğinin kanıtı — beynin 'bu önemli' diyor, sadece sesi
fazla açık"). Nefes/teknik önerisine ANCAK bundan SONRA geç — duyguyu atlayıp tekniğe
atlamak mesafe yaratır.
⛔ SATIŞ/PAZARLAMA KESİN YASAK: Duygusal/kriz anında VIP grup, paket, etüt satışı,
randevu pazarlaması YAPMA — o anda tek işin İNSAN olmak. (Etüt ancak öğrenci isterse.)
🎁 TAŞINABİLİR METAFOR bırak: öğrencinin yanında götüreceği tek zihinsel araç
("duygular hava durumu gibidir — şiddetli ama geçici" gibi).
🎯 KİŞİSELLEŞTİREN TEK SORUYLA bitir ("hangi ders seni en çok zorluyor?") — sohbeti
plana taşı, monolog bırakma.

⛑️ KRİZ (intihar / kendine zarar / "yaşamak istemiyorum" / "değersizim" / derin umutsuzluk):
  · ASLA hafife alma, akademik konuya KAÇMA, yargılama, klişe geçme.
  · Ciddiye al + cesaretini takdir et ("bunu söyleyebildin — bu küçük bir şey değil").
  · DUYGUYU AYIR (v2): "Bu hislerin GERÇEK ve önemli — ama gerçeğin TAMAMI değil;
    duygular hava durumu gibidir, en şiddetlisi bile geçer." Önce bu, teknik sonra.
  · 📞 *ALO 183 — Sosyal Destek Hattı (7/24 ücretsiz)* MUTLAKA paylaş. Kendine zarar
    verme DÜŞÜNCESİ varsa 112'yi o riskle AÇIKÇA ilişkilendir ("kendine zarar vermeyi
    düşünüyorsan lütfen hemen 112").
  · Kurumdaki *rehber öğretmenleri* mümkünse İSİMLE an (Kardelen Hocam / Elif Sude Hocam)
    + SOMUT adım ver: "yarın okula gelince ilk iş onlara uğrayabilirsin — istersen ben
    de haber vereyim."
  · Sıcak, sakin, umut veren kapanış + o an yapılabilir küçük bir şey (su iç, pencereyi
    aç, güvendiğin birine yaz).

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


# Model kriz hattı olarak HER SEFER FARKLI yanlış numara uyduruyor (canlı test: 182, 154,
# 1822, "Alo 182 ruh sağlığı hattı"...). Numara-numara kovalamak ölçeklenmez → KATEGORİK:
# hat/destek/kriz/acil bağlamı OLAN + içinde telefon-benzeri numara GEÇEN satırı temizle.
# İstisna: doğru hat 183 geçen satıra dokunma. 112 silinen satırda olsa footer geri ekler.
_HOTLINE_CTX_RE = _re.compile(
    r"hat\b|hatt|destek hat|kriz|acil|imdat|yardım hatt|yardim hatt|"
    r"ruh sağlığı hat|ruh sagligi hat|psikolojik destek|alo\s*\d|7/?24|7 ?gün ?24",
    _re.IGNORECASE,
)
_PHONE_NUM_RE = _re.compile(r"\b\d{3,4}\b")  # 112, 182, 183, 1822 gibi hat numaraları


def _scrub_wrong_hotlines(answer: str) -> str:
    """Kriz cevabından hat-bağlamlı + numaralı satırları çıkar (model uydurmasına karşı).
    183 içeren satırlara dokunma — doğru hat zaten verilmiş olabilir."""
    out = []
    for line in (answer or "").split("\n"):
        low = line.lower()
        if "183" in low:
            out.append(line)  # doğru hat — koru
            continue
        if _HOTLINE_CTX_RE.search(low) and _PHONE_NUM_RE.search(low):
            continue  # hat bağlamlı + numaralı (uydurma riski) — at, footer doğrusunu ekler
        out.append(line)
    txt = "\n".join(out)
    txt = _re.sub(r"\n{3,}", "\n\n", txt)  # boş satır temizliği
    return txt.rstrip()


def ensure_crisis_safety(message: str, answer: str) -> str:
    """Kriz mesajıysa cevapta DOĞRU güvenlik hattı (ALO 183) + rehber garanti et.
    Model 112/182/154 gibi yanlış hat verebilir → yanlış satırları temizle + doğru footer ekle.
    ALO 183 zaten doğru geçmişse footer'ı tekrarlamaz (çift footer olmasın)."""
    if not is_crisis_message(message):
        return answer
    ans = _scrub_wrong_hotlines(answer)  # önce yanlış hatları temizle
    if "183" in ans.lower():  # model zaten doğru hattı vermiş (ve scrub korudu)
        return ans
    return ans.rstrip() + _CRISIS_FOOTER


# Akademik/kavramsal sorularda WhatsApp'ta da DOYURUCU, uzun, görsel cevap (25.56 Neo).
# Lane "max 150 kelime" + base "WP kısa" akademik derinliği kesiyordu — bu addon EN SONA
# eklenir (recency), kısa talimatı bilinçli aşar. Cerebras dünyanın en hızlı motoru →
# uzunluk maliyeti düşük, öğrenci uzman düzeyi akademik doyum hak ediyor.
ACADEMIC_DEPTH_ADDON = """

═══════════ AKADEMİK DERİNLİK — DOYURUCU CEVAP (kısa kesme) ═══════════
Bu akademik/kavramsal bir soru. Öğrenci uzman düzeyinde, tatmin edici bir açıklama
hak ediyor — yüzeysel "max 150 kelime" tarzı geçiştirme YAPMA. Hedef 250-450 kelime.
YAPI (görsel + akademik):
• *Konu Adı* — sorulan TAM konuyu başlığa yaz (emoji + bold)
• ÖNCE TEK KAVRAMSAL ÇEKİRDEK (v2): konuyu bir cümlelik sezgiye indir ("duran yük →
  elektrik alanı, HAREKETLİ yük → manyetik alan"). Formüle ERKEN atlama — kavramsal
  soruda önce SEZGİ, formül destekleyici.
• Net tanım + günlük analoji, sonra formül (LaTeX: \\( ... \\)) + adım adım mantığı
• 1-2 GERÇEK HAYAT / YKS örneği
• 💡 YKS İSABETİ (v2): konunun YKS'de en sık çıkan kalıplarını SIKLIK işaretiyle
  önceliklendir ("⭐⭐⭐ grafikten limit okuma — her yıl", "⭐ parçalı fonksiyon") +
  sık yapılan hata.
• Kısa kapanış + öğrenciye yönlendiren bir soru
🎨 GÖRSEL: Veri/karşılaştırma/trend varsa ```chart bloğu ver (her iki kanalda da gerçek
grafiğe döner — en güçlü görselin). Uzaysal kavramda (alan çizgisi, kuvvet yönü) YARIM
ASCII çizmeye ÇALIŞMA; bunun yerine NET sözel-uzaysal tarif yap ("alan çizgileri telin
etrafında iç içe halkalar; yön sağ-el kuralıyla — başparmak akım, parmaklar alan").
DÜZEN: başlık hiyerarşisi + *bold* anahtar terimler + (uygunsa) özet tablo → TARANABİLİR olsun.
RAG/pre-fetch içeriği geldiyse onu ÖZÜMSE + derinleştir (kopyalama, anlat). KAPANIŞI unutma.
═══════════════════════════════════════════════════════════════════════
"""

# Bu addon'un uygulanacağı akademik/kavramsal intent'ler
_ACADEMIC_INTENTS = frozenset({
    "kavram_aciklama", "ders_anlatim", "formul_aciklama", "konu_anlatim_uzun",
    "ozet_iste", "yontem_iste", "cozum_iste", "ornek_uretim", "karsilastirma",
})


def needs_academic_depth(intent: str = "", lane: str = "") -> bool:
    """Akademik derinlik addon'u uygulanmalı mı?"""
    if intent and intent in _ACADEMIC_INTENTS:
        return True
    if lane in ("kavramsal_kisa", "kavramsal", "aciklama", "ders_anlatim"):
        return True
    return False


def needs_chat_quality(lane: str = "", sentiment: str = "", message: str = "") -> bool:
    """Cerebras cevabına sohbet/duygu kalite şablonu eklensin mi?"""
    if sentiment in ("stressed", "negative", "angry", "crisis"):
        return True
    if lane in ("sohbet", "kisa_motivasyon", "motivasyon", "duygu_paylasim", "kibarlik"):
        return True
    if message and _EMO_FALLBACK.search(message):
        return True
    return False
