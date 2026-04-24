"""
Redirect Templates — Classroom Management Çekirdek #3
=======================================================
Öğrenci off-topic konuşma sürüklemesine karşı DOĞAL yönlendirmeler.

Neo vizyonu:
  "Bir öğretmen 40 dk'lık dersin 20. dakikasında 'arkadaşlar dönelim' demez
   moda mod — 'aklıma bir şey geldi, şu konu şöyle...' der.
   Biz de öyle olmalıyız. Öğrenci *hissetmeli* ki sohbet devam ediyor,
   ama aslında derse dönüyor."

Her kategori için 5-6 varyasyon (random seçim → tekrar hissi olmasın):
  NAZIK       — drift_level='hafif': sadece 1 cümle ekle cevabın sonuna
  ORTA        — drift_level='orta': kısa sohbet kapatma + akademik soru
  NET         — drift_level='agir': açık ama yumuşak davet
  SON_SEANS   — token budget %90+: yarına davet
  KAPANIS     — token budget %100: günlük bitiş

Ayrıca:
  MERAK_UYANDIR — akademik cevabın sonuna karşı-soru (flow state)
  ISINMA        — ilk mesajlarda samimi karşılama
"""
from __future__ import annotations
import random
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════
# NAZIK (hafif drift — sadece ipucu)
# ═══════════════════════════════════════════════════════════════════════════
_NAZIK = [
    "_Bu arada aklıma geldi — {hedef_konu} konusunda kaldığın yerden devam etmek ister misin?_",
    "_Güzel sohbet. İstersen bu arada {hedef_konu}'a da bakabiliriz._",
    "_Keyifli... Bir ara {hedef_konu} konusunu bitirelim istersen, kısa sürer._",
    "_Aramızda kalsın, {hedef_konu}'yu unutmayalım._ 🎯",
    "_Not: bu hafta {hedef_konu}'dan geç kalma istemiyorum senin için._",
    "_Bu sohbete devam edebiliriz tabii — ama {hedef_konu} seni bekliyor._ 💡",
]

# ═══════════════════════════════════════════════════════════════════════════
# ORTA (drift_level='orta' — kısa sohbet kapat + akademik geçiş)
# ═══════════════════════════════════════════════════════════════════════════
_ORTA = [
    "Güzel paylaştın {name}. 😊\n\nŞimdi söyle bakalım — {hedef_konu} konusunda en son nerede kalmıştık? Oraya odaklanmak istiyorum.",
    "*{name}*, böyle bir sohbet iyi geliyor. 💙\n\nAma şunu konuşalım: {hedef_konu}'dan bugün bir şey çözdün mü? Hadi küçük bir görev alalım.",
    "Seninle her şeyi konuşabiliriz, biliyorsun. Ama *koçum hissim* şunu söylüyor: {hedef_konu}'ya 15 dakika ver, sonra devam ederiz.",
    "Anladım {name}. 🎯\n\nBirkaç dakika sana ait olsun — {hedef_konu}'dan *1 soru* çözelim mi? Sonra ne istersen konuşuruz.",
    "*{name}*, sohbet yorulduğunda hata artıyor. Şimdi kısa bir akademik mola vereyim: {hedef_konu} hakkında tek bir soru sorayım sana.",
    "Seni duyuyorum. Ama bugünkü *hedefin* var — {hedef_konu}'yu geçmeden bu günü kapatmak istemem. Birlikte halledelim.",
]

