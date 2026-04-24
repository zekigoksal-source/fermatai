# FermatAI VPS Migration — Master Checklist

> Bu dosya her adımı sırayla işaretleyeceğimiz ana takip listesi.
> Her ✅ = tamamlandı, her ⏳ = devam ediyor, her ⚠️ = dikkat!

## FAZ 0 — Ön Hazırlık (24 Nisan gece, ben yapıyorum)

- [x] Mevcut sistem audit (env, DB boyutu, kod hacmi)
- [x] `.env`'e GROQ_API_KEY eklendi (güvenli, git ignored)
- [x] VPS setup klasörü oluşturuldu
- [x] systemd service dosyaları hazırlandı
- [x] nginx config hazırlandı
- [x] Deploy + backup scripts hazırlandı
- [x] `.env.production.template` hazırlandı
- [x] first_install.sh hazırlandı (VPS'te one-shot kurulum)
- [ ] `llm_router.py`'e Groq handler ekle (sabah)
- [ ] Groq A/B test senaryoları belirle (sabah)

## FAZ 1 — Hetzner KYC + VPS (Sen yarın sabah, 30 dk)

- [ ] Hetzner kimlik doğrulama (pasaport veya ehliyet fotoğrafı)
- [ ] Ödeme yöntemi onaylat (kredi kartı)
- [ ] Hetzner Cloud Console'a gir
- [ ] "New Project" → adı: **FermatAI**
- [ ] "Add Server" → konum **Nuremberg** veya **Falkenstein** (Almanya)
- [ ] Image: **Ubuntu 24.04**
- [ ] Type: **CCX33** (8 dedicated vCPU, 32 GB RAM, 240 GB SSD)
- [ ] SSH Key: "Add SSH Key" → (birlikte oluşturacağız)
- [ ] Server adı: `fermatai-prod`
- [ ] "Create & Buy now" — ilk fatura €35 peşin
- [ ] **VPS IP adresini bana yaz** → `XX.XX.XX.XX`

## FAZ 2 — GitHub Repo Kurulumu (Sen, 10 dk)

- [ ] GitHub'da hesap kontrolü (varsa devam, yoksa aç)
- [ ] Yeni repo: **Private**, ad: `fermatai` (veya `fermat-ai`)
- [ ] README + .gitignore eklemeden empty repo
- [ ] **Repo URL'i bana yaz** → `git@github.com:neo/fermatai.git`
- [ ] Personal Access Token oluştur (scope: `repo`) — deploy key olarak kullanılacak

## FAZ 3 — SSH Key + İlk Bağlantı (Birlikte, 15 dk)

- [ ] Laptop'ta SSH key oluştur (`~/.ssh/id_ed25519_fermatai`)
- [ ] Public key'i Hetzner VPS'e ekle (`~/.ssh/authorized_keys`)
- [ ] Ben: `ssh root@IP` ile VPS'e bağlan — test
- [ ] VPS'te `neo` adında non-root user oluştur
- [ ] Sudo yetkisi ver (`usermod -aG sudo neo`)
- [ ] Root SSH login kapat (`PermitRootLogin no`)
- [ ] **KRİTİK:** root password değiştir, acil durum için kaydet

## FAZ 4 — first_install.sh Çalıştır (Ben, 1-2 saat otomatik)

Script şunları kuracak:
- [ ] `apt update && upgrade` (sistem güncel)
- [ ] `unattended-upgrades` (otomatik güvenlik patchi)
- [ ] UFW firewall (22 SSH + 80 HTTP + 443 HTTPS açık)
- [ ] fail2ban (SSH brute force koruması)
- [ ] Docker + docker-compose
- [ ] PostgreSQL 16 (Docker container)
- [ ] pgvector 0.8 (Postgres extension)
- [ ] Redis (Docker container)
- [ ] Python 3.11 + pip + venv
- [ ] nginx + certbot (Let's Encrypt)
- [ ] Playwright + Chromium (headless)
- [ ] Git + repo clone (GitHub'dan)
- [ ] `.venv` + `pip install -r requirements.txt`

## FAZ 5 — Environment + Database (Ben, 30 dk)

- [ ] `.env.production` oluştur (VPS'te, .env.template'ten)
- [ ] Tüm 28 env variable doldur (Groq dahil)
- [ ] `chmod 600 .env` (sadece owner okur)
- [ ] Laptop'ta `pg_dump fermatai | gzip > fermatai.sql.gz`
- [ ] `scp fermatai.sql.gz neo@VPS:/tmp/` (dump'ı VPS'e gönder)
- [ ] VPS'te `gunzip < fermatai.sql.gz | psql fermatai` (restore)
- [ ] Smoke test: `SELECT count(*) FROM students;` → 125 olmalı
- [ ] pgvector extension aktif mi? `\dx` ile kontrol

## FAZ 6 — Bridge Başlatma + Smoke Test (Ben, 30 dk)

- [ ] systemd service yerleştir: `fermatai-bridge.service`
- [ ] `systemctl daemon-reload`
- [ ] `systemctl enable fermatai-bridge`
- [ ] `systemctl start fermatai-bridge`
- [ ] `systemctl status` → "active (running)" gözükmeli
- [ ] `journalctl -u fermatai-bridge -n 50` → hata var mı?
- [ ] Curl test: `curl http://localhost:8001/chat` → HTTP 200 beklenir
- [ ] pgvector query test: RAG search çalışıyor mu?
- [ ] Analytics cache build: ilk yenileme

## FAZ 7 — Domain + SSL (Ben, 20 dk)

- [ ] `fermategitimkurumlari.com` DNS ayarı:
  - A record: `api.fermategitimkurumlari.com` → VPS IP
  - TTL: 3600
- [ ] Nginx config yerleştir: `/etc/nginx/sites-available/fermatai`
- [ ] `ln -s sites-enabled/fermatai`
- [ ] `nginx -t` (config test)
- [ ] `systemctl reload nginx`
- [ ] `certbot --nginx -d api.fermategitimkurumlari.com`
- [ ] Let's Encrypt otomatik yenileme aktif
- [ ] HTTPS test: `curl https://api.fermategitimkurumlari.com/chat`

## FAZ 8 — Groq Integration (Ben, 2-3 saat)

- [ ] `llm_router.py` düzenle:
  - [ ] Yeni kategoriler: `simple_tool`, `conceptual`, `complex`, `empathy`
  - [ ] Groq handler fonksiyonu
  - [ ] Routing: simple_tool + conceptual → Groq, complex + empathy → Claude
- [ ] `groq_handler.py` dosyası oluştur (API çağrısı wrapper)
- [ ] `.env` güncelle: `LLM_PROVIDER=hybrid_with_groq`
- [ ] `test_groq_integration.py` yaz (20 senaryo)
- [ ] A/B test: 50 mesaj Groq, 50 Claude karşılaştır
- [ ] Kalite skoru %80+ ise Groq prod'a al

## FAZ 9 — Meta WhatsApp Webhook Switch (Birlikte, 10 dk — KRİTİK)

**⚠️ Bu adımda 30 saniye downtime olabilir.**

- [ ] VPS bridge %100 çalışıyor + test mesaj OK ✅ (kontrol)
- [ ] Meta Developer Dashboard'a gir
- [ ] WhatsApp Business API → Webhooks
- [ ] Callback URL: `https://ngrok-eski.ngrok.io/webhook` → `https://api.fermategitimkurumlari.com/webhook`
- [ ] Verify Token aynı kalıyor (değişirse VPS'te de güncellenmeli)
- [ ] "Verify and Save" bas
- [ ] Test: Admin telefondan "sistem durum" mesajı at
- [ ] VPS log'unda mesaj görünüyor mu? (`journalctl -u fermatai-bridge -f`)
- [ ] Cevap WhatsApp'a geldi mi?
- [ ] ✅ Gelirse, laptop bridge'i kapat (`taskkill /PID ...`)
- [ ] Laptop ngrok'u da kapatabilirsin

## FAZ 10 — Monitoring + Backup (Ben, 30 dk)

- [ ] Cron job: `backup_db.sh` günlük saat 03:00
- [ ] Yedekler `/opt/backups/fermatai/` + rclone ile uzak bulut (B2/S3)
- [ ] Hetzner snapshot (haftalık manuel veya otomatik)
- [ ] Log rotation (systemd journald max 500MB)
- [ ] Uptime monitoring: UptimeRobot ücretsiz (https ping 5dk'da)
- [ ] Hata alarmı: kritik servisler down olursa Neo'ya WP

## FAZ 11 — Dev Workflow Doğrulama (Birlikte, 30 dk)

Test senaryosu: Küçük bir bug fix + deploy:

- [ ] Neo: "Fast response'a şu keyword ekle"
- [ ] Ben: `fast_responses.py` edit (laptop)
- [ ] Ben: `git add` + `commit` + `push` (GitHub'a)
- [ ] Ben: `ssh vps "cd /opt/fermatai && git pull && systemctl restart fermatai-bridge"`
- [ ] Neo: WhatsApp'tan test keyword
- [ ] ✅ Cevap gelirse: dev workflow hazır!

## FAZ 12 — Sonrası (1 hafta izleme)

- [ ] Günlük log incele: hata var mı?
- [ ] Claude + Groq maliyet takip: hedefte miyiz?
- [ ] Session keeper: Eyotek bağlantısı hâlâ sağlam mı?
- [ ] Öğrenci feedback: "yavaşladı mı?", "cevap geldi mi?"
- [ ] Sorun çıkarsa rollback planı hazır: webhook laptop'a geri

---

## 🚨 Acil Durum Rollback Planı

Eğer VPS'te büyük bir sorun çıkarsa ve canlı öğrenciler etkileniyorsa:

1. **30 saniyede:** Meta webhook URL'i eski ngrok'a geri çevir
2. **Laptop bridge'i yeniden başlat** (zaten kod aynı)
3. **Fermat eski düzende çalışır** — kesinti minimal
4. **VPS'te sorunu ayıkla, hazırlayınca tekrar switch et**

## 📋 Hazırlık Sonrası Teslim Edilen Dosyalar

Bu klasörde:
- ✅ `README.md`
- ✅ `MIGRATION_PLAN_VPS.md` (bu dosya)
- ✅ `.env.production.template`
- ✅ `systemd/fermatai-bridge.service`
- ✅ `nginx/fermatai.conf`
- ✅ `scripts/first_install.sh`
- ✅ `scripts/deploy.sh`
- ✅ `scripts/backup_db.sh`
- ✅ `scripts/restore_db.sh`
