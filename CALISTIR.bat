@echo off
chcp 65001 > nul
echo ============================================
echo  FermatAI - Veritabani Kurulum
echo ============================================
echo.

cd /d "C:\Users\zekig\OneDrive\Desktop\FermatAI"

echo [1/3] Cop kayitlar temizleniyor...
python cleanup_db.py
echo.

echo [2/3] 18 personel import ediliyor...
python import_staff.py
echo.

echo [3/3] Sistem testi calistiriliyor...
python test_all.py
echo.

echo ============================================
echo  TAMAMLANDI - Bu pencereyi kapatabilirsin
echo ============================================
pause
