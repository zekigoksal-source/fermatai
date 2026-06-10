# 🌌 Bilim Evreni — Tasarım Dokümanı ve Yol Haritası

> **Sürüm:** 2.0 (25.58-J, 11 Haziran 2026) · **Dosya:** `bilim-evreni.html` (tek dosya, statik)
> **Temel:** 3 paralel araştırma ajanı — (1) YKS konu→simülasyon haritası (PhET ~200 sim envanteri
> + ÖSYM 2018-2025 soru dağılımı), (2) PubChem PUG REST 3D şeması (canlı doğrulanmış),
> (3) NASA NSSDC gezegen/Kepler verisi (fact sheet arşiv doğrulamalı).

---

## Tasarım İlkeleri (değişmez)

1. **Çizilmiş değil, hesaplanmış:** Her simülasyon ya gerçek fizik motoru (Rapier) ya da
   gerçek sayısal entegratör kullanır. Her istasyonda **ölçülen vs teorik** değer yan yana.
2. **PhET standardı:** Slider parametreler + anlık geri bildirim + keşfedilecek tek yasa.
3. **YKS bağı zorunlu:** Her istasyon açıklamasında hangi YKS konusunu/soru tipini
   karşıladığı yazar.
4. **Gerçek veri:** PubChem (110M bileşik), NASA fact sheet — uydurma sayı yok.
5. **Çekirdek agent'a sıfır dokunuş:** Saf statik HTML; backend entegrasyonu yalnız URL
   derin linkiyle (`?oda=` `?istasyon=`).
6. **Tek dosya, CDN importmap:** three@0.165 + rapier3d-compat@0.12 (+esm, WASM gömülü).

## Mevcut Envanter (24 istasyon)

| Oda | İstasyon (id) | YKS Konusu | Parametreler | Doğrulanmış ölçüm |
|---|---|---|---|---|
| Fizik | firlatici | Atış hareketi (AYT ~1) | θ, v₀, m | menzil = teori ±0.1m; kütle bağımsızlığı |
| Fizik | sarkac | Basit harmonik (AYT ~1) | L₂, açı | T=2π√(L/g) ±%2 (büyük açı dahil) |
| Fizik | egik | Kuvvet-sürtünme (TYT+AYT ~3) | θ, μ | statik eşik μ≥tanθ; 5/7 yuvarlanma |
| Fizik | carpisma | Momentum (AYT ~2) | m₁,m₂,e,v | Σp birebir; e=0'da KE %50 kayıp |
| Fizik | yay | SHM (AYT ~1) | k, m | T=2π√(m/k) ±%1 |
| Fizik | manyetik | Manyetizma (AYT ~2) | I | B∝I/r görsel |
| Fizik | gezegen | Kütle-ağırlık, g | gezegen seçimi | NASA g değerleri; oda-geneli etki |
| Fizik | kepler | Çembersel hareket+kütle çekim | zaman hızı | T²/a³=1.000±0.0014 (5 gezegen) |
| Fizik | arsimet | Kaldırma kuvveti (TYT ~1) | ρ | batık oran = ρ/ρsu ±%2 |
| Fizik | dalga | Dalgalar (TYT+AYT ~1) | A, f, λ | v=λf; tanecik ilerlemez |
| Fizik | enerji | Enerji korunumu (TYT+AYT ~2) | μ | %98 korunum (μ=0), ısı kaybı görünür |
| Mat | yuzey | Fonksiyonlar/çok değişken | a, b, 4 şekil | canlı yüzey |
| Mat | turev | Türev (AYT ~5-6, en yüksek) | x₀, 3 fonksiyon | f'(x₀) sayısal; ekstremum tespiti |
| Mat | galton | Olasılık (TYT+AYT ~1-2) | — | binom→normal, gerçek fizikle |
| Mat | riemann | İntegral (AYT ~4-5) | n, 3 fonksiyon | sol toplam → gerçek ∫ yakınsama |
| Mat | trig | Trigonometri (AYT ~3-5) | θ | sin/cos/tan + bölge |
| Kimya | gaz | Gazlar (AYT ~1-2) | T, V, N | P duvar impulsundan; PV/NT sabit |
| Kimya | molekul | Türler arası etkileşim | 12 molekül | **PubChem canlı 3D** (CID doğrulanmış) |
| Kimya | difuzyon | Gazlarda yayılma | M₂ | Graham: v∝1/√M |
| Kimya | tepkime | Hız + Denge (AYT en yüksek) | T, Ea, k₋₁ | ileri=geri → denge; çarpışma teorisi |
| Bio | dna | Nükleik asitler (AYT ~2) | bp sayısı | A-T/G-C kuralı, H-bağı |
| Bio | populasyon | Ekosistem (TYT+AYT ~1-2) | α, β, γ | Lotka-Volterra faz döngüsü |
| Bio | fotosentez | Fotosentez (AYT ~1-2) | ışık, CO₂, T | minimum yasası + enzim denatürasyonu |
| Bio | mendel | Kalıtım (AYT ~3-4, en yüksek) | 3 çapraz | Punnett + n=100 büyük sayılar |

