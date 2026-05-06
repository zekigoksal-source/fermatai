"""
QA Final 1000 — Dataset Parça 2/5 (200 senaryo)
================================================
Kategoriler:
  F. PhET Deney (25)
  G. Wolfram Step (25)
  H. Wikipedia Lookup (20)
  I. PubChem Kimya (15)
  J. NASA Uzay (15)
  K. ArXiv Akademik (15)
  L. USGS Deprem (10)
  M. RAG Müfredat (40)
  N. Çıkmış Soru Görsel (35)
"""
from qa_final_dataset_p1 import PROFILES

# ─── F. PhET DENEY (25) ────────────────────────────────────────────────
PHET = [
    ("Newton 2. yasası için PhET deneyi var mı, simulasyon link", "ogr_taha", "llm"),
    ("Manyetik alan PhET deneyini açar mısın", "ogr_damla", "llm"),
    ("Coulomb yasası PhET — kuvvet hesabı interaktif", "ogr_mehmet", "llm"),
    ("Asit baz PhET deneyi — pH hesabı", "ogr_ada", "llm"),
    ("Faraday elektromanyetik indüksiyon PhET", "ogr_ecrin", "llm"),
    ("Gaz yasaları PhET deneyi", "ogr_yagiz", "llm"),
    ("Sürtünme kuvveti PhET", "ogr_zehra", "llm"),
    ("Eğik atış PhET simülasyonu", "ogr_taha", "llm"),
    ("Optik PhET — mercek deneyi", "ogr_damla", "llm"),
    ("Pendulum PhET sarkaç deneyi", "ogr_mehmet", "llm"),
    ("Atomic interactions PhET", "ogr_ada", "llm"),
    ("Wave on a String PhET", "ogr_ecrin", "llm"),
    ("Sound waves PhET", "ogr_yagiz", "llm"),
    ("Energy skate park PhET", "ogr_zehra", "llm"),
    ("Forces and motion PhET", "ogr_taha", "llm"),
    ("Friction PhET deneyi", "ogr_damla", "llm"),
    ("States of matter PhET", "ogr_mehmet", "llm"),
    ("Build an atom PhET", "ogr_ada", "llm"),
    ("DNA PhET deneyi", "ogr_ecrin", "llm"),
    ("Natural selection PhET", "ogr_yagiz", "llm"),
    ("Plate tectonics PhET", "ogr_zehra", "llm"),
    ("Greenhouse effect PhET deneyi", "ogr_taha", "llm"),
    ("Ohm's law PhET", "ogr_damla", "llm"),
    ("Circuit construction kit PhET", "ogr_mehmet", "llm"),
    ("Projectile motion PhET", "ogr_ada", "llm"),
]

# ─── G. WOLFRAM STEP-BY-STEP (25) ──────────────────────────────────────
WOLFRAM = [
    ("Wolfram'da çöz — ∫(x²+3x)dx adım adım", "ogr_taha", "llm"),
    ("Wolfram step çözüm — d/dx(sin(2x)·cos(x))", "ogr_damla", "llm"),
    ("limit (x→0) sin(x)/x Wolfram detaylı çözüm", "ogr_mehmet", "llm"),
    ("Wolfram'la — 3x² + 5x - 2 = 0 denklem çözümü", "ogr_ada", "llm"),
    ("Wolfram step — log₂(x) = 5 nasıl çözülür", "ogr_ecrin", "llm"),
    ("e^x = 7 denklemini Wolfram ile detaylı", "ogr_yagiz", "llm"),
    ("Wolfram — matrix [1,2;3,4] determinant adım adım", "ogr_zehra", "llm"),
    ("sin²(x) + cos²(x) = 1 ispat Wolfram", "ogr_taha", "llm"),
    ("Wolfram — (x+1)/(x-2) > 0 eşitsizlik çözümü", "ogr_damla", "llm"),
    ("∂/∂x(x²y + xy²) Wolfram step", "ogr_mehmet", "llm"),
    ("Wolfram — definitif integral 0'dan π'ye sin(x)dx", "ogr_ada", "llm"),
    ("|x-3| + 2 = 7 mutlak değer Wolfram", "ogr_ecrin", "llm"),
    ("Wolfram'da — 5! / 3! sadeleştirme", "ogr_yagiz", "llm"),
    ("Wolfram — vektör (1,2,3) × (4,5,6) çapraz çarpım", "ogr_zehra", "llm"),
    ("Wolfram — exp(iπ) + 1 = 0 Euler özdeşliği", "ogr_taha", "llm"),
    ("3 zar atışı toplamı 10 olasılık Wolfram", "ogr_damla", "llm"),
    ("Wolfram — n! / (n-2)! sadeleştirme", "ogr_mehmet", "llm"),
    ("Wolfram step — fonksiyon türevi (x³+2x)·e^x", "ogr_ada", "llm"),
    ("Wolfram — kompleks sayı 3+4i modulus argüman", "ogr_ecrin", "llm"),
    ("Wolfram — geometrik dizi toplamı 1+2+4+8+...+1024", "ogr_yagiz", "llm"),
    ("Wolfram — Taylor serisi e^x x=0 etrafında 5. derece", "ogr_zehra", "llm"),
    ("Wolfram — log(100) tabanı 10", "ogr_taha", "llm"),
    ("Wolfram — sin(15°) hesabı toplam formülü", "ogr_damla", "llm"),
    ("Wolfram — (a+b)⁴ binom açılımı", "ogr_mehmet", "llm"),
    ("Wolfram — y'' + y = 0 diferansiyel çözüm", "ogr_ada", "llm"),
]

