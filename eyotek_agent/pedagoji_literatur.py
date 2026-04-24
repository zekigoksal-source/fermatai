"""
FermatAI — Pedagoji Literaturu (22.1n-neo FAZ 1.2)
====================================================

12 temel egitim bilimleri kavrami. Bot bunlari:
  1. Kendi agzindan vermez (akademik literatur oldugu belli olmasin)
  2. Pratik ornege donusturerek ogrenciye uygular
  3. "Dweck'e gore..." degil, "Aslinda senin beyninde..." der (ama arkada Dweck)

Fonksiyonlar:
  - get_by_slug(slug) → {kisaca, kullanim_ornegi}
  - match_triggers(message) → ilgili kavram listesi (pattern match)
  - get_random_for_mood(mood) → duygusal duruma uyan kavram

Kullanim (Claude prompt'una inject):
  'Ogrenci "cok zorlaniyorum" dediyse → growth_mindset + zpd uygula'
"""
from __future__ import annotations

import re
import random
from typing import Optional
from db_pool import db_fetch, db_fetchrow, db_execute


# 12 kanonik kavram
KAVRAMLAR = [
    {
        "slug": "growth_mindset",
        "baslik": "Büyüme Zihniyeti (Growth Mindset)",
        "kisaca": "Yetenek sabit değil, gelişir. Hatalar öğrenme fırsatı.",
        "aciklama": (
            "Carol Dweck (2006, Stanford). İki zihniyet türü: Sabit zihniyet 'ben matematikte "
            "iyi DEĞİLİM' der, büyüme zihniyeti 'matematiği HENÜZ anlamadım' der. "
            "Beyin plastisitesi sayesinde her zorluk yeni nöral bağlantıdır. "
            "'Henüz' kelimesi sihirli anahtar."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'ben fizik yapamam' dedi → 'Yapamazsın değil, HENÜZ yapamıyorsun. "
            "Şu an zor gelen, 3 ay sonra otomatik olacak. Beyinde yeni yol açıyorsun.'"
        ),
        "trigger_patterns": r"yapam[ıa]yorum|beceremem|ben.*zay[iı]f|m[uü]mk[uü]n de[gğ]il|hi[cç] olmuyor|bosuna",
        "kaynak": "Dweck, C. (2006). Mindset: The New Psychology of Success",
        "etiketler": "motivasyon,ozguven,basarisizlik,zihniyet",
    },
    {
        "slug": "bloom_taksonomi",
        "baslik": "Bloom Taksonomisi (Bilgi Hiyerarşisi)",
        "kisaca": "Öğrenme 6 aşamalı: hatırla → anla → uygula → analiz et → değerlendir → yarat.",
        "aciklama": (
            "Benjamin Bloom (1956, rev. 2001). Bir konuda 'biliyorum' demek yeterli değil. "
            "Öğrenciye soru sorulduğunda hangi aşamada? Sadece formülü hatırlıyor mu (L1) "
            "yoksa benzer probleme uygulayabiliyor mu (L3)? YKS soruları L3-L5 arası."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'türevi ezberledim' dedi → 'Güzel — ama TYT'de türev uygulaması çıkıyor "
            "(L3). Sana iki örnek veriyorum, farklı senaryolar: hangisinde türev kullanılır?'"
        ),
        "trigger_patterns": r"ezberled[iı]m|s[iı]naviya haz[iı]r|anlad[iı]m san[iı]yordum|bilirim ama",
        "kaynak": "Bloom, B. (1956); Anderson & Krathwohl (2001)",
        "etiketler": "sinav,analiz,tekrar,degerlendirme",
    },
    {
        "slug": "deliberate_practice",
        "baslik": "Bilinçli Pratik (Deliberate Practice)",
        "kisaca": "Saat değil, doğru saat. Rastgele çözüm ≠ hedefli pratik.",
        "aciklama": (
            "Anders Ericsson (1993). 10,000 saat efsanesi yanlış yorumlanır: önemli olan miktar "
            "DEĞIL, kalite. 3 unsur: (1) spesifik zayıflığa odak, (2) anında geri bildirim, "
            "(3) konfor alanı dışı zorluk. Her problemden çıkan ders > 100 kolay problem."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'günde 200 test çözüyorum ama puanım artmıyor' dedi → 'Miktar değil, "
            "yöntem. 200 yerine 50 çöz ama her yanlışı 10 dakika analiz et. Kaliteli pratik."
        ),
        "trigger_patterns": r"cok calisiyorum|saatlerce|puan(iya)?m artmiyor|hep ayn[iı]|verim",
        "kaynak": "Ericsson (1993); Peak (2016)",
        "etiketler": "calisma,verim,gelisim,pratik",
    },
    {
        "slug": "feynman",
        "baslik": "Feynman Tekniği",
        "kisaca": "Konuyu 12 yaşındaki çocuğa anlatabiliyorsan gerçekten biliyorsun.",
        "aciklama": (
            "Richard Feynman (Nobelli fizikçi). 4 adım: (1) Konuyu seç, (2) Basit dille anlat "
            "(nota al, sanki öğretiyormuşsun gibi), (3) Takıldığın yere geri dön → boşluğu "
            "doldur, (4) Sadeleştir, analoji ekle. Ezber değil, kavrama."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'kaldırma kuvvetini anlamıyorum' dedi → 'Dur, kaldırma kuvvetini BANA "
            "anlat. Sanki hiç fizik bilmeyen birine. Nerede takılırsan orayı çözelim.'"
        ),
        "trigger_patterns": r"anlamiyorum|zorlan[iı]yorum|karisik|kafam kari[sş]ik|farkli ornek",
        "kaynak": "Feynman, R. (1960); Ultralearning (Young, 2019)",
        "etiketler": "ogrenme,teknik,kavrama,ezber",
    },
    {
        "slug": "spaced_repetition",
        "baslik": "Aralıklı Tekrar (Spaced Repetition)",
        "kisaca": "Unutma eğrisi doğal, tekrar tekrar görmekten aşılır.",
        "aciklama": (
            "Hermann Ebbinghaus (1885). 1 saat sonra %60 unuturuz. AMA aralıkla tekrar "
            "ederse hafıza kalıcı olur. Optimal aralık: 1 gün → 3 gün → 1 hafta → 2 hafta → 1 "
            "ay. Leitner sistemi bunun pratik uygulaması. Anki app buna dayalı."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'geçen ay çözdüğüm konuyu unuttum' dedi → 'Normal. Bugün tekrar bak, "
            "3 gün sonra bir daha, 1 hafta sonra. Her tekrar unutma süresini 2x uzatır.'"
        ),
        "trigger_patterns": r"unuttum|hatirlam[iı]yorum|her seferinde bastan|tekrar",
        "kaynak": "Ebbinghaus (1885); Leitner (1972); SuperMemo algorithm",
        "etiketler": "hafiza,tekrar,unutma,plan",
    },
    {
        "slug": "pomodoro",
        "baslik": "Pomodoro Tekniği",
        "kisaca": "25 dakika odak + 5 dakika mola = sürdürülebilir çalışma ritmi.",
        "aciklama": (
            "Francesco Cirillo (1980). İnsan odağı sürekli değil, döngüsel. 25/5/25/5 "
            "patterni en verimli. 4 pomodoro sonrası 15-30 dk uzun mola. Telefonu diğer "
            "odaya, bildirim kapalı. 'Konsantrasyon kas gibi — antrenmanla güçlenir.'"
        ),
        "kullanim_ornegi": (
            "Öğrenci '2 saat oturuyorum ama verim yok' dedi → '2 saat tek parça uyku "
            "alınması gibi — beyin yoruluyor. 4×(25/5) dene: daha az zaman, daha çok çıktı.'"
        ),
        "trigger_patterns": r"odaklanam[iı]yorum|sureli cal[iı]samiyorum|dikkatim dagil[iı]yor|verim d[uü][sş][uü]k",
        "kaynak": "Cirillo, F. (2006). The Pomodoro Technique",
        "etiketler": "odak,zaman,mola,disiplin",
    },
    {
        "slug": "dual_coding",
        "baslik": "İkili Kodlama (Dual Coding)",
        "kisaca": "Görsel + sözel birlikte = 2x kalıcılık. Sadece yazı değil, şema çiz.",
        "aciklama": (
            "Allan Paivio (1971). Beyin görsel ve sözel bilgiyi ayrı kanallarda işler. İkisini "
            "birleştirmek hafızayı güçlendirir. Formül ezberlemek yerine şema + örnek + "
            "anımsatıcı resim. Mind map, Cornell notes, akış diyagramları bu prensibin uygulaması."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'tarih ezberleyemiyorum' dedi → 'Zaman çizgisi çiz — 1453 ok, 1683 "
            "balon. Her olayı görselle işaretle. Beynin görsel + sözel 2x kodlayacak.'"
        ),
        "trigger_patterns": r"ezberleyem[iı]yorum|akl[iı]mda tutamiyorum|tarih|formul|liste",
        "kaynak": "Paivio, A. (1971). Imagery and Verbal Processes",
        "etiketler": "hafiza,gorsel,sema,not",
    },
    {
        "slug": "self_determination",
        "baslik": "Öz Belirleme Kuramı (SDT)",
        "kisaca": "İç motivasyon 3 ihtiyaçla beslenir: özerklik, yeterlilik, bağ kurma.",
        "aciklama": (
            "Deci & Ryan (1985). İçsel motivasyon dış ödülle değil, 3 psikolojik ihtiyacın "
            "doymasıyla gelir: (1) Özerklik — seçim hissi, (2) Yeterlilik — başarıyor olmak, "
            "(3) İlişki — bağlılık. Bu 3'ü olan öğrenci dışarıdan zorlamaya ihtiyaç duymaz."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'ailem zorluyor' dedi → 'Anlıyorum. Sana sorayım: eğer kimse zorlamasaydı, "
            "YKS'yi neden kazanmak isterdin? Kendi sesini bulalım.' (özerklik)"
        ),
        "trigger_patterns": r"annem|ailem zorlu|istemiyorum ama|mecburum|kendim icin de[gğ]il",
        "kaynak": "Deci & Ryan (1985); Self-Determination Theory",
        "etiketler": "motivasyon,aile,hedef,ozerklik",
    },
    {
        "slug": "flow",
        "baslik": "Akış Durumu (Flow)",
        "kisaca": "Zorluk + yetenek dengesi = zamanın durması, derin odak.",
        "aciklama": (
            "Mihaly Csíkszentmihályi (1975). Çok kolay = sıkılma. Çok zor = kaygı. Tam "
            "ortasında — yetkinliğinin hemen üstünde — 'akış' yaşanır. 90 dakika kesintisiz "
            "çalışabilir, zamanın geçtiğini anlamaz. Koşullar: net hedef, anında geri bildirim."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'çalışmak sıkıcı' dedi → 'Muhtemelen çok kolay ya da çok zor. Sana "
            "net seviye: 6 soru çözeceksin, 4'ünü yapabilmelisin. Fazla zor da değil kolay da."
        ),
        "trigger_patterns": r"s[iı]k[iı]c[iı]|saat gecm[iı]yor|motive olam[iı]yorum|zevk alm[iı]yorum",
        "kaynak": "Csíkszentmihályi, M. (1990). Flow",
        "etiketler": "odak,akis,zorluk,motivasyon",
    },
    {
        "slug": "zpd",
        "baslik": "Yakınsak Gelişim Alanı (ZPD)",
        "kisaca": "Tek başına yapamadığın ama rehberle yapabildiğin bölge — gerçek öğrenme burada.",
        "aciklama": (
            "Lev Vygotsky (1934). Bildiklerin (kolay) ve bilmediklerin (imkansız) arasında "
            "'rehber eşliğinde yapılabilir' bir alan var: ZPD. Öğretmen/bot/akran ZPD'de "
            "destek verir, öğrenci bu bölgede en hızlı büyür. Scaffold (iskele) mantığı."
        ),
        "kullanim_ornegi": (
            "Öğrenci 'türev çok zor' dedi → 'Tamamen yalnız yaparsan zor, ama birlikte "
            "bakalım — ilk 2 adımı ben göstereyim, 3.'den sen dene. Bu senin ZPD'n."
        ),
        "trigger_patterns": r"yaln[iı]z basar[iı]lm[iı]yor|yard[iı]ma ihtiyacim|ornekle|birlikte",
        "kaynak": "Vygotsky, L. (1934). Thought and Language",
        "etiketler": "ogretme,rehber,yardim,scaffolding",
    },
    {
        "slug": "metacognition",
        "baslik": "Üstbiliş (Metakognisyon)",
        "kisaca": "Öğrenme üzerine düşünme — 'nasıl öğreniyorum?' sorusu öğrenmenin anahtarı.",
        "aciklama": (
            "John Flavell (1976). Yüksek performansın iki katmanı var: (1) Bilgi, (2) "
            "Öğrenme sürecini izleme/yönetme. İkincisi olmadan ilk katman eksik kalır. "
            "'Hangi konuyu daha iyi anladım? Hangi çalışma yöntemi benimle uyumlu? "
            "Yanlışları neden yapıyorum?' — bu sorular üstbiliş."
        ),
        "kullanim_ornegi": (
            "Öğrenci deneme sonrası → 'Sadece neti bakma: 5 yanlış neden oldu? Zaman mı, "
            "kavram mı, dikkat mi? Her yanlışı kategoriye ayır. Kendi hatanı tanıyan öğrenir."
        ),
        "trigger_patterns": r"neden yanl[iı][sş]|hata yap[iı]yorum|deneme analiz|yanl[iı][sş] anl[iı]yorum",
        "kaynak": "Flavell, J. (1979); Zimmerman (2002)",
        "etiketler": "analiz,ustbilisel,hata,oz-degerlendirme",
    },
    {
        "slug": "cognitive_load",
        "baslik": "Bilişsel Yük Kuramı (CLT)",
        "kisaca": "Çalışma belleği sınırlı (7±2 parça). Fazla yük = öğrenme durur.",
        "aciklama": (
            "John Sweller (1988). 3 tip yük: (1) İç yük — konunun kendi zorluğu, (2) Dış yük "
            "— kötü sunum/notlar, (3) Öğretici yük — kalıcı hafızaya geçiş. Çok fazla konu "
            "aynı anda → beyin tıkanır. Tek seferde 1 kavram, üst üste eklenerek inşa."
        ),
        "kullanim_ornegi": (
            "Öğrenci 3 dersi birden çalışıyor → 'Bir defada bu kadar çok şey beynin için ağır. "
            "Matematik + Fizik + Kimya değil — 90 dk matematik, mola, sonra fizik. Tek kanal."
        ),
        "trigger_patterns": r"cok konu|birden fazla|karisik gidi[yi]or|kafam tutmu[sş]|3 ders|bir arada",
        "kaynak": "Sweller, J. (1988); Cognitive Load Theory",
        "etiketler": "hafiza,yuk,odak,plan",
    },
]


