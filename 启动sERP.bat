@echo off
title sERP Server

echo ============================================
echo            sERP Management System
echo ============================================
echo.

echo [1/6] Checking Python...
where python
if %errorlevel% neq 0 (
    echo [X] Python not found. Install Python 3 first.
    echo     https://www.python.org/downloads/
    pause
    exit /b 1
)

cd /d "%~dp0"

echo [2/6] Setting up virtual environment...
if not exist "venv\" (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [X] Failed to create venv
        pause
        exit /b 1
    )
)

echo [3/6] Activating venv...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo [X] Failed to activate venv
    pause
    exit /b 1
)

echo [4/6] Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [X] Failed to install dependencies
    pause
    exit /b 1
)

echo [5/6] Checking config...
if not exist ".env" (
    echo [X] .env config not found
    pause
    exit /b 1
)

echo [6/6] Starting server...
echo.
echo ============================================
echo   Browser will open http://localhost:5000
echo   Close this window to stop the server
echo ============================================
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"

python main.py

pause
