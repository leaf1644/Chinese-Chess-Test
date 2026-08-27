"""i18n 與 Pikafish IPC：不需 pygame／顯示器。

執行（專案根目錄）：
  python -m unittest tests.test_i18n_engine -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from xiangqi.engine import (  # noqa: E402
    EngineDispatcher,
    EngineResult,
    EngineTask,
    PikafishEngine,
)
from xiangqi import i18n  # noqa: E402


class TestNoPygameOnImport(unittest.TestCase):
    def test_xiangqi_package_does_not_import_pygame(self):
        code = (
            "import sys\n"
            "import xiangqi.i18n\n"
            "import xiangqi.engine\n"
            "import xiangqi.paths\n"
            "assert 'pygame' not in sys.modules, 'pygame was imported'\n"
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


class TestI18n(unittest.TestCase):
    def setUp(self):
        self._prev = i18n._current_lang
        i18n._current_lang = i18n.LANG_HANT

    def tearDown(self):
        i18n._current_lang = self._prev

    def test_t_default_hant(self):
        self.assertEqual(i18n.t("pvp"), "玩家對玩家")
        self.assertEqual(i18n.t("pass"), "過關！")

    def test_t_format_kwargs(self):
        self.assertEqual(i18n.t("ai_difficulty", level="中等"), "AI 難度：中等")

    def test_t_missing_key_returns_key(self):
        self.assertEqual(i18n.t("definitely_not_a_real_key"), "definitely_not_a_real_key")

    def test_t_hans_switch_in_memory(self):
        i18n._current_lang = i18n.LANG_HANS
        self.assertEqual(i18n.t("pvp"), "玩家对玩家")
        self.assertEqual(i18n.t("pass"), "过关！")

    def test_t_falls_back_to_hant_for_unknown_lang(self):
        i18n._current_lang = "xx"
        self.assertEqual(i18n.t("pvp"), "玩家對玩家")

    def test_helpers(self):
        self.assertEqual(i18n.difficulty_label(3), "中級")
        self.assertEqual(i18n.section_label("formula"), "定式訓練")
        self.assertEqual(i18n.section_label("challenge"), "殘局闖關")
        self.assertEqual(i18n.ai_difficulty_display("簡單"), "簡單")
        self.assertEqual(
            i18n.diff_group_label({"id": "beginner"}),
            "入門／初級",
        )

    def test_set_language_rejects_invalid(self):
        ok, err = i18n.set_language("en")
        self.assertFalse(ok)
        self.assertEqual(err, "invalid language")
        self.assertEqual(i18n.get_lang(), i18n.LANG_HANT)


class TestEngineTaskDataclass(unittest.TestCase):
    def test_task_defaults(self):
        task = EngineTask(req_id=1, kind="bestmove", fen="4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1")
        self.assertIsNone(task.movetime_ms)
        self.assertIsNone(task.depth)
        self.assertIsNone(task.max_wait_sec)

    def test_dispatcher_submit_and_handle_bestmove(self):
        disp = EngineDispatcher(engine_path="unused")
        disp.engine = mock.Mock()
        disp.engine.bestmove.return_value = "h2e2"
        disp.submit(7, "bestmove", "fen-x", movetime_ms=50, depth=4, max_wait_sec=1.5)
        task = disp.task_queue.get_nowait()
        self.assertIsInstance(task, EngineTask)
        self.assertEqual(task.req_id, 7)
        self.assertEqual(task.kind, "bestmove")
        self.assertEqual(task.fen, "fen-x")
        self.assertEqual(task.movetime_ms, 50)
        self.assertEqual(task.depth, 4)
        self.assertEqual(task.max_wait_sec, 1.5)
        disp._handle_task(task)
        res = disp.get_result_nowait()
        self.assertIsInstance(res, EngineResult)
        self.assertEqual(res.req_id, 7)
        self.assertEqual(res.kind, "bestmove")
        self.assertEqual(res.fen, "fen-x")
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.payload, "h2e2")
        disp.engine.bestmove.assert_called_once_with(
            "fen-x", 50, depth=4, max_wait_sec=1.5
        )

    def test_dispatcher_unknown_kind_is_error(self):
        disp = EngineDispatcher(engine_path="unused")
        disp.engine = mock.Mock()
        disp.submit(3, "nope", "fen-y")
        task = disp.task_queue.get_nowait()
        disp._handle_task(task)
        res = disp.get_result_nowait()
        self.assertEqual(res.status, "err")
        self.assertIn("unknown task kind", res.payload)

    def test_dispatcher_engine_exception_is_error(self):
        disp = EngineDispatcher(engine_path="unused")
        disp.engine = mock.Mock()
        disp.engine.analyse_full.side_effect = RuntimeError("boom")
        disp.submit(2, "analyse_full", "fen-z", movetime_ms=10)
        task = disp.task_queue.get_nowait()
        disp._handle_task(task)
        res = disp.get_result_nowait()
        self.assertEqual(res.status, "err")
        self.assertEqual(res.payload, "boom")

    def test_find_engine_path_sees_bundled_binary(self):
        eng = PikafishEngine()
        self.assertTrue(
            os.path.isfile(eng.engine_path),
            msg=f"engine_path={eng.engine_path}",
        )


if __name__ == "__main__":
    unittest.main()
