# Chinese-Chess-Test
A Chinese Chess App created by AI.

## Windows
- Run packaged app: `dist/ChineseChess/ChineseChess.exe` (share the whole folder).
- Rebuild: `build_exe.bat` (or `python -m PyInstaller --noconfirm --clean ChineseChess.spec`).
- Source run: put `chess.py`, `pikafish.exe`, `pikafish.nnue`, `assets/`, `endgames.json` together, then `python chess.py`.

## macOS
Windows `.exe` **does not** run on Mac. See **[MACOS.md](./MACOS.md)** for:
- Running with Python + macOS `pikafish` binary
- Packaging with `./build_macos.sh` / `ChineseChess-mac.spec`

## Visual assets
The game loads optional art from:
- `assets/board.png` — wooden Xiangqi board
- `assets/pieces/{red|black}_{rook|knight|bishop|advisor|king|cannon|pawn}.png` — piece sprites

If these files are missing, the app falls back to generated graphics.

