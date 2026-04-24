"""
FermatAI — Öğretmen/Öğrenci/Veli Üçgen Modeli (22.1n-neo EKSTRA)
==================================================================

Neo vizyonu: Bot sadece öğrenciyle değil, öğretmen ve veliyle de
PEDAGOJİK ORTAK olarak konuşur. Eğitim literatürü temelli öneriler verir.

AKTIVITELER:
  - build_ogretmen_brief(soz_no) — öğretmene pedagojik öneri
  - build_veli_rehberlik(soz_no, tema) — veliye eğitim psikolojisi rehberi

KULLANIM:
  Öğretmen "Damla hakkında öneri var mı?" → build_ogretmen_brief(Damla.soz_no)
  Veli "Çocuğum çalışmıyor" → build_veli_rehberlik(cocuk.soz_no, "motivasyon")
"""
from __future__ import annotations

from typing import Optional
from db_pool import db_fetch, db_fetchrow


async def build_ogretmen_brief(soz_no: int) -> dict:
    """Öğretmene özel pedagojik brief — öğrenci hakkında DURUMA özel öneri.

    Çıktı Claude'a inject edilir, öğretmen okur.
    """
    try:
        soz_no = int(soz_no)
    except:
        return {"error": "gecersiz soz_no"}

    # Öğrenci bilgileri
    ogr = await db_fetchrow(
        "SELECT full_name, class_name, program FROM students WHERE soz_no::int = $1",
        soz_no
    )
    if not ogr:
        return {"error": f"Ogrenci bulunamadi: {soz_no}"}

    isim = ogr["full_name"]
    sinif = ogr["class_name"]

    # Son denemeler trend
    trend = await db_fetch(
        """SELECT exam_date, toplam FROM student_exams
           WHERE soz_no = $1 AND exam_type = 'TYT' AND toplam > 0
           ORDER BY exam_date DESC LIMIT 5""",
        soz_no
    )

    # Zayıf konular
    zayif = await db_fetch(
        """SELECT ders, konu FROM student_topic_tracker
           WHERE soz_no = $1
             AND sinav_hata_yuzdesi < 40
             AND (tamamlandi IS NULL OR tamamlandi = FALSE)
           ORDER BY sinav_hata_yuzdesi ASC LIMIT 5""",
        soz_no
    )

    # Devamsızlık
    devamsiz = await db_fetchrow(
        "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1", soz_no
    )

    # Kişiselleştirme profili (VARK + MBTI + engeller)
    profil = None
    try:
        from kisisellestirme import get_profile
        profil = await get_profile(soz_no)
    except Exception:
        pass

    # Sentiment (son 7 gün)
    import json as _j
    negatif_sinyal = await db_fetchrow(
        """SELECT COUNT(*) AS n FROM student_insights
           WHERE soz_no = $1
             AND created_at > NOW() - INTERVAL '7 days'
             AND insight_type IN ('sentiment_negative','sentiment_stressed','sentiment_crisis')""",
        soz_no
    )

    # Pedagojik öneri mantığı
    oneriler = []

    if trend and len(trend) >= 2:
        son_net = float(trend[0]["toplam"] or 0)
        onceki_net = float(trend[1]["toplam"] or 0)
        fark = son_net - onceki_net
        if fark <= -5:
            oneriler.append({
                "tema": "Büyüme Zihniyeti (Dweck)",
                "gozlem": f"Son deneme {son_net}net, önceki {onceki_net}net — {abs(fark):.1f} net düşüş.",
                "oneri": (
                    f"Öğrenciyle 'HENÜZ' konusuna değinmek faydalı — "
                    f"düşüş genellikle 'ben bu dersi yapamıyorum' hissi yaratır. "
                    f"Görüşmede hedef sonuç DEĞİL, süreç: 'bu hafta neyi farklı yaptın?'"
                ),
            })
        elif fark >= 5:
            oneriler.append({
                "tema": "Pekiştirme (Kaizen)",
                "gozlem": f"Son deneme +{fark:.1f} artış.",
                "oneri": (
                    f"{isim} yüksek trendde. Ödül değil, PATTERN KAVRAMA şart: "
                    f"'Nasıl başardın?' sorusu — süreklilik için öğrencinin kendi metodunu "
                    f"anlaması gerek (metakognisyon)."
                ),
            })

    if zayif and len(zayif) >= 3:
        konular = ", ".join(f"{r['ders']}/{r['konu'][:20]}" for r in zayif[:3])
        oneriler.append({
            "tema": "Bilişsel Yük Kuramı (CLT)",
            "gozlem": f"{len(zayif)} zayıf konu var: {konular}",
            "oneri": (
                "Tüm zayıf konuları aynı anda çözmek beyni yorar (Sweller CLT). "
                "Tek etütte 1-2 konu, üst üste eklenerek inşa. ZPD'de (Vygotsky) ilk "
                "adımı birlikte yapın, sonraki adımları öğrenciye bırakın (scaffold)."
            ),
        })

    if devamsiz and float(devamsiz["toplam_saat"] or 0) > 100:
        oneriler.append({
            "tema": "Devamsızlık Sinyali",
            "gozlem": f"Toplam devamsızlık: {devamsiz['toplam_saat']} saat.",
            "oneri": (
                "Devamsızlık genellikle AKADEMİK değil, DUYGUSAL. Neden mi: kaygı, "
                "kıyas travması, motivasyon düşüklüğü, aile. Yargılamayan bir soru "
                "faydalı: 'Seni buraya getiren ne, seni burada tutmayan ne?'"
            ),
        })

    if negatif_sinyal and int(negatif_sinyal["n"]) >= 3:
        oneriler.append({
            "tema": "Psikolojik Uyarı",
            "gozlem": f"Son 7 gün {negatif_sinyal['n']} negatif sinyal (kaygı/stres)",
            "oneri": (
                "Öğrenci psikolojik açıdan zor bir dönemde. Rehber öğretmenle koordinasyon "
                "faydalı olabilir. Akademik baskıyı şimdilik azaltın — MOTIVASYON DÖNGÜSÜ "
                "kırılmış olabilir, önce güven, sonra performans (SDT)."
            ),
        })

    # VARK tercihi
    if profil and profil.get("vark_dominant"):
        v = profil["vark_dominant"]
        vark_oneri = {
            "visual":       "Öğrenci görsel öğreniyor — şema, grafik, harita kullanın.",
            "auditory":     "Öğrenci işitsel — sözlü açıklama, podcast, grup tartışması.",
            "reading":      "Öğrenci okuma odaklı — yazılı özet, liste, madde madde not.",
            "kinesthetic":  "Öğrenci yaparak öğreniyor — pratik soru, deney, role-play.",
        }.get(v)
        if vark_oneri:
            oneriler.append({
                "tema": "Öğrenme Stili (VARK)",
                "gozlem": f"Dominant stil: {v}",
                "oneri": vark_oneri,
            })

    if not oneriler:
        oneriler.append({
            "tema": "Genel Durum",
            "gozlem": "Kırmızı bayrak yok.",
            "oneri": f"{isim} şu an istikrarlı. Haftalık check-in yeterli.",
        })

    return {
        "basarili": True,
        "ogrenci": {"soz_no": soz_no, "ad": isim, "sinif": sinif},
        "pedagojik_oneriler": oneriler,
        "ogretmen_icin_not": (
            "Bu öneriler eğitim bilimleri literatürüne dayalı. Öğrenciyle konuşurken "
            "doğal dille kullanın, 'Dweck kuramı der ki' gibi akademik üslup yerine "
            "'öğrencimizin şu an ihtiyacı olan...' gibi pratik çerçeveleyin."
        ),
    }


