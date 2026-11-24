"""中国象棋规则单元测试：将军检测、白脸将、蹩马腿、将死、困毙、开局走法数。

运行：uv run python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.chess_game import ChessGame  # noqa: E402
from models.llm_player import LLMPlayer  # noqa: E402

EMPTY = "." * 9


def board_from(pieces):
    """pieces: {"e9": "K", ...} → 棋盘字符串（行 0 在上）"""
    rows = [list(EMPTY) for _ in range(10)]
    for coord, p in pieces.items():
        rows[int(coord[1])][ord(coord[0]) - 97] = p
    return "/".join("".join(r) for r in rows)


def game_with(pieces, side="red"):
    g = ChessGame()
    g.load_board_state(board_from(pieces), side)
    return g


class OpeningTests(unittest.TestCase):
    def test_opening_has_44_legal_moves(self):
        self.assertEqual(len(ChessGame().get_legal_moves()), 44)

    def test_perft_depth_2_and_3(self):
        # 标准中国象棋 perft：1=44, 2=1920, 3=79666
        g = ChessGame()

        def perft(d):
            if d == 0:
                return 1
            n = 0
            for m in g.get_legal_moves():
                self.assertTrue(g.make_move(m), m)
                n += perft(d - 1)
                g.undo_last_move()
            return n

        self.assertEqual(perft(2), 1920)
        self.assertEqual(perft(3), 79666)


class UserBugPositionTests(unittest.TestCase):
    """用户实战局面类型：黑炮在中路隔一个黑卒对着红帅，红方被将军。"""

    def setUp(self):
        g = ChessGame()
        # 黑炮 h2 平到 e2；红中兵 e6 已不在 → e2 炮 隔 e3 黑卒 将 e9 帅
        g.board[2][7] = '.'
        g.board[2][4] = 'c'
        g.board[6][4] = '.'
        g.current_player = "red"
        self.g = g

    def test_red_is_in_check_by_cannon_over_pawn(self):
        self.assertTrue(self.g.is_in_check("red"))
        self.assertEqual(self.g.checking_pieces("red"), ["e2"])

    def test_only_check_answers_are_legal(self):
        legal = set(self.g.get_legal_moves())
        # 垫子：炮 b7/h7 平到 e7、仕 d9/f9 上 e8、相 c9/g9 上 e7
        self.assertEqual(legal, {"b7e7", "h7e7", "d9e8", "f9e8", "c9e7", "g9e7"})
        for mv in legal:
            self.g.make_move(mv)
            self.assertFalse(self.g.is_in_check("red"), mv)
            self.g.undo_last_move()

    def test_non_answering_moves_rejected(self):
        for mv in ("h9g7", "a6a5", "i9i8", "b9c7", "e9e8"):
            self.assertTrue(self.g.is_pseudo_legal_move(self.g.coord_to_pos(mv[:2]), self.g.coord_to_pos(mv[2:])) or mv == "e9e8")
            self.assertFalse(self.g.make_move(mv), mv)
        self.assertEqual(self.g.current_player, "red")
        self.assertEqual(self.g.move_history, [])

    def test_prompt_tells_model_it_is_in_check(self):
        p = LLMPlayer("kimi-k3.1-pro-highspeed", "k")
        prompt = p.build_chess_prompt(self.g.get_board_state(), [], self.g.get_legal_moves(),
                                      in_check=True, checkers=self.g.checking_pieces("red"))
        self.assertIn("你正被将军", prompt)
        self.assertIn("必须应将", prompt)
        self.assertIn("e2", prompt)


class FlyingGeneralTests(unittest.TestCase):
    def test_pinned_piece_between_kings_cannot_leave_file(self):
        g = game_with({"e0": "k", "e4": "n", "e9": "K"}, side="black")
        legal = set(g.get_legal_moves())
        self.assertFalse(any(m.startswith("e4") for m in legal))
        self.assertEqual(legal, {"e0d0", "e0f0", "e0e1"})

    def test_king_cannot_step_onto_open_file_facing(self):
        g = game_with({"e0": "k", "d9": "K", "a5": "P"}, side="black")
        legal = set(g.get_legal_moves())
        self.assertNotIn("e0d0", legal)
        self.assertIn("e0f0", legal)
        self.assertIn("e0e1", legal)

    def test_facing_counts_as_check(self):
        g = game_with({"e0": "k", "e9": "K"}, side="red")
        self.assertTrue(g.kings_facing())
        self.assertTrue(g.is_in_check("red"))
        self.assertTrue(g.is_in_check("black"))


class HorseLegTests(unittest.TestCase):
    def test_blocked_leg_in_opening(self):
        legal = set(ChessGame().get_legal_moves())
        self.assertIn("b9a7", legal)
        self.assertIn("b9c7", legal)
        self.assertNotIn("b9d8", legal)  # c9 相 蹩马腿

    def test_blocked_leg_stops_moves(self):
        g = ChessGame()
        g.board[8][1] = 'C'  # b8 放子
        g.board[7][1] = '.'
        legal = set(g.get_legal_moves())
        self.assertNotIn("b9a7", legal)
        self.assertNotIn("b9c7", legal)

    def test_horse_check_depends_on_leg(self):
        g = game_with({"e9": "K", "d7": "n", "f0": "k", "a3": "p"}, side="red")
        self.assertTrue(g.is_in_check("red"))   # d7 马 腿 d8 空 → 将军
        g.board[8][3] = 'A'                       # d8 放红仕
        self.assertFalse(g.is_in_check("red"))  # 蹩马腿 → 不算将军


class PieceRuleTests(unittest.TestCase):
    def test_cannon_needs_exactly_one_screen(self):
        g = game_with({"e9": "K", "a9": "C", "a5": "p", "a3": "p", "a0": "r", "d0": "k"}, side="red")
        legal = set(g.get_legal_moves())
        self.assertIn("a9a3", legal)       # 隔 a5 吃 a3
        self.assertNotIn("a9a5", legal)    # 不能直接吃
        self.assertNotIn("a9a0", legal)    # 隔两子不行
        self.assertIn("a9a6", legal)

    def test_rook_check(self):
        g = game_with({"e9": "K", "e5": "r", "d0": "k"}, side="red")
        self.assertTrue(g.is_in_check("red"))
        g.board[7][4] = 'P'
        self.assertFalse(g.is_in_check("red"))

    def test_pawns_sideways_only_after_river(self):
        g = game_with({"e9": "K", "d0": "k", "e4": "P", "g6": "P"}, side="red")
        legal = set(g.get_legal_moves())
        self.assertTrue({"e4e3", "e4d4", "e4f4"} <= legal)
        self.assertIn("g6g5", legal)
        self.assertNotIn("g6f6", legal)
        self.assertNotIn("g6h6", legal)
        self.assertNotIn("e4e5", legal)   # 兵不能后退

    def test_black_pawn_check_sideways(self):
        g = game_with({"e9": "K", "d9": "p", "f0": "k"}, side="red")
        self.assertTrue(g.is_in_check("red"))   # 过河卒横走将军
        g2 = game_with({"e9": "K", "e8": "p", "f0": "k"}, side="red")
        self.assertTrue(g2.is_in_check("red"))  # 卒在帅正前方


class GameEndTests(unittest.TestCase):
    def test_classic_checkmate(self):
        # 双车错：车 a0 将军，车 i1 封住第 1 行，帅 d9 控制 d 线
        g = game_with({"e0": "k", "a0": "R", "i1": "R", "d9": "K", "i6": "p"}, side="black")
        self.assertTrue(g.is_in_check("black"))
        self.assertEqual(g.get_legal_moves(), [])
        st = g.get_game_status()
        self.assertEqual((st["over"], st["winner"], st["reason"]), (True, "red", "checkmate"))
        self.assertTrue(g.is_game_over())
        self.assertEqual(g.get_game_result(), "红方获胜")

    def test_mate_reached_by_a_move(self):
        g = game_with({"e0": "k", "a2": "R", "i1": "R", "d9": "K", "i6": "p"}, side="red")
        self.assertFalse(g.is_game_over())
        self.assertTrue(g.make_move("a2a0"))
        st = g.get_game_status()
        self.assertEqual(st["reason"], "checkmate")
        self.assertEqual(st["winner"], "red")

    def test_stalemate_is_loss(self):
        # 黑将 d0 未被将，但 d1 被车控制、e0 会和帅照面 → 无子可动（困毙）
        g = game_with({"d0": "k", "a1": "R", "e9": "K"}, side="black")
        self.assertFalse(g.is_in_check("black"))
        self.assertEqual(g.get_legal_moves(), [])
        st = g.get_game_status()
        self.assertEqual((st["over"], st["winner"], st["reason"]), (True, "red", "stalemate"))

    def test_move_limit_draw(self):
        g = ChessGame()
        g.max_moves = 4
        for mv in ("b9c7", "b0c2", "c7b9", "c2b0"):
            self.assertTrue(g.make_move(mv))
        st = g.get_game_status()
        self.assertEqual((st["over"], st["winner"], st["reason"]), (True, None, "move_limit"))
        self.assertEqual(g.get_game_result(), "平局")

    def test_battle_result_names_winner(self):
        from models.battle import ChessBattle
        b = ChessBattle(LLMPlayer("deepseek-flash", "k", display_name="红AI"),
                        LLMPlayer("kimi-k3.1-pro-highspeed", "k", display_name="黑AI"))
        b.game.load_board_state(board_from({"e0": "k", "a0": "R", "i1": "R", "d9": "K"}), "black")
        r = b.get_battle_result()
        self.assertEqual(r["winner"], "红AI")
        self.assertEqual(r["winner_color"], "red")
        self.assertEqual(r["reason"], "checkmate")
        self.assertIn("将死", r["message"])


if __name__ == "__main__":
    unittest.main()
