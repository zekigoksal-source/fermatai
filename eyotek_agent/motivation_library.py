"""
FermatAI Motivasyon & Pedagoji Icerik Kutuphanesi
==================================================
Claude kalitesinde, bilimsel kaynakli, kulturel zenginlikte
fast_response ve Ollama sablonlari.

Kaynak: Bilimsel arastirmalar + Turk kulturel referanslari
Her kullanim random secim — ASLA tekrar etmez.
"""

import random

# ═══════════════════════════════════════════════════════════════════
# SOHBET BASLANGICI — "nasilsin" alternatifleri (10+ cesit)
# ═══════════════════════════════════════════════════════════════════

SOHBET_YANITLARI = [
    (
        "Iyiyim *{name}*, tesekkurler! 😊 Sen nasilsin?\n\n"
        "Bugun kendini nasil hissediyorsun? "
        "*Enerjik* mi, yorgun mu, yoksa tam gaz mi? 💪\n\n"
        "_Bir ders hakkinda konusmak ister misin, yoksa sadece sohbet mi edelim?_"
    ),
    (
        "Iyiyim *{name}*! 😊 Sen anlat bakalim?\n\n"
        "Dersler nasil gidiyor bu aralar? "
        "Bir konu var mi *kafani kurcalayan*?\n\n"
        "_Istersen son deneme analizine bakalim, istersen sohbet edelim._ 🎯"
    ),
    (
        "Tesekkurler *{name}*, her sey yolunda! 😊\n\n"
        "Peki sen? Bugun okulda *neler oldu*?\n\n"
        "_Merak ettigin bir konu varsa yazabilirsin, "
        "yoksa planin hakkinda konusabiliriz._ 📚"
    ),
    (
        "Gayet iyiyim *{name}*! 🌟 Sen nasil hissediyorsun bugun?\n\n"
        "Bugunun enerji seviyeni *1-10 arasi* versek kac olur? 😄\n\n"
        "_Yuksekse harika — baslayalim! Dusukse de bir plan yapariz._"
    ),
    (
        "Iyiyim *{name}*! 😊 Bugun kafan *acik* mi, yoksa biraz *bulutlu* mu?\n\n"
        "Cunku havanin durumuna gore plan yapabiliriz — "
        "aciksa zor konular, bulutluysa tekrar. ☁️☀️\n\n"
        "_Ne yapmak istersin?_"
    ),
    (
        "Harikayim *{name}*! 😊 Sen nasilsin — *calisma modu* acik mi, "
        "yoksa motor isinmasi mi lazim henuz?\n\n"
        "_Ister ders konusalim, ister bir soru coz, ister sadece sohbet et._ 🎯"
    ),
    (
        "Iyiyim *{name}*, sordugun icin sagol! 🙏\n\n"
        "Bu hafta nasil geciyor — *hizli* mi ucuyor yoksa suruklenip mi gidiyor? 😄\n\n"
        "_Son birkac gunde kucuk bir zafer var mi paylasacagin?_ 🏆"
    ),
    (
        "Iyiyim *{name}*! 😊 Nasilsin yani *gercekten* — "
        "rutin cevap vermek zorunda degilsin.\n\n"
        "Bugun seni en cok ne *yordu*? Ya da ne *mutlu etti*?\n\n"
        "_Konusmak istedigin ne varsa yazabilirsin._ 💙"
    ),
]


# ═══════════════════════════════════════════════════════════════════
# MOTIVASYON BAGLAM TOPLAMA SORULARI (10+ cesit)
# Amac: ogrencinin durumunu anlamak, sonra Claude derinlemesine analiz
# ═══════════════════════════════════════════════════════════════════

