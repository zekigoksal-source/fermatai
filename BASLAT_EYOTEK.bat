@echo off
REM ================================================================
REM   FermatAI Eyotek Bridge — Laptop'tan manuel login + VPS aktar
REM ================================================================
REM Amac: Cloudflare Turnstile sadece manuel gecilebilir. Neo Chrome'da
REM bir kez login olur, script cookie'leri VPS'e aktarir. Sonrasinda
REM VPS bagimsiz calisir (~20-30dk, session keeper uzatir).
REM
REM Kullanim: Bu dosyaya cift tıkla. Gerisini script yonetir.
REM ================================================================
title FermatAI Eyotek Bridge

cd /d "%~dp0"

echo.
echo ================================================================
echo   FermatAI Eyotek Bridge - Laptop Manuel Login
echo ================================================================
echo.

REM 1) venv aktif mi kontrol
if not exist "eyotek_agent\.venv\Scripts\python.exe" (
    echo [HATA] venv bulunamadi: eyotek_agent\.venv
    echo       Kurulum yapildiysa .venv yolu farkli olabilir.
    pause
    exit /b 1
)

REM 2) Chrome acik degilse script kendisi acacak, script'e birak
echo [INFO] Eyotek bridge script baslatiliyor...
echo.
echo >> Chrome otomatik acilacak (veya zaten acikti ise mevcut kullanilacak)
echo >> Cloudflare kutusunu tikla, kullanici adi + sifre gir, login yap
echo >> Script URL'in /Pages/'a gecmesini bekler
echo >> Cookie'leri otomatik VPS'e aktarir
echo.

"eyotek_agent\.venv\Scripts\python.exe" "eyotek_agent\eyotek_bridge_laptop.py"

echo.
echo ================================================================
pause
