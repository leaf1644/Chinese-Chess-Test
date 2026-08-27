"""遊戲應用：共用對局狀態與極薄主迴圈。"""
from __future__ import annotations

import json
import os
import random
import sys
import time

import pygame

from xiangqi.board import (
    Piece,
    XiangqiBoard,
    apply_ucci_move,
    classify_move_quality,
    create_empty_xiangqi_board,
    score_to_cp,
    ucci_pv_to_chinese,
    validate_editor_position,
    validate_endgame_start_position,
)
from xiangqi.constants import (
    AI_DELAY_SEC,
    AI_DIFFICULTY_PRESETS,
    AI_SUGGEST_MOVETIME_MS,
    ANALYSIS_MOVETIME_MS,
    BLACK,
    EDITOR_PALETTE_BLACK,
    EDITOR_PALETTE_RED,
    ENDGAME_AI_DEPTH,
    ENDGAME_AI_MAX_WAIT_SEC,
    ENDGAME_AI_MOVETIME_MS,
    ENDGAME_DIFF_GROUPS,
    ENDGAME_SECTION_CHALLENGE,
    ENDGAME_SECTION_FORMULA,
    MODE_AI,
    MODE_EDITOR,
    MODE_EDITOR_LIB,
    MODE_ENDGAME,
    MODE_ENDGAME_DIFF,
    MODE_ENDGAME_LEVELS,
    MODE_MENU,
    MODE_PVP,
    RED,
    SAVE_FILE_NAME,
    TIME_CONTROL_PRESETS,
)
from xiangqi.engine import (
    DEFAULT_EVAL_MOVETIME_MS as AI_EVAL_MOVETIME_MS,
    EngineDispatcher,
)
from xiangqi.endgame import (
    is_endgame_unlocked,
    load_endgame_progress,
    load_endgames_catalog,
    save_endgame_progress,
)
from xiangqi.i18n import (
    LANG_HANS,
    LANG_HANT,
    ai_difficulty_display,
    diff_group_label,
    difficulty_label,
    get_lang,
    load_language_pref,
    section_label,
    set_language,
    t,
    time_control_label,
)
from xiangqi.paths import get_user_data_dir, get_user_data_path, project_root
from xiangqi.persist import load_custom_positions, save_custom_positions
from ui.assets import load_visual_assets
from ui.dialogs import prompt_text_input
from ui.draw import draw_piece_with_assets
from ui.theme import (
    BOARD_HEIGHT,
    BOARD_WIDTH,
    BOTTOM_BTN_GAP,
    BOTTOM_BTN_H,
    BOTTOM_BTN_MARGIN_X,
    BOTTOM_BTN_Y,
    BUTTON_BORDER,
    BUTTON_TEXT,
    COLOR_BG,
    COLOR_CARD_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_SECONDARY,
    ENDGAME_BACK_Y,
    ENDGAME_LIST_BOTTOM,
    ENDGAME_LIST_LEFT,
    ENDGAME_LIST_TOP,
    ENDGAME_LIST_WIDTH,
    ENDGAME_ROW_H,
    ENDGAME_SCROLLBAR_W,
    FONT_TITLE_CANDIDATES,
    FONT_UI_CANDIDATES,
    GRID_SIZE,
    HISTORY_LINE_H,
    HISTORY_PANEL_GAP,
    HISTORY_PANEL_RIGHT,
    HISTORY_PV_LINE_H,
    MARGIN_X,
    MARGIN_Y,
    MENU_CARD_BTN_GAP,
    MENU_CARD_BTN_START,
    MENU_CARD_PAD_X,
    MENU_COL_GAP,
    MENU_COL_H,
    MENU_COL_TOP,
    MENU_COL_W,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SUCCESS_COLOR,
    WARNING_COLOR,
    get_initial_window_size,
    get_render_rect,
    window_to_logical_pos,
)
from ui.text import format_clock_ms, wrap_text_by_width
from ui.widgets import Button, ScrollBar
from ui.screens.editor import EditorLibraryScreen, EditorScreen
from ui.screens.endgame_select import EndgameDiffScreen, EndgameLevelsScreen
from ui.screens.menu import MenuScreen
from ui.screens.play import PlayScreen