async def build_veli_rehberlik(soz_no: int, tema: str = "genel") -> dict:
    """Veliye eğitim psikolojisi temelli rehberlik metni uret.

    tema: 'motivasyon' | 'kaygi' | 'calisma' | 'ekran' | 'iletisim' | 'genel'
    """
    try:
        soz_no = int(soz_no)
    except:
        return {"error": "gecersiz soz_no"}

    ogr = await db_fetchrow(
        "SELECT full_name, class_name FROM students WHERE soz_no::int = $1", soz_no
    )
    if not ogr:
        return {"error": "Ogrenci bulunamadi"}

    isim = ogr["full_name"].split()[0]
    sinif = ogr["class_name"]

    # Tema bazli rehberlik
    rehberlikler = {
        "motivasyon": {
            "baslik": "Çocuğumun motivasyonu düşük",
            "literatur": "Self-Determination Theory (Deci & Ryan)",
            "rehberlik": (
                f"{isim} motivasyon düşüklüğü yaşıyor olabilir — 15-17 yaş dönemi "
                f"klasik bir durum. Araştırmalara göre iç motivasyon 3 ihtiyaçla beslenir:\n\n"
                f"1) **Özerklik**: Çocuğunuza 'Ne çalışacağını sen seç' deyin — baskı "
                f"ters etki yaratır. '{isim} bu hafta hangi dersi ilerlettin?' soru biçimi.\n\n"
                f"2) **Yeterlilik**: Küçük başarıları kutlayın. 'Dün 20 soru, bugün 22' "
                f"— minik ilerlemeler iç güven yaratır.\n\n"
                f"3) **İlişki**: Notları konuşmak yerine gününü sorun. 'Nasıldı bugün?' "
                f"'Neye güldün?' gibi. Bağ kurulunca çalışma kendiliğinden gelir.\n\n"
                f"*Önemli: 'Ailen yüzünden' yapan çocuk bir süre sonra bırakır. Kendisi "
                f"için yapan devam eder.*"
            ),
        },
        "kaygi": {
            "baslik": "Çocuğum sınav kaygısı yaşıyor",
            "literatur": "Yerkes-Dodson + CBT (Cognitive Behavioral)",
            "rehberlik": (
                f"{isim}'ın kaygısı normal — aslında hazırlığı önemsediğinin kanıtı. "
                f"Araştırmalara göre **%30 kaygı performans için ideal**, aşarsa zararlı.\n\n"
                f"Evde yapabilecekleriniz:\n\n"
                f"1) **Dil dikkati**: 'Sınava çok az kaldı, hazır mısın?' yerine "
                f"'Sınav yaklaşıyor, sen nasıl hissediyorsun?' — sorgulama değil, anlama.\n\n"
                f"2) **Normalize edin**: 'Kaygı kötü değil — önemsemenin işareti. Ben de "
                f"önemli işlerden önce heyecanlanırım.'\n\n"
                f"3) **4-7-8 Nefes**: Kaygı anında: 4 sn nefes al, 7 sn tut, 8 sn ver. "
                f"Parasempatik sistemi devreye alır — bilimsel olarak işe yarıyor.\n\n"
                f"4) **Uyku > ders**: Kaygılı bir beyin geceyarısı çalışmaz. 7-8 saat "
                f"uyku > 2 saat ek çalışma. Bu yaşta bu net.\n\n"
                f"*Panik atak gibi belirtiler (nefes alamama, kalp çarpıntısı) varsa "
                f"profesyonel destek önerebiliriz.*"
            ),
        },
        "calisma": {
            "baslik": "Çocuğum çalışamıyor / ertleyici",
            "literatur": "Öğrenilmiş Çaresizlik (Seligman) + Pomodoro",
            "rehberlik": (
                f"{isim}'ın çalışmama sorunu 2 farklı kökten gelebilir:\n\n"
                f"**A. Öğrenilmiş Çaresizlik** (Seligman): 'Ne yaparsam yapayım değişmiyor' "
                f"hissi. Bu durumda ufacık başarı deneyimi gerekiyor — 10 dakika çalışma "
                f"bile mucize. 'Hadi 10 dakika' teklifi kabul edilir, sonra devam eder.\n\n"
                f"**B. Bilişsel Yük** (Sweller): Beyin çok fazla konu arası sürekli "
                f"geçiş yaparsa yorulur. Çocuğunuzun planı 'matematik+fizik+biyoloji aynı "
                f"günde' ise, 'tek ders tek blok' önerin.\n\n"
                f"**Pratik Yaklaşım (Pomodoro)**: 25 dakika çalışma + 5 dakika mola. "
                f"Beyin döngüleri doğal — uzun saatler yerine küçük odaklı dilimler. "
                f"Telefonu başka odaya koymak %40 verim artırıyor.\n\n"
                f"*Evde baskı DEĞİL, örnek olun: Siz de bir hobiye düzenli vakit ayırın. "
                f"Çocuk gördüğünü öğrenir, duyduğunu değil.*"
            ),
        },
        "ekran": {
            "baslik": "Telefon/oyun bağımlılığı endişem",
            "literatur": "Dopamin döngüsü + davranışsal ekonomi",
            "rehberlik": (
                f"Telefon meselesi 2026'da her ailede var — sizde yalnız değilsiniz.\n\n"
                f"**Anlamak:** Telefon kötü değil, DOZ önemli. Beyin dopamin (ödül "
                f"kimyası) için sürekli uyaran arar — TikTok 15 saniyede yeni dopamin "
                f"verir, kitap sayfa sonunda. Beyin 'kolay' olanı seçer.\n\n"
                f"**Yaklaşım:**\n"
                f"1) Telefon yasağı değil, **zaman sınırı** (günde 2 saat toplamı) + "
                f"**yer sınırı** (yatak odasında değil).\n"
                f"2) Alternatif dopamin: Spor, müzik, sanat. Beyin yeni ödül kaynağı "
                f"bulmalı.\n"
                f"3) Akşam 21:00 sonrası telefon yok — mavi ışık uykuyu bozar "
                f"(melatonin azaltır).\n"
                f"4) Siz de telefon azaltın — çocuk 'babam/annem sürekli bakıyor' "
                f"diyorsa kural anlamsız.\n\n"
                f"*Çatışma değil, müzakere — kurallar ortak konuşulursa uygulanır.*"
            ),
        },
        "iletisim": {
            "baslik": "Çocuğumla iletişim kuramıyorum",
            "literatur": "Aktif dinleme + non-violent communication (Rosenberg)",
            "rehberlik": (
                f"15-17 yaş iletişim kopukluğu biyolojik — prefrontal korteks "
                f"gelişiyor, bağımsızlık arayışı güçlü. Siz hatalı değilsiniz, "
                f"çocuğunuz da. Doğa böyle.\n\n"
                f"**İletişimi geri açan 4 pratik:**\n\n"
                f"1) **Dinleme**: 20 dakika telefon/TV kapalı, yüz yüze. 'Nasıldı günün' "
                f"sorusu + dinleme. Yorum YOK.\n\n"
                f"2) **Sen-mesajı değil, ben-mesajı**: 'Sen sürekli başarısız oluyorsun' "
                f"→ 'Ben endişeleniyorum, çünkü seni önemsiyorum.'\n\n"
                f"3) **Paylaşılan aktivite**: Tartışma değil, birlikte yapma — yürüyüş, "
                f"yemek, film. İletişim doğal gelişir.\n\n"
                f"4) **Hata hakkı**: Çocuk hata yapacak. Her hata 'ders' değil, 'sen yine "
                f"aynı şeyi yaptın' değil. Onarım fırsatı.\n\n"
                f"*Ergenin kapattığı kapıyı kırmayın — çalmaya devam edin. Açarlar.*"
            ),
        },
        "genel": {
            "baslik": "Çocuğuma nasıl destek olabilirim",
            "literatur": "Growth Mindset (Dweck) + Authoritative Parenting (Baumrind)",
            "rehberlik": (
                f"{isim} ({sinif}) şu anda YKS hazırlığında. Genel rehberlik:\n\n"
                f"**3 Altın Kural (eğitim bilimleri ortak görüşü):**\n\n"
                f"🔹 **Sonuç değil süreç**: 'Kaç net aldın' yerine 'nasıl çalıştın, "
                f"zevk aldın mı' sorun. Sonuç odaklı çocuk performans için yaşar, "
                f"süreç odaklı çocuk öğrenmeyi sever.\n\n"
                f"🔹 **Eylem ≠ kimlik**: 'Tembel çocuk' etiketi yerine 'bugün motive "
                f"olmayan bir davranış' deyin. Eylem değiştirilebilir, kimlik değil.\n\n"
                f"🔹 **Beraberlik > yalnız bırakma**: '{isim}, kendin bilirsin' DEĞİL, "
                f"'Yanındayım, birlikte planlayalım' diyalog. Ergeli rehbere ihtiyaç var.\n\n"
                f"**Kurumla işbirliği**: Rehberlik öğretmeniyle düzenli görüşme, "
                f"veli-öğretmen üçgeninde şeffaflık önemli. Biz kurum olarak ayda 1 "
                f"veli özet göndeririz (yeni sezon sonrası aktif).\n\n"
                f"_Sorularınız için buradayız._"
            ),
        },
    }

    tema = tema.lower().strip()
    rehber = rehberlikler.get(tema, rehberlikler["genel"])

    return {
        "basarili": True,
        "ogrenci": isim,
        "sinif": sinif,
        "tema": tema,
        "baslik": rehber["baslik"],
        "literatur_kaynagi": rehber["literatur"],
        "rehberlik_metni": rehber["rehberlik"],
        "veli_icin_not": (
            "Bu rehberlik eğitim bilimleri literatürüne dayanıyor, kurumsal "
            "deneyimimizle harmanlandı. Soru ve detaylar için Kurumu arayabilirsiniz."
        ),
    }


