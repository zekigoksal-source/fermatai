# Ollama Hız Optimizasyonu (Paket C — 22.1n-neo)

## Server Tarafı (Windows — bir kere set edilir)

### Environment Variables (Kalıcı)

Windows ayarları → Sistem → Gelişmiş → Ortam Değişkenleri → Kullanıcı değişkenleri:

```
OLLAMA_NUM_PARALLEL=2
OLLAMA_MAX_LOADED_MODELS=2
OLLAMA_KEEP_ALIVE=15m
OLLAMA_FLASH_ATTENTION=1
```

### Etkisi

| Değişken | Ne yapar | Kazanım |
|----------|----------|---------|
| `OLLAMA_NUM_PARALLEL=2` | Aynı modelde 2 paralel istek | P95 22s → ~10s |
| `OLLAMA_MAX_LOADED_MODELS=2` | qwen2.5:7b + qwen2.5:3b aynı anda RAM'de | Backup model kullanımı |
| `OLLAMA_KEEP_ALIVE=15m` | Model 15dk idle'dan sonra unload (cold start önler) | Cold 9.5s → 0s |
| `OLLAMA_FLASH_ATTENTION=1` | Flash Attention (daha az VRAM, daha hızlı) | ~%20 hız |

### Değiştirme sonrası

1. **Ollama servisini yeniden başlat**:
   ```powershell
   Stop-Service Ollama
   Start-Service Ollama
   ```

2. Doğrulama:
   ```powershell
   Get-Service Ollama
   # veya
   curl http://localhost:11434/api/tags
   ```

3. İstemci (FermatAI bridge) kod tarafında zaten optimize:
   - `num_ctx=2048` (kısa sohbet için)
   - `num_batch=256` (prompt processing hızlı)
   - `keep_alive="15m"` (cold start yok)

## Küçük Model (Backup)

Basit selamlama/onay için `qwen2.5:3b` (1.9GB VRAM) daha hızlı:

```powershell
ollama pull qwen2.5:3b
```

`MAX_LOADED_MODELS=2` ile hem 7b hem 3b aynı anda hafızada kalabilir.

## Performance Beklenen

**Önceki**:
- qwen2.5:7b: ortalama 10s, P95 22s
- Single thread → 8 kullanıcı sıkıştığında kuyruk

**Paket C sonrası**:
- qwen2.5:7b: ortalama 6-8s, P95 ~10-12s
- 2 paralel → 16 kullanıcı concurrent
- Bridge kodu değişimi (num_ctx/num_batch) — anında aktif
- Server env değişimi — servis restart gerekli

## Notlar

- `OLLAMA_NUM_PARALLEL=4` denenebilir ama GPU VRAM'e dikkat (her paralel request ~1GB)
- qwen2.5:7b Q4 ~5GB VRAM — RTX 3060 12GB'da 2 paralel rahat
- Flash Attention sadece modern GPU'larda (Ampere+)
