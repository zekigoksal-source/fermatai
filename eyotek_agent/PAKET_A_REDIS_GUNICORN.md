# Paket A — Redis + Multi-Worker Aktivasyon Rehberi (22.1n-neo)

## Durum

✅ **Altyapı HAZIR** — `session_store.py` yazıldı (memory/redis otomatik adapter)
✅ **Docker Compose** — Redis servis tanımı eklendi (`docker-compose.yml`)
🟡 **Aktivasyon bekliyor** — Neo'nun `REDIS_URL=...` env set etmesi ile çalışır

Sistem şu an **MEMORY mode**'da, yani davranış ZERO değişim. Neo hazır olunca Redis'e geçer.

## Neden Bekliyor?

Multi-worker geçişi risk taşır:
- In-memory state (`_AGENT_SESSIONS`, `_PHONE_LOCKS`) bir worker'da yaşıyor
- 4 worker'a geçiş → state paylaşımı gerek → Redis şart
- Kod migration parçalı olmalı, tek seferde değil

**Bu yüzden kod "hazır ama kapalı"** — Neo sezon başında aktif eder.

## Kapasite Etkisi (Beklenen)

| Mod | Eşzamanlı Kullanıcı | Claude P95 | Durum |
|-----|---------------------|------------|-------|
| Şimdiki (single worker) | 8 | 54s | Yeterli (yaz öncesi) |
| Multi-worker + Redis | 32 | 30-40s | Yeni sezon (Eylül 2026) |

## Aktivasyon Adımları (Ağustos 2026 civarı)

### 1. Redis'i başlat
```powershell
cd C:\Users\zekig\OneDrive\Desktop\FermatAI
docker-compose up -d redis
```

Doğrulama:
```powershell
docker exec fermat_redis redis-cli ping
# PONG
```

### 2. `.env` güncelle
```
REDIS_URL=redis://localhost:6379
FASTAPI_WORKERS=4
```

### 3. Python bağımlılığı
```powershell
cd eyotek_agent
.venv\Scripts\pip install redis[hiredis]
```

### 4. Bridge code migration (yapılacak iş)

`whatsapp_bridge.py` içinde şu globaller Redis'e taşınmalı:
- `_AGENT_SESSIONS` → Redis `agent:<phone>` key
- `_PHONE_LOCKS` → Redis distributed lock (redlock)
- `_PHONE_QUEUES` → Redis `queue:<phone>` list
- `_TEMP_BANS` → Redis `ban:<phone>` key (TTL ile)
- `_CAPACITY_COUNTS` → Redis sorted set

**Bu migration'ı yapmak için 1 gün lazım** — session_store.py altyapı hazır, sadece kullanım yerlerini taşımak kalır.

### 5. Multi-worker başlatma (Windows — waitress)
```powershell
cd eyotek_agent
.venv\Scripts\pip install waitress
.venv\Scripts\waitress-serve --host 0.0.0.0 --port 8001 --threads 4 whatsapp_bridge:app
```

### Alternatif (Linux — gunicorn)
```bash
pip install gunicorn uvicorn[standard]
gunicorn whatsapp_bridge:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001
```

## Sticky Routing (Opsiyonel)

Aynı phone hep aynı worker'a gitmek zorunda değil (Redis shared state sayesinde). Ama latency için sticky routing iyi olur:
- Nginx upstream `hash $remote_addr consistent;` (ancak phone header'dan hash alınmalı)
- Caddy config benzeri

**Şimdilik gerek yok** — Redis shared state her worker'da state'i senkron tutar.

## Test Planı (Aktivasyon Öncesi)

1. `session_store.py` → Redis mode test (`python session_store.py`)
2. Tek worker + Redis → davranış değişmemeli
3. 2 worker + Redis → aynı phone farklı worker'a gitse bile lock çalışmalı
4. 4 worker + Redis → concurrent 30 mesaj → hepsi sırayla işlenmeli
5. Load test: `ab -n 100 -c 20 http://localhost:8001/health`

## Risk ve Azaltma

| Risk | Azaltma |
|------|---------|
| Redis down → tüm session kayıp | `allkeys-lru` policy + persistent volume |
| Worker restart → lock orphan | Redis lock TTL 5dk auto-release |
| Memory vs Redis davranış farkı | Aynı abstraction, aynı API |
| Migration sırasında outage | Önce tek worker + Redis test, sonra multi |

## Şu An Durum (20 Nisan 2026)

- ✅ `session_store.py` hazır — memory mode default
- ✅ Docker Redis service tanımlı (`docker-compose.yml`)
- ✅ Bu rehber yazıldı
- 🟡 `_PHONE_LOCKS` etc migration — Eylül öncesi yapılacak
- 🟡 Waitress multi-thread setup — Eylül öncesi

**Şu anki sistem**: `MemoryStore` ile single worker — davranış DEĞİŞMEZ.

Neo "Eylül için hazırla" diyene kadar bu iş pasif beklemede.
