@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

:: Dung py.exe (Windows Python Launcher) neu co, fallback sang python
where py >nul 2>&1 && set "PY=py" || set "PY=python"

:: ── Tao .env voi SECRET_KEY + STORAGE_SECRET ngau nhien neu chua co ──
:: BACKEND_HOST=127.0.0.1: cong backend khong can lo ra mang -- trinh duyet chi
:: vao cong frontend, Extension CITAD di qua proxy cung cong do. Doi 0.0.0.0 chi
:: khi that su co may khac goi thang API, va khi do PHAI dat them ALLOWED_ORIGINS.
:: ENV=production tat /docs, /redoc, /openapi.json -- can xem de go loi thi them
:: ENABLE_API_DOCS=1, dung ha ENV xuong development.
if not exist ".env" (
    echo [!] Khong tim thay file .env. Dang tao moi voi khoa ngau nhien...
    for /f "delims=" %%K in ('%PY% -c "import secrets; print(secrets.token_hex(32))"') do set "NEWKEY=%%K"
    for /f "delims=" %%K in ('%PY% -c "import secrets; print(secrets.token_hex(32))"') do set "NEWSS=%%K"
    (
        echo SECRET_KEY=!NEWKEY!
        echo STORAGE_SECRET=!NEWSS!
        echo BACKEND_HOST=127.0.0.1
        echo BACKEND_PORT=8000
        echo FRONTEND_PORT=8080
        echo ENV=production
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

:: ── Kiem tra .venv ──
:: Duong chay binh thuong chi ton ~0.1s. Chi khi that su hong moi vao nhanh sua chua.
set "FORCE_PIP=0"
set "VENV_OK=0"
if exist "!VENV_PY!" (
    "!VENV_PY!" -c "import sys" >nul 2>&1 && set "VENV_OK=1"
)

if "!VENV_OK!"=="0" (
    echo [!] .venv khong dung duoc. Chi tiet loi:
    if exist "!VENV_PY!" (
        "!VENV_PY!" -c "import sys" 2>&1
    ) else (
        echo     Khong tim thay !VENV_PY!
    )
    echo.

    %PY% -c "import sys" >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Khong chay duoc Python he thong ^(lenh: %PY%^).
        echo       Cai lai Python 3.10+ tu python.org, nho tick "Add to PATH".
        echo       Neu Windows mo Microsoft Store khi go "python": tat App Execution Alias
        echo       trong Settings ^> Apps ^> Advanced app settings ^> App execution aliases.
        pause
        exit /b 1
    )

    rem Buoc 1 -- va lai venv tai cho: giu nguyen thu vien da cai, mat vai giay.
    if exist ".venv" (
        echo [*] Dang sua .venv tai cho ^(giu lai thu vien da cai^)...
        %PY% -m venv --upgrade .venv >nul 2>&1
        "!VENV_PY!" -c "import sys" >nul 2>&1 && set "VENV_OK=1"
    )

    if "!VENV_OK!"=="1" (
        rem Venv chay lai duoc, nhung neu ban Python thay doi thi cac goi bien dich san
        rem nhu pandas / bcrypt / cryptography se khong import duoc -- khi do cai lai goi.
        "!VENV_PY!" -c "import fastapi, nicegui, docxtpl, pandas, bcrypt" >nul 2>&1
        if errorlevel 1 (
            echo [*] Thu vien khong khop ban Python moi -- se cai lai.
            set "FORCE_PIP=1"
        ) else (
            echo [OK] Da sua xong .venv, khong can cai lai thu vien.
        )
    ) else (
        echo [*] Khong sua duoc -- tao lai tu dau ^(mat vai phut^)...
        if exist ".venv" rmdir /s /q .venv
        %PY% -m venv .venv
        if errorlevel 1 (
            echo [LOI] Khong tao duoc .venv.
            pause
            exit /b 1
        )
        set "FORCE_PIP=1"
    )
    echo.
)

:: ── Cai/cap nhat thu vien khi requirements.txt doi (hoac vua dung lai venv) ──
:: Dau van tay = thoi diem sua + kich thuoc file, lay bang batch thuan (khong goi PowerShell).
set "REQ_TIME="
for %%F in ("requirements.txt") do set "REQ_TIME=%%~tF %%~zF"
if not defined REQ_TIME (
    echo [LOI] Khong tim thay requirements.txt.
    pause
    exit /b 1
)

set "STAMP="
if exist ".venv\.req_stamp" for /f "usebackq delims=" %%S in (".venv\.req_stamp") do set "STAMP=%%S"
if "!FORCE_PIP!"=="1" set "STAMP="

if not "!REQ_TIME!"=="!STAMP!" (
    echo [*] Dang cai/cap nhat thu vien...
    "!VENV_PY!" -m pip install -r requirements.txt --quiet --disable-pip-version-check
    if errorlevel 1 (
        echo [LOI] Cai thu vien that bai -- doc ky thong bao loi pip ngay phia tren.
        echo       UnicodeDecodeError = requirements.txt co ky tu co dau, khong phai loi mang.
        echo       Con lai: kiem tra ket noi internet.
        pause
        exit /b 1
    )
    >".venv\.req_stamp" echo !REQ_TIME!
    echo [OK] Cap nhat xong.
    echo.
)

echo Khoi dong he thong KSNB^&HTVH...
"!VENV_PY!" run.py
pause
