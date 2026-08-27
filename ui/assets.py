"""棋盤／棋子素材載入。"""
from __future__ import annotations

import math
import os

import pygame

from xiangqi.board import piece_type_from_name
from xiangqi.constants import PIECE_TO_FEN, RED
from xiangqi.paths import get_runtime_search_dirs
from .theme import COLOR_SELECTED, GRID_SIZE

def create_generated_board_surface():
    width = 8 * GRID_SIZE + 10
    height = 9 * GRID_SIZE + 10
    surf = pygame.Surface((width, height))

    # 生成木紋底色：垂直漸層 + 正弦紋理。
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(224 - 30 * ratio)
        g = int(198 - 28 * ratio)
        b = int(150 - 16 * ratio)
        for x in range(width):
            wood = int(8 * math.sin((x * 0.18) + (y * 0.03)) + 4 * math.sin(x * 0.05))
            rr = max(0, min(255, r + wood))
            gg = max(0, min(255, g + wood))
            bb = max(0, min(255, b + wood))
            surf.set_at((x, y), (rr, gg, bb))

    return surf


def create_generated_piece_sprite(piece_name, piece_color, font_names):
    size = GRID_SIZE
    center = size // 2
    radius = GRID_SIZE // 2 - 2

    sprite = pygame.Surface((size, size), pygame.SRCALPHA)
    # 柔和陰影
    pygame.draw.circle(sprite, (70, 62, 54, 90), (center + 2, center + 3), radius - 1)
    # 棋子底：暖米白
    pygame.draw.circle(sprite, (250, 246, 238), (center, center), radius - 1)
    # 外框
    pygame.draw.circle(sprite, piece_color, (center, center), radius - 1, 3)

    # 內圓紋理（淡墨）
    pygame.draw.circle(sprite, (200, 192, 180, 100), (center, center), radius - 7, 1)
    pygame.draw.circle(sprite, (190, 182, 170, 70), (center, center), radius - 10, 1)

    font = pygame.font.SysFont(font_names, 30, bold=True)
    text = font.render(piece_name, True, piece_color)
    text_rect = text.get_rect(center=(center, center))
    sprite.blit(text, text_rect)
    return sprite


def load_visual_assets(font_names):
    """載入棋盤與棋子素材。

    回傳 (board_surface, piece_sprites, board_from_asset)
    board_from_asset=True 表示使用真實棋盤圖，繪圖時應略過程式格線／楚河漢界以免重疊。
    """
    base_dir = next(iter(get_runtime_search_dirs()), os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(base_dir, "assets")
    pieces_dir = os.path.join(assets_dir, "pieces")

    for candidate_base in get_runtime_search_dirs():
        candidate_assets = os.path.join(candidate_base, "assets")
        if os.path.isdir(candidate_assets):
            assets_dir = candidate_assets
            pieces_dir = os.path.join(candidate_assets, "pieces")
            break

    board_surface = None
    board_from_asset = False
    board_candidates = [
        os.path.join(assets_dir, "board.png"),
        os.path.join(assets_dir, "board.jpg"),
        os.path.join(assets_dir, "board.jpeg"),
    ]
    for path in board_candidates:
        if os.path.exists(path):
            try:
                raw = pygame.image.load(path).convert()
                board_surface = pygame.transform.smoothscale(raw, (8 * GRID_SIZE + 10, 9 * GRID_SIZE + 10))
                board_from_asset = True
                break
            except Exception:
                board_surface = None
                board_from_asset = False

    if board_surface is None:
        board_surface = create_generated_board_surface()
        board_from_asset = False

    piece_sprites = {}
    for piece_name, piece_color in PIECE_TO_FEN.keys():
        key = (piece_name, piece_color)
        if key in piece_sprites:
            continue

        side = "red" if piece_color == RED else "black"
        piece_type = piece_type_from_name(piece_name)
        sprite = None
        if piece_type:
            for ext in ("png", "jpg", "jpeg"):
                candidate = os.path.join(pieces_dir, f"{side}_{piece_type}.{ext}")
                if os.path.exists(candidate):
                    try:
                        raw = pygame.image.load(candidate).convert_alpha()
                        # 俯視棋子略小於格距，中心對準交叉點時不致蓋住鄰線太多
                        piece_draw_size = max(40, int(GRID_SIZE * 0.88))
                        sprite = pygame.transform.smoothscale(raw, (piece_draw_size, piece_draw_size))
                        break
                    except Exception:
                        sprite = None

        if sprite is None:
            sprite = create_generated_piece_sprite(piece_name, piece_color, font_names)
        piece_sprites[key] = sprite

    return board_surface, piece_sprites, board_from_asset

