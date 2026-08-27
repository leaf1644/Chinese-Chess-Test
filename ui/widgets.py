"""按鈕與捲軸。"""
from __future__ import annotations

import pygame

from .theme import (
    BUTTON_BORDER,
    BUTTON_COLOR,
    BUTTON_HOVER_COLOR,
    BUTTON_RADIUS,
    BUTTON_TEXT,
    COLOR_CARD_ALT,
    COLOR_CARD_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_SECONDARY,
    draw_soft_shadow,
)


class Button:
    def __init__(
        self,
        x,
        y,
        width,
        height,
        text,
        color=BUTTON_COLOR,
        *,
        hover_color=BUTTON_HOVER_COLOR,
        radius=BUTTON_RADIUS,
        text_color=BUTTON_TEXT,
        border_color=BUTTON_BORDER,
        draw_shadow=True,
        ghost=False,
    ):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.color = color
        self.hover_color = hover_color
        self.is_hovered = False
        self.radius = radius
        self.text_color = text_color
        self.border_color = border_color
        self.draw_shadow = draw_shadow
        self.ghost = ghost

    def draw(self, screen, font):
        color = self.hover_color if self.is_hovered else self.color
        r = self.radius
        if self.ghost:
            # 幽靈按鈕：透明底 + 細邊框，不搶主視覺
            if self.is_hovered:
                pygame.draw.rect(screen, COLOR_CARD_ALT, self.rect, border_radius=r)
            pygame.draw.rect(screen, self.border_color, self.rect, 1, border_radius=r)
            text_c = self.text_color
            if self.is_hovered:
                text_c = COLOR_TEXT
            text_surface = font.render(self.text, True, text_c)
            text_rect = text_surface.get_rect(center=self.rect.center)
            screen.blit(text_surface, text_rect)
            return

        if self.draw_shadow and not self.is_hovered:
            draw_soft_shadow(screen, self.rect, radius=r, offset=(2, 3), layers=3, alpha=22)
        elif self.is_hovered:
            draw_soft_shadow(screen, self.rect, radius=r, offset=(1, 2), layers=2, alpha=18)
        pygame.draw.rect(screen, color, self.rect, border_radius=r)
        pygame.draw.rect(screen, self.border_color, self.rect, 1, border_radius=r)
        # 頂緣微高光（極簡質感）
        if self.rect.height > 10 and self.rect.width > 10:
            hi = pygame.Surface((self.rect.width - 4, max(2, self.rect.height // 5)), pygame.SRCALPHA)
            hi.fill((255, 255, 255, 28 if self.is_hovered else 18))
            screen.blit(hi, (self.rect.x + 2, self.rect.y + 2))
        text_surface = font.render(self.text, True, self.text_color)
        text_rect = text_surface.get_rect(center=self.rect.center)
        screen.blit(text_surface, text_rect)

    def is_clicked(self, pos):
        return self.rect.collidepoint(pos)

    def update_hover(self, pos):
        self.is_hovered = self.rect.collidepoint(pos)


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
