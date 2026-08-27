import pygame
import sys
import time
import os
import math
import random
import json
from contextlib import contextmanager
from dataclasses import dataclass

from xiangqi.engine import (
    DEFAULT_EVAL_MOVETIME_MS as AI_EVAL_MOVETIME_MS,
    DEFAULT_MOVETIME_MS as AI_MOVETIME_MS,
    INFINITE_SEARCH_MAX_WAIT_SEC as AI_INFINITE_SEARCH_MAX_WAIT_SEC,
    EngineDispatcher,
    EngineResult,
    EngineTask,
    PikafishEngine,
)
from xiangqi.i18n import (
    LANG_HANS,
    LANG_HANT,
    LANGUAGE_FILE_NAME,
    UI_STRINGS,
    ai_difficulty_display,
    diff_group_label,
    difficulty_label,
    get_lang,
    load_language_pref,
    save_language_pref,
    section_label,
    set_language,
    t,
    time_control_label,
)
from xiangqi.paths import (
    APP_NAME,
    find_data_file,
    get_runtime_search_dirs,
    get_user_data_dir,
    get_user_data_path,
)


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


def prompt_text_input(title, prompt, initial=""):
    """彈出輸入框（支援中文 IME），回傳字串或 None（取消）。"""
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            result = simpledialog.askstring(title, prompt, initialvalue=initial, parent=root)
        finally:
            root.destroy()
        if result is None:
            return None
        result = result.strip()
        return result if result else None
    except Exception:
        return None


def create_empty_xiangqi_board(turn=None):
    """空白棋盤（無子），供編輯器使用。"""
    board = XiangqiBoard(MODE_PVP)
    board.pieces = []
    board.turn = RED if turn is None else turn
    board.selected_piece = None
    board.winner = None
    board.is_check = False
    board.draw_reason = ""
    board.warning_msg = ""
    board.moves = []
    board.board_state_history = {}
    return board


# 象棋各兵種每方上限（將帥 1；兵卒 5；其餘 2）
PIECE_MAX_COUNT = {
    "帥": 1, "將": 1,
    "仕": 2, "士": 2,
    "相": 2, "象": 2,
    "馬": 2,
    "車": 2,
    "炮": 2, "包": 2,
    "兵": 5, "卒": 5,
}


def count_pieces_by_side_and_name(board):
    """回傳 {(color, name): count}。"""
    counts = {}
    for p in board.pieces:
        key = (p.color, p.name)
        counts[key] = counts.get(key, 0) + 1
    return counts


def validate_piece_counts(board):
    """檢查每方各兵種數量不超過規則上限。回傳 (ok, reason)。"""
    counts = count_pieces_by_side_and_name(board)
    for (color, name), n in counts.items():
        limit = PIECE_MAX_COUNT.get(name)
        if limit is None:
            return False, f"未知棋子：{name}"
        if n > limit:
            side = "紅" if color == RED else "黑"
            return False, f"{side}方「{name}」最多 {limit} 枚，目前 {n} 枚"
    # 將帥必須恰好各 1（有子局面）
    red_k = counts.get((RED, "帥"), 0)
    black_k = counts.get((BLACK, "將"), 0)
    if red_k != 1 or black_k != 1:
        return False, t("editor_need_kings")
    return True, ""


def validate_editor_position(board):
    """編輯器／自訂開局完整合法性。

    - 將帥各恰好 1，且在己方九宮合法格
    - 士／象／兵等皆在可到達格（is_legal_piece_square）
    - 各兵種數量不超上限（將 1、兵 5、其餘 2）
    - 不疊子、不照面
    - **雙方皆不可已被將軍**（避免開局將死／解將邏輯異常）
    - 行棋方須有合法著（非已終局）

    回傳 (ok, reason)。
    """
    ok_place, reason = validate_endgame_piece_placements(board)
    if not ok_place:
        return False, reason

    ok_cnt, reason_cnt = validate_piece_counts(board)
    if not ok_cnt:
        return False, reason_cnt

    if board.is_kings_facing():
        return False, t("editor_kings_facing")

    # 禁止開局已被將軍（含將死）
    if board.is_under_attack(RED):
        return False, t("editor_red_in_check")
    if board.is_under_attack(BLACK):
        return False, t("editor_black_in_check")

    if not board.has_valid_move(board.turn):
        return False, t("editor_no_legal_move")

    return True, ""


def get_initial_window_size():
    info = pygame.display.Info()
    available_width = max(320, info.current_w - 80)
    available_height = max(240, info.current_h - 120)
    scale = min(available_width / SCREEN_WIDTH, available_height / SCREEN_HEIGHT, 1.0)
    return (
        max(320, int(SCREEN_WIDTH * scale)),
        max(240, int(SCREEN_HEIGHT * scale)),
    )


def get_render_rect(window_size):
    window_width, window_height = window_size
    scale = min(window_width / SCREEN_WIDTH, window_height / SCREEN_HEIGHT)
    render_width = max(1, int(SCREEN_WIDTH * scale))
    render_height = max(1, int(SCREEN_HEIGHT * scale))
    return pygame.Rect(
        (window_width - render_width) // 2,
        (window_height - render_height) // 2,
        render_width,
        render_height,
    )


def window_to_logical_pos(pos, render_rect):
    if render_rect.width <= 0 or render_rect.height <= 0:
        return (-1, -1)

    x, y = pos
    if not render_rect.collidepoint(x, y):
        return (-1, -1)

    logical_x = int((x - render_rect.x) * SCREEN_WIDTH / render_rect.width)
    logical_y = int((y - render_rect.y) * SCREEN_HEIGHT / render_rect.height)
    return (
        max(0, min(SCREEN_WIDTH - 1, logical_x)),
        max(0, min(SCREEN_HEIGHT - 1, logical_y)),
    )

# --- 1. 系統常數 ---
SCREEN_WIDTH = 1100
SCREEN_HEIGHT = 900
GRID_SIZE = 64
BOARD_WIDTH = 8 * GRID_SIZE + 10
BOARD_HEIGHT = 9 * GRID_SIZE + 10
TOP_UI_HEIGHT = 130

# 對局頁：棋盤偏左，右側留給較大的「移動記錄」面板
MARGIN_X = 28
MARGIN_Y = (SCREEN_HEIGHT - BOARD_HEIGHT) // 2 + 40
HISTORY_PANEL_GAP = 16          # 棋盤與記錄區間距
HISTORY_PANEL_RIGHT = 18        # 記錄區右緣留白
HISTORY_LINE_H = 26             # 每步主行高
HISTORY_PV_LINE_H = 20          # 變例折行高

# --- 主題：現代新中式極簡（暖米白 + 柔和灰卡 + 微圓角軟陰影）---
# 背景／卡片
COLOR_BG = (246, 242, 234)           # 暖米白
COLOR_BG_SOFT = (238, 233, 224)      # 略深米底（分層用）
COLOR_CARD = (252, 250, 246)         # 卡片面
COLOR_CARD_ALT = (236, 232, 226)     # 次級灰卡
COLOR_CARD_BORDER = (200, 194, 184)  # 微邊線（略加深以分界）
COLOR_SHADOW = (40, 36, 32)          # 陰影色（搭配 alpha）
# 文字／線條（UI）——提高對比，避免米底上發灰難讀
COLOR_TEXT = (22, 20, 18)            # 主文字：近墨黑
COLOR_TEXT_SECONDARY = (52, 48, 44)  # 次要文字：仍清楚可讀
COLOR_TEXT_ON_DARK = (252, 250, 246)
COLOR_LINE = (36, 32, 28)            # 棋盤／分割線
COLOR_UI_BAR = (48, 44, 40)          # 頂欄：稍深以襯亮字
COLOR_SELECTED = (70, 120, 90)       # 選中：略加深青綠
# 棋子色（保留辨識度）
RED = (168, 36, 32)
BLACK = (22, 20, 18)
WHITE = (255, 255, 255)
GOLD = (160, 118, 48)                # 霧金（略加深，米底可讀）
WARNING_COLOR = (168, 40, 36)
SUCCESS_COLOR = (40, 110, 72)
# 按鈕
BUTTON_COLOR = (236, 230, 220)
BUTTON_HOVER_COLOR = (220, 212, 200)
BUTTON_TEXT = (22, 20, 18)           # 按鈕字：深墨
BUTTON_BORDER = (168, 160, 148)
BUTTON_RADIUS = 10
# 危險／次要操作
BUTTON_DANGER = (200, 130, 120)
BUTTON_DANGER_HOVER = (210, 150, 140)
BUTTON_ACCENT = (186, 178, 200)
BUTTON_ACCENT_HOVER = (200, 192, 214)
# 相容舊名
COLOR_PRIMARY = (90, 70, 54)         # 新中式暖褐墨

def _clamp_byte(v):
    return max(0, min(255, int(v)))


