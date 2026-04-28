import pygame
import sys
import time
import os
import subprocess
import threading
import queue
import math
import random
import json


def get_runtime_search_dirs():
    dirs = []

    def add(path):
        if path and path not in dirs:
            dirs.append(path)

    module_dir = os.path.dirname(os.path.abspath(__file__))
    add(module_dir)

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        add(exe_dir)
        add(os.path.join(exe_dir, "_internal"))

    add(getattr(sys, "_MEIPASS", ""))
    return dirs


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

MARGIN_X = (SCREEN_WIDTH - BOARD_WIDTH) // 2
MARGIN_Y = (SCREEN_HEIGHT - BOARD_HEIGHT) // 2 + 40

# 顏色定義
COLOR_BG = (235, 205, 155)
COLOR_UI_BAR = (60, 40, 20)
COLOR_LINE = (0, 0, 0)
COLOR_SELECTED = (0, 200, 0)
RED = (200, 20, 20)
BLACK = (20, 20, 20)
WHITE = (255, 255, 255)
GOLD = (255, 215, 0)
WARNING_COLOR = (255, 50, 50) # 紅色警告字
BUTTON_COLOR = (100, 150, 255)
BUTTON_HOVER_COLOR = (150, 200, 255)

# 遊戲模式
MODE_MENU = 0          # 選擇遊戲模式菜單
MODE_PVP = 1           # 玩家對玩家
MODE_AI = 2            # 玩家對 AI

# AI 相關設定
AI_MOVETIME_MS = 700
AI_DELAY_SEC = 1.0
AI_EVAL_MOVETIME_MS = 250
AI_SUGGEST_MOVETIME_MS = 350
AI_INFINITE_SEARCH_MAX_WAIT_SEC = 2.0
UCCI_FILES = "abcdefghi"
SAVE_FILE_NAME = "savegame.json"

AI_DIFFICULTY_PRESETS = {
    "簡單": {"depth": 3, "movetime_ms": 50, "mistake_rate": 0.45},
    "中等": {"depth": 6, "movetime_ms": 150, "mistake_rate": 0.15},
    "困難": {"depth": None, "movetime_ms": 500, "mistake_rate": 0.03},
}

PIECE_TO_FEN = {
    ('車', RED): 'R', ('馬', RED): 'N', ('相', RED): 'B', ('仕', RED): 'A', ('帥', RED): 'K', ('炮', RED): 'C', ('包', RED): 'C', ('兵', RED): 'P',
    ('車', BLACK): 'r', ('馬', BLACK): 'n', ('象', BLACK): 'b', ('士', BLACK): 'a', ('將', BLACK): 'k', ('包', BLACK): 'c', ('炮', BLACK): 'c', ('卒', BLACK): 'p',
}

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
    # 陰影
    pygame.draw.circle(sprite, (95, 75, 55, 150), (center + 2, center + 2), radius - 1)
    # 棋子底
    pygame.draw.circle(sprite, (242, 224, 188), (center, center), radius - 1)
    # 外框
    pygame.draw.circle(sprite, piece_color, (center, center), radius - 1, 3)

    # 內圓紋理
    pygame.draw.circle(sprite, (210, 188, 150, 120), (center, center), radius - 7, 1)
    pygame.draw.circle(sprite, (200, 176, 135, 90), (center, center), radius - 10, 1)

    font = pygame.font.SysFont(font_names, 30, bold=True)
    text = font.render(piece_name, True, piece_color)
    text_rect = text.get_rect(center=(center, center))
    sprite.blit(text, text_rect)
    return sprite