class GameApp:
    def __init__(self):
        pygame.init()
        self.window = pygame.display.set_mode(get_initial_window_size(), pygame.RESIZABLE)
        self.render_rect = get_render_rect(self.window.get_size())
        self.surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("中國象棋 Ver 3.2 (寫實棋盤棋子 + Pikafish)")
        self.clock = pygame.time.Clock()
    
        # 內文／按鈕：清晰黑體；大標題：楷體／書法感
        self.font_names = list(FONT_UI_CANDIDATES)
        self.font_title_names = list(FONT_TITLE_CANDIDATES)
        self.font = pygame.font.SysFont(self.font_names, 30, bold=True)          # 卡片標題
        self.font_body = pygame.font.SysFont(self.font_names, 22)                # 內文說明
        self.font_ui = pygame.font.SysFont(self.font_names, 38, bold=True)
        self.font_eval = pygame.font.SysFont(self.font_names, 48, bold=True)
        self.font_small = pygame.font.SysFont(self.font_names, 22)
        self.font_badge = pygame.font.SysFont(self.font_names, 18)
        self.font_warn = pygame.font.SysFont(self.font_names, 46, bold=True)
        self.font_banner = pygame.font.SysFont(self.font_names, 34, bold=True)  # 頂欄紅字提示
        self.font_menu = pygame.font.SysFont(self.font_title_names, 60)           # 主標題（書法／楷體）
        self.font_subtitle = pygame.font.SysFont(self.font_names, 26)            # 副標（細／灰）
        self.board_surface, self.piece_sprites, self.board_from_asset = load_visual_assets(self.font_names)
    
        # 遊戲狀態
        self.goto(MODE_MENU)  # 初始化為菜單狀態
        self.board = None
        self.history_scroll = None  # 移動歷史滾動條

        self.player_color = RED
        self.ai_color = BLACK
        self.view_color = RED

        # 殘局闖關
        self.endgame_levels, self.endgame_load_error = load_endgames_catalog()
        self.endgame_progress = load_endgame_progress()
        self.endgame_cleared = set(self.endgame_progress.get("cleared", []))
        self.endgame_current = None  # 目前關卡 dict
        self.endgame_player_moves = 0
        self.endgame_status = ""  # "", "cleared", "failed"
        self.endgame_list_scroll = 0
        self.endgame_level_buttons = []  # [(Button, level_dict|"locked")] 僅關卡列（不含返回）
        self.endgame_diff_buttons = []   # [(Button, group_dict)] 難度分組選單
        self.endgame_filter_group = None  # 目前選中的難度分組 dict（ENDGAME_DIFF_GROUPS 元素）
        self.endgame_active_section = ENDGAME_SECTION_FORMULA  # formula / challenge
        self.btn_endgame_menu = None      # 殘局闖關
        self.btn_formula_menu = None      # 定式訓練
        self.btn_endgame_back = None
        self.btn_endgame_hint = None
        self.btn_endgame_retry = None
        self.btn_endgame_levels = None
        self.endgame_list_scrollbar = None

        self.engine_dispatcher = None
        self.request_seq = 0

        self.ai_enabled = True
        self.ai_wait_until = 0.0
        self.ai_request_id = None
        self.ai_request_fen = None
        self.ai_difficulty_order = ["簡單", "中等", "困難"]
        self.ai_difficulty = "中等"
        self.ai_search_depth = AI_DIFFICULTY_PRESETS[self.ai_difficulty]["depth"]
        self.ai_movetime_ms = AI_DIFFICULTY_PRESETS[self.ai_difficulty]["movetime_ms"]
        self.ai_max_wait_sec = AI_DIFFICULTY_PRESETS[self.ai_difficulty].get("max_wait_sec")
        self.ai_mistake_rate = AI_DIFFICULTY_PRESETS[self.ai_difficulty].get("mistake_rate", 0.0)

        self.eval_enabled = True
        self.eval_request_id = None
        self.eval_last_fen_requested = None
        self.eval_red_score_cp = 0
        self.eval_text = "+0"

        self.suggest_enabled = False
        self.suggest_request_id = None
        self.suggest_last_fen_requested = None
        self.suggest_move = None
        self.btn_difficulty = None
        self.save_file_path = get_user_data_path(SAVE_FILE_NAME)
        self.draw_offer_popup = None  # {"from_color": RED/BLACK}
        self.btn_draw_accept = None
        self.btn_draw_reject = None
        self.replay_mode_active = False
        self.replay_record_moves = []
        self.replay_record_notation = []
        self.replay_finished_winner = None
        self.replay_finished_draw_reason = ""
        self.replay_snapshots = []
        self.replay_index = None  # None = 顯示最新局面；數字 = 顯示第 N 手後局面（0 為初始）
        self.game_start_fen = None  # 本局起始 FEN（標準開局或載入局面）；復盤／賽後分析必須由此重建

        # --- 棋鐘 ---
        self.time_control_idx = 0  # TIME_CONTROL_PRESETS 索引
        self.clock_enabled = False
        self.clock_red_ms = 0.0
        self.clock_black_ms = 0.0
        self.clock_inc_ms = 0
        self.clock_last_tick = None  # time.time()

        # --- 賽後分析 ---
        self.analysis_results = []  # list[dict] 與 move index 對齊
        self.analysis_status = "idle"  # idle | running | done | error
        self.analysis_progress = 0
        self.analysis_total = 0
        self.analysis_error = ""
        self.analysis_request_id = None
        self.analysis_queue = []  # 待分析 (ply_index, fen_before, fen_after, move, notation)
        self.analysis_pending_ply = None
        self.analysis_phase = None  # "before" | "after"
        self.analysis_before_cache = None
        self.btn_analyze = None

        # --- 局面編輯器 ---
        self.editor_selected = None  # (name, color) | "erase"  # 調色盤選取
        self.editor_board_pick = None  # 盤上選取待移動的 Piece 實例
        self.editor_message = ""  # 僅顯示錯誤／重要操作結果
        self.editor_saved_list = []
        self.editor_lib_selected = None  # 局面庫選中 id
        self.editor_lib_scroll = 0
        self.editor_lib_buttons = []  # [(Button, pos_dict)]
        self.btn_editor_back = None
        self.btn_editor_turn = None
        self.btn_editor_erase = None
        self.btn_editor_clear = None
        self.btn_editor_initial = None
        self.btn_editor_save = None
        self.btn_editor_load = None
        self.btn_editor_play_pvp = None
        self.btn_editor_play_ai = None
        self.btn_lib_back = None
        self.btn_lib_to_edit = None
        self.btn_lib_pvp = None
        self.btn_lib_ai = None
        self.btn_lib_rename = None
        self.btn_lib_delete = None
















































































        # 載入語言偏好並建立主選單（左→右：對戰｜AI｜殘局）
        set_language(load_language_pref())  # 啟動時寫入失敗可忽略，至少記憶體內已套用
        pygame.display.set_caption(t("app_caption"))
        self.menu_status_msg = ""
        self.menu_status_until = 0.0



        # 先建立按鈕實例，再套用三欄座標（btn_difficulty 改在人機對局內建立）
        self.btn_pvp = Button(0, 0, 100, 40, t("pvp"))
        self.btn_ai_red = Button(0, 0, 100, 40, t("ai_red"))
        self.btn_ai_black = Button(0, 0, 100, 40, t("ai_black"))
        self.btn_formula_menu = Button(0, 0, 100, 40, t("formula"))
        self.btn_endgame_menu = Button(0, 0, 100, 40, t("challenge"))
        self.btn_editor_menu = Button(0, 0, 100, 40, t("editor"))
        self.btn_difficulty = None
        self.btn_menu_load = Button(0, 0, 100, 40, t("load_save"))
        self.btn_clock = Button(0, 0, 100, 40, t("clock", label=time_control_label(self.current_time_control())))
        self.btn_quit = Button(0, 0, 100, 40, t("quit"))
        self.btn_quit.ghost = True
        self.btn_lang = Button(0, 0, 100, 40, t("lang_chip"))
        self.layout_menu_buttons()


        self.btn_undo = None  # 悔棋按鈕會在遊戲中建立
        self.btn_main_menu = None  # 遊戲中隨時返回主選單
        self.btn_suggest_toggle = None  # 建議著法開關
        self.btn_save_game = None
        self.btn_load_game = None
        self.btn_draw_offer = None
        self.btn_replay_mode = None
        self.btn_analyze = None
        self.btn_endgame_back = None
        self.goto(MODE_MENU)

    def goto(self, mode, *, play_mode=None):
        """切換目前 Screen，並同步 game_state（存檔／棋規仍用整數）。"""
        self.game_state = mode
        if mode == MODE_MENU:
            self.screen = MenuScreen(self)
        elif mode == MODE_ENDGAME_DIFF:
            self.screen = EndgameDiffScreen(self)
        elif mode == MODE_ENDGAME_LEVELS:
            self.screen = EndgameLevelsScreen(self)
        elif mode == MODE_EDITOR:
            self.screen = EditorScreen(self)
        elif mode == MODE_EDITOR_LIB:
            self.screen = EditorLibraryScreen(self)
        elif mode in (MODE_PVP, MODE_AI, MODE_ENDGAME):
            self.screen = PlayScreen(self, mode)
        else:
            self.screen = MenuScreen(self)

    def reset_ai_state(self):
        self.ai_wait_until = 0.0
        self.ai_request_id = None
        self.ai_request_fen = None


    def apply_ai_difficulty(self, level):
        cfg = AI_DIFFICULTY_PRESETS[level]
        self.ai_difficulty = level
        self.ai_search_depth = cfg.get("depth")
        self.ai_movetime_ms = cfg.get("movetime_ms")
        self.ai_max_wait_sec = cfg.get("max_wait_sec")
        self.ai_mistake_rate = cfg.get("mistake_rate", 0.0)
        if self.btn_difficulty:
            self.btn_difficulty.text = t("ai_difficulty", level=ai_difficulty_display(self.ai_difficulty))


    def cycle_ai_difficulty(self):
        """循環切換 AI 難度；對局中立刻生效（取消進行中的 AI 搜尋）。"""
        idx = self.ai_difficulty_order.index(self.ai_difficulty)
        next_level = self.ai_difficulty_order[(idx + 1) % len(self.ai_difficulty_order)]
        self.apply_ai_difficulty(next_level)
        # 若正輪到 AI，以新難度重新搜尋
        if self.game_state in (MODE_AI, MODE_ENDGAME) and self.board and self.ai_enabled and self.board.turn == self.ai_color:
            if not self.board.winner and not self.board.draw_reason and not self.endgame_status:
                self.reset_ai_state()
        if self.board:
            self.board.set_warning(t("ai_diff_changed", level=ai_difficulty_display(self.ai_difficulty)))
        return next_level


    def get_history_panel_rects(self):
        """棋盤偏左後，右側移動記錄佔滿剩餘寬度。"""
        panel_x = MARGIN_X + BOARD_WIDTH + HISTORY_PANEL_GAP
        panel_y = MARGIN_Y
        panel_width = max(220, SCREEN_WIDTH - panel_x - HISTORY_PANEL_RIGHT)
        # 略高於棋盤，方便顯示多行變例
        panel_height = BOARD_HEIGHT + 24
        clip_rect = pygame.Rect(panel_x + 6, panel_y + 38, panel_width - 28, panel_height - 46)
        return panel_x, panel_y, panel_width, panel_height, clip_rect


    def make_history_scrollbar(self):
        """建立貼齊移動記錄面板右側的滾動條。"""
        _px, _py, panel_w, panel_h, clip_rect = self.get_history_panel_rects()
        bar = ScrollBar(clip_rect.right + 2, clip_rect.y, 12, clip_rect.height, max(clip_rect.height + 1, 1000))
        return bar


    def get_display_notation_list(self):
        if self.replay_mode_active and self.replay_record_notation:
            return self.replay_record_notation
        if self.board:
            return self.board.move_notation
        return []


    def get_history_row_heights(self, font_for_wrap=None):
        """
        計算移動記錄每列像素高度（含展開的變例折行）。
        回傳 (heights:list[int], total:int, pv_lines_map:dict[int,list[str]])
        """
        notation_list = self.get_display_notation_list()
        panel_x, panel_y, panel_width, panel_height, clip_rect = self.get_history_panel_rects()
        wrap_font = font_for_wrap or self.font_badge
        max_pv_w = max(80, clip_rect.width - 8)
        heights = []
        pv_map = {}
        for i, _notation in enumerate(notation_list):
            h = HISTORY_LINE_H
            show_pv = (
                self.replay_mode_active
                and self.replay_index == i + 1
                and i < len(self.analysis_results)
                and self.analysis_results[i]
                and self.analysis_results[i].get("pv")
            )
            if show_pv:
                raw = str(self.analysis_results[i]["pv"])
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


    def get_history_max_scroll(self):
        _heights, total, _pv = self.get_history_row_heights()
        panel_x, panel_y, panel_width, panel_height, clip_rect = self.get_history_panel_rects()
        return max(0, total - clip_rect.height + 8)


    def get_notation_index_at_pos(self, pos):
        if not self.board:
            return None
        panel_x, panel_y, panel_width, panel_height, clip_rect = self.get_history_panel_rects()
        if not clip_rect.collidepoint(pos):
            return None
        scroll_offset = self.history_scroll.scroll_offset if self.history_scroll else 0
        y_in_list = pos[1] - clip_rect.y + scroll_offset
        if y_in_list < 0:
            return None
        heights, _total, _pv = self.get_history_row_heights()
        acc = 0
        for i, h in enumerate(heights):
            if acc <= y_in_list < acc + h:
                return i
            acc += h
        return None


    def make_board_snapshot(self):
        if not self.board:
            return None
        return {
            "pieces": [(p.name, p.color, p.x, p.y) for p in self.board.pieces],
            "turn": self.board.turn,
        }


    def reset_replay_history(self):
        self.replay_snapshots = []
        self.replay_index = None
        self.replay_mode_active = False
        snap = self.make_board_snapshot()
        if snap:
            self.replay_snapshots.append(snap)


    def append_replay_snapshot(self):
        snap = self.make_board_snapshot()
        if snap:
            self.replay_snapshots.append(snap)
        self.replay_index = None


    def sync_replay_history_after_undo(self):
        if not self.board:
            self.replay_snapshots = []
            self.replay_index = None
            return
        expected = len(self.board.move_notation) + 1
        if len(self.replay_snapshots) > expected:
            self.replay_snapshots = self.replay_snapshots[:expected]
        elif len(self.replay_snapshots) < expected:
            # 理論上不應發生，保底重置為當前局面。
            self.replay_snapshots = [self.make_board_snapshot()]
        self.replay_index = None


    def restore_game_to_step(self, step_idx, source_moves=None):
        if not self.board:
            return False

        all_moves = list(source_moves) if source_moves is not None else list(self.board.move_ucci_history)
        step_idx = max(0, min(step_idx, len(all_moves)))

        mode = self.board.game_mode if self.board.game_mode in (MODE_PVP, MODE_AI, MODE_ENDGAME) else MODE_PVP
        try:
            if self.game_start_fen:
                rebuilt = XiangqiBoard(mode, fen=self.game_start_fen)
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
        self.board = rebuilt
        self.replay_snapshots = new_snapshots
        self.replay_index = step_idx
        self.reset_ai_state()
        self.reset_eval_state(reset_display=True)
        self.reset_suggest_state(reset_display=True)
        self.close_draw_offer_popup()
        return True


    def current_time_control(self):
        return TIME_CONTROL_PRESETS[self.time_control_idx % len(TIME_CONTROL_PRESETS)]


    def cycle_time_control(self):
        self.time_control_idx = (self.time_control_idx + 1) % len(TIME_CONTROL_PRESETS)
        if self.btn_clock:
            self.btn_clock.text = t("clock", label=time_control_label(self.current_time_control()))


    def init_clocks_for_game(self):
        preset = self.current_time_control()
        if preset["base_sec"] <= 0:
            self.clock_enabled = False
            self.clock_red_ms = 0
            self.clock_black_ms = 0
            self.clock_inc_ms = 0
            self.clock_last_tick = None
            return
        self.clock_enabled = True
        self.clock_red_ms = float(preset["base_sec"] * 1000)
        self.clock_black_ms = float(preset["base_sec"] * 1000)
        self.clock_inc_ms = int(preset["inc_sec"] * 1000)
        self.clock_last_tick = time.time()


    def apply_clock_increment_for_last_mover(self):
        if not self.clock_enabled or not self.board or self.clock_inc_ms <= 0:
            return
        # move_piece 後 turn 已切到對手，故剛走完的是「非 turn」方
        mover = BLACK if self.board.turn == RED else RED
        if mover == RED:
            self.clock_red_ms += self.clock_inc_ms
        else:
            self.clock_black_ms += self.clock_inc_ms


    def tick_clocks(self):
        """每幀扣除行棋方用時；超時判負。"""
        if not self.clock_enabled or not self.board:
            return
        if self.board.winner or self.board.draw_reason or self.replay_mode_active or self.endgame_status:
            self.clock_last_tick = time.time()
            return
        if self.game_state not in (MODE_PVP, MODE_AI):
            return
        now = time.time()
        if self.clock_last_tick is None:
            self.clock_last_tick = now
            return
        dt_ms = (now - self.clock_last_tick) * 1000.0
        self.clock_last_tick = now
        if dt_ms <= 0:
            return
        if self.board.turn == RED:
            self.clock_red_ms -= dt_ms
            if self.clock_red_ms <= 0:
                self.clock_red_ms = 0
                self.board.winner = BLACK
                self.board.draw_reason = t("timeout_red")
                self.board.set_warning(t("timeout_red"))
                self.capture_finished_record_if_needed()
        else:
            self.clock_black_ms -= dt_ms
            if self.clock_black_ms <= 0:
                self.clock_black_ms = 0
                self.board.winner = RED
                self.board.draw_reason = t("timeout_black")
                self.board.set_warning(t("timeout_black"))
                self.capture_finished_record_if_needed()


    def reset_analysis_state(self):
        self.analysis_results = []
        self.analysis_status = "idle"
        self.analysis_progress = 0
        self.analysis_total = 0
        self.analysis_error = ""
        self.analysis_request_id = None
        self.analysis_queue = []
        self.analysis_pending_ply = None
        self.analysis_phase = None
        self.analysis_before_cache = None


    def build_analysis_queue_from_record(self):
        """由完整棋譜重建每步前後 FEN（支援自訂起始局面）。"""
        moves = list(self.replay_record_moves) if self.replay_record_moves else (list(self.board.move_ucci_history) if self.board else [])
        notations = list(self.replay_record_notation) if self.replay_record_notation else (list(self.board.move_notation) if self.board else [])
        if not moves:
            return []
        mode = MODE_PVP
        if self.board and self.board.game_mode in (MODE_PVP, MODE_AI, MODE_ENDGAME):
            mode = self.board.game_mode
        try:
            if self.game_start_fen:
                b = XiangqiBoard(mode, fen=self.game_start_fen)
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


    def start_postgame_analysis(self):
        self.capture_finished_record_if_needed()
        items = self.build_analysis_queue_from_record()
        if not items:
            if self.board:
                self.board.set_warning(t("analyze_need_game"))
            return False
        if not self.ensure_engine():
            if self.board:
                self.board.set_warning(t("analyze_fail", err="engine"))
            return False
        self.analysis_queue = items
        self.analysis_results = [None] * len(items)
        self.analysis_progress = 0
        self.analysis_total = len(items)
        self.analysis_status = "running"
        self.analysis_error = ""
        self.analysis_request_id = None
        self.analysis_pending_ply = None
        self.analysis_phase = None
        self.analysis_before_cache = None
        if self.board:
            self.board.set_warning(t("analyzing", cur=0, total=self.analysis_total))
        self._submit_next_analysis_task()
        return True


    def _submit_next_analysis_task(self):
        if self.analysis_status != "running" or not self.analysis_queue:
            return
        # 找下一個未完成的 ply
        next_item = None
        for item in self.analysis_queue:
            if self.analysis_results[item["ply"]] is None:
                next_item = item
                break
        if next_item is None:
            self.analysis_status = "done"
            self.analysis_request_id = None
            if self.board:
                self.board.set_warning(t("analyze_done"))
            return
        if not self.ensure_engine():
            self.analysis_status = "error"
            self.analysis_error = "engine"
            return
        self.analysis_pending_ply = next_item["ply"]
        self.analysis_phase = "before"
        self.analysis_request_id = self.new_request_id()
        self.engine_dispatcher.submit(
            self.analysis_request_id,
            "analyse_full",
            next_item["fen_before"],
            ANALYSIS_MOVETIME_MS,
        )


    def handle_analysis_result(self, payload):
        """處理一步分析（before → after → 彙總）。"""
        if self.analysis_pending_ply is None or self.analysis_pending_ply >= len(self.analysis_queue):
            return
        item = self.analysis_queue[self.analysis_pending_ply]
        if self.analysis_phase == "before":
            self.analysis_before_cache = payload
            self.analysis_phase = "after"
            self.analysis_request_id = self.new_request_id()
            self.engine_dispatcher.submit(
                self.analysis_request_id,
                "analyse_full",
                item["fen_after"],
                ANALYSIS_MOVETIME_MS,
            )
            return

        # phase after
        before = self.analysis_before_cache or {}
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
        self.analysis_results[item["ply"]] = {
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
        self.analysis_progress = sum(1 for r in self.analysis_results if r is not None)
        self.analysis_before_cache = None
        self.analysis_phase = None
        self.analysis_request_id = None
        if self.board:
            self.board.set_warning(t("analyzing", cur=self.analysis_progress, total=self.analysis_total))
        self._submit_next_analysis_task()


    def analysis_label_text(self, label_key):
        return {
            "best": t("label_best"),
            "good": t("label_good"),
            "mistake": t("label_mistake"),
            "blunder": t("label_blunder"),
        }.get(label_key, t("label_unknown"))


    def analysis_label_color(self, label_key):
        return {
            "best": SUCCESS_COLOR,
            "good": (88, 118, 150),
            "mistake": (176, 128, 64),
            "blunder": WARNING_COLOR,
        }.get(label_key, COLOR_TEXT_SECONDARY)


    def on_move_applied(self):
        self.reset_eval_state()
        self.reset_suggest_state()
        self.append_replay_snapshot()
        # 棋鐘：剛走完的一方加秒
        self.apply_clock_increment_for_last_mover()
        # 新著法使舊分析失效
        if self.analysis_status == "done":
            self.reset_analysis_state()


    def capture_finished_record_if_needed(self):
        if not self.board:
            return
        if not (self.board.winner or self.board.draw_reason):
            return
        if self.replay_record_moves:
            return
        self.replay_record_moves = list(self.board.move_ucci_history)
        self.replay_record_notation = list(self.board.move_notation)
        self.replay_finished_winner = self.board.winner
        self.replay_finished_draw_reason = self.board.draw_reason


    def enter_replay_mode(self, step_idx=None):
        if not self.board:
            return False
        self.capture_finished_record_if_needed()
        if not self.replay_record_notation and not self.replay_record_moves:
            self.board.set_warning(t("msg_replay_empty"))
            return False

        if step_idx is None:
            step_idx = len(self.replay_record_moves)
        if not self.restore_game_to_step(step_idx, source_moves=self.replay_record_moves):
            self.board.set_warning(t("msg_replay_enter_fail"))
            return False

        self.replay_mode_active = True
        self.ai_enabled = False
        if self.btn_replay_mode:
            self.btn_replay_mode.text = t("msg_replay_on")
        self.board.set_warning(t("msg_replay_enter", n=step_idx))
        return True


    def color_to_str(self, color):
        return "red" if color == RED else "black"


    def str_to_color(self, token, default):
        if token == "red":
            return RED
        if token == "black":
            return BLACK
        return default


    def layout_bottom_bar(self, button_specs, y=None, height=None, gap=None, margin_x=None):
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


    def setup_in_game_buttons(self, for_endgame=False):
        # 先建立實例，再由 layout_bottom_bar 統一等距排版
        self.btn_undo = Button(0, 0, 140, BOTTOM_BTN_H, t("undo"))
        self.btn_main_menu = Button(0, 0, 160, BOTTOM_BTN_H, t("main_menu"))
        suggest_label = t("suggest_on") if self.suggest_enabled else t("suggest_off")
        self.btn_suggest_toggle = Button(0, 0, 200, BOTTOM_BTN_H, suggest_label)
        if for_endgame:
            self.btn_save_game = None
            self.btn_load_game = None
            self.btn_draw_offer = None
            self.btn_replay_mode = None
            self.btn_analyze = None
            self.btn_difficulty = None
            self.btn_suggest_toggle = None  # 殘局不顯示建議
            self.btn_endgame_hint = None
            self.btn_endgame_retry = Button(0, 0, 120, BOTTOM_BTN_H, t("retry"))
            self.btn_endgame_levels = Button(0, 0, 160, BOTTOM_BTN_H, t("level_list"))
            self.layout_bottom_bar([
                (self.btn_endgame_retry, 120),
                (self.btn_undo, 140),
                (self.btn_main_menu, 160),
                (self.btn_endgame_levels, 160),
            ])
        else:
            self.btn_save_game = Button(0, 0, 110, BOTTOM_BTN_H, t("save"))
            self.btn_load_game = Button(0, 0, 110, BOTTOM_BTN_H, t("load"))
            self.btn_draw_offer = Button(915, 12, 170, 32, t("draw_offer"))
            self.btn_replay_mode = Button(915, 50, 170, 32, t("replay"))
            self.btn_analyze = Button(915, 88, 170, 32, t("analyze"))
            # AI 難度改在對局內切換（雙人模式不顯示）
            if self.game_state == MODE_AI:
                self.btn_difficulty = Button(
                    915, 126, 170, 32,
                    t("ai_difficulty", level=ai_difficulty_display(self.ai_difficulty)),
                )
            else:
                self.btn_difficulty = None
            self.btn_endgame_hint = None
            self.btn_endgame_retry = None
            self.btn_endgame_levels = None
            # 底部五鍵：等間距、水平置中
            self.layout_bottom_bar([
                (self.btn_save_game, 110),
                (self.btn_load_game, 110),
                (self.btn_suggest_toggle, 200),
                (self.btn_undo, 140),
                (self.btn_main_menu, 160),
            ])


    def endgame_levels_in_section(self, section=None):
        """目前區塊（定式訓練／殘局闖關）內的關卡。"""
        sec = section if section is not None else self.endgame_active_section
        return [lv for lv in self.endgame_levels if lv.get("section", ENDGAME_SECTION_FORMULA) == sec]


    def endgame_levels_for_group(self, group=None):
        """依「目前區塊 + 難度分組」篩選關卡；group=None 時回傳該區塊全部。

        group 為 ENDGAME_DIFF_GROUPS 的元素（含 difficulties 元組）。
        """
        base = self.endgame_levels_in_section()
        if group is None:
            return list(base)
        allowed = set(int(d) for d in group.get("difficulties", ()))
        return [lv for lv in base if int(lv.get("difficulty") or 1) in allowed]


    def endgame_available_groups(self):
        """回傳目前區塊內有關卡的難度分組列表。"""
        present = {int(lv.get("difficulty") or 1) for lv in self.endgame_levels_in_section()}
        groups = []
        for g in ENDGAME_DIFF_GROUPS:
            if any(int(d) in present for d in g["difficulties"]):
                groups.append(g)
        return groups


    def endgame_list_viewport_height(self):
        return max(80, ENDGAME_LIST_BOTTOM - ENDGAME_LIST_TOP)


    def endgame_list_content_height(self):
        n = len(self.endgame_levels_for_group(self.endgame_filter_group))
        return max(self.endgame_list_viewport_height(), n * ENDGAME_ROW_H)


    def endgame_list_max_scroll(self):
        return max(0, self.endgame_list_content_height() - self.endgame_list_viewport_height())


    def rebuild_endgame_list_scrollbar(self):
        list_h = self.endgame_list_viewport_height()
        content_h = self.endgame_list_content_height()
        bar_x = ENDGAME_LIST_LEFT + ENDGAME_LIST_WIDTH + 8
        self.endgame_list_scrollbar = ScrollBar(
            bar_x, ENDGAME_LIST_TOP, ENDGAME_SCROLLBAR_W, list_h, max(list_h + 1, content_h)
        )
        self.endgame_list_scrollbar.scroll_offset = min(self.endgame_list_scroll, self.endgame_list_max_scroll())
        self.endgame_list_scrollbar.content_height = content_h


    def build_endgame_diff_buttons(self):
        """建立難度分組選擇按鈕（入門／初級合併）。"""
        self.btn_endgame_back = Button(
            SCREEN_WIDTH // 2 - 150, ENDGAME_BACK_Y, 300, 48, t("back_menu")
        )
        self.endgame_diff_buttons = []
        groups = self.endgame_available_groups()
        if not groups:
            return
        btn_h = 56
        gap = 14
        start_y = ENDGAME_LIST_TOP
        for i, group in enumerate(groups):
            levels_g = self.endgame_levels_for_group(group)
            cleared_n = sum(1 for lv in levels_g if lv["id"] in self.endgame_cleared)
            label = t(
                "group_progress",
                label=diff_group_label(group),
                cleared=cleared_n,
                total=len(levels_g),
            )
            y = start_y + i * (btn_h + gap)
            btn = Button(ENDGAME_LIST_LEFT, y, ENDGAME_LIST_WIDTH, btn_h, label)
            self.endgame_diff_buttons.append((btn, group))


    def build_endgame_level_buttons(self):
        """建立「目前難度分組」下的關卡列按鈕（位置隨 scroll 更新）。"""
        self.endgame_list_scroll = max(0, min(self.endgame_list_scroll, self.endgame_list_max_scroll()))
        back_label = t("back_diff") if self.endgame_filter_group is not None else t("back_menu")
        self.btn_endgame_back = Button(
            SCREEN_WIDTH // 2 - 150, ENDGAME_BACK_Y, 300, 48, back_label
        )
        self.endgame_level_buttons = []
        filtered = self.endgame_levels_for_group(self.endgame_filter_group)
        # 同組內：先按 difficulty 再按 id，入門排在初級前
        filtered = sorted(
            filtered,
            key=lambda lv: (int(lv.get("difficulty") or 1), str(lv.get("id") or "")),
        )
        for i, level in enumerate(filtered):
            unlocked = is_endgame_unlocked(level, self.endgame_cleared)
            cleared = level["id"] in self.endgame_cleared
            mark = t("cleared_tag") if cleared else (t("locked_tag") if not unlocked else f"{i+1:02d}")
            sub = difficulty_label(int(level.get("difficulty") or 1))
            label = f"{mark}  {level['title']}  [{sub}]"
            if len(label) > 34:
                label = label[:33] + "…"
            y = ENDGAME_LIST_TOP + i * ENDGAME_ROW_H - self.endgame_list_scroll
            btn = Button(ENDGAME_LIST_LEFT, y, ENDGAME_LIST_WIDTH, ENDGAME_ROW_H - 8, label)
            self.endgame_level_buttons.append((btn, level if unlocked else "locked"))
        if self.endgame_list_scrollbar:
            self.endgame_list_scrollbar.scroll_offset = self.endgame_list_scroll
            self.endgame_list_scrollbar.content_height = self.endgame_list_content_height()


    def open_endgame_diff_select(self, section=None):
        """進入殘局／定式：先選難度分組。"""
        self.stop_engine()
        self.reset_ai_state()
        self.reset_eval_state(reset_display=True)
        self.reset_suggest_state(reset_display=True)
        self.board = None
        self.endgame_current = None
        self.endgame_status = ""
        self.endgame_list_scroll = 0
        self.endgame_filter_group = None
        self.endgame_level_buttons = []
        self.endgame_list_scrollbar = None
        if section is not None:
            self.endgame_active_section = section
        self.goto(MODE_ENDGAME_DIFF)
        self.build_endgame_diff_buttons()


    def open_endgame_level_select(self, group):
        """進入指定難度分組的關卡列表。"""
        self.endgame_filter_group = group
        self.endgame_list_scroll = 0
        self.goto(MODE_ENDGAME_LEVELS)
        self.rebuild_endgame_list_scrollbar()
        self.build_endgame_level_buttons()


    def mark_endgame_cleared(self, level_id):
        if level_id not in self.endgame_cleared:
            self.endgame_cleared.add(level_id)
            self.endgame_progress = {"cleared": sorted(self.endgame_cleared)}
            ok, err = save_endgame_progress(self.endgame_progress)
            if not ok and self.board:
                self.board.set_warning(t("msg_progress_fail", err=err))


    def check_endgame_result(self):
        """檢查殘局是否過關／失敗。

        過關只認「將死／困斃對手」（board.winner == 玩家），
        不是開局就把對方將吃掉。
        """
        if not self.board or not self.endgame_current or self.endgame_status:
            return
        goal = self.endgame_current.get("goal") or "checkmate"
        # 先處理「有和棋／違規原因」的情形（長將、長捉、重複局面等），避免誤顯示成「被將死」
        if self.board.draw_reason:
            if self.board.winner == self.player_color:
                # 極少見：有原因字串但玩家仍勝
                self.endgame_status = "cleared"
                self.mark_endgame_cleared(self.endgame_current["id"])
                self.board.set_warning(t("msg_endgame_pass"))
            else:
                self.endgame_status = "failed"
                self.board.set_warning(t("msg_endgame_fail_reason", reason=self.board.draw_reason))
            return
        if goal == "checkmate" and self.board.winner == self.player_color:
            self.endgame_status = "cleared"
            self.mark_endgame_cleared(self.endgame_current["id"])
            self.board.set_warning(t("msg_endgame_mate_pass"))
            return
        if self.board.winner and self.board.winner != self.player_color:
            self.endgame_status = "failed"
            self.board.set_warning(t("msg_endgame_fail_mated"))
            return
        max_moves = self.endgame_current.get("max_player_moves")
        if max_moves is not None:
            try:
                max_moves = int(max_moves)
            except (TypeError, ValueError):
                max_moves = None
        # 已達步數上限仍未將死 → 失敗（若本步已將死，上方已判定過關）
        if max_moves is not None and self.endgame_player_moves >= max_moves:
            self.endgame_status = "failed"
            self.board.set_warning(t("msg_endgame_fail_limit", n=max_moves))


    def start_session(self, 
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

        for_endgame = mode == MODE_ENDGAME or endgame_level is not None
        if clocks is None:
            clocks = not for_endgame

        self.stop_engine()
        self.reset_ai_state()
        self.reset_eval_state(reset_display=True)
        self.reset_suggest_state(reset_display=True)
        self.reset_analysis_state()

        def _fail_endgame_load(msg):
            print(msg)
            self.board = None
            self.goto(MODE_ENDGAME_LEVELS)
            self.rebuild_endgame_list_scrollbar()
            self.build_endgame_level_buttons()

        try:
            new_board = XiangqiBoard(mode, fen=fen)
        except Exception as ex:
            if for_endgame:
                level_id = (endgame_level or {}).get("id")
                _fail_endgame_load(f"[endgame] 載入失敗 {level_id}: {ex}")
                return False
            if self.board:
                self.board.set_warning(t("msg_fen_fail", err=ex))
            return False

        if validate == "editor":
            ok, reason = validate_editor_position(new_board)
            if not ok:
                self.board = new_board
                self.board.set_warning(t("editor_invalid", reason=reason))
                return False
        elif validate == "endgame" or for_endgame:
            ok, reason = validate_endgame_start_position(new_board)
            if not ok:
                level_id = (endgame_level or {}).get("id")
                _fail_endgame_load(f"[endgame] 非法開局 {level_id}: {reason}")
                return False

        self.board = new_board
        self.game_start_fen = self.board.to_fen()
        self.goto(mode)
        self.eval_enabled = True
        self.suggest_enabled = False

        if mode == MODE_PVP:
            self.ai_enabled = False
            self.player_color = RED
            self.ai_color = BLACK
            self.view_color = RED if view is None else view
        else:
            self.ai_enabled = True
            self.player_color = human_side
            if opponent is not None and opponent != human_side:
                self.ai_color = opponent
            else:
                self.ai_color = BLACK if human_side == RED else RED
            self.view_color = human_side if view is None else view
            if mode == MODE_AI:
                self.apply_ai_difficulty(self.ai_difficulty)

        if for_endgame and endgame_level is not None:
            self.endgame_current = endgame_level
            self.endgame_player_moves = 0
            self.endgame_status = ""
        elif not for_endgame:
            self.endgame_current = None
            self.endgame_status = ""
            self.endgame_player_moves = 0

        self.history_scroll = self.make_history_scrollbar()
        self.setup_in_game_buttons(for_endgame=for_endgame)
        self.reset_replay_history()
        self.replay_record_moves = []
        self.replay_record_notation = []
        self.replay_finished_winner = None
        self.replay_finished_draw_reason = ""
        self.replay_index = None
        self.replay_mode_active = False
        self.draw_offer_popup = None
        self.btn_draw_accept = None
        self.btn_draw_reject = None

        if clocks:
            self.init_clocks_for_game()
        else:
            self.clock_enabled = False
            self.clock_last_tick = None

        if warning:
            self.board.set_warning(warning)
        return True


    def start_endgame_level(self, level):
        human = RED if level.get("player_side") != "black" else BLACK
        return self.start_session(
            MODE_ENDGAME,
            fen=level["fen"],
            human_side=human,
            clocks=False,
            validate="endgame",
            warning=t("msg_endgame_start", title=level["title"]),
            endgame_level=level,
        )


    def open_editor(self):
        """進入局面編輯器。"""
        self.stop_engine()
        self.reset_ai_state()
        self.reset_eval_state(reset_display=True)
        self.reset_suggest_state(reset_display=True)
        self.board = create_empty_xiangqi_board(RED)
        # 預設放好將帥（錯開中線，避免開局照面）
        self.board.pieces.append(Piece("帥", RED, 5, 9))
        self.board.pieces.append(Piece("將", BLACK, 4, 0))
        self.editor_selected = ("兵", RED)
        self.editor_board_pick = None
        self.editor_message = ""  # 正常操作不刷訊息
        self.editor_saved_list = load_custom_positions()
        self.goto(MODE_EDITOR)
        self.build_editor_buttons()


    def build_editor_buttons(self):
        panel_x = MARGIN_X + BOARD_WIDTH + 24
        y = MARGIN_Y
        w = SCREEN_WIDTH - panel_x - 20
        self.btn_editor_back = Button(panel_x, y, w, 40, t("editor_back"))
        y += 50
        turn_label = t("editor_turn_red") if self.board and self.board.turn == RED else t("editor_turn_black")
        self.btn_editor_turn = Button(panel_x, y, w, 40, turn_label)
        y += 50
        self.btn_editor_erase = Button(panel_x, y, w, 36, t("editor_erase"))
        y += 44
        self.btn_editor_clear = Button(panel_x, y, w // 2 - 4, 36, t("editor_clear"))
        self.btn_editor_initial = Button(panel_x + w // 2 + 4, y, w // 2 - 4, 36, t("editor_initial"))
        y += 48
        self.btn_editor_save = Button(panel_x, y, w // 2 - 4, 36, t("editor_save"))
        self.btn_editor_load = Button(panel_x + w // 2 + 4, y, w // 2 - 4, 36, t("editor_load"))
        # 從此開局改由「載入局面」庫頁操作，編輯器內不再放開局按鈕
        self.btn_editor_play_pvp = None
        self.btn_editor_play_ai = None


    def open_editor_library(self):
        """獨立頁：瀏覽／選取已存局面。"""
        self.editor_saved_list = load_custom_positions()
        self.editor_lib_selected = None
        self.editor_lib_scroll = 0
        self.editor_message = ""
        self.goto(MODE_EDITOR_LIB)
        self.build_editor_lib_ui()


    def build_editor_lib_ui(self):
        self.editor_saved_list = load_custom_positions()
        self.btn_lib_back = Button(SCREEN_WIDTH // 2 - 150, ENDGAME_BACK_Y, 300, 44, t("editor_back_edit"))
        # 底部操作列
        bw, bh = 160, 40
        by = SCREEN_HEIGHT - 70
        gap = 12
        total = 5 * bw + 4 * gap
        bx = (SCREEN_WIDTH - total) // 2
        self.btn_lib_to_edit = Button(bx, by, bw, bh, t("editor_lib_to_edit"))
        self.btn_lib_pvp = Button(bx + (bw + gap), by, bw, bh, t("editor_lib_pvp"))
        self.btn_lib_ai = Button(bx + 2 * (bw + gap), by, bw, bh, t("editor_lib_ai"))
        self.btn_lib_rename = Button(bx + 3 * (bw + gap), by, bw, bh, t("editor_lib_rename"))
        self.btn_lib_delete = Button(bx + 4 * (bw + gap), by, bw, bh, t("editor_lib_delete"))

        list_top = ENDGAME_LIST_TOP
        list_left = ENDGAME_LIST_LEFT
        row_h = ENDGAME_ROW_H
        max_vis = max(1, (ENDGAME_LIST_BOTTOM - list_top) // row_h)
        max_scroll = max(0, len(self.editor_saved_list) - max_vis)
        self.editor_lib_scroll = max(0, min(self.editor_lib_scroll, max_scroll))
        self.editor_lib_buttons = []
        for i, pos in enumerate(self.editor_saved_list):
            y = list_top + (i - self.editor_lib_scroll) * row_h
            if y + row_h < list_top or y > ENDGAME_LIST_BOTTOM:
                continue
            label = pos.get("title") or pos.get("id")
            if len(label) > 28:
                label = label[:27] + "…"
            btn = Button(list_left, y, ENDGAME_LIST_WIDTH, row_h - 8, label)
            self.editor_lib_buttons.append((btn, pos))


    def editor_lib_get_selected(self):
        if not self.editor_lib_selected:
            return None
        for p in self.editor_saved_list:
            if p.get("id") == self.editor_lib_selected:
                return p
        return None


    def editor_palette_rects(self):
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


    def editor_place_piece(self, gx, gy, name, color):
        """在 (gx,gy) 放置棋子：檢查合法格與兵種數量上限。成功不寫 log。"""
        if not self.board or not (0 <= gx <= 8 and 0 <= gy <= 9):
            return
        ok_sq, reason_sq = is_legal_piece_square(name, color, gx, gy)
        if not ok_sq:
            self.editor_message = t("editor_bad_square", name=name)
            return

        temp = []
        for p in self.board.pieces:
            if p.x == gx and p.y == gy:
                continue
            if name in ("帥", "將") and p.name == name:
                continue
            temp.append(p)
        same_count = sum(1 for p in temp if p.color == color and p.name == name)
        limit = PIECE_MAX_COUNT.get(name, 0)
        if same_count + 1 > limit:
            side = "紅" if color == RED else "黑"
            self.editor_message = t("editor_too_many", side=side, name=name, limit=limit)
            return

        self.board.pieces = temp
        self.board.pieces.append(Piece(name, color, gx, gy))
        self.board.selected_piece = None
        self.board.winner = None
        self.board.draw_reason = ""
        self.editor_board_pick = None
        self.editor_message = ""


    def editor_erase_at(self, gx, gy):
        if not self.board:
            return
        # 若刪的是正在選取的棋，一併清除選取
        if self.editor_board_pick and self.editor_board_pick.x == gx and self.editor_board_pick.y == gy:
            self.editor_board_pick = None
        self.board.pieces = [p for p in self.board.pieces if not (p.x == gx and p.y == gy)]
        self.board.selected_piece = None
        self.editor_message = ""


    def editor_pick_board_piece(self, piece):
        """點選盤上棋子，準備移動／取代。"""
        if not piece:
            return
        self.editor_board_pick = piece
        self.editor_selected = None  # 退出調色盤放置／橡皮擦模式
        self.editor_message = t("editor_pick_hint")


    def editor_move_picked_to(self, gx, gy):
        """
        將 editor_board_pick 移到 (gx,gy)。
        - 空格：移動
        - 有他子：取代（他子刪除）
        - 點自己：取消選取
        """
        if not self.board or not self.editor_board_pick:
            return
        piece = self.editor_board_pick
        # 棋子可能已被清空；確認仍在盤上
        if piece not in self.board.pieces:
            self.editor_board_pick = None
            self.editor_message = ""
            return
        if piece.x == gx and piece.y == gy:
            self.editor_board_pick = None
            self.editor_message = ""
            return

        ok_sq, _reason = is_legal_piece_square(piece.name, piece.color, gx, gy)
        if not ok_sq:
            self.editor_message = t("editor_bad_square", name=piece.name)
            return

        target = self.board.get_piece_at(gx, gy)
        replaced = target is not None and target is not piece
        # 移除目標格棋子（若有）
        if replaced:
            self.board.pieces = [p for p in self.board.pieces if p is not target]

        # 將／帥唯一性：若目標曾有同名將帥已在上面移除；移動自身不增數量
        piece.x = gx
        piece.y = gy
        piece.selected = False
        self.board.selected_piece = None
        self.board.winner = None
        self.board.draw_reason = ""
        self.editor_board_pick = None
        # 移動成功不常駐訊息，避免干擾
        self.editor_message = ""


    def editor_save_current(self):
        if not self.board:
            return
        ok, reason = validate_editor_position(self.board)
        if not ok:
            self.editor_message = t("editor_invalid", reason=reason)
            return
        fen = self.board.to_fen()
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
            self.editor_message = t("editor_name_empty")
            return
        new_id = f"pos_{int(time.time())}"
        positions.append({"id": new_id, "title": title.strip(), "fen": fen})
        ok_w, err = save_custom_positions(positions)
        if ok_w:
            self.editor_saved_list = positions
            self.editor_message = t("editor_saved", title=title.strip())
        else:
            self.editor_message = t("editor_save_fail", err=err)


    def editor_lib_load_to_edit(self):
        item = self.editor_lib_get_selected()
        if not item:
            self.editor_message = t("editor_select_first")
            return
        try:
            self.board = XiangqiBoard(MODE_PVP, fen=item["fen"])
            self.editor_board_pick = None
            self.editor_message = t("editor_loaded", title=item["title"])
            self.goto(MODE_EDITOR)
            self.build_editor_buttons()
        except Exception as ex:
            self.editor_message = t("editor_load_fail", err=str(ex))


    def editor_lib_start_game(self, mode):
        item = self.editor_lib_get_selected()
        if not item:
            self.editor_message = t("editor_select_first")
            return
        # 像讀取存檔一樣進入對局；人機可繼續用 AI
        warning = (
            t("editor_start_ai", level=ai_difficulty_display(self.ai_difficulty))
            if mode == MODE_AI
            else t("editor_start_pvp")
        )
        self.start_session(mode, fen=item["fen"], human_side=RED, validate="editor", warning=warning)


    def editor_lib_rename(self):
        item = self.editor_lib_get_selected()
        if not item:
            self.editor_message = t("editor_select_first")
            return
        new_name = prompt_text_input(
            t("editor_rename_title"),
            t("editor_rename_prompt"),
            item.get("title") or "",
        )
        if new_name is None:
            return
        if not new_name.strip():
            self.editor_message = t("editor_name_empty")
            return
        positions = load_custom_positions()
        for p in positions:
            if p.get("id") == item["id"]:
                p["title"] = new_name.strip()
                break
        ok, err = save_custom_positions(positions)
        if ok:
            self.editor_saved_list = positions
            self.editor_message = t("editor_renamed")
            self.build_editor_lib_ui()
        else:
            self.editor_message = t("editor_save_fail", err=err)


    def editor_lib_delete(self):
        item = self.editor_lib_get_selected()
        if not item:
            self.editor_message = t("editor_select_first")
            return
        positions = [p for p in load_custom_positions() if p.get("id") != item["id"]]
        ok, err = save_custom_positions(positions)
        if ok:
            self.editor_saved_list = positions
            self.editor_lib_selected = None
            self.editor_message = t("editor_deleted")
            self.build_editor_lib_ui()
        else:
            self.editor_message = t("editor_save_fail", err=err)


    def save_game_to_disk(self):
        if not self.board or self.game_state not in (MODE_PVP, MODE_AI):
            return False
        try:
            payload = {
                "version": 1,
                "type": "savegame",  # 與 editor_positions 區分
                "game_state": self.game_state,
                "player_color": self.color_to_str(self.player_color),
                "ai_color": self.color_to_str(self.ai_color),
                "view_color": self.color_to_str(self.view_color),
                "ai_difficulty": self.ai_difficulty,
                "suggest_enabled": bool(self.suggest_enabled),
                "start_fen": self.game_start_fen,
                "moves": list(self.board.move_ucci_history),
                "history_scroll_offset": float(self.history_scroll.scroll_offset if self.history_scroll else 0.0),
            }
            os.makedirs(os.path.dirname(self.save_file_path), exist_ok=True)
            with open(self.save_file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            self.board.set_warning(t("msg_save_ok"))
            return True
        except Exception as ex:
            if self.board:
                self.board.set_warning(t("msg_save_fail", err=ex))
            return False


    def load_game_from_disk(self):

        load_path = self.save_file_path
        if not os.path.exists(load_path):
            # 相容舊版寫在程式目錄的存檔
            legacy = os.path.join(project_root(), SAVE_FILE_NAME)
            if os.path.isfile(legacy):
                load_path = legacy
            else:
                if self.board:
                    self.board.set_warning(t("msg_load_missing"))
                return False

        try:
            with open(load_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as ex:
            if self.board:
                self.board.set_warning(t("msg_load_fail", err=ex))
            return False

        # 禁止與局面庫 JSON 混讀
        if isinstance(payload, dict):
            if payload.get("type") == "editor_positions" or (
                "positions" in payload and "moves" not in payload
            ):
                if self.board:
                    self.board.set_warning(t("msg_load_is_editor"))
                return False

        try:
            saved_mode = int(payload.get("game_state", MODE_PVP))
            if saved_mode not in (MODE_PVP, MODE_AI):
                saved_mode = MODE_PVP

            saved_player = self.str_to_color(payload.get("player_color"), RED)
            saved_ai = self.str_to_color(payload.get("ai_color"), BLACK)
            saved_view = self.str_to_color(payload.get("view_color"), saved_player)
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
            if not self.start_session(
                saved_mode,
                fen=saved_start_fen,
                human_side=saved_player if saved_mode == MODE_AI else RED,
                view=saved_view,
                opponent=opponent,
            ):
                raise ValueError("無法建立存檔起始局面")

            saved_diff = payload.get("ai_difficulty", self.ai_difficulty)
            if saved_diff in AI_DIFFICULTY_PRESETS:
                self.apply_ai_difficulty(saved_diff)

            # 回放所有走步，重建完整棋局狀態與規則計數器。
            self.reset_replay_history()
            for mv in saved_moves:
                if not isinstance(mv, str) or len(mv) < 4:
                    raise ValueError("存檔中有無效走步")
                if not apply_ucci_move(self.board, mv):
                    raise ValueError(f"無法套用走步：{mv}")
                self.append_replay_snapshot()

            # 還原 UI 狀態
            self.suggest_enabled = bool(payload.get("suggest_enabled", False))
            if self.btn_suggest_toggle:
                self.btn_suggest_toggle.text = t("suggest_on") if self.suggest_enabled else t("suggest_off")

            if self.history_scroll:
                max_scroll = self.get_history_max_scroll()
                saved_offset = float(payload.get("history_scroll_offset", 0.0))
                self.history_scroll.scroll_offset = max(0, min(max_scroll, saved_offset))

            self.reset_ai_state()
            self.reset_eval_state(reset_display=True)
            self.reset_suggest_state(reset_display=True)
            self.replay_mode_active = False
            self.replay_record_moves = []
            self.replay_record_notation = []
            self.replay_finished_winner = None
            self.replay_finished_draw_reason = ""
            self.replay_index = None
            self.draw_offer_popup = None
            self.btn_draw_accept = None
            self.btn_draw_reject = None
            self.board.set_warning(t("msg_load_ok"))
            return True
        except Exception as ex:
            if self.board:
                self.board.set_warning(t("msg_load_fail", err=ex))
            return False


    def open_draw_offer_popup(self):
        if not self.board or self.board.winner or self.board.draw_reason:
            return
        self.draw_offer_popup = {"from_color": self.board.turn}
        self.btn_draw_accept = Button(SCREEN_WIDTH // 2 - 130, SCREEN_HEIGHT // 2 + 20, 120, 40, t("accept_draw"))
        self.btn_draw_reject = Button(SCREEN_WIDTH // 2 + 10, SCREEN_HEIGHT // 2 + 20, 120, 40, t("reject_draw"))


    def close_draw_offer_popup(self):
        self.draw_offer_popup = None
        self.btn_draw_accept = None
        self.btn_draw_reject = None


    def request_draw(self):
        if not self.board or self.board.winner or self.board.draw_reason:
            return
        if self.game_state == MODE_PVP:
            self.open_draw_offer_popup()
            return
        if self.game_state == MODE_AI:
            if self.board.turn != self.player_color:
                self.board.set_warning(t("msg_draw_not_your_turn"))
                return
            if abs(self.eval_red_score_cp) <= 100:
                self.board.draw_reason = t("msg_draw_agree_ai")
                self.board.set_warning(t("msg_draw_ai_accept"))
            else:
                self.board.set_warning(t("msg_draw_ai_reject"))


    def choose_ai_move(self, engine_bestmove):
        # 殘局固定用引擎最佳著，絕不故意失誤
        if self.game_state == MODE_ENDGAME:
            return engine_bestmove
        if not engine_bestmove or self.ai_mistake_rate <= 0:
            return engine_bestmove
        if random.random() >= self.ai_mistake_rate:
            return engine_bestmove

        legal_moves = self.board.legal_moves_ucci(self.ai_color) if self.board else []
        if not legal_moves:
            return engine_bestmove

        alternatives = [mv for mv in legal_moves if mv != engine_bestmove]
        if not alternatives:
            return engine_bestmove
        return random.choice(alternatives)


    def current_ai_search_params(self):
        """一般 AI 對戰用選單難度；殘局闖關固定最高強度。"""
        if self.game_state == MODE_ENDGAME:
            return ENDGAME_AI_MOVETIME_MS, ENDGAME_AI_DEPTH, ENDGAME_AI_MAX_WAIT_SEC
        return self.ai_movetime_ms, self.ai_search_depth, self.ai_max_wait_sec


    def reset_eval_state(self, reset_display=False):
        self.eval_request_id = None
        self.eval_last_fen_requested = None
        if reset_display:
            self.eval_red_score_cp = 0
            self.eval_text = "+0"


    def reset_suggest_state(self, reset_display=False):
        self.suggest_request_id = None
        self.suggest_last_fen_requested = None
        if reset_display:
            self.suggest_move = None


    def new_request_id(self):
        self.request_seq += 1
        return self.request_seq


    def ensure_engine(self):
        if self.engine_dispatcher:
            return True
        dispatcher = None
        try:
            dispatcher = EngineDispatcher()
            dispatcher.start()
            self.engine_dispatcher = dispatcher
            return True
        except Exception as e:
            # 啟動失敗時務必回收程序，避免遺留 pikafish 背景行程
            if dispatcher is not None:
                try:
                    dispatcher.stop()
                except Exception:
                    pass
            self.engine_dispatcher = None
            if self.board:
                self.board.set_warning(t("msg_engine_fail", err=e))
            return False


    def stop_engine(self):
        if self.engine_dispatcher:
            self.engine_dispatcher.stop()
        self.engine_dispatcher = None


    def poll_engine_results(self):

        if not self.engine_dispatcher:
            return

        while True:
            res = self.engine_dispatcher.get_result_nowait()
            if not res:
                break

            req_id, kind, req_fen, status, payload = (
                res.req_id, res.kind, res.fen, res.status, res.payload
            )

            if self.analysis_request_id is not None and req_id == self.analysis_request_id:
                if status == "err":
                    self.analysis_status = "error"
                    self.analysis_error = str(payload)
                    self.analysis_request_id = None
                    if self.board:
                        self.board.set_warning(t("analyze_fail", err=self.analysis_error))
                    continue
                try:
                    self.handle_analysis_result(payload)
                except Exception as ex:
                    self.analysis_status = "error"
                    self.analysis_error = str(ex)
                    self.analysis_request_id = None
                    if self.board:
                        self.board.set_warning(t("analyze_fail", err=self.analysis_error))
                continue

            if req_id == self.ai_request_id:
                self.ai_request_id = None
                if status == "err":
                    self.ai_enabled = False
                    if self.board:
                        self.board.set_warning(t("msg_ai_fail", err=payload))
                    continue

                if (not self.board or self.board.winner or self.board.draw_reason or
                    self.board.turn != self.ai_color or self.board.to_fen() != req_fen):
                    continue

                best = payload
                if not best:
                    self.ai_enabled = False
                    self.board.set_warning(t("msg_ai_no_move"))
                else:
                    move_to_play = self.choose_ai_move(best)
                    if not apply_ucci_move(self.board, move_to_play):
                        # 如果故意失誤著因局面時序失配而失敗，退回最佳著再試一次。
                        if move_to_play != best and apply_ucci_move(self.board, best):
                            self.ai_wait_until = 0.0
                            self.ai_request_fen = None
                            self.on_move_applied()
                            if self.game_state == MODE_ENDGAME:
                                self.check_endgame_result()
                        else:
                            self.ai_enabled = False
                            self.board.set_warning(t("msg_ai_bad_move", mv=move_to_play))
                    else:
                        self.ai_wait_until = 0.0
                        self.ai_request_fen = None
                        self.on_move_applied()
                        if self.game_state == MODE_ENDGAME:
                            self.check_endgame_result()
                continue

            if req_id == self.eval_request_id:
                self.eval_request_id = None
                if status == "err":
                    self.eval_enabled = False
                    if self.board:
                        self.board.set_warning(t("msg_eval_fail", err=payload))
                    continue
                if self.board and self.board.to_fen() == req_fen:
                    side_token = req_fen.split()[1]
                    score_type, score_value = payload
                    self.update_eval_from_score(score_type, score_value, side_token)
                continue

            if req_id == self.suggest_request_id:
                self.suggest_request_id = None
                if status == "err":
                    self.suggest_enabled = False
                    self.suggest_move = None
                    if self.btn_suggest_toggle:
                        self.btn_suggest_toggle.text = t("suggest_off")
                    if self.board:
                        self.board.set_warning(t("msg_suggest_fail", err=payload))
                    continue
                if self.board and self.board.to_fen() == req_fen:
                    self.suggest_move = payload
                continue


    def board_to_view_coords(self, x, y):
        if self.view_color == BLACK:
            return (8 - x, 9 - y)
        return (x, y)


    def view_to_board_coords(self, vx, vy):
        if self.view_color == BLACK:
            return (8 - vx, 9 - vy)
        return (vx, vy)


    def update_eval_from_score(self, score_type, score_value, side_token):

        if score_type == "mate":
            red_mate = score_value if side_token == "w" else -score_value
            sign = "+" if red_mate > 0 else "-"
            self.eval_text = f"{sign}M{abs(red_mate)}"
            self.eval_red_score_cp = 10000 if red_mate > 0 else -10000
            return

        # UCI score 是以 side-to-move 為視角；轉成紅方視角
        red_cp = score_value if side_token == "w" else -score_value
        self.eval_red_score_cp = red_cp
        self.eval_text = f"{red_cp:+d}"


    def menu_column_rects(self):
        total_w = 3 * MENU_COL_W + 2 * MENU_COL_GAP
        start_x = (SCREEN_WIDTH - total_w) // 2
        rects = []
        for i in range(3):
            x = start_x + i * (MENU_COL_W + MENU_COL_GAP)
            rects.append(pygame.Rect(x, MENU_COL_TOP, MENU_COL_W, MENU_COL_H))
        return rects


    def layout_menu_buttons(self):
        """依三欄版面放置主選單按鈕（加大卡片內邊距，避免描述與按鈕擠在一起）。"""
        cols = self.menu_column_rects()
        pad = MENU_CARD_PAD_X
        bw = MENU_COL_W - pad * 2
        bx = lambda col: col.x + pad
        y0 = MENU_CARD_BTN_START
        gap = MENU_CARD_BTN_GAP
        h_main, h_sub = 46, 40

        # 左欄：玩家對戰
        self.btn_pvp.rect = pygame.Rect(bx(cols[0]), cols[0].y + y0, bw, h_main)
        self.btn_pvp.text = t("pvp")
        self.btn_menu_load.rect = pygame.Rect(bx(cols[0]), cols[0].y + y0 + h_main + gap, bw, h_sub)
        self.btn_menu_load.text = t("load_save")
        self.btn_clock.rect = pygame.Rect(bx(cols[0]), cols[0].y + y0 + h_main + gap + h_sub + gap, bw, h_sub)
        self.btn_clock.text = t("clock", label=time_control_label(self.current_time_control()))

        # 中欄：玩家對 AI
        self.btn_ai_red.rect = pygame.Rect(bx(cols[1]), cols[1].y + y0, bw, h_main)
        self.btn_ai_red.text = t("ai_red")
        self.btn_ai_black.rect = pygame.Rect(bx(cols[1]), cols[1].y + y0 + h_main + gap, bw, h_main)
        self.btn_ai_black.text = t("ai_black")

        # 右欄：殘局 + 編輯器（按鈕區與描述拉開；底部留給 badges）
        self.btn_formula_menu.rect = pygame.Rect(bx(cols[2]), cols[2].y + y0, bw, h_sub)
        self.btn_formula_menu.text = t("formula")
        self.btn_endgame_menu.rect = pygame.Rect(
            bx(cols[2]), cols[2].y + y0 + h_sub + gap, bw, h_sub
        )
        self.btn_endgame_menu.text = t("challenge")
        self.btn_editor_menu.rect = pygame.Rect(
            bx(cols[2]), cols[2].y + y0 + 2 * (h_sub + gap), bw, h_sub
        )
        self.btn_editor_menu.text = t("editor")

        # 頂部右上：語言 chip（小圖示）
        chip = 44
        self.btn_lang.rect = pygame.Rect(SCREEN_WIDTH - chip - 20, 16, chip, chip)
        self.btn_lang.text = t("lang_chip")
        self.btn_lang.radius = chip // 2
        self.btn_lang.draw_shadow = True

        # 底部左下：結束遊戲（幽靈按鈕，次要操作）
        self.btn_quit.rect = pygame.Rect(20, SCREEN_HEIGHT - 48, 120, 32)
        self.btn_quit.text = t("quit")
        self.btn_quit.ghost = True
        self.btn_quit.draw_shadow = False
        self.btn_quit.radius = 8
        self.btn_quit.border_color = COLOR_CARD_BORDER
        self.btn_quit.text_color = COLOR_TEXT_SECONDARY


    def switch_language(self):
        """在繁體／簡體之間切換，並刷新可見 UI 文字。"""
        new_lang = LANG_HANS if get_lang() == LANG_HANT else LANG_HANT
        ok, err = set_language(new_lang)
        pygame.display.set_caption(t("app_caption"))
        self.layout_menu_buttons()
        if self.game_state == MODE_ENDGAME_DIFF:
            self.build_endgame_diff_buttons()
        elif self.game_state == MODE_ENDGAME_LEVELS:
            self.build_endgame_level_buttons()
        elif self.game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME) and self.board:
            self.setup_in_game_buttons(for_endgame=(self.game_state == MODE_ENDGAME))
            if not ok:
                self.board.set_warning(t("msg_lang_warn", err=err))
        if not ok:
            data_dir = get_user_data_dir()
            self.menu_status_msg = f"語言已切換（本次有效），但無法儲存偏好：{err}（目錄：{data_dir}）"
            self.menu_status_until = time.time() + 6.0
        else:
            self.menu_status_msg = ""
            self.menu_status_until = 0.0



    def shutdown(self):
        self.stop_engine()
        pygame.quit()
        sys.exit()

    def run(self):
        while True:
            mouse_pos = window_to_logical_pos(pygame.mouse.get_pos(), self.render_rect)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.shutdown()
                if event.type == pygame.VIDEORESIZE:
                    resized = (max(320, event.w), max(240, event.h))
                    self.window = pygame.display.set_mode(resized, pygame.RESIZABLE)
                    self.render_rect = get_render_rect(self.window.get_size())
                    continue
                self.screen.handle_event(event, mouse_pos)

            self.poll_engine_results()
            self.screen.update()

            self.surface.fill(COLOR_BG)
            self.screen.draw(self.surface, mouse_pos)

            self.window.fill(COLOR_BG)
            if self.render_rect.size == (SCREEN_WIDTH, SCREEN_HEIGHT):
                self.window.blit(self.surface, self.render_rect.topleft)
            else:
                scaled_frame = pygame.transform.smoothscale(self.surface, self.render_rect.size)
                self.window.blit(scaled_frame, self.render_rect.topleft)
            pygame.display.flip()
            self.clock.tick(30)


def main():
    app = GameApp()
    app.run()


if __name__ == "__main__":
    main()
