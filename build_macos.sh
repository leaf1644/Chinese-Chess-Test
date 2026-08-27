#!/usr/bin/env bash
# 在 macOS 上打包 ChineseChess.app
# 用法：chmod +x build_macos.sh && ./build_macos.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/5] Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ first."
  exit 1
fi
python3 --version

echo "[2/5] Checking PyInstaller..."
if ! python3 -c "import PyInstaller" 2>/dev/null; then
  echo "Installing PyInstaller..."
  python3 -m pip install pyinstaller
fi

if ! python3 -c "import pygame" 2>/dev/null; then
  echo "Installing pygame..."
  python3 -m pip install pygame
fi

if [[ ! -f chess.py ]]; then
  echo "chess.py not found in $(pwd)"
  exit 1
fi

echo "[3/5] Checking engine files..."
ENGINE=""
if [[ -f pikafish ]]; then
  ENGINE="pikafish"
elif [[ -f pikafish-macos ]]; then
  ENGINE="pikafish-macos"
elif [[ -f engines/pikafish ]]; then
  ENGINE="engines/pikafish"
fi

if [[ -z "$ENGINE" ]]; then
  echo "ERROR: macOS pikafish binary not found."
  echo "Place an executable named 'pikafish' next to chess.py (NOT pikafish.exe)."
  echo "Also place 'pikafish.nnue' in the same folder."
  exit 1
fi

if [[ ! -f pikafish.nnue ]]; then
  echo "ERROR: pikafish.nnue not found next to chess.py"
  exit 1
fi

chmod +x "$ENGINE" || true
# 若引擎不叫 pikafish，複製一份方便打包與執行時尋找
if [[ "$ENGINE" != "pikafish" ]]; then
  cp -f "$ENGINE" ./pikafish
  chmod +x ./pikafish
  ENGINE="pikafish"
fi

echo "  Engine: ./$ENGINE"
echo "  NNUE:   ./pikafish.nnue"

echo "[4/5] Building with PyInstaller..."
if [[ -f ChineseChess-mac.spec ]]; then
  python3 -m PyInstaller --noconfirm --clean ChineseChess-mac.spec
else
  # windowed → .app；add-data 在 macOS 用冒號
  python3 -m PyInstaller --noconfirm --clean --windowed --name ChineseChess \
    --add-data "pikafish:." \
    --add-data "pikafish.nnue:." \
    --add-data "assets:assets" \
    --add-data "endgames.json:." \
    --add-data "language.json:." \
    chess.py
fi

echo "[5/5] Done."
if [[ -d dist/ChineseChess.app ]]; then
  echo "App:  dist/ChineseChess.app"
  echo "Tip:  xattr -cr dist/ChineseChess.app   # if Gatekeeper blocks first open"
elif [[ -d dist/ChineseChess ]]; then
  echo "Dir:  dist/ChineseChess/"
  echo "Run:  open dist/ChineseChess/ChineseChess.app  or  ./dist/ChineseChess/ChineseChess"
else
  echo "Check dist/ for output."
fi
echo "Share the whole app/folder, not a single binary only."
