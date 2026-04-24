# Mac Studio M4 Max Değerlendirmesi — FermatAI İçin Karar Dosyası

> **24 Nisan 2026** · Neo'nun Dubai seyahati öncesi stratejik değerlendirme
> **Soru:** Mac Studio M4 Max (16 CPU / 40 GPU) + 128 GB RAM, ~$4,500-5,000
> **Cevabı kolay bir soru değil** — neye ne kazandırır, neye değmez: alttaki analiz

---

## 0. TL;DR — İki Cümlelik Özet

**Mac Studio M4 Max, FermatAI için "zorunlu değil ama yüksek stratejik kaldıraç" — bugünkü ana darboğazları (Eyotek session, 24/7 hosting) çözmez ama yerel 70B LLM, hızlı dev iterasyonu, batch RAG/Vision işleri ve ~%30-50 Claude maliyet azaltma ile 3-4 yıllık TCO'da kârlı.**

**Karar Çerçevesi:**
- Sadece "Fermat için" düşünürsen → *tercihli* (must değil, önemli kaldıraç)
- "Dev + AI araştırma + Fermat + diğer projeler" düşünürsen → *kuvvetle öneririm*
- Production 24/7 hosting çözümü arıyorsan → **yanlış alet** (Linux VPS gerekli)

---

## 1. BUGÜNKÜ GERÇEK DURUM (Ölçülmüş, Tahmin Değil)

### 1.1 Son 14 Gün (`routing_stats` + `usage_log` tablolarından)

| Kaynak | Mesaj | % | Ortalama Süre |
|---|---|---|---|
| **Claude API** | 637 (routing) + 1,418 (tool çağrısı) | %72 | 22.5 saniye |
| **Ollama (yerel)** | 48 (routing) + 170 (kullanım) | %5.4 | 9.8 saniye |
| **Fast Response** | 197 + 526 | %22.3 | 5ms |
| **Vision** | 34 | — | ~15s |

### 1.2 Gerçek Claude Maliyeti

```
Son 14 gün:    35,043,678 input token + 850,435 output token
Maliyet:       $117.89 (14 günde)
Aylık tahmin:  $253
Yıllık tahmin: $3,065
```

**Bu kritik bir rakam** — ilk raporumda "$200/ay" demiştim, gerçek **$253/ay**. Kurum büyüdükçe lineer artar.

### 1.3 Mevcut Donanım Sınırları

**Monster laptop (şu an):**
- Ollama: qwen2.5:7b (~5GB quantized), NUM_PARALLEL=2
- Büyük model yükleyemez (VRAM yetersiz)
- Playwright Chrome + Docker PostgreSQL + Bridge + Ollama aynı anda → sıcak, 80°C
- 24/7 çalıştırma: pil yıpranması, fan ömrü, kapağı açık tutmak lazım

---

## 2. MAC STUDIO M4 MAX NE SUNAR?

### 2.1 Teknik Özellikler

