@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Dung py.exe (Windows Python Launcher) neu co, fallback sang python
where py >nul 2>&1 && set "PY=py" || set "PY=python"

:: Tao .env voi SECRET_KEY + STORAGE_SECRET ngau nhien neu chua co
if not exist ".env" (
    echo [!] Khong tim thay file .env. Dang tao moi voi khoa ngau nhien...
    for /f "delims=" %%K in ('%PY% -c "import secrets; print(secrets.token_hex(32))"') do set "NEWKEY=%%K"
    for /f "delims=" %%K in ('%PY% -c "import secrets; print(secrets.token_hex(32))"') do set "NEWSS=%%K"
    (
        echo SECRET_KEY=!NEWKEY!
        echo STORAGE_SECRET=!NEWSS!
        echo BACKEND_HOST=0.0.0.0
        echo BACKEND_PORT=8000
        echo FRONTEND_PORT=8080
    ) > ".env"
    echo [OK] Da tao .env. Giu file nay bi mat va KHONG commit len git.
    echo.
)

:: Bo sung STORAGE_SECRET cho .env cu (them 07/2026 -- truoc do khoa nay hardcode trong source).
:: Thieu bien nay frontend se khong khoi dong duoc.
findstr /b /c:"STORAGE_SECRET=" ".env" >nul 2>&1
if errorlevel 1 (
    echo [!] .env chua co STORAGE_SECRET. Dang sinh khoa moi...
    for /f "delims=" %%K in ('%PY% -c "import secrets; print(secrets.token_hex(32))"') do set "NEWSS=%%K"
    >>".env" echo.
    >>".env" echo # Khoa ky cookie phien NiceGUI -- sinh tu dong khi nang cap
    >>".env" echo STORAGE_SECRET=!NEWSS!
    echo [OK] Da them STORAGE_SECRET vao .env.
    echo     LUU Y: nguoi dung dang dang nhap se bi dang xuat mot lan.
    echo.
)

:: Neu .venv bi hong (Python bi go cai/di chuyen), tu tao lai
.venv\Scripts\python.exe --version >nul 2>&1
if errorlevel 1 (
    echo [!] .venv bi hong. Dang tao lai...
    %PY% --version >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Khong tim thay Python. Vui long cai lai Python 3.10+.
        pause
        exit /b 1
    )
    if exist ".venv" rmdir /s /q .venv
    %PY% -m venv .venv
    echo [*] Cai dat thu vien...
    .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
    echo [OK] Xong.
    echo.
)

:: Cap nhat thu vien neu requirements.txt moi hon .venv (tuc la co package moi)
for /f %%T in ('powershell -NoProfile -Command "(Get-Item requirements.txt).LastWriteTime.Ticks"') do set "REQ_TIME=%%T"
for /f %%T in ('powershell -NoProfile -Command "if (Test-Path .venv\.req_stamp) { Get-Content .venv\.req_stamp } else { echo 0 }"') do set "STAMP=%%T"
if not "!REQ_TIME!"=="!STAMP!" (
    echo [*] requirements.txt da thay doi. Dang cap nhat thu vien...
    .venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
    echo !REQ_TIME! > .venv\.req_stamp
    echo [OK] Cap nhat xong.
    echo.
)

echo Khoi dong he thong KSNB^&HTVH...
.venv\Scripts\python.exe run.py
pause
