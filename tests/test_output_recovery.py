"""输出被截断时的有限自动恢复。全部走本地 mock，不调用真实 API。"""
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

os.environ.setdefault("AICHESS_MOVE_DELAY", "0.01")
os.environ.setdefault("AICHESS_NETWORK_BACKOFF", "0.05,0.05")

import app as server
import mock_openai_server as mock
from models.output_budget import next_truncation_budget, starting_budget

FAKE = "test-only-secret-not-a-real-key"


def ai(base, **over):
    data = {
        "provider": "custom",
        "display_name": "自定义截断模型",
        "model_name": "custom-trunc",
        "base_url": base,
        "api_key": FAKE,
        "thinking_mode": "disabled",
        "max_output": 1024,
        "timeout": 8,
    }
    data.update(over)
    return data


class BudgetLadderTests(unittest.TestCase):
    def test_ladder_is_capped(self):
        self.assertEqual(next_truncation_budget(1024), 4096)
        self.assertEqual(next_truncation_budget(4096), 8192)
        self.assertEqual(next_truncation_budget(8192), 8192)
        self.assertEqual(next_truncation_budget(16000), 8192)
        self.assertEqual(starting_budget(1024, 4096), 4096)
        self.assertEqual(starting_budget(1024, 0), 1024)


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), mock.Handler)
        cls.base = f"http://127.0.0.1:{cls.http.server_port}/v1"
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.client = server.app.test_client()
        cls.original = server.GAMES_DIR
        server.GAMES_DIR = tempfile.mkdtemp(prefix="aichess-budget-")

    @classmethod
    def tearDownClass(cls):
        cls.client.post("/api/stop_battle")
        cls.http.shutdown()
        server.GAMES_DIR = cls.original

    def setUp(self):
        self.client.post("/api/reset_battle")
        with mock.state_lock:
            mock.state.update(mode="ok", fail_remaining=0, requests=[], request_count=0, prompts=[],
                              hang_seconds=2, truncate_below=0, answer_mode="", hang_from_request=0)

    def tearDown(self):
        self.client.post("/api/stop_battle")

    def status(self):
        return self.client.get("/api/get_battle_status").get_json()

    def start(self, **player):
        body = self.client.post("/api/start_battle", json={
            "game": "gomoku",
            "mode": "human_vs_ai",
            "human_side": "second",
            "black_player": ai(self.base, **player),
        })
        data = body.get_json()
        self.assertEqual(body.status_code, 200, data)
        return data

    def wait_until(self, pred, timeout=8, desc="condition"):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.status()
            if pred(last):
                return last
            time.sleep(0.05)
        self.fail(f"timeout waiting for {desc}: {last!r}")

    def budgets(self):
        with mock.state_lock:
            return [item.get("max_tokens") for item in mock.state.get("requests") or []]

    def test_length_empty_retries_with_higher_budget_then_plays(self):
        with mock.state_lock:
            mock.state["truncate_below"] = 4096
        self.start(display_name="DeepSeek V4 Flash（更快）", model_name="deepseek-flash", provider="deepseek")
        moved = self.wait_until(lambda s: s.get("move_count") == 1, desc="move after truncation retry")
        self.assertEqual(moved["moves"][0]["move"], "A1")
        self.assertNotEqual(moved["moves"][0]["move"], "H8")
        self.assertEqual(self.budgets(), [1024, 4096])
        self.assertNotIn("合法棋步", moved.get("pause_reason") or "")
        self.assertEqual(moved["status"], "playing")
        with mock.state_lock:
            sent = mock.state["requests"]
        self.assertTrue(all(item.get("model") == "deepseek-flash" for item in sent))
        self.assertTrue(all(item.get("thinking") == {"type": "disabled"} for item in sent))

    def test_length_with_a_real_move_is_accepted_once(self):
        with mock.state_lock:
            mock.state["answer_mode"] = "length_with_move"
        self.start()
        moved = self.wait_until(lambda s: s.get("move_count") == 1, desc="length but content has the move")
        self.assertEqual(self.budgets(), [1024])
        self.assertEqual(moved["moves"][0]["move"], "A1")

    def test_exhausted_ladder_pauses_without_calling_it_an_illegal_move(self):
        with mock.state_lock:
            mock.state["truncate_below"] = 9000
        self.start()
        paused = self.wait_until(lambda s: s.get("status") == "paused", desc="paused after cap")
        self.assertEqual(paused["move_count"], 0)
        self.assertEqual(self.budgets(), [1024, 4096, 8192])
        self.assertNotIn("H8", paused["board_state"])
        self.assertIn("截断", paused["pause_reason"])
        self.assertNotIn("合法棋步", paused["pause_reason"])
        self.assertIn("不是棋力问题", paused["pause_reason"])
        self.assertIn("8192", paused["pause_reason"])

    def test_reasoning_only_does_not_become_a_move(self):
        with mock.state_lock:
            mock.state["answer_mode"] = "reasoning_only"
        self.start()
        paused = self.wait_until(lambda s: s.get("status") == "paused", desc="paused on empty content")
        self.assertEqual(paused["move_count"], 0)
        self.assertNotIn("X", paused["board_state"])
        self.assertEqual(len(self.budgets()), 3)
        self.assertTrue(all(item == 1024 for item in self.budgets()))
        self.assertIn("正文是空的", paused["pause_reason"])
        self.assertIn("不会从思考里猜", paused["pause_reason"])

    def test_bad_content_stays_on_the_same_budget(self):
        with mock.state_lock:
            mock.state["answer_mode"] = "bad_move"
        self.start()
        paused = self.wait_until(lambda s: s.get("status") == "paused", desc="paused on bad move")
        self.assertEqual(len(self.budgets()), 3)
        self.assertTrue(all(item == 1024 for item in self.budgets()))
        self.assertIn("没有合法", paused["pause_reason"])
        self.assertIn("不是输出被截断", paused["pause_reason"])

    def test_later_turn_starts_from_the_budget_that_worked(self):
        with mock.state_lock:
            mock.state["truncate_below"] = 4096
        self.start()
        state = self.wait_until(lambda s: s.get("your_turn"), desc="human turn")
        self.client.post("/api/human_move", json={"battle_id": state["battle_id"], "move": "B2"})
        self.wait_until(lambda s: s.get("move_count") >= 3 or (s.get("move_count") == 2 and not s.get("your_turn")), desc="second ai move", timeout=8)
        self.wait_until(lambda s: s.get("move_count") >= 3, desc="ai replied again")
        self.assertEqual(self.budgets(), [1024, 4096, 4096])

    def test_reset_during_truncation_retry_does_not_enter_the_new_game(self):
        with mock.state_lock:
            mock.state.update(truncate_below=100000, hang_from_request=2, hang_seconds=3)
        data = self.start()
        old = data["state"]["battle_id"]
        self.wait_until(lambda s: mock.state["request_count"] >= 2, desc="second call hanging")
        self.client.post("/api/reset_battle")
        fresh = self.client.post("/api/start_battle", json={"game": "gomoku", "mode": "local_pvp"}).get_json()
        self.assertEqual(fresh["status"], "success", fresh)
        time.sleep(0.4)
        now = self.status()
        self.assertEqual(now["battle_id"], fresh["state"]["battle_id"])
        self.assertNotEqual(now["battle_id"], old)
        self.assertEqual(now["move_count"], 0)
        self.assertNotIn("X", now["board_state"])


if __name__ == "__main__":
    unittest.main()
