@echo off
chcp 65001 > nul
echo ======================================================
echo   Redmi Watch - Gemini AI Sesli Asistan Koprusu
echo ======================================================
echo.

cd /d "%~dp0"

echo [1/2] Gerekli Python paketleri kontrol ediliyor...
python -m pip install -r requirements.txt

echo.
echo [2/2] Sunucu baslatiliyor...
python server.py

pause
