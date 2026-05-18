@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Cap nhat code moi nhat tu dong nghiep
echo ============================================================
echo.

:: Ghi nho nhanh hien tai de quay lai sau
for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT=%%B"
echo Nhanh hien tai: !CURRENT!
echo.

:: Canh bao neu chua luu het
git diff --quiet
if errorlevel 1 (
    echo [CANH BAO] Con thay doi chua commit tren nhanh nay.
    echo           Nen chay git-save.bat truoc khi cap nhat.
    echo.
    set /p CONFIRM=Tiep tuc? (y/N):
    if /i not "!CONFIRM!"=="y" (
        echo Huy.
        pause & exit /b 0
    )
    echo.
)

echo Dang lay code moi nhat...
git checkout develop
git pull origin develop
if errorlevel 1 (
    echo [LOI] Khong the cap nhat. Kiem tra ket noi mang.
    pause & exit /b 1
)

:: Quay lai nhanh cu (neu co)
if "!CURRENT!" NEQ "develop" if "!CURRENT!" NEQ "" (
    echo.
    echo Quay lai nhanh: !CURRENT!
    git checkout "!CURRENT!"
)

echo.
echo ============================================================
echo  Da cap nhat code moi nhat!
echo  Neu muon ap dung code moi nay vao nhanh dang lam:
echo    chay: git rebase origin/develop
echo  hoac dung git-submit.bat (tu dong lam buoc nay).
echo ============================================================
pause
