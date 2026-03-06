import pygame
import sys
import time
import os
import subprocess
import threading
import queue
import math

# --- 1. 系統常數 ---
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 800
BOARD_WIDTH = 540
BOARD_HEIGHT = 630
GRID_SIZE = 60

MARGIN_X = (SCREEN_WIDTH - BOARD_WIDTH) // 2
MARGIN_Y = (SCREEN_HEIGHT - BOARD_HEIGHT) // 2 + 50

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
UCCI_FILES = "abcdefghi"

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
            # 正確計算馬的腿位置：用整數除法 (dx//2, dy//2)
            # 例如：dx=2,dy=1 時，腿位置=(piece.x+1, piece.y+0)
            # 例如：dx=1,dy=2 時，腿位置=(piece.x+0, piece.y+1)
            leg_x = piece.x + dx // 2
            leg_y = piece.y + dy // 2
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

        base = os.path.dirname(os.path.abspath(__file__))
        candidates.extend([
            os.path.join(base, "pikafish.exe"),
            os.path.join(base, "pikafish"),
            os.path.join(base, "engines", "pikafish.exe"),
            os.path.join(base, "engines", "pikafish"),
            os.path.join(base, "Pikafish", "pikafish.exe"),
            os.path.join(base, "Pikafish", "pikafish"),
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

    def _send(self, cmd):
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Pikafish process is not running")
        self.process.stdin.write(cmd + "\n")
        self.process.stdin.flush()

    def _wait_for(self, predicate, timeout_sec):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            remain = max(0.01, deadline - time.time())
            try:
                line = self.queue.get(timeout=remain)
            except queue.Empty:
                continue
            if predicate(line):
                return line
        return None

    def start(self):
        if self.process and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            [self.engine_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.reader_thread.start()

        self._send("uci")
        if not self._wait_for(lambda s: s == "uciok", 5):
            raise RuntimeError("Pikafish 啟動失敗：沒有收到 uciok")
        self._send("isready")
        if not self._wait_for(lambda s: s == "readyok", 5):
            raise RuntimeError("Pikafish 啟動失敗：沒有收到 readyok")
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for(lambda s: s == "readyok", 5)

    def bestmove(self, fen, movetime_ms=AI_MOVETIME_MS):
        self._send(f"position fen {fen}")
        self._send(f"go movetime {movetime_ms}")
        line = self._wait_for(lambda s: s.startswith("bestmove "), max(2, movetime_ms / 1000 + 2))
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
        try:
            if self.process.poll() is None:
                self._send("quit")
        except Exception:
            pass
        try:
            self.process.terminate()
        except Exception:
            pass
        self.process = None


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

            req_id, kind, fen, movetime_ms = task
            try:
                if kind == "bestmove":
                    payload = self.engine.bestmove(fen, movetime_ms)
                elif kind == "analyse":
                    payload = self.engine.analyse_score(fen, movetime_ms)
                else:
                    raise RuntimeError(f"unknown task kind: {kind}")
                self.result_queue.put((req_id, kind, fen, "ok", payload))
            except Exception as ex:
                self.result_queue.put((req_id, kind, fen, "err", str(ex)))

    def submit(self, req_id, kind, fen, movetime_ms):
        self.task_queue.put((req_id, kind, fen, movetime_ms))

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
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("中國象棋 Ver 3.0 (將軍檢測 + 悔棋)")
    clock = pygame.time.Clock()
    
    font_names = ["simhei", "arialunicodems", "pingfangtc", "microsoftjhenghei"]
    font = pygame.font.SysFont(font_names, 32)
    font_ui = pygame.font.SysFont(font_names, 40)
    font_eval = pygame.font.SysFont(font_names, 52)
    font_small = pygame.font.SysFont(font_names, 24)
    font_warn = pygame.font.SysFont(font_names, 48) # 警告字體
    font_menu = pygame.font.SysFont(font_names, 56)
    
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

    eval_enabled = True
    eval_request_id = None
    eval_last_fen_requested = None
    eval_red_score_cp = 0
    eval_text = "+0"

    suggest_enabled = False
    suggest_request_id = None
    suggest_last_fen_requested = None
    suggest_move = None

    def reset_ai_state():
        nonlocal ai_wait_until, ai_request_id, ai_request_fen
        ai_wait_until = 0.0
        ai_request_id = None
        ai_request_fen = None

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
                elif not apply_ucci_move(board, best):
                    ai_enabled = False
                    board.set_warning(f"AI 走法無效：{best}")
                else:
                    ai_wait_until = 0.0
                    ai_request_fen = None
                    reset_eval_state()
                    reset_suggest_state()
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
    btn_undo = None  # 悔棋按鈕會在遊戲中建立
    btn_main_menu = None  # 遊戲中隨時返回主選單
    btn_suggest_toggle = None  # 建議著法開關
    btn_return_menu = None  # 返回菜單按鈕會在遊戲結束時建立
    
    while True:
        mouse_pos = pygame.mouse.get_pos()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                stop_engine()
                pygame.quit(); sys.exit()
            # 鍵盤事件：按 D 鍵可切換 debug 日誌（臨時，用於排查長捉/長將）
            if event.type == pygame.KEYDOWN and (game_state == MODE_PVP or game_state == MODE_AI):
                if event.key == pygame.K_d and board:
                    board.debug = not board.debug
                    board.set_warning(f"Debug={'開' if board.debug else '關'}")
            
            # --- 菜單模式 ---
            if game_state == MODE_MENU:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if btn_pvp.is_clicked(mouse_pos):
                        stop_engine()
                        reset_ai_state()
                        reset_eval_state(reset_display=True)
                        reset_suggest_state(reset_display=True)
                        board = XiangqiBoard(MODE_PVP)
                        game_state = MODE_PVP
                        ai_enabled = False
                        eval_enabled = True
                        player_color = RED
                        ai_color = BLACK
                        view_color = RED
                        btn_undo = Button(SCREEN_WIDTH // 2 - 80, SCREEN_HEIGHT - 40, 160, 35, "悔棋")
                        btn_main_menu = Button(SCREEN_WIDTH // 2 + 100, SCREEN_HEIGHT - 40, 180, 35, "回主選單")
                        btn_suggest_toggle = Button(SCREEN_WIDTH // 2 - 320, SCREEN_HEIGHT - 40, 220, 35, "建議著法：關")
                        history_scroll = ScrollBar(SCREEN_WIDTH - 30, MARGIN_Y, 15, BOARD_HEIGHT, 1000)
                    elif btn_ai_red.is_clicked(mouse_pos):
                        stop_engine()
                        reset_ai_state()
                        reset_eval_state(reset_display=True)
                        reset_suggest_state(reset_display=True)
                        board = XiangqiBoard(MODE_AI)
                        game_state = MODE_AI
                        ai_enabled = True
                        eval_enabled = True
                        player_color = RED
                        ai_color = BLACK
                        view_color = RED
                        btn_undo = Button(SCREEN_WIDTH // 2 - 80, SCREEN_HEIGHT - 40, 160, 35, "悔棋")
                        btn_main_menu = Button(SCREEN_WIDTH // 2 + 100, SCREEN_HEIGHT - 40, 180, 35, "回主選單")
                        btn_suggest_toggle = Button(SCREEN_WIDTH // 2 - 320, SCREEN_HEIGHT - 40, 220, 35, "建議著法：關")
                        history_scroll = ScrollBar(SCREEN_WIDTH - 30, MARGIN_Y, 15, BOARD_HEIGHT, 1000)
                    elif btn_ai_black.is_clicked(mouse_pos):
                        stop_engine()
                        reset_ai_state()
                        reset_eval_state(reset_display=True)
                        reset_suggest_state(reset_display=True)
                        board = XiangqiBoard(MODE_AI)
                        game_state = MODE_AI
                        ai_enabled = True
                        eval_enabled = True
                        player_color = BLACK
                        ai_color = RED
                        view_color = BLACK
                        btn_undo = Button(SCREEN_WIDTH // 2 - 80, SCREEN_HEIGHT - 40, 160, 35, "悔棋")
                        btn_main_menu = Button(SCREEN_WIDTH // 2 + 100, SCREEN_HEIGHT - 40, 180, 35, "回主選單")
                        btn_suggest_toggle = Button(SCREEN_WIDTH // 2 - 320, SCREEN_HEIGHT - 40, 220, 35, "建議著法：關")
                        history_scroll = ScrollBar(SCREEN_WIDTH - 30, MARGIN_Y, 15, BOARD_HEIGHT, 1000)
            
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
                    btn_return_menu = None
                    btn_main_menu = None
                    btn_suggest_toggle = None
                    btn_undo = None
                    history_scroll = None
                # 遊戲結束（勝利或和棋）時的返回菜單按鈕
                elif (board.winner or board.draw_reason) and btn_return_menu and btn_return_menu.is_clicked(mouse_pos):
                    stop_engine()
                    reset_ai_state()
                    reset_eval_state(reset_display=True)
                    reset_suggest_state(reset_display=True)
                    game_state = MODE_MENU
                    board = None
                    btn_return_menu = None
                    btn_main_menu = None
                    btn_suggest_toggle = None
                    btn_undo = None
                    history_scroll = None
                # 未結束遊戲時的操作
                elif not board.winner and not board.draw_reason:
                    # 處理滾輪事件（向上）
                    if event.button == 4:  # 滾輪向上
                        if history_scroll:
                            history_scroll.handle_scroll(-30, len(board.move_notation) * 25)
                    # 處理滾輪事件（向下）
                    elif event.button == 5:  # 滾輪向下
                        if history_scroll:
                            history_scroll.handle_scroll(30, len(board.move_notation) * 25)
                    # 建議著法開關
                    elif btn_suggest_toggle and btn_suggest_toggle.is_clicked(mouse_pos):
                        suggest_enabled = not suggest_enabled
                        btn_suggest_toggle.text = "建議著法：開" if suggest_enabled else "建議著法：關"
                        reset_suggest_state(reset_display=True)
                    # 悔棋按鈕
                    elif btn_undo and btn_undo.is_clicked(mouse_pos):
                        board.undo_last_move()
                        board.selected_piece = None
                        reset_ai_state()
                        reset_eval_state()
                        reset_suggest_state()
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
                                        reset_eval_state()
                                        reset_suggest_state()
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
                    engine_dispatcher.submit(ai_request_id, "bestmove", ai_request_fen, AI_MOVETIME_MS)
                else:
                    ai_enabled = False
                    board.set_warning("AI 引擎初始化失敗")

        # --- 即時評估 ---
        if game_state in (MODE_PVP, MODE_AI) and board and eval_enabled:
            current_fen = board.to_fen()
            if eval_request_id is None and current_fen != eval_last_fen_requested:
                if ensure_engine():
                    eval_last_fen_requested = current_fen
                    eval_request_id = new_request_id()
                    engine_dispatcher.submit(eval_request_id, "analyse", current_fen, AI_EVAL_MOVETIME_MS)
                else:
                    eval_enabled = False
                    board.set_warning("評估引擎初始化失敗")

        # --- 建議著法 ---
        if game_state in (MODE_PVP, MODE_AI) and board and suggest_enabled and not board.winner and not board.draw_reason:
            # AI 模式下，只在玩家回合提供建議
            if game_state == MODE_AI and board.turn != player_color:
                suggest_move = None
            else:
                current_fen = board.to_fen()
                if suggest_request_id is None and current_fen != suggest_last_fen_requested:
                    if ensure_engine():
                        suggest_last_fen_requested = current_fen
                        suggest_request_id = new_request_id()
                        engine_dispatcher.submit(suggest_request_id, "bestmove", current_fen, AI_SUGGEST_MOVETIME_MS)
                    else:
                        suggest_enabled = False
                        if btn_suggest_toggle:
                            btn_suggest_toggle.text = "建議著法：關"
                        board.set_warning("建議引擎初始化失敗")
        elif not suggest_enabled:
            suggest_move = None

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
            btn_pvp.draw(screen, font)
            btn_ai_red.draw(screen, font)
            btn_ai_black.draw(screen, font)
        
        elif game_state == MODE_PVP or game_state == MODE_AI:
            # 繪製遊戲界面
            # 1. 繪製 UI 欄
            pygame.draw.rect(screen, COLOR_UI_BAR, (0, 0, SCREEN_WIDTH, 90))
            
            turn_str = "紅方回合" if board.turn == RED else "黑方回合"
            color = RED if board.turn == RED else WHITE
            screen.blit(font_ui.render(turn_str, True, color), (20, 20))

            mode_text = "模式：雙人" if game_state == MODE_PVP else f"你：{'紅方' if player_color == RED else '黑方'}  AI：{'紅方' if ai_color == RED else '黑方'}"
            screen.blit(font_small.render(mode_text, True, WHITE), (20, 62))

            screen.blit(font_small.render("紅方評分", True, WHITE), (520, 16))
            screen.blit(font_eval.render(eval_text, True, GOLD), (520, 36))

            sugg_text = f"建議: {suggest_move}" if (suggest_enabled and suggest_move) else "建議: --"
            screen.blit(font_small.render(sugg_text, True, WHITE), (520, 72))
            
            # 狀態顯示 (將軍 / 勝利 / 正常)
            if board.winner:
                status = "紅方獲勝！" if board.winner == RED else "黑方獲勝！"
                screen.blit(font_ui.render(status, True, GOLD), (220, 25))
                
                # 創建返回菜單按鈕（如果還沒創建）
                if not btn_return_menu:
                    btn_return_menu = Button(SCREEN_WIDTH // 2 - 80, SCREEN_HEIGHT - 40, 160, 35, "回到菜單")
            elif board.draw_reason:
                # 顯示和棋原因
                draw_text = font.render(board.draw_reason, True, WARNING_COLOR)
                screen.blit(draw_text, (220, 25))
                
                # 創建返回菜單按鈕
                if not btn_return_menu:
                    btn_return_menu = Button(SCREEN_WIDTH // 2 - 80, SCREEN_HEIGHT - 40, 160, 35, "回到菜單")
            elif board.is_check:
                # 顯示閃爍的將軍文字
                if int(time.time() * 2) % 2 == 0: # 簡單的閃爍效果
                    screen.blit(font_warn.render("將軍！", True, GOLD), (250, 20))
            
            # 顯示警告訊息 (例如：不可送將) - 顯示 2 秒
            if board.warning_msg and time.time() - board.warning_timer < 2.0:
                warn_text = font_small.render(board.warning_msg, True, WARNING_COLOR)
                text_rect = warn_text.get_rect(center=(SCREEN_WIDTH//2, 75))
                screen.blit(warn_text, text_rect)

            # 2. 繪製棋盤
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
            history_panel_x = MARGIN_X + BOARD_WIDTH + 20
            history_panel_y = MARGIN_Y
            history_panel_width = SCREEN_WIDTH - history_panel_x - 30
            history_panel_height = BOARD_HEIGHT
            
            # 繪製背景板
            pygame.draw.rect(screen, (220, 210, 190), (history_panel_x, history_panel_y, history_panel_width, history_panel_height))
            pygame.draw.rect(screen, COLOR_LINE, (history_panel_x, history_panel_y, history_panel_width, history_panel_height), 2)
            
            # 標題
            title_text = font_small.render("移動記錄", True, COLOR_LINE)
            screen.blit(title_text, (history_panel_x + 5, history_panel_y + 5))
            
            # 計算可顯示的最大偏移量
            total_lines = len(board.move_notation)
            max_scroll = max(0, total_lines * 25 - (history_panel_height - 40))
            if history_scroll:
                history_scroll.content_height = total_lines * 25 + 40
            
            # 使用裁剪區域限制繪製範圍
            clip_rect = pygame.Rect(history_panel_x, history_panel_y + 35, history_panel_width - 15, history_panel_height - 35)
            screen.set_clip(clip_rect)
            
            # 顯示每一步移動，使用滾動偏移
            scroll_offset = history_scroll.scroll_offset if history_scroll else 0
            y_offset = history_panel_y + 35 - scroll_offset
            
            for i, notation in enumerate(board.move_notation):
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
                p.draw(screen, font, view_color)

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

            if btn_main_menu:
                btn_main_menu.update_hover(mouse_pos)
                btn_main_menu.draw(screen, font_small)

            if btn_suggest_toggle and not board.winner and not board.draw_reason:
                btn_suggest_toggle.update_hover(mouse_pos)
                btn_suggest_toggle.draw(screen, font_small)
            
            if btn_return_menu and (board.winner or board.draw_reason):
                btn_return_menu.update_hover(mouse_pos)
                btn_return_menu.draw(screen, font_small)

        pygame.display.flip()
        clock.tick(30)

if __name__ == "__main__":
    main()
