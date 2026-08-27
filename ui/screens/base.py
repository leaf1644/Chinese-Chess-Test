"""畫面基底。"""
from __future__ import annotations


class Screen:
    mode_id = None

    def __init__(self, app):
        self.app = app

    def handle_event(self, event, mouse_pos):
        return None

    def update(self):
        return None

    def draw(self, surface, mouse_pos):
        return None
