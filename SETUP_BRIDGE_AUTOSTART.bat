@echo off
chcp 65001 >nul
REM ═══════════════════════════════════════════════════════════════════
REM FermatAI Bridge + Session Keeper OTONOM — Windows Scheduled Task
REM (22.1l — bilgisayar acilinca bridge otomatik baslasin)
REM
REM TEK SEFER admin olarak calistir.
REM Sonra bilgisayar her acilisinda:
REM   1. FermatAI Bridge (port 8001) baslar
REM   2. Session Keeper (Eyotek 3dk periyod) calisir
REM ═══════════════════════════════════════════════════════════════════

set TASK_NAME=FermatAI_Bridge_AutoStart
set PROJECT_DIR=C:\Users\zekig\OneDrive\Desktop\FermatAI\eyotek_agent
set PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe
set SCRIPT_PATH=%PROJECT_DIR%\fermat_start.py
set LOG_DIR=%PROJECT_DIR%\logs

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.
echo =====================================================
echo   FermatAI Bridge Auto-Start Kurulumu
echo =====================================================
echo.
echo Task:     %TASK_NAME%
echo Tetik:    Bilgisayar her acilista
echo Script:   %SCRIPT_PATH%
echo Log:      %LOG_DIR%\bridge_autostart.log
echo.

REM Mevcut task varsa once sil (idempotent)
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %errorlevel%==0 (
    echo [!] Mevcut task bulundu, siliniyor...
    schtasks /delete /tn "%TASK_NAME%" /f
)

REM Task olustur — logon tetikli
schtasks /create /tn "%TASK_NAME%" ^
    /tr "cmd /c \"cd /d %PROJECT_DIR% ^&^& \"%PYTHON_EXE%\" fermat_start.py --autostart > %LOG_DIR%\bridge_autostart.log 2>^&1\"" ^
    /sc onlogon /rl LIMITED /f

if %errorlevel%==0 (
    echo.
    echo [OK] Scheduled Task olusturuldu.
    echo.
    echo Kontrol:        schtasks /query /tn "%TASK_NAME%"
    echo Manuel baslat:  schtasks /run /tn "%TASK_NAME%"
    echo Sil:            schtasks /delete /tn "%TASK_NAME%" /f
    echo.
    echo NOT: Ilk calistirmada Chrome CDP baglantisi icin manuel adim gerekebilir.
    echo       Session drop'larda Neo WhatsApp bildirim aliyor (session_keeper).
    echo.
) else (
    echo.
    echo [HATA] Task olusturulamadi. Admin yetkisiyle calistir.
    echo.
)

pause
