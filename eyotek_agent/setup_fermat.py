# FermatAI Setup & Fix Script
# Calistir: cd eyotek_agent dizinine gec, sonra: .\setup_fermat.ps1

$eyotekDir = "C:\Users\zekig\OneDrive\Desktop\FermatAI\eyotek_agent"
$envFile   = "$eyotekDir\.env"

Write-Host "`n=== FermatAI Setup Script ===" -ForegroundColor Cyan

# 1. Docker'dan gercek PostgreSQL sifresini al
Write-Host "`n[1/4] PostgreSQL sifresi Docker'dan aliniyor..." -ForegroundColor Yellow
try {
    $pgPass = docker exec fermat_postgres bash -c "echo `$POSTGRES_PASSWORD" 2>&1
    if ($LASTEXITCODE -eq 0 -and $pgPass) {
        $pgPass = $pgPass.Trim()
        Write-Host "    Sifre bulundu: $pgPass" -ForegroundColor Green
    } else {
        $pgPass = "fermat_secret_2024"
        Write-Host "    Docker'dan alinamadiDE, default kullaniliyor: $pgPass" -ForegroundColor Yellow
    }
} catch {
    $pgPass = "fermat_secret_2024"
    Write-Host "    Hata, default: $pgPass" -ForegroundColor Yellow
}

# 2. .env dosyasini guncelle
Write-Host "`n[2/4] .env guncelleniyor..." -ForegroundColor Yellow
$newDbUrl = "postgresql://fermat:$pgPass@localhost:5432/fermatai"
$content = Get-Content $envFile -Raw
$content = $content -replace 'DATABASE_URL=.*', "DATABASE_URL=$newDbUrl"
$content = $content -replace 'HEADLESS=true', 'HEADLESS=false'
Set-Content $envFile $content -NoNewline
Write-Host "    DATABASE_URL=$newDbUrl" -ForegroundColor Green

# 3. PostgreSQL baglantisini test et
Write-Host "`n[3/4] PostgreSQL baglanti testi..." -ForegroundColor Yellow
$testResult = docker exec fermat_postgres psql -U fermat -d fermatai -c "SELECT 'OK' as durum;" 2>&1
if ($testResult -match "OK") {
    Write-Host "    PostgreSQL: BASARILI" -ForegroundColor Green
} else {
    Write-Host "    PostgreSQL: $testResult" -ForegroundColor Red
    # Gercek sifreyi container env'den dene
    $pgPassAlt = docker exec fermat_postgres printenv POSTGRES_PASSWORD 2>&1
    if ($pgPassAlt -and $pgPassAlt.Trim()) {
        $pgPass = $pgPassAlt.Trim()
        $newDbUrl = "postgresql://fermat:$pgPass@localhost:5432/fermatai"
        $content = Get-Content $envFile -Raw
        $content = $content -replace 'DATABASE_URL=.*', "DATABASE_URL=$newDbUrl"
        Set-Content $envFile $content -NoNewline
        Write-Host "    Alternatif sifre denendi: $pgPass" -ForegroundColor Yellow
    }
}

# 4. Son .env goster
Write-Host "`n[4/4] Guncel .env:" -ForegroundColor Yellow
Get-Content $envFile | ForEach-Object { Write-Host "    $_" }

# 5. Smoke test calistir
Write-Host "`n=== Smoke Test Basliyor ===" -ForegroundColor Cyan
Set-Location $eyotekDir
& "$eyotekDir\.venv\Scripts\python.exe" "$eyotekDir\eyotek_agent.py"