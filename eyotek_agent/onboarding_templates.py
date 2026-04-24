"""
Onboarding Mesaj Şablonları (22.1n-K1K2)
=========================================

Neo talimatı: "metinler hazır olsun, AMA OTOMATİK GÖNDERİM YOK"
Tüm şablonlar `draft` — Neo yeni sezon başında manuel onay + toplu gönderim.

KULLANIM:
  from onboarding_templates import get_template
  metin = get_template("ogretmen_davet", name="Kardelen")
  # Neo toplu gönderim scriptinde kullanacak — outreach_pending'e yazılacak,
  # Neo UI'dan onay verip "gönder" butonu ile aktive edecek.

GÜVENLİK:
  Bu dosya MESAJ GÖNDERMEZ. Sadece string metin döner.
"""

# ─── ÖĞRETMEN ONBOARDING ────────────────────────────────────────────────
OGRETMEN_DAVET = """Merhaba {name} Hocam 👋

Zeki Bey — FermatAI sistemimiz artık öğretmenlere de özel yetkili panel ile hazır.

Size özel yapabilecekleriniz:
📊 *Öğrenci Performans Haritası* — sınıfınızdaki her öğrencinin trend, zayıf konu, etüt katılımı
📝 *Etüt Talebi Yönetimi* — öğrenciden gelen talep direkt size iletilir
📅 *Ders Programı* — haftalık takvim, öğrenci-derslik çakışma kontrolü
📸 *Çıkmış Soru Bankası* — konu bazlı görsel paylaşım (WhatsApp'tan direkt)
🎓 *MEB OGM Resmi Kaynaklar* — soru bankası, konu özetleri tek tıkla

Nasıl başlarım?
1️⃣ Bu mesaja *"web kodu"* yazın → 6 haneli kod gelir
2️⃣ _fermategitimkurumlari.com/fermatai_ sayfasına girin
3️⃣ Numaranız + kod ile giriş — hemen panelinizi görürsünüz

Soru çıkarsa Zeki Bey'e ulaşabilirsiniz.
FermatAI emrinizde 🎯"""


OGRETMEN_ESKALASYON = """{name} Hocam,

Öğrenci *{ogrenci_ad}* ({ogrenci_sinif}) fizik etüdü talep etti:
• Zayıf konu: {zayif_konu}
• Son deneme: {son_net} net (önceki: {onceki_net})
• Müsait saatin: {onerilen_saat}

Uygun mu? Uygunsa web üzerinden tek tıkla etüt açabilirsiniz:
{web_link}

_Uygun değilse başka bir öğretmen öneririm._"""


# ─── ÖĞRENCİ ONBOARDING ────────────────────────────────────────────────
OGRENCI_WEB_DAVET = """Merhaba {name}! 👋

Biliyor musun, senin için hazır bir *kişisel çalışma merkezi* var:

📊 *Deneme Analizin* — hangi konuda artış, hangisinde düşüş
🎯 *Zayıf Konular* — en acil çalışman gereken 5 konu
📈 *Puan Tahmini* — şu anki trendle hangi üniversiteye girebilirsin
📸 *Gerçek YKS Çıkmış Sorular* — konu bazlı, görselli
🎓 *MEB OGM Resmi Kaynakları* — soru bankası + PDF özet, hepsi ücretsiz

Hadi deneyelim:
1️⃣ Bana _"web kodu"_ yaz
2️⃣ 6 haneli kod göndereyim
3️⃣ _fermategitimkurumlari.com/fermatai_ aç, giriş yap

Panelinde kendi verilerini görünce biraz şaşıracaksın 😊
Akşama kadar buradayım, takıldığın yer olursa yaz."""


OGRENCI_RAPOR_HATIRLATMA = """{name}, yeni deneme sonucun geldi! 📊

Bu hafta bir analiz yapalım mı? Sana:
• Son 3 denemenin trend grafiği
• Hangi konuda hızla ilerliyorsun
• Kalan süreyle hedef netin gerçekçi mi

5 dakikalık bir sohbet. Hazır mısın?"""


OGRENCI_CALISMA_SOGUMA = """Selam {name} 👋

3 gündür sessizsin — hepimiz bazen mola ihtiyacı duyarız.
Ama sınava *{kalan_gun} gün* kaldı — her gün değerli.

Sadece 10 dk: bana en zorlandığın konuyu söyle, yoluna bakalım.
_Yapamıyorsan dinlenmen de normal, söyle öyle bırakayım._"""


