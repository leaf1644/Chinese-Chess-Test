"""象棋規則、FEN／UCCI、走子與審核。不依賴 pygame。"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass

from .constants import (
    BLACK,
    FEN_TO_PIECE,
    MODE_ENDGAME,
    MODE_PVP,
    PIECE_MAX_COUNT,
    PIECE_TO_FEN,
    RED,
    UCCI_FILES,
    opponent_side,
)
from .i18n import t
from .result import GameResult, ResultKind

def create_empty_xiangqi_board(turn=None):
    """空白棋盤（無子），供編輯器使用。"""
    board = XiangqiBoard(MODE_PVP)
    board.pieces = []
    board.turn = RED if turn is None else turn
    board.selected_piece = None
    board.clear_result()
    board.is_check = False
    board.warning_msg = ""
    board.moves = []
    board.board_state_history = {}
    return board


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


_EDITOR_MSGS = {
    "facing": lambda: t("editor_kings_facing"),
    "red_check": lambda: t("editor_red_in_check"),
    "black_check": lambda: t("editor_black_in_check"),
    "no_move": lambda: t("editor_no_legal_move"),
    "opp_no_move": lambda: t("editor_no_legal_move"),
    "missing_king": lambda: t("editor_need_kings"),
}
_ENDGAME_MSGS = {
    "facing": lambda: "開局將帥照面（非法局面）",
    "red_check": lambda: "開局紅方已被將軍（殘局不應如此）",
    "black_check": lambda: "開局黑方已被將軍（殘局不應如此）",
    "no_move": lambda: "行棋方開局無合法著（已是終局）",
    "opp_no_move": lambda: "對方開局已無合法著（已是困斃／將死）",
    "missing_king": lambda: "開局缺少將或帥",
}


def validate_legal_position(
    board,
    *,
    require_piece_limits=False,
    require_opponent_has_move=False,
    messages=None,
):
    """開局／局面合法性（落點、照面、被將、合法著）。

    require_piece_limits: 編輯器還檢查各兵種數量上限。
    require_opponent_has_move: 殘局還要求對方也有合法著。
    """
    msgs = messages or _ENDGAME_MSGS
    ok_place, reason = validate_endgame_piece_placements(board)
    if not ok_place:
        return False, reason
    if require_piece_limits:
        ok_cnt, reason_cnt = validate_piece_counts(board)
        if not ok_cnt:
            return False, reason_cnt
    if board.is_kings_facing():
        return False, msgs["facing"]()
    if board.is_under_attack(RED):
        return False, msgs["red_check"]()
    if board.is_under_attack(BLACK):
        return False, msgs["black_check"]()
    if not require_piece_limits:
        if not board.get_king(RED) or not board.get_king(BLACK):
            return False, msgs["missing_king"]()
    if not board.has_valid_move(board.turn):
        return False, msgs["no_move"]()
    if require_opponent_has_move:
        opp = opponent_side(board.turn)
        if not board.has_valid_move(opp):
            return False, msgs["opp_no_move"]()
    return True, ""


def validate_editor_position(board):
    """編輯器／自訂開局完整合法性。回傳 (ok, reason)。"""
    return validate_legal_position(
        board,
        require_piece_limits=True,
        messages=_EDITOR_MSGS,
    )


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
    return validate_legal_position(
        board,
        require_opponent_has_move=True,
        messages=_ENDGAME_MSGS,
    )


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


class Piece:
    def __init__(self, name, color, x, y):
        self.name = name
        self.color = color 
        self.x = x
        self.y = y
        self.selected = False



class XiangqiBoard:
    LONG_CHECK_COUNT = 3
    LONG_CHASE_COUNT = 3
    REPEAT_POSITION_LIMIT = 3

    def __init__(self, game_mode=MODE_PVP, fen=None):
        self.pieces = []
        self.turn = RED
        self.selected_piece = None
        self.result = None
        self.winner = None
        self.game_mode = game_mode  # 遊戲模式（PvP / AI / 殘局）
        
        # 狀態訊息
        self.is_check = False      # 是否正在將軍
        self.warning_msg = ""      # 違規提示訊息 (例如：不能送將)
        self.warning_timer = 0     # 訊息顯示計時器
        
        self.moves = []  # list[Move]
        
        # 長將/長捉檢測；draw_reason 與 result 同步（相容舊讀取）
        self.draw_reason = ""
        
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

    def set_result(self, kind, winner=None, message=""):
        """寫入終局結果，並同步 winner／draw_reason。"""
        self.result = GameResult(kind=kind, winner=winner, message=message or "")
        self.winner = winner
        if kind == ResultKind.CHECKMATE:
            self.draw_reason = ""
        else:
            self.draw_reason = message or ""

    def clear_result(self):
        self.result = None
        self.winner = None
        self.draw_reason = ""

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
        self.clear_result()
        self.is_check = self.is_under_attack(self.turn)
        self.warning_msg = ""
        self.warning_timer = 0
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
            self.set_result(ResultKind.LONG_CHECK, winner=next_turn, message=t("msg_long_check", n=n))
            if self.debug:
                print(f"[DEBUG] LONG-CHECK by piece id={id(piece)} indices={indices}")
            return
        first_targets = recent[0].chase_targets
        if first_targets and all(m.is_chase and m.chase_targets == first_targets for m in recent):
            self.set_result(
                ResultKind.LONG_CHASE,
                winner=next_turn,
                message=t("msg_long_chase", n=self.LONG_CHASE_COUNT),
            )
            if self.debug:
                print(f"[DEBUG] LONG-CAPTURE by piece id={id(piece)} targets={first_targets}")

    def _apply_post_move_rules(self, mover, next_turn):
        """走子確認後的終局規則。殘局不套用長將／長捉／重複判罰，但仍記錄局面次數。"""
        if self._enforces_repetition_penalties() and not self.draw_reason:
            self._apply_long_check_or_chase(mover, next_turn)
        if self._enforces_repetition_penalties() and not self.draw_reason:
            if not self.has_crossing_piece(RED) and not self.has_crossing_piece(BLACK):
                self.set_result(ResultKind.NO_CROSSING, winner=None, message=t("msg_no_crossing"))
        if self._enforces_repetition_penalties() and not self.draw_reason and self.check_repeated_steps_draw():
            self.set_result(ResultKind.REPEAT_MOVES, winner=None, message=t("msg_repeat_moves"))

        repeat_state_key = None
        if not self.draw_reason:
            repeat_count = self.check_repeat_position()
            repeat_state_key = self.get_board_state()
            if self._enforces_repetition_penalties() and repeat_count >= self.REPEAT_POSITION_LIMIT:
                self.set_result(
                    ResultKind.REPEAT_POSITION,
                    winner=None,
                    message=t("msg_repeat_pos", n=self.REPEAT_POSITION_LIMIT),
                )

        if not self.draw_reason and not self.has_valid_move(next_turn):
            self.set_result(ResultKind.CHECKMATE, winner=mover.color)
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
            self.set_result(ResultKind.CHECKMATE, winner=piece.color)

        next_turn = opponent_side(self.turn)
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
        enemy_color = opponent_side(attacker.color)
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
        
        self.clear_result()
        
        move = self.moves.pop()
        move.piece.x = move.old_x
        move.piece.y = move.old_y
        if move.captured:
            self.pieces.append(move.captured)
        
        if move.repeat_state_key and move.repeat_state_key in self.board_state_history:
            self.board_state_history[move.repeat_state_key] -= 1
            if self.board_state_history[move.repeat_state_key] <= 0:
                del self.board_state_history[move.repeat_state_key]

        self.turn = opponent_side(self.turn)
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

