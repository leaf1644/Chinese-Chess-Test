# macOS 執行與打包指南

> **重要：** 在 Windows 上打的 `ChineseChess.exe` **無法**在 Mac 上執行。  
> 請在 **Mac 本機** 執行原始碼，或在 **Mac 本機** 用 PyInstaller 打包成 `.app`。

---

## A. 在 Mac 上直接用 Python 執行（開發／自用）

### 1. 準備環境

```bash
# 建議 Python 3.10+（可用官方安裝包或 Homebrew）
python3 --version

# 進入專案目錄
cd /path/to/Chinese-Chess-Test-main

# （可選）虛擬環境
python3 -m venv .venv
source .venv/bin/activate

pip install pygame
```

### 2. 準備 Pikafish 引擎（Mac 版）

Windows 的 `pikafish.exe` **不能**用。需要 macOS 可執行檔，檔名建議為：

```text
pikafish          # 可執行檔
pikafish.nnue     # 網路權重（可與 Windows 版共用同一個 .nnue）
```

放到與 `chess.py` 同一層，例如：

```text
Chinese-Chess-Test-main/
  chess.py
  pikafish          ← macOS 二進位
  pikafish.nnue
  endgames.json
  language.json
  assets/
```

然後給予執行權限：

```bash
chmod +x ./pikafish
```

#### 如何取得 macOS 版 Pikafish？

1. 到 [Pikafish Releases](https://github.com/official-pikafish/Pikafish/releases) 查看是否有 **macOS / Darwin** 預編譯檔。  
2. 若沒有預編譯檔，需在 Mac 上從原始碼編譯（見官方說明）。  
3. 也可設定環境變數指定路徑：

```bash
export PIKAFISH_PATH="/完整路徑/pikafish"
```

**Apple Silicon（M1/M2/M3）** 與 **Intel Mac** 的二進位可能不同，請選對架構。

### 3. 執行

```bash
python3 chess.py
```

### 4. 使用者資料位置（Mac）

| 項目 | 路徑 |
|------|------|
| 語言、存檔、局面庫、進度 | `~/Library/Application Support/ChineseChess/` |

---

## B. 在 Mac 上打包成 `.app`（給別人用）

**必須在 macOS 上執行打包**（無法在 Windows 交叉編譯成可靠的 Mac App）。

### 1. 安裝依賴

```bash
cd /path/to/Chinese-Chess-Test-main
source .venv/bin/activate   # 若有虛擬環境
pip install pygame pyinstaller
```

### 2. 確認引擎檔

```bash
ls -l pikafish pikafish.nnue
chmod +x pikafish
# 可手動測引擎（可選）
./pikafish
# 輸入 uci 後應看到 id name ... 再輸入 quit
```

### 3. 一鍵打包

```bash
chmod +x build_macos.sh
./build_macos.sh
```

成功後輸出約為：

```text
dist/ChineseChess.app
```

或 onedir 目錄：

```text
dist/ChineseChess/
```

### 4. 手動 PyInstaller（等同腳本）

macOS 的 `--add-data` 用 **冒號** `:` 分隔：

```bash
python3 -m PyInstaller --noconfirm --clean --windowed --name ChineseChess \
  --add-data "pikafish:." \
  --add-data "pikafish.nnue:." \
  --add-data "assets:assets" \
  --add-data "endgames.json:." \
  --add-data "language.json:." \
  chess.py
```

若專案內有 `ChineseChess-mac.spec`，也可：

```bash
python3 -m PyInstaller --noconfirm --clean ChineseChess-mac.spec
```

### 5. 首次開啟被 Gatekeeper 擋下

未簽名 App 可能提示「無法驗證開發者」：

```bash
# 移除隔離屬性（本機測試常用）
xattr -cr dist/ChineseChess.app

# 或：系統設定 → 隱私權與安全性 → 仍要打開
```

正式對外發布建議：

- Apple Developer 帳號  
- `codesign` 簽名  
- 可選 `notarize` 公證  

### 6. 分享給別人

請分享 **整個** `ChineseChess.app`（或整個 `dist/ChineseChess` 資料夾），不要只給單一檔案。

對方若是不同 CPU 架構（Intel vs Apple Silicon），可能需要對應架構的 `pikafish` 與打包產物。

---

## C. 常見問題

### 1. 能開程式但沒有 AI？

- 檢查是否有 Mac 版 `pikafish`（非 `.exe`）  
- `chmod +x pikafish`  
- 對局中開「建議著法」或人機模式看頂部錯誤提示  

### 2. 中文字體怪怪的？

程式會嘗試 `pingfangtc`、`microsoftjhenghei` 等；Mac 一般會落到 **蘋方**，通常可讀。

### 3. Windows 與 Mac 能否共用存檔？

存檔都在各系統使用者資料夾，**不會自動同步**。  
可手動複製 JSON（如 `savegame.json`、`editor_positions.json`），但路徑不同。

### 4. 能否在 Windows 打 Mac 包？

**不建議／實務上不可靠。** 請在 Mac 上打包。

---

## D. 檢查清單（打包前）

- [ ] 在 Mac 上 `python3 chess.py` 可正常開棋盤  
- [ ] 人機對戰 / 建議著法可呼叫引擎  
- [ ] `pikafish` + `pikafish.nnue` 與 `chess.py` 同目錄  
- [ ] `assets/`、`endgames.json`、`language.json` 齊全  
- [ ] `./build_macos.sh` 成功  
- [ ] 雙擊 `.app` 可啟動（必要時 `xattr -cr`）  
