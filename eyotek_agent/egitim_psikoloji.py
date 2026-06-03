"""
FermatAI — Eğitim Psikolojisi Modülü (22.1n-neo FAZ 2.1)
==========================================================

Öğrenci mesaj patternlerini psikolojik açıdan analiz eder ve uygun müdahale
stratejisi önerir. Bot bu öneriyi direkt kullanıcıya vermez — Claude'un
system prompt'una inject edilir, Claude doğal dille aktarır.

TESPIT EDILEN DURUMLAR:
  - sinav_kaygisi   → CBT reframe + 4-7-8 nefes
  - motivasyon_dusuk → values clarification + small wins
  - ogrenme_bloku   → öğrenilmiş çaresizlik tespiti
  - perfeksiyonizm  → 'yeterince iyi' yaklaşımı
  - kiyas_travması  → akran baskısı destek

KULLANIM:
  from egitim_psikoloji import detect_state, get_intervention
  state = detect_state("kaygılıyım panik olacağım")
  # → {"durum": "sinav_kaygisi", "confidence": 0.85, ...}
  interv = await get_intervention(state["durum"])
  # → müdahale metni (CBT, nefes, mindfulness)
"""
from __future__ import annotations

import re
from typing import Optional


# ─── TESPIT PATTERN'LERİ ─────────────────────────────────────────────────────

_PATTERNS = {
    "sinav_kaygisi": {
        "keywords": [
            r"kaygi|kayg[iı]l[iı]|tedirginim|end[iı][sş]eli|panik|panik yapaca",
            r"nefes(im)?\s*(daral|yok|alam|kesil)",
            r"kalb[iı]m\s*(h[iı]zl|carpa|sik)",
            r"korkarim|korkuyorum|bastan savam",
            r"mahvolur?um|batacagim|berbat",
            r"sinav[iı]m\s*(yakin|var|geliyor).*stres",
            r"panik at[a]?k|stress?(liyim|im)?|terliyorum",
            # Oturum Mentenans (21 Nisan 14:28) — gergin/uyku/stres varyasyonlari
            r"\bgergin(im)?\b|geril(dim|iyorum)",
            r"uyku(m)?\s*(kac|yok|bozuk)|uyuyamiyorum",
            r"\bstres(liyim|li|im)?\b",
        ],
        "confidence_boost": r"kac\s*gun|yaklas[iı]yor|yakin|yetiseme|\bsinav\b",
    },
    "motivasyon_dusuk": {
        "keywords": [
            r"motive de[gğ]ilim|motivasyon(um)?\s*(yok|d[uü]s[uü]k)",
            r"istemiyorum|bosuna|anlamsi[zs]",
            r"neden calis|niye\s*u[gğ]ra[sş]",
            r"uskum|s[iı]k[iı]ld[iı]m.*ders|b[iı]ktim",
            r"pes etmek|pes ettim|vazgec|b[iı]rakmak",
            r"moralim bozuk|mutsuzum|umutsuzum",
            # Oturum Mentenans (21 Nisan 14:28)
            r"motivasyon(um)?\s*d[uü]s[uü]k",
            r"caliamiyorum|[cç]al[iı][sş]amiyorum",
            r"hic?bir\s*seyi\s*(yap|ist|[cç]al)",
            # 25.56 (Neo denetim — canlı test: "motivasyonum bitti" kaçıyordu):
            r"motivasyon(um)?\s*(bitti|t[uü]kendi|kalmad[iı]|s[iı]f[iı]r)",
            r"ba[sş]layam[iı]yorum|ba[sş]layabilmiyorum|ba[sş]layam[iı]yor",
            r"yapamayaca[gğ][iı]m|yapamam\b|beceremiyorum",
            r"hic?bir\s*[sş]ey(e|i)\s*(ba[sş]la|yapa|ist)",
            r"enerjim\s*yok|yorgunum.*ders|tak[iı]ts[iı]z",
            r"i[cç]im\s*ge[cç]miyor|gaz[iı]m\s*yok|hevesim\s*(yok|kalmad)",
        ],
        "confidence_boost": r"ger[cç]ekten|artik|surekli|hic|galiba",
    },
    "ogrenme_bloku": {
        "keywords": [
            r"calisamiyorum|oturam[iı]yorum.*ders",
            r"neyi\s*[cç]alisaca[gğ][iı]m[iı]\s*bilmiyorum",
            r"hic bir\s*(sey ise|konu)\s*yaramiyor",
            r"yapt[iı]kl?ar[iı]m.*fayda\s*etmiyor",
            r"ogrendim\s*ama\s*unutuyorum",
            r"kafam.*tutmuyor",
            # Oturum Mentenans (21 Nisan 14:28) — karis/durdu varyasyonlari
            r"kafam?\s*(karis|karı[sş]|durdu|tak[iı]ld)",
            r"\bkonuyu\s*anlam(iyorum|ad[iı]m)\b",
            r"anlam(iyor|adim)(u|um)?.*konuyu",
        ],
        "confidence_boost": r"haftalardir|aylardir|s[uü]rekli",
    },
    "perfeksiyonizm": {
        "keywords": [
            r"mukemmel\s*ol(acak|ma|mal)|her\s*s[eyı]i?\s*dogru",
            r"kusursuz|bir hata\s*yap",
            r"her\s*soruyu.*[cç]ozmeliy",
            r"yuzde 100|tam puan|hepsini",
            r"yeterince iyi\s*de[gğ]il|yeterli\s*olmayacak",
            r"bir\s*tek\s*yanlis.*mahvol",
            # Oturum Mentenans (21 Nisan 14:28)
            r"her\s*[sş]ey(i)?\s*m[uü]kemmel",
            r"yoksa\s*olmaz|olmazsa\s*olmaz",
        ],
        "confidence_boost": r"her zaman|surekli|devaml[iı]",
    },
    "kiyas_travmasi": {
        "keywords": [
            r"(damla|ecrin|taha|ali|zeynep|ayse|can|mehmet).*(benden|daha\s*iyi)",
            r"arkada[sş]lar[iı]m.*(iyi|yuksek|gecer|kiyasl)",
            r"herkes.*(tyt|ayt).*net(i|ler[iı])n",
            r"sinifimdaki(ler)?.*(benden|yuksek)",
            r"b[iı]r ben.*(yapamiyorum|gerideyim)",
            r"rakibim|rakiplerim",
            # Oturum Mentenans (21 Nisan 14:28) — kiyas fiili
            r"k[iı]yaslam(a|ay|iyorum)|k[iı]yasl[iı]yorum",
            r"daha\s*k[oö]t[uü](y[uü]m)?",
        ],
        "confidence_boost": r"su kadar|karsila[sş]t[iı]r|oysa|hep",
    },
}