# ─── H. WIKIPEDIA LOOKUP (20) ──────────────────────────────────────────
WIKI = [
    ("Wikipedia — Atatürk hayatı kısa özet", "ogr_taha", "llm"),
    ("Wiki'den — Mustafa Kemal hakkında bilgi", "ogr_damla", "llm"),
    ("Wikipedia — Albert Einstein biyografi", "ogr_mehmet", "llm"),
    ("Wikipedia — Tesla bilim insanı", "ogr_ada", "llm"),
    ("Wiki — Marie Curie keşifleri", "ogr_ecrin", "llm"),
    ("Wikipedia — İstanbul tarihi kısa", "ogr_yagiz", "llm"),
    ("Wiki'den — TÜBİTAK ne yapar", "ogr_zehra", "llm"),
    ("Wikipedia — YKS sınavı geçmişi", "ogr_taha", "llm"),
    ("Wiki — ODTÜ kuruluşu", "ogr_damla", "llm"),
    ("Wikipedia — Boğaziçi Üniversitesi tarihi", "ogr_mehmet", "llm"),
    ("Wiki — Selçuklu Devleti hakkında", "ogr_ada", "llm"),
    ("Wikipedia — Endülüs Emevileri", "ogr_ecrin", "llm"),
    ("Wiki — Yıldırım Bayezid hayatı", "ogr_yagiz", "llm"),
    ("Wikipedia — Fotosentez nedir", "ogr_zehra", "llm"),
    ("Wiki — Beyin anatomisi", "ogr_taha", "llm"),
    ("Wikipedia — Kalp dolaşım sistemi", "ogr_damla", "llm"),
    ("Wiki — Üçgen geometri", "ogr_mehmet", "llm"),
    ("Wikipedia — Enstrüman gelişimi", "ogr_ada", "llm"),
    ("Wiki'den — Nobel ödülü neden verilir", "ogr_ecrin", "llm"),
    ("Wikipedia — Fields madalyası", "ogr_yagiz", "llm"),
]

# ─── I. PUBCHEM KİMYA (15) ─────────────────────────────────────────────
PUBCHEM = [
    ("Glikoz molekülünün yapısı PubChem", "ogr_taha", "llm"),
    ("PubChem — kafein C8H10N4O2 molekül detay", "ogr_damla", "llm"),
    ("Aspirin molekülünün 3D yapısı", "ogr_mehmet", "llm"),
    ("PubChem — etanol özellikleri", "ogr_ada", "llm"),
    ("Penisilin moleküler yapısı", "ogr_ecrin", "llm"),
    ("PubChem — su H2O molekül", "ogr_yagiz", "llm"),
    ("DNA bazları — adenin yapısı", "ogr_zehra", "llm"),
    ("PubChem — kolesterol molekülü", "ogr_taha", "llm"),
    ("Vitamin C (askorbik asit) yapısı", "ogr_damla", "llm"),
    ("PubChem — testosteron molekül", "ogr_mehmet", "llm"),
    ("Karbonhidrat — sakkaroz yapısı", "ogr_ada", "llm"),
    ("PubChem — protein yapı taşı amino asit", "ogr_ecrin", "llm"),
    ("Polietilen polimer yapısı", "ogr_yagiz", "llm"),
    ("PubChem — bilim deneyinde kullanılan tipik bileşik", "ogr_zehra", "llm"),
    ("Klorofil molekülü detay", "ogr_taha", "llm"),
]