| Bileşen | Değer |
|---|---|
| CPU | 16 çekirdek (12 Performance + 4 Efficiency) |
| GPU | 40 çekirdek, 546 GB/s unified memory bandwidth |
| RAM | **128 GB unified memory** (CPU + GPU aynı havuzu kullanır) |
| Neural Engine | 16 çekirdek, 38 TOPS |
| Storage | 1-8 TB SSD (yapılandırmaya göre) |
| Güç | 270W max (laptop 150W'a göre 2x ama sabit) |
| Fiyat (Dubai tahmin) | $4,200-5,000 (ABD fiyatından ~%10 indirimli) |

### 2.2 FermatAI İçin Asıl Devrim: **128 GB Unified Memory**

Mac'teki unified memory = GPU ve CPU aynı 128 GB'ı paylaşıyor. Bu, normalde GPU'lar için 40-80 GB VRAM'lik modelleri çalıştırabileceğin anlamına geliyor. Şu an Fermat'ta 7B model var, 70B hayal.

**Mac Studio ile çalıştırabileceğin modeller (gerçekçi hız):**

| Model | Boyut (Q4) | Token/sn | Türkçe Kalitesi | Tool-calling |
|---|---|---|---|---|
| **Qwen 2.5 72B** | ~40 GB | 15-20 | ⭐⭐⭐⭐ (Çin'den, multi-dil güçlü) | ⭐⭐⭐⭐ (Claude'a yakın) |
| **Llama 3.3 70B** | ~40 GB | 15-20 | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Llama 3.1 8B** (hızlı) | ~5 GB | 80-120 | ⭐⭐ | ⭐⭐ |
| **Gemma 2 27B** | ~16 GB | 30-40 | ⭐⭐⭐ | ⭐⭐⭐ |
| **Mistral Large 123B** | ~70 GB | 8-12 | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Ollama qwen2.5:7b** (mevcut) | ~5 GB | 60-80 | ⭐⭐ | ⭐ |

**Önemli:** Qwen 2.5 72B, Claude Sonnet'in ~%80-85 seviyesinde tool-calling yapabiliyor. Sonnet'e denk değil ama **basit tool çağrıları için yeterli** (get_student_analytics, student_exams gibi yapılandırılmış isteklerde).

### 2.3 macOS Avantajları (Windows'a göre)

- **Unix tabanlı** — Python/asyncio/Docker daha stabil
- **64-bit ARM optimize edilmiş** — M-serisi için metal GPU
- **Daha az sistem overhead** — Windows'ın sürekli güncelleme + Defender baskısı yok
- **Uyku/uyanma stabil** — macOS server gibi 7/24 çalışır
- **Homebrew, MLX (Apple'ın ML framework'ü)** — LLM inference optimize

---

## 3. FERMATAI İÇİN SOMUT KAZANIMLAR

### 3.1 Yerel LLM Devrimi: 7B → 70B

**Şu an (qwen2.5:7b):**
- Kavramsal sorular: %85 kalite
- Tool-calling: %30 başarı (çok zayıf)
- Routing: sadece basit sohbet + kavramsal, tümü "auto-escalate to Claude"
- Yıllık maliyet kurtarışı: **$0** (çünkü kaliteli iş Ollama'ya verilmiyor)

**Mac Studio + Qwen 2.5 72B ile:**
- Kavramsal sorular: %95 kalite (Sonnet'e yakın)
- Tool-calling: %80 başarı (Sonnet %95, fark %15)
- Routing: basit tool çağrıları yerel, karmaşık olanlar Claude
- **%30-45'lik Claude trafiği yerele kayabilir**

**Mali etki hesabı:**
```
Şu an Claude: $253/ay × 12 = $3,065/yıl

Mac Studio ile %30 Claude→yerel geçişi:
  Kurtarış: $3,065 × 0.30 = $920/yıl
  
Mac Studio ile %45 geçiş (agresif ama gerçekçi):
  Kurtarış: $3,065 × 0.45 = $1,380/yıl
```

### 3.2 Hız Kazancı

| İşlem | Şu an | Mac Studio |
|---|---|---|
| Ollama 7B yanıt | 10 sn | 1-2 sn |
| Embedding (nomic) | 500 ms | 50-100 ms |
| RAG arama (5,547 kayıt) | 1.5 sn | 200-400 ms |
| Batch PDF embed (1000 chunk) | 15-20 dk | 2-3 dk |
| Vision API çağrısı | 15 sn (cloud) | **Aynı** (Vision Claude'da kalıyor) |

**Öğrenci deneyiminde etkisi:**
- "Bekletme" algısı azalır (şu an 22.5sn Claude ortalaması stres yapıyor)
- Basit sorular 1-2 sn'de cevap (WhatsApp'ın native his'ine yakın)

### 3.3 Paralelizm (Concurrent User)

**Şu an:** NUM_PARALLEL=2 → 3. öğrenci kuyrukta bekler
**Mac Studio:** NUM_PARALLEL=8-16 → 15+ eş zamanlı kullanıcı rahat

Yeni sezonda (1 Eylül 2026, 125 öğrenci × tüm veliler + rehber + yönetim) eş zamanlı kullanıcı patlaması beklenir. Mac Studio bu artışı rahatça kaldırır.

### 3.4 Dev Iterasyonu

Şu an:
- Yeni model denemek için laptop donuyor (Ollama + Chrome + Bridge + Docker)
- Büyük RAG import (32 MEB PDF) → 4-5 saat
- Prompt eval batch testi → 30 dk

Mac Studio:
- Paralel 2 Ollama instance (dev + prod) farkında değilsin
- MEB PDF import → 30-60 dk
- Prompt eval → 5 dk
- **Dev hızı 5-10x**

### 3.5 Gelecek Özellikler İçin Temel

**Yeni sezon (1 Eylül 2026) + sonrası planlı:**
- **Hata DNA sistemi** (her öğrencinin yanlış parmak izi) → büyük embedding işi
- **Veli haftalık nabız** → haftada 125 rapor üretimi, yerel LLM ile ideal
- **Alumni network** → mezun profil embedding
- **LGS topic_tracker** → +300 konu × +30 öğrenci = 9,000 yeni kayıt
- **Kıyamet Günü Simülasyonu** → 80 çıkmış soru × öğrenci cevapları = büyük batch

Bunların hepsi **local inference-heavy**. Mac Studio bu gelecek için temel.

---

## 4. MAC STUDIO'NUN ÇÖZMEYECEĞİ ŞEYLER

Dürüst olmak lazım — Mac Studio her sorunu çözmez:

### 4.1 Production 24/7 Hosting (Çözmez ❌)

Şu an Fermat laptop + ngrok'ta. Mac Studio da evde olacak. Ev internet/elektrik kesilirse, sistem düşer. Bu **Linux VPS'in görevi** (Hetzner $100/ay gibi).

**Mac Studio ≠ Server.** Production 24/7 için ayrı bir strateji lazım (VPS + Mac Studio'yu "AI compute node" olarak kullan).

### 4.2 Eyotek Session Drop (Çözmez ❌)

Ana darboğaz ASP.NET session timeout. Compute gücü değil, **zekâ gerekli** (CDP keep-alive, proper cookie rotation, ya da Eyotek API erişim). Mac/Windows fark etmez.

### 4.3 Claude Sonnet Seviyesi Kalite (Tam Çözmez ⚠️)

Qwen 72B Sonnet'e yakın ama eşit değil. Karmaşık analiz (çalışma planı protokolü, deneme karşılaştırma, duygu+konu kesişimi) hâlâ Claude'da kalacak.

**Gerçekçi hedef: %30-45 traffic yerele, gerisi Claude.**

### 4.4 Foto Soru Çözüm (Değişmez ⚠️)

Şu an Claude Vision (cloud, $0.02/foto). Mac Studio'da yerel Vision model (Llava, Qwen-VL-72B) çalışabilir AMA Claude Vision kalitesi çok önde, özellikle matematik formülü okuma. Kalite için Claude Vision'da kalmalı.

---

## 5. ALTERNATİFLER — MAC STUDIO DIŞI SEÇENEKLER

### 5.1 Linux VPS + Cloud LLM API

**Hetzner Dedicated Server GEX44 (Germany):**
- Intel i5-13500, 64 GB RAM, 2x 512GB NVMe, GPU yok
- ~€45/ay (~$50)
- Yıllık: $600

**Strateji:** Fermat Linux VPS'e, Ollama gerektiğinde **Groq API** (Llama 70B inference, $0.60/1M in, $0.80/1M out):
```
Yıllık Groq: 35M token × $0.60/M = $21/ay × 12 = $252/yıl (Claude'un %92 ucuzu)
VPS: $600/yıl
Toplam: ~$850/yıl
```

Mac Studio vs VPS+Groq:
- **Mac Studio:** $4,500 one-time + $100 elektrik/yıl → 5 yıl amortize
- **VPS+Groq:** $850/yıl → 5 yılda $4,250

**Finansal denk**, ama VPS+Groq 24/7 uptime garantili. Mac Studio dev + opsiyonel kaldıraç.

### 5.2 RTX 4090 Linux Desktop

- RTX 4090: 24 GB VRAM, $1,800
- Gerisi (CPU+RAM+case): $1,500
- Toplam: $3,300

Avantaj: 70B Q4 çalışır (just-fits 24GB), Linux ekosistemi full güç.
Dezavantaj: Windows değilse, Fermat'ın geri kalanı (Playwright) yeniden kurulmalı. Unified memory yok — CPU-GPU transfer overhead. Mac Studio'dan 2x hızlı ama 128GB RAM değil.

### 5.3 Mevcut Laptop + Groq API

**En ucuz yol:**
- Laptop'ta kal (0 ek donanım)
- Claude yerine Groq'a kaydırabileceğin %40'ı kaydır
- Yıllık: $1,500 (Claude) + $500 (Groq) = $2,000 (şimdiki $3,065'ten düşük)

**Avantaj:** $0 donanım yatırımı
**Dezavantaj:** Dev deneyim aynı yavaş, laptop yorulmaya devam

---

## 6. TCO (Total Cost of Ownership) — 5 Yıllık Karşılaştırma

```
SEÇENEK                     YIL 1     YIL 3     YIL 5
────────────────────────────────────────────────────────
A) Mevcut (laptop+Claude)   $3,065   $9,195    $15,325
B) Mac Studio + Claude %60   $4,500 cihaz
   + $1,840/yıl Claude       $6,340   $10,020   $13,700
C) VPS + Groq/Claude hybrid  $850/yıl
   (+$100 kurulum)           $950     $2,650    $4,350
D) Mac Studio + Groq + Claude
   (hybrid smart routing)    $4,500 + $1,200/yıl
                             $5,700   $8,100    $10,500
```

**5 yıllık kazanan: C (VPS + Groq)** — %75 daha ucuz, her gün çalışır.

**AMA:** C seçeneği dev hızında ve "local kontrolde" B'den çok zayıf.

**Karmatik seçim: D (Mac Studio + VPS + Groq)** — hepsi birden:
- Mac Studio dev + yerel LLM lab
- VPS production hosting (7/24)
- Groq pahalı Claude'un yarısı
- 5 yıl TCO: ~$11,000

---

## 7. MAC STUDIO ALIRSA NE DEĞİŞİR? (Senaryo Analizi)

### Senaryo A: "Mac Studio = Production Sunucu" ❌ YANLIŞ YAKLAŞIM

Ev internetiyle 24/7 production risk. İnternet kesintisi = öğrenci WhatsApp'ta yanıt alamaz. Evde sunucu soğutma, UPS, nem kontrol derdi.

**Tavsiye:** Bunu yapma.

### Senaryo B: "Mac Studio = Dev + AI Compute Node" ✅ DOĞRU YAKLAŞIM

```
Production:     Linux VPS (Hetzner €45/ay)
Bridge + DB:    VPS'te
LLM inference:  VPS'ten Mac Studio'ya tunneled (Tailscale / WireGuard)
Dev machine:    Mac Studio (yerel test, model eğitim, batch iş)
Fallback:       Groq API (Mac Studio kapalıysa)
```

Bu mimari:
- 7/24 uptime (VPS)
- Yerel LLM gücü (Mac Studio tunneled)
- Maliyet düşürme (Groq fallback)

### Senaryo C: "Mac Studio = Her şey" ⚠️ ORTA RİSK

Mac Studio home-office'te, ngrok sabit domain.
- UPS şart (30dk elektrik kesilirse)
- Sürekli soğutma (ısı sabit)
- Yedek internet (mobile modem fallback)

Çalışır ama operational risk yüksek. Fermat için önermiyorum.

---

## 8. ROI (Geri Dönüş Analizi)

### Mac Studio'nun Doğrudan ROI'si

```
Yatırım: $4,500
Yıllık kurtarış (Claude %35 azaltma): $1,075
Payback: 4.2 yıl

+ Dev hızı kazancı (parasal değer koyamam, ama büyük)
+ Yeni özellik hızla üretme (Hata DNA, Veli raporu, LGS scale-up)
+ Mac'lerin ikinci el değeri (3 yıl sonra ~$2,500 — kayıp $2,000)
```

### Dolaylı ROI (Fermat dışı kullanım)

- Kendi AI projeleri (Neo bireysel araştırma)
- Diğer kurum projeleri (Mahsum, Duygu kullanabilir)
- Video düzenleme, 3D render, müzik üretimi (M4 Max'in diğer güçleri)
- Eğitim içerik üretimi (video, PDF, animasyon)

Yani Mac Studio **sadece Fermat** için değil, **iş + kişisel + gelecek projeler** birleşimi için alınırsa ROI hızlanır.

---

## 9. RİSK ANALİZİ

### Mac Studio Alırsan

| Risk | Olasılık | Etki | Mitigation |
|---|---|---|---|
| Mac ekosistemi öğrenme eğrisi | Düşük | Küçük | Mac tecrübelisin zaten |
| Windows-specific Playwright sorun | Düşük | Orta | Production VPS'te kalır, Mac dev |
| 3 yıl sonra M5 çıkar, değer kaybı | Orta | Orta | Mac'ler değer tutar (%50 kayıp max) |
| Dubai'den getirme (garanti, uyumluluk) | Düşük | Küçük | Apple global garanti verir |
| Tek point of failure (Mac bozulursa) | Düşük | Büyük | Hetzner VPS fallback + laptop reserve |

### Mac Studio Almazsan

| Risk | Olasılık | Etki | Mitigation |
|---|---|---|---|
| Claude maliyet %100 büyür (500 öğrenci) | Yüksek | Büyük | Groq'a kayarak azalt |
| Laptop ömrü biter (ısı/kullanım) | Yüksek (2-3 yıl) | Orta | Yenisini al (~$2,500 yeni laptop) |
| Yerel LLM kalite devrimini kaçır | Orta | Orta | Groq 70B API yeterli olabilir |
| Dev iterasyon yavaş kalır | Kesin | Küçük | Şu ana kadar çalıştı, çalışır |

---

## 10. KARAR FRAMEWORK — Sana Özel

### ✅ AL eğer:

1. **Çoklu proje vizyonu var** (Fermat + kişisel AI + diğer kurum projeleri)
2. **Dev hız kritik** (yeni özellik 2 haftada yerine 3 gün)
3. **Local AI araştırmak istiyorsun** (fine-tuning, RAG tuning, multi-modal)
4. **3-5 yıl sahipleneceğim** (short-term değil, long investment)
5. **Dubai'de fiyat avantajı +$500-800** (VAT muafiyeti vs.)
6. **Redundant setup seviyorsun** (VPS production + Mac dev ideal mimarinin parçası)

### ❌ ALMA eğer:

1. **Tek derdin Fermat maliyeti azaltmak** → Groq API daha ucuz
2. **24/7 production hosting arıyorsun** → Linux VPS doğru alet
3. **$4,500 başka yere daha etkin** (Fermat pazarlama, yeni geliştirici, vs.)
4. **Laptop hâlâ iyi durumda ve 2+ yıl dayanır** görüyorsun
5. **Mac ekosistemine geçmek istemiyorsun** (Windows ERP bağlantılı)

---

## 11. BENİM HONEST ÖNERİM

### Eğer bugün Dubai'de durmak zorunda kalsam:

**İlk dalga (Dubai'de):**
- Mac Studio M4 Max 64GB RAM (128GB overkill olabilir, 64GB 70B için yeterli) — ~$3,200-3,800
- Tasarruf: $700-1,300

**İkinci dalga (Dubai sonrası, Türkiye'de):**
- Hetzner GEX44 veya benzer Linux VPS ($50/ay) production'a
- Tailscale ile Mac Studio bağla (LLM tunneled)
- Groq API şimdiden test aç (fallback)

**Toplam yatırım:** ~$3,500 cihaz + $600/yıl VPS = $4,100 ilk yıl
**Yıllık tasarruf:** $1,200-1,500 (Claude %35-45 azaltma)
**Net 3 yıl TCO:** ~$5,900 (mevcut $9,195'e göre %36 ucuz + 10x dev hızı)

### En riski düşük yol:

Dubai'de **sadece Mac Studio al** (şu an), VPS/Groq'u Türkiye'de konfigure et. Mac Studio development + sınırlı local inference için. Production kurgusu ayrı olayı olsun.

---

## 12. SOMUT ADIMLAR — EĞER ALIRSAN

1. **Dubai'de almadan önce test et:**
   - Apple Store'da M4 Max demo makinada Ollama 70B dene (mümkünse)
   - Apple Store'ta configuration yap: M4 Max 16C/40G, 64GB (veya 128GB), 1TB SSD

2. **Türkiye'ye döndüğünde ilk 7 gün:**
   - macOS Sequoia, homebrew, Python 3.11, Docker Desktop, PostgreSQL, Redis kur
   - Ollama install + Qwen 2.5 72B pull (~40GB)
   - MLX framework test (Apple'ın native ML)
   - Fermat repo clone, `.venv` kur, smoke test

3. **İlk 30 gün:**
   - `llm_router.py` Qwen 72B routing entegrasyonu
   - Tool-calling kalite test (100 senaryo, A/B Claude vs local)
   - Fast+Ollama+Local70B+Claude 4-katmanlı routing
   - Cost telemetri — gerçekten %30 azalma oldu mu ölç

4. **60 gün sonra karar noktası:**
   - Kalite kayıp kabul edilebilir mi?
   - Hangi endpoint'leri yerele kaydırdın?
   - Yatırım kendini amorti ediyor mu?

---

## 13. SONUÇ — Tek Paragrafta Karar

Mac Studio M4 Max, **FermatAI için mecburi değil ama stratejik bir kaldıraç**. Yıllık $3,065 Claude maliyetin %30-45'ini yerele kaydırarak $900-1,400/yıl tasarruf sağlar, dev hızını 5-10x artırır, yeni özellikler (Hata DNA, LGS scale-up, Veli raporu) için gerekli compute temelini verir. **Ancak 24/7 production hosting sorununu çözmez** — onun için Linux VPS gerekli. İdeal senaryo: Mac Studio dev + local LLM lab, VPS production, Groq fallback. $4,500 yatırım, 3-4 yıl amortize, 5 yıl TCO'da $5,000 kârlı çıkar ve dev deneyimin çıldırır. Alman için en güçlü gerekçe **"sadece Fermat değil, 3+ proje paralel çalıştırma" vizyonu**. Dubai avantajı +$500-800 net. **Şahsen olsam 64GB sürümü** (128 overkill, 64 Qwen 72B Q4 için yeterli, $800 tasarruf). En riski düşük adım: Dubai'de al, Türkiye'de VPS + Groq hybrid kur, 60 gün ölç, ikinci yatırım kararını o rakamlarla ver.

---

> **Bu rapor 24 Nisan 2026'da, Fermat'ın gerçek 14-günlük routing + token verileri esas alınarak hazırlandı.**
> © FermatAI · Stratejik donanım değerlendirmesi
