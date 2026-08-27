"""畫面尺寸、色票與繪製小工具。"""
from __future__ import annotations

import pygame

from xiangqi.constants import BLACK, RED

WHITE = (255, 255, 255)
GOLD = (160, 118, 48)
WARNING_COLOR = (168, 40, 36)
SUCCESS_COLOR = (40, 110, 72)
COLOR_BG = (246, 242, 234)
COLOR_BG_SOFT = (238, 233, 224)
COLOR_CARD = (252, 250, 246)
COLOR_CARD_ALT = (236, 232, 226)
COLOR_CARD_BORDER = (200, 194, 184)
COLOR_SHADOW = (40, 36, 32)
COLOR_TEXT = (22, 20, 18)
COLOR_TEXT_SECONDARY = (52, 48, 44)
COLOR_TEXT_ON_DARK = (252, 250, 246)
COLOR_LINE = (36, 32, 28)
COLOR_UI_BAR = (48, 44, 40)
COLOR_SELECTED = (70, 120, 90)
BUTTON_COLOR = (236, 230, 220)
BUTTON_HOVER_COLOR = (220, 212, 200)
BUTTON_TEXT = (22, 20, 18)
BUTTON_BORDER = (168, 160, 148)
BUTTON_RADIUS = 10
BUTTON_DANGER = (200, 130, 120)
BUTTON_DANGER_HOVER = (210, 150, 140)
BUTTON_ACCENT = (186, 178, 200)
BUTTON_ACCENT_HOVER = (200, 192, 214)
COLOR_PRIMARY = (90, 70, 54)

SCREEN_WIDTH = 1100
SCREEN_HEIGHT = 900
GRID_SIZE = 64
BOARD_WIDTH = 8 * GRID_SIZE + 10
BOARD_HEIGHT = 9 * GRID_SIZE + 10
TOP_UI_HEIGHT = 130
MARGIN_X = 28
MARGIN_Y = (SCREEN_HEIGHT - BOARD_HEIGHT) // 2 + 40
HISTORY_PANEL_GAP = 16
HISTORY_PANEL_RIGHT = 18
HISTORY_LINE_H = 26
HISTORY_PV_LINE_H = 20

MENU_COL_GAP = 28
MENU_COL_W = 318
MENU_COL_TOP = 168
MENU_COL_H = 470
MENU_CARD_PAD_X = 24
MENU_CARD_TITLE_Y = 30
MENU_CARD_DESC_Y = 62
MENU_CARD_BTN_START = 112
MENU_CARD_BTN_GAP = 16
MENU_PANEL_COLORS = (
    (250, 248, 244),
    (246, 246, 244),
    (248, 247, 242),
)
FONT_UI_CANDIDATES = [
    "microsoftjhenghei", "microsoftyahei", "noto sans cjk tc",
    "source hans sans tc", "pingfangtc", "simhei", "arialunicodems",
]
FONT_TITLE_CANDIDATES = [
    "kaiti", "kaiu", "stkaiti", "stxingkai", "dfkai-sb", "simkai",
    "fangsong", "stfangsong", "microsoftjhenghei",
]
BADGE_BG_FORMULA = (220, 226, 216)
BADGE_BG_CHALLENGE = (228, 220, 210)
BADGE_FG = (36, 32, 28)
BOTTOM_BTN_Y = SCREEN_HEIGHT - 50
BOTTOM_BTN_H = 38
BOTTOM_BTN_GAP = 14
BOTTOM_BTN_MARGIN_X = 20
ENDGAME_HEADER_Y = 48
ENDGAME_LEGEND_Y = 115
ENDGAME_BACK_Y = 160
ENDGAME_LIST_TOP = 230
ENDGAME_LIST_BOTTOM = SCREEN_HEIGHT - 50
ENDGAME_LIST_LEFT = SCREEN_WIDTH // 2 - 280
ENDGAME_LIST_WIDTH = 560
ENDGAME_ROW_H = 58
ENDGAME_SCROLLBAR_W = 16

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