MOTIVASYON_SORULARI = [
    (
        "💙 Seni duyuyorum {name}.\n\n"
        "Sana daha iyi yardimci olabilmem icin birkaç sey sormam lazim:\n\n"
        "1️⃣ Bu duygu *ne zamandir* var?\n"
        "   _(bugun mu, son birkac gun mu, uzun suredir mi?)_\n\n"
        "2️⃣ En cok *hangi konuda* zorlaniyorsun?\n"
        "   _(ders/sinav mi, aile baskisi mi, arkadas ortami mi?)_\n\n"
        "3️⃣ Simdi kendini *1-10 arasi* puanlasan kac verirdin?\n\n"
        "_Rahatca yazabilirsin, seninle konusuyoruz._ 🤝"
    ),
    (
        "Hey {name}, mesajini okudum. 💙\n\n"
        "Sana yardimci olmak istiyorum ama once seni biraz daha anlamam lazim:\n\n"
        "🔹 Bugun seni en cok *ne yordu*?\n"
        "🔹 Son zamanlarda *uyku duzeni* nasil?\n"
        "🔹 Sence en buyuk *engel* ne simdi?\n\n"
        "_Istersen tek kelimeyle bile cevap verebilirsin — onemli olan konusmak._ 🌟"
    ),
    (
        "{name}, boyle hissetmen *cok normal* ve bunu paylastigin icin tesekkurler. 💙\n\n"
        "Sana ozel bir destek plani olusturmak istiyorum. Bunun icin:\n\n"
        "📌 Hangi ders(ler) seni en cok *strese* sokuyor?\n"
        "📌 Gunluk ortalama kac saat *calisiyorsun*?\n"
        "📌 Kendine ayirdigin *bos zaman* var mi?\n\n"
        "_Cevaplarina gore birlikte bir strateji olusturalim._ 🎯"
    ),
    (
        "Anliyorum {name}. 💙 Bu hisler gercek ve onemli.\n\n"
        "Sana sormak istedigim birkaç sey var:\n\n"
        "🌟 Bugun en cok *neyi basardin*? _(kucuk de olsa)_\n"
        "🌟 Simdi *en cok ne istiyorsun*? _(dinlenmek mi, konusmak mi, plan mi?)_\n"
        "🌟 Yarin sabah kalktiginda *ne degismis* olmasini isterdin?\n\n"
        "_Bunlari duymak bana cok yardimci olacak._ 🤝"
    ),
    (
        "{name}, once su soruyu sormak istiyorum: 💙\n\n"
        "Hayatin su an bir film olsaydi, hangi sahnesinde olurdun?\n"
        "🎬 _Egitim montaji mi, buyuk sinav sahnesi mi, yoksa ara verme sahnesi mi?_\n\n"
        "Cunku senin *hikayenin neresinde* oldugun, sana nasil yardim edecegimi belirliyor.\n\n"
        "_Bir de su: Bu aralar seni en cok *ne* mesgul ediyor?_"
    ),
    (
        "Seni cok iyi anliyorum {name}. 💙\n\n"
        "Bir sey sormak istiyorum — _yargisiz, tamamen merak olarak:_\n\n"
        "Son 1 haftada *en keyif aldigin* an ne oldu?\n"
        "_(ders disinda bile olabilir — dizi, muzik, spor, arkadas)_\n\n"
        "Cunku seni motive eden seyi bilmem, calismani da kolaylastirmama yardimci olur.\n\n"
        "_Ayrica: su anki ruh halini 3 kelimeyle tarif etsen ne derdin?_ 🎯"
    ),
    (
        "{name}, boyle zamanlar herkesin basina gelir — sen yalniz degilsin. 💙\n\n"
        "Ama sana *dogru* yardim edebilmem icin su bilgiler lazim:\n\n"
        "1️⃣ Su an *en cok hangi ders* baski yapiyor?\n"
        "2️⃣ *Ailenin beklentisi* ile *senin hedefin* ayni yonde mi?\n"
        "3️⃣ Kendini *ne zaman en iyi* hissediyorsun? _(gun icinde, hafta icinde)_\n\n"
        "_Bu bilgilerle sana cok daha etkili destek olabilirim._"
    ),
    (
        "Hey {name}! 💙\n\n"
        "Biliyor musun, motivasyon bazen gelgit gibidir — "
        "gel-git normal, onemli olan *dalga gecince ne yaptigin*.\n\n"
        "Sana bir soru: Su an *calisma ortamin* nasil?\n"
        "- Sessiz bir oda mi, gurultulu mu?\n"
        "- Telefonun yaninda mi, uzakta mi?\n"
        "- Yalniz mi calisiyorsun, birisiyle mi?\n\n"
        "_Bazen motivasyon degil, ortam degismesi gerekiyor olabilir._ 🏡"
    ),
]