def blend_rgb(c1, c2, t):
    """線性混色 t∈[0,1]。"""
    return tuple(_clamp_byte(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_soft_shadow(surface, rect, radius=12, offset=(3, 4), layers=4, alpha=28):
    """柔和多層陰影（不改動原 rect）。"""
    if layers <= 0:
        return
    shadow_surf = pygame.Surface((rect.width + offset[0] * 4 + 12, rect.height + offset[1] * 4 + 12), pygame.SRCALPHA)
    base_x, base_y = 6, 6
    for i in range(layers, 0, -1):
        expand = i * 2
        a = max(6, alpha // i)
        r = pygame.Rect(
            base_x - expand + offset[0],
            base_y - expand + offset[1],
            rect.width + expand * 2,
            rect.height + expand * 2,
        )
        pygame.draw.rect(shadow_surf, (*COLOR_SHADOW, a), r, border_radius=radius + expand)
    surface.blit(shadow_surf, (rect.x - 6, rect.y - 6))


def draw_card(surface, rect, fill=COLOR_CARD, border=COLOR_CARD_BORDER, radius=14, shadow=True, border_width=1):
    """圓角卡片：可選軟陰影 + 淺邊框。"""
    if shadow:
        draw_soft_shadow(surface, rect, radius=radius)
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    if border_width > 0 and border:
        pygame.draw.rect(surface, border, rect, border_width, border_radius=radius)


def draw_badge(surface, center, text, font, bg=None, fg=None, pad_x=12, pad_y=5, radius=12):
    """小標籤（Badge）：回傳占用的 rect。"""
    if bg is None:
        bg = COLOR_CARD_ALT
    if fg is None:
        fg = COLOR_TEXT
    ts = font.render(text, True, fg)
    r = ts.get_rect()
    r.width += pad_x * 2
    r.height += pad_y * 2
    r.center = center
    pygame.draw.rect(surface, bg, r, border_radius=radius)
    pygame.draw.rect(surface, COLOR_CARD_BORDER, r, 1, border_radius=radius)
    surface.blit(ts, ts.get_rect(center=r.center))
    return r


def draw_badges_row(surface, centers_y, items, font, gap=10):
    """水平排列多個 badge；items = [(text, bg, fg), ...]。以 centers_y 的 y、畫面水平置中。"""
    if not items:
        return
    rendered = []
    total_w = 0
    for text, bg, fg in items:
        ts = font.render(text, True, fg or COLOR_TEXT)
        w = ts.get_width() + 24
        h = ts.get_height() + 10
        rendered.append((text, bg, fg, ts, w, h))
        total_w += w
    total_w += gap * (len(rendered) - 1)
    x = (SCREEN_WIDTH - total_w) // 2
    # 若需在卡片內置中，呼叫端可改用 draw_badge 逐一畫
    for text, bg, fg, ts, w, h in rendered:
        r = pygame.Rect(x, centers_y - h // 2, w, h)
        pygame.draw.rect(surface, bg or COLOR_CARD_ALT, r, border_radius=12)
        pygame.draw.rect(surface, COLOR_CARD_BORDER, r, 1, border_radius=12)
        surface.blit(ts, ts.get_rect(center=r.center))
        x += w + gap


def draw_badges_in_card(surface, card_rect, y, items, font, gap=8):
    """在卡片內水平置中排列 badges。"""
    if not items:
        return
    specs = []
    total_w = 0
    for text, bg, fg in items:
        ts = font.render(text, True, fg or COLOR_TEXT)
        w = ts.get_width() + 22
        h = max(26, ts.get_height() + 8)
        specs.append((ts, bg, w, h))
        total_w += w
    total_w += gap * (len(specs) - 1)
    x = card_rect.centerx - total_w // 2
    for ts, bg, w, h in specs:
        r = pygame.Rect(x, y - h // 2, w, h)
        pygame.draw.rect(surface, bg or COLOR_CARD_ALT, r, border_radius=11)
        pygame.draw.rect(surface, COLOR_CARD_BORDER, r, 1, border_radius=11)
        surface.blit(ts, ts.get_rect(center=r.center))
        x += w + gap

# 遊戲模式
MODE_MENU = 0              # 主選單
MODE_PVP = 1               # 玩家對玩家
MODE_AI = 2                # 玩家對 AI
MODE_ENDGAME_DIFF = 3      # 殘局闖關：選擇難度
MODE_ENDGAME = 4           # 殘局闖關：對局中
MODE_ENDGAME_LEVELS = 5    # 殘局闖關：該難度下的關卡列表
MODE_EDITOR = 6            # 局面編輯器
MODE_EDITOR_LIB = 7        # 已存局面庫（載入／重新命名）

# 編輯器棋子調色盤（紅／黑）
EDITOR_PALETTE_RED = [
    ("帥", RED), ("仕", RED), ("相", RED), ("馬", RED),
    ("車", RED), ("炮", RED), ("兵", RED),
]
EDITOR_PALETTE_BLACK = [
    ("將", BLACK), ("士", BLACK), ("象", BLACK), ("馬", BLACK),
    ("車", BLACK), ("包", BLACK), ("卒", BLACK),
]
# 與對局存檔 savegame.json 完全分開，禁止混讀
CUSTOM_POSITIONS_FILE_NAME = "editor_positions.json"
# 舊檔名相容遷移
CUSTOM_POSITIONS_LEGACY_NAME = "custom_positions.json"

# AI 相關設定（思考時間預設見 xiangqi.engine）
AI_DELAY_SEC = 1.0
AI_SUGGEST_MOVETIME_MS = 350
UCCI_FILES = "abcdefghi"
SAVE_FILE_NAME = "savegame.json"
ENDGAMES_FILE_NAME = "endgames.json"
ENDGAME_PROGRESS_FILE_NAME = "endgame_progress.json"

AI_DIFFICULTY_PRESETS = {
    "簡單": {"depth": 3, "movetime_ms": 50, "mistake_rate": 0.45},
    "中等": {"depth": 6, "movetime_ms": 150, "mistake_rate": 0.15},
    "困難": {"depth": None, "movetime_ms": 500, "mistake_rate": 0.03},
}
# 殘局闖關固定最高強度：不故意失誤，給引擎更長思考時間
ENDGAME_AI_MOVETIME_MS = 3000
ENDGAME_AI_DEPTH = None
ENDGAME_AI_MAX_WAIT_SEC = 8.0

# 賽後分析用引擎思考時間（毫秒／局面）
ANALYSIS_MOVETIME_MS = 400

# 棋鐘預設（base 基本時間秒；inc 每步加秒）
TIME_CONTROL_PRESETS = [
    {"id": "none", "base_sec": 0, "inc_sec": 0},
    {"id": "10m", "base_sec": 10 * 60, "inc_sec": 0},
    {"id": "20m", "base_sec": 20 * 60, "inc_sec": 0},
    {"id": "10m5s", "base_sec": 10 * 60, "inc_sec": 5},
    {"id": "20m5s", "base_sec": 20 * 60, "inc_sec": 5},
]

# 評分損失（centipawn，行棋方視角）→ 標記
def classify_move_quality(cp_loss):
    """依分數損失標記好棋／失誤／嚴重失誤。"""
    if cp_loss is None:
        return "unknown"
    if cp_loss <= 30:
        return "best"
    if cp_loss <= 80:
        return "good"
    if cp_loss <= 250:
        return "mistake"
    return "blunder"


def score_to_cp(score_type, score_value):
    """將引擎 score 轉成近似 centipawn（越大對 side-to-move 越好）。"""
    if score_type == "mate":
        if score_value == 0:
            return 0
        # mate in N → 很大正分；被殺 mate -N → 很大負分
        sign = 1 if score_value > 0 else -1
        return sign * (100000 - min(abs(score_value), 500) * 100)
    return int(score_value)


def format_clock_ms(ms):
    """毫秒 → mm:ss 顯示。"""
    ms = max(0, int(ms))
    total_sec = (ms + 999) // 1000  # 顯示向上取整秒，避免 0.1s 顯示 0:00 誤判
    m, s = divmod(total_sec, 60)
    return f"{m:02d}:{s:02d}"

PIECE_TO_FEN = {
    ('車', RED): 'R', ('馬', RED): 'N', ('相', RED): 'B', ('仕', RED): 'A', ('帥', RED): 'K', ('炮', RED): 'C', ('包', RED): 'C', ('兵', RED): 'P',
    ('車', BLACK): 'r', ('馬', BLACK): 'n', ('象', BLACK): 'b', ('士', BLACK): 'a', ('將', BLACK): 'k', ('包', BLACK): 'c', ('炮', BLACK): 'c', ('卒', BLACK): 'p',
}

# FEN 字元 → (棋子名, 顏色)；載入殘局用（黑方用象/士/將/包/卒）
FEN_TO_PIECE = {
    'R': ('車', RED), 'N': ('馬', RED), 'B': ('相', RED), 'A': ('仕', RED), 'K': ('帥', RED), 'C': ('炮', RED), 'P': ('兵', RED),
    'r': ('車', BLACK), 'n': ('馬', BLACK), 'b': ('象', BLACK), 'a': ('士', BLACK), 'k': ('將', BLACK), 'c': ('包', BLACK), 'p': ('卒', BLACK),
}

# 殘局兩大區塊（主選單右欄進入）
ENDGAME_SECTION_FORMULA = "formula"      # 定式訓練（基本殺法）
ENDGAME_SECTION_CHALLENGE = "challenge"  # 殘局闖關（如適情雅趣）

# 殘局選關：入門與初級合併為同一分組（label 由 t() 依語言產生）
ENDGAME_DIFF_GROUPS = [
    # 低飽和色塊，貼合新中式灰調
    {"id": "beginner", "difficulties": (1, 2), "color": ((186, 200, 184), (170, 186, 168))},
    {"id": "intermediate", "difficulties": (3,), "color": ((214, 196, 168), (200, 180, 150))},
    {"id": "advanced", "difficulties": (4,), "color": ((210, 176, 168), (196, 160, 152))},
    {"id": "expert", "difficulties": (5,), "color": ((188, 180, 198), (172, 164, 184))},
]

# 主選單三欄版面（左：對戰　中：AI　右：殘局）
MENU_COL_GAP = 28
MENU_COL_W = 318
MENU_COL_TOP = 168
MENU_COL_H = 470
MENU_CARD_PAD_X = 24          # 卡片左右內邊距
MENU_CARD_TITLE_Y = 30        # 欄目標題相對卡片頂
MENU_CARD_DESC_Y = 62         # 描述文字
MENU_CARD_BTN_START = 112     # 首顆按鈕（與描述拉開呼吸空間）
MENU_CARD_BTN_GAP = 16
# 三欄同屬柔和灰卡，僅微差色溫以區分
MENU_PANEL_COLORS = (
    (250, 248, 244),  # pvp
    (246, 246, 244),  # ai
    (248, 247, 242),  # endgame
)
# 字體候選：標題偏書法／楷體；內文偏正黑／黑體
FONT_UI_CANDIDATES = [
    "microsoftjhenghei", "microsoftyahei", "noto sans cjk tc",
    "source hans sans tc", "pingfangtc", "simhei", "arialunicodems",
]
FONT_TITLE_CANDIDATES = [
    "kaiti", "kaiu", "stkaiti", "stxingkai", "dfkai-sb", "simkai",
    "fangsong", "stfangsong", "microsoftjhenghei",
]
# Badge 色
BADGE_BG_FORMULA = (220, 226, 216)
BADGE_BG_CHALLENGE = (228, 220, 210)
BADGE_FG = (36, 32, 28)

# 對局頁底部按鈕列（等間距置中）
BOTTOM_BTN_Y = SCREEN_HEIGHT - 50
BOTTOM_BTN_H = 38
BOTTOM_BTN_GAP = 14
BOTTOM_BTN_MARGIN_X = 20

# 殘局關卡列表版面（邏輯座標，與 SCREEN_* 一致）
ENDGAME_HEADER_Y = 48
ENDGAME_LEGEND_Y = 115
ENDGAME_BACK_Y = 160
ENDGAME_LIST_TOP = 230
ENDGAME_LIST_BOTTOM = SCREEN_HEIGHT - 50
ENDGAME_LIST_LEFT = SCREEN_WIDTH // 2 - 280
ENDGAME_LIST_WIDTH = 560
ENDGAME_ROW_H = 58
ENDGAME_SCROLLBAR_W = 16

def board_to_ucci(x, y):
    return f"{UCCI_FILES[x]}{9 - y}"

def ucci_to_board(ucci):
    if len(ucci) < 2:
        return None
    file_char = ucci[0]
    rank_char = ucci[1]
    if file_char not in UCCI_FILES or not rank_char.isdigit():
        return None
    x = ord(file_char) - ord('a')
    y = 9 - int(rank_char)
    if not (0 <= x <= 8 and 0 <= y <= 9):
        return None
    return (x, y)


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


# 士／仕只能走斜線，九宮內實際可達格（與棋盤格色一致）
_ADVISOR_SQUARES_BLACK = frozenset({(3, 0), (5, 0), (4, 1), (3, 2), (5, 2)})
_ADVISOR_SQUARES_RED = frozenset({(3, 9), (5, 9), (4, 8), (3, 7), (5, 7)})
# 象／相不渡河，七個固定落點
_ELEPHANT_SQUARES_BLACK = frozenset({(2, 0), (6, 0), (0, 2), (4, 2), (8, 2), (2, 4), (6, 4)})
_ELEPHANT_SQUARES_RED = frozenset({(2, 9), (6, 9), (0, 7), (4, 7), (8, 7), (2, 5), (6, 5)})
# 兵／卒未過河時只能在原縱線（偶數 file）
_PAWN_HOME_FILES = frozenset({0, 2, 4, 6, 8})


def is_legal_piece_square(name, color, x, y):
    """檢查單一棋子是否站在規則允許的格子（不論如何運子能否到達）。

    回傳 (ok, reason)。用於殘局 FEN 審核，避免士落在九宮非斜線格等錯誤。
    """
    if not (0 <= x <= 8 and 0 <= y <= 9):
        return False, f"{name} 超出棋盤 ({x},{y})"

    if name in ('帥', '將'):
        if not (3 <= x <= 5):
            return False, f"{name} 必須在九宮內（x=3..5），目前 ({x},{y})"
        if color == RED and not (7 <= y <= 9):
            return False, f"帥必須在紅方九宮（y=7..9），目前 ({x},{y})"
        if color == BLACK and not (0 <= y <= 2):
            return False, f"將必須在黑方九宮（y=0..2），目前 ({x},{y})"
        return True, ""

    if name in ('仕', '士'):
        allowed = _ADVISOR_SQUARES_RED if color == RED else _ADVISOR_SQUARES_BLACK
        if (x, y) not in allowed:
            return False, (
                f"{name} 只能在九宮斜線格 "
                f"{'仕:(3,9)(5,9)(4,8)(3,7)(5,7)' if color == RED else '士:(3,0)(5,0)(4,1)(3,2)(5,2)'}，"
                f"目前 ({x},{y}) 非法"
            )
        return True, ""

    if name in ('相', '象'):
        allowed = _ELEPHANT_SQUARES_RED if color == RED else _ELEPHANT_SQUARES_BLACK
        if (x, y) not in allowed:
            return False, f"{name} 不在可到達的象位 ({x},{y})"
        return True, ""

    if name in ('兵', '卒'):
        # 紅兵由 y=6 向上，不能在 y>6；黑卒由 y=3 向下，不能在 y<3
        if color == RED:
            if y > 6:
                return False, f"兵不可能在 y={y}（起始列為 6，只會前進）"
            # 未過河（y>=5）：只能在原縱線 0/2/4/6/8
            if y >= 5 and x not in _PAWN_HOME_FILES:
                return False, f"兵未過河時只能在縱線 0/2/4/6/8，目前 ({x},{y})"
        else:
            if y < 3:
                return False, f"卒不可能在 y={y}（起始列為 3，只會前進）"
            if y <= 4 and x not in _PAWN_HOME_FILES:
                return False, f"卒未過河時只能在縱線 0/2/4/6/8，目前 ({x},{y})"
        return True, ""

    # 車馬炮可在任意格
    return True, ""


def validate_endgame_piece_placements(board):
    """檢查盤上每個棋子是否在合法格、將帥各一、無疊子。

    回傳 (ok, reason)。
    """
    seen = {}
    king_red = 0
    king_black = 0
    for p in board.pieces:
        key = (p.x, p.y)
        if key in seen:
            return False, f"疊子：({p.x},{p.y}) 同時有 {seen[key]} 與 {p.name}"
        seen[key] = p.name
        ok, reason = is_legal_piece_square(p.name, p.color, p.x, p.y)
        if not ok:
            return False, reason
        if p.name == '帥':
            king_red += 1
        elif p.name == '將':
            king_black += 1
    if king_red != 1:
        return False, f"紅方帥數量應為 1，目前 {king_red}"
    if king_black != 1:
        return False, f"黑方將數量應為 1，目前 {king_black}"
    return True, ""


def validate_endgame_start_position(board):
    """殘局開局必須：棋子合法落點、雙方皆未被將軍、將帥不照面、雙方皆有合法著。

    回傳 (ok, reason)。
    """
    ok_place, reason_place = validate_endgame_piece_placements(board)
    if not ok_place:
        return False, reason_place
    if board.is_kings_facing():
        return False, "開局將帥照面（非法局面）"
    if board.is_under_attack(RED):
        return False, "開局紅方已被將軍（殘局不應如此）"
    if board.is_under_attack(BLACK):
        return False, "開局黑方已被將軍（殘局不應如此）"
    if not board.get_king(RED) or not board.get_king(BLACK):
        return False, "開局缺少將或帥"
    if not board.has_valid_move(board.turn):
        return False, "行棋方開局無合法著（已是終局）"
    opp = BLACK if board.turn == RED else RED
    if not board.has_valid_move(opp):
        return False, "對方開局已無合法著（已是困斃／將死）"
    return True, ""


def piece_type_from_name(name):
    if name == '車':
        return "rook"
    if name == '馬':
        return "knight"
    if name in ('相', '象'):
        return "bishop"
    if name in ('仕', '士'):
        return "advisor"
    if name in ('帥', '將'):
        return "king"
    if name in ('炮', '包'):
        return "cannon"
    if name in ('兵', '卒'):
        return "pawn"
    return None


def create_generated_board_surface():
    width = 8 * GRID_SIZE + 10
    height = 9 * GRID_SIZE + 10
    surf = pygame.Surface((width, height))

    # 生成木紋底色：垂直漸層 + 正弦紋理。
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(224 - 30 * ratio)
        g = int(198 - 28 * ratio)
        b = int(150 - 16 * ratio)
        for x in range(width):
            wood = int(8 * math.sin((x * 0.18) + (y * 0.03)) + 4 * math.sin(x * 0.05))
            rr = max(0, min(255, r + wood))
            gg = max(0, min(255, g + wood))
            bb = max(0, min(255, b + wood))
            surf.set_at((x, y), (rr, gg, bb))

    return surf


def create_generated_piece_sprite(piece_name, piece_color, font_names):
    size = GRID_SIZE
    center = size // 2
    radius = GRID_SIZE // 2 - 2

    sprite = pygame.Surface((size, size), pygame.SRCALPHA)
    # 柔和陰影
    pygame.draw.circle(sprite, (70, 62, 54, 90), (center + 2, center + 3), radius - 1)
    # 棋子底：暖米白
    pygame.draw.circle(sprite, (250, 246, 238), (center, center), radius - 1)
    # 外框
    pygame.draw.circle(sprite, piece_color, (center, center), radius - 1, 3)

    # 內圓紋理（淡墨）
    pygame.draw.circle(sprite, (200, 192, 180, 100), (center, center), radius - 7, 1)
    pygame.draw.circle(sprite, (190, 182, 170, 70), (center, center), radius - 10, 1)

    font = pygame.font.SysFont(font_names, 30, bold=True)
    text = font.render(piece_name, True, piece_color)
    text_rect = text.get_rect(center=(center, center))
    sprite.blit(text, text_rect)
    return sprite


def load_visual_assets(font_names):
    """載入棋盤與棋子素材。

    回傳 (board_surface, piece_sprites, board_from_asset)
    board_from_asset=True 表示使用真實棋盤圖，繪圖時應略過程式格線／楚河漢界以免重疊。
    """
    base_dir = next(iter(get_runtime_search_dirs()), os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(base_dir, "assets")
    pieces_dir = os.path.join(assets_dir, "pieces")

    for candidate_base in get_runtime_search_dirs():
        candidate_assets = os.path.join(candidate_base, "assets")
        if os.path.isdir(candidate_assets):
            assets_dir = candidate_assets
            pieces_dir = os.path.join(candidate_assets, "pieces")
            break

    board_surface = None
    board_from_asset = False
    board_candidates = [
        os.path.join(assets_dir, "board.png"),
        os.path.join(assets_dir, "board.jpg"),
        os.path.join(assets_dir, "board.jpeg"),
    ]
    for path in board_candidates:
        if os.path.exists(path):
            try:
                raw = pygame.image.load(path).convert()
                board_surface = pygame.transform.smoothscale(raw, (8 * GRID_SIZE + 10, 9 * GRID_SIZE + 10))
                board_from_asset = True
                break
            except Exception:
                board_surface = None
                board_from_asset = False

    if board_surface is None:
        board_surface = create_generated_board_surface()
        board_from_asset = False

    piece_sprites = {}
    for piece_name, piece_color in PIECE_TO_FEN.keys():
        key = (piece_name, piece_color)
        if key in piece_sprites:
            continue

        side = "red" if piece_color == RED else "black"
        piece_type = piece_type_from_name(piece_name)
        sprite = None
        if piece_type:
            for ext in ("png", "jpg", "jpeg"):
                candidate = os.path.join(pieces_dir, f"{side}_{piece_type}.{ext}")
                if os.path.exists(candidate):
                    try:
                        raw = pygame.image.load(candidate).convert_alpha()
                        # 俯視棋子略小於格距，中心對準交叉點時不致蓋住鄰線太多
                        piece_draw_size = max(40, int(GRID_SIZE * 0.88))
                        sprite = pygame.transform.smoothscale(raw, (piece_draw_size, piece_draw_size))
                        break
                    except Exception:
                        sprite = None

        if sprite is None:
            sprite = create_generated_piece_sprite(piece_name, piece_color, font_names)
        piece_sprites[key] = sprite

    return board_surface, piece_sprites, board_from_asset


def draw_piece_with_assets(screen, piece, font, view_color, piece_sprites):
    if view_color == BLACK:
        draw_x = 8 - piece.x
        draw_y = 9 - piece.y
    else:
        draw_x = piece.x
        draw_y = piece.y

    cx = MARGIN_X + draw_x * GRID_SIZE
    cy = MARGIN_Y + draw_y * GRID_SIZE

    sprite = piece_sprites.get((piece.name, piece.color))
    if sprite:
        rect = sprite.get_rect(center=(cx, cy))
        screen.blit(sprite, rect)
        if piece.selected:
            pygame.draw.circle(screen, COLOR_SELECTED, (cx, cy), GRID_SIZE // 2 + 2, 4)
        return

    piece.draw(screen, font, view_color)


@dataclass
class Move:
    """一步棋的完整紀錄。悔棋只 pop 這一筆。"""
    piece: object
    old_x: int
    old_y: int
    new_x: int
    new_y: int
    captured: object
    ucci: str
    notation: str
    is_check: bool
    is_capture: bool
    is_rootless_capture: bool
    piece_id: int
    is_chase: bool
    chase_targets: tuple
    signature: tuple
    repeat_state_key: object = None

# --- 2. 棋子類別 ---
class Piece:
    def __init__(self, name, color, x, y):
        self.name = name
        self.color = color 
        self.x = x
        self.y = y
        self.selected = False

    def draw(self, screen, font, view_color=RED):
        if view_color == BLACK:
            draw_x = 8 - self.x
            draw_y = 9 - self.y
        else:
            draw_x = self.x
            draw_y = self.y

        cx = MARGIN_X + draw_x * GRID_SIZE
        cy = MARGIN_Y + draw_y * GRID_SIZE
        pygame.draw.circle(screen, (100, 80, 60), (cx+2, cy+2), GRID_SIZE // 2 - 2)
        pygame.draw.circle(screen, (240, 220, 180), (cx, cy), GRID_SIZE // 2 - 2)
        pygame.draw.circle(screen, self.color, (cx, cy), GRID_SIZE // 2 - 2, 3)
        if self.selected:
            pygame.draw.circle(screen, COLOR_SELECTED, (cx, cy), GRID_SIZE // 2 + 2, 4)
        text = font.render(self.name, True, self.color)
        text_rect = text.get_rect(center=(cx, cy))
        screen.blit(text, text_rect)

# --- 3. 棋盤核心邏輯 ---
class XiangqiBoard:
    LONG_CHECK_COUNT = 3
    LONG_CHASE_COUNT = 3
    REPEAT_POSITION_LIMIT = 3

    def __init__(self, game_mode=MODE_PVP, fen=None):
        self.pieces = []
        self.turn = RED
        self.selected_piece = None
        self.winner = None
        self.game_mode = game_mode  # 遊戲模式（PvP / AI / 殘局）
        
        # 狀態訊息
        self.is_check = False      # 是否正在將軍
        self.warning_msg = ""      # 違規提示訊息 (例如：不能送將)
        self.warning_timer = 0     # 訊息顯示計時器
        
        self.moves = []  # list[Move]
        
        # 長將/長捉檢測
        self.draw_reason = ""  # 和棋原因
        
        # 重複局面檢測：記錄每步後的棋盤狀態及出現次數
        self.board_state_history = {}  # {狀態字符串: 出現次數}
        # 調試開關（臨時）：啟用後會印日誌以協助定位長捉問題
        self.debug = False

        if fen:
            self.load_from_fen(fen)
        else:
            self.init_board()

        # 初始化棋盤狀態計數器
        initial_state = self.get_board_state()
        self.board_state_history[initial_state] = 1

    def init_board(self):
        layout_red = [
            ('車', 0, 9), ('馬', 1, 9), ('相', 2, 9), ('仕', 3, 9), ('帥', 4, 9),
            ('仕', 5, 9), ('相', 6, 9), ('馬', 7, 9), ('車', 8, 9),
            ('炮', 1, 7), ('炮', 7, 7),
            ('兵', 0, 6), ('兵', 2, 6), ('兵', 4, 6), ('兵', 6, 6), ('兵', 8, 6)
        ]
        layout_black = [
            ('車', 0, 0), ('馬', 1, 0), ('象', 2, 0), ('士', 3, 0), ('將', 4, 0),
            ('士', 5, 0), ('象', 6, 0), ('馬', 7, 0), ('車', 8, 0),
            ('包', 1, 2), ('包', 7, 2),
            ('卒', 0, 3), ('卒', 2, 3), ('卒', 4, 3), ('卒', 6, 3), ('卒', 8, 3)
        ]
        for name, x, y in layout_red: self.pieces.append(Piece(name, RED, x, y))
        for name, x, y in layout_black: self.pieces.append(Piece(name, BLACK, x, y))

    def load_from_fen(self, fen):
        """由 FEN 字串重建棋盤（格式需與 to_fen() 相容）。"""
        parts = fen.strip().split()
        if not parts:
            raise ValueError("空的 FEN")
        rows = parts[0].split("/")
        if len(rows) != 10:
            raise ValueError(f"FEN 列數錯誤（需要 10 列，實際 {len(rows)}）")

        self.pieces = []
        for y, row in enumerate(rows):
            x = 0
            for ch in row:
                if ch.isdigit():
                    x += int(ch)
                    continue
                info = FEN_TO_PIECE.get(ch)
                if not info:
                    raise ValueError(f"無法識別的 FEN 棋子字元：{ch}")
                if not (0 <= x <= 8):
                    raise ValueError("FEN 行寬超出棋盤")
                name, color = info
                self.pieces.append(Piece(name, color, x, y))
                x += 1
            if x != 9:
                raise ValueError(f"FEN 第 {y} 列寬度不正確（{x}，應為 9）")

        if len(parts) >= 2 and parts[1] in ("w", "b"):
            self.turn = RED if parts[1] == "w" else BLACK
        else:
            self.turn = RED

        self.selected_piece = None
        self.winner = None
        self.is_check = self.is_under_attack(self.turn)
        self.warning_msg = ""
        self.warning_timer = 0
        self.draw_reason = ""
        self.moves = []
        self.board_state_history = {}

    def get_piece_at(self, x, y):
        for p in self.pieces:
            if p.x == x and p.y == y: return p
        return None

    def get_king(self, color):
        target_name = '帥' if color == RED else '將'
        for p in self.pieces:
            if p.name == target_name: return p
        return None

    @property
    def move_history(self):
        """相容舊呼叫端：(piece, old_x, old_y, captured)。"""
        return [(m.piece, m.old_x, m.old_y, m.captured) for m in self.moves]

    @property
    def move_ucci_history(self):
        return [m.ucci for m in self.moves]

    @property
    def move_notation(self):
        return [m.notation for m in self.moves]

    def _enforces_repetition_penalties(self):
        """對局套用長將／長捉／三次重複／無過河子力和；殘局只認將死。"""
        return self.game_mode != MODE_ENDGAME

    def _recent_plies_by_piece(self, piece, n):
        """該棋子最近 n 步在 self.moves 中的下標（由舊到新）。不足則回傳較短列表。"""
        indices = []
        piece_id = id(piece)
        for i in range(len(self.moves) - 1, -1, -1):
            if self.moves[i].piece_id == piece_id:
                indices.append(i)
                if len(indices) == n:
                    break
        indices.reverse()
        return indices

    def _is_consecutive_own_plies(self, indices, n):
        if len(indices) != n:
            return False
        return all(indices[j] - indices[j - 1] == 2 for j in range(1, n))

    def _apply_long_check_or_chase(self, piece, next_turn):
        """同一子連續出手皆將軍或捉同一組無根子 → 執行方負。"""
        n = self.LONG_CHECK_COUNT
        indices = self._recent_plies_by_piece(piece, n)
        if not self._is_consecutive_own_plies(indices, n):
            return
        recent = [self.moves[i] for i in indices]
        if all(m.is_check for m in recent):
            self.draw_reason = t("msg_long_check", n=n)
            self.winner = next_turn
            if self.debug:
                print(f"[DEBUG] LONG-CHECK by piece id={id(piece)} indices={indices}")
            return
        first_targets = recent[0].chase_targets
        if first_targets and all(m.is_chase and m.chase_targets == first_targets for m in recent):
            self.draw_reason = t("msg_long_chase", n=self.LONG_CHASE_COUNT)
            self.winner = next_turn
            if self.debug:
                print(f"[DEBUG] LONG-CAPTURE by piece id={id(piece)} targets={first_targets}")

    def _apply_post_move_rules(self, mover, next_turn):
        """走子確認後的終局規則。殘局不套用長將／長捉／重複判罰，但仍記錄局面次數。"""
        if self._enforces_repetition_penalties() and not self.draw_reason:
            self._apply_long_check_or_chase(mover, next_turn)
        if self._enforces_repetition_penalties() and not self.draw_reason:
            if not self.has_crossing_piece(RED) and not self.has_crossing_piece(BLACK):
                self.draw_reason = t("msg_no_crossing")
                self.winner = None
        if self._enforces_repetition_penalties() and not self.draw_reason and self.check_repeated_steps_draw():
            self.draw_reason = t("msg_repeat_moves")
            self.winner = None

        repeat_state_key = None
        if not self.draw_reason:
            repeat_count = self.check_repeat_position()
            repeat_state_key = self.get_board_state()
            if self._enforces_repetition_penalties() and repeat_count >= self.REPEAT_POSITION_LIMIT:
                self.draw_reason = t("msg_repeat_pos", n=self.REPEAT_POSITION_LIMIT)
                self.winner = None

        if not self.draw_reason and not self.has_valid_move(next_turn):
            self.winner = mover.color
        return repeat_state_key

    def _displace(self, piece, tx, ty):
        """把棋子移到 (tx, ty) 並移除被吃子。回傳 ((old_x, old_y), captured_or_None)。"""
        orig = (piece.x, piece.y)
        captured = self.get_piece_at(tx, ty)
        if captured is piece:
            captured = None
        piece.x = tx
        piece.y = ty
        if captured:
            self.pieces.remove(captured)
        return orig, captured

    @contextmanager
    def _simulate_move(self, piece, tx, ty):
        """暫時走到 (tx, ty)（含吃子）；離開 with 時一定還原。"""
        orig, captured = self._displace(piece, tx, ty)
        try:
            yield captured
        finally:
            piece.x, piece.y = orig
            if captured:
                self.pieces.append(captured)

    def _is_self_safe(self, color):
        return (not self.is_under_attack(color)) and (not self.is_kings_facing())

    def would_be_legal_move(self, piece, tx, ty):
        """幾何可走到，且走完不送將、不照面。"""
        if not self.is_valid_move(piece, tx, ty):
            return False
        with self._simulate_move(piece, tx, ty):
            return self._is_self_safe(piece.color)

    def legal_moves_ucci(self, color):
        """指定方所有合法著（UCCI 字串）。"""
        moves = []
        for piece in list(self.pieces):
            if piece.color != color:
                continue
            fx, fy = piece.x, piece.y
            for tx in range(9):
                for ty in range(10):
                    if self.would_be_legal_move(piece, tx, ty):
                        moves.append(board_to_ucci(fx, fy) + board_to_ucci(tx, ty))
        return moves

    def _is_square_defended(self, square_x, square_y, by_color):
        """by_color 是否有棋能合法吃到該格。"""
        occupant = self.get_piece_at(square_x, square_y)
        for p in list(self.pieces):
            if p.color != by_color or p is occupant:
                continue
            if self.would_be_legal_move(p, square_x, square_y):
                return True
        return False

    def move_piece(self, piece, target_x, target_y):
        """ 嘗試移動棋子：包含所有規則檢查 """
        original_x, original_y = piece.x, piece.y
        with self._simulate_move(piece, target_x, target_y):
            if self.is_kings_facing():
                self.set_warning(t("msg_kings_facing"))
                return False
            if self.is_under_attack(piece.color):
                self.set_warning(t("msg_self_check"))
                return False

        _, captured_piece = self._displace(piece, target_x, target_y)

        # --- 確認移動有效 ---
        piece.selected = False
        self.selected_piece = None
        self.warning_msg = ""
        
        is_capture = captured_piece is not None
        is_rootless = bool(
            is_capture and not self._is_square_defended(piece.x, piece.y, captured_piece.color)
        )
        if self.debug and is_capture:
            print(f"[DEBUG] capture by {piece.name} id={id(piece)} at ({piece.x},{piece.y}) - is_rootless={is_rootless}")
        
        if captured_piece and captured_piece.name in ('帥', '將'):
            self.winner = piece.color

        next_turn = BLACK if self.turn == RED else RED
        self.turn = next_turn
        is_check = self.is_under_attack(next_turn)
        self.is_check = is_check

        chase_targets = self.get_rootless_threat_targets(piece)
        move = Move(
            piece=piece,
            old_x=original_x,
            old_y=original_y,
            new_x=target_x,
            new_y=target_y,
            captured=captured_piece,
            ucci=board_to_ucci(original_x, original_y) + board_to_ucci(target_x, target_y),
            notation=self.generate_move_notation(piece, original_x, original_y, target_x, target_y),
            is_check=is_check,
            is_capture=is_capture,
            is_rootless_capture=is_rootless,
            piece_id=id(piece),
            is_chase=len(chase_targets) > 0,
            chase_targets=chase_targets,
            signature=self.get_move_signature(piece, original_x, original_y, target_x, target_y),
        )
        self.moves.append(move)
        move.repeat_state_key = self._apply_post_move_rules(piece, next_turn)
        return True

    def is_under_attack(self, color):
        """ 檢查指定顏色的將帥是否正受到攻擊 """
        king = self.get_king(color)
        if not king: return False # 沒王了(已輸)

        # 檢查敵方所有棋子，看有沒有任何一個能吃到王
        enemy_color = BLACK if color == RED else RED
        for p in self.pieces:
            if p.color == enemy_color:
                # 這裡很關鍵：我們檢查敵方棋子 p 能不能移動到 king 的位置
                if self.is_valid_move(p, king.x, king.y):
                    return True
        return False

    def is_kings_facing(self):
        """檢查兩個將帥是否在同一列且中間無棋子（飛將）"""
        red_king = self.get_king(RED)
        black_king = self.get_king(BLACK)
        if not red_king or not black_king: return False
        if red_king.x != black_king.x: return False
        
        min_y, max_y = min(red_king.y, black_king.y), max(red_king.y, black_king.y)
        for y in range(min_y + 1, max_y):
            if self.get_piece_at(red_king.x, y): return False
        return True
    
    def has_crossing_piece(self, color):
        """
        檢查指定顏色是否有能過河的子力
        過河子力：能夠過河的棋子（車、馬、炮/包、兵/卒）
        如果這些棋子都被吃掉了，就沒有過河子力
        """
        for piece in self.pieces:
            if piece.color != color:
                continue
            
            piece_name = piece.name
            
            # 檢查是否有能過河的棋子
            # 紅方：車、馬、炮、兵
            # 黑方：車、馬、包、卒
            if color == RED:
                if piece_name in ('車', '馬', '炮', '兵'):
                    return True
            else:  # BLACK
                if piece_name in ('車', '馬', '包', '卒'):
                    return True
        
        return False
    
    def get_board_state(self):
        """
        生成當前棋盤狀態的字符串表示
        用於檢測局面是否重複
        格式：每個棋子記錄為 "顏色_名稱_x_y"，用 | 分隔
        """
        pieces_str = []
        for piece in sorted(self.pieces, key=lambda p: (p.y, p.x)):  # 按坐標排序確保順序一致
            color_str = "R" if piece.color == RED else "B"
            pieces_str.append(f"{color_str}_{piece.name}_{piece.x}_{piece.y}")
        
        state = "|".join(pieces_str)
        # 加上當前回合信息
        turn_str = "R" if self.turn == RED else "B"
        return state + f"|turn={turn_str}"

    def to_fen(self):
        """轉為象棋 FEN，供 Pikafish 使用。"""
        rows = []
        for y in range(10):
            empty = 0
            row = []
            for x in range(9):
                p = self.get_piece_at(x, y)
                if not p:
                    empty += 1
                    continue
                if empty > 0:
                    row.append(str(empty))
                    empty = 0
                fen_char = PIECE_TO_FEN.get((p.name, p.color))
                if not fen_char:
                    raise ValueError(f"無法轉換為 FEN 的棋子：{p.name}")
                row.append(fen_char)
            if empty > 0:
                row.append(str(empty))
            rows.append("".join(row))
        side = "w" if self.turn == RED else "b"
        return "/".join(rows) + f" {side} - - 0 1"
    
    def check_repeat_position(self):
        """
        記錄並回傳當前局面出現次數。
        對局模式：同一局面（含行棋方）達 3 次可判和（由呼叫端決定）。
        """
        current_state = self.get_board_state()

        if current_state in self.board_state_history:
            self.board_state_history[current_state] += 1
        else:
            self.board_state_history[current_state] = 1

        return self.board_state_history[current_state]
    
    def has_valid_move(self, color):
        """檢查指定顏色的玩家是否還有有效的移動"""
        for piece in list(self.pieces):
            if piece.color != color:
                continue
            for tx in range(9):
                for ty in range(10):
                    if self.would_be_legal_move(piece, tx, ty):
                        return True
        return False

    def set_warning(self, msg):
        self.warning_msg = msg
        self.warning_timer = time.time()
    
    def get_position_notation(self, x, y, color):
        """
        將棋盤坐標轉為象棋記法位置
        紅方：x=0是"九"，x=8是"一"
        黑方：x=0是"一"，x=8是"九"（與紅方對稱）
        """
        col_names_cn = ["九", "八", "七", "六", "五", "四", "三", "二", "一"]
        
        if color == RED:
            # 紅方：正常映射
            col_name = col_names_cn[x]
        else:
            # 黑方：反轉映射（8-x），使坐標對稱
            col_name = col_names_cn[8 - x]
        
        return col_name
    
    def get_direction_notation(self, color, old_x, old_y, new_x, new_y):
        """
        根據移動方向生成記法中的動作詞
        進：向己方陣地移動
        退：向對方陣地移動
        平：側向移動
        """
        if color == RED:
            # 紅方向上移動（y減小）
            if new_y < old_y:
                return "進"
            elif new_y > old_y:
                return "退"
            else:
                return "平"
        else:
            # 黑方向下移動（y增大）
            if new_y > old_y:
                return "進"
            elif new_y < old_y:
                return "退"
            else:
                return "平"
    
    def generate_move_notation(self, piece, old_x, old_y, new_x, new_y):
        """
        生成象棋記法，根據不同棋子類型使用不同規則
        
        規則：
        1. 馬：記原始列→到達列（馬二進三、馬2進4）
        2. 車/炮：
           - 縱向：記所在列+格數（車一進二、炮2退3）
           - 橫向：記原始列→到達列（車一平三、炮2平4）
        3. 兵/卒：
           - 縱向：記所在列+格數（兵三進一）
           - 橫向（過河後）：記原始列→到達列（兵一平二）
        4. 將帥/士/象：記原始列→到達列
        
        紅方：用中文列名和距離
        黑方：用阿拉伯數字列名和距離
        """
        piece_name = piece.name
        color = piece.color
        
        col_names_cn = ["九", "八", "七", "六", "五", "四", "三", "二", "一"]
        num_to_cn = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 
                     6: "六", 7: "七", 8: "八", 9: "九"}
        
        # 獲取列標記
        if color == RED:
            # 紅方：用中文
            old_col = col_names_cn[old_x]
            new_col = col_names_cn[new_x]
        else:
            # 黑方：用數字（對稱對應）
            # x=0(紅方九) -> 1, x=4(紅方五) -> 5, x=8(紅方一) -> 9
            old_col = str(old_x + 1)
            new_col = str(new_x + 1)
        
        # 判斷移動方向
        direction = self.get_direction_notation(color, old_x, old_y, new_x, new_y)
        
        # 根據棋子類型生成記譜
        if piece_name == '馬':
            # 馬：記原始列→到達列
            return f"{piece_name}{old_col}{direction}{new_col}"
        
        elif piece_name in ('車', '炮', '包'):
            # 車/炮：區分縱向和橫向
            if old_x == new_x:
                # 縱向移動：記所在的列 + 格數差
                col = old_col
                if color == RED:
                    move_distance = new_y - old_y  # 正數表示向黑方移動
                else:
                    move_distance = old_y - new_y  # 正數表示向紅方移動
                move_distance = abs(move_distance)
                # 紅方用中文，黑方用數字
                if color == RED:
                    distance_str = num_to_cn.get(move_distance, str(move_distance))
                else:
                    distance_str = str(move_distance)
                return f"{piece_name}{col}{direction}{distance_str}"
            else:
                # 橫向移動：記原始列→到達列
                return f"{piece_name}{old_col}{direction}{new_col}"
        
        elif piece_name in ('兵', '卒'):
            # 兵/卒：區分縱向和橫向
            if old_x == new_x:
                # 縱向移動：記所在的列 + 格數
                col = old_col
                if color == RED:
                    move_distance = new_y - old_y
                else:
                    move_distance = old_y - new_y
                move_distance = abs(move_distance)
                # 紅方用中文，黑方用數字
                if color == RED:
                    distance_str = num_to_cn.get(move_distance, str(move_distance))
                else:
                    distance_str = str(move_distance)
                return f"{piece_name}{col}{direction}{distance_str}"
            else:
                # 橫向移動（過河後）：記原始列→到達列
                return f"{piece_name}{old_col}{direction}{new_col}"
        
        else:
            # 將帥、士、象：區分縱向和橫向
            if old_x == new_x:
                # 縱向移動：記列名 + 方向 + 格數
                col = old_col
                if color == RED:
                    move_distance = new_y - old_y  # 正數表示向黑方移動
                else:
                    move_distance = old_y - new_y  # 正數表示向紅方移動
                move_distance = abs(move_distance)
                # 紅方用中文，黑方用數字
                if color == RED:
                    distance_str = num_to_cn.get(move_distance, str(move_distance))
                else:
                    distance_str = str(move_distance)
                return f"{piece_name}{col}{direction}{distance_str}"
            else:
                # 橫向移動：記原始列→到達列
                return f"{piece_name}{old_col}{direction}{new_col}"

    def get_move_signature(self, piece, old_x, old_y, new_x, new_y):
        """生成可比較的移動簽名：同一棋子同一路徑才視為同一步。"""
        return (id(piece), old_x, old_y, new_x, new_y)

    def check_repeated_steps_draw(self):
        """雙方循環著法判和：最近 6 步形成週期 2 的循環（各重複 3 次著法型態）。

        例如雙方一直 A-B-A-B-A-B，則 recent 滿足 recent[i]==recent[i-2]。
        """
        if len(self.moves) < 6:
            return False
        recent = [m.signature for m in self.moves[-6:]]
        # 週期 2：第 0 與 2、4 相同；第 1 與 3、5 相同
        for i in range(2, 6):
            if recent[i] != recent[i - 2]:
                return False
        # 兩步不能相同（否則是同一方連續走兩步，不應發生）
        if recent[0] == recent[1]:
            return False
        return True

    def get_rootless_threat_targets(self, attacker):
        """找出 attacker 當前可捉（可吃且無根）的敵方棋子集合。"""
        enemy_color = BLACK if attacker.color == RED else RED
        targets = []

        for target in list(self.pieces):
            if target.color != enemy_color or target.name in ('帥', '將'):
                continue
            if not self.would_be_legal_move(attacker, target.x, target.y):
                continue
            with self._simulate_move(attacker, target.x, target.y):
                defended = self._is_square_defended(attacker.x, attacker.y, enemy_color)
            if not defended:
                targets.append(id(target))

        targets.sort()
        return tuple(targets)
    
    def undo_last_move(self):
        """撤銷上一步移動（悔棋）"""
        if not self.moves:
            self.set_warning(t("msg_no_undo"))
            return False
        
        self.winner = None
        self.draw_reason = ""
        
        move = self.moves.pop()
        move.piece.x = move.old_x
        move.piece.y = move.old_y
        if move.captured:
            self.pieces.append(move.captured)
        
        if move.repeat_state_key and move.repeat_state_key in self.board_state_history:
            self.board_state_history[move.repeat_state_key] -= 1
            if self.board_state_history[move.repeat_state_key] <= 0:
                del self.board_state_history[move.repeat_state_key]

        self.turn = BLACK if self.turn == RED else RED
        self.is_check = self.is_under_attack(self.turn)
        self.set_warning(t("msg_undone"))
        return True

    def is_valid_move(self, piece, tx, ty):
        """幾何能否走到 (tx, ty)。不含送將／照面；完整合法性用 would_be_legal_move。"""
        dx, dy = tx - piece.x, ty - piece.y
        adx, ady = abs(dx), abs(dy)

        if not (0 <= tx <= 8 and 0 <= ty <= 9): return False
        target = self.get_piece_at(tx, ty)
        if target and target.color == piece.color: return False

        name = piece.name
        # 1. 帥/將
        if name in ('帥', '將'):
            if not (adx + ady == 1): return False
            if tx < 3 or tx > 5: return False
            if piece.color == RED and ty < 7: return False
            if piece.color == BLACK and ty > 2: return False
            return True
        # 2. 士/仕
        if name in ('仕', '士'):
            if not (adx == 1 and ady == 1): return False
            if tx < 3 or tx > 5: return False
            if piece.color == RED and ty < 7: return False
            if piece.color == BLACK and ty > 2: return False
            return True
        # 3. 相/象
        if name in ('相', '象'):
            if not (adx == 2 and ady == 2): return False
            eye_x, eye_y = piece.x + dx // 2, piece.y + dy // 2
            if self.get_piece_at(eye_x, eye_y): return False
            if piece.color == RED and ty < 5: return False
            if piece.color == BLACK and ty > 4: return False
            return True
        # 4. 馬
        if name == '馬':
            if not ((adx == 1 and ady == 2) or (adx == 2 and ady == 1)): return False
            # 蹩馬腿：腿點在「長邊方向」的相鄰格。
            # 不能直接用 //2，因為 -1 // 2 會得到 -1，造成負方向判定錯誤。
            if adx == 2:
                leg_x = piece.x + (1 if dx > 0 else -1)
                leg_y = piece.y
            else:
                leg_x = piece.x
                leg_y = piece.y + (1 if dy > 0 else -1)
            if self.get_piece_at(leg_x, leg_y): return False
            return True
        # 5. 車
        if name == '車':
            if not (dx == 0 or dy == 0): return False
            if self.count_obstacles(piece.x, piece.y, tx, ty) != 0: return False
            return True
        # 6. 炮/包
        if name in ('炮', '包'):
            if not (dx == 0 or dy == 0): return False
            count = self.count_obstacles(piece.x, piece.y, tx, ty)
            if target: return count == 1
            else: return count == 0
        # 7. 兵/卒
        if name in ('兵', '卒'):
            # 紅方：向上（dy < 0），黑方：向下（dy > 0）
            if piece.color == RED and dy > 0: return False
            if piece.color == BLACK and dy < 0: return False
            
            is_crossed = (piece.y <= 4) if piece.color == RED else (piece.y >= 5)
            
            # 未過河：只能往前，不能斜著
            if not is_crossed:
                if adx != 0: return False
            # 過河後：可以前進、左右，但不能後退
            else:
                # 只能移動1格：前進或左右
                if adx + ady != 1: return False
                # 確保不會後退（紅方不能向下、黑方不能向上）
                if piece.color == RED and dy > 0: return False
                if piece.color == BLACK and dy < 0: return False
            
            if ady > 1: return False
            return True
        return False

    def count_obstacles(self, x1, y1, x2, y2):
        count = 0
        if x1 == x2:
            step = 1 if y2 > y1 else -1
            for y in range(y1 + step, y2, step):
                if self.get_piece_at(x1, y): count += 1
        elif y1 == y2:
            step = 1 if x2 > x1 else -1
            for x in range(x1 + step, x2, step):
                if self.get_piece_at(x, y1): count += 1
        return count

# --- 4. 按鈕類 ---
class Button:
    def __init__(self, x, y, width, height, text, color=BUTTON_COLOR):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.color = color
        self.hover_color = BUTTON_HOVER_COLOR
        self.is_hovered = False
        self.radius = BUTTON_RADIUS
        self.text_color = BUTTON_TEXT
        self.border_color = BUTTON_BORDER
        self.draw_shadow = True

    def draw(self, screen, font):
        color = self.hover_color if self.is_hovered else self.color
        r = getattr(self, "radius", BUTTON_RADIUS)
        ghost = getattr(self, "ghost", False)
        if ghost:
            # 幽靈按鈕：透明底 + 細邊框，不搶主視覺
            if self.is_hovered:
                pygame.draw.rect(screen, COLOR_CARD_ALT, self.rect, border_radius=r)
            border = getattr(self, "border_color", COLOR_CARD_BORDER)
            pygame.draw.rect(screen, border, self.rect, 1, border_radius=r)
            text_c = getattr(self, "text_color", COLOR_TEXT_SECONDARY)
            if self.is_hovered:
                text_c = COLOR_TEXT
            text_surface = font.render(self.text, True, text_c)
            text_rect = text_surface.get_rect(center=self.rect.center)
            screen.blit(text_surface, text_rect)
            return

        if getattr(self, "draw_shadow", True) and not self.is_hovered:
            draw_soft_shadow(screen, self.rect, radius=r, offset=(2, 3), layers=3, alpha=22)
        elif self.is_hovered:
            draw_soft_shadow(screen, self.rect, radius=r, offset=(1, 2), layers=2, alpha=18)
        pygame.draw.rect(screen, color, self.rect, border_radius=r)
        border = getattr(self, "border_color", BUTTON_BORDER)
        pygame.draw.rect(screen, border, self.rect, 1, border_radius=r)
        # 頂緣微高光（極簡質感）
        if self.rect.height > 10 and self.rect.width > 10:
            hi = pygame.Surface((self.rect.width - 4, max(2, self.rect.height // 5)), pygame.SRCALPHA)
            hi.fill((255, 255, 255, 28 if self.is_hovered else 18))
            screen.blit(hi, (self.rect.x + 2, self.rect.y + 2))
        text_c = getattr(self, "text_color", BUTTON_TEXT)
        text_surface = font.render(self.text, True, text_c)
        text_rect = text_surface.get_rect(center=self.rect.center)
        screen.blit(text_surface, text_rect)

    def is_clicked(self, pos):
        return self.rect.collidepoint(pos)

    def update_hover(self, pos):
        self.is_hovered = self.rect.collidepoint(pos)

# --- 4. 滾動條類 ---
class ScrollBar:
    def __init__(self, x, y, width, height, content_height):
        self.rect = pygame.Rect(x, y, width, height)
        self.content_height = content_height
        self.scroll_offset = 0
        self.thumb_height = max(20, int(height * height / content_height))
        self.is_dragging = False

    def get_thumb_rect(self):
        """計算滑塊位置"""
        if self.content_height <= self.rect.height:
            return pygame.Rect(self.rect.x, self.rect.y, self.rect.width, self.thumb_height)

        max_offset = self.content_height - self.rect.height
        scroll_ratio = self.scroll_offset / max_offset if max_offset > 0 else 0
        thumb_y = self.rect.y + scroll_ratio * (self.rect.height - self.thumb_height)
        return pygame.Rect(self.rect.x, thumb_y, self.rect.width, self.thumb_height)

    def draw(self, screen):
        """繪製滾動條（柔和灰調）"""
        pygame.draw.rect(screen, COLOR_CARD_ALT, self.rect, border_radius=6)
        thumb = self.get_thumb_rect()
        pygame.draw.rect(screen, (150, 144, 136), thumb, border_radius=6)
    
    def handle_scroll(self, delta, max_scroll):
        """處理滾輪事件"""
        self.scroll_offset = max(0, min(max_scroll, self.scroll_offset + delta))
    
    def handle_click(self, pos):
        """處理滑塊拖動"""
        if self.get_thumb_rect().collidepoint(pos):
            self.is_dragging = True
    
    def handle_drag(self, pos, max_scroll):
        """處理拖動"""
        if self.is_dragging:
            scroll_ratio = (pos[1] - self.rect.y) / (self.rect.height - self.thumb_height + 1e-6)
            self.scroll_offset = max(0, min(max_scroll, scroll_ratio * max_scroll))
    
    def handle_release(self):
        """釋放拖動"""
        self.is_dragging = False


def apply_ucci_move(board, move_str):
    if not move_str or len(move_str) < 4:
        return False
    src = ucci_to_board(move_str[:2])
    dst = ucci_to_board(move_str[2:4])
    if not src or not dst:
        return False
    piece = board.get_piece_at(src[0], src[1])
    if not piece or piece.color != board.turn:
        return False
    if not board.is_valid_move(piece, dst[0], dst[1]):
        return False
    return board.move_piece(piece, dst[0], dst[1])


def ucci_to_chinese_notation(board, move_str):
    """將單步 UCCI（如 c3c4）轉為中文記譜（如 兵三進一）；失敗則回傳原字串。"""
    if not board or not move_str or len(move_str) < 4:
        return move_str or ""
    src = ucci_to_board(move_str[:2])
    dst = ucci_to_board(move_str[2:4])
    if not src or not dst:
        return move_str
    piece = board.get_piece_at(src[0], src[1])
    if not piece:
        return move_str
    try:
        return board.generate_move_notation(piece, src[0], src[1], dst[0], dst[1])
    except Exception:
        return move_str


def ucci_pv_to_chinese(fen, moves, max_plies=12):
    """
    將引擎 PV（UCCI 序列）轉為中文棋譜字串，例如：
    「炮八平五　馬2進3　兵三進一」
    """
    if not moves:
        return ""
    try:
        b = XiangqiBoard(MODE_PVP, fen=fen) if fen else XiangqiBoard(MODE_PVP)
    except Exception:
        return " ".join(str(m) for m in moves[:max_plies])

    notes = []
    for mv in list(moves)[:max_plies]:
        if not isinstance(mv, str) or len(mv) < 4:
            if mv:
                notes.append(str(mv))
            continue
        note = ucci_to_chinese_notation(b, mv)
        notes.append(note)
        if not apply_ucci_move(b, mv):
            break
    return "　".join(notes)


def wrap_text_by_width(text, font, max_width):
    """依像素寬度折行（中英混排按字元切）。"""
    if not text:
        return []
    if max_width <= 8:
        return [text]
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        if font.size(test)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines

def main():
    pygame.init()
    window = pygame.display.set_mode(get_initial_window_size(), pygame.RESIZABLE)
    render_rect = get_render_rect(window.get_size())
    screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("中國象棋 Ver 3.2 (寫實棋盤棋子 + Pikafish)")
    clock = pygame.time.Clock()
    
    # 內文／按鈕：清晰黑體；大標題：楷體／書法感
    font_names = list(FONT_UI_CANDIDATES)
    font_title_names = list(FONT_TITLE_CANDIDATES)
    font = pygame.font.SysFont(font_names, 30, bold=True)          # 卡片標題
    font_body = pygame.font.SysFont(font_names, 22)                # 內文說明
    font_ui = pygame.font.SysFont(font_names, 38, bold=True)
    font_eval = pygame.font.SysFont(font_names, 48, bold=True)
    font_small = pygame.font.SysFont(font_names, 22)
    font_badge = pygame.font.SysFont(font_names, 18)
    font_warn = pygame.font.SysFont(font_names, 46, bold=True)
    font_banner = pygame.font.SysFont(font_names, 34, bold=True)  # 頂欄紅字提示
    font_menu = pygame.font.SysFont(font_title_names, 60)           # 主標題（書法／楷體）
    font_subtitle = pygame.font.SysFont(font_names, 26)            # 副標（細／灰）
    board_surface, piece_sprites, board_from_asset = load_visual_assets(font_names)
    
    # 遊戲狀態
    game_state = MODE_MENU  # 初始化為菜單狀態
    board = None
    history_scroll = None  # 移動歷史滾動條

    player_color = RED
    ai_color = BLACK
    view_color = RED

    # 殘局闖關
    endgame_levels, endgame_load_error = load_endgames_catalog()
    endgame_progress = load_endgame_progress()
    endgame_cleared = set(endgame_progress.get("cleared", []))
    endgame_current = None  # 目前關卡 dict
    endgame_player_moves = 0
    endgame_status = ""  # "", "cleared", "failed"
    endgame_list_scroll = 0
    endgame_level_buttons = []  # [(Button, level_dict|"locked")] 僅關卡列（不含返回）
    endgame_diff_buttons = []   # [(Button, group_dict)] 難度分組選單
    endgame_filter_group = None  # 目前選中的難度分組 dict（ENDGAME_DIFF_GROUPS 元素）
    endgame_active_section = ENDGAME_SECTION_FORMULA  # formula / challenge
    btn_endgame_menu = None      # 殘局闖關
    btn_formula_menu = None      # 定式訓練
    btn_endgame_back = None
    btn_endgame_hint = None
    btn_endgame_retry = None
    btn_endgame_levels = None
    endgame_list_scrollbar = None

    engine_dispatcher = None
    request_seq = 0

    ai_enabled = True
    ai_wait_until = 0.0
    ai_request_id = None
    ai_request_fen = None
    ai_difficulty_order = ["簡單", "中等", "困難"]
    ai_difficulty = "中等"
    ai_search_depth = AI_DIFFICULTY_PRESETS[ai_difficulty]["depth"]
    ai_movetime_ms = AI_DIFFICULTY_PRESETS[ai_difficulty]["movetime_ms"]
    ai_max_wait_sec = AI_DIFFICULTY_PRESETS[ai_difficulty].get("max_wait_sec")
    ai_mistake_rate = AI_DIFFICULTY_PRESETS[ai_difficulty].get("mistake_rate", 0.0)

    eval_enabled = True
    eval_request_id = None
    eval_last_fen_requested = None
    eval_red_score_cp = 0
    eval_text = "+0"

    suggest_enabled = False
    suggest_request_id = None
    suggest_last_fen_requested = None
    suggest_move = None
    btn_difficulty = None
    save_file_path = get_user_data_path(SAVE_FILE_NAME)
    draw_offer_popup = None  # {"from_color": RED/BLACK}
    btn_draw_accept = None
    btn_draw_reject = None
    replay_mode_active = False
    replay_record_moves = []
    replay_record_notation = []
    replay_finished_winner = None
    replay_finished_draw_reason = ""
    replay_snapshots = []
    replay_index = None  # None = 顯示最新局面；數字 = 顯示第 N 手後局面（0 為初始）
    game_start_fen = None  # 本局起始 FEN（標準開局或載入局面）；復盤／賽後分析必須由此重建

    # --- 棋鐘 ---
    time_control_idx = 0  # TIME_CONTROL_PRESETS 索引
    clock_enabled = False
    clock_red_ms = 0.0
    clock_black_ms = 0.0
    clock_inc_ms = 0
    clock_last_tick = None  # time.time()

    # --- 賽後分析 ---
    analysis_results = []  # list[dict] 與 move index 對齊
    analysis_status = "idle"  # idle | running | done | error
    analysis_progress = 0
    analysis_total = 0
    analysis_error = ""
    analysis_request_id = None
    analysis_queue = []  # 待分析 (ply_index, fen_before, fen_after, move, notation)
    analysis_pending_ply = None
    analysis_phase = None  # "before" | "after"
    analysis_before_cache = None
    btn_analyze = None

    # --- 局面編輯器 ---
    editor_selected = None  # (name, color) | "erase"  # 調色盤選取
    editor_board_pick = None  # 盤上選取待移動的 Piece 實例
    editor_message = ""  # 僅顯示錯誤／重要操作結果
    editor_saved_list = []
    editor_lib_selected = None  # 局面庫選中 id
    editor_lib_scroll = 0
    editor_lib_buttons = []  # [(Button, pos_dict)]
    btn_editor_back = None
    btn_editor_turn = None
    btn_editor_erase = None
    btn_editor_clear = None
    btn_editor_initial = None
    btn_editor_save = None
    btn_editor_load = None
    btn_editor_play_pvp = None
    btn_editor_play_ai = None
    btn_lib_back = None
    btn_lib_to_edit = None
    btn_lib_pvp = None
    btn_lib_ai = None
    btn_lib_rename = None
    btn_lib_delete = None

    def reset_ai_state():
        nonlocal ai_wait_until, ai_request_id, ai_request_fen
        ai_wait_until = 0.0
        ai_request_id = None
        ai_request_fen = None

    def apply_ai_difficulty(level):
        nonlocal ai_difficulty, ai_search_depth, ai_movetime_ms, ai_max_wait_sec, ai_mistake_rate, btn_difficulty
        cfg = AI_DIFFICULTY_PRESETS[level]
        ai_difficulty = level
        ai_search_depth = cfg.get("depth")
        ai_movetime_ms = cfg.get("movetime_ms")
        ai_max_wait_sec = cfg.get("max_wait_sec")
        ai_mistake_rate = cfg.get("mistake_rate", 0.0)
        if btn_difficulty:
            btn_difficulty.text = t("ai_difficulty", level=ai_difficulty_display(ai_difficulty))

    def cycle_ai_difficulty():
        """循環切換 AI 難度；對局中立刻生效（取消進行中的 AI 搜尋）。"""
        idx = ai_difficulty_order.index(ai_difficulty)
        next_level = ai_difficulty_order[(idx + 1) % len(ai_difficulty_order)]
        apply_ai_difficulty(next_level)
        # 若正輪到 AI，以新難度重新搜尋
        if game_state in (MODE_AI, MODE_ENDGAME) and board and ai_enabled and board.turn == ai_color:
            if not board.winner and not board.draw_reason and not endgame_status:
                reset_ai_state()
        if board:
            board.set_warning(t("ai_diff_changed", level=ai_difficulty_display(ai_difficulty)))
        return next_level

    def get_history_panel_rects():
        """棋盤偏左後，右側移動記錄佔滿剩餘寬度。"""
        panel_x = MARGIN_X + BOARD_WIDTH + HISTORY_PANEL_GAP
        panel_y = MARGIN_Y
        panel_width = max(220, SCREEN_WIDTH - panel_x - HISTORY_PANEL_RIGHT)
        # 略高於棋盤，方便顯示多行變例
        panel_height = BOARD_HEIGHT + 24
        clip_rect = pygame.Rect(panel_x + 6, panel_y + 38, panel_width - 28, panel_height - 46)
        return panel_x, panel_y, panel_width, panel_height, clip_rect

    def make_history_scrollbar():
        """建立貼齊移動記錄面板右側的滾動條。"""
        _px, _py, panel_w, panel_h, clip_rect = get_history_panel_rects()
        bar = ScrollBar(clip_rect.right + 2, clip_rect.y, 12, clip_rect.height, max(clip_rect.height + 1, 1000))
        return bar

    def get_display_notation_list():
        if replay_mode_active and replay_record_notation:
            return replay_record_notation
        if board:
            return board.move_notation
        return []

    def get_history_row_heights(font_for_wrap=None):
        """
        計算移動記錄每列像素高度（含展開的變例折行）。
        回傳 (heights:list[int], total:int, pv_lines_map:dict[int,list[str]])
        """
        notation_list = get_display_notation_list()
        panel_x, panel_y, panel_width, panel_height, clip_rect = get_history_panel_rects()
        wrap_font = font_for_wrap or font_badge
        max_pv_w = max(80, clip_rect.width - 8)
        heights = []
        pv_map = {}
        for i, _notation in enumerate(notation_list):
            h = HISTORY_LINE_H
            show_pv = (
                replay_mode_active
                and replay_index == i + 1
                and i < len(analysis_results)
                and analysis_results[i]
                and analysis_results[i].get("pv")
            )
            if show_pv:
                raw = str(analysis_results[i]["pv"])
                full = t("analysis_pv", pv=raw)
                lines = wrap_text_by_width(full, wrap_font, max_pv_w)
                if not lines:
                    lines = [full]
                lines = lines[:6]
                pv_map[i] = lines
                h += 6 + len(lines) * HISTORY_PV_LINE_H
            heights.append(h)
        total = sum(heights) if heights else 0
        return heights, total, pv_map

    def get_history_max_scroll():
        _heights, total, _pv = get_history_row_heights()
        panel_x, panel_y, panel_width, panel_height, clip_rect = get_history_panel_rects()
        return max(0, total - clip_rect.height + 8)

    def get_notation_index_at_pos(pos):
        if not board:
            return None
        panel_x, panel_y, panel_width, panel_height, clip_rect = get_history_panel_rects()
        if not clip_rect.collidepoint(pos):
            return None
        scroll_offset = history_scroll.scroll_offset if history_scroll else 0
        y_in_list = pos[1] - clip_rect.y + scroll_offset
        if y_in_list < 0:
            return None
        heights, _total, _pv = get_history_row_heights()
        acc = 0
        for i, h in enumerate(heights):
            if acc <= y_in_list < acc + h:
                return i
            acc += h
        return None

    def make_board_snapshot():
        if not board:
            return None
        return {
            "pieces": [(p.name, p.color, p.x, p.y) for p in board.pieces],
            "turn": board.turn,
        }

    def reset_replay_history():
        nonlocal replay_snapshots, replay_index, replay_mode_active
        replay_snapshots = []
        replay_index = None
        replay_mode_active = False
        snap = make_board_snapshot()
        if snap:
            replay_snapshots.append(snap)

    def append_replay_snapshot():
        nonlocal replay_index
        snap = make_board_snapshot()
        if snap:
            replay_snapshots.append(snap)
        replay_index = None

    def sync_replay_history_after_undo():
        nonlocal replay_snapshots, replay_index
        if not board:
            replay_snapshots = []
            replay_index = None
            return
        expected = len(board.move_notation) + 1
        if len(replay_snapshots) > expected:
            replay_snapshots = replay_snapshots[:expected]
        elif len(replay_snapshots) < expected:
            # 理論上不應發生，保底重置為當前局面。
            replay_snapshots = [make_board_snapshot()]
        replay_index = None

    def restore_game_to_step(step_idx, source_moves=None):
        nonlocal board, replay_snapshots, replay_index, replay_mode_active
        if not board:
            return False

        all_moves = list(source_moves) if source_moves is not None else list(board.move_ucci_history)
        step_idx = max(0, min(step_idx, len(all_moves)))

        mode = board.game_mode if board.game_mode in (MODE_PVP, MODE_AI, MODE_ENDGAME) else MODE_PVP
        try:
            if game_start_fen:
                rebuilt = XiangqiBoard(mode, fen=game_start_fen)
            else:
                rebuilt = XiangqiBoard(mode)
        except Exception:
            return False

        new_snapshots = [{"pieces": [(p.name, p.color, p.x, p.y) for p in rebuilt.pieces], "turn": rebuilt.turn}]
        for mv in all_moves[:step_idx]:
            if not apply_ucci_move(rebuilt, mv):
                return False
            new_snapshots.append({"pieces": [(p.name, p.color, p.x, p.y) for p in rebuilt.pieces], "turn": rebuilt.turn})

        rebuilt.winner = None
        rebuilt.draw_reason = ""
        rebuilt.warning_msg = ""
        rebuilt.warning_timer = 0
        board = rebuilt
        replay_snapshots = new_snapshots
        replay_index = step_idx
        reset_ai_state()
        reset_eval_state(reset_display=True)
        reset_suggest_state(reset_display=True)
        close_draw_offer_popup()
        return True

    def current_time_control():
        return TIME_CONTROL_PRESETS[time_control_idx % len(TIME_CONTROL_PRESETS)]

    def cycle_time_control():
        nonlocal time_control_idx, btn_clock
        time_control_idx = (time_control_idx + 1) % len(TIME_CONTROL_PRESETS)
        if btn_clock:
            btn_clock.text = t("clock", label=time_control_label(current_time_control()))

    def init_clocks_for_game():
        nonlocal clock_enabled, clock_red_ms, clock_black_ms, clock_inc_ms, clock_last_tick
        preset = current_time_control()
        if preset["base_sec"] <= 0:
            clock_enabled = False
            clock_red_ms = 0
            clock_black_ms = 0
            clock_inc_ms = 0
            clock_last_tick = None
            return
        clock_enabled = True
        clock_red_ms = float(preset["base_sec"] * 1000)
        clock_black_ms = float(preset["base_sec"] * 1000)
        clock_inc_ms = int(preset["inc_sec"] * 1000)
        clock_last_tick = time.time()

    def apply_clock_increment_for_last_mover():
        nonlocal clock_red_ms, clock_black_ms
        if not clock_enabled or not board or clock_inc_ms <= 0:
            return
        # move_piece 後 turn 已切到對手，故剛走完的是「非 turn」方
        mover = BLACK if board.turn == RED else RED
        if mover == RED:
            clock_red_ms += clock_inc_ms
        else:
            clock_black_ms += clock_inc_ms

    def tick_clocks():
        """每幀扣除行棋方用時；超時判負。"""
        nonlocal clock_red_ms, clock_black_ms, clock_last_tick
        if not clock_enabled or not board:
            return
        if board.winner or board.draw_reason or replay_mode_active or endgame_status:
            clock_last_tick = time.time()
            return
        if game_state not in (MODE_PVP, MODE_AI):
            return
        now = time.time()
        if clock_last_tick is None:
            clock_last_tick = now
            return
        dt_ms = (now - clock_last_tick) * 1000.0
        clock_last_tick = now
        if dt_ms <= 0:
            return
        if board.turn == RED:
            clock_red_ms -= dt_ms
            if clock_red_ms <= 0:
                clock_red_ms = 0
                board.winner = BLACK
                board.draw_reason = t("timeout_red")
                board.set_warning(t("timeout_red"))
                capture_finished_record_if_needed()
        else:
            clock_black_ms -= dt_ms
            if clock_black_ms <= 0:
                clock_black_ms = 0
                board.winner = RED
                board.draw_reason = t("timeout_black")
                board.set_warning(t("timeout_black"))
                capture_finished_record_if_needed()

    def reset_analysis_state():
        nonlocal analysis_results, analysis_status, analysis_progress, analysis_total
        nonlocal analysis_error, analysis_request_id, analysis_queue
        nonlocal analysis_pending_ply, analysis_phase, analysis_before_cache
        analysis_results = []
        analysis_status = "idle"
        analysis_progress = 0
        analysis_total = 0
        analysis_error = ""
        analysis_request_id = None
        analysis_queue = []
        analysis_pending_ply = None
        analysis_phase = None
        analysis_before_cache = None

    def build_analysis_queue_from_record():
        """由完整棋譜重建每步前後 FEN（支援自訂起始局面）。"""
        moves = list(replay_record_moves) if replay_record_moves else (list(board.move_ucci_history) if board else [])
        notations = list(replay_record_notation) if replay_record_notation else (list(board.move_notation) if board else [])
        if not moves:
            return []
        mode = MODE_PVP
        if board and board.game_mode in (MODE_PVP, MODE_AI, MODE_ENDGAME):
            mode = board.game_mode
        try:
            if game_start_fen:
                b = XiangqiBoard(mode, fen=game_start_fen)
            else:
                b = XiangqiBoard(mode)
        except Exception:
            return []
        queue_items = []
        for i, mv in enumerate(moves):
            fen_before = b.to_fen()
            if not apply_ucci_move(b, mv):
                break
            fen_after = b.to_fen()
            note = notations[i] if i < len(notations) else mv
            queue_items.append({
                "ply": i,
                "move": mv,
                "notation": note,
                "fen_before": fen_before,
                "fen_after": fen_after,
            })
        return queue_items

    def start_postgame_analysis():
        nonlocal analysis_status, analysis_queue, analysis_results, analysis_progress
        nonlocal analysis_total, analysis_error, analysis_request_id
        nonlocal analysis_pending_ply, analysis_phase, analysis_before_cache
        capture_finished_record_if_needed()
        items = build_analysis_queue_from_record()
        if not items:
            if board:
                board.set_warning(t("analyze_need_game"))
            return False
        if not ensure_engine():
            if board:
                board.set_warning(t("analyze_fail", err="engine"))
            return False
        analysis_queue = items
        analysis_results = [None] * len(items)
        analysis_progress = 0
        analysis_total = len(items)
        analysis_status = "running"
        analysis_error = ""
        analysis_request_id = None
        analysis_pending_ply = None
        analysis_phase = None
        analysis_before_cache = None
        if board:
            board.set_warning(t("analyzing", cur=0, total=analysis_total))
        _submit_next_analysis_task()
        return True

    def _submit_next_analysis_task():
        nonlocal analysis_request_id, analysis_pending_ply, analysis_phase, analysis_status
        if analysis_status != "running" or not analysis_queue:
            return
        # 找下一個未完成的 ply
        next_item = None
        for item in analysis_queue:
            if analysis_results[item["ply"]] is None:
                next_item = item
                break
        if next_item is None:
            analysis_status = "done"
            analysis_request_id = None
            if board:
                board.set_warning(t("analyze_done"))
            return
        if not ensure_engine():
            analysis_status = "error"
            analysis_error = "engine"
            return
        analysis_pending_ply = next_item["ply"]
        analysis_phase = "before"
        analysis_request_id = new_request_id()
        engine_dispatcher.submit(
            analysis_request_id,
            "analyse_full",
            next_item["fen_before"],
            ANALYSIS_MOVETIME_MS,
        )

    def handle_analysis_result(payload):
        """處理一步分析（before → after → 彙總）。"""
        nonlocal analysis_before_cache, analysis_phase, analysis_request_id
        nonlocal analysis_progress, analysis_status, analysis_results
        if analysis_pending_ply is None or analysis_pending_ply >= len(analysis_queue):
            return
        item = analysis_queue[analysis_pending_ply]
        if analysis_phase == "before":
            analysis_before_cache = payload
            analysis_phase = "after"
            analysis_request_id = new_request_id()
            engine_dispatcher.submit(
                analysis_request_id,
                "analyse_full",
                item["fen_after"],
                ANALYSIS_MOVETIME_MS,
            )
            return

        # phase after
        before = analysis_before_cache or {}
        after = payload or {}
        before_cp = score_to_cp(before.get("score_type", "cp"), before.get("score_value", 0))
        after_cp_stm = score_to_cp(after.get("score_type", "cp"), after.get("score_value", 0))
        # 走子後輪到對手，對手分數取反即原行棋方分數
        after_cp_for_mover = -after_cp_stm
        cp_loss = max(0, before_cp - after_cp_for_mover)
        # 若最佳著與實際著相同，視為無損失
        best_mv = before.get("bestmove")
        if best_mv and best_mv == item["move"]:
            cp_loss = 0
        label = classify_move_quality(cp_loss)
        pv = before.get("pv") or []
        # 引擎 PV 為 UCCI；轉中文棋譜供人類閱讀
        fen_for_pv = item.get("fen_before") or ""
        if pv:
            pv_str = ucci_pv_to_chinese(fen_for_pv, pv, max_plies=12)
        elif best_mv:
            pv_str = ucci_pv_to_chinese(fen_for_pv, [best_mv], max_plies=1)
        else:
            pv_str = ""
        best_cn = ""
        if best_mv:
            best_cn = ucci_pv_to_chinese(fen_for_pv, [best_mv], max_plies=1) or best_mv
        analysis_results[item["ply"]] = {
            "ply": item["ply"],
            "move": item["move"],
            "notation": item["notation"],
            "label": label,
            "cp_loss": int(cp_loss),
            "before_cp": int(before_cp),
            "after_cp": int(after_cp_for_mover),
            "bestmove": best_mv or "",
            "bestmove_cn": best_cn,
            "pv": pv_str,
            "score_before": (before.get("score_type"), before.get("score_value")),
            "score_after": (after.get("score_type"), after.get("score_value")),
        }
        analysis_progress = sum(1 for r in analysis_results if r is not None)
        analysis_before_cache = None
        analysis_phase = None
        analysis_request_id = None
        if board:
            board.set_warning(t("analyzing", cur=analysis_progress, total=analysis_total))
        _submit_next_analysis_task()

    def analysis_label_text(label_key):
        return {
            "best": t("label_best"),
            "good": t("label_good"),
            "mistake": t("label_mistake"),
            "blunder": t("label_blunder"),
        }.get(label_key, t("label_unknown"))

    def analysis_label_color(label_key):
        return {
            "best": SUCCESS_COLOR,
            "good": (88, 118, 150),
            "mistake": (176, 128, 64),
            "blunder": WARNING_COLOR,
        }.get(label_key, COLOR_TEXT_SECONDARY)

    def on_move_applied():
        reset_eval_state()
        reset_suggest_state()
        append_replay_snapshot()
        # 棋鐘：剛走完的一方加秒
        apply_clock_increment_for_last_mover()
        # 新著法使舊分析失效
        if analysis_status == "done":
            reset_analysis_state()

    def capture_finished_record_if_needed():
        nonlocal replay_record_moves, replay_record_notation
        nonlocal replay_finished_winner, replay_finished_draw_reason
        if not board:
            return
        if not (board.winner or board.draw_reason):
            return
        if replay_record_moves:
            return
        replay_record_moves = list(board.move_ucci_history)
        replay_record_notation = list(board.move_notation)
        replay_finished_winner = board.winner
        replay_finished_draw_reason = board.draw_reason

    def enter_replay_mode(step_idx=None):
        nonlocal replay_mode_active, ai_enabled, btn_replay_mode
        if not board:
            return False
        capture_finished_record_if_needed()
        if not replay_record_notation and not replay_record_moves:
            board.set_warning(t("msg_replay_empty"))
            return False

        if step_idx is None:
            step_idx = len(replay_record_moves)
        if not restore_game_to_step(step_idx, source_moves=replay_record_moves):
            board.set_warning(t("msg_replay_enter_fail"))
            return False

        replay_mode_active = True
        ai_enabled = False
        if btn_replay_mode:
            btn_replay_mode.text = t("msg_replay_on")
        board.set_warning(t("msg_replay_enter", n=step_idx))
        return True

    def color_to_str(color):
        return "red" if color == RED else "black"

    def str_to_color(token, default):
        if token == "red":
            return RED
        if token == "black":
            return BLACK
        return default

    def layout_bottom_bar(button_specs, y=None, height=None, gap=None, margin_x=None):
        """將底部按鈕等距排列。button_specs: [(Button|None, width), ...]。"""
        y = BOTTOM_BTN_Y if y is None else y
        height = BOTTOM_BTN_H if height is None else height
        gap = BOTTOM_BTN_GAP if gap is None else gap
        margin_x = BOTTOM_BTN_MARGIN_X if margin_x is None else margin_x
        active = [(b, int(w)) for b, w in button_specs if b is not None and w > 0]
        if not active:
            return
        widths = [w for _, w in active]
        total = sum(widths) + gap * (len(active) - 1)
        avail = SCREEN_WIDTH - 2 * margin_x
        if total > avail and len(active) > 1:
            # 過寬時略縮間距，仍保持等距
            gap = max(8, (avail - sum(widths)) // (len(active) - 1))
            total = sum(widths) + gap * (len(active) - 1)
        x = max(margin_x, (SCREEN_WIDTH - total) // 2)
        for btn, w in active:
            btn.rect = pygame.Rect(x, y, w, height)
            btn.text_color = BUTTON_TEXT
            btn.border_color = BUTTON_BORDER
            x += w + gap

    def setup_in_game_buttons(for_endgame=False):
        nonlocal btn_undo, btn_main_menu, btn_suggest_toggle
        nonlocal btn_save_game, btn_load_game, btn_draw_offer, btn_replay_mode
        nonlocal btn_endgame_hint, btn_endgame_retry, btn_endgame_levels, btn_analyze
        nonlocal btn_difficulty
        # 先建立實例，再由 layout_bottom_bar 統一等距排版
        btn_undo = Button(0, 0, 140, BOTTOM_BTN_H, t("undo"))
        btn_main_menu = Button(0, 0, 160, BOTTOM_BTN_H, t("main_menu"))
        suggest_label = t("suggest_on") if suggest_enabled else t("suggest_off")
        btn_suggest_toggle = Button(0, 0, 200, BOTTOM_BTN_H, suggest_label)
        if for_endgame:
            btn_save_game = None
            btn_load_game = None
            btn_draw_offer = None
            btn_replay_mode = None
            btn_analyze = None
            btn_difficulty = None
            btn_suggest_toggle = None  # 殘局不顯示建議
            btn_endgame_hint = None
            btn_endgame_retry = Button(0, 0, 120, BOTTOM_BTN_H, t("retry"))
            btn_endgame_levels = Button(0, 0, 160, BOTTOM_BTN_H, t("level_list"))
            layout_bottom_bar([
                (btn_endgame_retry, 120),
                (btn_undo, 140),
                (btn_main_menu, 160),
                (btn_endgame_levels, 160),
            ])
        else:
            btn_save_game = Button(0, 0, 110, BOTTOM_BTN_H, t("save"))
            btn_load_game = Button(0, 0, 110, BOTTOM_BTN_H, t("load"))
            btn_draw_offer = Button(915, 12, 170, 32, t("draw_offer"))
            btn_replay_mode = Button(915, 50, 170, 32, t("replay"))
            btn_analyze = Button(915, 88, 170, 32, t("analyze"))
            # AI 難度改在對局內切換（雙人模式不顯示）
            if game_state == MODE_AI:
                btn_difficulty = Button(
                    915, 126, 170, 32,
                    t("ai_difficulty", level=ai_difficulty_display(ai_difficulty)),
                )
            else:
                btn_difficulty = None
            btn_endgame_hint = None
            btn_endgame_retry = None
            btn_endgame_levels = None
            # 底部五鍵：等間距、水平置中
            layout_bottom_bar([
                (btn_save_game, 110),
                (btn_load_game, 110),
                (btn_suggest_toggle, 200),
                (btn_undo, 140),
                (btn_main_menu, 160),
            ])

    def endgame_levels_in_section(section=None):
        """目前區塊（定式訓練／殘局闖關）內的關卡。"""
        sec = section if section is not None else endgame_active_section
        return [lv for lv in endgame_levels if lv.get("section", ENDGAME_SECTION_FORMULA) == sec]

    def endgame_levels_for_group(group=None):
        """依「目前區塊 + 難度分組」篩選關卡；group=None 時回傳該區塊全部。

        group 為 ENDGAME_DIFF_GROUPS 的元素（含 difficulties 元組）。
        """
        base = endgame_levels_in_section()
        if group is None:
            return list(base)
        allowed = set(int(d) for d in group.get("difficulties", ()))
        return [lv for lv in base if int(lv.get("difficulty") or 1) in allowed]

    def endgame_available_groups():
        """回傳目前區塊內有關卡的難度分組列表。"""
        present = {int(lv.get("difficulty") or 1) for lv in endgame_levels_in_section()}
        groups = []
        for g in ENDGAME_DIFF_GROUPS:
            if any(int(d) in present for d in g["difficulties"]):
                groups.append(g)
        return groups

    def endgame_list_viewport_height():
        return max(80, ENDGAME_LIST_BOTTOM - ENDGAME_LIST_TOP)

    def endgame_list_content_height():
        n = len(endgame_levels_for_group(endgame_filter_group))
        return max(endgame_list_viewport_height(), n * ENDGAME_ROW_H)

    def endgame_list_max_scroll():
        return max(0, endgame_list_content_height() - endgame_list_viewport_height())

    def rebuild_endgame_list_scrollbar():
        nonlocal endgame_list_scrollbar
        list_h = endgame_list_viewport_height()
        content_h = endgame_list_content_height()
        bar_x = ENDGAME_LIST_LEFT + ENDGAME_LIST_WIDTH + 8
        endgame_list_scrollbar = ScrollBar(
            bar_x, ENDGAME_LIST_TOP, ENDGAME_SCROLLBAR_W, list_h, max(list_h + 1, content_h)
        )
        endgame_list_scrollbar.scroll_offset = min(endgame_list_scroll, endgame_list_max_scroll())
        endgame_list_scrollbar.content_height = content_h

    def build_endgame_diff_buttons():
        """建立難度分組選擇按鈕（入門／初級合併）。"""
        nonlocal endgame_diff_buttons, btn_endgame_back
        btn_endgame_back = Button(
            SCREEN_WIDTH // 2 - 150, ENDGAME_BACK_Y, 300, 48, t("back_menu")
        )
        endgame_diff_buttons = []
        groups = endgame_available_groups()
        if not groups:
            return
        btn_h = 56
        gap = 14
        start_y = ENDGAME_LIST_TOP
        for i, group in enumerate(groups):
            levels_g = endgame_levels_for_group(group)
            cleared_n = sum(1 for lv in levels_g if lv["id"] in endgame_cleared)
            label = t(
                "group_progress",
                label=diff_group_label(group),
                cleared=cleared_n,
                total=len(levels_g),
            )
            y = start_y + i * (btn_h + gap)
            btn = Button(ENDGAME_LIST_LEFT, y, ENDGAME_LIST_WIDTH, btn_h, label)
            endgame_diff_buttons.append((btn, group))

    def build_endgame_level_buttons():
        """建立「目前難度分組」下的關卡列按鈕（位置隨 scroll 更新）。"""
        nonlocal endgame_level_buttons, btn_endgame_back, endgame_list_scroll
        endgame_list_scroll = max(0, min(endgame_list_scroll, endgame_list_max_scroll()))
        back_label = t("back_diff") if endgame_filter_group is not None else t("back_menu")
        btn_endgame_back = Button(
            SCREEN_WIDTH // 2 - 150, ENDGAME_BACK_Y, 300, 48, back_label
        )
        endgame_level_buttons = []
        filtered = endgame_levels_for_group(endgame_filter_group)
        # 同組內：先按 difficulty 再按 id，入門排在初級前
        filtered = sorted(
            filtered,
            key=lambda lv: (int(lv.get("difficulty") or 1), str(lv.get("id") or "")),
        )
        for i, level in enumerate(filtered):
            unlocked = is_endgame_unlocked(level, endgame_cleared)
            cleared = level["id"] in endgame_cleared
            mark = t("cleared_tag") if cleared else (t("locked_tag") if not unlocked else f"{i+1:02d}")
            sub = difficulty_label(int(level.get("difficulty") or 1))
            label = f"{mark}  {level['title']}  [{sub}]"
            if len(label) > 34:
                label = label[:33] + "…"
            y = ENDGAME_LIST_TOP + i * ENDGAME_ROW_H - endgame_list_scroll
            btn = Button(ENDGAME_LIST_LEFT, y, ENDGAME_LIST_WIDTH, ENDGAME_ROW_H - 8, label)
            endgame_level_buttons.append((btn, level if unlocked else "locked"))
        if endgame_list_scrollbar:
            endgame_list_scrollbar.scroll_offset = endgame_list_scroll
            endgame_list_scrollbar.content_height = endgame_list_content_height()

    def open_endgame_diff_select(section=None):
        """進入殘局／定式：先選難度分組。"""
        nonlocal game_state, endgame_list_scroll, endgame_current, endgame_status
        nonlocal board, endgame_filter_group, endgame_level_buttons, endgame_list_scrollbar
        nonlocal endgame_active_section
        stop_engine()
        reset_ai_state()
        reset_eval_state(reset_display=True)
        reset_suggest_state(reset_display=True)
        board = None
        endgame_current = None
        endgame_status = ""
        endgame_list_scroll = 0
        endgame_filter_group = None
        endgame_level_buttons = []
        endgame_list_scrollbar = None
        if section is not None:
            endgame_active_section = section
        game_state = MODE_ENDGAME_DIFF
        build_endgame_diff_buttons()

    def open_endgame_level_select(group):
        """進入指定難度分組的關卡列表。"""
        nonlocal game_state, endgame_list_scroll, endgame_filter_group
        endgame_filter_group = group
        endgame_list_scroll = 0
        game_state = MODE_ENDGAME_LEVELS
        rebuild_endgame_list_scrollbar()
        build_endgame_level_buttons()

    def mark_endgame_cleared(level_id):
        nonlocal endgame_progress, endgame_cleared
        if level_id not in endgame_cleared:
            endgame_cleared.add(level_id)
            endgame_progress = {"cleared": sorted(endgame_cleared)}
            ok, err = save_endgame_progress(endgame_progress)
            if not ok and board:
                board.set_warning(t("msg_progress_fail", err=err))

    def check_endgame_result():
        """檢查殘局是否過關／失敗。

        過關只認「將死／困斃對手」（board.winner == 玩家），
        不是開局就把對方將吃掉。
        """
        nonlocal endgame_status, endgame_player_moves
        if not board or not endgame_current or endgame_status:
            return
        goal = endgame_current.get("goal") or "checkmate"
        # 先處理「有和棋／違規原因」的情形（長將、長捉、重複局面等），避免誤顯示成「被將死」
        if board.draw_reason:
            if board.winner == player_color:
                # 極少見：有原因字串但玩家仍勝
                endgame_status = "cleared"
                mark_endgame_cleared(endgame_current["id"])
                board.set_warning(t("msg_endgame_pass"))
            else:
                endgame_status = "failed"
                board.set_warning(t("msg_endgame_fail_reason", reason=board.draw_reason))
            return
        if goal == "checkmate" and board.winner == player_color:
            endgame_status = "cleared"
            mark_endgame_cleared(endgame_current["id"])
            board.set_warning(t("msg_endgame_mate_pass"))
            return
        if board.winner and board.winner != player_color:
            endgame_status = "failed"
            board.set_warning(t("msg_endgame_fail_mated"))
            return
        max_moves = endgame_current.get("max_player_moves")
        if max_moves is not None:
            try:
                max_moves = int(max_moves)
            except (TypeError, ValueError):
                max_moves = None
        # 已達步數上限仍未將死 → 失敗（若本步已將死，上方已判定過關）
        if max_moves is not None and endgame_player_moves >= max_moves:
            endgame_status = "failed"
            board.set_warning(t("msg_endgame_fail_limit", n=max_moves))

    def start_session(
        mode,
        fen=None,
        human_side=RED,
        *,
        clocks=None,
        validate=None,
        warning=None,
        view=None,
        opponent=None,
        endgame_level=None,
    ):
        """開一局：標準開局、自訂 FEN、殘局、或讀檔前的起始局面。成功回傳 True。

        validate: None（不額外審核）、"editor"、"endgame"
        clocks: None 時殘局關閉棋鐘、其餘開啟
        """
        nonlocal game_state, board, history_scroll
        nonlocal ai_enabled, eval_enabled, suggest_enabled
        nonlocal player_color, ai_color, view_color
        nonlocal draw_offer_popup, btn_draw_accept, btn_draw_reject
        nonlocal replay_snapshots, replay_index, replay_mode_active
        nonlocal replay_record_moves, replay_record_notation
        nonlocal replay_finished_winner, replay_finished_draw_reason
        nonlocal endgame_current, endgame_status, endgame_player_moves
        nonlocal clock_enabled, clock_last_tick
        nonlocal game_start_fen

        for_endgame = mode == MODE_ENDGAME or endgame_level is not None
        if clocks is None:
            clocks = not for_endgame

        stop_engine()
        reset_ai_state()
        reset_eval_state(reset_display=True)
        reset_suggest_state(reset_display=True)
        reset_analysis_state()

        def _fail_endgame_load(msg):
            nonlocal game_state, board
            print(msg)
            board = None
            game_state = MODE_ENDGAME_LEVELS
            rebuild_endgame_list_scrollbar()
            build_endgame_level_buttons()

        try:
            new_board = XiangqiBoard(mode, fen=fen)
        except Exception as ex:
            if for_endgame:
                level_id = (endgame_level or {}).get("id")
                _fail_endgame_load(f"[endgame] 載入失敗 {level_id}: {ex}")
                return False
            if board:
                board.set_warning(t("msg_fen_fail", err=ex))
            return False

        if validate == "editor":
            ok, reason = validate_editor_position(new_board)
            if not ok:
                board = new_board
                board.set_warning(t("editor_invalid", reason=reason))
                return False
        elif validate == "endgame" or for_endgame:
            ok, reason = validate_endgame_start_position(new_board)
            if not ok:
                level_id = (endgame_level or {}).get("id")
                _fail_endgame_load(f"[endgame] 非法開局 {level_id}: {reason}")
                return False

        board = new_board
        game_start_fen = board.to_fen()
        game_state = mode
        eval_enabled = True
        suggest_enabled = False

        if mode == MODE_PVP:
            ai_enabled = False
            player_color = RED
            ai_color = BLACK
            view_color = RED if view is None else view
        else:
            ai_enabled = True
            player_color = human_side
            if opponent is not None and opponent != human_side:
                ai_color = opponent
            else:
                ai_color = BLACK if human_side == RED else RED
            view_color = human_side if view is None else view
            if mode == MODE_AI:
                apply_ai_difficulty(ai_difficulty)

        if for_endgame and endgame_level is not None:
            endgame_current = endgame_level
            endgame_player_moves = 0
            endgame_status = ""
        elif not for_endgame:
            endgame_current = None
            endgame_status = ""
            endgame_player_moves = 0

        history_scroll = make_history_scrollbar()
        setup_in_game_buttons(for_endgame=for_endgame)
        reset_replay_history()
        replay_record_moves = []
        replay_record_notation = []
        replay_finished_winner = None
        replay_finished_draw_reason = ""
        replay_index = None
        replay_mode_active = False
        draw_offer_popup = None
        btn_draw_accept = None
        btn_draw_reject = None

        if clocks:
            init_clocks_for_game()
        else:
            clock_enabled = False
            clock_last_tick = None

        if warning:
            board.set_warning(warning)
        return True

    def start_endgame_level(level):
        human = RED if level.get("player_side") != "black" else BLACK
        return start_session(
            MODE_ENDGAME,
            fen=level["fen"],
            human_side=human,
            clocks=False,
            validate="endgame",
            warning=t("msg_endgame_start", title=level["title"]),
            endgame_level=level,
        )

    def open_editor():
        """進入局面編輯器。"""
        nonlocal game_state, board, editor_selected, editor_message, editor_saved_list
        nonlocal editor_board_pick
        stop_engine()
        reset_ai_state()
        reset_eval_state(reset_display=True)
        reset_suggest_state(reset_display=True)
        board = create_empty_xiangqi_board(RED)
        # 預設放好將帥（錯開中線，避免開局照面）
        board.pieces.append(Piece("帥", RED, 5, 9))
        board.pieces.append(Piece("將", BLACK, 4, 0))
        editor_selected = ("兵", RED)
        editor_board_pick = None
        editor_message = ""  # 正常操作不刷訊息
        editor_saved_list = load_custom_positions()
        game_state = MODE_EDITOR
        build_editor_buttons()

    def build_editor_buttons():
        nonlocal btn_editor_back, btn_editor_turn, btn_editor_erase
        nonlocal btn_editor_clear, btn_editor_initial, btn_editor_save
        nonlocal btn_editor_load, btn_editor_play_pvp, btn_editor_play_ai
        panel_x = MARGIN_X + BOARD_WIDTH + 24
        y = MARGIN_Y
        w = SCREEN_WIDTH - panel_x - 20
        btn_editor_back = Button(panel_x, y, w, 40, t("editor_back"))
        y += 50
        turn_label = t("editor_turn_red") if board and board.turn == RED else t("editor_turn_black")
        btn_editor_turn = Button(panel_x, y, w, 40, turn_label)
        y += 50
        btn_editor_erase = Button(panel_x, y, w, 36, t("editor_erase"))
        y += 44
        btn_editor_clear = Button(panel_x, y, w // 2 - 4, 36, t("editor_clear"))
        btn_editor_initial = Button(panel_x + w // 2 + 4, y, w // 2 - 4, 36, t("editor_initial"))
        y += 48
        btn_editor_save = Button(panel_x, y, w // 2 - 4, 36, t("editor_save"))
        btn_editor_load = Button(panel_x + w // 2 + 4, y, w // 2 - 4, 36, t("editor_load"))
        # 從此開局改由「載入局面」庫頁操作，編輯器內不再放開局按鈕
        btn_editor_play_pvp = None
        btn_editor_play_ai = None

    def open_editor_library():
        """獨立頁：瀏覽／選取已存局面。"""
        nonlocal game_state, editor_saved_list, editor_lib_selected, editor_lib_scroll, editor_message
        editor_saved_list = load_custom_positions()
        editor_lib_selected = None
        editor_lib_scroll = 0
        editor_message = ""
        game_state = MODE_EDITOR_LIB
        build_editor_lib_ui()

    def build_editor_lib_ui():
        nonlocal btn_lib_back, btn_lib_to_edit, btn_lib_pvp, btn_lib_ai
        nonlocal btn_lib_rename, btn_lib_delete, editor_lib_buttons, editor_lib_scroll
        editor_saved_list = load_custom_positions()
        btn_lib_back = Button(SCREEN_WIDTH // 2 - 150, ENDGAME_BACK_Y, 300, 44, t("editor_back_edit"))
        # 底部操作列
        bw, bh = 160, 40
        by = SCREEN_HEIGHT - 70
        gap = 12
        total = 5 * bw + 4 * gap
        bx = (SCREEN_WIDTH - total) // 2
        btn_lib_to_edit = Button(bx, by, bw, bh, t("editor_lib_to_edit"))
        btn_lib_pvp = Button(bx + (bw + gap), by, bw, bh, t("editor_lib_pvp"))
        btn_lib_ai = Button(bx + 2 * (bw + gap), by, bw, bh, t("editor_lib_ai"))
        btn_lib_rename = Button(bx + 3 * (bw + gap), by, bw, bh, t("editor_lib_rename"))
        btn_lib_delete = Button(bx + 4 * (bw + gap), by, bw, bh, t("editor_lib_delete"))

        list_top = ENDGAME_LIST_TOP
        list_left = ENDGAME_LIST_LEFT
        row_h = ENDGAME_ROW_H
        max_vis = max(1, (ENDGAME_LIST_BOTTOM - list_top) // row_h)
        max_scroll = max(0, len(editor_saved_list) - max_vis)
        editor_lib_scroll = max(0, min(editor_lib_scroll, max_scroll))
        editor_lib_buttons = []
        for i, pos in enumerate(editor_saved_list):
            y = list_top + (i - editor_lib_scroll) * row_h
            if y + row_h < list_top or y > ENDGAME_LIST_BOTTOM:
                continue
            label = pos.get("title") or pos.get("id")
            if len(label) > 28:
                label = label[:27] + "…"
            btn = Button(list_left, y, ENDGAME_LIST_WIDTH, row_h - 8, label)
            editor_lib_buttons.append((btn, pos))

    def editor_lib_get_selected():
        if not editor_lib_selected:
            return None
        for p in editor_saved_list:
            if p.get("id") == editor_lib_selected:
                return p
        return None

    def editor_palette_rects():
        """回傳 [(rect, (name,color)|'erase'), ...]。"""
        items = []
        start_x = MARGIN_X
        y = MARGIN_Y + BOARD_HEIGHT + 16
        size = 44
        gap = 6
        x = start_x
        for name, color in EDITOR_PALETTE_RED:
            items.append((pygame.Rect(x, y, size, size), (name, color)))
            x += size + gap
        x = start_x
        y2 = y + size + gap
        for name, color in EDITOR_PALETTE_BLACK:
            items.append((pygame.Rect(x, y2, size, size), (name, color)))
            x += size + gap
        return items

    def editor_place_piece(gx, gy, name, color):
        """在 (gx,gy) 放置棋子：檢查合法格與兵種數量上限。成功不寫 log。"""
        nonlocal editor_message, editor_board_pick
        if not board or not (0 <= gx <= 8 and 0 <= gy <= 9):
            return
        ok_sq, reason_sq = is_legal_piece_square(name, color, gx, gy)
        if not ok_sq:
            editor_message = t("editor_bad_square", name=name)
            return

        temp = []
        for p in board.pieces:
            if p.x == gx and p.y == gy:
                continue
            if name in ("帥", "將") and p.name == name:
                continue
            temp.append(p)
        same_count = sum(1 for p in temp if p.color == color and p.name == name)
        limit = PIECE_MAX_COUNT.get(name, 0)
        if same_count + 1 > limit:
            side = "紅" if color == RED else "黑"
            editor_message = t("editor_too_many", side=side, name=name, limit=limit)
            return

        board.pieces = temp
        board.pieces.append(Piece(name, color, gx, gy))
        board.selected_piece = None
        board.winner = None
        board.draw_reason = ""
        editor_board_pick = None
        editor_message = ""  # 合法放置不顯示訊息

    def editor_erase_at(gx, gy):
        nonlocal editor_message, editor_board_pick
        if not board:
            return
        # 若刪的是正在選取的棋，一併清除選取
        if editor_board_pick and editor_board_pick.x == gx and editor_board_pick.y == gy:
            editor_board_pick = None
        board.pieces = [p for p in board.pieces if not (p.x == gx and p.y == gy)]
        board.selected_piece = None
        editor_message = ""

    def editor_pick_board_piece(piece):
        """點選盤上棋子，準備移動／取代。"""
        nonlocal editor_board_pick, editor_selected, editor_message
        if not piece:
            return
        editor_board_pick = piece
        editor_selected = None  # 退出調色盤放置／橡皮擦模式
        editor_message = t("editor_pick_hint")

    def editor_move_picked_to(gx, gy):
        """
        將 editor_board_pick 移到 (gx,gy)。
        - 空格：移動
        - 有他子：取代（他子刪除）
        - 點自己：取消選取
        """
        nonlocal editor_board_pick, editor_message
        if not board or not editor_board_pick:
            return
        piece = editor_board_pick
        # 棋子可能已被清空；確認仍在盤上
        if piece not in board.pieces:
            editor_board_pick = None
            editor_message = ""
            return
        if piece.x == gx and piece.y == gy:
            editor_board_pick = None
            editor_message = ""
            return

        ok_sq, _reason = is_legal_piece_square(piece.name, piece.color, gx, gy)
        if not ok_sq:
            editor_message = t("editor_bad_square", name=piece.name)
            return

        target = board.get_piece_at(gx, gy)
        replaced = target is not None and target is not piece
        # 移除目標格棋子（若有）
        if replaced:
            board.pieces = [p for p in board.pieces if p is not target]

        # 將／帥唯一性：若目標曾有同名將帥已在上面移除；移動自身不增數量
        piece.x = gx
        piece.y = gy
        piece.selected = False
        board.selected_piece = None
        board.winner = None
        board.draw_reason = ""
        editor_board_pick = None
        # 移動成功不常駐訊息，避免干擾
        editor_message = ""

    def editor_save_current():
        nonlocal editor_saved_list, editor_message
        if not board:
            return
        ok, reason = validate_editor_position(board)
        if not ok:
            editor_message = t("editor_invalid", reason=reason)
            return
        fen = board.to_fen()
        positions = load_custom_positions()
        default_name = f"局面 {len(positions) + 1}"
        title = prompt_text_input(
            t("editor_save_name_title"),
            t("editor_save_name_prompt"),
            default_name,
        )
        if title is None:
            return  # 使用者取消
        if not title.strip():
            editor_message = t("editor_name_empty")
            return
        new_id = f"pos_{int(time.time())}"
        positions.append({"id": new_id, "title": title.strip(), "fen": fen})
        ok_w, err = save_custom_positions(positions)
        if ok_w:
            editor_saved_list = positions
            editor_message = t("editor_saved", title=title.strip())
        else:
            editor_message = t("editor_save_fail", err=err)

    def editor_lib_load_to_edit():
        nonlocal board, editor_message, game_state, editor_board_pick
        item = editor_lib_get_selected()
        if not item:
            editor_message = t("editor_select_first")
            return
        try:
            board = XiangqiBoard(MODE_PVP, fen=item["fen"])
            editor_board_pick = None
            editor_message = t("editor_loaded", title=item["title"])
            game_state = MODE_EDITOR
            build_editor_buttons()
        except Exception as ex:
            editor_message = t("editor_load_fail", err=str(ex))

    def editor_lib_start_game(mode):
        nonlocal editor_message
        item = editor_lib_get_selected()
        if not item:
            editor_message = t("editor_select_first")
            return
        # 像讀取存檔一樣進入對局；人機可繼續用 AI
        warning = (
            t("editor_start_ai", level=ai_difficulty_display(ai_difficulty))
            if mode == MODE_AI
            else t("editor_start_pvp")
        )
        start_session(mode, fen=item["fen"], human_side=RED, validate="editor", warning=warning)

    def editor_lib_rename():
        nonlocal editor_saved_list, editor_message
        item = editor_lib_get_selected()
        if not item:
            editor_message = t("editor_select_first")
            return
        new_name = prompt_text_input(
            t("editor_rename_title"),
            t("editor_rename_prompt"),
            item.get("title") or "",
        )
        if new_name is None:
            return
        if not new_name.strip():
            editor_message = t("editor_name_empty")
            return
        positions = load_custom_positions()
        for p in positions:
            if p.get("id") == item["id"]:
                p["title"] = new_name.strip()
                break
        ok, err = save_custom_positions(positions)
        if ok:
            editor_saved_list = positions
            editor_message = t("editor_renamed")
            build_editor_lib_ui()
        else:
            editor_message = t("editor_save_fail", err=err)

    def editor_lib_delete():
        nonlocal editor_saved_list, editor_lib_selected, editor_message
        item = editor_lib_get_selected()
        if not item:
            editor_message = t("editor_select_first")
            return
        positions = [p for p in load_custom_positions() if p.get("id") != item["id"]]
        ok, err = save_custom_positions(positions)
        if ok:
            editor_saved_list = positions
            editor_lib_selected = None
            editor_message = t("editor_deleted")
            build_editor_lib_ui()
        else:
            editor_message = t("editor_save_fail", err=err)

    def save_game_to_disk():
        if not board or game_state not in (MODE_PVP, MODE_AI):
            return False
        try:
            payload = {
                "version": 1,
                "type": "savegame",  # 與 editor_positions 區分
                "game_state": game_state,
                "player_color": color_to_str(player_color),
                "ai_color": color_to_str(ai_color),
                "view_color": color_to_str(view_color),
                "ai_difficulty": ai_difficulty,
                "suggest_enabled": bool(suggest_enabled),
                "start_fen": game_start_fen,
                "moves": list(board.move_ucci_history),
                "history_scroll_offset": float(history_scroll.scroll_offset if history_scroll else 0.0),
            }
            os.makedirs(os.path.dirname(save_file_path), exist_ok=True)
            with open(save_file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            board.set_warning(t("msg_save_ok"))
            return True
        except Exception as ex:
            if board:
                board.set_warning(t("msg_save_fail", err=ex))
            return False

    def load_game_from_disk():
        nonlocal game_state, board, history_scroll
        nonlocal ai_enabled, eval_enabled, suggest_enabled
        nonlocal player_color, ai_color, view_color
        nonlocal draw_offer_popup, btn_draw_accept, btn_draw_reject
        nonlocal replay_index, replay_mode_active
        nonlocal replay_record_moves, replay_record_notation
        nonlocal replay_finished_winner, replay_finished_draw_reason
        nonlocal game_start_fen

        load_path = save_file_path
        if not os.path.exists(load_path):
            # 相容舊版寫在程式目錄的存檔
            legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), SAVE_FILE_NAME)
            if os.path.isfile(legacy):
                load_path = legacy
            else:
                if board:
                    board.set_warning(t("msg_load_missing"))
                return False

        try:
            with open(load_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as ex:
            if board:
                board.set_warning(t("msg_load_fail", err=ex))
            return False

        # 禁止與局面庫 JSON 混讀
        if isinstance(payload, dict):
            if payload.get("type") == "editor_positions" or (
                "positions" in payload and "moves" not in payload
            ):
                if board:
                    board.set_warning(t("msg_load_is_editor"))
                return False

        try:
            saved_mode = int(payload.get("game_state", MODE_PVP))
            if saved_mode not in (MODE_PVP, MODE_AI):
                saved_mode = MODE_PVP

            saved_player = str_to_color(payload.get("player_color"), RED)
            saved_ai = str_to_color(payload.get("ai_color"), BLACK)
            saved_view = str_to_color(payload.get("view_color"), saved_player)
            saved_moves = payload.get("moves", [])
            if not isinstance(saved_moves, list):
                raise ValueError("存檔 moves 格式錯誤")
            saved_start_fen = payload.get("start_fen")
            if saved_start_fen is not None and not isinstance(saved_start_fen, str):
                raise ValueError("存檔 start_fen 格式錯誤")

            opponent = None
            if saved_mode == MODE_AI:
                opponent = saved_ai if saved_ai != saved_player else (
                    BLACK if saved_player == RED else RED
                )
            if not start_session(
                saved_mode,
                fen=saved_start_fen,
                human_side=saved_player if saved_mode == MODE_AI else RED,
                view=saved_view,
                opponent=opponent,
            ):
                raise ValueError("無法建立存檔起始局面")

            saved_diff = payload.get("ai_difficulty", ai_difficulty)
            if saved_diff in AI_DIFFICULTY_PRESETS:
                apply_ai_difficulty(saved_diff)

            # 回放所有走步，重建完整棋局狀態與規則計數器。
            reset_replay_history()
            for mv in saved_moves:
                if not isinstance(mv, str) or len(mv) < 4:
                    raise ValueError("存檔中有無效走步")
                if not apply_ucci_move(board, mv):
                    raise ValueError(f"無法套用走步：{mv}")
                append_replay_snapshot()

            # 還原 UI 狀態
            suggest_enabled = bool(payload.get("suggest_enabled", False))
            if btn_suggest_toggle:
                btn_suggest_toggle.text = t("suggest_on") if suggest_enabled else t("suggest_off")

            if history_scroll:
                max_scroll = get_history_max_scroll()
                saved_offset = float(payload.get("history_scroll_offset", 0.0))
                history_scroll.scroll_offset = max(0, min(max_scroll, saved_offset))

            reset_ai_state()
            reset_eval_state(reset_display=True)
            reset_suggest_state(reset_display=True)
            replay_mode_active = False
            replay_record_moves = []
            replay_record_notation = []
            replay_finished_winner = None
            replay_finished_draw_reason = ""
            replay_index = None
            draw_offer_popup = None
            btn_draw_accept = None
            btn_draw_reject = None
            board.set_warning(t("msg_load_ok"))
            return True
        except Exception as ex:
            if board:
                board.set_warning(t("msg_load_fail", err=ex))
            return False

    def open_draw_offer_popup():
        nonlocal draw_offer_popup, btn_draw_accept, btn_draw_reject
        if not board or board.winner or board.draw_reason:
            return
        draw_offer_popup = {"from_color": board.turn}
        btn_draw_accept = Button(SCREEN_WIDTH // 2 - 130, SCREEN_HEIGHT // 2 + 20, 120, 40, t("accept_draw"))
        btn_draw_reject = Button(SCREEN_WIDTH // 2 + 10, SCREEN_HEIGHT // 2 + 20, 120, 40, t("reject_draw"))

    def close_draw_offer_popup():
        nonlocal draw_offer_popup, btn_draw_accept, btn_draw_reject
        draw_offer_popup = None
        btn_draw_accept = None
        btn_draw_reject = None

    def request_draw():
        if not board or board.winner or board.draw_reason:
            return
        if game_state == MODE_PVP:
            open_draw_offer_popup()
            return
        if game_state == MODE_AI:
            if board.turn != player_color:
                board.set_warning(t("msg_draw_not_your_turn"))
                return
            if abs(eval_red_score_cp) <= 100:
                board.draw_reason = t("msg_draw_agree_ai")
                board.set_warning(t("msg_draw_ai_accept"))
            else:
                board.set_warning(t("msg_draw_ai_reject"))

    def choose_ai_move(engine_bestmove):
        # 殘局固定用引擎最佳著，絕不故意失誤
        if game_state == MODE_ENDGAME:
            return engine_bestmove
        if not engine_bestmove or ai_mistake_rate <= 0:
            return engine_bestmove
        if random.random() >= ai_mistake_rate:
            return engine_bestmove

        legal_moves = board.legal_moves_ucci(ai_color) if board else []
        if not legal_moves:
            return engine_bestmove

        alternatives = [mv for mv in legal_moves if mv != engine_bestmove]
        if not alternatives:
            return engine_bestmove
        return random.choice(alternatives)

    def current_ai_search_params():
        """一般 AI 對戰用選單難度；殘局闖關固定最高強度。"""
        if game_state == MODE_ENDGAME:
            return ENDGAME_AI_MOVETIME_MS, ENDGAME_AI_DEPTH, ENDGAME_AI_MAX_WAIT_SEC
        return ai_movetime_ms, ai_search_depth, ai_max_wait_sec

    def reset_eval_state(reset_display=False):
        nonlocal eval_request_id, eval_last_fen_requested
        nonlocal eval_red_score_cp, eval_text
        eval_request_id = None
        eval_last_fen_requested = None
        if reset_display:
            eval_red_score_cp = 0
            eval_text = "+0"

    def reset_suggest_state(reset_display=False):
        nonlocal suggest_request_id, suggest_last_fen_requested, suggest_move
        suggest_request_id = None
        suggest_last_fen_requested = None
        if reset_display:
            suggest_move = None

    def new_request_id():
        nonlocal request_seq
        request_seq += 1
        return request_seq

    def ensure_engine():
        nonlocal engine_dispatcher
        if engine_dispatcher:
            return True
        dispatcher = None
        try:
            dispatcher = EngineDispatcher()
            dispatcher.start()
            engine_dispatcher = dispatcher
            return True
        except Exception as e:
            # 啟動失敗時務必回收程序，避免遺留 pikafish 背景行程
            if dispatcher is not None:
                try:
                    dispatcher.stop()
                except Exception:
                    pass
            engine_dispatcher = None
            if board:
                board.set_warning(t("msg_engine_fail", err=e))
            return False

    def stop_engine():
        nonlocal engine_dispatcher
        if engine_dispatcher:
            engine_dispatcher.stop()
        engine_dispatcher = None

    def poll_engine_results():
        nonlocal ai_request_id, eval_request_id, suggest_request_id, analysis_request_id
        nonlocal ai_enabled, eval_enabled, suggest_enabled
        nonlocal ai_wait_until, ai_request_fen, suggest_move
        nonlocal analysis_status, analysis_error

        if not engine_dispatcher:
            return

        while True:
            res = engine_dispatcher.get_result_nowait()
            if not res:
                break

            req_id, kind, req_fen, status, payload = (
                res.req_id, res.kind, res.fen, res.status, res.payload
            )

            if analysis_request_id is not None and req_id == analysis_request_id:
                if status == "err":
                    analysis_status = "error"
                    analysis_error = str(payload)
                    analysis_request_id = None
                    if board:
                        board.set_warning(t("analyze_fail", err=analysis_error))
                    continue
                try:
                    handle_analysis_result(payload)
                except Exception as ex:
                    analysis_status = "error"
                    analysis_error = str(ex)
                    analysis_request_id = None
                    if board:
                        board.set_warning(t("analyze_fail", err=analysis_error))
                continue

            if req_id == ai_request_id:
                ai_request_id = None
                if status == "err":
                    ai_enabled = False
                    if board:
                        board.set_warning(t("msg_ai_fail", err=payload))
                    continue

                if (not board or board.winner or board.draw_reason or
                    board.turn != ai_color or board.to_fen() != req_fen):
                    continue

                best = payload
                if not best:
                    ai_enabled = False
                    board.set_warning(t("msg_ai_no_move"))
                else:
                    move_to_play = choose_ai_move(best)
                    if not apply_ucci_move(board, move_to_play):
                        # 如果故意失誤著因局面時序失配而失敗，退回最佳著再試一次。
                        if move_to_play != best and apply_ucci_move(board, best):
                            ai_wait_until = 0.0
                            ai_request_fen = None
                            on_move_applied()
                            if game_state == MODE_ENDGAME:
                                check_endgame_result()
                        else:
                            ai_enabled = False
                            board.set_warning(t("msg_ai_bad_move", mv=move_to_play))
                    else:
                        ai_wait_until = 0.0
                        ai_request_fen = None
                        on_move_applied()
                        if game_state == MODE_ENDGAME:
                            check_endgame_result()
                continue

            if req_id == eval_request_id:
                eval_request_id = None
                if status == "err":
                    eval_enabled = False
                    if board:
                        board.set_warning(t("msg_eval_fail", err=payload))
                    continue
                if board and board.to_fen() == req_fen:
                    side_token = req_fen.split()[1]
                    score_type, score_value = payload
                    update_eval_from_score(score_type, score_value, side_token)
                continue

            if req_id == suggest_request_id:
                suggest_request_id = None
                if status == "err":
                    suggest_enabled = False
                    suggest_move = None
                    if btn_suggest_toggle:
                        btn_suggest_toggle.text = t("suggest_off")
                    if board:
                        board.set_warning(t("msg_suggest_fail", err=payload))
                    continue
                if board and board.to_fen() == req_fen:
                    suggest_move = payload
                continue

    def board_to_view_coords(x, y):
        if view_color == BLACK:
            return (8 - x, 9 - y)
        return (x, y)

    def view_to_board_coords(vx, vy):
        if view_color == BLACK:
            return (8 - vx, 9 - vy)
        return (vx, vy)

    def update_eval_from_score(score_type, score_value, side_token):
        nonlocal eval_red_score_cp, eval_text

        if score_type == "mate":
            red_mate = score_value if side_token == "w" else -score_value
            sign = "+" if red_mate > 0 else "-"
            eval_text = f"{sign}M{abs(red_mate)}"
            eval_red_score_cp = 10000 if red_mate > 0 else -10000
            return

        # UCI score 是以 side-to-move 為視角；轉成紅方視角
        red_cp = score_value if side_token == "w" else -score_value
        eval_red_score_cp = red_cp
        eval_text = f"{red_cp:+d}"

    # 載入語言偏好並建立主選單（左→右：對戰｜AI｜殘局）
    set_language(load_language_pref())  # 啟動時寫入失敗可忽略，至少記憶體內已套用
    pygame.display.set_caption(t("app_caption"))
    menu_status_msg = ""
    menu_status_until = 0.0

    def menu_column_rects():
        total_w = 3 * MENU_COL_W + 2 * MENU_COL_GAP
        start_x = (SCREEN_WIDTH - total_w) // 2
        rects = []
        for i in range(3):
            x = start_x + i * (MENU_COL_W + MENU_COL_GAP)
            rects.append(pygame.Rect(x, MENU_COL_TOP, MENU_COL_W, MENU_COL_H))
        return rects

    def layout_menu_buttons():
        """依三欄版面放置主選單按鈕（加大卡片內邊距，避免描述與按鈕擠在一起）。"""
        nonlocal btn_pvp, btn_ai_red, btn_ai_black, btn_formula_menu, btn_endgame_menu
        nonlocal btn_menu_load, btn_quit, btn_lang, btn_clock, btn_editor_menu
        cols = menu_column_rects()
        pad = MENU_CARD_PAD_X
        bw = MENU_COL_W - pad * 2
        bx = lambda col: col.x + pad
        y0 = MENU_CARD_BTN_START
        gap = MENU_CARD_BTN_GAP
        h_main, h_sub = 46, 40

        # 左欄：玩家對戰
        btn_pvp.rect = pygame.Rect(bx(cols[0]), cols[0].y + y0, bw, h_main)
        btn_pvp.text = t("pvp")
        btn_menu_load.rect = pygame.Rect(bx(cols[0]), cols[0].y + y0 + h_main + gap, bw, h_sub)
        btn_menu_load.text = t("load_save")
        btn_clock.rect = pygame.Rect(bx(cols[0]), cols[0].y + y0 + h_main + gap + h_sub + gap, bw, h_sub)
        btn_clock.text = t("clock", label=time_control_label(current_time_control()))

        # 中欄：玩家對 AI
        btn_ai_red.rect = pygame.Rect(bx(cols[1]), cols[1].y + y0, bw, h_main)
        btn_ai_red.text = t("ai_red")
        btn_ai_black.rect = pygame.Rect(bx(cols[1]), cols[1].y + y0 + h_main + gap, bw, h_main)
        btn_ai_black.text = t("ai_black")

        # 右欄：殘局 + 編輯器（按鈕區與描述拉開；底部留給 badges）
        btn_formula_menu.rect = pygame.Rect(bx(cols[2]), cols[2].y + y0, bw, h_sub)
        btn_formula_menu.text = t("formula")
        btn_endgame_menu.rect = pygame.Rect(
            bx(cols[2]), cols[2].y + y0 + h_sub + gap, bw, h_sub
        )
        btn_endgame_menu.text = t("challenge")
        btn_editor_menu.rect = pygame.Rect(
            bx(cols[2]), cols[2].y + y0 + 2 * (h_sub + gap), bw, h_sub
        )
        btn_editor_menu.text = t("editor")

        # 頂部右上：語言 chip（小圖示）
        chip = 44
        btn_lang.rect = pygame.Rect(SCREEN_WIDTH - chip - 20, 16, chip, chip)
        btn_lang.text = t("lang_chip")
        btn_lang.radius = chip // 2
        btn_lang.draw_shadow = True

        # 底部左下：結束遊戲（幽靈按鈕，次要操作）
        btn_quit.rect = pygame.Rect(20, SCREEN_HEIGHT - 48, 120, 32)
        btn_quit.text = t("quit")
        btn_quit.ghost = True
        btn_quit.draw_shadow = False
        btn_quit.radius = 8
        btn_quit.border_color = COLOR_CARD_BORDER
        btn_quit.text_color = COLOR_TEXT_SECONDARY

    # 先建立按鈕實例，再套用三欄座標（btn_difficulty 改在人機對局內建立）
    btn_pvp = Button(0, 0, 100, 40, t("pvp"))
    btn_ai_red = Button(0, 0, 100, 40, t("ai_red"))
    btn_ai_black = Button(0, 0, 100, 40, t("ai_black"))
    btn_formula_menu = Button(0, 0, 100, 40, t("formula"))
    btn_endgame_menu = Button(0, 0, 100, 40, t("challenge"))
    btn_editor_menu = Button(0, 0, 100, 40, t("editor"))
    btn_difficulty = None
    btn_menu_load = Button(0, 0, 100, 40, t("load_save"))
    btn_clock = Button(0, 0, 100, 40, t("clock", label=time_control_label(current_time_control())))
    btn_quit = Button(0, 0, 100, 40, t("quit"))
    btn_quit.ghost = True
    btn_lang = Button(0, 0, 100, 40, t("lang_chip"))
    layout_menu_buttons()

    def switch_language():
        """在繁體／簡體之間切換，並刷新可見 UI 文字。"""
        nonlocal menu_status_msg, menu_status_until
        new_lang = LANG_HANS if get_lang() == LANG_HANT else LANG_HANT
        ok, err = set_language(new_lang)
        pygame.display.set_caption(t("app_caption"))
        layout_menu_buttons()
        if game_state == MODE_ENDGAME_DIFF:
            build_endgame_diff_buttons()
        elif game_state == MODE_ENDGAME_LEVELS:
            build_endgame_level_buttons()
        elif game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME) and board:
            setup_in_game_buttons(for_endgame=(game_state == MODE_ENDGAME))
            if not ok:
                board.set_warning(t("msg_lang_warn", err=err))
        if not ok:
            data_dir = get_user_data_dir()
            menu_status_msg = f"語言已切換（本次有效），但無法儲存偏好：{err}（目錄：{data_dir}）"
            menu_status_until = time.time() + 6.0
        else:
            menu_status_msg = ""
            menu_status_until = 0.0

    btn_undo = None  # 悔棋按鈕會在遊戲中建立
    btn_main_menu = None  # 遊戲中隨時返回主選單
    btn_suggest_toggle = None  # 建議著法開關
    btn_save_game = None
    btn_load_game = None
    btn_draw_offer = None
    btn_replay_mode = None
    btn_analyze = None
    btn_endgame_back = None
    
    while True:
        mouse_pos = window_to_logical_pos(pygame.mouse.get_pos(), render_rect)
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                stop_engine()
                pygame.quit(); sys.exit()
            if event.type == pygame.VIDEORESIZE:
                resized = (max(320, event.w), max(240, event.h))
                window = pygame.display.set_mode(resized, pygame.RESIZABLE)
                render_rect = get_render_rect(window.get_size())
                continue
            # 鍵盤事件：按 D 鍵可切換 debug 日誌（臨時，用於排查長捉/長將）
            if event.type == pygame.KEYDOWN and game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
                if event.key == pygame.K_d and board:
                    board.debug = not board.debug
                    board.set_warning(
                        t("msg_debug", state=t("msg_debug_on") if board.debug else t("msg_debug_off"))
                    )
            
            # --- 菜單模式 ---
            if game_state == MODE_MENU:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if btn_pvp.is_clicked(mouse_pos):
                        start_session(MODE_PVP)
                    elif btn_ai_red.is_clicked(mouse_pos):
                        start_session(MODE_AI, human_side=RED)
                    elif btn_ai_black.is_clicked(mouse_pos):
                        start_session(MODE_AI, human_side=BLACK)
                    elif btn_formula_menu and btn_formula_menu.is_clicked(mouse_pos):
                        open_endgame_diff_select(ENDGAME_SECTION_FORMULA)
                    elif btn_endgame_menu and btn_endgame_menu.is_clicked(mouse_pos):
                        open_endgame_diff_select(ENDGAME_SECTION_CHALLENGE)
                    elif btn_editor_menu and btn_editor_menu.is_clicked(mouse_pos):
                        open_editor()
                    elif btn_menu_load and btn_menu_load.is_clicked(mouse_pos):
                        load_game_from_disk()
                    elif btn_clock and btn_clock.is_clicked(mouse_pos):
                        cycle_time_control()
                    elif btn_lang and btn_lang.is_clicked(mouse_pos):
                        switch_language()
                    elif btn_quit and btn_quit.is_clicked(mouse_pos):
                        stop_engine()
                        pygame.quit()
                        sys.exit()

            # --- 殘局：選擇難度 ---
            elif game_state == MODE_ENDGAME_DIFF:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if btn_endgame_back and btn_endgame_back.is_clicked(mouse_pos):
                        game_state = MODE_MENU
                        endgame_diff_buttons = []
                        endgame_level_buttons = []
                        endgame_filter_group = None
                    else:
                        for btn, group in endgame_diff_buttons:
                            if btn.is_clicked(mouse_pos):
                                open_endgame_level_select(group)
                                break

            # --- 殘局：該難度關卡列表 ---
            elif game_state == MODE_ENDGAME_LEVELS:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    list_rect = pygame.Rect(
                        ENDGAME_LIST_LEFT,
                        ENDGAME_LIST_TOP,
                        ENDGAME_LIST_WIDTH + ENDGAME_SCROLLBAR_W + 12,
                        endgame_list_viewport_height(),
                    )
                    if event.button == 4:
                        endgame_list_scroll = max(0, endgame_list_scroll - 48)
                        build_endgame_level_buttons()
                    elif event.button == 5:
                        endgame_list_scroll = min(endgame_list_max_scroll(), endgame_list_scroll + 48)
                        build_endgame_level_buttons()
                    elif event.button == 1:
                        if btn_endgame_back and btn_endgame_back.is_clicked(mouse_pos):
                            open_endgame_diff_select()
                        elif endgame_list_scrollbar and endgame_list_max_scroll() > 0:
                            endgame_list_scrollbar.handle_click(mouse_pos)
                            if endgame_list_scrollbar.is_dragging:
                                pass
                            elif list_rect.collidepoint(mouse_pos):
                                for btn, payload in endgame_level_buttons:
                                    # 只接受可見區域內的點擊
                                    if btn.rect.bottom <= ENDGAME_LIST_TOP or btn.rect.top >= ENDGAME_LIST_BOTTOM:
                                        continue
                                    if not btn.is_clicked(mouse_pos):
                                        continue
                                    if payload == "locked":
                                        break
                                    start_endgame_level(payload)
                                    break
                        elif list_rect.collidepoint(mouse_pos):
                            for btn, payload in endgame_level_buttons:
                                if btn.rect.bottom <= ENDGAME_LIST_TOP or btn.rect.top >= ENDGAME_LIST_BOTTOM:
                                    continue
                                if not btn.is_clicked(mouse_pos):
                                    continue
                                if payload == "locked":
                                    break
                                start_endgame_level(payload)
                                break
                elif event.type == pygame.MOUSEMOTION:
                    if endgame_list_scrollbar and endgame_list_scrollbar.is_dragging:
                        endgame_list_scrollbar.handle_drag(mouse_pos, endgame_list_max_scroll())
                        endgame_list_scroll = int(endgame_list_scrollbar.scroll_offset)
                        build_endgame_level_buttons()
                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1 and endgame_list_scrollbar:
                        endgame_list_scrollbar.handle_release()

            # --- 局面編輯器 ---
            elif game_state == MODE_EDITOR:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = mouse_pos
                    editor_btns = [
                        (btn_editor_back, "back"),
                        (btn_editor_turn, "turn"),
                        (btn_editor_erase, "erase"),
                        (btn_editor_clear, "clear"),
                        (btn_editor_initial, "initial"),
                        (btn_editor_save, "save"),
                        (btn_editor_load, "load"),
                    ]
                    handled = False
                    for btn, action in editor_btns:
                        if btn and btn.is_clicked(mouse_pos):
                            handled = True
                            if action == "back":
                                game_state = MODE_MENU
                                board = None
                                editor_message = ""
                                editor_board_pick = None
                            elif action == "turn" and board:
                                board.turn = BLACK if board.turn == RED else RED
                                build_editor_buttons()
                                editor_message = ""
                            elif action == "erase":
                                editor_selected = "erase"
                                editor_board_pick = None
                                editor_message = ""
                            elif action == "clear" and board:
                                board = create_empty_xiangqi_board(board.turn)
                                editor_board_pick = None
                                editor_message = ""
                                build_editor_buttons()
                            elif action == "initial":
                                board = XiangqiBoard(MODE_PVP)
                                editor_board_pick = None
                                editor_message = ""
                                build_editor_buttons()
                            elif action == "save":
                                editor_save_current()
                            elif action == "load":
                                editor_board_pick = None
                                open_editor_library()
                            break
                    if handled:
                        continue

                    for rect, item in editor_palette_rects():
                        if rect.collidepoint(mx, my) and event.button == 1:
                            editor_selected = item
                            editor_board_pick = None
                            editor_message = ""
                            handled = True
                            break
                    if handled:
                        continue

                    vx = round((mx - MARGIN_X) / GRID_SIZE)
                    vy = round((my - MARGIN_Y) / GRID_SIZE)
                    if 0 <= vx <= 8 and 0 <= vy <= 9 and board:
                        gx, gy = vx, vy
                        if event.button == 3 or editor_selected == "erase":
                            editor_erase_at(gx, gy)
                        elif event.button == 1:
                            clicked_piece = board.get_piece_at(gx, gy)
                            # 1) 已選盤上棋 → 移到空格，或點他子則取代
                            if editor_board_pick is not None:
                                editor_move_picked_to(gx, gy)
                            # 2) 點盤上既有棋子 → 選取移動（優先於調色盤，方便改標準開局）
                            elif clicked_piece is not None:
                                editor_pick_board_piece(clicked_piece)
                            # 3) 空格 + 調色盤 → 放置新棋
                            elif isinstance(editor_selected, tuple):
                                name, color = editor_selected
                                editor_place_piece(gx, gy, name, color)

            # --- 已存局面庫 ---
            elif game_state == MODE_EDITOR_LIB:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 4:
                        editor_lib_scroll = max(0, editor_lib_scroll - 1)
                        build_editor_lib_ui()
                    elif event.button == 5:
                        editor_lib_scroll += 1
                        build_editor_lib_ui()
                    elif event.button == 1:
                        if btn_lib_back and btn_lib_back.is_clicked(mouse_pos):
                            game_state = MODE_EDITOR
                            build_editor_buttons()
                        elif btn_lib_to_edit and btn_lib_to_edit.is_clicked(mouse_pos):
                            editor_lib_load_to_edit()
                        elif btn_lib_pvp and btn_lib_pvp.is_clicked(mouse_pos):
                            editor_lib_start_game(MODE_PVP)
                        elif btn_lib_ai and btn_lib_ai.is_clicked(mouse_pos):
                            editor_lib_start_game(MODE_AI)
                        elif btn_lib_rename and btn_lib_rename.is_clicked(mouse_pos):
                            editor_lib_rename()
                        elif btn_lib_delete and btn_lib_delete.is_clicked(mouse_pos):
                            editor_lib_delete()
                        else:
                            for btn, pos in editor_lib_buttons:
                                if btn.is_clicked(mouse_pos):
                                    editor_lib_selected = pos.get("id")
                                    editor_message = ""
                                    break

            # --- 遊戲模式（含殘局） ---
            elif event.type == pygame.MOUSEBUTTONDOWN and game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
                # 遊戲中隨時返回主選單
                if btn_main_menu and btn_main_menu.is_clicked(mouse_pos):
                    stop_engine()
                    reset_ai_state()
                    reset_eval_state(reset_display=True)
                    reset_suggest_state(reset_display=True)
                    game_state = MODE_MENU
                    board = None
                    endgame_current = None
                    endgame_status = ""
                    btn_main_menu = None
                    btn_suggest_toggle = None
                    btn_undo = None
                    btn_save_game = None
                    btn_load_game = None
                    btn_draw_offer = None
                    btn_replay_mode = None
                    btn_difficulty = None
                    btn_analyze = None
                    btn_endgame_hint = None
                    btn_endgame_retry = None
                    btn_endgame_levels = None
                    history_scroll = None
                    replay_snapshots = []
                    replay_index = None
                    replay_mode_active = False
                    replay_record_moves = []
                    replay_record_notation = []
                    replay_finished_winner = None
                    replay_finished_draw_reason = ""
                    close_draw_offer_popup()
                elif game_state == MODE_ENDGAME and btn_endgame_levels and btn_endgame_levels.is_clicked(mouse_pos):
                    open_endgame_diff_select()
                elif game_state == MODE_ENDGAME and btn_endgame_retry and btn_endgame_retry.is_clicked(mouse_pos):
                    if endgame_current:
                        start_endgame_level(endgame_current)
                else:
                    max_scroll = get_history_max_scroll()

                    # PVP 求和彈窗優先處理
                    if draw_offer_popup:
                        if event.button == 1:
                            if btn_draw_accept and btn_draw_accept.is_clicked(mouse_pos):
                                board.draw_reason = t("msg_draw_agree")
                                close_draw_offer_popup()
                            elif btn_draw_reject and btn_draw_reject.is_clicked(mouse_pos):
                                board.set_warning(t("msg_draw_rejected"))
                                close_draw_offer_popup()
                        continue

                    # 先處理棋譜滾動（終局後也可滾動）。
                    if event.button == 4:
                        if history_scroll:
                            history_scroll.handle_scroll(-30, max_scroll)
                        continue
                    if event.button == 5:
                        if history_scroll:
                            history_scroll.handle_scroll(30, max_scroll)
                        continue

                    # 滾動條拖動起點（必須與上方 button 4/5 同層，不可縮在 wheel 分支內）
                    if event.button == 1 and history_scroll:
                        history_scroll.handle_click(mouse_pos)
                        if history_scroll.is_dragging:
                            continue

                    # 賽後分析：終局後也必須可點（不可被下方 continue 擋掉）
                    if event.button == 1 and btn_analyze and btn_analyze.is_clicked(mouse_pos):
                        if analysis_status == "running":
                            if board:
                                board.set_warning(
                                    t("analyzing", cur=analysis_progress, total=max(1, analysis_total))
                                )
                        else:
                            start_postgame_analysis()
                        continue

                    # AI 難度：對局中可隨時切換（含終局後）
                    if event.button == 1 and btn_difficulty and btn_difficulty.is_clicked(mouse_pos):
                        if game_state == MODE_AI:
                            cycle_ai_difficulty()
                        continue

                    if event.button == 1 and btn_replay_mode and btn_replay_mode.is_clicked(mouse_pos):
                        if replay_mode_active:
                            board.set_warning(t("msg_replay_active"))
                        elif board.winner or board.draw_reason:
                            enter_replay_mode()
                        else:
                            board.set_warning(t("msg_replay_need_end"))
                        continue

                    # 未進入復盤模式時，終局局面不可直接操作棋子／存讀檔等。
                    if (board.winner or board.draw_reason) and not replay_mode_active:
                        continue

                    # 復盤模式下可點譜跳局面，但不影響原終局棋譜。
                    if replay_mode_active and event.button == 1:
                        idx = get_notation_index_at_pos(mouse_pos)
                        if idx is not None:
                            if restore_game_to_step(idx + 1, source_moves=replay_record_moves):
                                board.set_warning(t("msg_replay_jump", n=idx + 1))
                            else:
                                board.set_warning(t("msg_replay_jump_fail"))
                            continue
                        # 復盤中不再處理走子／悔棋等，但分析已在上方處理
                        continue

                    # 以下是未結束遊戲時的操作
                    if btn_save_game and btn_save_game.is_clicked(mouse_pos):
                        save_game_to_disk()
                    elif btn_load_game and btn_load_game.is_clicked(mouse_pos):
                        load_game_from_disk()
                    elif btn_draw_offer and (not replay_mode_active) and btn_draw_offer.is_clicked(mouse_pos):
                        request_draw()
                    elif btn_suggest_toggle and btn_suggest_toggle.is_clicked(mouse_pos):
                        suggest_enabled = not suggest_enabled
                        btn_suggest_toggle.text = t("suggest_on") if suggest_enabled else t("suggest_off")
                        reset_suggest_state(reset_display=True)
                        if not suggest_enabled:
                            reset_eval_state(reset_display=True)
                    elif btn_undo and btn_undo.is_clicked(mouse_pos):
                        if endgame_status:
                            continue
                        if board.undo_last_move():
                            board.selected_piece = None
                            reset_ai_state()
                            reset_eval_state()
                            reset_suggest_state()
                            sync_replay_history_after_undo()
                            if game_state == MODE_ENDGAME:
                                endgame_player_moves = sum(
                                    1 for piece, *_rest in board.move_history
                                    if piece.color == player_color
                                )
                                endgame_status = ""
                    else:
                        if endgame_status and game_state == MODE_ENDGAME:
                            continue
                        if game_state in (MODE_AI, MODE_ENDGAME) and ai_enabled and board.turn == ai_color:
                            continue
                        # 棋盤操作
                        mx, my = mouse_pos
                        vx = round((mx - MARGIN_X) / GRID_SIZE)
                        vy = round((my - MARGIN_Y) / GRID_SIZE)

                        if 0 <= vx <= 8 and 0 <= vy <= 9:
                            gx, gy = view_to_board_coords(vx, vy)
                            clicked = board.get_piece_at(gx, gy)
                            selected = board.selected_piece

                            if selected:
                                # 嘗試移動
                                if board.is_valid_move(selected, gx, gy):
                                    if not board.move_piece(selected, gx, gy):
                                        # 如果 move_piece 返回 False，代表移動後會被將軍，已被駁回
                                        pass
                                    else:
                                        on_move_applied()
                                        if game_state == MODE_ENDGAME:
                                            endgame_player_moves += 1
                                            check_endgame_result()
                                        if game_state in (MODE_AI, MODE_ENDGAME) and board.turn == ai_color and not endgame_status:
                                            reset_ai_state()
                                            ai_wait_until = time.time() + AI_DELAY_SEC
                                elif clicked and clicked.color == board.turn:
                                    selected.selected = False
                                    clicked.selected = True
                                    board.selected_piece = clicked
                            else:
                                if clicked and clicked.color == board.turn:
                                    clicked.selected = True
                                    board.selected_piece = clicked

            elif event.type == pygame.MOUSEMOTION and game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
                if history_scroll:
                    history_scroll.handle_drag(mouse_pos, get_history_max_scroll())

            elif event.type == pygame.MOUSEBUTTONUP and game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
                if event.button == 1 and history_scroll:
                    history_scroll.handle_release()

        # --- 引擎結果回收 ---
        poll_engine_results()

        # --- 棋鐘 ---
        if game_state in (MODE_PVP, MODE_AI) and board:
            tick_clocks()

        # --- AI 回合（一般 AI 對戰 + 殘局對手） ---
        # 分析進行中暫停 AI，避免搶引擎
        if (game_state in (MODE_AI, MODE_ENDGAME) and board and ai_enabled and
            analysis_status != "running" and
            not endgame_status and
            not board.winner and not board.draw_reason and board.turn == ai_color):
            if ai_wait_until <= 0:
                ai_wait_until = time.time() + AI_DELAY_SEC

            if ai_request_id is None and time.time() >= ai_wait_until:
                ai_request_fen = board.to_fen()
                if ensure_engine():
                    ai_request_id = new_request_id()
                    mt, depth, max_wait = current_ai_search_params()
                    engine_dispatcher.submit(
                        ai_request_id,
                        "bestmove",
                        ai_request_fen,
                        mt,
                        depth=depth,
                        max_wait_sec=max_wait,
                    )
                else:
                    ai_enabled = False
                    board.set_warning(t("msg_ai_engine_fail"))

        # --- 即時評估（僅在建議著法開啟時） ---
        if game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME) and board and eval_enabled and suggest_enabled and not board.winner and not board.draw_reason and not endgame_status:
            current_fen = board.to_fen()
            if eval_request_id is None and current_fen != eval_last_fen_requested:
                if ensure_engine():
                    eval_last_fen_requested = current_fen
                    eval_request_id = new_request_id()
                    engine_dispatcher.submit(eval_request_id, "analyse", current_fen, AI_EVAL_MOVETIME_MS)
                else:
                    eval_enabled = False
                    board.set_warning(t("msg_eval_engine_fail"))
        elif not suggest_enabled:
            reset_eval_state(reset_display=True)

        # --- 建議著法 ---
        if game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME) and board and suggest_enabled and not board.winner and not board.draw_reason and not endgame_status:
            # AI／殘局模式下，只在玩家回合提供建議
            if game_state in (MODE_AI, MODE_ENDGAME) and (not replay_mode_active) and board.turn != player_color:
                suggest_move = None
            else:
                current_fen = board.to_fen()
                if suggest_request_id is None and current_fen != suggest_last_fen_requested:
                    if ensure_engine():
                        suggest_last_fen_requested = current_fen
                        suggest_request_id = new_request_id()
                        engine_dispatcher.submit(suggest_request_id, "bestmove", current_fen, AI_SUGGEST_MOVETIME_MS, depth=None, max_wait_sec=None)
                    else:
                        suggest_enabled = False
                        if btn_suggest_toggle:
                            btn_suggest_toggle.text = t("suggest_off")
                        board.set_warning(t("msg_suggest_engine_fail"))
        elif not suggest_enabled:
            suggest_move = None

        if game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME) and board:
            capture_finished_record_if_needed()
            if game_state == MODE_ENDGAME and not endgame_status:
                check_endgame_result()

        # --- 繪圖 ---
        screen.fill(COLOR_BG)
        
        if game_state == MODE_MENU:
            # --- Header：主標題置中；語言 chip 右上 ---
            title = font_menu.render(t("app_title"), True, COLOR_TEXT)
            screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 52)))
            line_w = 100
            pygame.draw.line(
                screen, GOLD,
                (SCREEN_WIDTH // 2 - line_w, 86),
                (SCREEN_WIDTH // 2 + line_w, 86),
                1,
            )
            subtitle = font_subtitle.render(t("choose_mode"), True, COLOR_TEXT_SECONDARY)
            screen.blit(subtitle, subtitle.get_rect(center=(SCREEN_WIDTH // 2, 118)))

            # 三欄卡片（加大內邊距：標題／描述／按鈕分層）
            cols = menu_column_rects()
            col_titles = [t("col_pvp"), t("col_ai"), t("col_endgame")]
            col_descs = [t("pvp_desc"), t("ai_desc"), t("endgame_desc")]
            for i, col in enumerate(cols):
                draw_card(screen, col, fill=MENU_PANEL_COLORS[i], radius=16, shadow=True)
                ct = font.render(col_titles[i], True, COLOR_TEXT)
                screen.blit(ct, ct.get_rect(center=(col.centerx, col.y + MENU_CARD_TITLE_Y)))
                cd = font_body.render(col_descs[i], True, COLOR_TEXT_SECONDARY)
                screen.blit(cd, cd.get_rect(center=(col.centerx, col.y + MENU_CARD_DESC_Y)))

            # 主操作按鈕（統一暖灰）
            for btn in (btn_pvp, btn_menu_load, btn_clock, btn_ai_red, btn_ai_black,
                        btn_formula_menu, btn_endgame_menu, btn_editor_menu):
                if not btn:
                    continue
                btn.update_hover(mouse_pos)
                btn.color = BUTTON_COLOR
                btn.hover_color = BUTTON_HOVER_COLOR
                btn.border_color = BUTTON_BORDER
                btn.text_color = BUTTON_TEXT
                btn.ghost = False
                btn.draw_shadow = True

            # 左欄
            btn_pvp.draw(screen, font_small)
            btn_menu_load.draw(screen, font_small)
            btn_clock.draw(screen, font_small)
            tip_y = btn_clock.rect.bottom + 22
            clock_tip = font_body.render(t("clock_tip"), True, COLOR_TEXT_SECONDARY)
            screen.blit(clock_tip, clock_tip.get_rect(center=(cols[0].centerx, tip_y)))

            # 中欄
            btn_ai_red.draw(screen, font_small)
            btn_ai_black.draw(screen, font_small)
            tip = font_body.render(t("ai_tip"), True, COLOR_TEXT_SECONDARY)
            screen.blit(tip, tip.get_rect(center=(cols[1].centerx, btn_ai_black.rect.bottom + 22)))

            # 右欄：按鈕 + badges + 編輯器說明
            btn_formula_menu.draw(screen, font_small)
            btn_endgame_menu.draw(screen, font_small)
            btn_editor_menu.draw(screen, font_small)
            n_formula = sum(1 for lv in endgame_levels if lv.get("section") == ENDGAME_SECTION_FORMULA)
            n_challenge = sum(1 for lv in endgame_levels if lv.get("section") == ENDGAME_SECTION_CHALLENGE)
            badge_y = btn_editor_menu.rect.bottom + 28
            draw_badges_in_card(
                screen,
                cols[2],
                badge_y,
                [
                    (t("badge_formula", n=n_formula), BADGE_BG_FORMULA, BADGE_FG),
                    (t("badge_challenge", n=n_challenge), BADGE_BG_CHALLENGE, BADGE_FG),
                ],
                font_badge,
                gap=8,
            )
            ed = font_body.render(t("editor_desc"), True, COLOR_TEXT_SECONDARY)
            screen.blit(ed, ed.get_rect(center=(cols[2].centerx, badge_y + 32)))
            if endgame_load_error:
                err = font_body.render(endgame_load_error, True, WARNING_COLOR)
                screen.blit(err, err.get_rect(center=(cols[2].centerx, badge_y + 54)))

            # Header 語言 chip（右上）
            if btn_lang:
                btn_lang.update_hover(mouse_pos)
                btn_lang.color = COLOR_CARD
                btn_lang.hover_color = COLOR_CARD_ALT
                btn_lang.border_color = COLOR_CARD_BORDER
                btn_lang.text_color = COLOR_TEXT
                btn_lang.ghost = False
                btn_lang.draw_shadow = True
                btn_lang.draw(screen, font_small)

            # Footer：結束遊戲幽靈按鈕（左下，不搶主視覺）
            if btn_quit:
                btn_quit.update_hover(mouse_pos)
                btn_quit.ghost = True
                btn_quit.draw(screen, font_badge)

            if menu_status_msg and time.time() < menu_status_until:
                warn = font_small.render(menu_status_msg, True, WARNING_COLOR)
                screen.blit(warn, warn.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 90)))

        elif game_state == MODE_ENDGAME_DIFF:
            # 難度選擇頁
            section_title = section_label(endgame_active_section)
            title = font_menu.render(section_title, True, COLOR_TEXT)
            screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_HEADER_Y)))
            sub = font_small.render(t("pick_diff"), True, COLOR_TEXT_SECONDARY)
            screen.blit(sub, sub.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_LEGEND_Y)))
            tip2 = font_small.render(
                t("tip_challenge") if endgame_active_section == ENDGAME_SECTION_CHALLENGE else t("tip_formula"),
                True, COLOR_TEXT_SECONDARY,
            )
            screen.blit(tip2, tip2.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_LEGEND_Y + 28)))

            if btn_endgame_back:
                btn_endgame_back.update_hover(mouse_pos)
                btn_endgame_back.color = BUTTON_COLOR
                btn_endgame_back.hover_color = BUTTON_HOVER_COLOR
                btn_endgame_back.draw(screen, font_small)

            section_levels = endgame_levels_in_section()
            if not section_levels:
                msg = font.render(endgame_load_error or t("no_levels_section"), True, WARNING_COLOR)
                screen.blit(msg, msg.get_rect(center=(SCREEN_WIDTH // 2, (ENDGAME_LIST_TOP + ENDGAME_LIST_BOTTOM) // 2)))
            else:
                for btn, group in endgame_diff_buttons:
                    btn.update_hover(mouse_pos)
                    base, hover = group.get("color", (BUTTON_COLOR, BUTTON_HOVER_COLOR))
                    btn.color = base
                    btn.hover_color = hover
                    btn.draw(screen, font)

            count_text = font_small.render(
                t("section_total", section=section_title, n=len(section_levels)), True, COLOR_TEXT_SECONDARY
            )
            screen.blit(count_text, count_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 28)))

        elif game_state == MODE_ENDGAME_LEVELS:
            # 標題／說明／返回：固定上方，不與列表重疊
            section_title = section_label(endgame_active_section)
            group_label = diff_group_label(endgame_filter_group) if endgame_filter_group else t("level_label")
            title = font_menu.render(f"{section_title} · {group_label}", True, COLOR_TEXT)
            screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_HEADER_Y)))

            legend_lines = [t("legend1"), t("legend2")]
            for li, line in enumerate(legend_lines):
                sub = font_small.render(line, True, COLOR_TEXT_SECONDARY)
                screen.blit(sub, sub.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_LEGEND_Y + li * 26)))

            if btn_endgame_back:
                btn_endgame_back.update_hover(mouse_pos)
                btn_endgame_back.color = BUTTON_COLOR
                btn_endgame_back.hover_color = BUTTON_HOVER_COLOR
                btn_endgame_back.draw(screen, font_small)

            # 列表卡片
            list_h = endgame_list_viewport_height()
            list_bg = pygame.Rect(ENDGAME_LIST_LEFT - 10, ENDGAME_LIST_TOP - 8, ENDGAME_LIST_WIDTH + 20, list_h + 16)
            draw_card(screen, list_bg, fill=COLOR_CARD, radius=14, shadow=True)

            filtered = endgame_levels_for_group(endgame_filter_group)
            if not filtered:
                msg = font.render(t("no_levels_diff"), True, WARNING_COLOR)
                screen.blit(msg, msg.get_rect(center=(SCREEN_WIDTH // 2, (ENDGAME_LIST_TOP + ENDGAME_LIST_BOTTOM) // 2)))
            else:
                clip = pygame.Rect(ENDGAME_LIST_LEFT - 4, ENDGAME_LIST_TOP, ENDGAME_LIST_WIDTH + 8, list_h)
                screen.set_clip(clip)
                for btn, payload in endgame_level_buttons:
                    if btn.rect.bottom <= ENDGAME_LIST_TOP or btn.rect.top >= ENDGAME_LIST_BOTTOM:
                        continue
                    btn.update_hover(mouse_pos)
                    if payload == "locked":
                        btn.color = COLOR_CARD_ALT
                        btn.hover_color = blend_rgb(COLOR_CARD_ALT, COLOR_TEXT, 0.08)
                        btn.text_color = COLOR_TEXT_SECONDARY
                    else:
                        cleared = payload["id"] in endgame_cleared
                        btn.color = (198, 210, 196) if cleared else BUTTON_COLOR
                        btn.hover_color = (184, 198, 182) if cleared else BUTTON_HOVER_COLOR
                        btn.text_color = BUTTON_TEXT
                    btn.draw(screen, font_small)
                screen.set_clip(None)

                if endgame_list_scrollbar and endgame_list_max_scroll() > 0:
                    endgame_list_scrollbar.draw(screen)

            count_text = font_small.render(
                t("section_total", section=group_label, n=len(filtered)), True, COLOR_TEXT_SECONDARY
            )
            screen.blit(count_text, count_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 28)))

        elif game_state == MODE_EDITOR:
            # 頂部標題列
            pygame.draw.rect(screen, COLOR_UI_BAR, (0, 0, SCREEN_WIDTH, 56))
            title = font_ui.render(t("editor_title"), True, COLOR_TEXT_ON_DARK)
            screen.blit(title, (20, 10))
            hint = font_small.render(t("editor_palette") + "　|　" + t("editor_rmb"), True, COLOR_TEXT_ON_DARK)
            screen.blit(hint, (280, 18))

            # 棋盤
            if board_surface:
                screen.blit(board_surface, (MARGIN_X - 5, MARGIN_Y - 5))
            else:
                pygame.draw.rect(screen, COLOR_LINE, (MARGIN_X - 5, MARGIN_Y - 5, 8 * GRID_SIZE + 10, 9 * GRID_SIZE + 10), 4)
                for y in range(10):
                    pygame.draw.line(screen, COLOR_LINE, (MARGIN_X, MARGIN_Y + y * GRID_SIZE), (MARGIN_X + 8 * GRID_SIZE, MARGIN_Y + y * GRID_SIZE))
                for x in range(9):
                    pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + x * GRID_SIZE, MARGIN_Y), (MARGIN_X + x * GRID_SIZE, MARGIN_Y + 9 * GRID_SIZE))

            if board:
                for p in board.pieces:
                    # 盤上選取的棋高亮
                    if editor_board_pick is not None and p is editor_board_pick:
                        p.selected = True
                    else:
                        p.selected = False
                    draw_piece_with_assets(screen, p, font, RED, piece_sprites)

            # 調色盤
            for rect, item in editor_palette_rects():
                draw_card(screen, rect, fill=COLOR_CARD, radius=8, shadow=False, border_width=1)
                border_c = GOLD if editor_selected == item else COLOR_CARD_BORDER
                pygame.draw.rect(screen, border_c, rect, 2 if editor_selected != item else 3, border_radius=8)
                if isinstance(item, tuple):
                    name, color = item
                    ts = font_small.render(name, True, color)
                    screen.blit(ts, ts.get_rect(center=rect.center))

            # 右側按鈕
            for btn in (
                btn_editor_back, btn_editor_turn, btn_editor_erase,
                btn_editor_clear, btn_editor_initial, btn_editor_save,
                btn_editor_load,
            ):
                if not btn:
                    continue
                btn.update_hover(mouse_pos)
                btn.color = BUTTON_COLOR
                btn.hover_color = BUTTON_HOVER_COLOR
                if btn is btn_editor_erase and editor_selected == "erase":
                    btn.color = (210, 180, 150)
                    btn.hover_color = (200, 168, 138)
                btn.draw(screen, font_small)

            # 僅錯誤／儲存結果提示（自動換行）
            panel_x = MARGIN_X + BOARD_WIDTH + 24
            msg_y = MARGIN_Y + 320
            msg_w = SCREEN_WIDTH - panel_x - 24
            if editor_message:
                # 依寬度折行（約 14 字／行）
                chars_per_line = max(8, msg_w // 16)
                lines = []
                s = editor_message
                while s:
                    lines.append(s[:chars_per_line])
                    s = s[chars_per_line:]
                for li, line in enumerate(lines[:6]):
                    col = WARNING_COLOR if any(
                        k in editor_message for k in ("非法", "不能", "最多", "不合法", "失敗", "空白")
                    ) else COLOR_TEXT
                    screen.blit(font_small.render(line, True, col), (panel_x, msg_y + li * 24))

            side_hint = font_small.render(t("editor_side_hint"), True, COLOR_TEXT_SECONDARY)
            screen.blit(side_hint, (panel_x, SCREEN_HEIGHT - 40))

        elif game_state == MODE_EDITOR_LIB:
            title = font_menu.render(t("editor_lib_title"), True, COLOR_TEXT)
            screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_HEADER_Y)))
            sub = font_small.render(t("editor_lib_hint"), True, COLOR_TEXT_SECONDARY)
            screen.blit(sub, sub.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_LEGEND_Y)))

            if btn_lib_back:
                btn_lib_back.update_hover(mouse_pos)
                btn_lib_back.color = BUTTON_COLOR
                btn_lib_back.hover_color = BUTTON_HOVER_COLOR
                btn_lib_back.draw(screen, font_small)

            list_h = ENDGAME_LIST_BOTTOM - ENDGAME_LIST_TOP
            list_bg = pygame.Rect(ENDGAME_LIST_LEFT - 10, ENDGAME_LIST_TOP - 8, ENDGAME_LIST_WIDTH + 20, list_h + 16)
            draw_card(screen, list_bg, fill=COLOR_CARD, radius=14, shadow=True)

            if not editor_saved_list:
                msg = font.render(t("editor_no_saved"), True, WARNING_COLOR)
                screen.blit(msg, msg.get_rect(center=(SCREEN_WIDTH // 2, (ENDGAME_LIST_TOP + ENDGAME_LIST_BOTTOM) // 2)))
            else:
                for btn, pos in editor_lib_buttons:
                    btn.update_hover(mouse_pos)
                    if pos.get("id") == editor_lib_selected:
                        btn.color = (198, 210, 196)
                        btn.hover_color = (184, 198, 182)
                    else:
                        btn.color = BUTTON_COLOR
                        btn.hover_color = BUTTON_HOVER_COLOR
                    btn.draw(screen, font_small)

            for btn in (btn_lib_to_edit, btn_lib_pvp, btn_lib_ai, btn_lib_rename, btn_lib_delete):
                if not btn:
                    continue
                btn.update_hover(mouse_pos)
                btn.color = BUTTON_COLOR
                btn.hover_color = BUTTON_HOVER_COLOR
                if btn is btn_lib_delete:
                    btn.color = BUTTON_DANGER
                    btn.hover_color = BUTTON_DANGER_HOVER
                btn.draw(screen, font_small)

            if editor_message:
                # 底部訊息，簡短顯示
                mcol = WARNING_COLOR if "請" in editor_message or "失敗" in editor_message else SUCCESS_COLOR
                ms = font_small.render(editor_message, True, mcol)
                screen.blit(ms, ms.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 100)))

        elif game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
            # 繪製遊戲界面
            # 1. 頂欄（柔和深灰）
            pygame.draw.rect(screen, COLOR_UI_BAR, (0, 0, SCREEN_WIDTH, TOP_UI_HEIGHT))
            # 底緣細線
            pygame.draw.line(screen, blend_rgb(COLOR_UI_BAR, GOLD, 0.25), (0, TOP_UI_HEIGHT - 1), (SCREEN_WIDTH, TOP_UI_HEIGHT - 1), 1)

            turn_str = t("red_turn") if board.turn == RED else t("black_turn")
            color = RED if board.turn == RED else COLOR_TEXT_ON_DARK
            screen.blit(font_ui.render(turn_str, True, color), (20, 12))

            if game_state == MODE_PVP:
                mode_text = t("mode_pvp")
            elif game_state == MODE_ENDGAME and endgame_current:
                max_m = endgame_current.get("max_player_moves")
                limit = f"{endgame_player_moves}/{max_m}" if max_m is not None else f"{endgame_player_moves}"
                status_tag = {
                    "cleared": t("status_cleared"),
                    "failed": t("status_failed"),
                }.get(endgame_status, t("status_playing"))
                mode_text = t(
                    "endgame_hud",
                    title=endgame_current["title"],
                    limit=limit,
                    status=status_tag,
                )
            else:
                mode_text = t(
                    "mode_ai_line",
                    you=t("side_red") if player_color == RED else t("side_black"),
                    ai=t("side_red") if ai_color == RED else t("side_black"),
                    level=ai_difficulty_display(ai_difficulty),
                )
            screen.blit(font_small.render(mode_text, True, COLOR_TEXT_ON_DARK), (20, 52))

            # 棋鐘顯示（雙人／人機）
            if clock_enabled and game_state in (MODE_PVP, MODE_AI):
                red_clk = format_clock_ms(clock_red_ms)
                black_clk = format_clock_ms(clock_black_ms)
                # 上方為對方（視角翻轉時對調標籤）
                top_is_black = view_color == RED
                top_label = t("side_black") if top_is_black else t("side_red")
                bot_label = t("side_red") if top_is_black else t("side_black")
                top_ms = clock_black_ms if top_is_black else clock_red_ms
                bot_ms = clock_red_ms if top_is_black else clock_black_ms
                top_txt = f"{top_label} {format_clock_ms(top_ms)}"
                bot_txt = f"{bot_label} {format_clock_ms(bot_ms)}"
                active_top = (board.turn == BLACK and top_is_black) or (board.turn == RED and not top_is_black)
                c_top = GOLD if active_top else COLOR_TEXT_SECONDARY
                c_bot = GOLD if not active_top else COLOR_TEXT_SECONDARY
                screen.blit(font_small.render(top_txt, True, c_top), (MARGIN_X, TOP_UI_HEIGHT + 4))
                screen.blit(
                    font_small.render(bot_txt, True, c_bot),
                    (MARGIN_X, MARGIN_Y + BOARD_HEIGHT + 8),
                )

            eval_x = 730
            if suggest_enabled:
                screen.blit(font_small.render(t("suggest_header"), True, COLOR_TEXT_ON_DARK), (eval_x, 10))
                sugg_text = t("suggest_move", move=suggest_move) if suggest_move else t("suggest_none")
                screen.blit(font_small.render(sugg_text, True, COLOR_TEXT_ON_DARK), (eval_x, 44))
                screen.blit(font_small.render(t("eval_line", score=eval_text), True, GOLD), (eval_x, 76))
            else:
                screen.blit(font_small.render(t("suggest_off"), True, COLOR_TEXT_SECONDARY), (eval_x, 44))
            
            # 狀態顯示 (將軍 / 勝利 / 正常)
            if replay_mode_active:
                if replay_finished_winner:
                    status = t("win_red") if replay_finished_winner == RED else t("win_black")
                    screen.blit(font.render(status, True, GOLD), (250, 10))
                elif replay_finished_draw_reason:
                    draw_text = font.render(str(replay_finished_draw_reason), True, WARNING_COLOR)
                    screen.blit(draw_text, (250, 10))
            elif board.winner:
                status = t("win_red") if board.winner == RED else t("win_black")
                screen.blit(font_ui.render(status, True, GOLD), (250, 10))
            elif board.draw_reason:
                # 顯示和棋原因
                draw_text = font.render(board.draw_reason, True, WARNING_COLOR)
                screen.blit(draw_text, (250, 10))
            elif board.is_check:
                # 顯示閃爍的將軍文字
                if int(time.time() * 2) % 2 == 0: # 簡單的閃爍效果
                    screen.blit(font_warn.render(t("check"), True, GOLD), (250, 10))

            if replay_mode_active:
                rv_text = font_small.render(t("replay"), True, GOLD)
                screen.blit(rv_text, (20, 92))
            elif board.winner or board.draw_reason:
                rv_text = font_small.render(t("replay"), True, GOLD)
                screen.blit(rv_text, (20, 92))
            
            # 頂欄醒目提示（存檔／違規等）— 加大字體並置於頂欄中上方，避免貼底看不清
            if board.warning_msg and time.time() - board.warning_timer < 2.8:
                warn_text = font_banner.render(board.warning_msg, True, (255, 92, 82))
                # 頂欄垂直約 1/3 處，不貼底線
                text_rect = warn_text.get_rect(center=(SCREEN_WIDTH // 2, 46))
                # 半透明底條提升對比
                pad_x, pad_y = 18, 8
                bg = pygame.Rect(
                    text_rect.x - pad_x,
                    text_rect.y - pad_y,
                    text_rect.width + pad_x * 2,
                    text_rect.height + pad_y * 2,
                )
                # 限制不超出頂欄
                if bg.bottom > TOP_UI_HEIGHT - 4:
                    bg.bottom = TOP_UI_HEIGHT - 4
                    text_rect.centery = bg.centery
                if bg.top < 4:
                    bg.top = 4
                    text_rect.centery = bg.centery
                shadow = pygame.Surface((bg.width, bg.height), pygame.SRCALPHA)
                shadow.fill((20, 14, 12, 210))
                screen.blit(shadow, bg.topleft)
                pygame.draw.rect(screen, (120, 50, 44), bg, 1, border_radius=8)
                screen.blit(warn_text, text_rect)

            # 2. 繪製棋盤
            if board_surface:
                # 執黑時翻轉棋盤圖，與棋子視角一致（楚河漢界也會對調）
                draw_board = board_surface
                if board_from_asset and view_color == BLACK:
                    draw_board = pygame.transform.flip(board_surface, True, True)
                screen.blit(draw_board, (MARGIN_X - 5, MARGIN_Y - 5))

            if board_from_asset:
                # 素材棋盤已含精確 9x10 格線／九宮／楚河漢界；不再疊加外框以免錯位感
                pass
            else:
                pygame.draw.rect(screen, COLOR_LINE, (MARGIN_X - 5, MARGIN_Y - 5, 8 * GRID_SIZE + 10, 9 * GRID_SIZE + 10), 4)
                for y in range(10):
                    pygame.draw.line(screen, COLOR_LINE, (MARGIN_X, MARGIN_Y + y * GRID_SIZE), (MARGIN_X + 8 * GRID_SIZE, MARGIN_Y + y * GRID_SIZE))
                for x in range(9):
                    if x == 0 or x == 8:
                        pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + x * GRID_SIZE, MARGIN_Y), (MARGIN_X + x * GRID_SIZE, MARGIN_Y + 9 * GRID_SIZE))
                    else:
                        pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + x * GRID_SIZE, MARGIN_Y), (MARGIN_X + x * GRID_SIZE, MARGIN_Y + 4 * GRID_SIZE))
                        pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + x * GRID_SIZE, MARGIN_Y + 5 * GRID_SIZE), (MARGIN_X + x * GRID_SIZE, MARGIN_Y + 9 * GRID_SIZE))
                # 九宮格
                pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + 3*GRID_SIZE, MARGIN_Y + 7*GRID_SIZE), (MARGIN_X + 5*GRID_SIZE, MARGIN_Y + 9*GRID_SIZE))
                pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + 5*GRID_SIZE, MARGIN_Y + 7*GRID_SIZE), (MARGIN_X + 3*GRID_SIZE, MARGIN_Y + 9*GRID_SIZE))
                pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + 3*GRID_SIZE, MARGIN_Y), (MARGIN_X + 5*GRID_SIZE, MARGIN_Y + 2*GRID_SIZE))
                pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + 5*GRID_SIZE, MARGIN_Y), (MARGIN_X + 3*GRID_SIZE, MARGIN_Y + 2*GRID_SIZE))

                font_river = pygame.font.SysFont(font_names, 40)
                left_river = t("river_left") if view_color == RED else t("river_right")
                right_river = t("river_right") if view_color == RED else t("river_left")
                screen.blit(font_river.render(left_river, True, COLOR_LINE), (MARGIN_X + 1.5 * GRID_SIZE, MARGIN_Y + 4.2 * GRID_SIZE))
                screen.blit(font_river.render(right_river, True, COLOR_LINE), (MARGIN_X + 5.5 * GRID_SIZE, MARGIN_Y + 4.2 * GRID_SIZE))

            # 3. 繪製移動歷史（加寬面板 + 變例多行中文）
            history_panel_x, history_panel_y, history_panel_width, history_panel_height, clip_rect = get_history_panel_rects()
            history_rect = pygame.Rect(history_panel_x, history_panel_y, history_panel_width, history_panel_height)
            draw_card(screen, history_rect, fill=COLOR_CARD, radius=12, shadow=True)

            # 標題
            title_text = font_small.render(t("move_log"), True, COLOR_TEXT)
            screen.blit(title_text, (history_panel_x + 14, history_panel_y + 10))
            pygame.draw.line(
                screen, COLOR_CARD_BORDER,
                (history_panel_x + 12, history_panel_y + 36),
                (history_panel_x + history_panel_width - 14, history_panel_y + 36),
                1,
            )

            notation_list = get_display_notation_list()
            row_heights, content_h, pv_map = get_history_row_heights(font_badge)
            max_scroll = get_history_max_scroll()
            if history_scroll:
                history_scroll.content_height = max(clip_rect.height + 1, content_h + 12)
                # 滾動條貼在記錄面板右側
                history_scroll.rect.x = history_panel_x + history_panel_width - 18
                history_scroll.rect.y = clip_rect.y
                history_scroll.rect.height = clip_rect.height
                history_scroll.thumb_height = max(
                    20, int(clip_rect.height * clip_rect.height / max(1, history_scroll.content_height))
                )

            screen.set_clip(clip_rect)
            scroll_offset = history_scroll.scroll_offset if history_scroll else 0
            y_offset = clip_rect.y - scroll_offset

            for i, notation in enumerate(notation_list):
                row_h = row_heights[i] if i < len(row_heights) else HISTORY_LINE_H
                # 超出可視區則略過繪製（仍推進 y）
                row_bottom = y_offset + row_h
                if row_bottom >= clip_rect.y and y_offset <= clip_rect.bottom:
                    if replay_mode_active and replay_index == i + 1:
                        hl = pygame.Rect(
                            clip_rect.x + 2, y_offset, clip_rect.width - 4, max(HISTORY_LINE_H, row_h - 2)
                        )
                        pygame.draw.rect(screen, (236, 228, 210), hl, border_radius=6)

                    move_color = RED if i % 2 == 0 else COLOR_TEXT
                    tag = ""
                    tag_color = move_color
                    if i < len(analysis_results) and analysis_results[i]:
                        ar = analysis_results[i]
                        tag = f" [{analysis_label_text(ar['label'])} Δ{ar['cp_loss']}]"
                        tag_color = analysis_label_color(ar["label"])

                    move_text = font_small.render(f"{i+1}. {notation}", True, move_color)
                    screen.blit(move_text, (clip_rect.x + 6, y_offset + 2))
                    if tag:
                        tag_surf = font_small.render(tag, True, tag_color)
                        tx = clip_rect.x + 6 + move_text.get_width()
                        # 標籤過寬則折到下一視覺區仍畫在同行右側裁切內
                        if tx + tag_surf.get_width() < clip_rect.right - 4:
                            screen.blit(tag_surf, (tx, y_offset + 2))
                        else:
                            # 改畫較短標籤
                            short = font_badge.render(
                                f"[{analysis_label_text(analysis_results[i]['label'])}]", True, tag_color
                            )
                            screen.blit(short, (clip_rect.x + 6, y_offset + 2 + 16))

                    # 變例：多行完整顯示（中文棋譜）
                    if i in pv_map:
                        pv_y = y_offset + HISTORY_LINE_H + 2
                        for li, line in enumerate(pv_map[i]):
                            col = COLOR_PRIMARY if li == 0 else COLOR_TEXT_SECONDARY
                            pv_surf = font_badge.render(line, True, col)
                            screen.blit(pv_surf, (clip_rect.x + 10, pv_y))
                            pv_y += HISTORY_PV_LINE_H

                y_offset += row_h

            screen.set_clip(None)

            if history_scroll and max_scroll > 0:
                history_scroll.draw(screen)

            # 4. 繪製棋子
            for p in board.pieces:
                draw_piece_with_assets(screen, p, font, view_color, piece_sprites)

            # 5. 繪製建議著法高亮
            if suggest_enabled and suggest_move and len(suggest_move) >= 4:
                src = ucci_to_board(suggest_move[:2])
                dst = ucci_to_board(suggest_move[2:4])
                if src and dst:
                    svx, svy = board_to_view_coords(src[0], src[1])
                    dvx, dvy = board_to_view_coords(dst[0], dst[1])
                    sx = MARGIN_X + svx * GRID_SIZE
                    sy = MARGIN_Y + svy * GRID_SIZE
                    dx = MARGIN_X + dvx * GRID_SIZE
                    dy = MARGIN_Y + dvy * GRID_SIZE
                    pygame.draw.circle(screen, (40, 170, 255), (sx, sy), GRID_SIZE // 2 + 6, 3)
                    pygame.draw.circle(screen, (255, 180, 40), (dx, dy), GRID_SIZE // 2 + 6, 3)
                    pygame.draw.line(screen, (255, 180, 40), (sx, sy), (dx, dy), 3)

            # 6. 底部按鈕：依目前可見項重新等距排版，再繪製
            finished = bool(board.winner or board.draw_reason)
            if game_state == MODE_ENDGAME:
                layout_bottom_bar([
                    (btn_endgame_retry, 120),
                    (btn_undo if not endgame_status else None, 140),
                    (btn_main_menu, 160),
                    (btn_endgame_levels, 160),
                ])
            else:
                layout_bottom_bar([
                    (btn_save_game if not finished else None, 110),
                    (btn_load_game if not finished else None, 110),
                    (btn_suggest_toggle if not finished else None, 200),
                    (btn_undo if not finished else None, 140),
                    (btn_main_menu, 160),
                ])

            def _draw_bottom_btn(btn):
                if not btn:
                    return
                btn.text_color = BUTTON_TEXT
                btn.border_color = BUTTON_BORDER
                btn.color = BUTTON_COLOR
                btn.hover_color = BUTTON_HOVER_COLOR
                btn.update_hover(mouse_pos)
                btn.draw(screen, font_small)

            if game_state == MODE_ENDGAME:
                _draw_bottom_btn(btn_endgame_retry)
                if not endgame_status:
                    _draw_bottom_btn(btn_undo)
                _draw_bottom_btn(btn_main_menu)
                _draw_bottom_btn(btn_endgame_levels)
            else:
                if not finished:
                    _draw_bottom_btn(btn_save_game)
                    _draw_bottom_btn(btn_load_game)
                    _draw_bottom_btn(btn_suggest_toggle)
                    _draw_bottom_btn(btn_undo)
                _draw_bottom_btn(btn_main_menu)

            # 右側功能鈕（非底部列）
            if btn_draw_offer and not finished and not replay_mode_active:
                btn_draw_offer.update_hover(mouse_pos)
                btn_draw_offer.text_color = BUTTON_TEXT
                btn_draw_offer.draw(screen, font_small)

            if btn_replay_mode and (finished or replay_mode_active):
                btn_replay_mode.update_hover(mouse_pos)
                btn_replay_mode.text_color = BUTTON_TEXT
                btn_replay_mode.draw(screen, font_small)

            if btn_analyze and game_state in (MODE_PVP, MODE_AI):
                if analysis_status == "running":
                    btn_analyze.text = t("analyzing", cur=analysis_progress, total=max(1, analysis_total))
                elif analysis_status == "done":
                    btn_analyze.text = t("analyze_done")
                else:
                    btn_analyze.text = t("analyze")
                btn_analyze.update_hover(mouse_pos)
                btn_analyze.text_color = BUTTON_TEXT
                btn_analyze.draw(screen, font_small)

            if btn_difficulty and game_state == MODE_AI:
                btn_difficulty.text = t("ai_difficulty", level=ai_difficulty_display(ai_difficulty))
                btn_difficulty.update_hover(mouse_pos)
                btn_difficulty.text_color = BUTTON_TEXT
                btn_difficulty.draw(screen, font_small)

            if game_state == MODE_ENDGAME:
                pass  # 重來／關卡列表已在底部列繪製
                if endgame_status == "cleared":
                    banner = font_ui.render(t("pass"), True, GOLD)
                    screen.blit(banner, banner.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40)))
                elif endgame_status == "failed":
                    banner = font_ui.render(t("fail_banner"), True, WARNING_COLOR)
                    screen.blit(banner, banner.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40)))

            if draw_offer_popup and btn_draw_accept and btn_draw_reject:
                overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                overlay.fill((40, 36, 32, 100))
                screen.blit(overlay, (0, 0))
                popup_rect = pygame.Rect(SCREEN_WIDTH // 2 - 220, SCREEN_HEIGHT // 2 - 110, 440, 220)
                draw_card(screen, popup_rect, fill=COLOR_CARD, radius=16, shadow=True, border_width=1)
                requester = t("side_red") if draw_offer_popup["from_color"] == RED else t("side_black")
                msg = font.render(t("msg_draw_popup", who=requester), True, COLOR_TEXT)
                msg_rect = msg.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 25))
                screen.blit(msg, msg_rect)
                btn_draw_accept.update_hover(mouse_pos)
                btn_draw_reject.update_hover(mouse_pos)
                btn_draw_accept.draw(screen, font_small)
                btn_draw_reject.draw(screen, font_small)

        window.fill(COLOR_BG)
        if render_rect.size == (SCREEN_WIDTH, SCREEN_HEIGHT):
            window.blit(screen, render_rect.topleft)
        else:
            scaled_frame = pygame.transform.smoothscale(screen, render_rect.size)
            window.blit(scaled_frame, render_rect.topleft)
        pygame.display.flip()
        clock.tick(30)

if __name__ == "__main__":
    main()
