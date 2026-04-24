# 🚀 FermatAI — Yeni Sezon Devreye Alma Rehberi

**Tarih:** 1 Eylül 2026 hedef canlı tarihi
**Hazırlık:** 20 Nisan 2026 itibarıyla 7 Fikir + 3 Kampanya + Güvenlik Guard hazır, flag'ler kapalı.

---

## ⚠️ Kritik Kural
**"Hiçbir kullanıcıya mesaj atma"** — tüm hazırlıklar bu kurala uyar. Aşağıdaki adımlar takip edilmediği sürece hiçbir proaktif mesaj gitmez.

---

## 📋 Ön Hazırlık Checklist (Ağustos sonu — 1 hafta önce)

### 1. Eyotek verisi senkron
- [ ] Eyotek'ten yeni sezon dönemi seçili olduğunu doğrula
- [ ] `python eyotek_agent.py` → öğrenci listesini senkronla (yeni kayıtlar dahil)
- [ ] `python sync_exams.py` → mevcut deneme verilerini çek
- [ ] DB kontrolü: `SELECT COUNT(*) FROM students WHERE status='active'`

### 2. Atlas + sentiment reset
- [ ] `UPDATE student_insights SET active=FALSE WHERE created_at < '2026-08-01'` — eski sezon verilerini pasife çek
- [ ] `UPDATE atlas_suggestions SET status='uygulandi' WHERE status='yeni' AND created_at < '2026-06-01'` — eski uyarıları kapat
- [ ] Yeni sezona temiz başla

### 3. ACL + rol güncellemeleri
- [ ] Yeni öğretmen kayıtları acl_users'a (`staff` senkronu)
- [ ] Eski mezun öğrencilerin rollerini `mezun` yap (opsiyonel ayrı tablo)
- [ ] Veli numaralarının doğruluğu (ilk hafta kritik)

---

## 🎛️ Flag Aktivasyon Sırası (1 Eylül 2026)

`.env` dosyasına ekle — **sırayı değiştirme**, her flag'den sonra 1-2 gün gözlem yap:

### Faz 1: Core Insight (Gün 1)
```bash
# İçeride çalışır, kullanıcıya mesaj göndermez
# Sadece DB'ye yazar, Claude context'e verir
# Risk: ÇOK DÜŞÜK
OUTREACH_ENABLED=false   # HENÜZ KAPALI
```
**Kontrol:**
- Öğrenciler chat'e girince active_insights context'te görünüyor mu?
- `SELECT COUNT(*) FROM student_insights WHERE active=TRUE` büyüyor mu?

