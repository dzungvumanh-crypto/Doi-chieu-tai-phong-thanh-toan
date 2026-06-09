@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Tao .env voi SECRET_KEY ngau nhien neu chua co
if not exist ".env" (
    echo [!] Khong tim thay file .env. Dang tao moi voi SECRET_KEY ngau nhien...
    for /f "delims=" %%K in ('python -c "import secrets; print(secrets.token_hex(32))"') do set "NEWKEY=%%K"
    (
        echo SECRET_KEY=!NEWKEY!
        echo BACKEND_HOST=0.0.0.0
        echo BACKEND_PORT=8000
        echo FRONTEND_PORT=8080
    ) > ".env"
    echo [OK] Da tao .env. Giu file nay bi mat va KHONG commit len git.
    echo.
)

:: Neu .venv bi hong (Python bi go cai/di chuyen), tu tao lai
.venv\Scripts\python.exe --version >nul 2>&1
if errorlevel 1 (
    echo [!] .venv bi hong. Dang tao lai...
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Khong tim thay Python. Vui long cai lai Python 3.10+.
        pause
        exit /b 1
    )
    if exist ".venv" rmdir /s /q .venv
    python -m venv .venv
    echo [*] Cai dat thu vien...
    .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
    echo [OK] Xong.
    echo.
)

echo Khoi dong he thong KSNB^&HTVH...
.venv\Scripts\python.exe run.py
pause
