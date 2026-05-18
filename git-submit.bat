@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Nop code de review (Push + mo Pull Request)
echo ============================================================
echo.

:: Lay nhanh hien tai
for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT=%%B"

if "!CURRENT!"=="main" (
    echo [LOI] Dang o nhanh main -- khong nop thang vao day.
    pause & exit /b 1
)
if "!CURRENT!"=="develop" (
    echo [LOI] Dang o nhanh develop -- khong nop thang vao day.
    pause & exit /b 1
)

echo Nhanh hien tai: !CURRENT!
echo.

:: Kiem tra con thay doi chua luu
git diff --quiet
if errorlevel 1 (
    echo [!] Con thay doi chua commit. Hay chay git-save.bat truoc.
    pause & exit /b 1
)

:: Lay code moi nhat
echo [1/3] Ket noi GitHub...
git fetch origin develop
if errorlevel 1 (
    echo [LOI] Khong ket noi duoc GitHub. Kiem tra mang.
    pause & exit /b 1
)

:: Rebase de tich hop code dong nghiep
echo [2/3] Cap nhat voi code moi nhat cua dong nghiep...
git rebase origin/develop
if errorlevel 1 (
    echo.
    echo [LOI] Xung dot (conflict) khi cap nhat!
    echo       Noi dung xung dot da duoc danh dau trong file lien quan.
    echo       Nho Nguoi 1 ho tro giai quyet.
    echo.
    echo       De huy va quay lai trang thai cu: git rebase --abort
    pause & exit /b 1
)

:: Day code len
echo [3/3] Dang day code len GitHub...
git push origin "!CURRENT!" --force-with-lease
if errorlevel 1 (
    echo [LOI] Khong the day code. Thu lai sau.
    pause & exit /b 1
)

:: Mo trinh duyet tao PR
set "PR_URL=https://github.com/khanhbq693/KSNB/compare/develop...!CURRENT!"
echo.
echo ============================================================
echo  Da day code thanh cong! Dang mo GitHub...
echo.
echo  Trong trang Pull Request vua mo:
echo  1. Dien mo ta: lam gi, test the nao, co thay doi DB khong
echo  2. Bam "Create pull request"
echo  3. Doi nguoi review phan hoi (trong 1 ngay lam viec)
echo ============================================================
start "" "!PR_URL!"
pause
