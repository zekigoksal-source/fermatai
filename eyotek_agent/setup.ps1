# FermatAI Eyotek Agent - Kurulum Scripti
# Çalıştırma: .\setup.ps1

Write-Host "=== FermatAI Eyotek Agent Kurulum ===" -ForegroundColor Cyan

# venv oluştur (yoksa)
if (-not (Test-Path "venv")) {
    Write-Host "venv oluşturuluyor..." -ForegroundColor Yellow
    python -m venv venv
}

# venv aktif et
Write-Host "venv aktif ediliyor..." -ForegroundColor Yellow
& .\venv\Scripts\Activate.ps1

# Paketleri yükle
Write-Host "Paketler yükleniyor..." -ForegroundColor Yellow
pip install -r requirements.txt

# Playwright chromium yükle
Write-Host "Playwright Chromium yükleniyor..." -ForegroundColor Yellow
python -m playwright install chromium

Write-Host "=== Kurulum tamamlandi! ===" -ForegroundColor Green
Write-Host "Calistirmak icin: .\venv\Scripts\Activate.ps1 sonra python eyotek_agent.py" -ForegroundColor Cyan
