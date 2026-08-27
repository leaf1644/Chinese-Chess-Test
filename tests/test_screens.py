"""Screen 物件與極薄 main() 迴圈。"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestChessImportWithoutPygame(unittest.TestCase):
    def test_import_chess_does_not_bind_pygame(self):
        code = (
            "import sys\n"
            "import chess\n"
            "assert 'pygame' not in sys.modules, 'pygame was imported'\n"
            "from chess import XiangqiBoard, RED\n"
            "b = XiangqiBoard()\n"
            "assert b.get_king(RED) is not None\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class TestMainIsThin(unittest.TestCase):
    def test_ui_app_main_under_150_lines(self):
        path = os.path.join(ROOT, "ui", "app.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        main_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        nlines = main_fn.end_lineno - main_fn.lineno + 1
        self.assertLessEqual(nlines, 150, f"main() has {nlines} lines")
        run_fn = None
        for n in tree.body:
            if isinstance(n, ast.ClassDef) and n.name == "GameApp":
                run_fn = next(x for x in n.body if isinstance(x, ast.FunctionDef) and x.name == "run")
        self.assertIsNotNone(run_fn)
        run_lines = run_fn.end_lineno - run_fn.lineno + 1
        self.assertLessEqual(run_lines, 150, f"GameApp.run() has {run_lines} lines")


class TestScreenProtocol(unittest.TestCase):
    def test_screens_have_handle_event_update_draw(self):
        from ui.screens.base import Screen
        from ui.screens.editor import EditorLibraryScreen, EditorScreen
        from ui.screens.endgame_select import EndgameDiffScreen, EndgameLevelsScreen
        from ui.screens.menu import MenuScreen
        from ui.screens.play import PlayScreen
        from xiangqi.constants import (
            MODE_AI,
            MODE_EDITOR,
            MODE_EDITOR_LIB,
            MODE_ENDGAME,
            MODE_ENDGAME_DIFF,
            MODE_ENDGAME_LEVELS,
            MODE_MENU,
            MODE_PVP,
        )

        for cls in (
            MenuScreen,
            EndgameDiffScreen,
            EndgameLevelsScreen,
            EditorScreen,
            EditorLibraryScreen,
        ):
            self.assertTrue(issubclass(cls, Screen))
            self.assertTrue(callable(cls.handle_event))
            self.assertTrue(callable(cls.update))
            self.assertTrue(callable(cls.draw))

        self.assertEqual(MenuScreen.mode_id, MODE_MENU)
        self.assertEqual(EndgameDiffScreen.mode_id, MODE_ENDGAME_DIFF)
        self.assertEqual(EndgameLevelsScreen.mode_id, MODE_ENDGAME_LEVELS)
        self.assertEqual(EditorScreen.mode_id, MODE_EDITOR)
        self.assertEqual(EditorLibraryScreen.mode_id, MODE_EDITOR_LIB)

        class _App:
            pass

        play = PlayScreen(_App(), MODE_PVP)
        self.assertEqual(play.mode_id, MODE_PVP)
        play_ai = PlayScreen(_App(), MODE_AI)
        self.assertEqual(play_ai.mode_id, MODE_AI)
        play_eg = PlayScreen(_App(), MODE_ENDGAME)
        self.assertEqual(play_eg.mode_id, MODE_ENDGAME)


class TestGameAppGoto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.app import GameApp
        cls.app = GameApp()

    def test_goto_swaps_screen_object(self):
        from ui.screens.menu import MenuScreen
        from ui.screens.play import PlayScreen
        from xiangqi.constants import MODE_MENU, MODE_PVP

        self.app.goto(MODE_MENU)
        self.assertIsInstance(self.app.screen, MenuScreen)
        self.assertEqual(self.app.game_state, MODE_MENU)
        self.assertTrue(self.app.start_session(MODE_PVP))
        self.assertIsInstance(self.app.screen, PlayScreen)
        self.assertEqual(self.app.game_state, MODE_PVP)
        self.assertEqual(self.app.screen.mode_id, MODE_PVP)


if __name__ == "__main__":
    unittest.main()
