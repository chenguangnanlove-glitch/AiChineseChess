"""五子棋自由规则：胜负、满盘、越界、占位、回合，以及和象棋分开的提示词/解析。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.gomoku_game import GomokuGame  # noqa: E402


def play(g, *moves):
    for move in moves:
        if not g.make_move(move):
            raise AssertionError(f"应能落下 {move}，当前 {g.current_player}，局面 {g.get_board_state()}")


class WinTests(unittest.TestCase):
    def test_horizontal_exact_five(self):
        g = GomokuGame()
        play(g, "A1", "A2", "B1", "B2", "C1", "C2", "D1", "D2", "E1")
        status = g.get_game_status()
        self.assertEqual((status["over"], status["winner"], status["reason"]), (True, "black", "five"))
        self.assertIn("五子或以上", status["message"])
        self.assertIn("黑棋", status["message"])
        self.assertEqual(g.get_legal_moves(), [])
        self.assertFalse(g.make_move("F1"))

    def test_vertical_five(self):
        g = GomokuGame()
        play(g, "H1", "A1", "H2", "A2", "H3", "A3", "H4", "A4", "H5")
        self.assertEqual(g.get_game_status()["winner"], "black")
        self.assertEqual(g.get_game_status()["reason"], "five")

    def test_diagonal_down_right(self):
        g = GomokuGame()
        play(g, "A1", "A2", "B2", "A3", "C3", "A4", "D4", "A5", "E5")
        self.assertEqual(g.get_game_status()["winner"], "black")

    def test_diagonal_down_left(self):
        g = GomokuGame()
        play(g, "E1", "H1", "D2", "H2", "C3", "H3", "B4", "H4", "A5")
        self.assertEqual(g.get_game_status()["winner"], "black")

    def test_overline_six_still_wins(self):
        row = "XXXXXX" + "." * 9
        g = GomokuGame()
        g.load_board_state("/".join([row] + ["." * 15] * 14), "white")
        status = g.get_game_status()
        self.assertEqual(status["reason"], "five")
        self.assertEqual(status["winner"], "black")
        self.assertIn("或以上", status["message"])

    def test_four_is_not_yet_a_win(self):
        g = GomokuGame()
        play(g, "A1", "A2", "B1", "B2", "C1", "C2", "D1")
        self.assertFalse(g.is_game_over())
        self.assertEqual(g.get_game_status()["reason"], "ongoing")

    def test_opponent_stone_breaks_the_line(self):
        g = GomokuGame()
        g.load_board_state("/".join(["XXXOX" + "." * 10] + ["." * 15] * 14), "white")
        self.assertFalse(g.is_game_over())


class BoardEndTests(unittest.TestCase):
    def test_full_board_without_five_is_draw(self):
        # 棋盘形棋子会在斜线上连成超过五子，不能拿来当和棋。这里用错开的 XXXXO。
        base = "XXXXO"
        rows = ["".join(base[(c + r * 2) % 5] for c in range(15)) for r in range(15)]
        g = GomokuGame()
        g.load_board_state("/".join(rows), "black")
        status = g.get_game_status()
        self.assertEqual((status["over"], status["winner"], status["reason"]), (True, None, "full"))
        self.assertIn("和棋", status["message"])
        self.assertEqual(g.get_legal_moves(), [])
        self.assertFalse(g.make_move("H8"))

    def test_five_beats_a_full_board(self):
        rows = [["O"] * 15 for _ in range(15)]
        for c in range(5):
            rows[0][c] = "X"
        g = GomokuGame()
        g.load_board_state("/".join("".join(row) for row in rows), "white")
        self.assertEqual(g.get_game_status()["reason"], "five")
        self.assertEqual(g.get_game_status()["winner"], "black")


class LegalityTests(unittest.TestCase):
    def test_opening_is_black_and_has_225_points(self):
        g = GomokuGame()
        self.assertEqual(g.current_player, "black")
        legal = g.get_legal_moves()
        self.assertEqual(len(legal), 225)
        self.assertEqual(legal[0], "A1")
        self.assertIn("H8", legal)
        self.assertIn("O15", legal)
        self.assertNotIn("A0", legal)
        self.assertNotIn("P1", legal)

    def test_turn_alternates_and_stone_color_follows_the_side_to_move(self):
        g = GomokuGame()
        self.assertTrue(g.make_move("h8"))
        self.assertEqual(g.move_history[-1]["move"], "H8")
        self.assertEqual(g.move_history[-1]["player"], "black")
        self.assertEqual(g.board[7][7], "X")
        self.assertEqual(g.current_player, "white")
        self.assertTrue(g.make_move("H9"))
        self.assertEqual(g.board[8][7], "O")
        self.assertEqual(g.current_player, "black")
        # 不能连走：下一手是黑棋，但占位失败不应吃掉回合
        before = g.current_player
        self.assertFalse(g.make_move("H8"))
        self.assertEqual(g.current_player, before)
        self.assertEqual(len(g.move_history), 2)

    def test_out_of_bounds_occupied_and_chess_coordinates_rejected(self):
        g = GomokuGame()
        for bad in ("A0", "A16", "P8", "H", "", "a0a1", "H8H9", "Z9", "H08"):
            self.assertFalse(g.make_move(bad), bad)
        self.assertEqual(g.current_player, "black")
        self.assertEqual(g.move_history, [])
        self.assertTrue(g.make_move("A1"))
        self.assertFalse(g.make_move("A1"))
        self.assertEqual(g.board[0][0], "X")
        self.assertEqual(g.current_player, "white")


class PromptParseTests(unittest.TestCase):
    def test_prompt_is_gomoku_not_xiangqi(self):
        g = GomokuGame()
        prompt = g.build_prompt(g.get_board_state(), [], g.get_legal_moves())
        self.assertIn("五子棋", prompt)
        self.assertIn("无禁手", prompt)
        self.assertIn("五子或更多", prompt)
        self.assertIn("列 A–O", prompt)
        self.assertIn("行 1–15", prompt)
        self.assertIn("落子：", prompt)
        self.assertNotIn("棋步：", prompt)
        self.assertNotIn("列a-i", prompt)
        self.assertNotIn("行0-9", prompt)
        self.assertIn("合法落点", prompt)

    def test_parser_accepts_labeled_point_and_ignores_xiangqi_moves(self):
        g = GomokuGame()
        legal = g.get_legal_moves()
        parsed = g.parse_model_response("分析：占中\n策略：先连\n落子：H8", legal)
        self.assertEqual(parsed["move"], "H8")
        fullwidth = g.parse_model_response("落子：Ｈ８", legal)
        self.assertEqual(fullwidth["move"], "H8")
        self.assertIsNone(g.parse_model_response("棋步：h7e7", legal))
        self.assertIsNone(g.parse_model_response("棋步：a0a1", legal))
        self.assertIsNone(g.parse_model_response("落子：h7e7", legal))
        mixed = g.parse_model_response("别走棋步：h7e7。\n落子：C3", legal)
        self.assertEqual(mixed["move"], "C3")
        last = g.parse_model_response("落子：A1\n不对，改落子：O15", legal)
        self.assertEqual(last["move"], "O15")

    def test_system_prompt_rejects_xiangqi_coordinates(self):
        text = GomokuGame().system_prompt()
        self.assertIn("五子棋", text)
        self.assertIn("无禁手", text)
        self.assertNotIn("帅", text)


if __name__ == "__main__":
    unittest.main()
