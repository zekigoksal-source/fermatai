"""
Pedagoji V2 — 41 Kavram Seed Listesi (curated by Neo + Claude)
================================================================

Her seed:
  - slug: unique kod
  - baslik: Türkçe başlık
  - kategori: 8 kategoriden biri
  - kisaca: 1 cümle özet
  - core_facts: Cerebras üretiminde kullanılacak ÇEKİRDEK GERÇEKLER
  - kullanim_durumu: hangi öğrenci durumunda kullanılır
  - trigger_patterns: regex (hangi mesajda otomatik tetiklenir)
  - kaynak: doğrulanmış akademik kaynak
  - etiketler: arama
"""

KAVRAM_SEED = [
    # ═══════════════════════════════════════════════════════════
    # KATEGORİ: HAFIZA (5 kavram)
    # ═══════════════════════════════════════════════════════════
    {
        "slug": "spaced_repetition",
        "baslik": "Aralıklı Tekrar (Spaced Repetition)",
        "kategori": "HAFIZA",
        "kisaca": "Unutma eğrisi doğal, aralıklı tekrar kalıcılığı sağlar.",
        "core_facts": "Hermann Ebbinghaus (1885) kendi üzerinde 11.000+ anlamsız hece deneyi yaptı. 1 saat sonra %60 unutulur, ama aralıkla tekrar (1 gün, 3 gün, 1 hafta, 1 ay) kalıcılaştırır. Leitner sistemi (1972) bunu kart kutularıyla uygular. Anki ve SuperMemo bu prensibe dayanır.",
        "kullanim_durumu": "Öğrenci 'geçen ay öğrendiğimi unuttum' dedi → optimal aralık şeması ver",
        "trigger_patterns": r"unuttum|hatirlam[ıi]yorum|her seferinde bastan|tekrar|akl[ıi]mdan ucuyor",
        "kaynak": "Ebbinghaus (1885) — Über das Gedächtnis; Leitner (1972)",
        "etiketler": "hafiza,tekrar,unutma,plan",
    },
    {
        "slug": "retrieval_practice",
        "baslik": "Hatırlatma Pratiği (Retrieval Practice)",
        "kategori": "HAFIZA",
        "kisaca": "Test ederek öğrenme, sadece okumadan 2-3x daha kalıcı.",
        "core_facts": "Roediger & Karpicke (2006) Washington University deneyi: aynı süreyi okuyarak vs kendine test ederek geçirenler — test edenler 1 hafta sonra 2x daha çok hatırladı. 'Testing Effect' kanıtlandı. Aktif hatırlama hafıza yollarını güçlendirir.",
        "kullanim_durumu": "Öğrenci konu okuyor ama unutuyor → test çözmeye yönlendir",
        "trigger_patterns": r"sadece okuyorum|tekrar okuyorum|verim al[ıi]m[ıi]yorum|yine unuttum",
        "kaynak": "Roediger & Karpicke (2006) — Psychological Science; Karpicke & Blunt (2011)",
        "etiketler": "hafiza,test,aktif,bilim",
    },
    {
        "slug": "dual_coding",
        "baslik": "İkili Kodlama (Dual Coding)",
        "kategori": "HAFIZA",
        "kisaca": "Görsel + sözel birlikte = 2x kalıcılık.",
        "core_facts": "Allan Paivio (1971) İkili Kodlama Teorisi: beyin görsel ve sözel bilgiyi ayrı kanallarda işler. İkisini birleştirmek hafızayı güçlendirir. Mind map, Cornell notes, akış diyagramları, anımsatıcı resimler bu prensibin uygulamasıdır.",
        "kullanim_durumu": "Öğrenci 'tarih ezberleyemiyorum' / 'liste ezberi zor' → görsel + sözel önerisi",
        "trigger_patterns": r"ezberleyem[ıi]yorum|liste|tarih ezber|formul ezber|sema",
        "kaynak": "Paivio, A. (1971) — Imagery and Verbal Processes",
        "etiketler": "hafiza,gorsel,sema,not",
    },
    {
        "slug": "interleaving",
        "baslik": "Karıştırma Etkisi (Interleaving)",
        "kategori": "HAFIZA",
        "kisaca": "Aynı konuyu blok halinde değil, konuları karıştırarak çalış.",
        "core_facts": "Doug Rohrer & Kelli Taylor (2007) Univ South Florida: matematik öğrencileri 4 farklı problem türünü blok (AAAABBBB) vs karışık (ABABABAB) yapanları kıyasladılar. Karışık çalışanlar test sonrası 2x daha iyi performans gösterdi — başlangıçta zorlanır ama uzun vadede kazanır.",
        "kullanim_durumu": "Öğrenci 'aynı konudan 50 soru çözüp diğerine geçiyorum' → karıştırma stratejisi öner",
        "trigger_patterns": r"ayn[ıi] konu|blok|hep ayn[ıi] tip|cesitlilik yok",
        "kaynak": "Rohrer & Taylor (2007) — Instructional Science",
        "etiketler": "hafiza,bilim,calisma,strateji",
    },
    {
        "slug": "working_memory",
        "baslik": "Çalışma Belleği (Working Memory)",
        "kategori": "HAFIZA",
        "kisaca": "Aynı anda 7±2 bilgi parçası tutabilirsin — fazlası tıkar.",
        "core_facts": "Alan Baddeley (1974) Çalışma Belleği Modeli: fonolojik döngü (sözel) + görsel-mekansal taslak + merkezi yönetici. George Miller (1956) '7±2 sihirli sayı' çalışmasıyla beraber temel: aynı anda fazla bilgi yükleyince beyin tıkanır. 'Chunking' (parçalara bölme) çözüm.",
        "kullanim_durumu": "Öğrenci 3 dersi birden / fazla şeyi aynı anda hatırlamaya çalışıyor → chunking öner",
        "trigger_patterns": r"cok konu|3 ders|kafam tutmu[sş]|ayni anda|cok sey",
        "kaynak": "Baddeley (1974); Miller (1956) — Psychological Review",
        "etiketler": "hafiza,bilim,yuk,parca",
    },

    # ═══════════════════════════════════════════════════════════
    # KATEGORİ: MOTIVASYON (7 kavram)
    # ═══════════════════════════════════════════════════════════
    {
        "slug": "growth_mindset",
        "baslik": "Büyüme Zihniyeti (Growth Mindset)",
        "kategori": "MOTIVASYON",
        "kisaca": "Yetenek sabit değil, gelişir. 'Henüz' kelimesi sihirli anahtar.",
        "core_facts": "Carol Dweck (2006, Stanford) 30+ yıllık araştırma: 'sabit zihniyet' (yetenek doğuştan) vs 'büyüme zihniyeti' (gelişebilir). Çocuklara 'zekisin' yerine 'çabaladığın için başardın' diyenlerde uzun vadeli başarı 2x. Beyin plastisitesi bilimsel temel: her zorluk yeni nöral bağ.",
        "kullanim_durumu": "Öğrenci 'yapamıyorum / matematik yeteneğim yok' → 'henüz' reframe + plastisite",
        "trigger_patterns": r"yapam[ıi]yorum|beceremem|m[uü]mk[uü]n de[gğ]il|hi[cç] olmuyor|yetenek(?:siz)?",
        "kaynak": "Dweck, C. (2006) — Mindset: The New Psychology of Success",
        "etiketler": "motivasyon,ozguven,basarisizlik,zihniyet",
    },
    {
        "slug": "self_efficacy",
        "baslik": "Öz-Yeterlilik (Self-Efficacy)",
        "kategori": "MOTIVASYON",
        "kisaca": "'Yapabilirim' inancı performansın temel belirleyicisi.",
        "core_facts": "Albert Bandura (1977) Sosyal Bilişsel Teori. Öz-yeterlilik 4 kaynaktan beslenir: (1) Geçmiş başarılar, (2) Başkalarını gözlemlemek (vicarious), (3) Sözel ikna, (4) Fizyolojik durum. Öz-yeterlilik düşükse zorlukta vazgeçer; yüksekse ısrar eder. Akademik performansın en güçlü tahmincisi.",
        "kullanim_durumu": "Öğrenci 'başarılı olamayacağım' inancında → küçük başarı zinciri kur, görsel kanıt göster",
        "trigger_patterns": r"basaramayacam|kendime g[uü]venim|inanc[ıi]m yok|imkans[ıi]z",
        "kaynak": "Bandura (1977) — Self-Efficacy: Toward a Unifying Theory",
        "etiketler": "motivasyon,inanc,bilim,bandura",
    },
    {
        "slug": "grit",
        "baslik": "Azim (Grit)",
        "kategori": "MOTIVASYON",
        "kisaca": "Uzun vadeli hedef için tutku + dayanıklılığın birleşimi.",
        "core_facts": "Angela Duckworth (2007, Penn). West Point askeri akademiden Spelling Bee yarışmacısına 1000+ kişi araştırdı: IQ ve yetenekten daha güçlü tahmincide grit. 'Grit Scale' geliştirdi (12 soru). 'Yetenek + çaba = beceri. Beceri + çaba = başarı.' TED 14M görüntüleme.",
        "kullanim_durumu": "Öğrenci uzun vadede vazgeçme eğilimi gösteriyor → uzun vadeli hedef + günlük adım",
        "trigger_patterns": r"uzun vade|s[uü]rd[uü]r|y[ıi]ll[ıi]k hedef|uzun s[uü]reli|y[ıi]l(?:lar)?",
        "kaynak": "Duckworth, A. (2016) — Grit: The Power of Passion and Perseverance",
        "etiketler": "motivasyon,azim,uzun_vade,duckworth",
    },
    {
        "slug": "self_determination",
        "baslik": "Öz-Belirleme Kuramı (SDT)",
        "kategori": "MOTIVASYON",
        "kisaca": "İçsel motivasyon 3 ihtiyaçla beslenir: özerklik, yeterlilik, bağ.",
        "core_facts": "Edward Deci & Richard Ryan (1985, Rochester). 40+ yıllık araştırma: dış ödüller (para, not) içsel motivasyonu BOZAR. İçsel motivasyon 3 psikolojik ihtiyaçtan beslenir: (1) Özerklik = seçim hissi, (2) Yeterlilik = başarıyor olma, (3) İlişki = bağlılık. Bu 3'ü olan öğrenci dışarıdan zorlamaya muhtaç değil.",
        "kullanim_durumu": "Öğrenci 'ailem zorluyor / mecburum' diyor → özerklik soruları, iç ses bulma",
        "trigger_patterns": r"ailem zorlu|mecburum|kendi(?:m i[cç]in)? de[gğ]il|istemiyorum ama",
        "kaynak": "Deci & Ryan (1985) — Self-Determination Theory",
        "etiketler": "motivasyon,aile,hedef,ozerklik",
    },
    {
        "slug": "achievement_goal",
        "baslik": "Başarı Hedef Teorisi (Achievement Goal)",
        "kategori": "MOTIVASYON",
        "kisaca": "Mastery (öğrenmek için) hedef vs Performance (göstermek için) hedef.",
        "core_facts": "Carol Dweck & Andrew Elliot (1980-2000'ler). 2 yönelim: (1) Mastery = 'öğrenmek için çalışıyorum', (2) Performance = 'başkalarına göstermek/yenilmemek için'. Mastery yönelimli öğrenciler zorlukta vazgeçmez, performance yönelimli olanlar başarısızlıktan kaçar. Mastery long-term hedeflerde 2x avantajlı.",
        "kullanim_durumu": "Öğrenci 'sıralamam' / 'arkadaşlarımdan kötü' diyor → mastery'e yönlendir",
        "trigger_patterns": r"s[ıi]ralam|arkadaslar[ıi]m|baskalar[ıi]ndan|gostermek|yenilm",
        "kaynak": "Elliot & Dweck (2005) — Handbook of Competence and Motivation",
        "etiketler": "motivasyon,hedef,performans,bilim",
    },
    {
        "slug": "implementation_intention",
        "baslik": "Uygulama Niyeti (Implementation Intention)",
        "kategori": "MOTIVASYON",
        "kisaca": "'X olursa Y yaparım' formülü hedefe ulaşma şansını 2-3x artırır.",
        "core_facts": "Peter Gollwitzer (1999, NYU) meta-analiz: niyet → eylem dönüşümünde 'if-then' planları %35 daha etkili. Genel hedef ('daha çok çalışacağım') yerine spesifik plan ('saat 7'de masaya geçip matematik açacağım'). Beynin otopilot devresini aktifleştiriyor.",
        "kullanim_durumu": "Öğrenci 'çalışacağım' der ama uygulayamıyor → if-then formül",
        "trigger_patterns": r"yapacam ama|s[oö]z verdim|dene(?:di|me)|yine yapamad[ıi]m",
        "kaynak": "Gollwitzer (1999) — American Psychologist",
        "etiketler": "motivasyon,plan,uygulama,bilim",
    },
    {
        "slug": "intrinsic_extrinsic",
        "baslik": "İçsel vs Dışsal Motivasyon",
        "kategori": "MOTIVASYON",
        "kisaca": "İçinden gelen motivasyon kalıcı, dış ödül geçici.",
        "core_facts": "Deci (1971) klasik deneyi: çocuklara çizim hediye karşılığı yaptırılınca, ödül kalkınca daha az çiziyorlar. Dış ödül içsel motivasyonu söndürür. Edward Deci 'Why We Do What We Do' (1995) — kitabı temel kaynak. Para/not eğitimde geçici işe yarar ama uzun vadede zarar.",
        "kullanim_durumu": "Öğrenci sadece ödül için çalışıyor → içsel motivasyon arayışı",
        "trigger_patterns": r"para|hediye|odul|telefon i[cç]in|kazan(?:c|ç)",
        "kaynak": "Deci, E. (1971); Deci & Ryan (2000) — Contemporary Educational Psychology",
        "etiketler": "motivasyon,odul,ic,dis,bilim",
    },

    # ═══════════════════════════════════════════════════════════
    # KATEGORİ: ODAK (5 kavram)
    # ═══════════════════════════════════════════════════════════
    {
        "slug": "pomodoro",
        "baslik": "Pomodoro Tekniği",
        "kategori": "ODAK",
        "kisaca": "25 dakika odak + 5 dakika mola = sürdürülebilir çalışma.",
        "core_facts": "Francesco Cirillo (1980'ler, üniversite öğrencisiyken). Domates şeklinde mutfak zamanlayıcısıyla başladı (pomodoro = İtalyanca domates). 25 dk yoğun odak + 5 dk mola, 4 pomodoro sonrası 15-30 dk uzun mola. İnsan dikkati doğal döngüsel — sürekli değil. 30M+ uygulayıcı.",
        "kullanim_durumu": "Öğrenci 'odaklanamıyorum / 2 saat oturuyorum verim yok' → 25/5 ritmi",
        "trigger_patterns": r"odaklanam[ıi]yorum|s[uü]reli cal[ıi][sş]am[ıi]yorum|dikkat|verim d[uü][sş][uü]k|2 saat",
        "kaynak": "Cirillo, F. (2006) — The Pomodoro Technique",
        "etiketler": "odak,zaman,mola,disiplin",
    },
    {
        "slug": "flow",
        "baslik": "Akış (Flow)",
        "kategori": "ODAK",
        "kisaca": "Zorluk + yetenek dengesi = zaman durur, derin odak yaşanır.",
        "core_facts": "Mihaly Csíkszentmihályi (1975, Chicago). 30 yıllık nicel araştırma: sanatçı/sporcu/cerrahlarda 'optimal deneyim' anları gözlemledi. Koşullar: (1) Net hedef, (2) Anında geri bildirim, (3) Zorluk-yetenek dengesi (yetkinliğin hemen üstünde). Çok kolay = sıkılma, çok zor = kaygı. Tam ortada akış.",
        "kullanim_durumu": "Öğrenci 'sıkıcı' / 'çok zor' / 'zaman geçmiyor' → zorluk seviyesi kalibrasyonu",
        "trigger_patterns": r"s[ıi]k[ıi]c[ıi]|saat gecm[ıi]yor|motive olam[ıi]yorum|zevk alm[ıi]yorum|cok kolay",
        "kaynak": "Csíkszentmihályi, M. (1990) — Flow",
        "etiketler": "odak,akis,zorluk,motivasyon",
    },
    {
        "slug": "cognitive_load",
        "baslik": "Bilişsel Yük Kuramı (CLT)",
        "kategori": "ODAK",
        "kisaca": "Beyin sınırlı 7±2 parça tutar. Fazla yük = öğrenme durur.",
        "core_facts": "John Sweller (1988, New South Wales). 3 yük tipi: (1) İç yük = konunun zorluğu, (2) Dış yük = sunum kalitesi (kötü slaytlar fazla yük), (3) Öğretici yük = uzun belleğe transfer. Aynı anda fazla yön = beyin tıkanır. Tek seferde 1 kavram, üst üste ekle.",
        "kullanim_durumu": "Öğrenci 3 dersi birden / karmakarışık çalışıyor → tek kanal",
        "trigger_patterns": r"cok konu|birden fazla|kar[ıi][sş][ıi]k gidi[yi]or|kafam tutmu[sş]|3 ders",
        "kaynak": "Sweller, J. (1988) — Cognitive Science",
        "etiketler": "hafiza,yuk,odak,plan",
    },
    {
        "slug": "default_mode_network",
        "baslik": "Varsayılan Mod Ağı (DMN)",
        "kategori": "ODAK",
        "kisaca": "Beyin 'mola' verdiğinde aslında bağlantı kuruyor — duş anları!",
        "core_facts": "Marcus Raichle (2001, Washington Univ) fMRI keşfi: beyin pasif durumda (yürüyüş, duş, yataktan önce) DMN aktivasyonu yapar — yaratıcı bağlantılar burada kurulur. Eureka momentlerinin %72'si bu durumlarda gelir. Sürekli ekran/odak DMN'i bastırır.",
        "kullanim_durumu": "Öğrenci sürekli çalışıyor ama 'aha' anları gelmiyor → mola değeri",
        "trigger_patterns": r"hi[cç] anlam[ıi]yorum|kavrayam[ıi]yorum|kafam y[oğ]gun|mola",
        "kaynak": "Raichle (2001) — PNAS; Beaty et al. (2014)",
        "etiketler": "beyin,bilim,yaratici,mola",
    },
    {
        "slug": "deliberate_practice",
        "baslik": "Bilinçli Pratik (Deliberate Practice)",
        "kategori": "ODAK",
        "kisaca": "10K saat değil, doğru saat. Kalite > miktar.",
        "core_facts": "Anders Ericsson (1993, Florida State) keman ustaları çalışması. 10.000 saat efsanesi yanlış yorumlanır: önemli olan miktar DEĞİL, kalite. 3 unsur: (1) Spesifik zayıflığa odak, (2) Anında geri bildirim, (3) Konfor alanı dışı zorluk. 'Peak' (2016) kitabı detay verdi.",
        "kullanim_durumu": "Öğrenci 'günde 200 test çözüyorum ama puanım artmıyor' → kalite>miktar",
        "trigger_patterns": r"cok cal[ıi][sş][ıi]yorum|saatlerce|puan artm[ıi]yor|hep ayn[ıi]|verim",
        "kaynak": "Ericsson (1993); Ericsson & Pool (2016) — Peak",
        "etiketler": "calisma,verim,gelisim,pratik",
    },

    # ═══════════════════════════════════════════════════════════
    # KATEGORİ: STRES (5 kavram)
    # ═══════════════════════════════════════════════════════════
    {
        "slug": "yerkes_dodson",
        "baslik": "Yerkes-Dodson Yasası",
        "kategori": "STRES",
        "kisaca": "Optimal stres = optimal performans. Çok az = isteksizlik, çok fazla = donma.",
        "core_facts": "Robert Yerkes & John Dodson (1908, Harvard) fareler üzerinde elektrik şoku deneyi. Performans-uyarılma ilişkisi 'ters U' eğrisi: çok düşük stres = performans düşük, optimal stres = pik, çok yüksek stres = donma. Sınav öncesi hafif kaygı NORMAL VE FAYDALI.",
        "kullanim_durumu": "Öğrenci 'sınav korkusu' / 'panikledim' → stresi düşman değil hazırlık sinyali olarak çerçevele",
        "trigger_patterns": r"s[ıi]nav korkusu|panik|donup kald[ıi]m|stres",
        "kaynak": "Yerkes & Dodson (1908) — Journal of Comparative Neurology",
        "etiketler": "stres,performans,bilim,deney",
    },
    {
        "slug": "mindfulness",
        "baslik": "Mindfulness (Bilinçli Farkındalık)",
        "kategori": "STRES",
        "kisaca": "Şu ana yargılamadan dikkat = stresi azaltır, odağı güçlendirir.",
        "core_facts": "Jon Kabat-Zinn (1979, Massachusetts Tıp Fakültesi) Budist meditasyon tekniğini bilime entegre etti — MBSR (Mindfulness-Based Stress Reduction). 200+ klinik araştırma: anksiyete, depresyon, ağrı yönetiminde etkili. 8 hafta, günde 30 dk. 35.000+ tıp kuruluşunda uygulanıyor.",
        "kullanim_durumu": "Öğrenci 'kaygılıyım / aklım dağınık' → 5 dk nefes egzersizi",
        "trigger_patterns": r"kayg[ıi]l[ıi]y[ıi]m|nefesim daral|kalbim [cç]arp[ıi]yor|stres|sakin",
        "kaynak": "Kabat-Zinn (1990) — Full Catastrophe Living",
        "etiketler": "stres,nefes,zihin,bilim",
    },
    {
        "slug": "test_anxiety",
        "baslik": "Sınav Kaygısı (Test Anxiety)",
        "kategori": "STRES",
        "kisaca": "Sınavda donup kalmak — bilişsel + duygusal iki bileşen vardır.",
        "core_facts": "Liebert & Morris (1967) Sınav Kaygısı 2 bileşen: (1) Bilişsel ('başaramayacağım' kaygı düşünceleri çalışma belleğini meşgul eder), (2) Duygusal (titreme, terleme, mide bulantısı). Bilişsel daha zararlı. Çare: önceden hazırlık + bilişsel reframe + nefes.",
        "kullanim_durumu": "Sınav öncesi 'donup kaldım / unuttum' diyor → reframe + nefes + hazırlık",
        "trigger_patterns": r"unuttum hepsini|s[ıi]nav g[uü]n[uü] korkuyorum|panikledim|donup",
        "kaynak": "Liebert & Morris (1967) — Psychological Reports; Cassady (2010)",
        "etiketler": "stres,sinav,kaygi,bilim",
    },
    {
        "slug": "self_compassion",
        "baslik": "Öz-Şefkat (Self-Compassion)",
        "kategori": "STRES",
        "kisaca": "Hata yaptığında kendine yargı değil şefkat — performansı artırır.",
        "core_facts": "Kristin Neff (2003, Texas Austin) 3 bileşen: (1) Öz-iyilik (kendine yargı yerine sıcaklık), (2) Ortak insanlık ('herkes hata yapar, yalnız değilim'), (3) Mindfulness (duygulara takılmadan farkındalık). Öz-eleştiriden daha güçlü motivasyon — utanç kaçınma, şefkat ısrarı doğurur.",
        "kullanim_durumu": "Öğrenci 'aptal mıyım, hep böyle' / kendi-eleştiri yüksek → şefkat dilini öğret",
        "trigger_patterns": r"aptal m[ıi]y[ıi]m|kendime k[ıi]z[ıi]yorum|nefret ediyorum|salakça",
        "kaynak": "Neff (2003) — Self and Identity",
        "etiketler": "stres,sefkat,kendi,bilim",
    },
    {
        "slug": "stress_reframe",
        "baslik": "Stres Yeniden Çerçeveleme",
        "kategori": "STRES",
        "kisaca": "Stres düşman değil, hazırlık sinyali. Reframe performansı artırır.",
        "core_facts": "Jeremy Jamieson (2010-2018, Rochester) deneyleri: 'stresi enerji olarak gör' bilgisi verilen öğrenciler GRE/quiz testlerinde stres semptomları aynı seviyedeydi ama performans %10-20 yükseldi. Kelly McGonigal 'The Upside of Stress' (2015) popülerleştirdi.",
        "kullanim_durumu": "Öğrenci 'stresliyim, başaramayacağım' → 'stres = beynim hazır' reframe",
        "trigger_patterns": r"streslyim|kayg[ıi]l[ıi]|titriyorum|nefesim",
        "kaynak": "Jamieson et al. (2010-2018) — JEP General; McGonigal (2015)",
        "etiketler": "stres,reframe,bilim,modern",
    },

    # ═══════════════════════════════════════════════════════════
    # KATEGORİ: DISIPLIN (5 kavram)
    # ═══════════════════════════════════════════════════════════
    {
        "slug": "atomic_habits",
        "baslik": "Atomik Alışkanlıklar (%1 Kuralı)",
        "kategori": "DISIPLIN",
        "kisaca": "Günlük %1 gelişim 1 yılda 37x birikir.",
        "core_facts": "James Clear (2018) bestseller. 4 yasa: (1) Açık yap (cue), (2) Çekici yap (craving), (3) Kolay yap (response), (4) Tatmin edici yap (reward). Habit stacking ('X'ten sonra Y yapacağım'), environment design (ortamı kolaylaştır), identity-based habits ('ben düzenli çalışan biriyim').",
        "kullanim_durumu": "Öğrenci 'düzensizim, alışkanlık yapamıyorum' → küçük başla, ortam kur",
        "trigger_patterns": r"d[uü]zensizim|al[ıi]kanl[ıi]k|d[uü]zen|kuram[ıi]yorum|s[ıi]rl[ıi]",
        "kaynak": "Clear, J. (2018) — Atomic Habits",
        "etiketler": "alişkanlik,sistem,modern,kucuk",
    },
    {
        "slug": "habit_loop",
        "baslik": "Alışkanlık Döngüsü (Cue-Routine-Reward)",
        "kategori": "DISIPLIN",
        "kisaca": "Her alışkanlık 3 parça: tetikleyici → eylem → ödül.",
        "core_facts": "Charles Duhigg (2012) 'The Power of Habit'. Beyinde alışkanlıklar bazal ganglion'da kodlanır — bir kez kurulduğunda otomatiktir. Cue: ortam/duygu (örn: saat 7), Routine: davranış (oturup matematik), Reward: tatmin (rahatlık, ilerleme hissi). Eski alışkanlığı silemez ama replace edebilirsin.",
        "kullanim_durumu": "Öğrenci kötü alışkanlık (telefon) bırakamıyor → tetikleyici tanımla, replace et",
        "trigger_patterns": r"telefonu b[ıi]rak[ıi]m|sosyal medya|al[ıi]kanl[ıi]k(?:tan)?|kotu d[oö]ng",
        "kaynak": "Duhigg (2012) — The Power of Habit",
        "etiketler": "alişkanlik,beyin,donguler,modern",
    },
    {
        "slug": "two_minute_rule",
        "baslik": "2 Dakika Kuralı",
        "kategori": "DISIPLIN",
        "kisaca": "Her alışkanlığı '2 dakikada yapılabilir' versiyonuna indirge.",
        "core_facts": "James Clear & David Allen birlikte popülerleştirdi. Yeni alışkanlıkta beynin direnci ilk dakikalarda gelir. '30 dk koşacağım' yerine 'spor ayakkabısını giyeceğim' başla. 2 dakikada yapılabilir mini hedef → momentum yaratır → genişletilebilir. Erteleme tedavisi.",
        "kullanim_durumu": "Öğrenci başlamayı erteliyor / koca hedef korkutuyor → 2 dk versiyonu",
        "trigger_patterns": r"ba[sş]layam[ıi]yorum|erteliyorum|kocaman g[oö]r[uü]nce|cok zor ba[sş]lam",
        "kaynak": "Clear (2018); Allen (2001) — Getting Things Done",
        "etiketler": "alişkanlik,kucuk,baslama,modern",
    },
    {
        "slug": "procrastination",
        "baslik": "Erteleme Psikolojisi (Procrastination)",
        "kategori": "DISIPLIN",
        "kisaca": "Erteleme tembellik değil, duygu yönetimi sorunudur.",
        "core_facts": "Tim Pychyl (2013, Carleton Univ) ve Fuschia Sirois (Sheffield): erteleme = 'şu an iyi hissedeyim, gelecek bana ait değil' duygu kaçışı. Çözüm: (1) Görevi BAŞLAT (5 dk yeter), (2) Mükemmellik aramayı bırak, (3) Kendine şefkat (öz-eleştiri ertelemeyi kötüleştirir).",
        "kullanim_durumu": "Öğrenci 'sürekli erteliyorum / tembelim' diyor → tembellik değil duygu kaçışı çerçeveleme",
        "trigger_patterns": r"erteliyorum|tembelim|yarin yapar[ıi]m|son g[uü]ne|ya[zr][iı]n",
        "kaynak": "Pychyl (2013) — Solving the Procrastination Puzzle; Sirois (2014)",
        "etiketler": "erteleme,duygu,bilim,modern",
    },
    {
        "slug": "kaizen",
        "baslik": "Kaizen (Sürekli İyileştirme)",
        "kategori": "DISIPLIN",
        "kisaca": "Japon felsefesi: küçük sürekli iyileştirme = devasa birikim.",
        "core_facts": "Japonya'da WWII sonrası endüstriyel verimlilik için Edwards Deming + Toyota geliştirdi. 'Kai' (değişim) + 'Zen' (iyi) = sürekli iyi-değişim. Toyota Üretim Sistemi = kaizen + just-in-time. Bireysel uygulama: her gün küçük bir şey iyileştir (Robert Maurer 'One Small Step' 2014).",
        "kullanim_durumu": "Öğrenci büyük dönüşüm istiyor ama yapamıyor → küçük adımlar felsefesi",
        "trigger_patterns": r"b[uü]y[uü]k d[oö]n[uü][sş][uü]m|tamamen de[gğ]i[sş]|sif[ıi]rdan ba[sş]la|her [sş]ey",
        "kaynak": "Imai (1986) — Kaizen; Maurer (2014) — One Small Step",
        "etiketler": "alişkanlik,japon,felsefe,sistem",
    },

    # ═══════════════════════════════════════════════════════════
    # KATEGORİ: KIMLIK (4 kavram)
    # ═══════════════════════════════════════════════════════════
    {
        "slug": "ikigai",
        "baslik": "Ikigai (Yaşam Anlamı)",
        "kategori": "KIMLIK",
        "kisaca": "Sevdiğin + iyi olduğun + dünya gereksinimi + geçim = ikigai.",
        "core_facts": "Japon felsefesi (Ki = canlı, Gai = değer). Hector Garcia & Francesc Miralles (2016) Okinawa uzun yaşam kitabıyla popülerleşti. 4 daire kesişimi: (1) Sevdiğin, (2) İyi olduğun, (3) Dünyanın ihtiyaç duyduğu, (4) Para kazanabileceğin. Bu 4 kesişim = ikigai = yaşam anlamı.",
        "kullanim_durumu": "Öğrenci 'ne istiyorum bilmiyorum, anlamsız' → ikigai 4 sorusu",
        "trigger_patterns": r"ne istedi[gğ]imi|anlams[ıi]z|hedef yok|ne i[cş]e yarayacak",
        "kaynak": "Garcia & Miralles (2016) — Ikigai: The Japanese Secret",
        "etiketler": "kimlik,anlam,japon,hedef",
    },
    {
        "slug": "perma",
        "baslik": "PERMA (Mutluluk 5'lemesi)",
        "kategori": "KIMLIK",
        "kisaca": "Kalıcı mutluluk: Pozitif duygu + Bağlılık + İlişki + Anlam + Başarı.",
        "core_facts": "Martin Seligman (2011, Penn) Pozitif Psikoloji kurucusu. PERMA = (1) Positive emotion = keyifli anlar, (2) Engagement = akış halinde aktivite, (3) Relationships = sosyal bağ, (4) Meaning = kendinden büyük amaca hizmet, (5) Accomplishment = anlamlı başarı. Hepsini denge önemli.",
        "kullanim_durumu": "Öğrenci 'mutsuzum, ne yapsam' → PERMA 5 boyut tara",
        "trigger_patterns": r"mutsuz|moralim|ne yapsam|hayat anlams[ıi]z|s[oö]nm[uü][sş]",
        "kaynak": "Seligman (2011) — Flourish",
        "etiketler": "kimlik,mutluluk,bilim,seligman",
    },
    {
        "slug": "stoicism",
        "baslik": "Stoacılık (Kontrol Edilebilir vs Edilemez)",
        "kategori": "KIMLIK",
        "kisaca": "Kontrol edemediğine değil, edebileceğine odaklan.",
        "core_facts": "Antik Yunan/Roma felsefesi (MÖ 300'den itibaren). Epiktetos, Marcus Aurelius, Seneca. Temel ilke: hayatta 2 kategori vardır — (1) Kontrolün altında olanlar (düşüncelerin, eylemlerin, tepkilerin), (2) Olmayanlar (başkalarının davranışı, sonuçlar, geçmiş). Enerjini 1'e ver. Modern CBT'nin atası.",
        "kullanim_durumu": "Öğrenci 'sınav sonucu / başkalarının düşüncesi' kaygısı → kontrol matrisi",
        "trigger_patterns": r"ne d[uü][sş][uü]n[uü]r|sonu[cç] korkutu|kontrol(?:s[uü]z)?|olcaklar[ıi]m",
        "kaynak": "Epiktetos — Enchiridion; Marcus Aurelius — Meditasyonlar",
        "etiketler": "kimlik,felsefe,kontrol,antik",
    },
    {
        "slug": "logotherapy",
        "baslik": "Logoterapi (Anlam Terapisi)",
        "kategori": "KIMLIK",
        "kisaca": "İnsan anlam arayan varlıktır — zorlukta bile anlam bulunur.",
        "core_facts": "Viktor Frankl (1946) Auschwitz sonrası kurdu. 3. Viyana psikoterapi okulu (Freud + Adler sonrası). Temel tez: insanı motive eden zevk değil ANLAM. En kötü şartlarda bile 'neden' bulan hayatta kalır ('Auschwitz'te anlamı olan kalbinin kırılmadığı görülürdü'). 12M+ kitap satışı.",
        "kullanim_durumu": "Öğrenci 'neden çalışıyorum, anlamı ne' → kişisel anlam keşfi",
        "trigger_patterns": r"anlam[ıi]?|neden cal[ıi][sş]|amac yok|ni[cç]in|ne i[cş]e yar",
        "kaynak": "Frankl (1946) — Man's Search for Meaning",
        "etiketler": "kimlik,anlam,psikoloji,trajik",
    },

    # ═══════════════════════════════════════════════════════════
    # KATEGORİ: OGRENME (6 kavram)
    # ═══════════════════════════════════════════════════════════
    {
        "slug": "feynman",
        "baslik": "Feynman Tekniği",
        "kategori": "OGRENME",
        "kisaca": "Konuyu 12 yaşına anlatabiliyorsan gerçekten biliyorsun.",
        "core_facts": "Richard Feynman (Nobelli fizikçi 1965). 4 adım: (1) Konuyu seç, (2) Basit dille anlat (sanki 12 yaşına), (3) Boşlukları farket, (4) Sadeleştir + analoji ekle. Cornell, Caltech derslerinde kullandı. Scott Young 'Ultralearning' (2019) modernize etti. Öz-değerlendirmede güçlü.",
        "kullanim_durumu": "Öğrenci 'anlamadım, karışık' → 'BANA anlat, nerede takıldın görelim'",
        "trigger_patterns": r"anlam[ıi]yorum|zorlan[ıi]yorum|kar[ıi][sş][ıi]k|kafam kar[ıi][sş][ıi]k",
        "kaynak": "Feynman (1985) — Surely You're Joking; Young (2019) — Ultralearning",
        "etiketler": "ogrenme,teknik,kavrama,ezber",
    },
    {
        "slug": "bloom_taksonomi",
        "baslik": "Bloom Taksonomisi",
        "kategori": "OGRENME",
        "kisaca": "Öğrenme 6 aşamalı: hatırla → anla → uygula → analiz → değerlendir → yarat.",
        "core_facts": "Benjamin Bloom (1956, Chicago) ve revizyon Anderson & Krathwohl (2001). Bilgi piramidi: L1 Hatırla → L2 Anla → L3 Uygula → L4 Analiz Et → L5 Değerlendir → L6 Yarat. YKS soruları çoğu L3-L5. Sadece formül ezberlemek L1, soruyu çözmek L3-L4. Öğrenme derinliği bu hiyerarşide ölçülür.",
        "kullanim_durumu": "Öğrenci 'ezberledim biliyorum' diyor → L3 sorusu sor",
        "trigger_patterns": r"ezberled[ıi]m|s[ıi]naviya haz[ıi]r|anlad[ıi]m san[ıi]yordum|bilirim ama",
        "kaynak": "Bloom (1956); Anderson & Krathwohl (2001)",
        "etiketler": "sinav,analiz,tekrar,degerlendirme",
    },
    {
        "slug": "zpd",
        "baslik": "Yakınsak Gelişim Alanı (ZPD)",
        "kategori": "OGRENME",
        "kisaca": "Tek başına yapamadığın ama rehberle yapabildiğin = gerçek öğrenme alanı.",
        "core_facts": "Lev Vygotsky (1934, Sovyet psikolog). 38 yaşında verem öldü, çalışmaları 1962'de keşfedildi. ZPD: (1) Bildiğin (kolay) + (2) Bilmediğin (imkansız) arasında 'rehberle yapılabilir' bir alan. Öğretmen/AI/akran 'scaffolding' (iskele) verir, öğrenci geçer, sonra iskele kalkar.",
        "kullanim_durumu": "Öğrenci 'çok zor, yapamıyorum' → 'birlikte yapalım, ilk 2 adımı ben göstereyim'",
        "trigger_patterns": r"yaln[ıi]z basar[ıi]lm[ıi]yor|yard[ıi]ma ihtiyacim|ornekle|birlikte",
        "kaynak": "Vygotsky (1934) — Thought and Language",
        "etiketler": "ogretme,rehber,yardim,scaffolding",
    },
    {
        "slug": "metacognition",
        "baslik": "Üstbiliş (Metacognition)",
        "kategori": "OGRENME",
        "kisaca": "Öğrenme üzerine düşünme — 'nasıl öğreniyorum' sorusu öğrenmenin anahtarı.",
        "core_facts": "John Flavell (1979, Stanford). 2 katman: (1) Bilgi katmanı, (2) Süreci izleme/yönetme katmanı. Üstbilişsel sorular: 'Hangi konuyu daha iyi anladım? Hangi yöntem benimle uyumlu? Yanlışları neden yapıyorum?' Zimmerman (2002) öz-düzenlemeli öğrenme modeli geliştirdi.",
        "kullanim_durumu": "Deneme sonrası analiz, yanlış kategorilemesi, kendi öğrenme tarzını fark etme",
        "trigger_patterns": r"neden yanl[ıi][sş]|hata yap[ıi]yorum|deneme analiz|anlamiyorum nas[ıi]l",
        "kaynak": "Flavell (1979); Zimmerman (2002) — Theory Into Practice",
        "etiketler": "analiz,ustbilisel,hata,oz-degerlendirme",
    },
    {
        "slug": "elaborative_interrogation",
        "baslik": "Detaylandırıcı Sorgulama (Elaborative Interrogation)",
        "kategori": "OGRENME",
        "kisaca": "Her bilgi için 'neden böyle?' sor — kalıcılık 2x artar.",
        "core_facts": "Pressley et al. (1992, Maryland) deneyleri: 'fil hortumla su içer' bilgisi karşısında 'NEDEN hortumla?' sorusu cevapla beraber kodlandığında %50 daha kalıcı. 'Why-questions' önceki bilgiyle bağlantı kurmaya zorlar — derin işleme. Self-explanation (Chi 1989) benzer prensiple çalışır.",
        "kullanim_durumu": "Öğrenci formül/tarih ezberliyor ama anlamıyor → 'neden böyle' sorgulama",
        "trigger_patterns": r"ezber|nas[ıi]l hat[ıi]rlay[ıi]m|formul ezberi|tarih ezber",
        "kaynak": "Pressley et al. (1992); Chi (1989) — Cognitive Science",
        "etiketler": "ogrenme,sorgu,derin,bilim",
    },
    {
        "slug": "multiple_intelligences",
        "baslik": "Çoklu Zekâ Teorisi (Multiple Intelligences)",
        "kategori": "OGRENME",
        "kisaca": "Tek IQ değil, 8 farklı zekâ türü var — herkes bir alanda güçlü.",
        "core_facts": "Howard Gardner (1983, Harvard) 'Frames of Mind'. 8 zekâ: (1) Dilsel, (2) Mantıksal-Matematiksel, (3) Mekansal, (4) Müziksel, (5) Bedensel-Kinestetik, (6) Kişiler-arası, (7) Kişisel, (8) Doğacı. Eğitim sisteminin sadece 1-2'sini ölçtüğü eleştirisi. Notlandırma çok zekâya yetersiz.",
        "kullanim_durumu": "Öğrenci 'matematikte iyi değilim, başarısızım' → diğer zekâ alanları kıyas",
        "trigger_patterns": r"yetenek(?:siz)?|matematik yetenek|tek alan|ben(?:im)? alanim degil",
        "kaynak": "Gardner (1983) — Frames of Mind",
        "etiketler": "ogrenme,zeka,gardner,degerlendirme",
    },

    # ═══════════════════════════════════════════════════════════
    # KATEGORİ: AZIM (4 kavram)
    # ═══════════════════════════════════════════════════════════
    {
        "slug": "learned_optimism",
        "baslik": "Öğrenilmiş İyimserlik (Learned Optimism)",
        "kategori": "AZIM",
        "kisaca": "Açıklama tarzın geri toparlanmayı belirler — 'kalıcı/geçici' ayrımı.",
        "core_facts": "Martin Seligman (1990, Penn). Köpekler üzerinde 'öğrenilmiş çaresizlik' deneyinden iyimserliğin de öğrenilebileceğini keşfetti. 3 boyut: (1) Sürekli mi geçici mi? (2) Genel mi özel? (3) Kişisel mi dışsal? İyimserler kötüyü 'geçici/özel/dışsal', iyiyi 'kalıcı/genel/kişisel' olarak çerçeveler.",
        "kullanim_durumu": "Öğrenci 'her zaman böyle / her şeyde başarısızım' → 3 boyut reframe",
        "trigger_patterns": r"her zaman|her sey|asla olmaz|surekli ayn[ıi]",
        "kaynak": "Seligman (1990) — Learned Optimism",
        "etiketler": "azim,iyimserlik,bilim,reframe",
    },
    {
        "slug": "learned_helplessness",
        "baslik": "Öğrenilmiş Çaresizlik",
        "kategori": "AZIM",
        "kisaca": "Tekrarlayan başarısızlıkta 'ne yapsam olmaz' inancı yerleşir.",
        "core_facts": "Martin Seligman & Steven Maier (1967) köpek deneyi: kaçışı engellenen şok karşısında köpekler kaçabilir hale gelse bile pasif kalıyor — 'çaresizlik öğrendik'. İnsanda klinik depresyon modeli haline geldi. Kırma yolu: küçük başarı zincirleri, kontrol hissi geri kazanma.",
        "kullanim_durumu": "Öğrenci uzun süre 'ne yapsam olmuyor' moduna girmiş → küçük kontrol noktaları",
        "trigger_patterns": r"ne yapsam|ne fayda|kaderim|olmaz benden|adildim",
        "kaynak": "Seligman & Maier (1967) — JEP",
        "etiketler": "azim,bilim,depresyon,seligman",
    },
    {
        "slug": "post_traumatic_growth",
        "baslik": "Travma Sonrası Büyüme (Post-Traumatic Growth)",
        "kategori": "AZIM",
        "kisaca": "Travma sadece zarar vermez — bazılarında derin gelişim doğurur.",
        "core_facts": "Tedeschi & Calhoun (1995, North Carolina). Travma yaşayanların %50-70'i 5 alanda büyüme yaşıyor: (1) Kişisel güç, (2) İlişkiler, (3) Hayata yeni takdir, (4) Yeni olasılıklar, (5) Manevi gelişim. Stephen Joseph (2011) 'What Doesn't Kill Us' kitabıyla popülerleştirdi. Kırılgan değil dayanıklı.",
        "kullanim_durumu": "Öğrenci büyük başarısızlık/kayıp sonrası 'yıkıldım' → büyüme potansiyeli",
        "trigger_patterns": r"y[ıi]k[ıi]ld[ıi]m|kaybettim|kayb[ıi]m|toparlanam[ıi]yorum|kotu g[uü]n",
        "kaynak": "Tedeschi & Calhoun (1995); Joseph (2011) — What Doesn't Kill Us",
        "etiketler": "azim,buyume,trauma,bilim",
    },
    {
        "slug": "resilience",
        "baslik": "Dayanıklılık (Resilience)",
        "kategori": "AZIM",
        "kisaca": "Geri toparlanma yeteneği — öğrenilebilir, doğuştan değil.",
        "core_facts": "Ann Masten (2001, Minnesota) 30 yıllık araştırma: dayanıklılık 'sıradan büyü' — özel kişilerde değil, herkeste oluşabilir. 4 unsur: (1) Aile/sosyal destek, (2) Problem-çözme becerisi, (3) Öz-düzenleme, (4) Anlam/inanç. American Psychological Association: dayanıklılık eğitimle gelişir.",
        "kullanim_durumu": "Öğrenci geri toparlanamıyor → dayanıklılık 4 unsuru üzerinden plan",
        "trigger_patterns": r"geri d[oö]nem|toparlanam[ıi]yorum|d[uü][sş]t[uü]m|kalkam[ıi]yorum",
        "kaynak": "Masten (2001) — American Psychologist; APA Resilience Guide",
        "etiketler": "azim,bilim,toparlama,modern",
    },
]


def get_kategori_dagilim() -> dict:
    from collections import Counter
    return dict(Counter(k["kategori"] for k in KAVRAM_SEED))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    dist = get_kategori_dagilim()
    total = sum(dist.values())
    print(f"📊 Kavram SEED dağılımı: {total} adet")
    print()
    for kat, cnt in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {kat:12s} → {cnt:2d} kavram")
    print()
    print(f"✅ Hedef: 41, Mevcut: {total}")
