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


class EndgameDiffScreen(Screen):
    mode_id = MODE_ENDGAME_DIFF

    def handle_event(self, event, mouse_pos):
        app = self.app
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.btn_endgame_back and app.btn_endgame_back.is_clicked(mouse_pos):
                app.goto(MODE_MENU)
                app.endgame_diff_buttons = []
                app.endgame_level_buttons = []
                app.endgame_filter_group = None
            else:
                for btn, group in app.endgame_diff_buttons:
                    if btn.is_clicked(mouse_pos):
                        app.open_endgame_level_select(group)
                        break

    def draw(self, surface, mouse_pos):
        app = self.app
        screen = surface
        # 難度選擇頁
        section_title = section_label(app.endgame_active_section)
        title = app.font_menu.render(section_title, True, COLOR_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_HEADER_Y)))
        sub = app.font_small.render(t("pick_diff"), True, COLOR_TEXT_SECONDARY)
        screen.blit(sub, sub.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_LEGEND_Y)))
        tip2 = app.font_small.render(
            t("tip_challenge") if app.endgame_active_section == ENDGAME_SECTION_CHALLENGE else t("tip_formula"),
            True, COLOR_TEXT_SECONDARY,
        )
        screen.blit(tip2, tip2.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_LEGEND_Y + 28)))

        if app.btn_endgame_back:
            app.btn_endgame_back.update_hover(mouse_pos)
            app.btn_endgame_back.color = BUTTON_COLOR
            app.btn_endgame_back.hover_color = BUTTON_HOVER_COLOR
            app.btn_endgame_back.draw(screen, app.font_small)

        section_levels = app.endgame_levels_in_section()
        if not section_levels:
            msg = app.font.render(app.endgame_load_error or t("no_levels_section"), True, WARNING_COLOR)
            screen.blit(msg, msg.get_rect(center=(SCREEN_WIDTH // 2, (ENDGAME_LIST_TOP + ENDGAME_LIST_BOTTOM) // 2)))
        else:
            for btn, group in app.endgame_diff_buttons:
                btn.update_hover(mouse_pos)
                base, hover = group.get("color", (BUTTON_COLOR, BUTTON_HOVER_COLOR))
                btn.color = base
                btn.hover_color = hover
                btn.draw(screen, app.font)

        count_text = app.font_small.render(
            t("section_total", section=section_title, n=len(section_levels)), True, COLOR_TEXT_SECONDARY
        )
        screen.blit(count_text, count_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 28)))


class EndgameLevelsScreen(Screen):
    mode_id = MODE_ENDGAME_LEVELS

    def handle_event(self, event, mouse_pos):
        app = self.app
        if event.type == pygame.MOUSEBUTTONDOWN:
            list_rect = pygame.Rect(
                ENDGAME_LIST_LEFT,
                ENDGAME_LIST_TOP,
                ENDGAME_LIST_WIDTH + ENDGAME_SCROLLBAR_W + 12,
                app.endgame_list_viewport_height(),
            )
            if event.button == 4:
                app.endgame_list_scroll = max(0, app.endgame_list_scroll - 48)
                app.build_endgame_level_buttons()
            elif event.button == 5:
                app.endgame_list_scroll = min(app.endgame_list_max_scroll(), app.endgame_list_scroll + 48)
                app.build_endgame_level_buttons()
            elif event.button == 1:
                if app.btn_endgame_back and app.btn_endgame_back.is_clicked(mouse_pos):
                    app.open_endgame_diff_select()
                elif app.endgame_list_scrollbar and app.endgame_list_max_scroll() > 0:
                    app.endgame_list_scrollbar.handle_click(mouse_pos)
                    if app.endgame_list_scrollbar.is_dragging:
                        pass
                    elif list_rect.collidepoint(mouse_pos):
                        for btn, payload in app.endgame_level_buttons:
                            # 只接受可見區域內的點擊
                            if btn.rect.bottom <= ENDGAME_LIST_TOP or btn.rect.top >= ENDGAME_LIST_BOTTOM:
                                return
                            if not btn.is_clicked(mouse_pos):
                                return
                            if payload == "locked":
                                break
                            app.start_endgame_level(payload)
                            break
                elif list_rect.collidepoint(mouse_pos):
                    for btn, payload in app.endgame_level_buttons:
                        if btn.rect.bottom <= ENDGAME_LIST_TOP or btn.rect.top >= ENDGAME_LIST_BOTTOM:
                            return
                        if not btn.is_clicked(mouse_pos):
                            return
                        if payload == "locked":
                            break
                        app.start_endgame_level(payload)
                        break
        elif event.type == pygame.MOUSEMOTION:
            if app.endgame_list_scrollbar and app.endgame_list_scrollbar.is_dragging:
                app.endgame_list_scrollbar.handle_drag(mouse_pos, app.endgame_list_max_scroll())
                app.endgame_list_scroll = int(app.endgame_list_scrollbar.scroll_offset)
                app.build_endgame_level_buttons()
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1 and app.endgame_list_scrollbar:
                app.endgame_list_scrollbar.handle_release()

    def draw(self, surface, mouse_pos):
        app = self.app
        screen = surface
        # 標題／說明／返回：固定上方，不與列表重疊
        section_title = section_label(app.endgame_active_section)
        group_label = diff_group_label(app.endgame_filter_group) if app.endgame_filter_group else t("level_label")
        title = app.font_menu.render(f"{section_title} · {group_label}", True, COLOR_TEXT)
        screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_HEADER_Y)))

        legend_lines = [t("legend1"), t("legend2")]
        for li, line in enumerate(legend_lines):
            sub = app.font_small.render(line, True, COLOR_TEXT_SECONDARY)
            screen.blit(sub, sub.get_rect(center=(SCREEN_WIDTH // 2, ENDGAME_LEGEND_Y + li * 26)))

        if app.btn_endgame_back:
            app.btn_endgame_back.update_hover(mouse_pos)
            app.btn_endgame_back.color = BUTTON_COLOR
            app.btn_endgame_back.hover_color = BUTTON_HOVER_COLOR
            app.btn_endgame_back.draw(screen, app.font_small)

        # 列表卡片
        list_h = app.endgame_list_viewport_height()
        list_bg = pygame.Rect(ENDGAME_LIST_LEFT - 10, ENDGAME_LIST_TOP - 8, ENDGAME_LIST_WIDTH + 20, list_h + 16)
        draw_card(screen, list_bg, fill=COLOR_CARD, radius=14, shadow=True)

        filtered = app.endgame_levels_for_group(app.endgame_filter_group)
        if not filtered:
            msg = app.font.render(t("no_levels_diff"), True, WARNING_COLOR)
            screen.blit(msg, msg.get_rect(center=(SCREEN_WIDTH // 2, (ENDGAME_LIST_TOP + ENDGAME_LIST_BOTTOM) // 2)))
        else:
            clip = pygame.Rect(ENDGAME_LIST_LEFT - 4, ENDGAME_LIST_TOP, ENDGAME_LIST_WIDTH + 8, list_h)
            screen.set_clip(clip)
            for btn, payload in app.endgame_level_buttons:
                if btn.rect.bottom <= ENDGAME_LIST_TOP or btn.rect.top >= ENDGAME_LIST_BOTTOM:
                    continue
                btn.update_hover(mouse_pos)
                if payload == "locked":
                    btn.color = COLOR_CARD_ALT
                    btn.hover_color = blend_rgb(COLOR_CARD_ALT, COLOR_TEXT, 0.08)
                    btn.text_color = COLOR_TEXT_SECONDARY
                else:
                    cleared = payload["id"] in app.endgame_cleared
                    btn.color = (198, 210, 196) if cleared else BUTTON_COLOR
                    btn.hover_color = (184, 198, 182) if cleared else BUTTON_HOVER_COLOR
                    btn.text_color = BUTTON_TEXT
                btn.draw(screen, app.font_small)
            screen.set_clip(None)

            if app.endgame_list_scrollbar and app.endgame_list_max_scroll() > 0:
                app.endgame_list_scrollbar.draw(screen)

        count_text = app.font_small.render(
            t("section_total", section=group_label, n=len(filtered)), True, COLOR_TEXT_SECONDARY
        )
        screen.blit(count_text, count_text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 28)))

