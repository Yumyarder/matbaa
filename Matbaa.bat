@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Matbaa - Akademik PDF - Kindle EPUB Studio
echo ============================================
echo.

REM --- Frontend: install deps once, build once (safe to re-run; skips if already done) ---
if not exist "frontend\node_modules" (
    echo [1/3] Frontend bagimliliklari kuruluyor, bu biraz surebilir...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo HATA: npm install basarisiz oldu. Node.js kurulu mu? https://nodejs.org
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo [1/3] Frontend bagimliliklari zaten kurulu, atlaniyor.
)

if not exist "backend\app\frontend_dist\index.html" (
    echo [2/3] Frontend derleniyor...
    pushd frontend
    call npm run build
    if errorlevel 1 (
        echo HATA: Frontend derlemesi basarisiz oldu.
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo [2/3] Frontend zaten derlenmis, atlaniyor.
    echo       (Frontend kodunu guncellediyseniz backend\app\frontend_dist klasorunu silip tekrar calistirin.)
)

REM --- Backend: create venv + install deps once ---
if not exist "backend\.venv\Scripts\python.exe" (
    echo [3/3] Python sanal ortami kuruluyor...
    pushd backend
    python -m venv .venv
    if errorlevel 1 (
        echo HATA: Python sanal ortami olusturulamadi. Python kurulu mu? https://python.org
        popd
        pause
        exit /b 1
    )
    call .venv\Scripts\python.exe -m pip install --upgrade pip
    call .venv\Scripts\pip.exe install -r requirements.txt
    if errorlevel 1 (
        echo HATA: Python bagimliliklari kurulamadi.
        popd
        pause
        exit /b 1
    )
    popd
) else (
    echo [3/3] Python sanal ortami zaten hazir, atlaniyor.
)

echo.
echo Matbaa baslatiliyor... Tarayici birazdan otomatik acilacak.
echo (http://127.0.0.1:8765)
echo Kapatmak icin bu pencereyi kapatin ya da Ctrl+C basin.
echo.

cd backend
.venv\Scripts\python.exe run_server.py

pause
