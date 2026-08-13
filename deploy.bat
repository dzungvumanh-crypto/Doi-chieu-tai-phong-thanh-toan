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

:: .env cua may dich KHONG bi copy de (giu SECRET_KEY va cau hinh rieng), nen hai
:: bien duoi day phai sua tay -- va quen thi im lang khong bao gi. Kiem ho luon.
echo [1/8] Kiem tra .env tren may dich (BACKEND_URL/BACKEND_HOST/ENV)...
:: Tim Python CHAY DUOC. Khong chi kiem tra file co ton tai: du an nam tren o USB,
:: doi may la .venv hong (xem start.bat) -- file van con nhung chay la loi. Con
:: `py` thi tren mot so may vuong ban Microsoft Store alias. Nen thu chay thu that.
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" "%~dp0.venv\Scripts\python.exe" -c "pass" >nul 2>&1 && set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY py -c "pass" >nul 2>&1 && set "PY=py"
if not defined PY python -c "pass" >nul 2>&1 && set "PY=python"
if not defined PY goto envkhongpy

:: --siet-bao-mat: chi may CHINH moi siet (BACKEND_HOST=127.0.0.1, ENV=production).
:: deploy-test.bat KHONG truyen co nay -- he thong test can /docs de go loi.
"%PY%" "%~dp0scripts\deploy_env_check.py" "%DEST%\.env" 8000 check --siet-bao-mat
if errorlevel 2 goto envloi
if errorlevel 1 goto envsua
goto envxong

:envkhongpy
echo     [!] Khong tim thay Python chay duoc tren may nay -- BO QUA buoc kiem tra .env.
echo         Hay tu kiem tren may dich: BACKEND_URL phai la http://127.0.0.1:8000
goto envxong

:envloi
echo     [!] Khong kiem tra duoc .env -- xem thong bao tren, sua tay neu can.
goto envxong

:envsua
echo.
set /p FIXENV=    Sua lai .env cho dung? (Y/n):
if /i "%FIXENV%"=="n" goto envboqua
"%PY%" "%~dp0scripts\deploy_env_check.py" "%DEST%\.env" 8000 fix --siet-bao-mat
goto envxong

:envboqua
echo     [BO QUA] .env giu nguyen -- nho sua tay TRUOC khi khoi dong lai.

:envxong
echo.

:: Copy tung folder code -- bo qua venv, data, __pycache__
echo [2/8] Copy backend...
robocopy "%~dp0backend"    "%DEST%\backend"    /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS

echo [3/8] Copy frontend...
robocopy "%~dp0frontend"   "%DEST%\frontend"   /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS

echo [4/8] Copy templates + scripts...
robocopy "%~dp0templates"  "%DEST%\templates"  /E /NFL /NDL /NJH /NJS
robocopy "%~dp0scripts"    "%DEST%\scripts"    /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS

echo [5/8] Copy file goc...
copy /Y "%~dp0run.py"            "%DEST%\run.py"            >nul
copy /Y "%~dp0init_db.py"        "%DEST%\init_db.py"        >nul
copy /Y "%~dp0requirements.txt"  "%DEST%\requirements.txt"  >nul
if exist "%~dp0start.bat" copy /Y "%~dp0start.bat" "%DEST%\start.bat" >nul
if exist "%~dp0Logs_update.md" copy /Y "%~dp0Logs_update.md" "%DEST%\Logs_update.md" >nul

echo [6/8] Do file thua tren may dich (code cu da bi xoa khoi du an)...
:: robocopy /E chi them va ghi de, KHONG BAO GIO xoa. File .py da bo khoi du an
:: van nam lai tren may dich -- va frontend/main.py nap trang bang cach QUET thu muc
:: frontend/pages, nen mot trang da xoa van song o dia chi cu. Xem scripts\deploy_don_file_thua.py.
if not defined PY goto thuakhongpy
"%PY%" "%~dp0scripts\deploy_don_file_thua.py" "%~dp0." "%DEST%" check
if errorlevel 2 goto thualoi
if errorlevel 1 goto thuahoi
goto thuaxong

:thuahoi
echo.
set /p XOATHUA=    Xoa cac file .py cu nay tren may dich? (Y/n): 
if /i "%XOATHUA%"=="n" goto thuaboqua
"%PY%" "%~dp0scripts\deploy_don_file_thua.py" "%~dp0." "%DEST%" fix
goto thuaxong

:thuaboqua
echo     [BO QUA] Giu nguyen -- trang cu van mo duoc bang dia chi cu tren may chinh.
goto thuaxong

:thuakhongpy
echo     [!] Khong tim thay Python chay duoc -- BO QUA buoc do file thua.
goto thuaxong

:thualoi
echo     [!] Khong do duoc file thua -- xem thong bao tren.

:thuaxong
echo.

echo [7/8] Xoa __pycache__ cu tren may dich...
for /d /r "%DEST%" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d"
)

echo [8/8] Kiem tra thu vien Python...
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
