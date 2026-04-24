"""
FermatAI — Fast Response Zenginleşmesi (22.1n-neo FAZ 1.1)
============================================================

Saat/gün/durum-aware Fast Response varyantları:
  - Selamlama: saat + gün kombinasyonları
  - Motivasyon: durum-bazlı (deneme öncesi/sonrası, günlük)
  - Sohbet kapatma: 25+ varyasyon
  - Akademik tebrik: ders bazlı özel
  - Veda: sınıf-bazlı (12 SAY → İTÜ, Mezun → tercih)

KULLANIM:
  from fast_response_enrich import smart_selam, smart_veda, akademik_tebrik
  msg = smart_selam(role="ogrenci", name="Ali", class_name="11 SAY")
  # Saat + gün kontrolu otomatik
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════
# SAAT BAZLI SELAMLAMA
# ═══════════════════════════════════════════════════════════════════════════

_SAAT_BAZLI_SELAM = {
    "gece": [  # 00:00-06:00
        "*{name}*, bu saatte de burada mısın? 🌙 Uyku önemli — beyin dinlenirken öğreniyor. 7-8 saat uyku, çalıştığın 10 saatten değerli.",
        "*{name}*, gece yarısı geçti. Bir şey için mi uyuyamadın? Dinlensen daha iyi — yarın da varız.",
        "*{name}*, gece vardiyası? 🌙 Sabah tekrar bakarsın, vücudunu zorlamayalım.",
    ],
    "sabah_erken": [  # 06:00-09:00
        "Günaydın *{name}*! ☀️ Yeni bir gün, taze beyin. Bugün ne üzerinde çalışıyorsun?",
        "*{name}*, günaydın! Sabahın erken saatleri çalışmak için ideal — kortizol seviyesi yüksek, odak güçlü.",
        "Sabah sabah burada mısın *{name}*? ☀️ Güzel — erken kuş solucanı yakalar.",
        "Günaydın! Kahvenin yanına bir hedef koy bugün. *{name}* ne hedefliyorsun?",
    ],
    "sabah": [  # 09:00-12:00
        "Merhaba *{name}*! 🌞 Sabah enerjisi tepede, ne çözelim?",
        "*{name}*, nasılsın? Sabah moduna girdin mi tamam?",
        "Merhaba! Güzel saat — odak için ideal zaman.",
    ],
    "oglen": [  # 12:00-15:00
        "Merhaba *{name}*, öğleden sonra nasıl gidiyor?",
        "*{name}*, bugün nasıl? Sabah ne yaptın, akşam ne planlıyorsun?",
        "Öğlen molası mı? 🍎 Yemek sonrası beyin biraz yavaş — hafif konular iyi gider.",
    ],
    "ikindi": [  # 15:00-18:00
        "*{name}*, ikindi vakti! Öğleden sonra verimi? Bu saatler klasik çalışma vakti.",
        "Merhaba *{name}*, enerjin nasıl? Akşam öncesi son odak dilimi.",
        "*{name}*, ikindi çay molası mı? ☕ Sohbet edelim veya çalışalım?",
    ],
    "aksam": [  # 18:00-21:00
        "İyi akşamlar *{name}*! 🌆 Günün son çalışma dilimi — ya tekrar ya yeni bir konu?",
        "Merhaba *{name}*, akşam oldu. Gün nasıl geçti?",
        "*{name}*, akşamın güzel saatleri. Bugünün kazanımı ne oldu?",
    ],
    "gece_erken": [  # 21:00-00:00
        "İyi akşamlar *{name}* 🌙. Bu saatlerde beyin toparlanma modunda — ağır konu değil, tekrar daha iyi.",
        "*{name}*, son saatler. Uyumadan önce 15dk tekrar + uyku = hafızaya kazıma (spaced repetition).",
        "*{name}*, gece yaklaşıyor. Yarına güç lazım — sen dinlenmeyi de çalışma planı say.",
    ],
}


_GUN_BAZLI_EKSTRA = {
    0: ["Pazartesi — yeni hafta, taze başlangıç.", "Haftanın ilk günü — tempo kurma zamanı.",
        "Pazartesi enerji günü! 💪"],
    1: ["Salı — hafta rayında ilerliyor.", "Salı — dün baladın, bugün hızlan."],
    2: ["Çarşamba — haftanın orta noktası.", "Çarşamba, yarı yol."],
    3: ["Perşembe — dönüş yolundayız.", "Perşembe, hafta sonu yaklaşıyor."],
    4: ["Cuma — hafta sonu öncesi son çalışma günü.",
        "Cuma — Türkiye geneli deneme günü! 📊",
        "Cuma, hafta kapatma."],
    5: ["Cumartesi — hafta sonu tempo kendin belirliyorsun.",
        "Cumartesi — dinlenme + tekrar ikilisi.",
        "Cumartesi! Kendi ritmini kur."],
    6: ["Pazar — yarına hazırlık + biraz nefes.",
        "Pazar — hafta değerlendirmesi + planı.",
        "Pazar akşamı: geçmişi geri sar, gelecek haftayı çiz."],
}


def _get_saat_dilimi(hour: int) -> str:
    if hour < 6:   return "gece"
    if hour < 9:   return "sabah_erken"
    if hour < 12:  return "sabah"
    if hour < 15:  return "oglen"
    if hour < 18:  return "ikindi"
    if hour < 21:  return "aksam"
    return "gece_erken"


def smart_selam(name: str = "", gun_ekle: bool = True) -> str:
    """Saat + (optional) gun bazli selamlama."""
    now = datetime.now()
    dilim = _get_saat_dilimi(now.hour)
    first_name = name.split()[0] if name else "arkadaşım"
    selam = random.choice(_SAAT_BAZLI_SELAM[dilim]).format(name=first_name)
    if gun_ekle and random.random() < 0.4:
        gun_mesaji = random.choice(_GUN_BAZLI_EKSTRA[now.weekday()])
        selam += "\n\n_" + gun_mesaji + "_"
    return selam


# ═══════════════════════════════════════════════════════════════════════════
# MOTİVASYON — 30+ VARYASYON
# ═══════════════════════════════════════════════════════════════════════════

_MOTIVASYON_GENEL = [
    "*{name}*, her çözülen soru bir nöral bağlantı. Bugünkü 50 soru = yarının 50 yeni yolu. 🧠",
    "*{name}*, sen burada olduğun için zaten yarının %10'u garanti. Devam.",
    "*{name}*, Aziz Sancar'ın öğretmeni muhtemelen 'sen Harran'da Nobel alırsın' dememişti. Başlangıç şart değil — yürüyüş önemli.",
    "*{name}*, Kobe Bryant her gün 4:04 AM antrenman. Sen şimdi 5 saat öndesin rakiplerinden.",
    "*{name}*, Edison 10,000 deneme yaptı. Her yanlış bir 'buradan olmuyor' bilgisi. Yanlış = keşif.",
    "*{name}*, 'henüz yapamıyorum' — en güçlü cümle. Beyin şu an yeni yol açıyor.",
    "*{name}*, zorluğun sebebi beceriksizliğin değil — yetersizin değil — sadece *henüz* üzerinden atlatmadın. Zaman meselesi.",
    "*{name}*, Feynman 'anlayamıyorsam anlatırım' derdi. Anlatmayı dene — anlarsın.",
    "*{name}*, uzun yol koşucusu hızlı değil, sabırlı. Sen sabırdasın.",
    "*{name}*, Cahit Arf: 'Matematik bilmediğin tarafa yürümek'. Şu anda yürüyorsun.",
    "*{name}*, Malala 17'sinde Nobel. Sen 17'sinde ne başlatıyorsun?",
    "*{name}*, Van Gogh hayatında 2 tablo sattı. Senin 'standart' olmaman geleceğin.",
    "*{name}*, bir adım az atan bile 1000 gün sonra 1000 adım önde. Sen her gün adım atıyorsun.",
    "*{name}*, sınır yok — sadece henüz aşılmamış zorluk var.",
    "*{name}*, motivasyon duygu, disiplin davranış. Duygu gelmiyorsa davranış devam.",
    "*{name}*, bugünkü çaban yarının 'şanslıydın' dediği şey olacak.",
    "*{name}*, İbn-i Sina 18'de tıp hocası. Sen 17'sinde ne inşa ediyorsun?",
    "*{name}*, Fermat bir matematikçiydi. Sen Fermat'ın öğrencisisin. Onun mirasını taşıyorsun.",
    "*{name}*, başarı fotoğraf değil film. Tek karelere değil, akışa bak.",
    "*{name}*, Einstein 'matematikte kötüydü' yalan. Sen de 'ben bu derste iyi değilim' yalanından çık.",
    "*{name}*, 'yavaş gidiyorum' diyorsan doğru yoldasın. Hızlı gidenler yanılır çoğunluğunda.",
    "*{name}*, Pomodoro: 25 dk odak + 5 mola. Basit ama %40 verim artışı. Bugün dene.",
    "*{name}*, bir saat doğru çalışma > üç saat dalgın çalışma. Kalite seç.",
    "*{name}*, Oktay Sinanoğlu 25'inde Yale prof. Sen 17'sinde temeli atıyorsun.",
    "*{name}*, yanlış yaptığın anda öğreniyorsun — doğru yaptığında sadece eski bilgiyi tekrarlıyorsun.",
    "*{name}*, biraz yorgun musun? Normal. Yorgunluk çalıştığının kanıtı — vazgeçmen değil.",
    "*{name}*, Sokrates: 'bilmediğini bilmek bilgeliktir'. Sen bilmediklerin için geldin buraya — zaten bilge yoldasın.",
    "*{name}*, Sabiha Gökçen '1937 ilk kadın pilot'. Sen 2026 'YKS başarısı'. Sen sıradaki.",
    "*{name}*, Mustafa Kemal'in 'Kemal' ismi matematik hocasından. Senin de matematik hocandan miras — Fermat.",
    "*{name}*, her deneme bir film karesi. Yıl sonunda film izlenir, tek kare değil.",
    "*{name}*, Michael Jordan lise takımından atılmıştı. Kaç şampiyonluk? 6. Reddedilmek son değil.",
    "*{name}*, Marie Curie iki Nobel — kış laboratuarında isin olmayan biriydi. Mevzu şart değil, merak.",
]


# ═══════════════════════════════════════════════════════════════════════════
# SOHBET KAPATMA — 25+ VARYASYON
# ═══════════════════════════════════════════════════════════════════════════

_SOHBET_KAPATMA = [
    "İyi çalışmalar *{name}*! Takıldığın yerde dön yine. 💪",
    "*{name}*, kendini yorma. Dengeli git. 🎯",
    "İyi akşamlar! Uyku da çalışma — beyin dinlenirken kazıyor. 🌙",
    "*{name}*, Pomodoro kırıksa 5dk mola ver, devam et. ⏰",
    "Görüşürüz *{name}*! Her gün seninle olmak güzel.",
    "*{name}*, Su iç, esnet — bedenin aracın. 💧",
    "Bir dahaki sohbette hangi konu olsun? Bekliyorum. 📚",
    "İyi günler *{name}* — Aziz Sancar bugün de seninle. 🏆",
    "*{name}*, biraz da kitap oku — beyin farklı kanalda dinleniyor. 📖",
    "Akşam check-in'i bekliyorum. 3 soru: iyi ne gitti? 🌟",
    "Kendine iyi bak *{name}*. Ritim kur, rituel yap.",
    "*{name}*, küçük ama sürekli — Kaizen prensibi. Yarın görüşürüz.",
    "İyi dersler! Cahit Arf: 'bilmediğin tarafa yürümek güzeldir.' 🧭",
    "*{name}*, sen bugün de küçük bir adım attın. 1000 gün sonra dağın başındasın.",
    "Uyku önemli *{name}* — 7-8 saat. Devamı gelsin.",
    "*{name}*, bir dahaki sohbette 'nasıl ilerleme gösterdin' sorusu hazır. 🎓",
    "Yarın burayız! Soru biriktir — birlikte çözeriz.",
    "*{name}*, hızlanacaksın — vakit meselesi. Sabırla. ⏱️",
    "İyi akşamlar — 'henüz' cümlesi unutma. Her şey *henüz* aşamasında.",
    "*{name}*, bir Pomodoro daha dene — 25 dakika, belki o soru çözülür.",
    "Görüşürüz arkadaşım. Edison 10k deneme, sen 10 ders — oranla daha azsın. Devam.",
    "*{name}*, mesele kazanmak değil — devam etmek. Sen devam ediyorsun.",
    "İyi çalışmalar! Yarın bir soruyla gel — öğrenelim.",
    "*{name}*, tıkandığında yaz — birlikte açarız.",
    "İyi akşamlar *{name}*. Yarın bir ders, bir konu, bir hedef. 🎯",
    "*{name}*, her seans sende bir şey bırakıyor — fark ediyor musun?",
]


# ═══════════════════════════════════════════════════════════════════════════
# AKADEMİK TEBRİK — DERS BAZLI
# ═══════════════════════════════════════════════════════════════════════════

_AKADEMIK_TEBRIK = {
    "matematik": [
        "*{name}*, *{net}* net matematik! 🔢 Cahit Arf'ın 'bilmediğin tarafa yürümek' dediği yer burası. Devam.",
        "Matematik *{net}* net — Harezmi'nin geleneğinde ilerliyorsun. Algoritma senin kanında.",
        "*{net}* net! Matematik zihni zorlamak — felsefi bir eylem. Sokrates onaylardı.",
    ],
    "fizik": [
        "*{net}* net fizik! ⚡ Ali Kuşçu 500 yıl önce Ayasofya'dan kozmosu ölçtü — sen onun mirasındasın.",
        "Fizik *{net}*! Newton 'dev omuzlarında durduğum için' der — sen şimdi onun omuzlarında.",
    ],
    "kimya": [
        "*{net}* net kimya! 🧪 Oktay Sinanoğlu kuantum kimyasında çığır açtı — 25'inde Yale prof. Sen temelde iyisin.",
        "Kimya *{net}* net — Marie Curie gibi biraz laboratuvar hayatı düşün. ⚗️",
    ],
    "biyoloji": [
        "*{net}* net biyoloji! 🧬 Aziz Sancar DNA tamiriyle Nobel aldı. Sen onun dil kökünden.",
        "Biyoloji *{net}*! Hayatın kodunu çözüyorsun. İbn-i Sina da tıp kitabını bu yaşında yazmıştı.",
    ],
    "edebiyat": [
        "*{net}* net edebiyat! 📖 Sabahattin Ali lisede 'Kuyucaklı Yusuf' için notlar alıyordu. Sen de öyle birikiyorsun.",
        "Edebiyat *{net}* — kelimeler insanın en güçlü aleti. Kullanıyorsun iyi.",
    ],
    "tarih": [
        "*{net}* net tarih! 📜 Mustafa Kemal tarihi severdi — 'Tarih bilmeyen millet yaşayamaz' demişti.",
        "Tarih *{net}*! Geçmişi bilen geleceği kurar — sen ikisinin ortasındasın.",
    ],
    "turkce": [
        "*{net}* net Türkçe! 🇹🇷 Dilinin hâkimi olmak aklının hâkimi olmaktır — sen hâkimsin.",
        "Türkçe *{net}*! Yunus Emre, Mehmet Âkif, Orhan Veli — hepsi sana miras.",
    ],
    "cografya": [
        "*{net}* net coğrafya! 🌍 Evliya Çelebi gibi — bilgi seyahati.",
        "Coğrafya *{net}*! Dünya haritasını kafanda tutuyorsun — bu ayrıcalık.",
    ],
    "felsefe": [
        "*{net}* net felsefe! 🎭 Sokrates'in 'bilmediğini bilmek' ilkesinin öğrencisisin.",
    ],
    "genel": [
        "*{name}*, *{net}* toplam net! Bir hafta öncesine göre *+{artis}*. Git böyle.",
        "*{net}* net — güzel iş *{name}*. Yolundasın. 🎯",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# SINIF BAZLI VEDA
# ═══════════════════════════════════════════════════════════════════════════

_SINIF_BAZLI_VEDA = {
    "12 SAY": [
        "İyi çalışmalar *{name}*! İTÜ senin kapında — 62 gün. 🎓",
        "*{name}*, 12 SAY — son düzlük. Her soru bir adım yakınlaştırıyor. 💪",
        "*{name}*, Boğaziçi, ODTÜ, İTÜ — hepsi bekliyor. Bugün bir soru daha. 🌉",
    ],
    "12 EA": [
        "İyi çalışmalar *{name}*! Hukuk fakültesi senin hayalinse — bugün onu kuruyorsun.",
        "*{name}*, 12 EA — hukuk/iktisat/psikoloji bekliyor. Kararlılığın tercihini çizer.",
    ],
    "12 SÖZ": [
        "İyi çalışmalar *{name}*! Edebiyat, hukuk, tarih — kelimelerle dünya kuranlardansın.",
        "*{name}*, 12 SÖZ — tarih, coğrafya, dil. Sen toplumun belleğisin.",
    ],
    "11 SAY": [
        "*{name}*, 11 SAY — gelecek yıl büyük sınav. Bu yıl temel. İyi çalışmalar! 🧱",
        "*{name}*, bu yıl sağlam temel, gelecek yıl zafer. Adım adım.",
    ],
    "11 EA": [
        "*{name}*, 11 EA — bir yıl sonra aranıza bir YKS girecek. Şimdi hazırlık.",
    ],
    "11 SÖZ": [
        "*{name}*, 11 SÖZ — kelimeler senin dünyan. Bu yıl kelime dağarcığı büyüdükçe, deneme netin de büyüyecek.",
    ],
    "10.Snf": [
        "*{name}*, 10. sınıf — 2 yıl var. Uzun maratonda başlangıç. Acele yok, ritim önemli. 🏃",
        "*{name}*, 10. sınıfta temel atıyorsun. Sonraki 2 yıl kazanımın üstüne ekleyecek.",
    ],
    "9.Snf": [
        "*{name}*, 9. sınıf — lise başı. Şu an her ne yaparsan yıllarca taşıyacaksın. İyi çalışmalar!",
    ],
    "Mezun": [
        "*{name}*, mezun! 🎓 Tercih mesaisi yaklaşıyor. Sorular?",
        "*{name}*, YKS geçmişte — şimdi tercih stratejisi. Akademik yönü konuşalım. 🗺️",
        "*{name}*, üniversite hayali gerçeğe dönüşüyor. Hangi bölümü planlıyorsun?",
    ],
    "default": [
        "İyi çalışmalar *{name}*! Bir dahaki sohbette buluşuruz. 💪",
        "*{name}*, yolun açık olsun.",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

def smart_motivasyon(name: str = "") -> str:
    first = name.split()[0] if name else "arkadaşım"
    return random.choice(_MOTIVASYON_GENEL).format(name=first)


def smart_sohbet_kapatma(name: str = "") -> str:
    first = name.split()[0] if name else "arkadaşım"
    return random.choice(_SOHBET_KAPATMA).format(name=first)


def akademik_tebrik(ders: str, net: float, name: str = "", artis: float = None) -> str:
    """Ders spesifik tebrik."""
    first = name.split()[0] if name else "sen"
    ders_key = (ders or "").lower().replace(" ", "")
    pool = _AKADEMIK_TEBRIK.get(ders_key) or _AKADEMIK_TEBRIK["genel"]
    msg = random.choice(pool)
    try:
        return msg.format(name=first, net=net, artis=round(artis, 1) if artis else "?")
    except KeyError:
        return msg.replace("{name}", first).replace("{net}", str(net))


def sinif_veda(class_name: str, name: str = "") -> str:
    """Sinif bazli veda."""
    first = name.split()[0] if name else "arkadaşım"
    cn = (class_name or "").strip()
    # Sinif key eşleştir (11 SAY, 12 EA vb.)
    for key, pool in _SINIF_BAZLI_VEDA.items():
        if key in cn or key.lower() in cn.lower():
            return random.choice(pool).format(name=first)
    # Mezun tespiti
    if "mezun" in cn.lower():
        return random.choice(_SINIF_BAZLI_VEDA["Mezun"]).format(name=first)
    return random.choice(_SINIF_BAZLI_VEDA["default"]).format(name=first)


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=== SAAT BAZLI SELAM ===")
    for _ in range(3):
        print(" " + smart_selam(name="İrem"))
        print()

    print("\n=== MOTIVASYON (5 ornek) ===")
    for _ in range(5):
        print(" " + smart_motivasyon(name="Mehmet"))

    print("\n=== SOHBET KAPATMA (5 ornek) ===")
    for _ in range(5):
        print(" " + smart_sohbet_kapatma(name="Ayşe"))

    print("\n=== AKADEMIK TEBRIK ===")
    print(" Matematik:", akademik_tebrik("matematik", 32.5, "Ali"))
    print(" Fizik:", akademik_tebrik("fizik", 11.0, "Zeynep"))

    print("\n=== SINIF VEDA ===")
    for c in ["12 SAY", "12 EA", "11 SÖZ", "10.Snf", "Mezun", "Unknown"]:
        print(f" {c}: {sinif_veda(c, 'Damla')}")