def detect_state(message: str) -> Optional[dict]:
    """Mesajda tespit edilen psikolojik durumu don.

    Returns:
        {"durum": str, "confidence": float, "matched_keywords": list} veya None
    """
    if not message or len(message) < 5:
        return None
    msg = message.lower()

    best = None
    best_score = 0.0

    for durum, cfg in _PATTERNS.items():
        score = 0.0
        matched = []
        for pat in cfg["keywords"]:
            if re.search(pat, msg, re.IGNORECASE):
                score += 0.3
                matched.append(pat[:30])
        # Boost
        boost_pat = cfg.get("confidence_boost")
        if boost_pat and re.search(boost_pat, msg, re.IGNORECASE):
            score += 0.2
        score = min(1.0, score)

        if score > best_score:
            best_score = score
            best = {"durum": durum, "confidence": round(score, 2),
                     "matched_keywords": matched[:3]}

    if best and best["confidence"] >= 0.3:
        return best
    return None


# ─── MÜDAHALE STRATEJİLERİ (15 protokol: 5 durum × 3 strateji) ──────────────
# Oturum Mentenans (21 Nisan 18:45) — Neo talimatı: "intervention content basic,
# CBT/ACT/MBSR referansları ile derinleştir."
# Her durum için 3 katman:
#   HEMEN        — İlk 30 saniye içinde yapılabilir (fizyolojik/zihinsel quick win)
#   KISA VADE    — Bu hafta (somut aksiyon, habit tracking)
#   UZUN VADE    — Derin reframe (literatür temelli, ömürlük)