# ─── J. NASA UZAY (15) ─────────────────────────────────────────────────
NASA = [
    ("NASA APOD bugünün uzay fotoğrafı ne", "ogr_taha", "llm"),
    ("NASA — Mars yüzey fotoğrafları", "ogr_damla", "llm"),
    ("NASA — Hubble teleskopu son keşif", "ogr_mehmet", "llm"),
    ("NASA — Webb teleskopu yeni görüntü", "ogr_ada", "llm"),
    ("Uzaydan Dünya fotoğrafı NASA", "ogr_ecrin", "llm"),
    ("NASA — Saturnün halkalarının fotoğrafı", "ogr_yagiz", "llm"),
    ("NASA — Galaksi fotoğrafları arşiv", "ogr_zehra", "llm"),
    ("Apollo 11 ay'a iniş NASA görüntüleri", "ogr_taha", "llm"),
    ("ISS uluslararası uzay istasyonu fotoğraf", "ogr_damla", "llm"),
    ("NASA — kara delik görüntüleri", "ogr_mehmet", "llm"),
    ("Yıldız oluşumu NASA fotoğraflar", "ogr_ada", "llm"),
    ("NASA arkeoloji uzaydan", "ogr_ecrin", "llm"),
    ("Andromeda galaksisi NASA", "ogr_yagiz", "llm"),
    ("NASA — Güneş tutulması fotoğrafları", "ogr_zehra", "llm"),
    ("Curiosity Mars rover fotoğrafları", "ogr_taha", "llm"),
]

# ─── K. ARXIV AKADEMİK (15) ────────────────────────────────────────────
ARXIV = [
    ("ArXiv'da — kuantum bilgisayar son makaleler", "ogr_taha", "llm"),
    ("ArXiv — yapay zeka deep learning makaleleri", "ogr_damla", "llm"),
    ("ArXiv'dan — kara delik fizik araştırmaları", "ogr_mehmet", "llm"),
    ("ArXiv — string theory son makale", "ogr_ada", "llm"),
    ("ArXiv'da — gravitasyonel dalgalar son keşifler", "ogr_ecrin", "llm"),
    ("ArXiv — kanser tedavisi yeni yaklaşım", "ogr_yagiz", "llm"),
    ("ArXiv'dan — protein katlanması AlphaFold", "ogr_zehra", "llm"),
    ("ArXiv — iklim değişikliği modelleri", "ogr_taha", "llm"),
    ("ArXiv'da — kuantum kriptografi", "ogr_damla", "llm"),
    ("ArXiv — nükleer füzyon ITER projesi", "ogr_mehmet", "llm"),
    ("ArXiv'dan — egzoplanet yaşanabilirlik", "ogr_ada", "llm"),
    ("ArXiv — yapay sinir ağları yeni mimari", "ogr_ecrin", "llm"),
    ("ArXiv'da — robotik manipülasyon", "ogr_yagiz", "llm"),
    ("ArXiv — Higgs bozonu son araştırmalar", "ogr_zehra", "llm"),
    ("ArXiv — antimadde araştırmaları", "ogr_taha", "llm"),
]

# ─── L. USGS DEPREM (10) ───────────────────────────────────────────────
USGS = [
    ("USGS — son 1 günün depremleri", "ogr_taha", "llm"),
    ("USGS'den Türkiye depremleri son 1 hafta", "ogr_damla", "llm"),
    ("USGS — son büyük deprem nerede oldu", "ogr_mehmet", "llm"),
    ("Marmara depremleri USGS verileri", "ogr_ada", "llm"),
    ("Japonya depremleri USGS son ay", "ogr_ecrin", "llm"),
    ("USGS — Anadolu fay hattı son aktivite", "ogr_yagiz", "llm"),
    ("USGS verileri — küresel deprem haritası", "ogr_zehra", "llm"),
    ("Pasifik halkası depremleri USGS", "ogr_taha", "llm"),
    ("USGS — Şili depremleri büyüklük 7+", "ogr_damla", "llm"),
    ("USGS — son 24 saat 4+ büyüklük depremler", "ogr_mehmet", "llm"),
]