async def get_prompt_hint() -> str:
    """Claude system_prompt'una eklenecek referans."""
    return (
        "\n🔺 OGRETMEN/OGRENCI/VELI UCGEN MODEL (ucgen_model.py):\n"
        "  - Ogretmen 'X ogrenci hakkinda one' dediginde → build_ogretmen_brief(soz_no)\n"
        "    Cikti: pedagojik literatur tabanli oneriler (CLT, Dweck, VARK, SDT)\n"
        "  - Veli 'cocugum calismiyor/kaygili/oyun' dediginde → build_veli_rehberlik(soz_no, tema)\n"
        "    Cikti: veli rehberliği (SDT, CBT, Seligman, Baumrind)\n"
        "  Kural: 'Dweck der ki' gibi akademik referans verme, PRATIK cerceve."
    )


if __name__ == "__main__":
    import asyncio, sys, io, json
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    async def main():
        # Test ogrenci (Mahmut Taha — soz_no=182)
        brief = await build_ogretmen_brief(182)
        print("═══ OGRETMEN BRIEF (Mahmut Taha) ═══")
        print(json.dumps(brief, ensure_ascii=False, indent=2, default=str)[:2000])
        print()
        rehber = await build_veli_rehberlik(182, "motivasyon")
        print("═══ VELI REHBERLIK (motivasyon) ═══")
        print(f"Baslik: {rehber.get('baslik')}")
        print(f"Kaynak: {rehber.get('literatur_kaynagi')}")
        print(rehber.get('rehberlik_metni', '')[:800])
    asyncio.run(main())
