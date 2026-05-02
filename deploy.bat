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
set "DEST=C:\Users\KhanhPC\Desktop\System"

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
echo [1/5] Copy backend...
robocopy "%~dp0backend"    "%DEST%\backend"    /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS

echo [2/5] Copy frontend...
robocopy "%~dp0frontend"   "%DEST%\frontend"   /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS

echo [3/5] Copy templates...
robocopy "%~dp0templates"  "%DEST%\templates"  /E /NFL /NDL /NJH /NJS

echo [4/5] Copy file goc...
copy /Y "%~dp0run.py"            "%DEST%\run.py"            >nul
copy /Y "%~dp0init_db.py"        "%DEST%\init_db.py"        >nul
copy /Y "%~dp0requirements.txt"  "%DEST%\requirements.txt"  >nul
copy /Y "%~dp0deploy.bat"        "%DEST%\deploy.bat"        >nul
if exist "%~dp0start.bat" copy /Y "%~dp0start.bat" "%DEST%\start.bat" >nul

echo [5/5] Xoa __pycache__ cu tren may dich...
for /d /r "%DEST%" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d"
)

echo.
echo ============================================================
echo  XONG! Code moi da duoc cap nhat.
echo  Du lieu data\ksnb.db KHONG bi thay doi.
echo  Khoi dong lai ung dung tren may chinh de ap dung.
echo ============================================================
pause
endlocal