def load_visual_assets(font_names):
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
                break
            except Exception:
                board_surface = None

    if board_surface is None:
        board_surface = create_generated_board_surface()

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
                        sprite = pygame.transform.smoothscale(raw, (GRID_SIZE, GRID_SIZE))
                        break
                    except Exception:
                        sprite = None

        if sprite is None:
            sprite = create_generated_piece_sprite(piece_name, piece_color, font_names)
        piece_sprites[key] = sprite

    return board_surface, piece_sprites


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
    def __init__(self, game_mode=MODE_PVP):
        self.pieces = []
        self.turn = RED
        self.selected_piece = None
        self.winner = None
        self.game_mode = game_mode  # 遊戲模式（PvP 或 AI）
        
        # 狀態訊息
        self.is_check = False      # 是否正在將軍
        self.warning_msg = ""      # 違規提示訊息 (例如：不能送將)
        self.warning_timer = 0     # 訊息顯示計時器
        
        # 悔棋功能：存儲移動歷史
        self.move_history = []     # 儲存所有移動: (piece, old_x, old_y, captured_piece)
        self.move_ucci_history = []  # 儲存 UCCI 走步，用於存檔/重播
        self.move_notation = []    # 儲存中文記譜: ["兵三進一", "炮8平7", ...]
        self.move_is_check = []    # 記錄每步移動後是否造成將軍
        self.move_is_capture = []  # 記錄每步是否吃子
        self.move_is_rootless_capture = []  # 記錄每步是否為無根吃子（被吃子無防守者）
        self.move_piece_id = []    # 記錄每步移動是由哪一個棋子進行的（棋子ID）
        self.move_is_chase = []    # 記錄每步是否形成「捉」（威脅無根子）
        self.move_chase_targets = [] # 記錄每步被捉目標集合（用於長捉判定）
        self.move_signature = []   # 記錄每步移動簽名（用於重複著法判和）
        self.move_repeat_state = [] # 記錄每步是否有寫入重複局面計數（供悔棋回滾）
        
        # 長將/長捉檢測
        self.draw_reason = ""  # 和棋原因
        
        # 重複局面檢測：記錄每步後的棋盤狀態及出現次數
        self.board_state_history = {}  # {狀態字符串: 出現次數}
        # 調試開關（臨時）：啟用後會印日誌以協助定位長捉問題
        self.debug = False
        
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

    def get_piece_at(self, x, y):
        for p in self.pieces:
            if p.x == x and p.y == y: return p
        return None

    def get_king(self, color):
        target_name = '帥' if color == RED else '將'
        for p in self.pieces:
            if p.name == target_name: return p
        return None

    def move_piece(self, piece, target_x, target_y):
        """ 嘗試移動棋子：包含所有規則檢查 """
        target_piece = self.get_piece_at(target_x, target_y)
        
        # --- 1. 備份當前狀態 (Snapshot) ---
        original_x, original_y = piece.x, piece.y
        removed_piece = target_piece
        
        # --- 2. 執行虛擬移動 ---
        piece.x = target_x
        piece.y = target_y
        if target_piece:
            self.pieces.remove(target_piece)
            
        # --- 3. 安全檢查 (Security Check) ---
        # 檢查 A: 是否導致飛將 (Kings Facing)
        if self.is_kings_facing():
            self.undo_move(piece, original_x, original_y, removed_piece)
            self.set_warning("移動無效：將帥不可照面")
            return False

        # 檢查 B: 移動後自己是否仍被將軍 (自殺/沒解將)
        if self.is_under_attack(piece.color):
            self.undo_move(piece, original_x, original_y, removed_piece)
            self.set_warning("移動無效：不可送將！")
            return False

        # --- 4. 確認移動有效 ---
        piece.selected = False
        self.selected_piece = None
        self.warning_msg = "" # 清除錯誤訊息
        
        # 記錄移動歷史（用於悔棋）
        self.move_history.append((piece, original_x, original_y, removed_piece))
        self.move_ucci_history.append(board_to_ucci(original_x, original_y) + board_to_ucci(target_x, target_y))
        
        # 生成並記錄中文記譜
        notation = self.generate_move_notation(piece, original_x, original_y, target_x, target_y)
        self.move_notation.append(notation)
        
        # 記錄本步是否吃子
        is_capture = removed_piece is not None
        # 判斷是否為無根吃子（被吃的棋子在當時沒有任何合法防守者能吃回）
        is_rootless = False
        if is_capture:
            defended = False
            # 檢查被吃方是否有任何棋子能合法地吃回新位置上的棋子
            if self.debug:
                print(f"[DEBUG] Checking defenders for {piece.name} at ({piece.x},{piece.y}) against {removed_piece.name}")
            for p in self.pieces:
                if p.color == removed_piece.color:
                    # 先檢查 p 能否合法移動到目標位置（吃掉 piece）
                    # 此時 p 仍在原位，piece 已在目標位置
                    if not self.is_valid_move(p, piece.x, piece.y, check_simulation=True):
                        if self.debug:
                            print(f"[DEBUG]   {p.name} at ({p.x},{p.y}): invalid move")
                        continue
                    
                    # 虛擬執行吃子：檢查 p 吃掉 piece 後是否會導致自己被將軍
                    original_px, original_py = p.x, p.y
                    p.x = piece.x
                    p.y = piece.y
                    
                    # 檢查是否導致自方被將軍（送將規則）
                    is_safe = not self.is_under_attack(p.color)
                    
                    # 還原狀態
                    p.x = original_px
                    p.y = original_py
                    
                    if is_safe:
                        defended = True
                        if self.debug:
                            print(f"[DEBUG]   {p.name} at ({original_px},{original_py}): CAN defend (safe)")
                        break
                    else:
                        if self.debug:
                            print(f"[DEBUG]   {p.name} at ({original_px},{original_py}): invalid (would be attacked)")
            is_rootless = not defended
        self.move_is_capture.append(is_capture)
        self.move_is_rootless_capture.append(is_rootless)
        if self.debug and is_capture:
            print(f"[DEBUG] capture by {piece.name} id={id(piece)} at ({piece.x},{piece.y}) - is_rootless={is_rootless}")
        
        # 檢查是否吃掉對方將帥 (理論上上面檢查B會擋住，除非對方無路可走)
        if target_piece and target_piece.name in ('帥', '將'):
            self.winner = piece.color

        # 切換回合
        next_turn = BLACK if self.turn == RED else RED
        self.turn = next_turn
        
        # --- 5. 檢查對手是否被將軍 ---
        is_check = self.is_under_attack(next_turn)
        if is_check:
            self.is_check = True
        else:
            self.is_check = False
        
        # 記錄本步是否造成將軍
        self.move_is_check.append(is_check)
        
        # 記錄本步移動是由哪一個棋子進行的（用 id(piece) 唯一識別）
        self.move_piece_id.append(id(piece))
        self.move_signature.append(self.get_move_signature(piece, original_x, original_y, target_x, target_y))

        # 「捉」：本步移動後，該棋子是否威脅到至少一個無根子
        chase_targets = self.get_rootless_threat_targets(piece)
        self.move_is_chase.append(len(chase_targets) > 0)
        self.move_chase_targets.append(chase_targets)
        
        # --- 6. 檢查長將（同一棋子連續5次出手都造成將軍） ---
        if len(self.move_piece_id) >= 5:
            piece_recent_indices = []
            for i in range(len(self.move_piece_id) - 1, -1, -1):
                if self.move_piece_id[i] == id(piece):
                    piece_recent_indices.append(i)
                    if len(piece_recent_indices) == 5:
                        break

            if len(piece_recent_indices) == 5:
                piece_recent_indices.reverse()
                is_consecutive = all(piece_recent_indices[j] - piece_recent_indices[j - 1] == 2 for j in range(1, 5))
                if is_consecutive and all(self.move_is_check[idx] for idx in piece_recent_indices):
                    self.draw_reason = "長將（同一棋子連續5次將軍），執行方輸掉"
                    self.winner = next_turn  # next_turn 是對手，對手贏
                    if self.debug:
                        print(f"[DEBUG] LONG-CHECK by piece id={id(piece)} indices={piece_recent_indices}")
        
        # --- 7. 檢查長捉（同一棋子連續5次出手都在捉同一組無根子） ---
        if len(self.move_piece_id) >= 5 and not self.draw_reason:
            piece_recent_indices = []
            for i in range(len(self.move_piece_id) - 1, -1, -1):
                if self.move_piece_id[i] == id(piece):
                    piece_recent_indices.append(i)
                    if len(piece_recent_indices) == 5:
                        break

            if len(piece_recent_indices) == 5:
                piece_recent_indices.reverse()
                is_consecutive = all(piece_recent_indices[j] - piece_recent_indices[j - 1] == 2 for j in range(1, 5))
                if is_consecutive:
                    first_targets = self.move_chase_targets[piece_recent_indices[0]]
                    all_chase = all(self.move_is_chase[idx] for idx in piece_recent_indices)
                    same_targets = all(self.move_chase_targets[idx] == first_targets for idx in piece_recent_indices)
                    if all_chase and first_targets and same_targets:
                        self.draw_reason = "長捉（同一棋子連續5次捉同一無根子），執行方輸掉"
                        self.winner = next_turn  # next_turn 是對手，對手贏
                        if self.debug:
                            print(f"[DEBUG] LONG-CAPTURE by piece id={id(piece)} targets={first_targets}")
        
        # --- 8. 檢查無可過河判和（雙方都沒有過河子力） ---
        if not self.draw_reason:
            red_has_crossing = self.has_crossing_piece(RED)
            black_has_crossing = self.has_crossing_piece(BLACK)
            if not red_has_crossing and not black_has_crossing:
                # 雙方都沒有過河子力，判和
                self.draw_reason = "無可過河，判和"
                self.winner = None
        
        # --- 9A. 檢查重複著法（雙方各5手，共10步） ---
        if not self.draw_reason and self.check_repeated_steps_draw():
            self.draw_reason = "重複著法（雙方各5手，共10步），判和"
            self.winner = None

        # --- 9B. 檢查重複局面判和（優先級較低） ---
        # 只有在沒有長將/長捉/無可過河/重複著法的情況下，才檢查重複局面
        repeat_state_key = None
        if not self.draw_reason:
            # 記錄當前棋盤狀態並檢查是否重複出現5次以上
            repeat_count = self.check_repeat_position()
            repeat_state_key = self.get_board_state()
            if repeat_count >= 5:
                # 同一局面出現5次，判和
                self.draw_reason = "重複局面（出現5次），判和"
                self.winner = None
        
        # --- 10. 檢查對手是否無路可走（困地） ---
        if not self.draw_reason and not self.has_valid_move(next_turn):
            # 對手無路可走，當前玩家獲勝
            self.winner = piece.color

        # 無論是否觸發和棋/勝負，都記錄這步是否更新過重複局面計數
        self.move_repeat_state.append(repeat_state_key)
            
        return True

    def undo_move(self, piece, old_x, old_y, removed_piece):
        """ 還原移動 """
        piece.x = old_x
        piece.y = old_y
        if removed_piece:
            self.pieces.append(removed_piece)

    def is_under_attack(self, color):
        """ 檢查指定顏色的將帥是否正受到攻擊 """
        king = self.get_king(color)
        if not king: return False # 沒王了(已輸)

        # 檢查敵方所有棋子，看有沒有任何一個能吃到王
        enemy_color = BLACK if color == RED else RED
        for p in self.pieces:
            if p.color == enemy_color:
                # 這裡很關鍵：我們檢查敵方棋子 p 能不能移動到 king 的位置
                if self.is_valid_move(p, king.x, king.y, check_simulation=True):
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
        檢查是否出現重複局面
        象棋規則：同一局面出現5次則判和
        返回重複次數
        """
        current_state = self.get_board_state()
        
        # 記錄當前狀態
        if current_state in self.board_state_history:
            self.board_state_history[current_state] += 1
        else:
            self.board_state_history[current_state] = 1
        
        return self.board_state_history[current_state]
    
    def has_valid_move(self, color):
        """檢查指定顏色的玩家是否還有有效的移動"""
        for piece in self.pieces:
            if piece.color == color:
                # 嘗試移動到棋盤上所有可能的位置
                for tx in range(9):
                    for ty in range(10):
                        if self.is_valid_move(piece, tx, ty, check_simulation=True):
                            # 檢查這個移動是否會導致自己被將軍（模擬移動）
                            target = self.get_piece_at(tx, ty)
                            original_x, original_y = piece.x, piece.y
                            
                            piece.x = tx
                            piece.y = ty
                            if target:
                                self.pieces.remove(target)
                            
                            is_safe = (not self.is_under_attack(color)) and (not self.is_kings_facing())
                            
                            # 還原
                            piece.x = original_x
                            piece.y = original_y
                            if target:
                                self.pieces.append(target)
                            
                            if is_safe:
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
        """雙方各連續重複 5 手（共 10 步）時判和。"""
        if len(self.move_signature) < 10:
            return False
        recent = self.move_signature[-10:]
        for i in range(4, 10):
            if recent[i] != recent[i - 4]:
                return False
        return True

    def get_rootless_threat_targets(self, attacker):
        """找出 attacker 當前可捉（可吃且無根）的敵方棋子集合。"""
        enemy_color = BLACK if attacker.color == RED else RED
        targets = []

        for target in list(self.pieces):
            if target.color != enemy_color:
                continue
            if target.name in ('帥', '將'):
                continue

            if not self.is_valid_move(attacker, target.x, target.y, check_simulation=True):
                continue

            original_ax, original_ay = attacker.x, attacker.y
            self.pieces.remove(target)
            attacker.x, attacker.y = target.x, target.y

            legal_capture = (not self.is_under_attack(attacker.color)) and (not self.is_kings_facing())
            defended = False

            if legal_capture:
                for defender in self.pieces:
                    if defender.color != enemy_color:
                        continue
                    if not self.is_valid_move(defender, attacker.x, attacker.y, check_simulation=True):
                        continue

                    original_dx, original_dy = defender.x, defender.y
                    defender.x, defender.y = attacker.x, attacker.y
                    safe_recap = (not self.is_under_attack(defender.color)) and (not self.is_kings_facing())
                    defender.x, defender.y = original_dx, original_dy

                    if safe_recap:
                        defended = True
                        break

            attacker.x, attacker.y = original_ax, original_ay
            self.pieces.append(target)

            if legal_capture and not defended:
                targets.append(id(target))

        targets.sort()
        return tuple(targets)
    
    def undo_last_move(self):
        """撤銷上一步移動（悔棋）"""
        if not self.move_history:
            self.set_warning("沒有可悔棋的移動！")
            return False
        
        # 如果遊戲已結束，重置贏家狀態
        self.winner = None
        self.draw_reason = ""
        
        # 取出最後一步移動
        piece, old_x, old_y, captured_piece = self.move_history.pop()
        
        # 同時刪除對應的記譜和狀態記錄
        if self.move_notation:
            self.move_notation.pop()
        if self.move_ucci_history:
            self.move_ucci_history.pop()
        if self.move_is_check:
            self.move_is_check.pop()
        if self.move_is_capture:
            self.move_is_capture.pop()
        if self.move_is_rootless_capture:
            self.move_is_rootless_capture.pop()
        if self.move_is_chase:
            self.move_is_chase.pop()
        if self.move_chase_targets:
            self.move_chase_targets.pop()
        if self.move_signature:
            self.move_signature.pop()
        repeat_state_key = None
        if self.move_piece_id:
            self.move_piece_id.pop()
        if self.move_repeat_state:
            repeat_state_key = self.move_repeat_state.pop()
        
        # 還原棋子位置
        piece.x = old_x
        piece.y = old_y
        
        # 還原被吃掉的棋子
        if captured_piece:
            self.pieces.append(captured_piece)
        
        # 如果這一步曾寫入重複局面計數，悔棋時需要回滾
        if repeat_state_key and repeat_state_key in self.board_state_history:
            self.board_state_history[repeat_state_key] -= 1
            if self.board_state_history[repeat_state_key] <= 0:
                del self.board_state_history[repeat_state_key]

        # 切換回合（悔棋後回到上一個玩家）
        self.turn = BLACK if self.turn == RED else RED
        
        # 重新檢查狀態：要檢查「當前回合方」是否被將軍
        self.is_check = self.is_under_attack(self.turn)
        
        self.set_warning("已悔棋！")
        return True

    def is_valid_move(self, piece, tx, ty, check_simulation=False):
        """ 
        驗證移動規則 
        check_simulation: 如果為 True，代表我們只是在運算攻擊範圍，不檢查'是否會送將' (避免無限迴圈)
        """
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
    
    def draw(self, screen, font):
        color = self.hover_color if self.is_hovered else self.color
        pygame.draw.rect(screen, color, self.rect)
        pygame.draw.rect(screen, BLACK, self.rect, 3)
        text_surface = font.render(self.text, True, BLACK)
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
        """繪製滾動條"""
        # 背景
        pygame.draw.rect(screen, (200, 200, 200), self.rect)
        # 滑塊
        thumb = self.get_thumb_rect()
        pygame.draw.rect(screen, (100, 100, 100), thumb)
    
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

class PikafishEngine:
    """以 UCI/UCCI 指令驅動 Pikafish。"""
    def __init__(self, engine_path=None):
        self.engine_path = engine_path or self.find_engine_path()
        self.process = None
        self.queue = queue.Queue()
        self.reader_thread = None

    def find_engine_path(self):
        candidates = []
        env_path = os.environ.get("PIKAFISH_PATH", "").strip()
        if env_path:
            candidates.append(env_path)

        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        onedrive_desktop = os.path.join(home, "OneDrive", "Desktop")

        for base in get_runtime_search_dirs():
            candidates.extend([
                os.path.join(base, "pikafish.exe"),
                os.path.join(base, "pikafish"),
                os.path.join(base, "engines", "pikafish.exe"),
                os.path.join(base, "engines", "pikafish"),
                os.path.join(base, "Pikafish", "pikafish.exe"),
                os.path.join(base, "Pikafish", "pikafish"),
            ])

        candidates.extend([
            os.path.join(desktop, "pikafish.exe"),
            os.path.join(desktop, "pikafish"),
            os.path.join(onedrive_desktop, "pikafish.exe"),
            os.path.join(onedrive_desktop, "pikafish"),
        ])
        for path in candidates:
            if path and os.path.exists(path):
                return path
        # 找不到時回傳預設，讓錯誤訊息更直接
        return candidates[0] if candidates else "pikafish"

    def _reader(self):
        while self.process and self.process.poll() is None:
            line = self.process.stdout.readline()
            if not line:
                break
            self.queue.put(line.strip())

    def _format_start_error(self, message, startup_lines):
        details = [f"{message} (path={self.engine_path})"]
        if startup_lines:
            details.append("輸出=" + " | ".join(startup_lines[-8:]))
        return "；".join(details)

    def _send(self, cmd):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Pikafish process is not running")
        self.process.stdin.write(cmd + "\n")
        self.process.stdin.flush()

    def _wait_for(self, predicate, timeout_sec, seen_lines=None):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            remain = max(0.01, deadline - time.time())
            try:
                line = self.queue.get(timeout=remain)
            except queue.Empty:
                continue
            if seen_lines is not None:
                seen_lines.append(line)
            if predicate(line):
                return line
        return None

    def start(self):
        if self.process and self.process.poll() is None:
            return
        engine_cwd = None
        if os.path.isabs(self.engine_path):
            engine_cwd = os.path.dirname(self.engine_path) or None
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        self.process = subprocess.Popen(
            [self.engine_path],
            cwd=engine_cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        self.reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.reader_thread.start()

        startup_lines = []
        self._send("uci")
        if not self._wait_for(lambda s: s == "uciok", 5, startup_lines):
            raise RuntimeError(self._format_start_error("Pikafish 啟動失敗：沒有收到 uciok", startup_lines))
        self._send("isready")
        if not self._wait_for(lambda s: s == "readyok", 5, startup_lines):
            raise RuntimeError(self._format_start_error("Pikafish 啟動失敗：沒有收到 readyok", startup_lines))
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for(lambda s: s == "readyok", 5, startup_lines)

    def _build_go_command(self, movetime_ms=None, depth=None):
        parts = []
        if isinstance(depth, int) and depth > 0:
            parts.extend(["depth", str(depth)])
        if movetime_ms is not None and movetime_ms > 0:
            parts.extend(["movetime", str(int(movetime_ms))])
        if parts:
            return "go " + " ".join(parts)
        return "go infinite"

    def bestmove(self, fen, movetime_ms=AI_MOVETIME_MS, depth=None, max_wait_sec=None):
        self._drain_queue()
        self._send(f"position fen {fen}")
        go_cmd = self._build_go_command(movetime_ms, depth)
        self._send(go_cmd)

        if max_wait_sec is None:
            if movetime_ms is not None and movetime_ms > 0:
                max_wait_sec = max(1.2, movetime_ms / 1000 + 1.0)
            else:
                max_wait_sec = AI_INFINITE_SEARCH_MAX_WAIT_SEC

        line = self._wait_for(lambda s: s.startswith("bestmove "), max_wait_sec)
        if not line and go_cmd == "go infinite":
            try:
                self._send("stop")
            except Exception:
                pass
            line = self._wait_for(lambda s: s.startswith("bestmove "), 2)
        if not line:
            return None
        parts = line.split()
        if len(parts) < 2 or parts[1] == "(none)":
            return None
        return parts[1]

    def _drain_queue(self):
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break

    def _parse_score_line(self, line):
        parts = line.split()
        for i in range(len(parts) - 2):
            if parts[i] != "score":
                continue
            score_type = parts[i + 1]
            score_val = parts[i + 2]
            if score_type in ("cp", "mate") and score_val.lstrip("-").isdigit():
                return score_type, int(score_val)
        return None

    def analyse_score(self, fen, movetime_ms=AI_EVAL_MOVETIME_MS):
        self._drain_queue()
        self._send(f"position fen {fen}")
        self._send(f"go movetime {movetime_ms}")

        latest = ("cp", 0)
        deadline = time.time() + max(2, movetime_ms / 1000 + 2)
        while time.time() < deadline:
            remain = max(0.01, deadline - time.time())
            try:
                line = self.queue.get(timeout=remain)
            except queue.Empty:
                continue

            if line.startswith("info "):
                parsed = self._parse_score_line(line)
                if parsed:
                    latest = parsed
            elif line.startswith("bestmove "):
                break

        return latest

    def stop(self):
        if not self.process:
            return
        proc = self.process
        reader_thread = self.reader_thread
        try:
            if proc.poll() is None:
                proc.stdin.write("quit\n")
                proc.stdin.flush()
        except Exception:
            pass
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            if proc.poll() is None:
                proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        if reader_thread and reader_thread.is_alive():
            reader_thread.join(timeout=0.5)
        self.process = None
        self.reader_thread = None


class EngineDispatcher:
    """單一引擎工作器：序列化處理 AI/評估/建議任務。"""
    def __init__(self, engine_path=None):
        self.engine_path = engine_path
        self.engine = None
        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.engine = PikafishEngine(self.engine_path)
        self.engine.start()
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                task = self.task_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if task is None:
                continue

            req_id, kind, fen, movetime_ms, depth, max_wait_sec = task
            try:
                if kind == "bestmove":
                    payload = self.engine.bestmove(fen, movetime_ms, depth=depth, max_wait_sec=max_wait_sec)
                elif kind == "analyse":
                    payload = self.engine.analyse_score(fen, movetime_ms)
                else:
                    raise RuntimeError(f"unknown task kind: {kind}")
                self.result_queue.put((req_id, kind, fen, "ok", payload))
            except Exception as ex:
                self.result_queue.put((req_id, kind, fen, "err", str(ex)))

    def submit(self, req_id, kind, fen, movetime_ms=None, depth=None, max_wait_sec=None):
        self.task_queue.put((req_id, kind, fen, movetime_ms, depth, max_wait_sec))

    def get_result_nowait(self):
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        self.stop_event.set()
        try:
            self.task_queue.put_nowait(None)
        except Exception:
            pass
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=0.2)
        if self.engine:
            self.engine.stop()
        self.worker = None
        self.engine = None


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

def main():
    pygame.init()
    window = pygame.display.set_mode(get_initial_window_size(), pygame.RESIZABLE)
    render_rect = get_render_rect(window.get_size())
    screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("中國象棋 Ver 3.1 (Pikafish 難度 + 可替換素材)")
    clock = pygame.time.Clock()
    
    font_names = ["simhei", "arialunicodems", "pingfangtc", "microsoftjhenghei"]
    font = pygame.font.SysFont(font_names, 32)
    font_ui = pygame.font.SysFont(font_names, 40)
    font_eval = pygame.font.SysFont(font_names, 52)
    font_small = pygame.font.SysFont(font_names, 24)
    font_warn = pygame.font.SysFont(font_names, 48) # 警告字體
    font_menu = pygame.font.SysFont(font_names, 56)
    board_surface, piece_sprites = load_visual_assets(font_names)
    
    # 遊戲狀態
    game_state = MODE_MENU  # 初始化為菜單狀態
    board = None
    history_scroll = None  # 移動歷史滾動條

    player_color = RED
    ai_color = BLACK
    view_color = RED

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
    save_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SAVE_FILE_NAME)
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
            btn_difficulty.text = f"AI 難度：{ai_difficulty}"

    def get_history_panel_rects():
        panel_x = MARGIN_X + BOARD_WIDTH + 20
        panel_y = MARGIN_Y
        panel_width = SCREEN_WIDTH - panel_x - 30
        panel_height = BOARD_HEIGHT
        clip_rect = pygame.Rect(panel_x, panel_y + 35, panel_width - 15, panel_height - 35)
        return panel_x, panel_y, panel_width, panel_height, clip_rect

    def get_display_notation_list():
        if replay_mode_active and replay_record_notation:
            return replay_record_notation
        if board:
            return board.move_notation
        return []

    def get_history_max_scroll():
        total_lines = len(get_display_notation_list())
        panel_height = BOARD_HEIGHT
        return max(0, total_lines * 25 - (panel_height - 40))

    def get_notation_index_at_pos(pos):
        if not board:
            return None
        panel_x, panel_y, panel_width, panel_height, clip_rect = get_history_panel_rects()
        if not clip_rect.collidepoint(pos):
            return None
        scroll_offset = history_scroll.scroll_offset if history_scroll else 0
        y_in_list = pos[1] - (panel_y + 35) + scroll_offset
        if y_in_list < 0:
            return None
        idx = int(y_in_list // 25)
        notation_list = get_display_notation_list()
        if 0 <= idx < len(notation_list):
            return idx
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

        rebuilt = XiangqiBoard(board.game_mode)
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

    def on_move_applied():
        reset_eval_state()
        reset_suggest_state()
        append_replay_snapshot()

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
            board.set_warning("沒有可復盤的棋譜")
            return False

        if step_idx is None:
            step_idx = len(replay_record_moves)
        if not restore_game_to_step(step_idx, source_moves=replay_record_moves):
            board.set_warning("進入復盤模式失敗")
            return False

        replay_mode_active = True
        ai_enabled = False
        if btn_replay_mode:
            btn_replay_mode.text = "復盤中"
        board.set_warning(f"已進入復盤模式（第 {step_idx} 手）")
        return True

    def color_to_str(color):
        return "red" if color == RED else "black"

    def str_to_color(token, default):
        if token == "red":
            return RED
        if token == "black":
            return BLACK
        return default

    def setup_in_game_buttons():
        nonlocal btn_undo, btn_main_menu, btn_suggest_toggle
        nonlocal btn_save_game, btn_load_game, btn_draw_offer, btn_replay_mode
        btn_undo = Button(SCREEN_WIDTH // 2 - 80, SCREEN_HEIGHT - 40, 160, 35, "悔棋")
        btn_main_menu = Button(SCREEN_WIDTH // 2 + 100, SCREEN_HEIGHT - 40, 180, 35, "回主選單")
        btn_suggest_toggle = Button(SCREEN_WIDTH // 2 - 320, SCREEN_HEIGHT - 40, 220, 35, "建議著法：關")
        btn_save_game = Button(10, SCREEN_HEIGHT - 40, 150, 35, "存檔")
        btn_load_game = Button(810, SCREEN_HEIGHT - 40, 180, 35, "讀檔")
        btn_draw_offer = Button(915, 12, 170, 32, "求和")
        btn_replay_mode = Button(915, 50, 170, 32, "復盤模式")

    def start_new_game(mode, human_side=RED):
        nonlocal game_state, board, history_scroll
        nonlocal ai_enabled, eval_enabled, suggest_enabled
        nonlocal player_color, ai_color, view_color
        nonlocal draw_offer_popup, btn_draw_accept, btn_draw_reject
        nonlocal replay_snapshots, replay_index, replay_mode_active
        nonlocal replay_record_moves, replay_record_notation
        nonlocal replay_finished_winner, replay_finished_draw_reason

        stop_engine()
        reset_ai_state()
        reset_eval_state(reset_display=True)
        reset_suggest_state(reset_display=True)

        board = XiangqiBoard(mode)
        game_state = mode
        eval_enabled = True
        suggest_enabled = False

        if mode == MODE_AI:
            ai_enabled = True
            player_color = human_side
            ai_color = BLACK if human_side == RED else RED
            view_color = human_side
        else:
            ai_enabled = False
            player_color = RED
            ai_color = BLACK
            view_color = RED

        history_scroll = ScrollBar(SCREEN_WIDTH - 30, MARGIN_Y, 15, BOARD_HEIGHT, 1000)
        setup_in_game_buttons()
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

    def save_game_to_disk():
        if not board or game_state not in (MODE_PVP, MODE_AI):
            return False
        try:
            payload = {
                "version": 1,
                "game_state": game_state,
                "player_color": color_to_str(player_color),
                "ai_color": color_to_str(ai_color),
                "view_color": color_to_str(view_color),
                "ai_difficulty": ai_difficulty,
                "suggest_enabled": bool(suggest_enabled),
                "moves": list(board.move_ucci_history),
                "history_scroll_offset": float(history_scroll.scroll_offset if history_scroll else 0.0),
            }
            with open(save_file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            board.set_warning("存檔成功")
            return True
        except Exception as ex:
            if board:
                board.set_warning(f"存檔失敗：{ex}")
            return False

    def load_game_from_disk():
        nonlocal game_state, board, history_scroll
        nonlocal ai_enabled, eval_enabled, suggest_enabled
        nonlocal player_color, ai_color, view_color
        nonlocal draw_offer_popup, btn_draw_accept, btn_draw_reject
        nonlocal replay_index, replay_mode_active
        nonlocal replay_record_moves, replay_record_notation
        nonlocal replay_finished_winner, replay_finished_draw_reason

        if not os.path.exists(save_file_path):
            if board:
                board.set_warning("找不到存檔檔案")
            return False

        try:
            with open(save_file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as ex:
            if board:
                board.set_warning(f"讀檔失敗：{ex}")
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

            if saved_mode == MODE_AI:
                start_new_game(MODE_AI, saved_player)
                ai_color = saved_ai if saved_ai != player_color else (BLACK if player_color == RED else RED)
                view_color = saved_view
            else:
                start_new_game(MODE_PVP, RED)
                view_color = saved_view

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
                btn_suggest_toggle.text = "建議著法：開" if suggest_enabled else "建議著法：關"

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
            board.set_warning("讀檔成功")
            return True
        except Exception as ex:
            if board:
                board.set_warning(f"讀檔失敗：{ex}")
            return False

    def open_draw_offer_popup():
        nonlocal draw_offer_popup, btn_draw_accept, btn_draw_reject
        if not board or board.winner or board.draw_reason:
            return
        draw_offer_popup = {"from_color": board.turn}
        btn_draw_accept = Button(SCREEN_WIDTH // 2 - 130, SCREEN_HEIGHT // 2 + 20, 120, 40, "接受和棋")
        btn_draw_reject = Button(SCREEN_WIDTH // 2 + 10, SCREEN_HEIGHT // 2 + 20, 120, 40, "拒絕")

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
                board.set_warning("目前不是你的回合，不能向 AI 求和")
                return
            if abs(eval_red_score_cp) <= 100:
                board.draw_reason = "雙方同意和棋（AI接受求和）"
                board.set_warning("AI 接受和棋")
            else:
                board.set_warning("AI 拒絕和棋（分差超過100）")

    def collect_legal_ucci_moves(color):
        if not board:
            return []

        moves = []
        for piece in list(board.pieces):
            if piece.color != color:
                continue

            from_x, from_y = piece.x, piece.y
            for tx in range(9):
                for ty in range(10):
                    if tx == from_x and ty == from_y:
                        continue
                    if not board.is_valid_move(piece, tx, ty):
                        continue

                    target = board.get_piece_at(tx, ty)
                    piece.x, piece.y = tx, ty
                    if target:
                        board.pieces.remove(target)

                    illegal = board.is_kings_facing() or board.is_under_attack(piece.color)

                    piece.x, piece.y = from_x, from_y
                    if target:
                        board.pieces.append(target)

                    if illegal:
                        continue

                    moves.append(board_to_ucci(from_x, from_y) + board_to_ucci(tx, ty))

        return moves

    def choose_ai_move(engine_bestmove):
        if not engine_bestmove or ai_mistake_rate <= 0:
            return engine_bestmove
        if random.random() >= ai_mistake_rate:
            return engine_bestmove

        legal_moves = collect_legal_ucci_moves(ai_color)
        if not legal_moves:
            return engine_bestmove

        alternatives = [mv for mv in legal_moves if mv != engine_bestmove]
        if not alternatives:
            return engine_bestmove
        return random.choice(alternatives)

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
        try:
            engine_dispatcher = EngineDispatcher()
            engine_dispatcher.start()
            return True
        except Exception as e:
            engine_dispatcher = None
            if board:
                board.set_warning(f"引擎初始化失敗：{e}")
            return False

    def stop_engine():
        nonlocal engine_dispatcher
        if engine_dispatcher:
            engine_dispatcher.stop()
        engine_dispatcher = None

    def poll_engine_results():
        nonlocal ai_request_id, eval_request_id, suggest_request_id
        nonlocal ai_enabled, eval_enabled, suggest_enabled
        nonlocal ai_wait_until, ai_request_fen, suggest_move

        if not engine_dispatcher:
            return

        while True:
            res = engine_dispatcher.get_result_nowait()
            if not res:
                break

            req_id, kind, req_fen, status, payload = res

            if req_id == ai_request_id:
                ai_request_id = None
                if status == "err":
                    ai_enabled = False
                    if board:
                        board.set_warning(f"AI 執行失敗：{payload}")
                    continue

                if (not board or board.winner or board.draw_reason or
                    board.turn != ai_color or board.to_fen() != req_fen):
                    continue

                best = payload
                if not best:
                    ai_enabled = False
                    board.set_warning("AI 無可用走法或超時")
                else:
                    move_to_play = choose_ai_move(best)
                    if not apply_ucci_move(board, move_to_play):
                        # 如果故意失誤著因局面時序失配而失敗，退回最佳著再試一次。
                        if move_to_play != best and apply_ucci_move(board, best):
                            ai_wait_until = 0.0
                            ai_request_fen = None
                            on_move_applied()
                        else:
                            ai_enabled = False
                            board.set_warning(f"AI 走法無效：{move_to_play}")
                    else:
                        ai_wait_until = 0.0
                        ai_request_fen = None
                        on_move_applied()
                continue

            if req_id == eval_request_id:
                eval_request_id = None
                if status == "err":
                    eval_enabled = False
                    if board:
                        board.set_warning(f"評估執行失敗：{payload}")
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
                        btn_suggest_toggle.text = "建議著法：關"
                    if board:
                        board.set_warning(f"建議執行失敗：{payload}")
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

    # 菜單按鈕
    btn_pvp = Button(SCREEN_WIDTH // 2 - 140, 260, 280, 60, "玩家對玩家")
    btn_ai_red = Button(SCREEN_WIDTH // 2 - 140, 350, 280, 60, "玩家(紅) 對 AI")
    btn_ai_black = Button(SCREEN_WIDTH // 2 - 140, 440, 280, 60, "玩家(黑) 對 AI")
    btn_difficulty = Button(SCREEN_WIDTH // 2 - 140, 530, 280, 50, f"AI 難度：{ai_difficulty}")
    btn_menu_load = Button(SCREEN_WIDTH // 2 - 140, 600, 280, 50, "讀取存檔")
    btn_undo = None  # 悔棋按鈕會在遊戲中建立
    btn_main_menu = None  # 遊戲中隨時返回主選單
    btn_suggest_toggle = None  # 建議著法開關
    btn_save_game = None
    btn_load_game = None
    btn_draw_offer = None
    btn_replay_mode = None
    
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
            if event.type == pygame.KEYDOWN and (game_state == MODE_PVP or game_state == MODE_AI):
                if event.key == pygame.K_d and board:
                    board.debug = not board.debug
                    board.set_warning(f"Debug={'開' if board.debug else '關'}")
            
            # --- 菜單模式 ---
            if game_state == MODE_MENU:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if btn_pvp.is_clicked(mouse_pos):
                        start_new_game(MODE_PVP, RED)
                    elif btn_ai_red.is_clicked(mouse_pos):
                        start_new_game(MODE_AI, RED)
                    elif btn_ai_black.is_clicked(mouse_pos):
                        start_new_game(MODE_AI, BLACK)
                    elif btn_difficulty and btn_difficulty.is_clicked(mouse_pos):
                        idx = ai_difficulty_order.index(ai_difficulty)
                        next_idx = (idx + 1) % len(ai_difficulty_order)
                        apply_ai_difficulty(ai_difficulty_order[next_idx])
                    elif btn_menu_load and btn_menu_load.is_clicked(mouse_pos):
                        load_game_from_disk()
            
            # --- 遊戲模式 ---
            elif event.type == pygame.MOUSEBUTTONDOWN and (game_state == MODE_PVP or game_state == MODE_AI):
                # 遊戲中隨時返回主選單
                if btn_main_menu and btn_main_menu.is_clicked(mouse_pos):
                    stop_engine()
                    reset_ai_state()
                    reset_eval_state(reset_display=True)
                    reset_suggest_state(reset_display=True)
                    game_state = MODE_MENU
                    board = None
                    btn_main_menu = None
                    btn_suggest_toggle = None
                    btn_undo = None
                    btn_save_game = None
                    btn_load_game = None
                    btn_draw_offer = None
                    btn_replay_mode = None
                    history_scroll = None
                    replay_snapshots = []
                    replay_index = None
                    replay_mode_active = False
                    replay_record_moves = []
                    replay_record_notation = []
                    replay_finished_winner = None
                    replay_finished_draw_reason = ""
                    close_draw_offer_popup()
                else:
                    max_scroll = get_history_max_scroll()

                    # PVP 求和彈窗優先處理
                    if draw_offer_popup:
                        if event.button == 1:
                            if btn_draw_accept and btn_draw_accept.is_clicked(mouse_pos):
                                board.draw_reason = "雙方同意和棋"
                                close_draw_offer_popup()
                            elif btn_draw_reject and btn_draw_reject.is_clicked(mouse_pos):
                                board.set_warning("對方拒絕和棋")
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

                    # 滾動條拖動起點
                        if event.button == 1 and history_scroll:
                            history_scroll.handle_click(mouse_pos)
                            if history_scroll.is_dragging:
                                continue

                    if event.button == 1 and btn_replay_mode and btn_replay_mode.is_clicked(mouse_pos):
                        if replay_mode_active:
                            board.set_warning("已在復盤模式")
                        elif board.winner or board.draw_reason:
                            enter_replay_mode()
                        else:
                            board.set_warning("對局尚未結束，暫不可進入復盤模式")
                        continue

                    # 未進入復盤模式時，終局局面不可直接操作棋子。
                    if (board.winner or board.draw_reason) and not replay_mode_active:
                        continue

                    # 復盤模式下可點譜跳局面，但不影響原終局棋譜。
                    if replay_mode_active and event.button == 1:
                        idx = get_notation_index_at_pos(mouse_pos)
                        if idx is not None:
                            if restore_game_to_step(idx + 1, source_moves=replay_record_moves):
                                board.set_warning(f"復盤跳轉：第 {idx + 1} 手")
                            else:
                                board.set_warning("復盤跳轉失敗")
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
                        btn_suggest_toggle.text = "建議著法：開" if suggest_enabled else "建議著法：關"
                        reset_suggest_state(reset_display=True)
                        if not suggest_enabled:
                            reset_eval_state(reset_display=True)
                    elif btn_undo and btn_undo.is_clicked(mouse_pos):
                        if board.undo_last_move():
                            board.selected_piece = None
                            reset_ai_state()
                            reset_eval_state()
                            reset_suggest_state()
                            sync_replay_history_after_undo()
                    else:
                        if game_state == MODE_AI and ai_enabled and board.turn == ai_color:
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
                                        if game_state == MODE_AI and board.turn == ai_color:
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

            elif event.type == pygame.MOUSEMOTION and (game_state == MODE_PVP or game_state == MODE_AI):
                if history_scroll:
                    history_scroll.handle_drag(mouse_pos, get_history_max_scroll())

            elif event.type == pygame.MOUSEBUTTONUP and (game_state == MODE_PVP or game_state == MODE_AI):
                if event.button == 1 and history_scroll:
                    history_scroll.handle_release()

        # --- 引擎結果回收 ---
        poll_engine_results()

        # --- AI 回合 ---
        if (game_state == MODE_AI and board and ai_enabled and
            not board.winner and not board.draw_reason and board.turn == ai_color):
            if ai_wait_until <= 0:
                ai_wait_until = time.time() + AI_DELAY_SEC

            if ai_request_id is None and time.time() >= ai_wait_until:
                ai_request_fen = board.to_fen()
                if ensure_engine():
                    ai_request_id = new_request_id()
                    engine_dispatcher.submit(
                        ai_request_id,
                        "bestmove",
                        ai_request_fen,
                        ai_movetime_ms,
                        depth=ai_search_depth,
                        max_wait_sec=ai_max_wait_sec,
                    )
                else:
                    ai_enabled = False
                    board.set_warning("AI 引擎初始化失敗")

        # --- 即時評估（僅在建議著法開啟時） ---
        if game_state in (MODE_PVP, MODE_AI) and board and eval_enabled and suggest_enabled and not board.winner and not board.draw_reason:
            current_fen = board.to_fen()
            if eval_request_id is None and current_fen != eval_last_fen_requested:
                if ensure_engine():
                    eval_last_fen_requested = current_fen
                    eval_request_id = new_request_id()
                    engine_dispatcher.submit(eval_request_id, "analyse", current_fen, AI_EVAL_MOVETIME_MS)
                else:
                    eval_enabled = False
                    board.set_warning("評估引擎初始化失敗")
        elif not suggest_enabled:
            reset_eval_state(reset_display=True)

        # --- 建議著法 ---
        if game_state in (MODE_PVP, MODE_AI) and board and suggest_enabled and not board.winner and not board.draw_reason:
            # AI 模式下，只在玩家回合提供建議
            if game_state == MODE_AI and (not replay_mode_active) and board.turn != player_color:
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
                            btn_suggest_toggle.text = "建議著法：關"
                        board.set_warning("建議引擎初始化失敗")
        elif not suggest_enabled:
            suggest_move = None

        if game_state in (MODE_PVP, MODE_AI) and board:
            capture_finished_record_if_needed()

        # --- 繪圖 ---
        screen.fill(COLOR_BG)
        
        if game_state == MODE_MENU:
            # 繪製菜單
            title = font_menu.render("中國象棋", True, BLACK)
            title_rect = title.get_rect(center=(SCREEN_WIDTH // 2, 100))
            screen.blit(title, title_rect)
            
            subtitle = font.render("選擇遊戲模式", True, BLACK)
            subtitle_rect = subtitle.get_rect(center=(SCREEN_WIDTH // 2, 200))
            screen.blit(subtitle, subtitle_rect)
            
            btn_pvp.update_hover(mouse_pos)
            btn_ai_red.update_hover(mouse_pos)
            btn_ai_black.update_hover(mouse_pos)
            if btn_difficulty:
                btn_difficulty.update_hover(mouse_pos)
            if btn_menu_load:
                btn_menu_load.update_hover(mouse_pos)
            btn_pvp.draw(screen, font)
            btn_ai_red.draw(screen, font)
            btn_ai_black.draw(screen, font)
            if btn_difficulty:
                btn_difficulty.draw(screen, font_small)
            if btn_menu_load:
                btn_menu_load.draw(screen, font_small)
            tip = font_small.render("提示：點擊 AI 難度按鈕可循環切換", True, BLACK)
            screen.blit(tip, (SCREEN_WIDTH // 2 - 180, 665))
        
        elif game_state == MODE_PVP or game_state == MODE_AI:
            # 繪製遊戲界面
            # 1. 繪製 UI 欄
            pygame.draw.rect(screen, COLOR_UI_BAR, (0, 0, SCREEN_WIDTH, TOP_UI_HEIGHT))
            
            turn_str = "紅方回合" if board.turn == RED else "黑方回合"
            color = RED if board.turn == RED else WHITE
            screen.blit(font_ui.render(turn_str, True, color), (20, 12))

            mode_text = (
                "模式：雙人"
                if game_state == MODE_PVP
                else f"你：{'紅方' if player_color == RED else '黑方'}  AI：{'紅方' if ai_color == RED else '黑方'}  難度：{ai_difficulty}"
            )
            screen.blit(font_small.render(mode_text, True, WHITE), (20, 52))

            eval_x = 730
            if suggest_enabled:
                screen.blit(font_small.render("建議著法（含評分）", True, WHITE), (eval_x, 10))
                sugg_text = f"建議: {suggest_move}" if suggest_move else "建議: --"
                screen.blit(font_small.render(sugg_text, True, WHITE), (eval_x, 44))
                screen.blit(font_small.render(f"評分: {eval_text}", True, GOLD), (eval_x, 76))
            else:
                screen.blit(font_small.render("建議著法：關", True, WHITE), (eval_x, 44))
            
            # 狀態顯示 (將軍 / 勝利 / 正常)
            if replay_mode_active:
                if replay_finished_winner:
                    status = "原局結果：紅方獲勝" if replay_finished_winner == RED else "原局結果：黑方獲勝"
                    screen.blit(font.render(status, True, GOLD), (250, 10))
                elif replay_finished_draw_reason:
                    draw_text = font.render(f"原局結果：{replay_finished_draw_reason}", True, WARNING_COLOR)
                    screen.blit(draw_text, (250, 10))
            elif board.winner:
                status = "紅方獲勝！" if board.winner == RED else "黑方獲勝！"
                screen.blit(font_ui.render(status, True, GOLD), (250, 10))
            elif board.draw_reason:
                # 顯示和棋原因
                draw_text = font.render(board.draw_reason, True, WARNING_COLOR)
                screen.blit(draw_text, (250, 10))
            elif board.is_check:
                # 顯示閃爍的將軍文字
                if int(time.time() * 2) % 2 == 0: # 簡單的閃爍效果
                    screen.blit(font_warn.render("將軍！", True, GOLD), (250, 10))

            if replay_mode_active:
                rv_text = font_small.render("復盤模式：可點譜跳步、可繼續下棋，且不影響原棋譜", True, GOLD)
                screen.blit(rv_text, (20, 92))
            elif board.winner or board.draw_reason:
                rv_text = font_small.render("對局已結束，按「復盤模式」可開始分析", True, GOLD)
                screen.blit(rv_text, (20, 92))
            
            # 顯示警告訊息 (例如：不可送將) - 顯示 2 秒
            if board.warning_msg and time.time() - board.warning_timer < 2.0:
                warn_text = font_small.render(board.warning_msg, True, WARNING_COLOR)
                text_rect = warn_text.get_rect(center=(SCREEN_WIDTH//2, TOP_UI_HEIGHT - 10))
                screen.blit(warn_text, text_rect)

            # 2. 繪製棋盤
            if board_surface:
                screen.blit(board_surface, (MARGIN_X - 5, MARGIN_Y - 5))
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
            left_river = "楚河" if view_color == RED else "漢界"
            right_river = "漢界" if view_color == RED else "楚河"
            screen.blit(font_river.render(left_river, True, COLOR_LINE), (MARGIN_X + 1.5 * GRID_SIZE, MARGIN_Y + 4.2 * GRID_SIZE))
            screen.blit(font_river.render(right_river, True, COLOR_LINE), (MARGIN_X + 5.5 * GRID_SIZE, MARGIN_Y + 4.2 * GRID_SIZE))

            # 3. 繪製移動歷史
            history_panel_x, history_panel_y, history_panel_width, history_panel_height, clip_rect = get_history_panel_rects()
            
            # 繪製背景板
            pygame.draw.rect(screen, (220, 210, 190), (history_panel_x, history_panel_y, history_panel_width, history_panel_height))
            pygame.draw.rect(screen, COLOR_LINE, (history_panel_x, history_panel_y, history_panel_width, history_panel_height), 2)
            
            # 標題
            title_text = font_small.render("移動記錄", True, COLOR_LINE)
            screen.blit(title_text, (history_panel_x + 5, history_panel_y + 5))
            
            # 計算可顯示的最大偏移量
            notation_list = get_display_notation_list()
            total_lines = len(notation_list)
            max_scroll = get_history_max_scroll()
            if history_scroll:
                history_scroll.content_height = total_lines * 25 + 40
            
            # 使用裁剪區域限制繪製範圍
            screen.set_clip(clip_rect)
            
            # 顯示每一步移動，使用滾動偏移
            scroll_offset = history_scroll.scroll_offset if history_scroll else 0
            y_offset = history_panel_y + 35 - scroll_offset
            
            for i, notation in enumerate(notation_list):
                if replay_mode_active and replay_index == i + 1:
                    pygame.draw.rect(screen, (255, 236, 180), (history_panel_x + 2, y_offset - 1, history_panel_width - 20, 23))
                # 紅方和黑方交替顯示
                move_color = RED if i % 2 == 0 else BLACK
                move_text = font_small.render(f"{i+1}. {notation}", True, move_color)
                screen.blit(move_text, (history_panel_x + 10, y_offset))
                y_offset += 25
            
            # 清除裁剪區域
            screen.set_clip(None)
            
            # 繪製滾動條
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

            # 6. 繪製按鈕
            if btn_undo and not board.winner and not board.draw_reason:
                btn_undo.update_hover(mouse_pos)
                btn_undo.draw(screen, font_small)

            if btn_save_game and not board.winner and not board.draw_reason:
                btn_save_game.update_hover(mouse_pos)
                btn_save_game.draw(screen, font_small)

            if btn_load_game and not board.winner and not board.draw_reason:
                btn_load_game.update_hover(mouse_pos)
                btn_load_game.draw(screen, font_small)

            if btn_draw_offer and not board.winner and not board.draw_reason and not replay_mode_active:
                btn_draw_offer.update_hover(mouse_pos)
                btn_draw_offer.draw(screen, font_small)

            if btn_replay_mode and (board.winner or board.draw_reason or replay_mode_active):
                btn_replay_mode.update_hover(mouse_pos)
                btn_replay_mode.draw(screen, font_small)

            if btn_main_menu:
                btn_main_menu.update_hover(mouse_pos)
                btn_main_menu.draw(screen, font_small)

            if btn_suggest_toggle and not board.winner and not board.draw_reason:
                btn_suggest_toggle.update_hover(mouse_pos)
                btn_suggest_toggle.draw(screen, font_small)

            if draw_offer_popup and btn_draw_accept and btn_draw_reject:
                overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 110))
                screen.blit(overlay, (0, 0))
                popup_rect = pygame.Rect(SCREEN_WIDTH // 2 - 220, SCREEN_HEIGHT // 2 - 110, 440, 220)
                pygame.draw.rect(screen, (245, 233, 205), popup_rect)
                pygame.draw.rect(screen, COLOR_LINE, popup_rect, 3)
                requester = "紅方" if draw_offer_popup["from_color"] == RED else "黑方"
                msg = font.render(f"{requester}提出求和，是否接受？", True, COLOR_LINE)
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
