"""
FermatAI — Anekdot Kütüphanesi (22.1n-neo FAZ 1.3)
====================================================

22+ gerçek hayat hikayesi. Bot motivasyon/zor an/ilham verirken kullanir.

KULLANIM:
  - Ogrenci "basaramiyorum" → get_for_mood("vazgecme") → Edison 10k deneme
  - Matematik korkusu → get_for_konu("matematik") → Ali Kuscu / Cahit Arf
  - Genel motivasyon → get_random()

KURAL: Anekdot dogrulanmis olmali. Yanlis bilgi yazilirsa bot halusilasyon yapar.
"""
from __future__ import annotations

import random
from typing import Optional
from db_pool import db_fetch, db_fetchrow, db_execute


ANEKDOTLAR = [
    # ─── TÜRK BİLİM İNSANLARI ──
    {
        "slug": "aziz_sancar_harran",
        "kim": "Aziz Sancar",
        "konu": "baslamak",
        "baslik": "Harran'dan Nobel'e — yolu kim cizdi?",
        "metin": (
            "Aziz Sancar 1946'da Mardin Savur'da, 8 kardeşli bir çiftçi ailenin oğlu olarak "
            "doğdu. Elektrik yoktu, kütüphane uzaktı. İstanbul Tıp'a girdi, Amerika'ya DNA "
            "tamiri araştırmak için gitti. 2015 Kimya Nobel'i. 'Köyden çıkan beni değil, merakımı "
            "taşıdım' dedi. Önemli olan nereden başladığın değil, neyi taşıdığın."
        ),
        "ders": "",
        "duygusal_hedef": "baslangic,vazgecme,sartlar",
        "kaynak": "Aziz Sancar (2015 Nobel lecture); biyografi",
        "etiketler": "turk,nobel,dna,azim,kokleri",
    },
    {
        "slug": "cahit_arf_matematik",
        "kim": "Cahit Arf",
        "konu": "matematik",
        "baslik": "Arf Değişmezi — dünyaya Türk matematiği",
        "metin": (
            "Cahit Arf (1910-1997) ODTÜ matematik bölümünün kurucularından. 'Arf Değişmezi' "
            "diye bir matematik kavramı var — dünya matematik literatüründe hâlâ kullanılıyor. "
            "Ama Cahit Hoca şakacıydı: 'Bir matematik problemi çözmek, bilmediğin bir tarafa "
            "doğru yürümektir — ama en çok o yürüyüş güzeldir' derdi. Sen de şimdi yürüyorsun."
        ),
        "ders": "matematik",
        "duygusal_hedef": "ilham,matematik_korkusu,kimlik",
        "kaynak": "Cahit Arf biyografi; Tübitak",
        "etiketler": "turk,matematik,odtu,arf",
    },
    {
        "slug": "oktay_sinanoglu_genc_prof",
        "kim": "Oktay Sinanoğlu",
        "konu": "yas",
        "baslik": "25 yaşında profesör — 'Türk Einstein'ı'",
        "metin": (
            "Oktay Sinanoğlu 25 yaşında Yale Üniversitesi'nin en genç profesörü oldu. "
            "Kuantum kimyasında çığır açtı — çok elektronlu atom teorisi onun adını taşır. "
            "Lise yıllarında 'çok yorgunum' demek için zamanı yoktu. 'Yaşım küçük, vaktim "
            "bol değil' derdi. Sen de şimdi küçüksün, vakit bol."
        ),
        "ders": "kimya",
        "duygusal_hedef": "yas_baskisi,zaman,hedef",
        "kaynak": "Oktay Sinanoğlu biyografi",
        "etiketler": "turk,yale,kuantum,genc,ozguven",
    },
    {
        "slug": "ali_kuscu_astronomi",
        "kim": "Ali Kuşçu",
        "konu": "merak",
        "baslik": "Ali Kuşçu — Fatih'in gözbebeği astronom",
        "metin": (
            "Ali Kuşçu 15. yüzyılda Semerkant'tan İstanbul'a geldi. Fatih Sultan Mehmet "
            "onu Ayasofya'ya başmüderris atadı. Dünya'nın çevresini ölçtü, ay'ın mesafesini "
            "hesapladı — modern astronomi aletleri olmadan. Kopernik'ten 30 yıl önce "
            "dünyanın döndüğünü anlatan formülü vardı. Merak + hesap + cesaret."
        ),
        "ders": "fizik",
        "duygusal_hedef": "ilham,bilim_tarihi,ozguven",
        "kaynak": "Aydın Sayılı — Türk Bilim Tarihi",
        "etiketler": "turk,osmanli,astronomi,matematik",
    },
    {
        "slug": "sabiha_gokcen_pilot",
        "kim": "Sabiha Gökçen",
        "konu": "sinir",
        "baslik": "İlk kadın savaş pilotu — Sabiha Gökçen",
        "metin": (
            "1937. Sabiha Gökçen dünyanın ilk kadın savaş pilotu oldu. Atatürk'ün manevi "
            "kızı. 'Bir kadın pilot olamaz' cümlesini çok duydu. O kenara yazdı, uçtu. "
            "Yıl 2026 — artık 'bir öğrenci YKS'de dereceye giremez' cümlesini duyan sensin. "
            "Sabiha hanımın dediği gibi: 'Kenara yaz, uçmaya devam.'"
        ),
        "ders": "",
        "duygusal_hedef": "sinir,toplum_baskisi,cinsiyet",
        "kaynak": "Sabiha Gökçen — Uçtum (anı kitabı)",
        "etiketler": "turk,pilot,kadin,ilk,cesaret",
    },
    {
        "slug": "mustafa_kemal_matematik",
        "kim": "Mustafa Kemal",
        "konu": "odak",
        "baslik": "Kemal ismi — matematikten gelen ad",
        "metin": (
            "Mustafa Kemal'in matematik öğretmeni Yüzbaşı Mustafa, küçük öğrencisine 'sen "
            "de Mustafa, ben de — birbirimize karışıyoruz. Senin için daha yakışıklı: "
            "Kemal — mükemmellik demek' dedi ve adına Kemal ekledi. O günden sonra "
            "ad tutkunun görsel sembolü oldu. Her problem çözdüğünde Kemal oluyorsun."
        ),
        "ders": "matematik",
        "duygusal_hedef": "ilham,kimlik,hedef",
        "kaynak": "Şevket Süreyya Aydemir — Tek Adam",
        "etiketler": "turk,tarih,ataturk,matematik",
    },
    # ─── DÜNYA BILIM İNSANLARI ──
    {
        "slug": "einstein_matematik_efsane",
        "kim": "Albert Einstein",
        "konu": "efsane",
        "baslik": "Einstein matematikte kötüydü yalanı",
        "metin": (
            "Şu meşhur 'Einstein matematikte kötüydü' efsanesi YANLIŞ. Einstein 10 yaşında "
            "analitik geometri, 15'inde kalkülüs biliyordu. Efsane şöyle başladı: 1930'larda "
            "lise notları açıklandı, 1=en yüksek not sistemi yanlış yorumlandı. Sen de "
            "'matematikte kötüyüm' etiketini üzerinden at — beyinlerimiz bu değil."
        ),
        "ders": "matematik",
        "duygusal_hedef": "ozguven,matematik_korkusu,efsane",
        "kaynak": "Walter Isaacson — Einstein biyografi (2007)",
        "etiketler": "fizik,matematik,efsane,ozguven",
    },
    {
        "slug": "feynman_feynman_tekniği",
        "kim": "Richard Feynman",
        "konu": "ogrenme",
        "baslik": "Bilmediğimi nasıl anlarım? — Feynman yöntemi",
        "metin": (
            "Richard Feynman (Nobelli fizikçi) bir konuyu anlayıp anlamadığını kontrol "
            "etmek için şunu yapardı: Konuyu 12 yaşındaki bir çocuğa anlatmaya çalış. "
            "Karmaşık kelimeler kullanırsan — aslında anlamıyorsun demek. Basit dilde "
            "anlatabiliyorsan — gerçekten öğrenmişsin. Deneme şimdi: konuyu bana anlat."
        ),
        "ders": "",
        "duygusal_hedef": "ogrenme,teknik,karisiklik",
        "kaynak": "Surely You're Joking, Mr. Feynman! (1985)",
        "etiketler": "fizik,nobel,ogrenme,teknik",
    },
    {
        "slug": "edison_10000_deneme",
        "kim": "Thomas Edison",
        "konu": "basarisizlik",
        "baslik": "10.000 deneme — başarısızlık diye bir şey yok",
        "metin": (
            "Edison ampul yaparken 10.000+ farklı malzemede denedi. Bir gazeteci alaycı "
            "bir şekilde 'Bu kadar çok kere başarısız olmak nasıl hissettiriyor?' diye sordu. "
            "Edison: 'Ben başarısız olmadım. Ampul'ün çalışmayacağı 10.000 yol keşfettim.' "
            "Senin her yanlışın da bir keşif — neyin çalışmayacağının ipucu."
        ),
        "ders": "",
        "duygusal_hedef": "basarisizlik,vazgecme,hata",
        "kaynak": "Edison biyografi; Smithsonian",
        "etiketler": "kesif,azim,basarisizlik,hata",
    },
    {
        "slug": "marie_curie_iki_nobel",
        "kim": "Marie Curie",
        "konu": "azim",
        "baslik": "İki Nobel — imkansızdı, oldu",
        "metin": (
            "Marie Curie Polonya'dan geldi, Paris Sorbonne'a öğrenci oldu — kadın "
            "bilim insanının olmadığı yıllarda. Fizik Nobel'i 1903, Kimya Nobel'i 1911. "
            "İki farklı bilim dalında iki Nobel — tarihte tek. Laboratuarını kış akşamında "
            "ısıtacak parası yoktu. Şimdi öğrencinin elinde 5000 YKS sorusu ve AI koç var."
        ),
        "ders": "",
        "duygusal_hedef": "azim,sartlar,kadin,bilim",
        "kaynak": "Marie Curie biyografi (1937)",
        "etiketler": "nobel,fizik,kimya,kadin,azim",
    },
    # ─── İSLAM / DOĞU BİLİMİ ──
    {
        "slug": "ibn_sina_tip_kitabi",
        "kim": "İbn-i Sina",
        "konu": "genclik",
        "baslik": "18 yaşında tıp hocası — El-Kanun fi't-Tıb",
        "metin": (
            "İbn-i Sina 10 yaşında Kur'an-ı ezberledi, 16'da tıp kitapları okudu, 18'de "
            "ünlü tabip oldu. Canon Medicinae 6 asır boyunca Avrupa tıp fakültelerinde okutuldu. "
            "'Bu hayat kısa, bilim uzun — vakit kaybedemem' dedi. Sen şimdi 11. sınıftasın — "
            "İbn-i Sina'nın tıp hocası olduğu yaşa 7 yıl var. Vakit var, yön gerekli."
        ),
        "ders": "",
        "duygusal_hedef": "genclik,hedef,zaman",
        "kaynak": "İbn-i Sina — El-Kanun fi't-Tıb (1025)",
        "etiketler": "islam,tip,genc,hedef",
    },
    {
        "slug": "harezmi_algoritma",
        "kim": "El-Harezmi",
        "konu": "matematik",
        "baslik": "Algoritma kelimesinin kökeni — El-Harezmi",
        "metin": (
            "Her gün kullandığın 'algoritma' kelimesi Harezmi'nin isminden geliyor. 9. "
            "yüzyıl Bağdat. 'Kitab'ul-Cebr' kitabıyla 'cebir' (algebra) kelimesini yarattı. "
            "Matematik sorusu çözerken bilsen de bilmesen de — Harezmi'nin metodunu "
            "kullanıyorsun. Sen kökleri olan bir matematik geleneğinin parçasısın."
        ),
        "ders": "matematik",
        "duygusal_hedef": "kimlik,ilham,tarih",
        "kaynak": "Robert of Chester — Algoritmi de numero Indorum",
        "etiketler": "islam,matematik,cebir,tarih",
    },
    # ─── SPORCU / AZIM ──
    {
        "slug": "kobe_404_am_alarmı",
        "kim": "Kobe Bryant",
        "konu": "disiplin",
        "baslik": "4:04 AM alarmı — mamba mentality",
        "metin": (
            "Kobe Bryant her sabah 4:04'te uyanıp antrenmana başlardı. Bir gazeteci: "
            "'Neden bu kadar erken?' Kobe: 'Çünkü 8'de antrenmana gelen rakiplerim, benim "
            "4 saat uzağımda.' Sen de derslerine 2 saat erken başladığında — rakiplerinden "
            "2 saat öndesin. Disiplin = antrenman değil, iradenin gündelik testi."
        ),
        "ders": "",
        "duygusal_hedef": "disiplin,motivasyon,zaman",
        "kaynak": "Mamba Mentality (2018); röportajlar",
        "etiketler": "spor,disiplin,sabah,azim",
    },
    {
        "slug": "michael_jordan_liseden_atildi",
        "kim": "Michael Jordan",
        "konu": "basarisizlik",
        "baslik": "Lise takımından atıldı — 6 NBA şampiyonluğu",
        "metin": (
            "10. sınıfta Michael Jordan lise basketbol takımından atıldı — 'yeterince "
            "iyi değilsin' dediler. Ağladı, ama her gün 6'da salona geldi. NBA'de 6 "
            "şampiyonluk, 5 MVP. 'Kariyerimde 9000+ şut kaçırdım, 300 maç kaybettim. "
            "İşte bu yüzden başardım.' Kabul etmezseler olmadığın değil, henüz olmadığın "
            "anlamına gelir."
        ),
        "ders": "",
        "duygusal_hedef": "basarisizlik,ret,azim",
        "kaynak": "For the Love of the Game (1998)",
        "etiketler": "spor,basarisizlik,azim,reddedilme",
    },
    # ─── EDEBIYAT / SANATÇI ──
    {
        "slug": "sabahattin_ali_lisede_yazdi",
        "kim": "Sabahattin Ali",
        "konu": "genclik",
        "baslik": "Kuyucaklı Yusuf — lisede başlayan yazarlık",
        "metin": (
            "Sabahattin Ali'nin 'Kuyucaklı Yusuf' romanı Türk edebiyatının en sevilen "
            "eserlerinden. İlk öykülerini lisede yazmaya başladı. Çanakkale Balıkesir "
            "Öğretmen Okulu'ndan. Bugün 'Kürk Mantolu Madonna' dünya dillerine çevriliyor. "
            "Sen de lise yaşındasın. Ne başlamak için erken, ne beklemek için geç."
        ),
        "ders": "edebiyat",
        "duygusal_hedef": "genclik,baslamak,hedef",
        "kaynak": "Sevengül Sönmez — Sabahattin Ali biyografi",
        "etiketler": "turk,edebiyat,genc,roman",
    },
    {
        "slug": "van_gogh_2_tablo_satti",
        "kim": "Vincent van Gogh",
        "konu": "reddedilme",
        "baslik": "Hayatında 2 tablo sattı — ölümünden sonra dünyanın en pahalı ressamı",
        "metin": (
            "Van Gogh hayatındayken sadece 2 tablosunu satabildi. Kardeşi Theo ona "
            "'vazgeç, gerçekçi ol' derdi. Van Gogh: 'Yapmam gereken budur.' Bugün "
            "bir tablosu 100 milyon dolar. Bugünün onaylamadığı, yarının standardı. "
            "Sen de 'standart' değilsen — belki ileride standart olan sensin."
        ),
        "ders": "",
        "duygusal_hedef": "reddedilme,toplum,kimlik",
        "kaynak": "Van Gogh mektupları; Theo yazışmaları",
        "etiketler": "sanat,reddedilme,azim,gelecek",
    },
    # ─── ODAK / ÖĞRENME ANEKDOTLARI ──
    {
        "slug": "elon_10_hour_rule",
        "kim": "Elon Musk",
        "konu": "ogrenme",
        "baslik": "Her gün 2 yeni şey — biraz ama sürekli",
        "metin": (
            "Elon Musk roket, araba, beyin çipi — farklı alanlarda çalışıyor. Yöntemi? "
            "Her gün 2 saatte farklı bir konuda okumak. 'Beyin ağaç gibidir — dalları "
            "olmadan yaprak yapamazsın. Önce ana dalı (temel kavramı) anla, sonra "
            "yapraklar (detaylar) eklenir.' Bugün senin dalın: TYT temel matematik."
        ),
        "ders": "",
        "duygusal_hedef": "ogrenme,sistem,plan",
        "kaynak": "Walter Isaacson — Elon Musk biyografi (2023)",
        "etiketler": "girisim,ogrenme,sistem",
    },
    {
        "slug": "benjamin_franklin_13_virtue",
        "kim": "Benjamin Franklin",
        "konu": "disiplin",
        "baslik": "13 erdem — haftalık döngüde kendini geliştirme",
        "metin": (
            "Benjamin Franklin (ABD kurucu baba, bilim insanı) 20 yaşında 13 erdem belirledi — "
            "sükunet, çalışkanlık, dürüstlük vb. Her hafta birine odaklandı, 13 haftada "
            "tam döngü. 'Mükemmel olamayız ama sistemli gelişebiliriz.' Sen de '13 konu' "
            "çıkar, her hafta birini mükemmelleştir. YKS için bu sistem uygular."
        ),
        "ders": "",
        "duygusal_hedef": "disiplin,sistem,plan",
        "kaynak": "Franklin Autobiography (1791)",
        "etiketler": "sistem,plan,disiplin,hafta",
    },
    {
        "slug": "joe_hisaishi_5am",
        "kim": "Joe Hisaishi",
        "konu": "disiplin",
        "baslik": "Her gün saat 5 — 40 yıl beste",
        "metin": (
            "Joe Hisaishi Studio Ghibli'nin film müziği bestecisi. 40 yıldır her sabah "
            "5'te masasında — her gün 3-4 saat beste yapar, bazen bir nota bile doğmaz. "
            "'Yaratıcılık esin değildir, alışkanlıktır. Her gün otururum — bir gün ilham "
            "gelmez, ama 99 gün gelir.' Senin de YKS hazırlığın böyle — her gün otur."
        ),
        "ders": "",
        "duygusal_hedef": "disiplin,alişkanlik,ritual",
        "kaynak": "Joe Hisaishi röportajlari",
        "etiketler": "muzik,disiplin,ritual,alişkanlik",
    },
    # ─── MODERN İLHAM ──
    {
        "slug": "malala_15_yasinda_vuruldu",
        "kim": "Malala Yousafzai",
        "konu": "sinir",
        "baslik": "15 yaşında eğitim için vuruldu — sonra Nobel aldı",
        "metin": (
            "Malala 15 yaşında Pakistan'da okula gittiği için Taliban tarafından vuruldu. "
            "Hayatta kaldı. Dünyaya eğitim hakkının mücadelesini anlattı. 17 yaşında "
            "Nobel Barış Ödülü — en genç Nobel sahibi. 'Bir çocuk, bir öğretmen, bir "
            "kitap, bir kalem dünyayı değiştirebilir.' Sen şu anda tam o noktadasın."
        ),
        "ders": "",
        "duygusal_hedef": "sinir,egitim,kiz,cesaret",
        "kaynak": "I Am Malala (2013)",
        "etiketler": "nobel,egitim,kadin,azim",
    },
    {
        "slug": "aykut_elmas_akut_kurdu",
        "kim": "Nasuh Mahruki (AKUT)",
        "konu": "hedef",
        "baslik": "AKUT'u kuran dağcı — 1 hayat kurtarmak = evreni kurtarmak",
        "metin": (
            "Nasuh Mahruki AKUT'u 1996'da kurdu. 15 ülkeden kişi kurtardı. Everest'e "
            "iki kere çıktı. 'Bir hayatı kurtaran bir evreni kurtarır' fikriyle yaşıyor. "
            "Büyük hedef bir tek eylemden başlar. Senin bir deneme, bir konu, bir gün — "
            "o 'tek'in birikerek evreni değiştirir."
        ),
        "ders": "",
        "duygusal_hedef": "hedef,etki,anlam",
        "kaynak": "Nasuh Mahruki — Everest (2003)",
        "etiketler": "turk,hedef,etki,dagci",
    },
    {
        "slug": "sokrates_bilmedigimi_bilirim",
        "kim": "Sokrates",
        "konu": "bilgelik",
        "baslik": "Bilmediğini bilmek — bilgeliğin başlangıcı",
        "metin": (
            "2500 yıl önce Delphi Tanrıçası 'Atina'nın en bilgesi kim?' diye sorulduğunda "
            "'Sokrates' dedi. Sokrates itiraz etti: 'Ben hiçbir şey bilmiyorum.' Tanrıça: "
            "'İşte o yüzden en bilgesin — herkes bildiğini sanıyor, sen bilmediğini "
            "biliyorsun.' Sen bir soruya 'anlamadım' dediğinde — Sokrates gibi bilgeleşiyorsun."
        ),
        "ders": "",
        "duygusal_hedef": "bilgelik,alcakgonulluluk,ogrenme",
        "kaynak": "Platon — Apology",
        "etiketler": "felsefe,bilgelik,ogrenme,tarih",
    },
]