# ─── M. RAG MÜFREDAT (40) ──────────────────────────────────────────────
RAG_MUFREDAT = [
    ("AYT Matematik müfredatındaki tüm konuları sırala", "ogr_taha", "llm"),
    ("TYT türkçe konuları RAG'tan getir, kapsamlı liste", "ogr_damla", "llm"),
    ("AYT Fizik konularının ağırlık dağılımı nedir", "ogr_mehmet", "llm"),
    ("Hangi konular hem TYT hem AYT'de ortak", "ogr_ada", "llm"),
    ("9. sınıf matematik konuları YKS'de çıkar mı", "ogr_ecrin", "llm"),
    ("12. sınıf fizik konularının tamamı YKS'de mi", "ogr_yagiz", "llm"),
    ("Biyoloji 11. sınıf konuları detaylı liste", "ogr_zehra", "llm"),
    ("Kimya organik konuları nereden başlar", "ogr_taha", "llm"),
    ("Limit konusunun tüm alt başlıkları", "ogr_damla", "llm"),
    ("İntegral kapsamı YKS'de neler", "ogr_mehmet", "llm"),
    ("Hücre konusu ne kadar detaylı çıkıyor", "ogr_ada", "llm"),
    ("LGS matematik kazanımları yıl yıl", "ogr_ecrin", "llm"),
    ("LGS fen bilimleri konuları liste", "ogr_yagiz", "llm"),
    ("LGS Türkçe içeriği detay", "ogr_zehra", "llm"),
    ("Yeni Maarif modeli ne getiriyor", "ogr_taha", "llm"),
    ("2028 YKS değişiyor mu, önemli farklar", "ogr_damla", "llm"),
    ("Hangi tip soru çıkar AYT matematikte", "ogr_mehmet", "llm"),
    ("Yorum ağırlıklı mı YKS soruları", "ogr_ada", "llm"),
    ("Ezber konuları neler", "ogr_ecrin", "llm"),
    ("YKS müfredatı kaç ana başlık", "ogr_yagiz", "llm"),
    ("AYT Sayısal hangi dersleri kapsar — detay", "ogr_zehra", "llm"),
    ("AYT Eşit Ağırlık dersleri ve ağırlıkları", "ogr_taha", "llm"),
    ("AYT Sözel dersleri detay", "ogr_damla", "llm"),
    ("Tarih müfredat — kronolojik sıralı", "ogr_mehmet", "llm"),
    ("Coğrafya — fiziki, beşeri, ekonomik konular dağılımı", "ogr_ada", "llm"),
    ("Felsefe konuları — dönemler ve filozoflar", "ogr_ecrin", "llm"),
    ("Edebiyat dönemleri ve önemli yazarlar", "ogr_yagiz", "llm"),
    ("Türk-İslam edebiyatı kapsamı", "ogr_zehra", "llm"),
    ("Cumhuriyet dönemi edebiyatı yazarlar", "ogr_taha", "llm"),
    ("Tanzimat edebiyatı önemli figürler", "ogr_damla", "llm"),
    ("Servet-i Fünun şair ve yazarları", "ogr_mehmet", "llm"),
    ("Milli Edebiyat akımı temsilcileri", "ogr_ada", "llm"),
    ("Türev konusu hangi sınıfta öğretilir", "ogr_ecrin", "llm"),
    ("Karmaşık sayılar müfredatı", "ogr_yagiz", "llm"),
    ("Logaritma kuralları ve uygulamaları kapsamı", "ogr_zehra", "llm"),
    ("Trigonometri konuları detaylı liste", "ogr_taha", "llm"),
    ("Olasılık ve istatistik kapsamı", "ogr_damla", "llm"),
    ("Geometride katı cisimler ne kadar çıkar", "ogr_mehmet", "llm"),
    ("Analitik geometri konuları detay", "ogr_ada", "llm"),
    ("Cebirsel ifadeler ve denklemler kapsamı", "ogr_ecrin", "llm"),
]

