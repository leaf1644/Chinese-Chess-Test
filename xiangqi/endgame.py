"""殘局關卡目錄與進度。不依賴 pygame。"""
from __future__ import annotations

import json
import os

from .constants import (
    ENDGAME_PROGRESS_FILE_NAME,
    ENDGAME_SECTION_CHALLENGE,
    ENDGAME_SECTION_FORMULA,
    ENDGAMES_FILE_NAME,
)
from .paths import find_data_file, get_user_data_path

def load_endgames_catalog(path=None):
    """讀取 endgames.json，回傳 (levels_list, error_message)。"""
    path = path or find_data_file(ENDGAMES_FILE_NAME)
    if not os.path.isfile(path):
        return [], f"找不到 {ENDGAMES_FILE_NAME}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as ex:
        return [], f"讀取殘局檔失敗：{ex}"

    levels = data.get("levels", [])
    if not isinstance(levels, list):
        return [], "endgames.json 格式錯誤：levels 必須是陣列"

    cleaned = []
    for i, raw in enumerate(levels):
        if not isinstance(raw, dict):
            continue
        level_id = str(raw.get("id") or f"level_{i+1}")
        fen = raw.get("fen")
        if not fen or not isinstance(fen, str):
            continue
        section = str(raw.get("section") or ENDGAME_SECTION_FORMULA).strip().lower()
        if section not in (ENDGAME_SECTION_FORMULA, ENDGAME_SECTION_CHALLENGE):
            section = ENDGAME_SECTION_FORMULA
        cleaned.append({
            "id": level_id,
            "title": str(raw.get("title") or level_id),
            "difficulty": int(raw.get("difficulty") or 1),
            "category": str(raw.get("category") or "殘局"),
            "section": section,
            "source": str(raw.get("source") or ""),
            "player_side": str(raw.get("player_side") or "red").lower(),
            "fen": fen.strip(),
            "goal": str(raw.get("goal") or "checkmate"),
            "max_player_moves": raw.get("max_player_moves"),
            "hint": str(raw.get("hint") or ""),
            "solution": raw.get("solution") if isinstance(raw.get("solution"), list) else [],
            "unlock_after": raw.get("unlock_after"),
        })
    return cleaned, None


def load_endgame_progress(path=None):
    """讀取關卡進度（優先 %APPDATA%/ChineseChess）。"""
    path = path or get_user_data_path(ENDGAME_PROGRESS_FILE_NAME)
    if not os.path.isfile(path):
        # 相容舊版：曾寫在程式目錄旁
        legacy = find_data_file(ENDGAME_PROGRESS_FILE_NAME)
        if legacy and os.path.isfile(legacy) and os.path.abspath(legacy) != os.path.abspath(path):
            path = legacy
        else:
            return {"cleared": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cleared = data.get("cleared", [])
        if not isinstance(cleared, list):
            cleared = []
        return {"cleared": [str(x) for x in cleared]}
    except Exception:
        return {"cleared": []}


def save_endgame_progress(progress, path=None):
    """寫入關卡進度到使用者資料目錄。回傳 (ok, error_message)。"""
    path = path or get_user_data_path(ENDGAME_PROGRESS_FILE_NAME)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return True, ""
    except Exception as ex:
        return False, str(ex)


def is_endgame_unlocked(level, cleared_ids):
    req = level.get("unlock_after")
    if not req:
        return True
    return str(req) in cleared_ids

