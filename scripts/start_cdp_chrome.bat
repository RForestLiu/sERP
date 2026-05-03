@echo off
echo ============================================
echo   CDP Recon - Starting Chrome + Listener
echo ============================================
echo.
echo Make sure ALL Chrome windows are closed first!
echo.
echo If Chrome is open, close it now and re-run this script.
echo.
pause

echo [*] Starting Chrome with CDP port 9222 ...
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 https://www.dianxiaomi.com

echo [*] Waiting for CDP port ...
:wait
timeout /t 2 /nobreak >nul
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9222/json',timeout=2)" 2>nul
if %ERRORLEVEL% neq 0 goto wait

echo [*] CDP ready!

echo [*] Starting listener ...
cd /d "%~dp0.."
python -u scripts\cdp_listener.py

pause