# ═══════════════════════════════════════════════════════════════════════════
# NET (drift_level='agir' — 3 ardışık off-topic, net davet)
# ═══════════════════════════════════════════════════════════════════════════
_NET = [
    "*{name}*, şimdi seni bir öğretmenin olarak geri çağırmam gerek — son üç mesajımız dersten uzaklaştı. 🎯\n\nHadi {hedef_konu}'ya dönelim. Bir soru seç, birlikte bakalım.",
    "Seviyorum seninle konuşmayı ama *bu bir öğretmen-öğrenci ilişkisi*. Beni koçun gibi gör — şimdi {hedef_konu}'a odaklanmamız gerek. İster misin?",
    "İyi muhabbet {name}! 😄 Ama bir öğretmenin olarak dürüst olmam lazım: son mesajlarımız seni {hedef_konu}'dan uzaklaştırıyor. 10 dakika gerçek çalışma yapalım mı?",
    "Dinle {name}, seninle sohbet ederim her konuda ama *en büyük hedefin {hedef_konu}'yu bitirmek*. Şimdi buraya dönelim — yoksa gün sonunda pişman olursun.",
    "Anladım, dağılmak insana iyi gelir bazen. Ama *bu kanalı açtığında hedefin netti*: {hedef_konu}'yu öğrenmek. Şimdi birlikte 1 soru çözüp devam edelim mi?",
    "*{name}*, şu anki halimi söyleyeyim: sana iyi bir öğretmen olmak istiyorum. Bunun için {hedef_konu}'ya geri dönmen gerek. *Bir soru seçelim* — birlikte çözeriz, sonra istediğin kadar konuşabiliriz.",
]

# ═══════════════════════════════════════════════════════════════════════════
# SON_SEANS (token budget %90+ — nazik günü kapat)
# ═══════════════════════════════════════════════════════════════════════════
_SON_SEANS = [
    "*{name}*, bugün güzel konuştuk. Yorulmadan öğrenmek için bir kural var — *biraz dinlen*. Yarın taze kafayla devam edelim mi?",
    "Bugünkü sohbet bana keyif verdi {name}. Ama beynin de dinlenmeli — hafıza uykuda pekişir. Yarın buluşmak üzere? 🌙",
    "Bir şey söyleyeyim {name}: bugün bol konuştuk, bu iyi. Ama *yarına da bir şeyler saklayalım*. İyi çalışmalar, yarın burayım.",
    "{name}, son cümleni söyleyeyim: bugün iyi iş çıkardın, şimdi kendine bir mola ver. Yarın taze bir başlangıç. 🎯",
    "Bu sohbet 20. dakikasında artık — sen de yorgunsun {name}. Bunu bir *güzel kapanış* yapalım, yarın devam. 💪",
]

# ═══════════════════════════════════════════════════════════════════════════
# KAPANIS (token budget %100 — sert ama sıcak bitiş)
# ═══════════════════════════════════════════════════════════════════════════
_KAPANIS = [
    "*{name}*, bugünün kontenjanı doldu 😊 — çok konuştuk ve bu iyi bir şey. Yarın görüşmek üzere, iyi akşamlar!\n\n_Acil bir durum varsa öğretmenine yazabilirsin._",
    "Burada durmalıyız {name}. Hem sen yorgunsun hem de seninle iyi konuşmak için yarına hazırlanmalıyım. Görüşürüz!\n\n_İyi dinlen — yarın daha iyi anlatırım._ 🌟",
    "Bugünlük kapak olsun {name}. Yarın bambaşka bir gün. Kendine iyi bak, ders aklında kalsın.\n\n_Yarın buluşuyoruz._ 🎯",
    "Seni seviyorum {name} ama öğretmenin olarak biliyorum: *bugün yeterli*. Yarın görüşürüz.\n\n_İyi geceler._ 🌙",
]

# ═══════════════════════════════════════════════════════════════════════════
# MERAK_UYANDIR (akademik cevap sonu — karşı-soru, flow state)
# ═══════════════════════════════════════════════════════════════════════════
_MERAK = [
    "_Peki sence bu kural her zaman geçerli mi, bir istisna aklına geliyor mu?_ 🤔",
    "_Sen bu konuyu günlük hayatta nerede görüyorsun?_ 💡",
    "_Hangi kısmı seni en çok şaşırttı?_ ✨",
    "_Şimdi benzer bir soru çözmek ister misin?_ 🎯",
    "_Bu konu nerede kafanı karıştırıyor hala?_ 🤝",
    "_Aynı mantığı başka bir derse de uygulayabilir misin?_ 🧠",
    "_Seni en çok zorlayan kısım hangisiydi?_ 💪",
    "_Bir örnek sen verir misin şimdi?_ 📐",
    "_Peki {name}, bu bilgiyle bir sonraki adımı atabilir misin?_ 🎓",
    "_Sana bir soru sorayım: bunun bir sonraki aşaması ne olur sence?_ 🔬",
]