# ─── N. ÇIKMIŞ SORU GÖRSEL (35) ────────────────────────────────────────
CIKMIS_GORSEL = [
    ("2025 TYT matematik çıkmış soruları göster", "ogr_taha", "llm"),
    ("2024 AYT fizik soruları görsel olarak", "ogr_damla", "llm"),
    ("2023 YKS matematik soruları", "ogr_mehmet", "llm"),
    ("2022 TYT türkçe çıkmış sorular", "ogr_ada", "llm"),
    ("Türev konusu çıkmış sorular göster", "ogr_ecrin", "fast/cikmis_match"),
    ("Manyetizma çıkmış sorular", "ogr_yagiz", "fast/cikmis_match"),
    ("Hücre konusu çıkmış sorular", "ogr_zehra", "fast/cikmis_match"),
    ("Paragraf çıkmış sorular göster", "ogr_taha", "fast/cikmis_match"),
    ("Osmanlı tarihi çıkmış sorular", "ogr_damla", "fast/cikmis_match"),
    ("Trigonometri çıkmış sorular", "ogr_mehmet", "fast/cikmis_match"),
    ("Limit konusu çıkmış sorular", "ogr_ada", "fast/cikmis_match"),
    ("İntegral çıkmış soruları göster", "ogr_ecrin", "fast/cikmis_match"),
    ("Asit baz çıkmış sorular", "ogr_yagiz", "fast/cikmis_match"),
    ("DNA çıkmış sorular", "ogr_zehra", "fast/cikmis_match"),
    ("Newton yasaları çıkmış sorular", "ogr_taha", "llm"),
    ("Atatürk inkılapları çıkmış sorular", "ogr_damla", "llm"),
    ("İklim çıkmış sorular", "ogr_mehmet", "llm"),
    ("Logaritma çıkmış sorular göster", "ogr_ada", "llm"),
    ("Polinom çıkmış sorular", "ogr_ecrin", "llm"),
    ("Kombinasyon çıkmış soruları", "ogr_yagiz", "llm"),
    ("2025 TYT matematik 30. sorusunun görseli", "ogr_zehra", "llm"),
    ("2024 AYT fizik 15. soru göster", "ogr_taha", "llm"),
    ("Kimya organik çıkmış sorular liste", "ogr_damla", "llm"),
    ("Biyoloji ekoloji çıkmış sorular", "ogr_mehmet", "llm"),
    ("Türkçe sözcük anlamı çıkmış sorular", "ogr_ada", "llm"),
    ("Edebiyat divan dönemi çıkmış sorular", "ogr_ecrin", "llm"),
    ("Coğrafya iklim çıkmış sorular", "ogr_yagiz", "llm"),
    ("Felsefe çıkmış sorular YKS", "ogr_zehra", "llm"),
    ("Geometri üçgen çıkmış sorular", "ogr_taha", "llm"),
    ("Çember çıkmış sorular", "ogr_damla", "llm"),
    ("Karmaşık sayı çıkmış sorular", "ogr_mehmet", "llm"),
    ("Matris çıkmış sorular", "ogr_ada", "llm"),
    ("Olasılık çıkmış sorular göster", "ogr_ecrin", "llm"),
    ("Vektör çıkmış sorular", "ogr_yagiz", "llm"),
    ("Fonksiyon çıkmış sorular", "ogr_zehra", "llm"),
]

ALL_P2 = (
    [(m, p, e, "PhET") for m, p, e in PHET] +
    [(m, p, e, "Wolfram") for m, p, e in WOLFRAM] +
    [(m, p, e, "Wiki") for m, p, e in WIKI] +
    [(m, p, e, "PubChem") for m, p, e in PUBCHEM] +
    [(m, p, e, "NASA") for m, p, e in NASA] +
    [(m, p, e, "ArXiv") for m, p, e in ARXIV] +
    [(m, p, e, "USGS") for m, p, e in USGS] +
    [(m, p, e, "RAG_Mufredat") for m, p, e in RAG_MUFREDAT] +
    [(m, p, e, "Cikmis_Gorsel") for m, p, e in CIKMIS_GORSEL]
)
