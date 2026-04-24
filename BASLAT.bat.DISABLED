@echo off
title FermatAI - Neo Kontrol Merkezi
color 0A

cd /d "C:\Users\zekig\OneDrive\Desktop\FermatAI\eyotek_agent"

echo.
echo  ============================================
echo   FERMAT AI - Sistem Baslatiliyor
echo  ============================================
echo.

:: 1. Docker
echo  [1/5] Docker kontrol ediliyor...
docker start fermat_postgres fermat_redis fermat_chroma >nul 2>&1
ping -n 4 127.0.0.1 >nul
docker exec fermat_postgres pg_isready >nul 2>&1
if %errorlevel% equ 0 (
    echo        [OK] PostgreSQL calisiyor
) else (
    echo        [!] PostgreSQL bekleniyor...
    ping -n 6 127.0.0.1 >nul
)

:: 2. ngrok
echo  [2/5] ngrok baslatiliyor...
for /f "tokens=2 delims==" %%a in ('findstr "NGROK_AUTHTOKEN" .env 2^>nul') do (
    ngrok config add-authtoken %%a >nul 2>&1
)
taskkill /f /im ngrok.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul
for /f "tokens=2 delims==" %%d in ('findstr "NGROK_DOMAIN" .env 2^>nul') do (
    start /b "" ngrok http 8001 --domain=%%d --log=stdout >logs\ngrok.log 2>&1
)
ping -n 4 127.0.0.1 >nul
echo        [OK] ngrok (sabit domain)

:: 3. Ollama
echo  [3/5] Ollama baslatiliyor...
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo        [OK] Ollama zaten calisiyor
) else (
    start /b "" "C:\Users\zekig\AppData\Local\Programs\Ollama\ollama.exe" serve >nul 2>&1
    ping -n 6 127.0.0.1 >nul
    echo        [OK] Ollama baslatildi
)

:: 4. Chrome CDP
echo  [4/5] Chrome CDP kontrol ediliyor...
curl -s http://localhost:9222/json/version >nul 2>&1
if %errorlevel% equ 0 (
    echo        [OK] Chrome CDP zaten acik
) else (
    echo        Chrome aciliyor...
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebug" "https://fermat.eyotek.com/v1"
    echo.
    echo  ============================================
    echo   Chrome acildi. Eyotek'e giris yapin.
    echo   Giris yaptiktan sonra ENTER'a basin.
    echo  ============================================
    echo.
    pause
)

:: 5. Neo Kontrol Merkezi
echo  [5/5] Neo Kontrol Merkezi baslatiliyor...
echo.

.venv\Scripts\python fermat_start.py

:: Temizlik + terminal kapat
taskkill /f /im ngrok.exe >nul 2>&1
exit
