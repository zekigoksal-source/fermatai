@echo off
chcp 65001 >nul
REM FermatAI DB Backup — Windows Scheduled Task kurulumu
REM Bu bat dosyasini TEK SEFER admin olarak calistir, cron kurulur.
REM Sonra her gun 03:00'te otomatik backup alir.

set TASK_NAME=FermatAI_DB_Backup
set PROJECT_DIR=C:\Users\zekig\OneDrive\Desktop\FermatAI\eyotek_agent
set PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe
set SCRIPT_PATH=%PROJECT_DIR%\db_backup.py
set LOG_DIR=%PROJECT_DIR%\logs\backup

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo.
echo =====================================================
echo   FermatAI Backup Scheduled Task Kurulumu
echo =====================================================
echo.
echo Task:     %TASK_NAME%
echo Saat:     Her gun 03:00
echo Script:   %SCRIPT_PATH%
echo Log:      %LOG_DIR%\backup_cron.log
echo.

REM Mevcut task varsa once sil (idempotent)
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %errorlevel%==0 (
    echo [!] Mevcut task bulundu, siliniyor...
    schtasks /delete /tn "%TASK_NAME%" /f
)

REM Task olustur — gunluk 03:00
schtasks /create /tn "%TASK_NAME%" ^
    /tr "cmd /c \"cd /d %PROJECT_DIR% ^&^& \"%PYTHON_EXE%\" db_backup.py >> %LOG_DIR%\backup_cron.log 2>^&1\"" ^
    /sc daily /st 03:00 /rl LIMITED /f

if %errorlevel%==0 (
    echo.
    echo [OK] Scheduled Task olusturuldu.
    echo.
    echo Kontrol: schtasks /query /tn "%TASK_NAME%"
    echo Manuel calistir: schtasks /run /tn "%TASK_NAME%"
    echo Sil:     schtasks /delete /tn "%TASK_NAME%" /f
    echo.
) else (
    echo.
    echo [HATA] Task olusturulamadi. Admin yetkisiyle calistir.
    echo.
)

pause
