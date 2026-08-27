"""核心象棋規則、FEN／UCCI、存檔與引擎啟動清理的單元測試。

執行（專案根目錄）：
  set SDL_VIDEODRIVER=dummy
  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

# 必須在 import chess 前設定，避免 pygame 需要真實顯示器
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import chess as app  # noqa: E402


class TestUCCIRoundTrip(unittest.TestCase):
    def test_board_ucci_roundtrip_corners(self):
        samples = [(0, 0), (8, 0), (0, 9), (8, 9), (4, 5)]
        for x, y in samples:
            ucci = app.board_to_ucci(x, y)
            back = app.ucci_to_board(ucci)
            self.assertEqual(back, (x, y), msg=f"ucci={ucci}")

    def test_ucci_invalid(self):
        self.assertIsNone(app.ucci_to_board(""))
        self.assertIsNone(app.ucci_to_board("z9"))
        self.assertIsNone(app.ucci_to_board("a"))


class TestFEN(unittest.TestCase):
    def test_load_start_position_kings(self):
        board = app.XiangqiBoard()
        fen = board.to_fen()
        self.assertTrue(fen.endswith(" w - - 0 1") or " w " in fen)
        b2 = app.XiangqiBoard(fen=fen)
        self.assertEqual(len(b2.pieces), len(board.pieces))
        self.assertIsNotNone(b2.get_king(app.RED))
        self.assertIsNotNone(b2.get_king(app.BLACK))

    def test_simple_endgame_fen_roundtrip(self):
        fen = "4k4/9/9/9/9/9/9/9/4R4/4K4 w - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        self.assertEqual(board.to_fen().split()[0], fen.split()[0])
        self.assertEqual(board.turn, app.RED)

    def test_illegal_advisor_square_rejected_by_validator(self):
        # 士在 (3,1) 非法
        fen = "4k4/3a1a3/9/9/9/9/9/9/4R4/4K4 w - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        ok, reason = app.validate_endgame_start_position(board)
        self.assertFalse(ok)
        self.assertIn("士", reason)


class TestPieceMoves(unittest.TestCase):
    def test_rook_horizontal_clear(self):
        board = app.XiangqiBoard(fen="4k4/9/9/9/9/9/9/9/4R4/4K4 w - - 0 1")
        rook = board.get_piece_at(4, 8)
        self.assertIsNotNone(rook)
        self.assertTrue(board.is_valid_move(rook, 0, 8))
        self.assertTrue(board.is_valid_move(rook, 8, 8))

    def test_cannon_need_screen_to_capture(self):
        # 紅炮在 e1、中間有紅兵、黑將在 e9 線——吃子需隔一子
        fen = "4k4/9/9/9/4P4/9/9/9/4C4/5K3 w - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        cannon = board.get_piece_at(4, 8)
        # 無子可吃於空格：可直走
        self.assertTrue(board.is_valid_move(cannon, 4, 6))
        # 有兵作炮架才能打到將線上的將？將在 (4,0)，兵 (4,4)，炮 (4,8)
        # 中間恰好一子，可打將
        self.assertTrue(board.is_valid_move(cannon, 4, 0))

    def test_knight_blocked_by_leg(self):
        fen = "4k4/9/9/9/9/9/9/4P4/4N4/4K4 w - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        knight = board.get_piece_at(4, 8)
        # 馬腿 (4,7) 有兵，向上跳被蹩
        self.assertFalse(board.is_valid_move(knight, 3, 6))
        self.assertFalse(board.is_valid_move(knight, 5, 6))

    def test_kings_facing_illegal(self):
        fen = "4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        king = board.get_king(app.RED)
        # 紅帥往上走到與黑將同線空曠會照面——若帥可走到 (4,8) 仍可能照面
        # 直接驗證 is_kings_facing
        self.assertTrue(board.is_kings_facing())


class TestCheckAndMate(unittest.TestCase):
    def test_mate_in_one_horse_cannon(self):
        # 馬後炮一步殺（與 endgames eg_007 相同結構）
        fen = "4k4/9/4N4/9/9/9/9/9/9/3C1K3 w - - 0 1"
        board = app.XiangqiBoard(game_mode=app.MODE_PVP, fen=fen)
        ok, _ = app.validate_endgame_start_position(board)
        self.assertTrue(ok)
        cannon = board.get_piece_at(3, 9)
        self.assertIsNotNone(cannon)
        self.assertTrue(board.move_piece(cannon, 4, 9))
        # 黑方無合法著 → 紅勝
        self.assertEqual(board.winner, app.RED)

    def test_cannot_leave_own_king_in_check(self):
        fen = "4k4/9/9/9/9/9/9/9/4R4/4K4 b - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        king = board.get_king(app.BLACK)
        self.assertTrue(board.is_under_attack(app.BLACK))
        # 沿車線走仍被將
        self.assertFalse(board.would_be_legal_move(king, 4, 1))
        self.assertFalse(board.move_piece(king, 4, 1))
        self.assertEqual(king.x, 4)
        self.assertEqual(king.y, 0)
        # 橫移離開車線可解將
        self.assertTrue(board.would_be_legal_move(king, 5, 0))
        self.assertTrue(board.move_piece(king, 5, 0))
        self.assertFalse(board.is_under_attack(app.BLACK))


class TestSimulateMove(unittest.TestCase):
    def test_simulate_restores_on_exception(self):
        board = app.XiangqiBoard()
        fen = board.to_fen()
        n = len(board.pieces)
        pawn = None
        for p in board.pieces:
            if p.color == app.RED and p.name == "兵" and board.is_valid_move(p, p.x, p.y - 1):
                pawn = p
                break
        self.assertIsNotNone(pawn)
        with self.assertRaises(RuntimeError):
            with board._simulate_move(pawn, pawn.x, pawn.y - 1):
                raise RuntimeError("boom")
        self.assertEqual(board.to_fen(), fen)
        self.assertEqual(len(board.pieces), n)

    def test_legal_moves_ucci_start_position(self):
        board = app.XiangqiBoard()
        red = board.legal_moves_ucci(app.RED)
        self.assertGreater(len(red), 10)
        self.assertTrue(all(len(mv) >= 4 for mv in red))
        self.assertTrue(board.has_valid_move(app.RED))
        self.assertTrue(board.has_valid_move(app.BLACK))

    def test_has_valid_move_false_when_mated(self):
        # 馬後炮將死後輪到黑
        fen = "4k4/9/4N4/9/9/9/9/9/9/3C1K3 w - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        cannon = board.get_piece_at(3, 9)
        self.assertTrue(board.move_piece(cannon, 4, 9))
        self.assertEqual(board.winner, app.RED)
        self.assertFalse(board.has_valid_move(app.BLACK))
        self.assertEqual(board.legal_moves_ucci(app.BLACK), [])


class TestRepeatAndLongRules(unittest.TestCase):
    def test_repeat_position_counts(self):
        board = app.XiangqiBoard(game_mode=app.MODE_PVP)
        # 初始已計 1 次
        self.assertGreaterEqual(sum(board.board_state_history.values()), 1)
        state = board.get_board_state()
        board.board_state_history[state] = 2
        # 再記錄同一局面
        c = board.check_repeat_position()
        # check_repeat_position 用當前局面 key 遞增
        self.assertGreaterEqual(c, 1)

    def test_long_check_not_applied_in_endgame_mode(self):
        # 殘局模式不應因長將判負
        fen = "4k4/9/9/9/9/9/9/9/4R4/4K4 w - - 0 1"
        board = app.XiangqiBoard(game_mode=app.MODE_ENDGAME, fen=fen)
        rook = board.get_piece_at(4, 8)
        # 連續運車將軍（簡化：只驗證 endgame 下 draw_reason 不因短序列誤觸）
        self.assertTrue(board.move_piece(rook, 4, 1))  # 車進到靠近將，可能將軍
        # 不論是否將軍，殘局模式不應立刻因「長將」設 winner 給黑
        if board.draw_reason:
            self.assertNotIn("長將", board.draw_reason)

    def test_move_is_single_record(self):
        board = app.XiangqiBoard(game_mode=app.MODE_PVP)
        piece = None
        for p in board.pieces:
            if p.color == app.RED and p.name == "兵" and board.is_valid_move(p, p.x, p.y - 1):
                piece = p
                break
        self.assertIsNotNone(piece)
        ox, oy = piece.x, piece.y
        self.assertTrue(board.move_piece(piece, ox, oy - 1))
        self.assertEqual(len(board.moves), 1)
        mv = board.moves[0]
        self.assertEqual(mv.piece, piece)
        self.assertEqual((mv.old_x, mv.old_y), (ox, oy))
        self.assertEqual(board.move_ucci_history, [mv.ucci])
        self.assertEqual(board.move_notation, [mv.notation])
        self.assertEqual(len(board.move_history), 1)
        self.assertTrue(board.undo_last_move())
        self.assertEqual(len(board.moves), 0)
        self.assertEqual(board.move_notation, [])

    def test_endgame_mode_skips_repetition_penalties(self):
        endgame = app.XiangqiBoard(
            game_mode=app.MODE_ENDGAME,
            fen="4k4/9/9/9/9/9/9/9/4R4/4K4 w - - 0 1",
        )
        self.assertFalse(endgame._enforces_repetition_penalties())
        pvp = app.XiangqiBoard(game_mode=app.MODE_PVP)
        self.assertTrue(pvp._enforces_repetition_penalties())

    def test_undo_restores_repeat_counter(self):
        board = app.XiangqiBoard(game_mode=app.MODE_PVP)
        fen_before = board.to_fen()
        # 走一步再悔棋
        piece = None
        for p in board.pieces:
            if p.color == app.RED and p.name == "兵":
                # 兵三進一 典型
                if board.is_valid_move(p, p.x, p.y - 1):
                    piece = p
                    break
        if piece is None:
            self.skipTest("找不到可前進的紅兵")
        ox, oy = piece.x, piece.y
        self.assertTrue(board.move_piece(piece, ox, oy - 1))
        self.assertTrue(board.undo_last_move())
        self.assertEqual(board.to_fen().split()[0], fen_before.split()[0])


class TestApplyUCCI(unittest.TestCase):
    def test_apply_ucci_move_red_pawn(self):
        board = app.XiangqiBoard()
        # 找一個合法 UCCI
        for p in board.pieces:
            if p.color != app.RED or p.name != "兵":
                continue
            for ty in range(10):
                if ty == p.y:
                    continue
                if board.is_valid_move(p, p.x, ty):
                    mv = app.board_to_ucci(p.x, p.y) + app.board_to_ucci(p.x, ty)
                    self.assertTrue(app.apply_ucci_move(board, mv))
                    return
        self.skipTest("無合法兵步")


class TestUserDataPaths(unittest.TestCase):
    def test_user_data_dir_writable(self):
        d = app.get_user_data_dir()
        self.assertTrue(os.path.isdir(d))
        probe = os.path.join(d, ".write_probe_test")
        try:
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            self.assertTrue(os.path.isfile(probe))
        finally:
            try:
                os.remove(probe)
            except OSError:
                pass

    def test_language_pref_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "language.json")
            with mock.patch("xiangqi.paths.get_user_data_path", return_value=path):
                ok, err = app.save_language_pref(app.LANG_HANS)
                self.assertTrue(ok, err)
                lang = app.load_language_pref()
                self.assertEqual(lang, app.LANG_HANS)

    def test_endgame_progress_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "endgame_progress.json")
            with mock.patch.object(app, "get_user_data_path", return_value=path):
                ok, err = app.save_endgame_progress({"cleared": ["eg_001", "sq_001"]})
                self.assertTrue(ok, err)
                data = app.load_endgame_progress(path)
                self.assertIn("eg_001", data["cleared"])


class TestEngineStartCleanup(unittest.TestCase):
    def test_start_failure_calls_stop(self):
        eng = app.PikafishEngine(engine_path="__nonexistent_pikafish_binary__")
        with self.assertRaises(Exception):
            eng.start()
        # 失敗後 process 應已清空
        self.assertIsNone(eng.process)

    def test_handshake_failure_stops_process(self):
        # 用假 Popen：啟動後不回應 uciok
        eng = app.PikafishEngine(engine_path="pikafish")
        fake_proc = mock.MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.stdin = mock.MagicMock()
        fake_proc.stdout = mock.MagicMock()

        def fake_popen(*a, **k):
            return fake_proc

        with mock.patch("subprocess.Popen", side_effect=fake_popen):
            with mock.patch.object(eng, "_wait_for", return_value=None):
                with self.assertRaises(RuntimeError):
                    eng.start()
        # stop 應曾被呼叫，process 清空
        self.assertIsNone(eng.process)
        # 至少嘗試過 terminate/kill 或 wait
        self.assertTrue(
            fake_proc.terminate.called
            or fake_proc.kill.called
            or fake_proc.wait.called
            or fake_proc.stdin.write.called
        )


class TestEditorValidation(unittest.TestCase):
    def test_kings_facing_rejected(self):
        b = app.create_empty_xiangqi_board()
        b.pieces.append(app.Piece("帥", app.RED, 4, 9))
        b.pieces.append(app.Piece("將", app.BLACK, 4, 0))
        ok, reason = app.validate_editor_position(b)
        self.assertFalse(ok)

    def test_in_check_rejected(self):
        # 紅車對黑將，黑被將軍
        fen = "4k4/9/9/9/9/9/9/9/4R4/5K3 w - - 0 1"
        b = app.XiangqiBoard(fen=fen)
        ok, reason = app.validate_editor_position(b)
        self.assertFalse(ok)
        self.assertTrue("將軍" in reason or "check" in reason.lower() or "将" in reason)

    def test_piece_count_limit(self):
        b = app.create_empty_xiangqi_board()
        b.pieces.append(app.Piece("帥", app.RED, 5, 9))
        b.pieces.append(app.Piece("將", app.BLACK, 4, 0))
        b.pieces.append(app.Piece("車", app.RED, 0, 9))
        b.pieces.append(app.Piece("車", app.RED, 8, 9))
        b.pieces.append(app.Piece("車", app.RED, 0, 7))  # 第 3 隻紅車
        ok, reason = app.validate_piece_counts(b)
        self.assertFalse(ok)
        self.assertIn("車", reason)

    def test_pawn_max_five(self):
        self.assertEqual(app.PIECE_MAX_COUNT["兵"], 5)
        self.assertEqual(app.PIECE_MAX_COUNT["馬"], 2)
        self.assertEqual(app.PIECE_MAX_COUNT["帥"], 1)

    def test_legal_quiet_position_ok(self):
        # 將帥錯開 + 無攻擊
        fen = "3k5/9/9/9/9/9/9/9/9/5K3 w - - 0 1"
        b = app.XiangqiBoard(fen=fen)
        ok, reason = app.validate_editor_position(b)
        self.assertTrue(ok, reason)


class TestSideIdentity(unittest.TestCase):
    def test_red_black_are_idents_not_rgb(self):
        self.assertEqual(app.RED, "red")
        self.assertEqual(app.BLACK, "black")
        self.assertIsInstance(app.side_rgb(app.RED), tuple)
        self.assertEqual(app.side_rgb(app.RED), (168, 36, 32))
        self.assertEqual(app.side_rgb(app.BLACK), (22, 20, 18))

    def test_piece_color_is_identity(self):
        board = app.XiangqiBoard()
        king = board.get_king(app.RED)
        self.assertEqual(king.color, app.RED)
        self.assertEqual(king.color, "red")


class TestValidateLegalPosition(unittest.TestCase):
    def test_shared_helper_matches_wrappers(self):
        fen = "3k5/9/9/9/9/9/9/9/9/5K3 w - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        ok_shared, _ = app.validate_legal_position(board, require_piece_limits=True)
        ok_editor, _ = app.validate_editor_position(board)
        self.assertEqual(ok_shared, ok_editor)
        self.assertTrue(ok_editor)

    def test_endgame_wrapper_uses_shared(self):
        fen = "4k4/9/4N4/9/9/9/9/9/9/3C1K3 w - - 0 1"
        board = app.XiangqiBoard(fen=fen)
        ok_a, ra = app.validate_endgame_start_position(board)
        ok_b, rb = app.validate_legal_position(board, require_opponent_has_move=True)
        self.assertEqual(ok_a, ok_b)
        self.assertEqual(ra, rb)


class TestGameResult(unittest.TestCase):
    def test_checkmate_sets_typed_result(self):
        fen = "4k4/9/4N4/9/9/9/9/9/9/3C1K3 w - - 0 1"
        board = app.XiangqiBoard(game_mode=app.MODE_PVP, fen=fen)
        cannon = board.get_piece_at(3, 9)
        self.assertTrue(board.move_piece(cannon, 4, 9))
        self.assertIsNotNone(board.result)
        self.assertEqual(board.result.kind, app.ResultKind.CHECKMATE)
        self.assertEqual(board.result.winner, app.RED)
        self.assertEqual(board.winner, app.RED)
        self.assertEqual(board.draw_reason, "")

    def test_timeout_kind_keeps_winner_and_message(self):
        board = app.XiangqiBoard(game_mode=app.MODE_PVP)
        board.set_result(app.ResultKind.TIMEOUT, winner=app.BLACK, message="紅方超時，黑方獲勝")
        self.assertEqual(board.result.kind, app.ResultKind.TIMEOUT)
        self.assertEqual(board.winner, app.BLACK)
        self.assertEqual(board.draw_reason, "紅方超時，黑方獲勝")


class TestMoveNotation(unittest.TestCase):
    def test_red_pawn_forward_is_file_plus_distance(self):
        board = app.XiangqiBoard()
        pawn = board.get_piece_at(6, 6)
        self.assertIsNotNone(pawn)
        self.assertEqual(
            board.generate_move_notation(pawn, 6, 6, 6, 5),
            "兵三進一",
        )

    def test_red_rook_horizontal_is_dest_file(self):
        board = app.XiangqiBoard()
        rook = board.get_piece_at(0, 9)
        self.assertIsNotNone(rook)
        self.assertEqual(
            board.generate_move_notation(rook, 0, 9, 4, 9),
            "車九平五",
        )

    def test_knight_always_uses_dest_file(self):
        board = app.XiangqiBoard()
        knight = board.get_piece_at(1, 9)
        self.assertIsNotNone(knight)
        self.assertEqual(
            board.generate_move_notation(knight, 1, 9, 2, 7),
            "馬八進七",
        )


class TestLongCheck(unittest.TestCase):
    def test_three_consecutive_checks_by_same_piece_loses(self):
        # 帥放邊線，避免將在中線躲避時與帥照面誤判將死
        fen = "4k4/9/9/9/9/9/9/9/4R4/8K w - - 0 1"
        board = app.XiangqiBoard(game_mode=app.MODE_PVP, fen=fen)
        rook = board.get_piece_at(4, 8)
        king = board.get_king(app.BLACK)
        self.assertTrue(board.move_piece(rook, 4, 2))
        self.assertTrue(board.is_check)
        self.assertIsNone(board.winner)
        self.assertTrue(board.move_piece(king, 5, 0))
        self.assertTrue(board.move_piece(rook, 5, 2))
        self.assertTrue(board.is_check)
        self.assertIsNone(board.winner)
        self.assertTrue(board.move_piece(king, 4, 0))
        self.assertTrue(board.move_piece(rook, 4, 2))
        self.assertEqual(board.result.kind, app.ResultKind.LONG_CHECK)
        self.assertEqual(board.winner, app.BLACK)
        self.assertIn("長將", board.draw_reason)

    def test_endgame_mode_does_not_lose_on_short_checks(self):
        fen = "4k4/9/9/9/9/9/9/9/4R4/8K w - - 0 1"
        board = app.XiangqiBoard(game_mode=app.MODE_ENDGAME, fen=fen)
        rook = board.get_piece_at(4, 8)
        king = board.get_king(app.BLACK)
        self.assertTrue(board.move_piece(rook, 4, 2))
        self.assertTrue(board.move_piece(king, 5, 0))
        self.assertTrue(board.move_piece(rook, 5, 2))
        self.assertTrue(board.move_piece(king, 4, 0))
        self.assertTrue(board.move_piece(rook, 4, 2))
        self.assertIsNone(board.winner)
        if board.draw_reason:
            self.assertNotIn("長將", board.draw_reason)


class TestEndgameCatalog(unittest.TestCase):
    def test_every_catalog_fen_is_legal_start(self):
        levels, err = app.load_endgames_catalog()
        self.assertIsNone(err)
        self.assertGreaterEqual(len(levels), 10)
        for lv in levels:
            board = app.XiangqiBoard(game_mode=app.MODE_ENDGAME, fen=lv["fen"])
            ok, reason = app.validate_endgame_start_position(board)
            self.assertTrue(ok, msg=f"{lv['id']} {lv.get('title')}: {reason}")

    def test_generator_has_no_duplicate_candidate_list(self):
        import gen_endgames_with_pikafish as gen
        self.assertFalse(hasattr(gen, "CANDIDATES"))


class TestEndgameUnlock(unittest.TestCase):
    def test_clearing_previous_unlocks_next_in_same_list(self):
        levels = [
            {"id": "a", "unlock_after": None},
            {"id": "b", "unlock_after": "other_group_id"},
            {"id": "c", "unlock_after": "still_other"},
        ]
        cleared = set()
        self.assertTrue(app.is_unlocked_in_sequence(levels, 0, cleared))
        self.assertFalse(app.is_unlocked_in_sequence(levels, 1, cleared))
        cleared.add("a")
        self.assertTrue(app.is_unlocked_in_sequence(levels, 1, cleared))
        self.assertFalse(app.is_unlocked_in_sequence(levels, 2, cleared))
        cleared.add("b")
        self.assertTrue(app.is_unlocked_in_sequence(levels, 2, cleared))

    def test_cleared_level_stays_open(self):
        levels = [{"id": "a"}, {"id": "b"}]
        self.assertTrue(app.is_unlocked_in_sequence(levels, 1, {"b"}))

    def test_catalog_beginner_list_ignores_cross_group_unlock_after(self):
        """定式入門／初級列表依畫面順序解鎖，不被 unlock_after 指向高級關卡住。"""
        levels, err = app.load_endgames_catalog()
        self.assertIsNone(err)
        beginner_diffs = (1, 2)
        filtered = sorted(
            [
                lv for lv in levels
                if lv.get("section") == app.ENDGAME_SECTION_FORMULA
                and int(lv.get("difficulty") or 1) in beginner_diffs
            ],
            key=lambda lv: (int(lv.get("difficulty") or 1), str(lv.get("id") or "")),
        )
        self.assertGreaterEqual(len(filtered), 3)
        eg013 = next(lv for lv in filtered if lv["id"] == "eg_013")
        self.assertEqual(eg013.get("unlock_after"), "eg_006")
        idx = next(i for i, lv in enumerate(filtered) if lv["id"] == "eg_013")
        prev = {filtered[idx - 1]["id"]}
        self.assertFalse(app.is_endgame_unlocked(eg013, prev))
        self.assertTrue(app.is_unlocked_in_sequence(filtered, idx, prev))
        self.assertTrue(app.is_unlocked_in_sequence(filtered, 0, set()))
        self.assertTrue(app.is_unlocked_in_sequence(filtered, 1, {filtered[0]["id"]}))


class TestSavePayload(unittest.TestCase):
    def test_corrupt_save_does_not_crash_load_helpers(self):
        # 僅驗證 json 錯誤可被捕獲的模式（load_game 在 main 內，此處測 progress）
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{not-json")
            data = app.load_endgame_progress(path)
            self.assertEqual(data["cleared"], [])


if __name__ == "__main__":
    unittest.main()
