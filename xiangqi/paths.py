"""執行期搜尋路徑與使用者資料目錄。不依賴 pygame。"""
from __future__ import annotations

import os
import sys


APP_NAME = "ChineseChess"


def project_root():
    """專案根目錄（xiangqi 套件的上一層；與 chess.py 同層）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_runtime_search_dirs():
    """唯讀資源搜尋路徑（程式目錄、打包 _internal 等）。"""
    dirs = []

    def add(path):
        if path and path not in dirs:
            dirs.append(path)

    # 與舊版 chess.py 的 module_dir 相同：專案根，而非 xiangqi/ 本身
    add(project_root())

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        add(exe_dir)
        add(os.path.join(exe_dir, "_internal"))

    add(getattr(sys, "_MEIPASS", ""))
    return dirs


def get_user_data_dir():
    """可寫入的使用者資料目錄（語言、存檔、關卡進度）。

    Windows: %APPDATA%\\ChineseChess
    macOS: ~/Library/Application Support/ChineseChess
    其他: ~/.config/ChineseChess 或 $XDG_CONFIG_HOME/ChineseChess
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        # 回退到使用者家目錄下的隱藏資料夾
        path = os.path.join(os.path.expanduser("~"), f".{APP_NAME.lower()}")
        os.makedirs(path, exist_ok=True)
    return path


def get_user_data_path(filename):
    return os.path.join(get_user_data_dir(), filename)


def find_data_file(filename):
    """在執行目錄／打包目錄中尋找資料檔。"""
    for base in get_runtime_search_dirs():
        path = os.path.join(base, filename)
        if os.path.isfile(path):
            return path
    return os.path.join(project_root(), filename)