_INTERVENTIONS = {
    "sinav_kaygisi": {
        "kisa_aciklama": "Sınav kaygısı — CBT + fizyolojik düzenleme",
        "pedagoji_kavram": "growth_mindset, flow, yerkes_dodson",
        "sablon_slug": "sinav_kaygisi",
        "protokoller": {
            "HEMEN": (
                "ACIL MÜDAHALE (30 sn — öğrenci hemen uygulayabilir):\n"
                "1) *4-7-8 Nefes*: 4 sn burundan AL, 7 sn TUT, 8 sn ağızdan VER. 4 tur.\n"
                "   → Parasempatik sinir sistemini aktive eder, kortizol düşer.\n"
                "2) *5-4-3-2-1 grounding* (MBSR): 5 şey gör, 4 ses duy, 3 şey dokun, "
                "2 koku, 1 tat. Amigdalayı yavaşlatır.\n"
                "3) *Normalizasyon*: 'Kaygı yanlış değil — beyninin umursadığı sinyali.'\n"
                "4) Örnek başlangıç: 'Şu an içinde ne hissediyorsun — kalp, nefes, kas?'"
            ),
            "KISA_VADE": (
                "BU HAFTA (günlük 15 dk, 7 gün takip):\n"
                "1) *CBT Düşünce Kaydı*: Her kaygı anında yaz →\n"
                "   a) Otomatik düşünce ('mahvolacağım')\n"
                "   b) Kanıt ne diyor? (son 3 deneme notun, hazırlığın)\n"
                "   c) Yeni çerçeve ('zorlanacağım ama hazırlandım')\n"
                "2) *Yerkes-Dodson ayarı*: Kaygı 0 = umursamıyor, 10 = felç. 3-4 ideal. "
                "Öğrenciye 'şu an 1-10 kaç?' sor, 7+ ise nefes + 5 dk mola.\n"
                "3) *Sınav simülasyonu*: Evde gerçek sınav koşulu (zamanlı, sessiz, "
                "telefonsuz). Amigdalayı 'tanıdık' koşullandırır.\n"
                "4) *Uyku hijyeni*: 7-8 saat zorunlu. Kaygı uykusuzlukla artar."
            ),
            "UZUN_VADE": (
                "DERİN REFRAME (aylar — kimlik katmanında değişim):\n"
                "1) *ACT — Değer bazlı eylem*: Kaygı olsun, ama değerin (öğrenme, "
                "gelişim) doğrultusunda *eyleme devam et*. 'Kaygıyı yok edeyim sonra "
                "çalışırım' tuzak. Kaygıyla çalışmayı öğren.\n"
                "2) *Growth mindset (Dweck)*: Zeka sabit değil, gelişiyor. Hata = veri. "
                "'Başaramazsam ben kötüyüm' → 'Başaramadım, ne öğrendim?'\n"
                "3) *Anekdot — Feynman*: Nobel ödüllü fizikçi sınavlarda kaygılıydı. "
                "Çözüm: 'Notları almış gibi davranmak' — zihinsel hazırlık.\n"
                "4) *Sınav = ölçüm, değer değil*: Notun sen değilsin. Kimliğini "
                "performansla birleştirme."
            ),
        },
    },
    "motivasyon_dusuk": {
        "kisa_aciklama": "Motivasyon kaybı — SDT + ACT + small wins",
        "pedagoji_kavram": "self_determination, flow, values_clarification",
        "sablon_slug": "motivasyon_dusuk",
        "protokoller": {
            "HEMEN": (
                "ACIL MÜDAHALE (şimdi — 1 dakika):\n"
                "1) *Duyguyu adlandır* (ACT): 'Demek ki içinde bir yorgunluk, bir boşluk "
                "var. Bu normal, değer verdiğin için böyle.'\n"
                "2) *5-dakika kuralı*: 'Sadece 5 dakika aç kitabı. Bitir, sonra bırak. "
                "Sadece 5 dakika.' — eylemsizlik kırılırsa momentum gelir.\n"
                "3) *Vücut kontrolü*: Su iç, yüzünü yıka, 10 şınav. Zihinden değil "
                "bedenden başla.\n"
                "4) *Kendi sesini sor*: 'YKS'yi neden istiyorsun, kendi cümlenle? "
                "Ailen için değil, senin için.' Hemen cevap veremezse OK."
            ),
            "KISA_VADE": (
                "BU HAFTA (mini habit stacking):\n"
                "1) *Small Wins (Amabile)*: Bugün 1 konu, yarın 1 konu. Her gün check. "
                "Beynin 'bitirme' dopamini salgılar, momentum artar.\n"
                "2) *Values clarification* (SDT): 3 değerini yaz (aile, özgürlük, "
                "merak). Çalışma bu değerlere nasıl hizmet ediyor? Bağla.\n"
                "3) *Habit anchor*: 'Kahvaltıdan sonra' (tetik) → '10 dk test çöz' "
                "(yeni alışkanlık). Mevcut rutinlere çek.\n"
                "4) *Çevresel tasarım*: Kitabı masaya koy, telefonu başka odaya. "
                "İrade yerine sürtünme azaltma.\n"
                "5) Eğer 'hiçbir şey anlam ifade etmiyor' 2+ hafta → rehber ögretmen. "
                "Anhedonia (zevk alamama) crisis indicator."
            ),
            "UZUN_VADE": (
                "DERİN REFRAME (3+ ay):\n"
                "1) *Intrinsic vs extrinsic (Deci-Ryan)*: Dış baskıdan (aile, öğretmen) "
                "içe geçiş. Özerklik + yeterlik + bağlanma = gerçek motivasyon.\n"
                "2) *Flow state (Csikszentmihalyi)*: Zorluk/yetenek dengesi. Çok kolay "
                "→ sıkıcı, çok zor → kaygı. Orta → akış. Düzeyine uygun sorular seç.\n"
                "3) *Purpose (Frankl - Logoterapi)*: 'Niye yaşıyorum?' sorusunun "
                "cevabı hayat enerjisidir. YKS bu sorunun bir aracı mı, yoksa "
                "amaç mı olmuş? Araç olması sağlıklı.\n"
                "4) *Anekdot — Kobe Bryant*: 'Her sabah 4'te basket antrenmanı. Neden? "
                "Çünkü seviyorum.' İç motivasyon > dış baskı, her zaman."
            ),
        },
    },
    "ogrenme_bloku": {
        "kisa_aciklama": "Öğrenme bloğu — Öğrenilmiş çaresizlik (Seligman) + ZPD",
        "pedagoji_kavram": "pomodoro, flow, zpd, learned_helplessness",
        "sablon_slug": None,
        "protokoller": {
            "HEMEN": (
                "ACIL MÜDAHALE (blok anında — 2 dk):\n"
                "1) *Spesifikleştir*: 'Hangi konu? Hangi saat? Hangi ortam?' Genel "
                "'çalışamıyorum' → spesifik 'bu matematik sorusunda takıldım'.\n"
                "2) *Mini win*: 'En kolay sorusu hangisi? Sadece onu yap.' İlk başarı "
                "'öğrenilmiş çaresizlik'i kırar.\n"
                "3) *Kontext değiştir*: 5 dk yürü, yer değiştir, su iç. Beynin "
                "reset olur.\n"
                "4) *Kağıt-kalem kuralı*: Ekrandan değil, kağıda yaz. Bilişsel yük azalır."
            ),
            "KISA_VADE": (
                "BU HAFTA (sistematik çözüm):\n"
                "1) *Pomodoro 25+5*: 25 dk yoğun + 5 dk mola. 4 tur sonra 15 dk uzun "
                "mola. Dikkat süresini kasla.\n"
                "2) *ZPD (Vygotsky)*: Yakın gelişim bölgesi. Şu an yapabildiğinle "
                "yapamadığın arası soru çöz. Çok kolay = sıkılırsın, çok zor = blok.\n"
                "3) *Feynman tekniği*: Konuyu 10 yaşındaki bir çocuğa anlatırmış gibi "
                "yazı yaz. Bilginin eksik olduğu noktalar ortaya çıkar.\n"
                "4) *Spaced repetition*: 1 gün, 3 gün, 7 gün, 14 gün aralıklarla "
                "tekrar. Unutulma eğrisini kır (Ebbinghaus).\n"
                "5) *Habit stacking*: 'Öğleden sonra dönüşte' (tetik) → '20 dk matematik'"
            ),
            "UZUN_VADE": (
                "DERİN REFRAME (özgüven yapılandırma):\n"
                "1) *Cognitive Load Theory (Sweller)*: Çalışma belleği limitli (7±2). "
                "Aşırı yükleme → blok. Konuyu parçala (chunking), her parça 1 kavram.\n"
                "2) *Metacognition*: 'Nasıl öğreniyorum?' farkındalığı. Öğrenme "
                "tarzını (VARK) bul — görsel mi, işitsel mi? Kendi yönteminle çalış.\n"
                "3) *Attribution theory (Weiner)*: 'Başaramadım çünkü ZEKİ DEĞİLİM' "
                "yerine 'Başaramadım çünkü YÖNTEM YANLIŞ olabilir'. İç→dış, sabit→değişken.\n"
                "4) *Anekdot — Edison*: 'Başarısız olmadım, ampulü yapmayan 10.000 yol "
                "buldum.' Her 'blok' bir öğrenme verisi."
            ),
        },
    },
    "perfeksiyonizm": {
        "kisa_aciklama": "Mükemmeliyetçilik — 'Yeterince iyi' reframe + Kaizen",
        "pedagoji_kavram": "bloom_taksonomi, growth_mindset, kaizen",
        "sablon_slug": "perfeksiyonizm",
        "protokoller": {
            "HEMEN": (
                "ACIL MÜDAHALE (şu anda — 30 sn):\n"
                "1) *İkilem tuzağını göster*: 'Ya %100 yap, ya hiç yap' — bu bir "
                "yanılgı. Orta yol var: *%75 yeterince iyi*.\n"
                "2) *Pomodoro yöntemi*: 'Bu soruyu 5 dakikada yap, sonra geç.' "
                "Süre kısıtı → mükemmel olamaz, bitmesi gerek.\n"
                "3) *İlk taslak berbat olsun* (Anne Lamott): 'Kötü taslak yaz, sonra "
                "iyileştir.' İçsel editörü sustur.\n"
                "4) *Normalleştir*: 'Şu an hissettiğin baskı, birçok başarılının "
                "yaşadığı duygu.'"
            ),
            "KISA_VADE": (
                "BU HAFTA (mükemmeliyet detoxu):\n"
                "1) *Hata kota sistemi*: Günde 3 hata yapma hedefi. 'Hata = öğrenme' "
                "reframe. Hatasız gün = yeterince zorlanmıyorsun demek.\n"
                "2) *Kaizen (Toyota)*: Günlük %1 gelişim. 100 gün sonra 100x değil, "
                "2.7x iyi olursun (1.01^100). Büyük atılım değil, sürekli ufak adım.\n"
                "3) *Good enough protocol*: Ödev/deneme bitir SONRA kontrol et. "
                "Kontrol ederken değiştirme dürtüsünü 3 dakika bekletme — bu dürtü "
                "%50 gücünü kaybeder.\n"
                "4) *Kişisel standart VS gerçek standart*: Öğretmen hangi puanla "
                "üniversite veriyor? O sınırın üstünde 'yeterince iyi'. Daha fazlası "
                "stres, daha azı risk."
            ),
            "UZUN_VADE": (
                "DERİN REFRAME (kimlik katmanı):\n"
                "1) *Brené Brown — kusur araştırması*: Mükemmeliyetçilik öz-koruma "
                "kalkanı, başarı formülü değil. 'Ya yetersiz olursam?' korkusundan "
                "kaçış.\n"
                "2) *Growth vs Fixed Mindset (Dweck)*: 'Ben mükemmeliyetçiyim' = "
                "sabit kimlik. 'Bazen mükemmeliyet tuzağına düşüyorum, öğreniyorum' "
                "= gelişim kimliği.\n"
                "3) *Bloom Taksonomisi*: L1 hatırlama → L6 yaratma. Her seviyede %100 "
                "olmak imkansız. L3 uygulama %75 yeterli, L6'ya çıkarken %50.\n"
                "4) *Anekdot — Van Gogh*: Hayatı boyunca 2 tablo sattı. Bugün en pahalı "
                "ressam. Dönemin 'standart' değil, süreç ve otantiklik önemli.\n"
                "5) *Sabahattin Ali*: 'Yeter ki başlasın, kusurlu başlasın ama başlasın.'"
            ),
        },
    },
    "kiyas_travmasi": {
        "kisa_aciklama": "Akran kıyası — Kendi yolu + social comparison theory",
        "pedagoji_kavram": "growth_mindset, self_determination, social_comparison",
        "sablon_slug": "kiyas_travmasi",
        "protokoller": {
            "HEMEN": (
                "ACIL MÜDAHALE (kıyas anı — 1 dk):\n"
                "1) *Normalleştir*: 'Kıyas insan refleksi, utanacak bir şey yok. "
                "Avcı-toplayıcı beynimiz sürü içinde pozisyon arıyor.'\n"
                "2) *Instagram analojisi*: 'Arkadaşının highlight reel'i, senin behind "
                "the scenes'inle kıyaslanmaz.'\n"
                "3) *Üç kişiyle yaz*: 'Benden iyi olan 1 kişi, benimle aynı 1 kişi, "
                "benden az olan 1 kişi.' Sıralama göreli — sen ortadaki bir gerçeksin.\n"
                "4) *Kişisel süreç checkpoint*: 'Geçen ay bu konudan kaç alıyordun? "
                "Şimdi kaç? Kendi eğrin önemli.'"
            ),
            "KISA_VADE": (
                "BU HAFTA (sağlıklı kıyas):\n"
                "1) *Downward comparison bypass*: 'Daha kötüsünü aramaya çalışma, "
                "özgüven ziyan olur. Yatay veya yukarı kıyas daha yararlı AMA kendi "
                "seviyenden yakın.'\n"
                "2) *Self-compassion (Neff)*: Kendine şu soruyu sor — 'En yakın "
                "arkadaşım bu durumda olsa ona ne derdim?' Kendine de aynı şefkat.\n"
                "3) *Ara başarı grafiği*: Son 5 denemedeki NET trendini çiz. Yukarı "
                "gidiyorsa 'Benim eğrim var' de. Rakibin hızından BAĞIMSIZ.\n"
                "4) *Çevre düzenleme*: WhatsApp sınıf grubunda kıyas tetikleyici "
                "konuşmalar → sessize al. Kendine alan yarat."
            ),
            "UZUN_VADE": (
                "DERİN REFRAME (Rakip yeniden tanımı):\n"
                "1) *Gerçek rakip yeniden tanımla*: 'Rakibin 3 ay önceki sen. Onunla "
                "yarış, diğerlerini rakip görme.' Kendinle yarış sürdürülebilir, "
                "diğeriyle tükenir.\n"
                "2) *Identity based goals (James Clear)*: 'Birinci olmak' dış hedef, "
                "'Gelişen öğrenci kimliğine sahip olmak' iç kimlik. Kimliğe dayalı "
                "hedef kıyastan etkilenmez.\n"
                "3) *Sosyal karşılaştırma teorisi (Festinger)*: Upward comparison "
                "motive eder AMA sadece ulaşılabilir hedefle. Damla 90 net yapıyorsa "
                "sen 30'da → kıyas zararlı. 45-55 arası biriyle kıyas yararlı.\n"
                "4) *Anekdot — Jordan & Kobe*: 'Kendinden iyi biriyle yarışırken "
                "motive olursun AMA hedefin onu geçmek değil, kendi tavanını "
                "bulmaktır.'\n"
                "5) *Vygotsky ZPD*: Biraz ileride biriyle çalışmak (peer tutor) "
                "gelişim sağlar AMA uzak seviyedekiyle kıyas travma yaratır."
            ),
        },
    },
}


