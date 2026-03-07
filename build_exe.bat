@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo Python not found. Please install Python 3.10+ first.
  exit /b 1
)

echo [2/4] Checking PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
  echo Installing PyInstaller...
  python -m pip install pyinstaller
  if errorlevel 1 (
    echo Failed to install PyInstaller.
    exit /b 1
  )
)

if not exist "chess.py" (
  echo chess.py not found in current folder.
  exit /b 1
)

set EXTRA_ARGS=
if exist "pikafish.exe" set EXTRA_ARGS=%EXTRA_ARGS% --add-data "pikafish.exe;."
if exist "pikafish.nnue" set EXTRA_ARGS=%EXTRA_ARGS% --add-data "pikafish.nnue;."
if exist "assets" set EXTRA_ARGS=%EXTRA_ARGS% --add-data "assets;assets"

echo [3/4] Building EXE...
python -m PyInstaller --noconfirm --clean --windowed --name ChineseChess %EXTRA_ARGS% chess.py
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

echo [4/4] Done.
echo EXE output: dist\ChineseChess\ChineseChess.exe
echo Share the whole dist\ChineseChess folder to others.
exit /b 0
