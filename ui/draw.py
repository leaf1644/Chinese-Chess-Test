"""棋子繪製。"""
from __future__ import annotations

import pygame

from xiangqi.constants import BLACK, RED
from .theme import COLOR_SELECTED, GRID_SIZE, MARGIN_X, MARGIN_Y

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

    draw_piece_vector(screen, piece, font, view_color)




def draw_piece_vector(screen, piece, font, view_color=RED):
    if view_color == BLACK:
        draw_x = 8 - piece.x
        draw_y = 9 - piece.y
    else:
        draw_x = piece.x
        draw_y = piece.y
    cx = MARGIN_X + draw_x * GRID_SIZE
    cy = MARGIN_Y + draw_y * GRID_SIZE
    pygame.draw.circle(screen, (100, 80, 60), (cx + 2, cy + 3), GRID_SIZE // 2 - 2)
    pygame.draw.circle(screen, (240, 220, 180), (cx, cy), GRID_SIZE // 2 - 2)
    pygame.draw.circle(screen, piece.color, (cx, cy), GRID_SIZE // 2 - 2, 3)
    if piece.selected:
        pygame.draw.circle(screen, COLOR_SELECTED, (cx, cy), GRID_SIZE // 2 + 2, 4)
    text = font.render(piece.name, True, piece.color)
    text_rect = text.get_rect(center=(cx, cy))
    screen.blit(text, text_rect)