# ═══════════════════════════════════════════════════════════════════
# YARDIMCI FONKSIYONLAR
# ═══════════════════════════════════════════════════════════════════

def get_sohbet(name: str) -> str:
    """Random sohbet yaniti sec ve isim yerlestir."""
    return random.choice(SOHBET_YANITLARI).replace("{name}", name or "")


def get_motivasyon_sorusu(name: str) -> str:
    """Random motivasyon baglam toplama sorusu sec."""
    return random.choice(MOTIVASYON_SORULARI).replace("{name}", name or "")


# ═══════════════════════════════════════════════════════════════════
# TREND BAZLI MOTİVASYON — yükseliş / düşüş / stabil (her biri 10+)
# fast_response'ta ogrenci_motivasyon() tarafindan kullanilir
# ═══════════════════════════════════════════════════════════════════

TREND_YUKSELIS = [
    (
        "📈 *{name}, yukselistesin!*\n\n"
        "Son denemelerde netlerin artiyor — bu tesaduf degil, *calismanin sonucu.*\n\n"
        "Ama dikkat: yukselirken en tehlikeli sey *rahatlamak.* "
        "Simdi ivmeyi korumak icin zayif konularina odaklan.\n\n"
        "_Hangi konuyu guclendirmek istersin?_ 🎯"
    ),
    (
        "🔥 *Gidisatin muhtesem {name}!*\n\n"
        "Netlerin tirmaniyor — *cin bambusu* gibi, kok salmistin, simdi buyume basladi.\n\n"
        "Bu tempoda hedefin yakin. Ama unutma: *son 60 gunde kazanilan 10 net = YKS'de 30-40 puan fark.*\n\n"
        "_Devam et, sana inaniyorum!_ 💪"
    ),
    (
        "✨ *{name}, trendi goruyorum — yukarida!*\n\n"
        "Einstein: 'Delilik ayni seyi yapip farkli sonuc beklemektir.' "
        "Sen farkli yapiyorsun, sonuc da farkli geliyor.\n\n"
        "Bu hafta hangi derse yogunlasti? Oradan devam edelim.\n\n"
        "_Bir sonraki denemede hedefin kac net?_ 🎯"
    ),
    (
        "💪 *{name}, netlerin yukseliyor!*\n\n"
        "Bu grafik bana *karli bir dagin zirvesine yuruyusu* hatirlatiyor — "
        "her adim zor ama gorunus guzellesiyoor.\n\n"
        "Sana sormak istiyorum: bu yukselisi *en cok hangi ders* sagladi?\n\n"
        "_Onu konusalim, yarisina kadar geldik!_ 🏔"
    ),
    (
        "🚀 *Harika {name}, ivme sende!*\n\n"
        "Angela Duckworth'un dedigi gibi: *'Tutku + Azim = Basari.'* "
        "Yetenekten degil, calisindan geliyor bu yukselis.\n\n"
        "Simdi onemli: *ayni tempoda devam.* Rutin bozma, plan degistirme.\n\n"
        "_Haftanin geri kalaninda ne uzerinde calisiyorsun?_ 📚"
    ),
    (
        "📊 *{name}, veriler cok guzel konusuyor!*\n\n"
        "Yukselis gercek ve tutarli — bu *kisa vadeli sansizlik degil, uzun vadeli calisma.*\n\n"
        "Feynman: 'Dogayi kandiramazsiniz.' Sinavda da oyle — gercek bilgi her zaman kazanir.\n\n"
        "_Bu motivasyonla bir calisma plani yapalim mi?_ 🎯"
    ),
    (
        "🌟 *{name}, tebrikler — yukselis devam ediyor!*\n\n"
        "Biliyor musun, *her 5 net artis = yaklasik 15-20 puan* fark yapar. "
        "Sen simdi o farkini olusturuyorsun.\n\n"
        "James Clear: '%1 iyilesme her gun → yil sonunda 37 kat.' Tam bunu yapiyorsun.\n\n"
        "_Zayif konularini soyle, birlikte planlayalim!_ 💪"
    ),
    (
        "⭐ *{name}, bu grafik seni anlatıyor!*\n\n"
        "Yukselis trendi net. Su an yapman gereken: *momentum kaybetmemek.*\n\n"
        "Pratik oneri: yarin sabah kalktiginda hemen 10 dk calis. "
        "Zeigarnik etkisi — *basladiktan sonra devam etmek kolay.*\n\n"
        "_Hangi ders icin sabah rutini kuralim?_ 🎯"
    ),
    (
        "🎉 *{name}, yukselis gercek!*\n\n"
        "Sana bir bilimsel gercek: beyin *tekrar ettikce sinaptik baglari guclendiriyor.* "
        "Her cozdugun soru kalici ogrenmeye katkida bulunuyor.\n\n"
        "Simdi *en zayif 2 konuya* odaklanirsan, toplu puan atlayisi yakalarsın.\n\n"
        "_Zayif konularina bakalim mi?_ 📊"
    ),
    (
        "🏆 *{name}, bu tempo ile hedefin yakin!*\n\n"
        "Atatürk: 'Basari, sasiranlarin degil, sasmayanlarin isleridir.' "
        "Sen sasmiyorsun, kararli gidiyorsun.\n\n"
        "Son asamada dikkat: *kolay konulari ihmal etme.* "
        "Kazanilmis netleri kaybetmek en acıtıcı sey.\n\n"
        "_Guclu konulari koruma plani yapalim mi?_ 🛡"
    ),
]