async def hydrate_db(force: bool = False):
    """12 kavrami DB'ye ekle (idempotent)."""
    n = 0
    for k in KAVRAMLAR:
        await db_execute(
            """INSERT INTO pedagoji_literatur
               (slug, baslik, kisaca, aciklama, kullanim_ornegi, trigger_patterns, kaynak, etiketler)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (slug) DO UPDATE SET
                 baslik=EXCLUDED.baslik, kisaca=EXCLUDED.kisaca,
                 aciklama=EXCLUDED.aciklama, kullanim_ornegi=EXCLUDED.kullanim_ornegi,
                 trigger_patterns=EXCLUDED.trigger_patterns, kaynak=EXCLUDED.kaynak,
                 etiketler=EXCLUDED.etiketler""",
            k["slug"], k["baslik"], k["kisaca"], k["aciklama"],
            k["kullanim_ornegi"], k["trigger_patterns"], k["kaynak"], k["etiketler"]
        )
        n += 1
    return n


async def get_by_slug(slug: str) -> Optional[dict]:
    r = await db_fetchrow("SELECT * FROM pedagoji_literatur WHERE slug=$1", slug)
    return dict(r) if r else None


async def match_triggers(message: str, limit: int = 3) -> list[dict]:
    """Mesajda tetikleyen kavramlari don."""
    if not message:
        return []
    msg = message.lower()
    rows = await db_fetch("SELECT slug, baslik, kisaca, kullanim_ornegi, trigger_patterns FROM pedagoji_literatur")
    matches = []
    for r in rows:
        pat = r.get("trigger_patterns")
        if not pat:
            continue
        try:
            if re.search(pat, msg, re.IGNORECASE):
                matches.append(dict(r))
        except Exception:
            pass
    return matches[:limit]