def _flatten_protokoller(durum_cfg: dict) -> str:
    """3 protokol katmanını tek metne çevir (Claude inject için)."""
    p = durum_cfg.get("protokoller", {})
    parts = []
    if p.get("HEMEN"):
        parts.append("🚨 HEMEN:\n" + p["HEMEN"])
    if p.get("KISA_VADE"):
        parts.append("\n📅 KISA VADE:\n" + p["KISA_VADE"])
    if p.get("UZUN_VADE"):
        parts.append("\n🌱 UZUN VADE:\n" + p["UZUN_VADE"])
    return "\n".join(parts)


async def get_intervention(durum: str, katman: str = "") -> Optional[dict]:
    """Belirtilen duruma uygun müdahale bilgisini dön.

    Args:
        durum: 'sinav_kaygisi', 'motivasyon_dusuk', 'ogrenme_bloku',
               'perfeksiyonizm', 'kiyas_travmasi'
        katman: Opsiyonel — 'HEMEN' | 'KISA_VADE' | 'UZUN_VADE' | ''
                Bos veya gecersizse 3 katman birlestirilir.

    Returns: dict with keys:
        - kisa_aciklama
        - pedagoji_kavram
        - sablon_slug
        - strateji_claude_icin (flatten string — Claude prompt'a inject icin)
        - protokoller (raw 3-layer dict)
    """
    cfg = _INTERVENTIONS.get(durum)
    if not cfg:
        return None
    # Backward compat: strateji_claude_icin anahtarını flatten ile üret
    katman = (katman or "").upper().replace(" ", "_")
    if katman in ("HEMEN", "KISA_VADE", "UZUN_VADE"):
        strateji = cfg["protokoller"].get(katman, "")
    else:
        strateji = _flatten_protokoller(cfg)
    return {
        "kisa_aciklama": cfg["kisa_aciklama"],
        "pedagoji_kavram": cfg["pedagoji_kavram"],
        "sablon_slug": cfg["sablon_slug"],
        "strateji_claude_icin": strateji,
        "protokoller": cfg["protokoller"],
    }