TREND_DUSUS = [
    (
        "📉 *{name}, son denemede biraz dusus var.*\n\n"
        "Ama endise etme — bu *normal bir dalganma.* "
        "Onemli olan trendi degil, *nedeni* anlamak.\n\n"
        "Sence ne oldu? Konu mu zordu, konsantrasyon mu dusuk, zaman mi yetmedi?\n\n"
        "_Birlikte analiz yapalim, sebebi bulalim._ 🔍"
    ),
    (
        "💙 *{name}, dusus gecici — sen kalicisin.*\n\n"
        "Carol Dweck: 'Basarisizlik bir son degil, ogrenme firsatidir.' "
        "Bu deneme sana *neyi bilmedigini* gosterdi.\n\n"
        "Hata yaptigin konulara odaklanirsan, bir sonraki denemede *toparlama garanti.*\n\n"
        "_Hangi derste en cok dusus yasadin?_ 📊"
    ),
    (
        "🌱 *{name}, her dusus bir ders iceriyor.*\n\n"
        "Son denemede biraz gerileme var ama bu *sezonun parçası.* "
        "Maratonculara bak — son 10 km en zor ama *en degerli.*\n\n"
        "Sana ozel bir soru: son 1 haftada gunluk kac saat calistin?\n\n"
        "_Belki calisma rutininde kucuk bir ayar yeterli._ ⚙"
    ),
    (
        "💪 *{name}, dusuler yukselmek icindir.*\n\n"
        "Viktor Frankl: 'Anlam bulan insan her sartla basa cikar.' "
        "Senin anlamın var — hedefin var.\n\n"
        "Pratik adim: *yarin sadece 1 zayif konudan 20 soru coz.* "
        "Kucuk basarilar motivasyonu geri getirir.\n\n"
        "_Hangi konudan baslayalim?_ 🎯"
    ),
    (
        "📌 *{name}, dusus analizi yapalim:*\n\n"
        "Cogu zaman dusus *genel yorgunluktan* gelir, bilgi eksikliginden degil.\n\n"
        "Kontrol listesi:\n"
        "☐ Uyku 7+ saat mi?\n"
        "☐ Telefon kapali mi calisirken?\n"
        "☐ 45dk'da 1 mola aliyor musun?\n\n"
        "_Bunlardan hangisi eksik?_ 🤔"
    ),
    (
        "🔄 *{name}, bazen bir adim geri iki adim ileri demektir.*\n\n"
        "Spitzer'in unutma egrisi: bilgi *tekrar edilmezse* 24 saatte %70 kaybolur. "
        "Belki son hafta tekrar eksik kalmistir.\n\n"
        "Oneri: bu hafta *yeni konu ekleme, sadece eski konulari tekrar et.*\n\n"
        "_Tekrar plani yapalim mi?_ 📚"
    ),
    (
        "🧠 *{name}, dusus seni tanimlamaz.*\n\n"
        "Bir sinav = bir gun. Senin gercek kapasiten *ortalamanla* olculur, "
        "tek bir sinavla degil.\n\n"
        "Sana sormak istiyorum: bu denemede *surpriz* zorluk mu vardi, "
        "yoksa bildigin konulari mi kacirdin?\n\n"
        "_Farkli sorunlarin farkli cozumleri var — konusalim._ 🔍"
    ),
    (
        "🌟 *{name}, her sampiyonun kotugunleri olur.*\n\n"
        "Kobe Bryant: 'Basarisiz oldugum 9000 sut beni sampyon yapti.' "
        "Onemli olan *denemekten vazgecmemek.*\n\n"
        "Sana kucuk bir gorev: yarin 5 dk'lik bir fizik tekrari yap. "
        "Sadece 5 dk. Bittikten sonra bana yaz.\n\n"
        "_Yapabilir misin?_ 💪"
    ),
    (
        "📊 *{name}, gerceklere bakalim:*\n\n"
        "Evet dusus var. Ama *sezon basindan bu yana toplamda ne kadar yukseldin?* "
        "Buyuk resmi gormek onemli.\n\n"
        "Bir kotudeneme seni geri almaz — *bir ay calisma almaz.* "
        "Toparlanma zamaniniz.\n\n"
        "_Son 5 denemeni kiyaslayalim mi? Buyuk resmi gorelim._ 📈"
    ),
    (
        "💙 *{name}, seni anliyorum.*\n\n"
        "Dusus his olarak zor ama *veri olarak yonetilebilir.* "
        "Hangi derste kac net kaybettin bilirsek, *tam odakli calisma* yapabiliriz.\n\n"
        "Cuceloglu: 'Kendini tanimak basarinin ilk adimi.' "
        "Zayif noktani bilmek zaten yari cozum.\n\n"
        "_Zayif konularina bakalim mi?_ 🎯"
    ),
]

