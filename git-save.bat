@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Luu thay doi (commit)
echo ============================================================
echo.

:: Lay nhanh hien tai
for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT=%%B"

:: Khong duoc commit thang vao main hoac develop
if "!CURRENT!"=="main" (
    echo [LOI] Dang o nhanh main -- khong commit thang vao day.
    echo       Chay git-start.bat truoc.
    pause & exit /b 1
)
if "!CURRENT!"=="develop" (
    echo [LOI] Dang o nhanh develop -- khong commit thang vao day.
    echo       Chay git-start.bat truoc.
    pause & exit /b 1
)

echo Nhanh hien tai: !CURRENT!
echo.

:: Canh bao neu .env co trong danh sach thay doi
git status | find ".env" >nul 2>&1
if not errorlevel 1 (
    echo [CANH BAO!] Phat hien file .env trong git status!
    echo            File nay chua mat khau -- TUYET DOI KHONG commit.
    echo            Kiem tra lai roi thu lai.
    echo.
    git status
    pause & exit /b 1
)

:: Hien thi cac file da thay doi
echo Cac file thay doi:
git status --short
echo.

:: Khong co gi de commit
git diff --quiet && git diff --staged --quiet
if not errorlevel 1 (
    echo [!] Khong co thay doi nao de luu.
    pause & exit /b 0
)

:: Hoi noi dung commit
echo Loai thay doi (dung lam tien to):
echo   feat     - tinh nang moi
echo   fix      - sua loi
echo   refactor - cai thien code (khong doi tinh nang)
echo   chore    - thu vien, cau hinh, build
echo.
set /p COMMIT_MSG=Noi dung commit (vi du: feat: them truong ly do huy):
if "!COMMIT_MSG!"=="" (
    echo [LOI] Noi dung khong duoc de trong.
    pause & exit /b 1
)

git add -A
git commit -m "!COMMIT_MSG!"

echo.
echo ============================================================
echo  Da luu thanh cong!
echo  Luu tiep khi co thay doi moi, hoac chay git-submit.bat
echo  khi xong het cong viec de nop cho nguoi review.
echo ============================================================
pause
