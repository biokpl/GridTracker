@echo off
chcp 65001 >nul
echo Sermaye Danismani Servisleri Baslatiliyor...

set PY=C:\Users\BioCSI\AppData\Local\Programs\Python\Python313\pythonw.exe
set GRIDTRACKER=C:\Users\BioCSI\CLAUDE\GridTracker
set ADVISOR=C:\Users\BioCSI\CLAUDE\Günlük Sermaye Yönetimi

REM ── 1. server.py — eski süreci PID ile durdur, yenisini başlat ────────────
echo [1/3] server.py yeniden baslatiliyor...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5050 "') do (
    taskkill /F /PID %%a 2>nul
)
timeout /t 1 /nobreak >nul
start "" /B "%PY%" "%GRIDTRACKER%\server.py"
timeout /t 2 /nobreak >nul
echo     server.py TAMAM (port 5050)

REM ── 2. monitor.pyw — varsa durdur, yenisini başlat ──────────────────────
echo [2/3] monitor.pyw baslatiliyor...
wmic process where "CommandLine like '%%monitor.pyw%%'" delete 2>nul
timeout /t 1 /nobreak >nul
start "" /B "%PY%" "%ADVISOR%\monitor.pyw"
timeout /t 1 /nobreak >nul
echo     monitor.pyw TAMAM (15 dk'da bir SASA kontrol)

REM ── 3. İlk analizi hemen çalıştır ────────────────────────────────────────
echo [3/3] Ilk analiz calistiriliyor...
cd /d "%ADVISOR%"
"%PY%" advisor.py --run
echo     Analiz TAMAM

echo.
echo =========================================
echo  TUM SERVISLER HAZIR
echo  - server.py    : port 5050 aktif
echo  - monitor.pyw  : arka planda calisıyor
echo  - Ilk analiz   : tamamlandi
echo  - SASA pozisyonu state.json'a islendi
echo =========================================
echo.
pause
