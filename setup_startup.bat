@echo off
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
copy "%~dp0start_server.vbs" "%STARTUP%\GridTracker_Server.vbs" > nul
echo GridTracker sunucusu Windows baslangicinа eklendi.
echo Bir sonraki oturumdan itibaren otomatik baslar.
pause
