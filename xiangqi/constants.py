"""棋規／對局常數。不依賴 pygame。"""
from __future__ import annotations

# 棋手／棋子身分（不是 RGB）。繪製色見 SIDE_RGB／side_rgb()。
RED = "red"
BLACK = "black"

SIDE_RGB = {
    RED: (168, 36, 32),
    BLACK: (22, 20, 18),
}


def side_rgb(side):
    """身分 → 繪製用 RGB。誤傳舊版 RGB tuple 時仍可對回表。"""
    if side in SIDE_RGB:
        return SIDE_RGB[side]
    for ident, rgb in SIDE_RGB.items():
        if side == rgb:
            return rgb
    return SIDE_RGB[RED]


def parse_side(token, default=RED):
    """存檔／FEN／字串 → 身分。"""
    if token in (RED, BLACK):
        return token
    if token in ("r", "R", "w"):
        return RED
    if token in ("b", "B"):
        return BLACK
    return default


def opponent_side(side):
    return BLACK if side == RED else RED

# 對局／畫面模式（存檔仍寫入整數；畫面改由 Screen 物件切換）
MODE_MENU = 0
MODE_PVP = 1
MODE_AI = 2
MODE_ENDGAME_DIFF = 3
MODE_ENDGAME = 4
MODE_ENDGAME_LEVELS = 5
MODE_EDITOR = 6
MODE_EDITOR_LIB = 7

UCCI_FILES = "abcdefghi"
SAVE_FILE_NAME = "savegame.json"
ENDGAMES_FILE_NAME = "endgames.json"
ENDGAME_PROGRESS_FILE_NAME = "endgame_progress.json"
CUSTOM_POSITIONS_FILE_NAME = "editor_positions.json"
CUSTOM_POSITIONS_LEGACY_NAME = "custom_positions.json"

AI_DELAY_SEC = 1.0
AI_SUGGEST_MOVETIME_MS = 350
AI_DIFFICULTY_PRESETS = {
    "簡單": {"depth": 3, "movetime_ms": 50, "mistake_rate": 0.45},
    "中等": {"depth": 6, "movetime_ms": 150, "mistake_rate": 0.15},
    "困難": {"depth": None, "movetime_ms": 500, "mistake_rate": 0.03},
}
ENDGAME_AI_MOVETIME_MS = 3000
ENDGAME_AI_DEPTH = None
ENDGAME_AI_MAX_WAIT_SEC = 8.0
ANALYSIS_MOVETIME_MS = 400

TIME_CONTROL_PRESETS = [
    {"id": "none", "base_sec": 0, "inc_sec": 0},
    {"id": "10m", "base_sec": 10 * 60, "inc_sec": 0},
    {"id": "20m", "base_sec": 20 * 60, "inc_sec": 0},
    {"id": "10m5s", "base_sec": 10 * 60, "inc_sec": 5},
    {"id": "20m5s", "base_sec": 20 * 60, "inc_sec": 5},
]

PIECE_MAX_COUNT = {
    "帥": 1, "將": 1,
    "仕": 2, "士": 2,
    "相": 2, "象": 2,
    "馬": 2,
    "車": 2,
    "炮": 2, "包": 2,
    "兵": 5, "卒": 5,
}

PIECE_TO_FEN = {
    ('車', RED): 'R', ('馬', RED): 'N', ('相', RED): 'B', ('仕', RED): 'A', ('帥', RED): 'K', ('炮', RED): 'C', ('包', RED): 'C', ('兵', RED): 'P',
    ('車', BLACK): 'r', ('馬', BLACK): 'n', ('象', BLACK): 'b', ('士', BLACK): 'a', ('將', BLACK): 'k', ('包', BLACK): 'c', ('炮', BLACK): 'c', ('卒', BLACK): 'p',
}

FEN_TO_PIECE = {
    'R': ('車', RED), 'N': ('馬', RED), 'B': ('相', RED), 'A': ('仕', RED), 'K': ('帥', RED), 'C': ('炮', RED), 'P': ('兵', RED),
    'r': ('車', BLACK), 'n': ('馬', BLACK), 'b': ('象', BLACK), 'a': ('士', BLACK), 'k': ('將', BLACK), 'c': ('包', BLACK), 'p': ('卒', BLACK),
}

ENDGAME_SECTION_FORMULA = "formula"
ENDGAME_SECTION_CHALLENGE = "challenge"

ENDGAME_DIFF_GROUPS = [
    {"id": "beginner", "difficulties": (1, 2), "color": ((186, 200, 184), (170, 186, 168))},
    {"id": "intermediate", "difficulties": (3,), "color": ((214, 196, 168), (200, 180, 150))},
    {"id": "advanced", "difficulties": (4,), "color": ((210, 176, 168), (196, 160, 152))},
    {"id": "expert", "difficulties": (5,), "color": ((188, 180, 198), (172, 164, 184))},
]

EDITOR_PALETTE_RED = [
    ("帥", RED), ("仕", RED), ("相", RED), ("馬", RED),
    ("車", RED), ("炮", RED), ("兵", RED),
]
EDITOR_PALETTE_BLACK = [
    ("將", BLACK), ("士", BLACK), ("象", BLACK), ("馬", BLACK),
    ("車", BLACK), ("包", BLACK), ("卒", BLACK),
]