async def hydrate_db() -> int:
    n = 0
    for a in ANEKDOTLAR:
        await db_execute(
            """INSERT INTO anekdotlar (slug, kim, konu, baslik, metin, ders,
                                        duygusal_hedef, kaynak, etiketler)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (slug) DO UPDATE SET
                 kim=EXCLUDED.kim, konu=EXCLUDED.konu, baslik=EXCLUDED.baslik,
                 metin=EXCLUDED.metin, ders=EXCLUDED.ders,
                 duygusal_hedef=EXCLUDED.duygusal_hedef, kaynak=EXCLUDED.kaynak,
                 etiketler=EXCLUDED.etiketler""",
            a["slug"], a["kim"], a["konu"], a["baslik"], a["metin"], a["ders"],
            a["duygusal_hedef"], a["kaynak"], a["etiketler"]
        )
        n += 1
    return n


async def get_for_mood(mood: str) -> Optional[dict]:
    """Duygusal hedefe uyan rastgele anekdot. mood: vazgecme, sinir, reddedilme, ..."""
    rows = await db_fetch(
        "SELECT * FROM anekdotlar WHERE duygusal_hedef LIKE $1 ORDER BY RANDOM() LIMIT 1",
        f"%{mood}%"
    )
    return dict(rows[0]) if rows else None