def get_prompt_hint() -> str:
    """Claude system_prompt'a kısa referans."""
    return (
        "\n🧠 EGITIM PSIKOLOJISI MUDAHALELERI (detect_state → intervention):\n"
        "  Mesajda tespit patternleri varsa, uygun strateji uygula:\n"
        "  - SINAV_KAYGISI → 4-7-8 nefes + CBT reframe + normalleştir\n"
        "  - MOTIVASYON_DUSUK → SDT values clarification + small wins + 'kendi sesi'\n"
        "  - OGRENME_BLOKU → Seligman ogrenilmis caresizlik; spesifik trigger bul\n"
        "  - PERFEKSIYONIZM → 'yeterince iyi' + Van Gogh + Kaizen\n"
        "  - KIYAS_TRAVMASI → gerçek rakip = 3 ay önceki sen; Instagram analoji\n"
        "  KRIZ SINYALI (3+ hafta ogrenme bloku, pes etme ifadesi, bos geliyor) → "
        "rehberlik ogretmene yonlendir (direkt 'sen rehbere git' DEME, 'konusabilecegin "
        "biri gerekiyor' tarzi nazik oneri)."
    )


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    tests = [
        "kaygılıyım panik olacağım sınav yaklaşıyor",
        "motivasyonum yok hiç istemiyorum boşuna geliyor",
        "herkes benden daha iyi Damla 90 net yapıyor ben 45",
        "her şey mükemmel olmalı bir hata yaparsam mahvolurum",
        "çalışamıyorum günlerdir oturamıyorum ne çalışacağımı bilmiyorum",
    ]
    async def main():
        for t in tests:
            s = detect_state(t)
            print(f'\n"{t}"')
            if s:
                print(f'  → {s["durum"]} (conf: {s["confidence"]})')
                intervention = await get_intervention(s["durum"])
                if intervention:
                    print(f'  → {intervention["kisa_aciklama"]}')
    asyncio.run(main())
