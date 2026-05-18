@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Bat dau cong viec moi
echo ============================================================
echo.

echo [1/3] Chuyen sang develop va lay code moi nhat...
git checkout develop
if errorlevel 1 (
    echo [LOI] Khong the chuyen sang develop.
    pause & exit /b 1
)
git pull origin develop
if errorlevel 1 (
    echo [LOI] Khong the lay code moi. Kiem tra ket noi mang.
    pause & exit /b 1
)

echo.
echo [2/3] Dat ten nhanh cho cong viec nay.
echo       Vi du: leaves/them-ly-do-huy   hoac   handover/sua-loi-tinh-tong
echo.
set /p BRANCH=Ten nhanh:
if "!BRANCH!"=="" (
    echo [LOI] Ten nhanh khong duoc de trong.
    pause & exit /b 1
)

echo.
echo [3/3] Tao nhanh moi: !BRANCH!
git checkout -b "!BRANCH!"
if errorlevel 1 (
    echo [LOI] Khong the tao nhanh. Co the nhanh nay da ton tai -- thu ten khac.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  San sang! Dang lam viec tren nhanh: !BRANCH!
echo  Khi xong mot phan, chay  git-save.bat  de luu lai.
echo ============================================================
pause
