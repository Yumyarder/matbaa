@echo off
setlocal
cd /d "%~dp0"

echo ==========================================================
echo   Matbaa - gercek bir standalone .exe olusturuluyor
echo   (Bu adim, Node/Python kurulu olmayan bir bilgisayarda
echo    bile calisacak TEK BASINA bir Matbaa.exe uretir.)
echo ==========================================================
echo.

if not exist "backend\app\frontend_dist\index.html" (
    echo HATA: Once frontend derlenmis olmali.
    echo Once Matbaa.bat'i bir kez calistirin, ya da elle:
    echo   cd frontend
    echo   npm install
    echo   npm run build
    pause
    exit /b 1
)

cd backend

if not exist ".venv\Scripts\python.exe" (
    echo Python sanal ortami kuruluyor...
    python -m venv .venv
    call .venv\Scripts\python.exe -m pip install --upgrade pip
    call .venv\Scripts\pip.exe install -r requirements.txt
)

echo PyInstaller kuruluyor...
call .venv\Scripts\python.exe -m pip install pyinstaller

echo.
echo Derleniyor... (PyMuPDF/ebooklib nedeniyle birkac dakika surebilir)
echo.

REM Matbaa.spec lists the data the app reads beside its modules (the Kindle
REM typefaces, the Turkish word list) and the built frontend. Run through
REM python -m: the pip launchers (pyinstaller.exe) fail silently when the
REM folder path has a non-ASCII letter (as "Seyler2" with S-cedilla does).
.venv\Scripts\python.exe -m PyInstaller --noconfirm Matbaa.spec

if errorlevel 1 (
    echo.
    echo Derleme basarisiz oldu. README.md'deki "Matbaa.exe'yi kendiniz
    echo derlemek" bolumune bakin.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   Bitti! Matbaa.exe su klasorde: backend\dist\Matbaa.exe
echo   Bu tek dosyayi istediginiz yere kopyalayip calistirabilirsiniz.
echo ==========================================================
pause