# ─── MÜDÜR / REHBER ────────────────────────────────────────────────
MUDUR_HAFTALIK_OZET = """Sayın Müdürüm, haftalık kurum özeti 📋

📊 *Bu hafta sistemi kullanan:* {aktif_sayi} öğrenci
📝 *Toplam etüt:* {etut_sayisi}
📈 *Deneme trendleri:*
  - TYT ortalama: {tyt_ort} net ({tyt_degisim})
  - AYT ortalama: {ayt_ort} net ({ayt_degisim})

🎯 *En çok gelişen 3 öğrenci:*
{en_gelisen_liste}

⚠️ *Dikkat edilmesi gerekenler:*
{riskli_liste}

Detay analiz için FermatAI web paneli: _fermategitimkurumlari.com/fermatai_"""


VELI_HAFTALIK_DIGEST = """Merhaba {veli_ad} 👋

*{ogrenci_ad}* bu hafta:

📊 *Akademik durum:*
• Son deneme: {son_net} net ({trend})
• 1 hafta önce: {onceki_net} net
• En güçlü: {guclu_ders}
• Dikkat gerektiren: {zayif_ders}

📚 *Çalışma alanı:*
{calistigi_konu}

⏱ *Devamsızlık:* {devam_saat} saat (bu hafta {hafta_devam})

💬 *{ogrenci_ad}'le bu hafta:*
{gorusme_ozet}

_Sorularınız için Fermat Eğitim Kurumları: +90 546 260 54 46_
_Her Pazar akşamı otomatik — yanıtlamak için şu mesajı cevaplayın._"""


REHBER_RISK_OGRENCI = """{name} Hocam,

Bu hafta 3 risk sinyali tespit ettim:

🔴 *{ogrenci_ad}* ({ogrenci_sinif})
  - Son 7 gün: {sinyal_sayisi} negatif sinyal
  - Tipik ifade: "{ornek_mesaj}"
  - Son deneme: {son_net} net (önceki: {onceki_net})

Görüşme planlamak ister misiniz? FermatAI panelinde detaylı analiz hazır."""


# ─── ŞABLON SÖZLÜĞÜ ──────────────────────────────────────────────────
TEMPLATES = {
    "ogretmen_davet": OGRETMEN_DAVET,
    "ogretmen_eskalasyon": OGRETMEN_ESKALASYON,
    "ogrenci_web_davet": OGRENCI_WEB_DAVET,
    "ogrenci_rapor_hatirlatma": OGRENCI_RAPOR_HATIRLATMA,
    "ogrenci_calisma_soguma": OGRENCI_CALISMA_SOGUMA,
    "mudur_haftalik_ozet": MUDUR_HAFTALIK_OZET,
    "rehber_risk_ogrenci": REHBER_RISK_OGRENCI,
    "veli_haftalik_digest": VELI_HAFTALIK_DIGEST,  # 22.1n-toplanti #9
}


def get_template(template_key: str, **kwargs) -> str:
    """Şablon doldur. Eksik placeholder'lar boş string olur (KeyError riski yok)."""
    t = TEMPLATES.get(template_key)
    if not t:
        return ""
    # Güvenli format — eksik anahtar boş string
    class _SafeDict(dict):
        def __missing__(self, key):
            return ""
    try:
        return t.format_map(_SafeDict(**kwargs))
    except Exception:
        return t


def preview_all() -> dict:
    """Tüm şablonları sample verilerle preview (Neo gözden geçirsin)."""
    return {
        "ogretmen_davet": get_template("ogretmen_davet", name="Kardelen"),
        "ogrenci_web_davet": get_template("ogrenci_web_davet", name="Ali"),
        "mudur_haftalik_ozet": get_template("mudur_haftalik_ozet",
            aktif_sayi=22, etut_sayisi=58,
            tyt_ort=74, tyt_degisim="+2.3 net",
            ayt_ort=38, ayt_degisim="+1.1 net",
            en_gelisen_liste="• Ali Demir (+8 net)\n• Ecrin Beller (+5 net)\n• Zehra Çetin (+4 net)",
            riskli_liste="• 3 öğrenci 100+ saat devamsız\n• 2 öğrenci son 2 denemede düşüşte"),
    }


if __name__ == "__main__":
    import sys, io, json
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    previews = preview_all()
    for k, v in previews.items():
        print(f"\n{'='*60}\n{k.upper()}\n{'='*60}")
        print(v)