# ═══════════════════════════════════════════════════════════════════════════
# ISINMA (ilk 2-3 mesaj — sağlıklı sohbet açılışı)
# ═══════════════════════════════════════════════════════════════════════════
_ISINMA_AKADEMIK_GECIS = [
    "Şimdi söyle bakalım: bugün hangi konuyu bitirmek istersin?",
    "Bugünkü hedefimiz ne olsun?",
    "Aklında hangi konu var bugün?",
    "Hangi dersi birlikte çalışalım?",
    "Bir konuyu kısa sürede bitirelim mi bugün?",
]


# ═══════════════════════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════════════════════

def get_redirect(drift_level: str, name: str = "",
                 hedef_konu: str = "ders") -> Optional[str]:
    """drift_level'e göre uygun redirect mesajı döner.

    Args:
        drift_level: 'yok' | 'hafif' | 'orta' | 'agir'
        name: öğrenci adı (ilk ad kullanılır)
        hedef_konu: 'türev', 'kaldırma kuvveti', 'paragraf' vb. (varsa)

    Returns: str mesaj veya None (redirect gerekmiyor)
    """
    first = (name or "").split()[0] if name else "arkadaşım"
    konu = hedef_konu or "ders"

    pool = None
    if drift_level == "hafif":
        pool = _NAZIK
    elif drift_level == "orta":
        pool = _ORTA
    elif drift_level == "agir":
        pool = _NET
    else:
        return None

    msg = random.choice(pool)
    return msg.format(name=first, hedef_konu=konu)


def get_budget_closing(status: str, name: str = "") -> Optional[str]:
    """Token budget kapanış mesajı.

    status: 'last_seans' | 'exceeded'
    """
    first = (name or "").split()[0] if name else "arkadaşım"
    if status == "last_seans":
        return random.choice(_SON_SEANS).format(name=first)
    if status == "exceeded":
        return random.choice(_KAPANIS).format(name=first)
    return None


def get_merak_sorusu(name: str = "") -> str:
    """Akademik cevabın sonuna eklemek için karşı-soru."""
    first = (name or "").split()[0] if name else "sen"
    return random.choice(_MERAK).format(name=first)


def get_isinma_gecis() -> str:
    """Isınma sonrası akademik geçiş cümlesi."""
    return random.choice(_ISINMA_AKADEMIK_GECIS)


# Toplam şablon sayısı kontrolü
def template_count() -> dict:
    return {
        "nazik": len(_NAZIK),
        "orta": len(_ORTA),
        "net": len(_NET),
        "son_seans": len(_SON_SEANS),
        "kapanis": len(_KAPANIS),
        "merak": len(_MERAK),
        "isinma_gecis": len(_ISINMA_AKADEMIK_GECIS),
        "toplam": len(_NAZIK) + len(_ORTA) + len(_NET) + len(_SON_SEANS)
                  + len(_KAPANIS) + len(_MERAK) + len(_ISINMA_AKADEMIK_GECIS),
    }


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=== Şablon envanteri ===")
    cnt = template_count()
    for k, v in cnt.items():
        print(f"  {k}: {v}")

    print("\n=== ORTA redirect örnekleri ===")
    for i in range(3):
        r = get_redirect("orta", name="Zehra", hedef_konu="türev kuralı")
        print(f"  {i+1}. {r}")

    print("\n=== NET redirect (agir drift) ===")
    for i in range(2):
        r = get_redirect("agir", name="Ali", hedef_konu="kaldırma kuvveti")
        print(f"  {i+1}. {r}")

    print("\n=== Budget kapanışları ===")
    print(f"  last_seans: {get_budget_closing('last_seans', 'Ayşe')}")
    print(f"  exceeded:   {get_budget_closing('exceeded', 'Mehmet')}")

    print("\n=== Merak soruları (3 örnek) ===")
    for i in range(3):
        print(f"  {i+1}. {get_merak_sorusu('Zehra')}")