async def get_random_for_tag(tag: str) -> Optional[dict]:
    """Etiketle esleyen rastgele kavram (etiket: motivasyon, odak, hafiza...)."""
    rows = await db_fetch(
        "SELECT slug, baslik, kisaca, kullanim_ornegi FROM pedagoji_literatur WHERE etiketler LIKE $1",
        f"%{tag}%"
    )
    if not rows:
        return None
    return dict(random.choice(rows))


async def get_prompt_injection() -> str:
    """Claude system_prompt'una eklenecek kisa literatur referansi."""
    return (
        "\n🎓 PEDAGOJIK LITERATUR REFERANSI (kullanirken dogal konus, akademik dil kacin):\n"
        "  - Growth Mindset (Dweck): 'yapamiyorum' → 'henuz yapamiyorum' + beyin plastisitesi\n"
        "  - Feynman: 'anlamiyorum' → 'BANA anlat, nerede takildin gorelim'\n"
        "  - Pomodoro: 'odaklanamiyorum' → 25/5 donemi + telefon baska oda\n"
        "  - Spaced Rep: 'unuttum' → 1 gun, 3 gun, 1 hafta tekrar plani\n"
        "  - Dual Coding: 'ezberleyemiyorum' → sema + gorsel + anlam\n"
        "  - Deliberate Practice: 'cok calisiyorum' → kalite vs miktar, her yanlisi analiz\n"
        "  - CLT: '3 ders birden' → tek kanal, tek oturum, ust uste ekleme\n"
        "  - ZPD: 'cok zor' → birlikte ilk adim, scaffold\n"
        "  - SDT: 'ailem zorluyor' → ozerklik bulma, neden sen istiyorsun\n"
        "  - Flow: 'sikici' → zorluk-yetenek dengesi ayari\n"
        "  - Metacognition: deneme sonrasi → 'neden' hatasi, hata tipolojisi\n"
        "  - Bloom: 'ezberledim' → uygulama (L3) sorusu ile dogrula\n"
        "  ⚠ Bu kavramlari KAYNAK GOSTEREREK DEGIL, DOGAL DILLE uygula (bot akademik kitap degil, egitim ortagi).\n"
    )


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    async def main():
        n = await hydrate_db()
        print(f"{n} kavram DB'ye eklendi")
        # Test trigger match
        m = await match_triggers("ben fizik yapamam hiç olmuyor")
        for k in m:
            print(f"  MATCH: {k['slug']} → {k['kisaca']}")
    asyncio.run(main())
