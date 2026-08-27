from __future__ import annotations

import time

import pygame

from xiangqi.constants import (
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


class MenuScreen(Screen):
    mode_id = MODE_MENU

    def handle_event(self, event, mouse_pos):
        app = self.app
        if event.type == pygame.MOUSEBUTTONDOWN:
            if app.btn_pvp.is_clicked(mouse_pos):
                app.start_session(MODE_PVP)
            elif app.btn_ai_red.is_clicked(mouse_pos):
                app.start_session(MODE_AI, human_side=RED)
            elif app.btn_ai_black.is_clicked(mouse_pos):
                app.start_session(MODE_AI, human_side=BLACK)
            elif app.btn_formula_menu and app.btn_formula_menu.is_clicked(mouse_pos):
                app.open_endgame_diff_select(ENDGAME_SECTION_FORMULA)
            elif app.btn_endgame_menu and app.btn_endgame_menu.is_clicked(mouse_pos):
                app.open_endgame_diff_select(ENDGAME_SECTION_CHALLENGE)
            elif app.btn_editor_menu and app.btn_editor_menu.is_clicked(mouse_pos):
                app.open_editor()
            elif app.btn_menu_load and app.btn_menu_load.is_clicked(mouse_pos):
                app.load_game_from_disk()
            elif app.btn_clock and app.btn_clock.is_clicked(mouse_pos):
                app.cycle_time_control()
            elif app.btn_lang and app.btn_lang.is_clicked(mouse_pos):
                app.switch_language()
            elif app.btn_quit and app.btn_quit.is_clicked(mouse_pos):
                app.shutdown()

    def update(self):
        app = self.app
        return None

    def draw(self, surface, mouse_pos):
        app = self.app
        screen = surface
        # --- Header：主標題置中；語言 chip 右上 ---
        title = app.font_menu.render(t("app_title"), True, COLOR_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 52)))
        line_w = 100
        pygame.draw.line(
            screen, GOLD,
            (SCREEN_WIDTH // 2 - line_w, 86),
            (SCREEN_WIDTH // 2 + line_w, 86),
            1,
        )
        subtitle = app.font_subtitle.render(t("choose_mode"), True, COLOR_TEXT_SECONDARY)
        screen.blit(subtitle, subtitle.get_rect(center=(SCREEN_WIDTH // 2, 118)))

        # 三欄卡片（加大內邊距：標題／描述／按鈕分層）
        cols = app.menu_column_rects()
        col_titles = [t("col_pvp"), t("col_ai"), t("col_endgame")]
        col_descs = [t("pvp_desc"), t("ai_desc"), t("endgame_desc")]
        for i, col in enumerate(cols):
            draw_card(screen, col, fill=MENU_PANEL_COLORS[i], radius=16, shadow=True)
            ct = app.font.render(col_titles[i], True, COLOR_TEXT)
            screen.blit(ct, ct.get_rect(center=(col.centerx, col.y + MENU_CARD_TITLE_Y)))
            cd = app.font_body.render(col_descs[i], True, COLOR_TEXT_SECONDARY)
            screen.blit(cd, cd.get_rect(center=(col.centerx, col.y + MENU_CARD_DESC_Y)))

        # 主操作按鈕（統一暖灰）
        for btn in (app.btn_pvp, app.btn_menu_load, app.btn_clock, app.btn_ai_red, app.btn_ai_black,
                    app.btn_formula_menu, app.btn_endgame_menu, app.btn_editor_menu):
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
        app.btn_pvp.draw(screen, app.font_small)
        app.btn_menu_load.draw(screen, app.font_small)
        app.btn_clock.draw(screen, app.font_small)
        tip_y = app.btn_clock.rect.bottom + 22
        clock_tip = app.font_body.render(t("clock_tip"), True, COLOR_TEXT_SECONDARY)
        screen.blit(clock_tip, clock_tip.get_rect(center=(cols[0].centerx, tip_y)))

        # 中欄
        app.btn_ai_red.draw(screen, app.font_small)
        app.btn_ai_black.draw(screen, app.font_small)
        tip = app.font_body.render(t("ai_tip"), True, COLOR_TEXT_SECONDARY)
        screen.blit(tip, tip.get_rect(center=(cols[1].centerx, app.btn_ai_black.rect.bottom + 22)))

        # 右欄：按鈕 + badges + 編輯器說明
        app.btn_formula_menu.draw(screen, app.font_small)
        app.btn_endgame_menu.draw(screen, app.font_small)
        app.btn_editor_menu.draw(screen, app.font_small)
        n_formula = sum(1 for lv in app.endgame_levels if lv.get("section") == ENDGAME_SECTION_FORMULA)
        n_challenge = sum(1 for lv in app.endgame_levels if lv.get("section") == ENDGAME_SECTION_CHALLENGE)
        badge_y = app.btn_editor_menu.rect.bottom + 28
        draw_badges_in_card(
            screen,
            cols[2],
            badge_y,
            [
                (t("badge_formula", n=n_formula), BADGE_BG_FORMULA, BADGE_FG),
                (t("badge_challenge", n=n_challenge), BADGE_BG_CHALLENGE, BADGE_FG),
            ],
            app.font_badge,
            gap=8,
        )
        ed = app.font_body.render(t("editor_desc"), True, COLOR_TEXT_SECONDARY)
        screen.blit(ed, ed.get_rect(center=(cols[2].centerx, badge_y + 32)))
        if app.endgame_load_error:
            err = app.font_body.render(app.endgame_load_error, True, WARNING_COLOR)
            screen.blit(err, err.get_rect(center=(cols[2].centerx, badge_y + 54)))

        # Header 語言 chip（右上）
        if app.btn_lang:
            app.btn_lang.update_hover(mouse_pos)
            app.btn_lang.color = COLOR_CARD
            app.btn_lang.hover_color = COLOR_CARD_ALT
            app.btn_lang.border_color = COLOR_CARD_BORDER
            app.btn_lang.text_color = COLOR_TEXT
            app.btn_lang.ghost = False
            app.btn_lang.draw_shadow = True
            app.btn_lang.draw(screen, app.font_small)

        # Footer：結束遊戲幽靈按鈕（左下，不搶主視覺）
        if app.btn_quit:
            app.btn_quit.update_hover(mouse_pos)
            app.btn_quit.ghost = True
            app.btn_quit.draw(screen, app.font_badge)

        if app.menu_status_msg and time.time() < app.menu_status_until:
            warn = app.font_small.render(app.menu_status_msg, True, WARNING_COLOR)
            screen.blit(warn, warn.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 90)))

