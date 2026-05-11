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
copy /Y "%~dp0deploy.bat"        "%DEST%\deploy.bat"        >nul
if exist "%~dp0start.bat" copy /Y "%~dp0start.bat" "%DEST%\start.bat" >nul

echo [5/6] Xoa __pycache__ cu tren may dich...
for /d /r "%DEST%" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d"
)

echo [6/6] Cap nhat thu vien Python (neu co package moi)...
if exist "%DEST%\venv\Scripts\python.exe" (
    "%DEST%\venv\Scripts\python.exe" -m pip install -r "%DEST%\requirements.txt" --quiet --upgrade
    echo     [OK] Thu vien da cap nhat.
) else (
    echo     [!] Khong tim thay venv tren may dich -- bo qua buoc nay.
    echo         Chay start.bat lan dau de tao lai venv.
)

echo.
echo ============================================================
echo  XONG! Code moi da duoc cap nhat.
echo  Du lieu data\ksnb.db KHONG bi thay doi.
echo  Schema DB se tu dong migrate khi khoi dong lai.
echo.
echo  LUU Y: Can file .env voi SECRET_KEY tren may dich.
echo  Khoi dong lai ung dung: tat tien trinh cu, chay start.bat
echo ============================================================
pause
endlocal
