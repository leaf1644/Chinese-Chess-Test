from __future__ import annotations

import time

import pygame

from xiangqi.constants import (
    BLACK,
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
    side_rgb,
)
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


class EditorScreen(Screen):
    mode_id = MODE_EDITOR

    def handle_event(self, event, mouse_pos):
        app = self.app
        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = mouse_pos
            editor_btns = [
                (app.btn_editor_back, "back"),
                (app.btn_editor_turn, "turn"),
                (app.btn_editor_erase, "erase"),
                (app.btn_editor_clear, "clear"),
                (app.btn_editor_initial, "initial"),
                (app.btn_editor_save, "save"),
                (app.btn_editor_load, "load"),
            ]
            handled = False
            for btn, action in editor_btns:
                if btn and btn.is_clicked(mouse_pos):
                    handled = True
                    if action == "back":
                        app.goto(MODE_MENU)
                        app.board = None
                        app.set_editor_message("")
                        app.editor_board_pick = None
                    elif action == "turn" and app.board:
                        app.board.turn = BLACK if app.board.turn == RED else RED
                        app.build_editor_buttons()
                        app.set_editor_message("")
                    elif action == "erase":
                        app.editor_selected = "erase"
                        app.editor_board_pick = None
                        app.set_editor_message("")
                    elif action == "clear" and app.board:
                        app.board = create_empty_xiangqi_board(app.board.turn)
                        app.editor_board_pick = None
                        app.set_editor_message("")
                        app.build_editor_buttons()
                    elif action == "initial":
                        app.board = XiangqiBoard(MODE_PVP)
                        app.editor_board_pick = None
                        app.set_editor_message("")
                        app.build_editor_buttons()
                    elif action == "save":
                        app.editor_save_current()
                    elif action == "load":
                        app.editor_board_pick = None
                        app.open_editor_library()
                    break
            if handled:
                return

            for rect, item in app.editor_palette_rects():
                if rect.collidepoint(mx, my) and event.button == 1:
                    app.editor_selected = item
                    app.editor_board_pick = None
                    app.set_editor_message("")
                    handled = True
                    break
            if handled:
                return

            vx = round((mx - MARGIN_X) / GRID_SIZE)
            vy = round((my - MARGIN_Y) / GRID_SIZE)
            if 0 <= vx <= 8 and 0 <= vy <= 9 and app.board:
                gx, gy = vx, vy
                if event.button == 3 or app.editor_selected == "erase":
                    app.editor_erase_at(gx, gy)
                elif event.button == 1:
                    clicked_piece = app.board.get_piece_at(gx, gy)
                    # 1) 已選盤上棋 → 移到空格，或點他子則取代
                    if app.editor_board_pick is not None:
                        app.editor_move_picked_to(gx, gy)
                    # 2) 點盤上既有棋子 → 選取移動（優先於調色盤，方便改標準開局）
                    elif clicked_piece is not None:
                        app.editor_pick_board_piece(clicked_piece)
                    # 3) 空格 + 調色盤 → 放置新棋
                    elif isinstance(app.editor_selected, tuple):
                        name, color = app.editor_selected
                        app.editor_place_piece(gx, gy, name, color)

    def draw(self, surface, mouse_pos):
        app = self.app
        screen = surface
        # 頂部標題列
        pygame.draw.rect(screen, COLOR_UI_BAR, (0, 0, SCREEN_WIDTH, 56))
        title = app.font_ui.render(t("editor_title"), True, COLOR_TEXT_ON_DARK)
        screen.blit(title, (20, 10))
        hint = app.font_small.render(t("editor_palette") + "　|　" + t("editor_rmb"), True, COLOR_TEXT_ON_DARK)
        screen.blit(hint, (280, 18))

        # 棋盤
        if app.board_surface:
            screen.blit(app.board_surface, (MARGIN_X - 5, MARGIN_Y - 5))
        else:
            pygame.draw.rect(screen, COLOR_LINE, (MARGIN_X - 5, MARGIN_Y - 5, 8 * GRID_SIZE + 10, 9 * GRID_SIZE + 10), 4)
            for y in range(10):
                pygame.draw.line(screen, COLOR_LINE, (MARGIN_X, MARGIN_Y + y * GRID_SIZE), (MARGIN_X + 8 * GRID_SIZE, MARGIN_Y + y * GRID_SIZE))
            for x in range(9):
                pygame.draw.line(screen, COLOR_LINE, (MARGIN_X + x * GRID_SIZE, MARGIN_Y), (MARGIN_X + x * GRID_SIZE, MARGIN_Y + 9 * GRID_SIZE))

        if app.board:
            for p in app.board.pieces:
                # 盤上選取的棋高亮
                if app.editor_board_pick is not None and p is app.editor_board_pick:
                    p.selected = True
                else:
                    p.selected = False
                draw_piece_with_assets(screen, p, app.font, RED, app.piece_sprites)

        # 調色盤
        for rect, item in app.editor_palette_rects():
            draw_card(screen, rect, fill=COLOR_CARD, radius=8, shadow=False, border_width=1)
            border_c = GOLD if app.editor_selected == item else COLOR_CARD_BORDER
            pygame.draw.rect(screen, border_c, rect, 2 if app.editor_selected != item else 3, border_radius=8)
            if isinstance(item, tuple):
                name, color = item
                ts = app.font_small.render(name, True, side_rgb(color))
                screen.blit(ts, ts.get_rect(center=rect.center))

        # 右側按鈕
        for btn in (
            app.btn_editor_back, app.btn_editor_turn, app.btn_editor_erase,
            app.btn_editor_clear, app.btn_editor_initial, app.btn_editor_save,
            app.btn_editor_load,
        ):
            if not btn:
                continue
            btn.update_hover(mouse_pos)
            btn.color = BUTTON_COLOR
            btn.hover_color = BUTTON_HOVER_COLOR
            if btn is app.btn_editor_erase and app.editor_selected == "erase":
                btn.color = (210, 180, 150)
                btn.hover_color = (200, 168, 138)
            btn.draw(screen, app.font_small)

        # 僅錯誤／儲存結果提示（自動換行）
        panel_x = MARGIN_X + BOARD_WIDTH + 24
        msg_y = MARGIN_Y + 320
        msg_w = SCREEN_WIDTH - panel_x - 24
        if app.editor_message:
            # 依寬度折行（約 14 字／行）
            chars_per_line = max(8, msg_w // 16)
            lines = []
            s = app.editor_message
            while s:
                lines.append(s[:chars_per_line])
                s = s[chars_per_line:]
            for li, line in enumerate(lines[:6]):
                col = WARNING_COLOR if app.editor_message_kind == "error" else COLOR_TEXT
                screen.blit(app.font_small.render(line, True, col), (panel_x, msg_y + li * 24))

        side_hint = app.font_small.render(t("editor_side_hint"), True, COLOR_TEXT_SECONDARY)
        screen.blit(side_hint, (panel_x, SCREEN_HEIGHT - 40))


class EditorLibraryScreen(Screen):
    mode_id = MODE_EDITOR_LIB

    def handle_event(self, event, mouse_pos):
        app = self.app
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 4:
                app.editor_lib_scroll = max(0, app.editor_lib_scroll - 1)
                app.build_editor_lib_ui()
            elif event.button == 5:
                app.editor_lib_scroll += 1
                app.build_editor_lib_ui()
            elif event.button == 1:
                if app.btn_lib_back and app.btn_lib_back.is_clicked(mouse_pos):
                    app.goto(MODE_EDITOR)
                    app.build_editor_buttons()
                elif app.btn_lib_to_edit and app.btn_lib_to_edit.is_clicked(mouse_pos):
                    app.editor_lib_load_to_edit()
                elif app.btn_lib_pvp and app.btn_lib_pvp.is_clicked(mouse_pos):
                    app.editor_lib_start_game(MODE_PVP)
                elif app.btn_lib_ai and app.btn_lib_ai.is_clicked(mouse_pos):
                    app.editor_lib_start_game(MODE_AI)
                elif app.btn_lib_rename and app.btn_lib_rename.is_clicked(mouse_pos):
                    app.editor_lib_rename()
                elif app.btn_lib_delete and app.btn_lib_delete.is_clicked(mouse_pos):
                    app.editor_lib_delete()
                else:
                    for btn, pos in app.editor_lib_buttons:
                        if btn.is_clicked(mouse_pos):
                            app.editor_lib_selected = pos.get("id")
                            app.set_editor_message("")
                            break

    def draw(self, surface, mouse_pos):
        app = self.app
        screen = surface
        title = app.font_menu.render(t("editor_lib_title"), True, COLOR_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_HEADER_Y)))
        sub = app.font_small.render(t("editor_lib_hint"), True, COLOR_TEXT_SECONDARY)
        screen.blit(sub, sub.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_LEGEND_Y)))

        if app.btn_lib_back:
            app.btn_lib_back.update_hover(mouse_pos)
            app.btn_lib_back.color = BUTTON_COLOR
            app.btn_lib_back.hover_color = BUTTON_HOVER_COLOR
            app.btn_lib_back.draw(screen, app.font_small)

        list_h = ENDGAME_LIST_BOTTOM - ENDGAME_LIST_TOP
        list_bg = pygame.Rect(ENDGAME_LIST_LEFT - 10, ENDGAME_LIST_TOP - 8, ENDGAME_LIST_WIDTH + 20, list_h + 16)
        draw_card(screen, list_bg, fill=COLOR_CARD, radius=14, shadow=True)

        if not app.editor_saved_list:
            msg = app.font.render(t("editor_no_saved"), True, WARNING_COLOR)
            screen.blit(msg, msg.get_rect(center=(SCREEN_WIDTH // 2, (ENDGAME_LIST_TOP + ENDGAME_LIST_BOTTOM) // 2)))
        else:
            for btn, pos in app.editor_lib_buttons:
                btn.update_hover(mouse_pos)
                if pos.get("id") == app.editor_lib_selected:
                    btn.color = (198, 210, 196)
                    btn.hover_color = (184, 198, 182)
                else:
                    btn.color = BUTTON_COLOR
                    btn.hover_color = BUTTON_HOVER_COLOR
                btn.draw(screen, app.font_small)

        for btn in (app.btn_lib_to_edit, app.btn_lib_pvp, app.btn_lib_ai, app.btn_lib_rename, app.btn_lib_delete):
            if not btn:
                continue
            btn.update_hover(mouse_pos)
            btn.color = BUTTON_COLOR
            btn.hover_color = BUTTON_HOVER_COLOR
            if btn is app.btn_lib_delete:
                btn.color = BUTTON_DANGER
                btn.hover_color = BUTTON_DANGER_HOVER
            btn.draw(screen, app.font_small)

        if app.editor_message:
            # 底部訊息，簡短顯示
            mcol = WARNING_COLOR if app.editor_message_kind == "error" else SUCCESS_COLOR
            ms = app.font_small.render(app.editor_message, True, mcol)
            screen.blit(ms, ms.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 100)))