## Yol Haritası (öncelik = pedagojik değer × soru sıklığı × yapılabilirlik)

**Sonraki dalga (araştırma ajanının İLK 12'sinden kalanlar):**
1. ⚡ **DC Devre Kurucu** (Fizik, TYT+AYT ~2) — sürükle-bırak topoloji; V=IR, seri/paralel. (büyük UI işi)
2. 🧲 **Lorentz Kuvveti 3D** (AYT manyetizma ~2) — yüklü parçacık B alanında helis; q, v, B slider.
3. 🔍 **Optik Tezgah** (TYT+AYT ~1) — mercek/ayna, Snell; ışın izleme Line'larla.
4. 🌡️ **Hal Değişimi** (TYT) — gaz motorundan türetilebilir: T düşür → yoğunlaşma kümeleri.
5. 🧪 **pH Tankı** (TYT+AYT ~1) — derişim/kuvvet slider → pH = −log[H⁺] + renk skalası.
6. 🦠 **Mitoz/Mayoz sahnesi** (Bio) — kromozom ayrışma animasyonu evre kontrollü.
7. 🎢 **Yatay atış + referans çerçevesi** — bırakılan vs fırlatılan eşzamanlı düşer.
8. 🛰️ **NASA canlı API** — APOD görseli hub'a pano; Horizons'tan gerçek anlık gezegen konumu.

**Kişiselleştirme (backend, ayrı oturum):**
- `topic_tracker` zayıf konu → istasyon eşleme tablosu (`konu_istasyon_map`) → bot cevabında
  otomatik `?istasyon=` linki. Sistem promptuna kural: "zayıf konu X simülasyonla destekleniyorsa
  Evren linki öner." Ziyaret telemetrisi (hangi öğrenci hangi istasyonda ne kadar) → localStorage
  + opsiyonel POST endpoint (yeni sezon işi).

**Bilinen sınırlar:**
- PubChem rate limit 5 istek/sn — kullanıcı başına sorun değil, önbellek var.
- Enerji parkı trimesh pürüzü: ~%2/tur kayıp (kabul edilebilir, "pist sürtünmesi" olarak okunur).
- Mendel n=1000'de ±2σ sapma normaldir (bu bir hata değil, olasılık dersinin kendisi).
- iOS<16.4 importmap desteklemez (2026 öğrenci cihazlarında ihmal edilebilir).

## Test Altyapısı

`window.__fz` debug API — deterministik doğrulama (rAF kısılmasından bağımsız):
- `fastForward(sn)` senkron fizik ilerletme · `api(id)` istasyon iç API'si
- `goto(oda)` ışınlanma · `dyn(kind)` gövde konum/hız · `cam()/setCam()` kamera
- Her yeni istasyon PR'ında: en az 1 sayısal "ölçülen≈teori" doğrulaması zorunlu.

## Kaynaklar
- PhET Colorado envanteri (~200 sim) · oPhysics (~120 sim) — ajan taraması 11 Haz 2026
- ÖSYM 2018-2025 çıkmış soru dağılımları (TYT Fen 7+7+6, AYT F14/K13/B13/M30+10)
- PubChem PUG REST (CORS açık, canlı doğrulandı) · NASA NSSDC fact sheets (2025 arşiv)
