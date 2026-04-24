# FermatAI VPS Migration — Operational Rehberi

> **Tarih:** 24-25 Nisan 2026 · Hetzner CCX33 + Groq API entegrasyonu
> **Amaç:** Laptop 24/7 açık kalmasın, Fermat Almanya'da production-grade çalışsın
> **Migration süresi:** 1 hafta (tempo), 2-3 gün (agresif)

## 📁 Klasör İçeriği

```
vps_setup/
├── README.md                           (bu dosya)
├── MIGRATION_PLAN_VPS.md               (master checklist, her adım)
├── .env.production.template            (VPS env şablonu)
├── systemd/
│   ├── fermatai-bridge.service         (FastAPI bridge - uvicorn)
│   └── fermatai-keeper.service         (Session keeper — opsiyonel)
├── nginx/
│   └── fermatai.conf                   (reverse proxy + SSL)
└── scripts/
    ├── first_install.sh                (VPS'e ilk kurulum, tek seferlik)
    ├── deploy.sh                       (her git push sonrası)
    ├── backup_db.sh                    (günlük PostgreSQL yedek)
    └── restore_db.sh                   (kriz anında geri yükle)
```

## 🚦 Yarın Akşam Canlıya Geçiş Akışı

1. **Sen:** Hetzner KYC tamamla, CCX33 VPS kur (15 dk)
2. **Sen:** GitHub'da `fermatai` private repo aç (5 dk) — Neo'nun GitHub hesabı?
3. **Birlikte:** SSH key kur, VPS IP'yi bana ver
4. **Ben:** `first_install.sh` çalıştır (VPS'te, 1 saat otomatik)
5. **Ben:** PostgreSQL dump alıp VPS'e restore (20 dk)
6. **Ben:** `.env.production` doldur + service'i başlat (15 dk)
7. **Ben:** Domain DNS kur + Let's Encrypt SSL (20 dk)
8. **Ben:** Groq API integration (`llm_router.py` patch, 2 saat)
9. **Birlikte:** Meta WhatsApp webhook URL değiştir (5 dk)
10. **Test:** Bir mesaj at, VPS cevap versin. Laptop bridge kapat.

**Tahmini toplam süre:** 4-6 saat aktif, bir tam akşam.

## ⚠️ Kritik Notlar

- **.env dosyası ASLA git'e commit EDİLMEYECEK** (gitignore güvenli)
- **Laptop bridge migration tamamlanana kadar ÇALIŞMAYA DEVAM**
- **Meta webhook switch son adım** — VPS %100 hazır olmadan dokunma
- **Rollback planı hazır:** Sorun olursa webhook'u laptop'a geri çevir, 30 saniye
- **Playwright/Chrome VPS'te headless** — Eyotek cookie management ayrı plan (yeni sezona taşınabilir, sınav dönemi yazma işlemi zaten kapalı)

## 🔐 Güvenlik Checklist (Yarın VPS açılınca)

- [ ] SSH key-only login (parola kapalı)
- [ ] UFW firewall (22 + 80 + 443 + 5432 sadece localhost)
- [ ] fail2ban (brute force koruması)
- [ ] PostgreSQL dış bağlantı kapalı (sadece localhost)
- [ ] Automatic security updates (`unattended-upgrades`)
- [ ] `.env` dosyası 600 permission (`chmod 600 .env`)
- [ ] Groq + Claude + Meta token'ları sadece VPS'te

## 📊 Beklenen Maliyet (aylık)

| Kalem | Tahmin |
|---|---|
| Hetzner CCX33 | €35 (~$38) |
| Snapshot backup | $3 |
| Groq API | $15-25 |
| Claude API (%55 azaltılmış) | ~$140 |
| **TOPLAM** | **~$200/ay** |

Mevcut: $253/ay → **$50/ay kurtarış + 7/24 uptime + laptop özgürlüğü**
