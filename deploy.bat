@echo off
chcp 65001 >nul
setlocal

:: ============================================================
:: deploy.bat -- Copy code moi sang may chinh (qua mang/USB)
:: Chi copy SOURCE CODE, KHONG dung den data/ksnb.db
:: ============================================================
:: Sua dong duoi thanh duong dan thuc te truoc khi chay:
::   Qua mang LAN:  set "DEST=\\192.168.1.100\TenShare\System"
::   Cung may:      set "DEST=C:\...\System"
:: ============================================================
set "DEST=C:\Users\ThanhDaoTien\Desktop\TTTT_System"

echo ============================================================
echo  Deploy code moi sang: %DEST%
echo  Du lieu (data\ksnb.db) giu nguyen KHONG bi ghi de
echo ============================================================
echo.

if not exist "%DEST%" (
    echo [LOI] Khong tim thay thu muc dich: %DEST%
    echo Hay kiem tra duong dan hoac ket noi mang.
    pause
    exit /b 1
)

:: Copy tung folder code -- bo qua venv, data, __pycache__
echo [1/6] Copy backend...
robocopy "%~dp0backend"    "%DEST%\backend"    /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS

echo [2/6] Copy frontend...
robocopy "%~dp0frontend"   "%DEST%\frontend"   /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS

echo [3/6] Copy templates...
robocopy "%~dp0templates"  "%DEST%\templates"  /E /NFL /NDL /NJH /NJS

echo [4/6] Copy file goc...
copy /Y "%~dp0run.py"            "%DEST%\run.py"            >nul
copy /Y "%~dp0init_db.py"        "%DEST%\init_db.py"        >nul
copy /Y "%~dp0requirements.txt"  "%DEST%\requirements.txt"  >nul
if exist "%~dp0start.bat" copy /Y "%~dp0start.bat" "%DEST%\start.bat" >nul
if exist "%~dp0Logs_update.md" copy /Y "%~dp0Logs_update.md" "%DEST%\Logs_update.md" >nul

echo [5/6] Xoa __pycache__ cu tren may dich...
for /d /r "%DEST%" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d"
)

echo [6/6] Kiem tra thu vien Python...
set "DEST_PY="
if exist "%DEST%\.venv\Scripts\python.exe" set "DEST_PY=%DEST%\.venv\Scripts\python.exe"
if not defined DEST_PY if exist "%DEST%\venv\Scripts\python.exe" set "DEST_PY=%DEST%\venv\Scripts\python.exe"

set "NEED_PIP=0"
if not exist "%DEST%\requirements.txt" set "NEED_PIP=1"
if "%NEED_PIP%"=="0" (
    fc /b "%~dp0requirements.txt" "%DEST%\requirements.txt" >nul 2>&1
    if errorlevel 1 set "NEED_PIP=1"
)

if "%NEED_PIP%"=="1" (
    echo     requirements.txt thay doi -- dang cai thu vien...
    if not defined DEST_PY (
        echo     [!] Chua co venv tren may dich -- start.bat se tu tao khi chay lan dau.
        goto end
    )
    "%DEST_PY%" -m pip install -r "%DEST%\requirements.txt" --quiet
    if errorlevel 1 (
        echo     [!] pip install that bai -- kiem tra ket noi internet tren may dich.
    ) else (
        echo     [OK] Thu vien da cap nhat xong.
    )
) else (
    echo     [OK] requirements.txt khong doi -- bo qua pip install.
)

echo.
echo ============================================================
echo  XONG! Code moi da duoc cap nhat.
echo  Du lieu data\ksnb.db KHONG bi thay doi.
echo  Schema DB se tu dong migrate khi khoi dong lai.
echo.
echo  LUU Y: Can file .env voi SECRET_KEY tren may dich.
echo  Ban nay them bien STORAGE_SECRET -- start.bat se TU SINH neu .env chua co.
echo  Nguoi dung dang dang nhap se bi dang xuat MOT LAN sau khi khoi dong lai.
echo  Khoi dong lai ung dung: tat tien trinh cu, chay start.bat
echo ============================================================
echo.
pause

:: Sau khi deploy xong may chinh, tu dong cap nhat luon he thong TEST (9000/9090)
if exist "%~dp0deploy-test.bat" (
    call "%~dp0deploy-test.bat"
) else (
    echo [!] Khong tim thay deploy-test.bat -- bo qua cap nhat he thong test.
    pause
)
goto realend

:end
pause

:realend
endlocal
