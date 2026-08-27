"""存檔與局面庫。不依賴 pygame。"""
from __future__ import annotations

import json
import os

from .constants import CUSTOM_POSITIONS_FILE_NAME, CUSTOM_POSITIONS_LEGACY_NAME
from .paths import get_user_data_path

def load_custom_positions():
    """讀取局面編輯器專用局面庫（與 savegame.json 無關）。"""
    path = get_user_data_path(CUSTOM_POSITIONS_FILE_NAME)
    legacy = get_user_data_path(CUSTOM_POSITIONS_LEGACY_NAME)
    if not os.path.isfile(path) and os.path.isfile(legacy):
        path = legacy
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 嚴格只要 positions 陣列，避免誤讀存檔結構
        if not isinstance(data, dict) or "positions" not in data:
            if isinstance(data, list):
                items = data
            else:
                return []
        else:
            items = data.get("positions", [])
        if not isinstance(items, list):
            return []
        cleaned = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            # 拒絕對局存檔欄位混入
            if "moves" in raw or "game_state" in raw:
                continue
            fen = raw.get("fen")
            if not fen or not isinstance(fen, str):
                continue
            cleaned.append({
                "id": str(raw.get("id") or f"pos_{len(cleaned)+1}"),
                "title": str(raw.get("title") or raw.get("id") or "untitled"),
                "fen": fen.strip(),
            })
        return cleaned
    except Exception:
        return []


def save_custom_positions(positions):
    """寫入局面編輯器專用 JSON。回傳 (ok, error)。"""
    path = get_user_data_path(CUSTOM_POSITIONS_FILE_NAME)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "version": 1,
            "type": "editor_positions",  # 明確標記，避免與 savegame 混淆
            "positions": positions,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return True, ""
    except Exception as ex:
        return False, str(ex)

