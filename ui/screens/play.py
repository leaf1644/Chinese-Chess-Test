from __future__ import annotations

import time

import pygame

from xiangqi.constants import (
    AI_DELAY_SEC,
    AI_SUGGEST_MOVETIME_MS,
    BLACK,
    ENDGAME_SECTION_CHALLENGE,
    ENDGAME_SECTION_FORMULA,
    MODE_AI,
    MODE_EDITOR,
    MODE_ENDGAME,
    MODE_ENDGAME_DIFF,
    MODE_ENDGAME_LEVELS,
    MODE_MENU,
    MODE_PVP,
    RED,
)
from xiangqi.engine import DEFAULT_EVAL_MOVETIME_MS as AI_EVAL_MOVETIME_MS
from xiangqi.result import ResultKind
from xiangqi.i18n import (
    ai_difficulty_display,
    diff_group_label,
    get_lang,
    section_label,
    t,
)
from ui.theme import (
    BADGE_BG_CHALLENGE,
    BADGE_BG_FORMULA,
    BADGE_FG,
    BOARD_HEIGHT,
    BOARD_WIDTH,
    BOTTOM_BTN_Y,
    BUTTON_BORDER,
    BUTTON_COLOR,
    BUTTON_DANGER,
    BUTTON_DANGER_HOVER,
    BUTTON_HOVER_COLOR,
    BUTTON_TEXT,
    COLOR_BG,
    COLOR_CARD,
    COLOR_CARD_ALT,
    COLOR_CARD_BORDER,
    COLOR_LINE,
    COLOR_PRIMARY,
    COLOR_PIECE_RED,
    COLOR_TEXT,
    COLOR_TEXT_ON_DARK,
    COLOR_TEXT_SECONDARY,
    COLOR_UI_BAR,
    ENDGAME_HEADER_Y,
    ENDGAME_LEGEND_Y,
    ENDGAME_LIST_BOTTOM,
    ENDGAME_LIST_LEFT,
    ENDGAME_LIST_TOP,
    ENDGAME_LIST_WIDTH,
    ENDGAME_SCROLLBAR_W,
    GOLD,
    GRID_SIZE,
    HISTORY_LINE_H,
    HISTORY_PV_LINE_H,
    MARGIN_X,
    MARGIN_Y,
    MENU_CARD_DESC_Y,
    MENU_CARD_TITLE_Y,
    MENU_PANEL_COLORS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SUCCESS_COLOR,
    TOP_UI_HEIGHT,
    WARNING_COLOR,
    blend_rgb,
    draw_card,
    draw_badges_in_card,
)
from xiangqi.board import ucci_to_board
from ui.draw import draw_piece_with_assets
from ui.text import format_clock_ms, wrap_text_by_width
from ui.widgets import Button
from .base import Screen


