@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Neu venv bi hong (Python bi go cai/di chuyen), tu tao lai
venv\Scripts\python.exe --version >nul 2>&1
if errorlevel 1 (
    echo [!] Venv bi hong. Dang tao lai...
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Khong tim thay Python. Vui long cai lai Python 3.10+.
        pause
        exit /b 1
    )
    rmdir /s /q venv
    python -m venv venv
    echo [*] Cai dat thu vien...
    venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
    echo [OK] Xong.
    echo.
)

echo Khoi dong he thong KSNB^&HTVH...
venv\Scripts\python.exe run.py
pause