TREND_STABIL = [
    (
        "➡️ *{name}, istikrarlisin — bu iyi bir sey!*\n\n"
        "Ama istikrar = konfor alani olmasin. "
        "*Simdi 1 adim daha atmanin tam zamani.*\n\n"
        "Zayif konularindan birine odaklanirsan, bu duzluk *yukselise* doner.\n\n"
        "_Hangi derse yogunlasmak istersin?_ 🎯"
    ),
    (
        "📊 *{name}, sabit gidiyorsun!*\n\n"
        "Sabitlik iyi — ama YKS'de *fark yaratan* ogrenci, stabili *bozan* ogrencidir.\n\n"
        "Pratik oneri: bu hafta *sadece 1 zayif konuya* gunluk 30dk ayir. "
        "Kucuk odaklanma = buyuk puan.\n\n"
        "_Zayif konularina bakalim mi?_ 📚"
    ),
    (
        "🧠 *{name}, su an bir platodaysin.*\n\n"
        "Plato = ilerleme durmadi, *gorunmuyor* sadece. "
        "Altta ogrenme devam ediyor — beyinin bilgiyi *yeniden yapilandirmasi* zaman alir.\n\n"
        "Newton: 'Sabir gosterene dogalari bile boyun eger.'\n\n"
        "_Bu hafta ne uzerinde calisiyorsun?_ 💪"
    ),
    (
        "⚡ *{name}, dengeli gidiyorsun ama bir kivilcim lazim!*\n\n"
        "Sence hangi ders seni *en cok heyecanlandiriyor?* "
        "O derste derinlesmek motivasyonu geri getirir.\n\n"
        "Bazen calismayi *sevdigin* dersten baslamak, *sevilmeyeni* de surukler.\n\n"
        "_Favori dersin ne?_ 🌟"
    ),
    (
        "📌 *{name}, sana bir meydan okuma:*\n\n"
        "Bu hafta *tek bir konuyu* tamamen bitir. "
        "Basla → calis → soru coz → tamam de. *Bitirme hissi* motivasyon patlamasi yaratir.\n\n"
        "Zeigarnik etkisi: tamamlanmamis isler zihni mesgul eder. "
        "*Bir tanesini kapatmak* hafifletir.\n\n"
        "_Hangi konuyu bitirelim?_ 🎯"
    ),
    (
        "🎯 *{name}, stabil gitmek kolay degil — bunu takdir ediyorum.*\n\n"
        "Ama simdi kritik soru: *Hedefine ne kadar yakinsin?*\n\n"
        "Eger hedefe 20 net uzaktaysan, kalan 60 gunde *haftada 3-4 net artisi* yeterli.\n\n"
        "_Puan hesaplayalim mi? Hedefine ne kadar yakin oldugunu gorelim._ 📊"
    ),
    (
        "🔬 *{name}, sabitlik = guclu temel demek.*\n\n"
        "Marie Curie: 'Hayatta korkulmasi gereken sey yoktur, sadece anlasilmasi gereken seyler vardir.' "
        "Simdi anlamaman gereken: *hangi konular seni tutuyor?*\n\n"
        "Bir sonraki denemede *5 net artis* icin 2-3 konu yeter.\n\n"
        "_Bakalim mi hangileri?_ 🔍"
    ),
    (
        "💡 *{name}, sana bir perspektif:*\n\n"
        "Su anki netin tutarli — bu *guvenilirlik.* "
        "Ama YKS'de guvenilirlik + *kucuk siçrama* = buyuk fark.\n\n"
        "Mesela: Mat'ta 3 net artis + Fizik'te 2 net = *+15 puan.* "
        "Bu kadar basit.\n\n"
        "_Hesaplayalim mi? 'Kac puan yaparim' yaz._ 📊"
    ),
    (
        "🏃 *{name}, duz yolda hiz kazanmanin tam zamani!*\n\n"
        "Maraton kosucusu duz arazide hizlanir, yokusta yavaslar. "
        "Sen simdi *duz arazidesin* — ivme kazan!\n\n"
        "Bu hafta: *her gun 1 saat ekstra* bir zayif konuya. 7 saat = ciddi gelisim.\n\n"
        "_Hangi konuda ekstra calisalim?_ 💪"
    ),
    (
        "🌟 *{name}, istikrar senin sulanin — simdi dalga yarat!*\n\n"
        "Biliyor musun, gol atan futbolcu genellikle *sessiz kalan* oyuncudur — "
        "sabırla pozisyon bekler, sonra *tek hareketle* fark yaratir.\n\n"
        "Senin icin o hareket: *en zayif 2 konuya bu hafta odaklan.*\n\n"
        "_Zayif konularina bakalim, strateji kuralim._ 🎯"
    ),
]


def get_trend_motivasyon(name: str, trend: str) -> str:
    """Trend bazli motivasyon mesaji sec.
    trend: 'yukselis' | 'dusus' | 'stabil'
    """
    if trend == "yukselis":
        pool = TREND_YUKSELIS
    elif trend == "dusus":
        pool = TREND_DUSUS
    else:
        pool = TREND_STABIL
    return random.choice(pool).replace("{name}", name or "")
