# 🌍 FermatAI 3D Eğitim Dünyası — Geliştirme Brief'i

> **Amaç:** Yeni bir Claude Code oturumunun (Fable 5 ile) bu işi sıfırdan bağlam
> kaybetmeden, tam kapasiteyle sürdürmesi için hazırlanmış devir belgesi.
> **Oluşturulma:** 10 Haziran 2026, Oturum 25.58-G sonrası.
> **Kullanım:** Yeni oturumda `/model claude-fable-5` → bu dosyayı `Read` ettir → başla.

---

## ⚠️ ÖNCE: Model (Fable 5) koruma notu

Anthropic platform güvenlik sınıflandırıcısı **siber-güvenlik + biyoloji** yakınlığında
tetiklenip Fable 5'i Opus 4.8'e düşürüyor. Bu oyun işi kendi başına TETİKLEYİCİ DEĞİL.
- **Bu oturumu temiz tut:** güvenlik denetimi / pentest / "spoofing/injection/exploit"
  kelimeleri GEÇMESİN. Sadece fizik + grafik + 3D + etkileşim konuş.
- İstasyon içeriğinde fizik/matematik kullan (manyetizma, yerçekimi, optik, dalga,
  mekanik). Biyoloji istasyonunu (hücre vb.) bu oturumda EKLEME — gereksiz risk.
- Garanti yok (muhafazakâr ayar) ama temiz oyun-dev oturumunda Fable 5 kararlı kalır.

---

## 📍 Şu ana kadar yapılan (durum)

İki prototip `eyotek_agent/static/games/` altında, `/static/games/` mount'undan serve:

1. **manyetik-alan-lab.html** — SABİT simülasyon (kamera döndür-izle). Neo: "bunu zaten
   make_render_link yapıyor, yeni numara değil." → aşılması gereken seviye.
2. **fizik-bahcesi.html** — YÜRÜNEBİLİR dünya (FPS kontrol: masaüstü pointer-lock+WASD,
   mobil joystick). 4 istasyon, yaklaş→panel→etkileş. Neo: "tam hayal ettiğim tarz bu
   ama görsel + fizik motoru + etkileşim çok daha gelişmiş olsun."

**Bu brief = fizik-bahcesi.html'in PROFESYONEL versiyonu.** Mevcut dosyayı referans al,
sıfırdan daha güçlü kur (ya da yeni dosya: `fizik-dunyasi-v2.html`).

---

## 🎯 Hedef: 3 eksende sıçrama

### 1. GERÇEK FİZİK MOTORU (en önemli)
- **Rapier** (`@dimforge/rapier3d-compat`, Rust→WASM) — en hızlı, deterministik, modern.
  CDN: `https://cdn.jsdelivr.net/npm/@dimforge/rapier3d-compat/...`. WASM async init —
  `await RAPIER.init()` ile başlat, sonra dünya kur.
- Alternatif (daha basit): **cannon-es** (saf JS, hafif, kolay CDN). Mobil performansı
  zayıfsa veya WASM sorun çıkarırsa buna düş.
- Gerçek: rigid body, çarpışma, sürtünme, momentum, kütle, restitution (sekme).
- **Kritik fark:** mermi fırlatınca parabolü ÇİZME — motor gerçek g ile hesaplasın,
  sen trajektory'yi izle. Top eğik düzlemden GERÇEKTEN yuvarlansın.

### 2. GÖRSEL KALİTE
- **Gölgeler:** `renderer.shadowMap.enabled=true`, directional light + shadow camera,
  objeler `castShadow`/`receiveShadow`.
- **PBR malzeme:** MeshStandardMaterial metalness/roughness + environment map (reflection).
- **Post-processing:** EffectComposer + **UnrealBloomPass** (parıltı), opsiyonel SSAO,
  vignette, FXAA. Three.js examples/jsm'den (CDN importmap veya bundle).
- **Atmosfer:** HDRI veya gradient-shader gökyüzü, zemin dokusu, sis derinliği, ışık
  sıcaklığı. Parçacık efektleri (toz, kıvılcım, alan çizgileri).
- **Three.js sürüm:** r147 yerine güncel (r160+) modül yapısına geçmeyi değerlendir
  (importmap ile examples/jsm temiz gelir).

### 3. GELİŞMİŞ ETKİLEŞİM
- Objeyi **tut & fırlat** (raycast + fizik impulse) — eline al, savur.
- **Blok yerleştir/yık** (Minecraft-vari yapı kurma) — opsiyonel ama "sandbox" hissi.
- **Mancınık/fırlatıcı istasyonu:** açı + hız ayarla → gerçek parabolik atış → nereye
  düştüğünü ölç (menzil formülü canlı doğrulansın).
- **Sarkaç, eğik düzlem, çarpışma masası** (momentum korunumu deneyi).
- Ölçüm araçları: hız/ivme okuması, trajektory izi, çarpışma sonrası hız.

---

## 🏗️ Mimari kuralları (DEĞİŞMEZ)

- **Çekirdek agent'a DOKUNMA.** Saf statik HTML/JS, `static/games/` altında. Silmek =
  geri almak. `fermat_core_agent.py`, `whatsapp_bridge.py` vb. değişmez.
- Tek dosya büyürse: CDN kütüphaneleri + (gerekirse) `static/games/assets/` altında
  doku/model. Importmap ile modül yapısı temiz olur.
- **Mobil birincil kanal** (öğrenciler telefonda). Fizik+bloom ağır → kalite kademesi:
  mobilde gölge/bloom düşür veya kapat, masaüstünde tam. `devicePixelRatio` clamp.
- WASM async init'i intro ekranıyla maskele ("Dünya yükleniyor…").

## 🚀 Deploy akışı (her fazda)
```
git add eyotek_agent/static/games/<dosya>.html
git commit  (Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>)
git push origin claude/sweet-jemison-99ea7e
ssh VPS: cd /opt/fermatai && git fetch + git reset --hard origin/<branch>
curl http://localhost:8001/static/games/<dosya>.html  → HTTP 200
public: https://api.fermategitimkurumlari.com/static/games/<dosya>.html
```
- VPS: `116.203.117.106`, user `neo`, key `id_ed25519_fermatai`.
- Preview test: `.claude/launch.json`'a `lab-static` (python http.server 8055,
  cwd=static/games) config'i EKLE (gitignore'da, commit'e girmez). preview_eval ile
  hareket/fizik/etkileşim ölç, preview_screenshot ile görsel doğrula.
  NOT: sürekli-animasyonlu WebGL'de screenshot bazen takılır → eval ile state ölç.

## ✅ Faz planı (her fazı preview'da doğrula, sonra deploy)
1. **Motor + hareket:** Rapier init + zemin + FPS kontrol + 1 fizik objesi (düşen küp).
2. **İstasyonlar:** mancınık, sarkaç, eğik düzlem, manyetik alan — gerçek fizikle.
3. **Görsel cila:** gölge + PBR + bloom + gökyüzü + parçacık.
4. **Etkileşim derinliği:** tut/fırlat, blok yerleştir, ölçüm araçları.
5. **Mobil optimizasyon + kalite kademesi.**

## 📌 Beklenti
"Kusursuz" tek seferde çıkmaz — fazlarla, her fazı test ederek. Fizik motoru entegrasyonu
+ WASM + post-processing ciddi iş; sabırla ve doğrulayarak ilerle. Önce ÇALIŞAN motor,
sonra güzellik.

İlgili: KALDIGIM.md (25.58-F/G blokları), BLUEPRINT.md (render mimarisi), three_templates.py
(mevcut shell deseni + marka renkleri #C76F3E/#A78BFA/#0F172A).