### Faz 2: Admin/Neo Outreach (Gün 2-3)
```bash
OUTREACH_ENABLED=true
ALERTS_ACTIVE=true        # Alarm sistemi Neo'ya bildirir
```
**Kontrol:**
- `alert_system.py --test` → Neo'ya WhatsApp alarm gelir mi?
- Öğrenci/öğretmene HİÇ mesaj gitmez (Neo admin whitelist'inde)
- `SELECT * FROM outreach_pending WHERE status='pending' LIMIT 5` → beklemedeki mesajlar Neo'ya özel mi?

### Faz 3: Öğretmen Onboarding (Gün 4-7) — MANUEL TETİK
Neo kendisi gönderir, otomatik değil:
```python
# onboarding_runner.py (henüz yazılmadı — Neo'nun UI'sı gerekli)
from onboarding_templates import get_template
metin = get_template("ogretmen_davet", name="Kardelen")
# Neo Wix/panel üzerinden veya manuel WhatsApp gönderiyor
```
**Kontrol:**
- İlk 3 öğretmenle pilot (Orhan, Merve, Kardelen)
- 7 gün gözlem: çatışma, yanlış cevap, confusion var mı?
- Atlas_suggestions yeni kayıtlara bak

### Faz 4: Öğrenci Davet (Hafta 2)
```bash
# Neo onaylı toplu aktivasyon — script değil manuel atma
```
Grup bazlı başlat: önce 12 SAY (20 öğrenci) → 11 SAY → 11 EA → diğer

### Faz 5: Yaz/Sezon Modülleri (Temmuz & Ekim)
```bash
YAZ_KAMPI_ACTIVE=true     # SADECE Temmuz son haftası
VELI_MODULE_ACTIVE=true   # Ekim'de (veli güvene aldıktan sonra)
TELAFI_ACTIVE=true        # Hafta 3+ sonrası
```

---

## 🧪 Test Senaryoları (her faz sonrası)

### Faz 1 Test (Insight)
```bash
# Simüle: bir öğrenci mesaj atsa ne olur?
python -c "
import asyncio
from insight_extractor import run_extraction_background
asyncio.run(run_extraction_background(
    '905075530945', 174,
    'bugun matematik cok zor geldi, itu yerine bogazici dusunuyorum',
    ''
))
"
# Beklenti: mood + goal_evolution kaydı düşer
# Kontrol: SELECT * FROM student_insights WHERE soz_no=174 ORDER BY id DESC LIMIT 3
```

### Faz 2 Test (Guard)
```bash
python -c "
import asyncio
from whatsapp_bridge import send_wa_message
async def m():
    # Yabancı numaraya dene
    r = await send_wa_message('905000000000', '[TEST]', _outreach=True, _reason='test')
    print(f'sent={r} (False olmali)')
asyncio.run(m())
"
# Beklenti: sent=False, outreach_pending'e kayıt düşer
```

### Faz 3 Test (Öğretmen)
```bash
# Öğretmenin web koduyla giriş simülasyonu:
# 1. Manuel WhatsApp'tan Neo "Kardelen Hocam sana ogretmen paneli acildi..." gönderir
# 2. Kardelen "web kodu" yazar
# 3. OTP gelir, Kardelen giriş yapar
# 4. Dashboard açılır, sınıf verileri görünür
```

---

## 📊 Günlük Monitoring (ilk 30 gün)

Neo sabah 08:00 ve akşam 20:00 kontrol etmeli:

```bash
# Aktif kullanıcılar (son 24 saat)
python -c "
import asyncio
from db_pool import db_fetch
async def m():
    rows = await db_fetch('''
      SELECT role, COUNT(DISTINCT phone) AS aktif
      FROM routing_stats
      WHERE created_at > NOW() - INTERVAL '1 day'
      GROUP BY role
    ''')
    for r in rows:
        print(f'  {r[\"role\"]}: {r[\"aktif\"]}')
asyncio.run(m())
"

# Outreach pending (onay bekleyen mesajlar)
python -c "
import asyncio
from db_pool import db_fetch
async def m():
    rows = await db_fetch('SELECT reason, COUNT(*) c FROM outreach_pending WHERE status=\\'pending\\' GROUP BY reason')
    for r in rows: print(f'  {r[\"reason\"]}: {r[\"c\"]}')
asyncio.run(m())
"

# Yeni atlas suggestions
python -c "
import asyncio
from db_pool import db_fetch
async def m():
    rows = await db_fetch('SELECT id, title, severity FROM atlas_suggestions WHERE status=\\'yeni\\' ORDER BY created_at DESC LIMIT 10')
    for r in rows: print(f'  #{r[\"id\"]} [{r[\"severity\"]}] {r[\"title\"][:70]}')
asyncio.run(m())
"
```

---

## 🔒 Acil Durum Kapatma (Kill Switch)

Sorun olursa:
```bash
# .env dosyasını düzenle:
OUTREACH_ENABLED=false   # TÜM proaktif mesajlar durur
# Bridge restart:
# Mevcut PID'i bul: netstat -ano | findstr :8001
# Öldür + yeniden başlat
```

**Spesifik alanlar:**
- Alarm: `ALERTS_ACTIVE=false`
- Telafi: `TELAFI_ACTIVE=false`
- Veli: `VELI_MODULE_ACTIVE=false`

Bridge restart gerekir — env değişiklikleri runtime okunur ama temiz state için restart önerilir.

---

## 📈 Başarı Metrikleri (Hedef)

| Metrik | Bugün (20 Nisan) | Hedef Ekim | Hedef Aralık |
|--------|-----------------|------------|--------------|
| Öğrenci aktif | %18 | %50 | %70 |
| Öğretmen aktif | %0 | %40 | %70 |
| Rehber aktif | 2 | 4 (tüm) | 4 |
| Veli aktif | 0 | %30 | %60 |
| Maliyet/ay | $55 | $80 | $120 |
| Atlas yeni uyarı/hafta | 3-5 | <2 | <1 |

---

## 🧠 Neo için Zihinsel Model

FermatAI bir sistem değil, bir **"pedagojik sinyal platformu"**. Her insight, her sorgu, her chart — öğrencinin gerçek zamanlı mental modelini oluşturur.

Yeni sezonda 3 ilke:
1. **"Sessiz gözlemci ama sesli koç"** — Insight sessizce toplanır, müdahale tetikleyici olur
2. **"Her platform kendi doğasında"** — WhatsApp hızlı, Web derin, ikisi de uyumlu cevap
3. **"Veliyi koruyarak kazanmak"** — önce öğrenci+öğretmen olgun, sonra veli

---

## 📞 Sorun Olursa
Claude Code'da: "KALDIGIM oku, şu durumda ne yapmalıyım?" → son 22.1n-vizyon bloğu rehber.

Neo'nun manuel kontrolleri: ngrok online mu, fermategitimkurumlari.com/fermatai açılıyor mu, outreach_pending boş mu.

**🎯 İlk 30 gün hedef: 0 krizde rollback, kullanıcı sayısı stabil artış.**