class PlayScreen(Screen):
    def __init__(self, app, mode_id):
        super().__init__(app)
        self.mode_id = mode_id

    def handle_event(self, event, mouse_pos):
        app = self.app
        if event.type == pygame.KEYDOWN and app.game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
            if event.key == pygame.K_d and app.board:
                app.board.debug = not app.board.debug
                app.board.set_warning(
                    t("msg_debug", state=t("msg_debug_on") if app.board.debug else t("msg_debug_off"))
                )

        if event.type == pygame.MOUSEBUTTONDOWN and app.game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
            # 遊戲中隨時返回主選單
            if app.btn_main_menu and app.btn_main_menu.is_clicked(mouse_pos):
                app.stop_engine()
                app.reset_ai_state()
                app.reset_eval_state(reset_display=True)
                app.reset_suggest_state(reset_display=True)
                app.goto(MODE_MENU)
                app.board = None
                app.endgame_current = None
                app.endgame_status = ""
                app.btn_main_menu = None
                app.btn_suggest_toggle = None
                app.btn_undo = None
                app.btn_save_game = None
                app.btn_load_game = None
                app.btn_draw_offer = None
                app.btn_replay_mode = None
                app.btn_difficulty = None
                app.btn_analyze = None
                app.btn_endgame_hint = None
                app.btn_endgame_retry = None
                app.btn_endgame_levels = None
                app.history_scroll = None
                app.replay_snapshots = []
                app.replay_index = None
                app.replay_mode_active = False
                app.replay_record_moves = []
                app.replay_record_notation = []
                app.replay_finished_winner = None
                app.replay_finished_draw_reason = ""
                app.close_draw_offer_popup()
            elif app.game_state == MODE_ENDGAME and app.btn_endgame_levels and app.btn_endgame_levels.is_clicked(mouse_pos):
                app.open_endgame_diff_select()
            elif app.game_state == MODE_ENDGAME and app.btn_endgame_retry and app.btn_endgame_retry.is_clicked(mouse_pos):
                if app.endgame_current:
                    app.start_endgame_level(app.endgame_current)
            else:
                max_scroll = app.get_history_max_scroll()

                # PVP 求和彈窗優先處理
                if app.draw_offer_popup:
                    if event.button == 1:
                        if app.btn_draw_accept and app.btn_draw_accept.is_clicked(mouse_pos):
                            app.board.set_result(
                                ResultKind.AGREE_DRAW, winner=None, message=t("msg_draw_agree")
                            )
                            app.close_draw_offer_popup()
                        elif app.btn_draw_reject and app.btn_draw_reject.is_clicked(mouse_pos):
                            app.board.set_warning(t("msg_draw_rejected"))
                            app.close_draw_offer_popup()
                    return

                # 先處理棋譜滾動（終局後也可滾動）。
                if event.button == 4:
                    if app.history_scroll:
                        app.history_scroll.handle_scroll(-30, max_scroll)
                    return
                if event.button == 5:
                    if app.history_scroll:
                        app.history_scroll.handle_scroll(30, max_scroll)
                    return

                # 滾動條拖動起點（必須與上方 button 4/5 同層，不可縮在 wheel 分支內）
                if event.button == 1 and app.history_scroll:
                    app.history_scroll.handle_click(mouse_pos)
                    if app.history_scroll.is_dragging:
                        return

                # 賽後分析：終局後也必須可點（不可被下方 return 擋掉）
                if event.button == 1 and app.btn_analyze and app.btn_analyze.is_clicked(mouse_pos):
                    if app.analysis_status == "running":
                        if app.board:
                            app.board.set_warning(
                                t("analyzing", cur=app.analysis_progress, total=max(1, app.analysis_total))
                            )
                    else:
                        app.start_postgame_analysis()
                    return

                # AI 難度：對局中可隨時切換（含終局後）
                if event.button == 1 and app.btn_difficulty and app.btn_difficulty.is_clicked(mouse_pos):
                    if app.game_state == MODE_AI:
                        app.cycle_ai_difficulty()
                    return

                if event.button == 1 and app.btn_replay_mode and app.btn_replay_mode.is_clicked(mouse_pos):
                    if app.replay_mode_active:
                        app.board.set_warning(t("msg_replay_active"))
                    elif app.board.winner or app.board.draw_reason:
                        app.enter_replay_mode()
                    else:
                        app.board.set_warning(t("msg_replay_need_end"))
                    return

                # 未進入復盤模式時，終局局面不可直接操作棋子／存讀檔等。
                if (app.board.winner or app.board.draw_reason) and not app.replay_mode_active:
                    return

                # 復盤模式下可點譜跳局面，但不影響原終局棋譜。
                if app.replay_mode_active and event.button == 1:
                    idx = app.get_notation_index_at_pos(mouse_pos)
                    if idx is not None:
                        if app.restore_game_to_step(idx + 1, source_moves=app.replay_record_moves):
                            app.board.set_warning(t("msg_replay_jump", n=idx + 1))
                        else:
                            app.board.set_warning(t("msg_replay_jump_fail"))
                        return
                    # 復盤中不再處理走子／悔棋等，但分析已在上方處理
                    return

                # 以下是未結束遊戲時的操作
                if app.btn_save_game and app.btn_save_game.is_clicked(mouse_pos):
                    app.save_game_to_disk()
                elif app.btn_load_game and app.btn_load_game.is_clicked(mouse_pos):
                    app.load_game_from_disk()
                elif app.btn_draw_offer and (not app.replay_mode_active) and app.btn_draw_offer.is_clicked(mouse_pos):
                    app.request_draw()
                elif app.btn_suggest_toggle and app.btn_suggest_toggle.is_clicked(mouse_pos):
                    app.suggest_enabled = not app.suggest_enabled
                    app.btn_suggest_toggle.text = t("suggest_on") if app.suggest_enabled else t("suggest_off")
                    app.reset_suggest_state(reset_display=True)
                    if not app.suggest_enabled:
                        app.reset_eval_state(reset_display=True)
                elif app.btn_undo and app.btn_undo.is_clicked(mouse_pos):
                    if app.endgame_status:
                        return
                    if app.board.undo_last_move():
                        app.board.selected_piece = None
                        app.reset_ai_state()
                        app.reset_eval_state()
                        app.reset_suggest_state()
                        app.sync_replay_history_after_undo()
                        if app.game_state == MODE_ENDGAME:
                            app.endgame_player_moves = sum(
                                1 for piece, *_rest in app.board.move_history
                                if piece.color == app.player_color
                            )
                            app.endgame_status = ""
                else:
                    if app.endgame_status and app.game_state == MODE_ENDGAME:
                        return
                    if app.game_state in (MODE_AI, MODE_ENDGAME) and app.ai_enabled and app.board.turn == app.ai_color:
                        return
                    # 棋盤操作
                    mx, my = mouse_pos
                    vx = round((mx - MARGIN_X) / GRID_SIZE)
                    vy = round((my - MARGIN_Y) / GRID_SIZE)

                    if 0 <= vx <= 8 and 0 <= vy <= 9:
                        gx, gy = app.view_to_board_coords(vx, vy)
                        clicked = app.board.get_piece_at(gx, gy)
                        selected = app.board.selected_piece

                        if selected:
                            # 嘗試移動
                            if app.board.is_valid_move(selected, gx, gy):
                                if not app.board.move_piece(selected, gx, gy):
                                    # 如果 move_piece 返回 False，代表移動後會被將軍，已被駁回
                                    pass
                                else:
                                    app.on_move_applied()
                                    if app.game_state == MODE_ENDGAME:
                                        app.endgame_player_moves += 1
                                        app.check_endgame_result()
                                    if app.game_state in (MODE_AI, MODE_ENDGAME) and app.board.turn == app.ai_color and not app.endgame_status:
                                        app.reset_ai_state()
                                        app.ai_wait_until = time.time() + AI_DELAY_SEC
                            elif clicked and clicked.color == app.board.turn:
                                selected.selected = False
                                clicked.selected = True
                                app.board.selected_piece = clicked
                        else:
                            if clicked and clicked.color == app.board.turn:
                                clicked.selected = True
                                app.board.selected_piece = clicked

        if event.type == pygame.MOUSEMOTION and app.game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
            if app.history_scroll:
                app.history_scroll.handle_drag(mouse_pos, app.get_history_max_scroll())

        if event.type == pygame.MOUSEBUTTONUP and app.game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME):
            if event.button == 1 and app.history_scroll:
                app.history_scroll.handle_release()

    def update(self):
        app = self.app
        # --- 棋鐘 ---
        if app.game_state in (MODE_PVP, MODE_AI) and app.board:
            app.tick_clocks()

        # --- AI 回合（一般 AI 對戰 + 殘局對手） ---
        # 分析進行中暫停 AI，避免搶引擎
        if (app.game_state in (MODE_AI, MODE_ENDGAME) and app.board and app.ai_enabled and
            app.analysis_status != "running" and
            not app.endgame_status and
            not app.board.winner and not app.board.draw_reason and app.board.turn == app.ai_color):
            if app.ai_wait_until <= 0:
                app.ai_wait_until = time.time() + AI_DELAY_SEC

            if app.ai_request_id is None and time.time() >= app.ai_wait_until:
                app.ai_request_fen = app.board.to_fen()
                if app.ensure_engine():
                    app.ai_request_id = app.new_request_id()
                    mt, depth, max_wait = app.current_ai_search_params()
                    app.engine_dispatcher.submit(
                        app.ai_request_id,
                        "bestmove",
                        app.ai_request_fen,
                        mt,
                        depth=depth,
                        max_wait_sec=max_wait,
                    )
                else:
                    app.ai_enabled = False
                    app.board.set_warning(t("msg_ai_engine_fail"))

        # --- 即時評估（僅在建議著法開啟時） ---
        if app.game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME) and app.board and app.eval_enabled and app.suggest_enabled and not app.board.winner and not app.board.draw_reason and not app.endgame_status:
            current_fen = app.board.to_fen()
            if app.eval_request_id is None and current_fen != app.eval_last_fen_requested:
                if app.ensure_engine():
                    app.eval_last_fen_requested = current_fen
                    app.eval_request_id = app.new_request_id()
                    app.engine_dispatcher.submit(app.eval_request_id, "analyse", current_fen, AI_EVAL_MOVETIME_MS)
                else:
                    app.eval_enabled = False
                    app.board.set_warning(t("msg_eval_engine_fail"))
        elif not app.suggest_enabled:
            app.reset_eval_state(reset_display=True)

        # --- 建議著法 ---
        if app.game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME) and app.board and app.suggest_enabled and not app.board.winner and not app.board.draw_reason and not app.endgame_status:
            # AI／殘局模式下，只在玩家回合提供建議
            if app.game_state in (MODE_AI, MODE_ENDGAME) and (not app.replay_mode_active) and app.board.turn != app.player_color:
                app.suggest_move = None
            else:
                current_fen = app.board.to_fen()
                if app.suggest_request_id is None and current_fen != app.suggest_last_fen_requested:
                    if app.ensure_engine():
                        app.suggest_last_fen_requested = current_fen
                        app.suggest_request_id = app.new_request_id()
                        app.engine_dispatcher.submit(app.suggest_request_id, "bestmove", current_fen, AI_SUGGEST_MOVETIME_MS, depth=None, max_wait_sec=None)
                    else:
                        app.suggest_enabled = False
                        if app.btn_suggest_toggle:
                            app.btn_suggest_toggle.text = t("suggest_off")
                        app.board.set_warning(t("msg_suggest_engine_fail"))
        elif not app.suggest_enabled:
            app.suggest_move = None

        if app.game_state in (MODE_PVP, MODE_AI, MODE_ENDGAME) and app.board:
            app.capture_finished_record_if_needed()
            if app.game_state == MODE_ENDGAME and not app.endgame_status:
                app.check_endgame_result()

    def draw(self, surface, mouse_pos):
        app = self.app
        screen = surface
        # 繪製遊戲界面
        # 1. 頂欄（柔和深灰）
        pygame.draw.rect(screen, COLOR_UI_BAR, (0, 0, SCREEN_WIDTH, TOP_UI_HEIGHT))
        # 底緣細線
        pygame.draw.line(screen, blend_rgb(COLOR_UI_BAR, GOLD, 0.25), (0, TOP_UI_HEIGHT - 1), (SCREEN_WIDTH, TOP_UI_HEIGHT - 1), 1)

        turn_str = t("red_turn") if app.board.turn == RED else t("black_turn")
        color = COLOR_PIECE_RED if app.board.turn == RED else COLOR_TEXT_ON_DARK
        screen.blit(app.font_ui.render(turn_str, True, color), (20, 12))

        if app.game_state == MODE_PVP:
            mode_text = t("mode_pvp")
        elif app.game_state == MODE_ENDGAME and app.endgame_current:
            max_m = app.endgame_current.get("max_player_moves")
            limit = f"{app.endgame_player_moves}/{max_m}" if max_m is not None else f"{app.endgame_player_moves}"
            status_tag = {
                "cleared": t("status_cleared"),
                "failed": t("status_failed"),
            }.get(app.endgame_status, t("status_playing"))
            mode_text = t(
                "endgame_hud",
                title=app.endgame_current["title"],
                limit=limit,
                status=status_tag,
            )
        else:
            mode_text = t(
                "mode_ai_line",
                you=t("side_red") if app.player_color == RED else t("side_black"),
                ai=t("side_red") if app.ai_color == RED else t("side_black"),
                level=ai_difficulty_display(app.ai_difficulty),
            )
        screen.blit(app.font_small.render(mode_text, True, COLOR_TEXT_ON_DARK), (20, 52))

        # 棋鐘顯示（雙人／人機）
        if app.clock_enabled and app.game_state in (MODE_PVP, MODE_AI):
            red_clk = format_clock_ms(app.clock_red_ms)
            black_clk = format_clock_ms(app.clock_black_ms)
            # 上方為對方（視角翻轉時對調標籤）
            top_is_black = app.view_color == RED
            top_label = t("side_black") if top_is_black else t("side_red")
            bot_label = t("side_red") if top_is_black else t("side_black")
            top_ms = app.clock_black_ms if top_is_black else app.clock_red_ms
            bot_ms = app.clock_red_ms if top_is_black else app.clock_black_ms
            top_txt = f"{top_label} {format_clock_ms(top_ms)}"
            bot_txt = f"{bot_label} {format_clock_ms(bot_ms)}"
            active_top = (app.board.turn == BLACK and top_is_black) or (app.board.turn == RED and not top_is_black)
            c_top = GOLD if active_top else COLOR_TEXT_SECONDARY
            c_bot = GOLD if not active_top else COLOR_TEXT_SECONDARY
            screen.blit(app.font_small.render(top_txt, True, c_top), (MARGIN_X, TOP_UI_HEIGHT + 4))
            screen.blit(
                app.font_small.render(bot_txt, True, c_bot),
                (MARGIN_X, MARGIN_Y + BOARD_HEIGHT + 8),
            )

        eval_x = 730
        if app.suggest_enabled:
            screen.blit(app.font_small.render(t("suggest_header"), True, COLOR_TEXT_ON_DARK), (eval_x, 10))
            sugg_text = t("suggest_move", move=app.suggest_move) if app.suggest_move else t("suggest_none")
            screen.blit(app.font_small.render(sugg_text, True, COLOR_TEXT_ON_DARK), (eval_x, 44))
            screen.blit(app.font_small.render(t("eval_line", score=app.eval_text), True, GOLD), (eval_x, 76))
        else:
            screen.blit(app.font_small.render(t("suggest_off"), True, COLOR_TEXT_SECONDARY), (eval_x, 44))

        # 狀態顯示 (將軍 / 勝利 / 正常)
        if app.replay_mode_active:
            if app.replay_finished_winner:
                status = t("win_red") if app.replay_finished_winner == RED else t("win_black")
                screen.blit(app.font.render(status, True, GOLD), (250, 10))
            elif app.replay_finished_draw_reason:
                draw_text = app.font.render(str(app.replay_finished_draw_reason), True, WARNING_COLOR)
                screen.blit(draw_text, (250, 10))
        elif app.board.winner:
            status = t("win_red") if app.board.winner == RED else t("win_black")
            screen.blit(app.font_ui.render(status, True, GOLD), (250, 10))
        elif app.board.draw_reason:
            # 顯示和棋原因
            draw_text = app.font.render(app.board.draw_reason, True, WARNING_COLOR)
            screen.blit(draw_text, (250, 10))
        elif app.board.is_check:
            # 顯示閃爍的將軍文字
            if int(time.time() * 2) % 2 == 0: # 簡單的閃爍效果
                screen.blit(app.font_warn.render(t("check"), True, GOLD), (250, 10))

        if app.replay_mode_active:
            rv_text = app.font_small.render(t("replay"), True, GOLD)
            screen.blit(rv_text, (20, 92))
        elif app.board.winner or app.board.draw_reason:
            rv_text = app.font_small.render(t("replay"), True, GOLD)
            screen.blit(rv_text, (20, 92))

        # 頂欄醒目提示（存檔／違規等）— 加大字體並置於頂欄中上方，避免貼底看不清
        if app.board.warning_msg and time.time() - app.board.warning_timer < 2.8:
            warn_text = app.font_banner.render(app.board.warning_msg, True, (255, 92, 82))
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
        if app.board_surface:
            # 執黑時翻轉棋盤圖，與棋子視角一致（楚河漢界也會對調）
            draw_board = app.board_surface
            if app.board_from_asset and app.view_color == BLACK:
                draw_board = pygame.transform.flip(app.board_surface, True, True)
            screen.blit(draw_board, (MARGIN_X - 5, MARGIN_Y - 5))

        if app.board_from_asset:
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

            font_river = pygame.font.SysFont(app.font_names, 40)
            left_river = t("river_left") if app.view_color == RED else t("river_right")
            right_river = t("river_right") if app.view_color == RED else t("river_left")
            screen.blit(font_river.render(left_river, True, COLOR_LINE), (MARGIN_X + 1.5 * GRID_SIZE, MARGIN_Y + 4.2 * GRID_SIZE))
            screen.blit(font_river.render(right_river, True, COLOR_LINE), (MARGIN_X + 5.5 * GRID_SIZE, MARGIN_Y + 4.2 * GRID_SIZE))

        # 3. 繪製移動歷史（加寬面板 + 變例多行中文）
        history_panel_x, history_panel_y, history_panel_width, history_panel_height, clip_rect = app.get_history_panel_rects()
        history_rect = pygame.Rect(history_panel_x, history_panel_y, history_panel_width, history_panel_height)
        draw_card(screen, history_rect, fill=COLOR_CARD, radius=12, shadow=True)

        # 標題
        title_text = app.font_small.render(t("move_log"), True, COLOR_TEXT)
        screen.blit(title_text, (history_panel_x + 14, history_panel_y + 10))
        pygame.draw.line(
            screen, COLOR_CARD_BORDER,
            (history_panel_x + 12, history_panel_y + 36),
            (history_panel_x + history_panel_width - 14, history_panel_y + 36),
            1,
        )

        notation_list = app.get_display_notation_list()
        row_heights, content_h, pv_map = app.get_history_row_heights(app.font_badge)
        max_scroll = app.get_history_max_scroll()
        if app.history_scroll:
            app.history_scroll.content_height = max(clip_rect.height + 1, content_h + 12)
            # 滾動條貼在記錄面板右側
            app.history_scroll.rect.x = history_panel_x + history_panel_width - 18
            app.history_scroll.rect.y = clip_rect.y
            app.history_scroll.rect.height = clip_rect.height
            app.history_scroll.thumb_height = max(
                20, int(clip_rect.height * clip_rect.height / max(1, app.history_scroll.content_height))
            )

        screen.set_clip(clip_rect)
        scroll_offset = app.history_scroll.scroll_offset if app.history_scroll else 0
        y_offset = clip_rect.y - scroll_offset

        for i, notation in enumerate(notation_list):
            row_h = row_heights[i] if i < len(row_heights) else HISTORY_LINE_H
            # 超出可視區則略過繪製（仍推進 y）
            row_bottom = y_offset + row_h
            if row_bottom >= clip_rect.y and y_offset <= clip_rect.bottom:
                if app.replay_mode_active and app.replay_index == i + 1:
                    hl = pygame.Rect(
                        clip_rect.x + 2, y_offset, clip_rect.width - 4, max(HISTORY_LINE_H, row_h - 2)
                    )
                    pygame.draw.rect(screen, (236, 228, 210), hl, border_radius=6)

                move_color = COLOR_PIECE_RED if i % 2 == 0 else COLOR_TEXT
                tag = ""
                tag_color = move_color
                if i < len(app.analysis_results) and app.analysis_results[i]:
                    ar = app.analysis_results[i]
                    tag = f" [{app.analysis_label_text(ar['label'])} Δ{ar['cp_loss']}]"
                    tag_color = app.analysis_label_color(ar["label"])

                move_text = app.font_small.render(f"{i+1}. {notation}", True, move_color)
                screen.blit(move_text, (clip_rect.x + 6, y_offset + 2))
                if tag:
                    tag_surf = app.font_small.render(tag, True, tag_color)
                    tx = clip_rect.x + 6 + move_text.get_width()
                    # 標籤過寬則折到下一視覺區仍畫在同行右側裁切內
                    if tx + tag_surf.get_width() < clip_rect.right - 4:
                        screen.blit(tag_surf, (tx, y_offset + 2))
                    else:
                        # 改畫較短標籤
                        short = app.font_badge.render(
                            f"[{app.analysis_label_text(app.analysis_results[i]['label'])}]", True, tag_color
                        )
                        screen.blit(short, (clip_rect.x + 6, y_offset + 2 + 16))

                # 變例：多行完整顯示（中文棋譜）
                if i in pv_map:
                    pv_y = y_offset + HISTORY_LINE_H + 2
                    for li, line in enumerate(pv_map[i]):
                        col = COLOR_PRIMARY if li == 0 else COLOR_TEXT_SECONDARY
                        pv_surf = app.font_badge.render(line, True, col)
                        screen.blit(pv_surf, (clip_rect.x + 10, pv_y))
                        pv_y += HISTORY_PV_LINE_H

            y_offset += row_h

        screen.set_clip(None)

        if app.history_scroll and max_scroll > 0:
            app.history_scroll.draw(screen)

        # 4. 繪製棋子
        for p in app.board.pieces:
            draw_piece_with_assets(screen, p, app.font, app.view_color, app.piece_sprites)

        # 5. 繪製建議著法高亮
        if app.suggest_enabled and app.suggest_move and len(app.suggest_move) >= 4:
            src = ucci_to_board(app.suggest_move[:2])
            dst = ucci_to_board(app.suggest_move[2:4])
            if src and dst:
                svx, svy = app.board_to_view_coords(src[0], src[1])
                dvx, dvy = app.board_to_view_coords(dst[0], dst[1])
                sx = MARGIN_X + svx * GRID_SIZE
                sy = MARGIN_Y + svy * GRID_SIZE
                dx = MARGIN_X + dvx * GRID_SIZE
                dy = MARGIN_Y + dvy * GRID_SIZE
                pygame.draw.circle(screen, (40, 170, 255), (sx, sy), GRID_SIZE // 2 + 6, 3)
                pygame.draw.circle(screen, (255, 180, 40), (dx, dy), GRID_SIZE // 2 + 6, 3)
                pygame.draw.line(screen, (255, 180, 40), (sx, sy), (dx, dy), 3)

        # 6. 底部按鈕：依目前可見項重新等距排版，再繪製
        finished = bool(app.board.winner or app.board.draw_reason)
        if app.game_state == MODE_ENDGAME:
            app.layout_bottom_bar([
                (app.btn_endgame_retry, 120),
                (app.btn_undo if not app.endgame_status else None, 140),
                (app.btn_main_menu, 160),
                (app.btn_endgame_levels, 160),
            ])
        else:
            app.layout_bottom_bar([
                (app.btn_save_game if not finished else None, 110),
                (app.btn_load_game if not finished else None, 110),
                (app.btn_suggest_toggle if not finished else None, 200),
                (app.btn_undo if not finished else None, 140),
                (app.btn_main_menu, 160),
            ])

        def _draw_bottom_btn(btn):
            if not btn:
                return
            btn.text_color = BUTTON_TEXT
            btn.border_color = BUTTON_BORDER
            btn.color = BUTTON_COLOR
            btn.hover_color = BUTTON_HOVER_COLOR
            btn.update_hover(mouse_pos)
            btn.draw(screen, app.font_small)

        if app.game_state == MODE_ENDGAME:
            _draw_bottom_btn(app.btn_endgame_retry)
            if not app.endgame_status:
                _draw_bottom_btn(app.btn_undo)
            _draw_bottom_btn(app.btn_main_menu)
            _draw_bottom_btn(app.btn_endgame_levels)
        else:
            if not finished:
                _draw_bottom_btn(app.btn_save_game)
                _draw_bottom_btn(app.btn_load_game)
                _draw_bottom_btn(app.btn_suggest_toggle)
                _draw_bottom_btn(app.btn_undo)
            _draw_bottom_btn(app.btn_main_menu)

        # 右側功能鈕（非底部列）
        if app.btn_draw_offer and not finished and not app.replay_mode_active:
            app.btn_draw_offer.update_hover(mouse_pos)
            app.btn_draw_offer.text_color = BUTTON_TEXT
            app.btn_draw_offer.draw(screen, app.font_small)

        if app.btn_replay_mode and (finished or app.replay_mode_active):
            app.btn_replay_mode.update_hover(mouse_pos)
            app.btn_replay_mode.text_color = BUTTON_TEXT
            app.btn_replay_mode.draw(screen, app.font_small)

        if app.btn_analyze and app.game_state in (MODE_PVP, MODE_AI):
            if app.analysis_status == "running":
                app.btn_analyze.text = t("analyzing", cur=app.analysis_progress, total=max(1, app.analysis_total))
            elif app.analysis_status == "done":
                app.btn_analyze.text = t("analyze_done")
            else:
                app.btn_analyze.text = t("analyze")
            app.btn_analyze.update_hover(mouse_pos)
            app.btn_analyze.text_color = BUTTON_TEXT
            app.btn_analyze.draw(screen, app.font_small)

        if app.btn_difficulty and app.game_state == MODE_AI:
            app.btn_difficulty.text = t("ai_difficulty", level=ai_difficulty_display(app.ai_difficulty))
            app.btn_difficulty.update_hover(mouse_pos)
            app.btn_difficulty.text_color = BUTTON_TEXT
            app.btn_difficulty.draw(screen, app.font_small)

        if app.game_state == MODE_ENDGAME:
            pass  # 重來／關卡列表已在底部列繪製
            if app.endgame_status == "cleared":
                banner = app.font_ui.render(t("pass"), True, GOLD)
                screen.blit(banner, banner.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40)))
            elif app.endgame_status == "failed":
                banner = app.font_ui.render(t("fail_banner"), True, WARNING_COLOR)
                screen.blit(banner, banner.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40)))

        if app.draw_offer_popup and app.btn_draw_accept and app.btn_draw_reject:
            overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            overlay.fill((40, 36, 32, 100))
            screen.blit(overlay, (0, 0))
            popup_rect = pygame.Rect(SCREEN_WIDTH // 2 - 220, SCREEN_HEIGHT // 2 - 110, 440, 220)
            draw_card(screen, popup_rect, fill=COLOR_CARD, radius=16, shadow=True, border_width=1)
            requester = t("side_red") if app.draw_offer_popup["from_color"] == RED else t("side_black")
            msg = app.font.render(t("msg_draw_popup", who=requester), True, COLOR_TEXT)
            msg_rect = msg.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 25))
            screen.blit(msg, msg_rect)
            app.btn_draw_accept.update_hover(mouse_pos)
            app.btn_draw_reject.update_hover(mouse_pos)
            app.btn_draw_accept.draw(screen, app.font_small)
            app.btn_draw_reject.draw(screen, app.font_small)