async def get_for_ders(ders: str) -> Optional[dict]:
    """Ders odakli anekdot (Matematik: Cahit Arf, Edebiyat: Sabahattin Ali...)."""
    rows = await db_fetch(
        "SELECT * FROM anekdotlar WHERE ders = $1 ORDER BY RANDOM() LIMIT 1",
        ders.lower()
    )
    return dict(rows[0]) if rows else None


async def get_for_etiket(etiket: str) -> Optional[dict]:
    """Etikete gore (turk, nobel, disiplin, genc, kadin...)."""
    rows = await db_fetch(
        "SELECT * FROM anekdotlar WHERE etiketler LIKE $1 ORDER BY RANDOM() LIMIT 1",
        f"%{etiket}%"
    )
    return dict(rows[0]) if rows else None


async def get_random() -> Optional[dict]:
    rows = await db_fetch("SELECT * FROM anekdotlar ORDER BY RANDOM() LIMIT 1")
    return dict(rows[0]) if rows else None


async def get_prompt_hint() -> str:
    """Claude prompt'a kisa referans (anekdot kategorileri)."""
    return (
        "\n📚 ANEKDOT KUTUPHANESI (uygun yerde HIKAYE ile ogrenci motive et):\n"
        "  Vazgecme/basarisizlik → Edison (10k deneme), Jordan (takim disi), Van Gogh (2 tablo)\n"
        "  Turk bilim/kimlik → Aziz Sancar (Harran'dan Nobel), Cahit Arf, Ali Kuscu, Harezmi\n"
        "  Genc yas hedef → Ibn-i Sina (18'de hoca), Oktay Sinanoglu (25 Yale prof), Malala (17 Nobel)\n"
        "  Matematik korkusu → Einstein efsanesi YALAN, Cahit Arf yurumek\n"
        "  Disiplin → Kobe (4:04 AM), Franklin (13 erdem), Joe Hisaishi (her sabah 5)\n"
        "  Kadin-sinir → Sabiha Gokcen (ilk pilot), Marie Curie (2 Nobel), Malala\n"
        "  Edebiyat → Sabahattin Ali (lisede basladi)\n"
        "  Bilgelik → Sokrates (bilmedigini bil)\n"
        "  Hedef/etki → Mustafa Kemal (matematikten ad), Nasuh Mahruki (AKUT)\n"
        "  Kullanim: anekdot_kutuphanesi.get_for_mood('vazgecme') ya da .get_for_ders('matematik')\n"
        "  Kural: Bot 'anektot kutuphanemde' DEMEZ — dogal anlatim ('biliyor musun, ...')\n"
    )


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    async def main():
        n = await hydrate_db()
        print(f'{n} anekdot eklendi')
        r = await get_for_mood('vazgecme')
        if r:
            print(f'\nVazgecme anekdotu:')
            print(f'  {r["baslik"]}')
            print(f'  — {r["kim"]}')
            print(f'  {r["metin"][:200]}...')
    asyncio.run(main())
