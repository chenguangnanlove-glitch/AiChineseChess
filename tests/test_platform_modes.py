"""两种游戏、三种模式：人机 mock、同机双人、AI 对 AI、非法着法、断网、停止/重置后的迟到响应。"""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

os.environ.setdefault("AICHESS_MOVE_DELAY", "0.01")
os.environ.setdefault("AICHESS_NETWORK_BACKOFF", "0.05,0.05,0.05")

import app as server
import mock_openai_server as mock

FAKE = "test-only-secret-not-a-real-key"


def ai(base, name="mock-model", display="测试模型"):
    return {
        "provider": "custom",
        "display_name": display,
        "model_name": name,
        "base_url": base,
        "api_key": FAKE,
        "thinking_mode": "disabled",
        "max_output": 1024,
        "timeout": 8,
    }


class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), mock.Handler)
        cls.base = f"http://127.0.0.1:{cls.http.server_port}/v1"
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.client = server.app.test_client()
        cls.original_dir = server.GAMES_DIR
        server.GAMES_DIR = tempfile.mkdtemp(prefix="aichess-platform-")

    @classmethod
    def tearDownClass(cls):
        cls.client.post("/api/stop_battle")
        cls.http.shutdown()
        server.GAMES_DIR = cls.original_dir

    def setUp(self):
        self.client.post("/api/reset_battle")
        with mock.state_lock:
            mock.state.update(mode="ok", fail_remaining=0, requests=[], request_count=0, prompts=[], hang_seconds=2)
        self.events = []
        self._real_emit = server.socketio.emit

        def spy(event, data=None, **kwargs):
            self.events.append((event, data))
            return self._real_emit(event, data, **kwargs)

        server.socketio.emit = spy

    def tearDown(self):
        server.socketio.emit = self._real_emit
        self.client.post("/api/stop_battle")
        battle = server.current_battle
        thread = getattr(battle, "loop_thread", None) if battle else None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def status(self):
        return self.client.get("/api/get_battle_status").get_json()

    def start(self, payload):
        response = self.client.post("/api/start_battle", json=payload)
        body = response.get_json()
        return response.status_code, body

    def wait_until(self, pred, timeout=8, desc="condition"):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.status()
            try:
                if pred(last):
                    return last
            except Exception as exc:  # noqa
                last = exc
            time.sleep(0.05)
        self.fail(f"timeout waiting for {desc}: {last!r}")

    def human(self, battle_id, move):
        response = self.client.post("/api/human_move", json={"battle_id": battle_id, "move": move})
        return response.status_code, response.get_json()

    def test_local_pvp_both_games_make_no_api_calls(self):
        code, body = self.start({"game": "xiangqi", "mode": "local_pvp"})
        self.assertEqual(code, 200, body)
        state = self.wait_until(lambda s: s.get("phase") == "human_turn" and "a6a5" in s.get("legal_moves", []), desc="xiangqi human")
        self.assertEqual(state["game"], "xiangqi")
        self.assertEqual(state["mode"], "local_pvp")
        self.assertTrue(state["your_turn"])
        self.assertEqual(mock.state["request_count"], 0)
        code, denied = self.human(state["battle_id"], "a0a1")
        self.assertEqual(code, 400, denied)
        self.assertEqual(denied["error_type"], "illegal")
        self.assertEqual(self.status()["move_count"], 0)
        self.assertEqual(self.status()["current_player"], "red")
        code, ok = self.human(state["battle_id"], "a6a5")
        self.assertEqual(code, 200, ok)
        moved = self.wait_until(lambda s: s.get("move_count") == 1 and s.get("current_player") == "black", desc="black to move")
        self.assertEqual(mock.state["request_count"], 0)
        record = json.load(open(moved["record_path"], encoding="utf-8"))
        self.assertEqual(record["game"], "xiangqi")
        self.assertEqual(record["mode"], "local_pvp")
        self.assertEqual(record["participants"]["red"]["kind"], "human")
        self.assertEqual(record["participants"]["black"]["kind"], "human")
        self.assertNotIn(FAKE, json.dumps(record))
        self.assertNotIn("api_key", json.dumps(record))

        self.client.post("/api/reset_battle")
        code, body = self.start({"game": "gomoku", "mode": "local_pvp"})
        self.assertEqual(code, 200, body)
        state = self.wait_until(lambda s: s.get("your_turn") and s.get("game") == "gomoku", desc="gomoku human")
        bid = state["battle_id"]
        script = ["H8", "A1", "H9", "A2", "H10", "A3", "H11", "A4", "H12"]
        for move in script:
            self.wait_until(lambda s: s.get("your_turn"), desc=f"turn before {move}")
            code, placed = self.human(bid, move)
            self.assertEqual(code, 200, placed)
            self.wait_until(lambda s, n=script.index(move) + 1: s.get("move_count") >= n or (s.get("status") == "finished"), desc=move)
        finished = self.wait_until(lambda s: s.get("status") == "finished", desc="gomoku win")
        self.assertEqual(finished["result"]["reason"], "five")
        self.assertEqual(finished["result"]["winner_color"], "black")
        self.assertEqual(mock.state["request_count"], 0)
        record = json.load(open(finished["record_path"], encoding="utf-8"))
        self.assertEqual(record["game"], "gomoku")
        self.assertEqual(record["mode"], "local_pvp")
        self.assertIn("无禁手", record["rules"])
        self.assertEqual(record["participants"]["black"]["kind"], "human")
        self.assertEqual(record["participants"]["white"]["kind"], "human")
        self.assertNotIn("red", record)

    def test_human_vs_ai_hides_thinking_until_move_and_rejects_early_clicks(self):
        with mock.state_lock:
            mock.state.update(mode="hang", fail_remaining=1, hang_seconds=1.2, request_count=0)
        code, body = self.start({
            "game": "gomoku",
            "mode": "human_vs_ai",
            "human_side": "second",
            "black_player": ai(self.base, "gomoku-ai", "黑棋模型"),
        })
        self.assertEqual(code, 200, body)
        bid = body["state"]["battle_id"]
        self.wait_until(lambda s: s.get("phase") == "thinking", desc="ai thinking")
        code, rejected = self.human(bid, "H8")
        self.assertEqual(code, 409, rejected)
        self.assertEqual(rejected["error_type"], "turn")
        self.assertEqual(self.status()["move_count"], 0)
        self.assertNotIn("X", self.status()["board_state"])
        with mock.state_lock:
            mock.state.update(mode="ok", fail_remaining=0)
        moved = self.wait_until(lambda s: s.get("move_count") == 1 and s.get("your_turn"), desc="ai placed")
        self.assertEqual(moved["current_player"], "white")
        self.assertIn("X", moved["board_state"])
        streams = [data for name, data in self.events if name == "thinking_stream" and isinstance(data, dict) and data.get("battle_id") == bid]
        self.assertEqual(streams, [])
        self.assertGreaterEqual(mock.state["request_count"], 1)
        made = [data for name, data in self.events if name == "move_made" and isinstance(data, dict) and data.get("battle_id") == bid]
        self.assertTrue(made)
        self.assertTrue(made[0].get("thinking_hidden"))
        self.assertEqual(made[0].get("thinking"), "")
        self.assertTrue(made[0].get("sealed_thinking"))
        prompts = mock.state.get("prompts") or []
        self.assertTrue(prompts)
        self.assertIn("五子棋", prompts[0])
        self.assertIn("落子：", prompts[0])
        self.assertNotIn("棋步：", prompts[0])

    def test_late_api_after_reset_does_not_enter_the_new_game(self):
        with mock.state_lock:
            mock.state.update(mode="hang", fail_remaining=5, hang_seconds=1.5, request_count=0)
        code, body = self.start({
            "game": "gomoku",
            "mode": "human_vs_ai",
            "human_side": "second",
            "black_player": ai(self.base),
        })
        self.assertEqual(code, 200, body)
        old_id = body["state"]["battle_id"]
        self.wait_until(lambda s: mock.state["request_count"] >= 1, desc="request in flight")
        self.client.post("/api/reset_battle")
        self.assertEqual(self.status()["status"], "no_battle")
        code, body = self.start({"game": "gomoku", "mode": "local_pvp"})
        self.assertEqual(code, 200, body)
        new_id = body["state"]["battle_id"]
        self.assertNotEqual(old_id, new_id)
        code, stale = self.human(old_id, "H8")
        self.assertEqual(code, 409, stale)
        self.assertEqual(stale["error_type"], "stale")
        time.sleep(1.8)
        quiet = self.status()
        self.assertEqual(quiet["battle_id"], new_id)
        self.assertEqual(quiet["move_count"], 0)
        self.assertNotIn("X", quiet["board_state"])
        self.assertNotIn("O", quiet["board_state"])
        code, placed = self.human(new_id, "H8")
        self.assertEqual(code, 200, placed)
        landed = self.wait_until(lambda s: s.get("move_count") == 1, desc="new game move")
        self.assertEqual(landed["moves"][0]["move"], "H8")
        self.assertEqual(landed["moves"][0]["player"], "black")

    def test_new_game_requires_confirmation_and_does_not_keep_old_state(self):
        code, body = self.start({"game": "xiangqi", "mode": "local_pvp"})
        state = self.wait_until(lambda s: "a6a5" in s.get("legal_moves", []), desc="ready")
        self.human(state["battle_id"], "a6a5")
        self.wait_until(lambda s: s.get("move_count") == 1, desc="played")
        code, blocked = self.start({"game": "gomoku", "mode": "local_pvp"})
        self.assertEqual(code, 409, blocked)
        self.assertEqual(blocked["error_type"], "confirm_required")
        kept = self.status()
        self.assertEqual(kept["game"], "xiangqi")
        self.assertEqual(kept["move_count"], 1)
        self.assertIn("a6a5", [m["move"] for m in kept["moves"]])
        code, body = self.start({"game": "gomoku", "mode": "local_pvp", "confirm_replace": True})
        self.assertEqual(code, 200, body)
        fresh = self.wait_until(lambda s: s.get("game") == "gomoku" and s.get("move_count") == 0, desc="fresh gomoku")
        self.assertNotIn("a6a5", fresh["board_state"])
        self.assertEqual(fresh["current_player"], "black")
        self.assertEqual(len(fresh["board_state"].split("/")), 15)

    def test_ai_vs_ai_gomoku_and_xiangqi_human_each_use_their_own_parser(self):
        code, body = self.start({
            "game": "gomoku",
            "mode": "ai_vs_ai",
            "black_player": ai(self.base, "black-model", "黑模型"),
            "white_player": ai(self.base, "white-model", "白模型"),
        })
        self.assertEqual(code, 200, body)
        self.wait_until(lambda s: s.get("move_count") >= 2, desc="two gomoku moves")
        self.client.post("/api/stop_battle")
        prompts = list(mock.state.get("prompts") or [])
        self.assertGreaterEqual(len(prompts), 2)
        self.assertTrue(all("五子棋" in p and "落子：" in p and "棋步：" not in p for p in prompts))
        record = json.load(open(self.status()["record_path"], encoding="utf-8"))
        self.assertEqual(record["game"], "gomoku")
        self.assertEqual(record["mode"], "ai_vs_ai")
        self.assertEqual(record["participants"]["black"]["kind"], "ai")
        self.assertEqual(record["participants"]["white"]["kind"], "ai")
        self.assertEqual({record["participants"]["black"]["model_name"], record["participants"]["white"]["model_name"]}, {"black-model", "white-model"})
        self.assertNotIn(FAKE, json.dumps(record))

        self.client.post("/api/reset_battle")
        with mock.state_lock:
            mock.state.update(request_count=0, prompts=[], requests=[])
        code, body = self.start({
            "game": "xiangqi",
            "mode": "human_vs_ai",
            "human_side": "first",
            "black_player": ai(self.base, "xiangqi-ai", "黑方模型"),
        })
        self.assertEqual(code, 200, body)
        state = self.wait_until(lambda s: s.get("your_turn") and s.get("game") == "xiangqi", desc="human red")
        self.assertEqual(mock.state["request_count"], 0)
        self.human(state["battle_id"], "a6a5")
        answered = self.wait_until(lambda s: s.get("move_count") >= 2, desc="ai answered")
        self.assertGreaterEqual(mock.state["request_count"], 1)
        xiangqi_prompts = mock.state.get("prompts") or []
        self.assertTrue(any("中国象棋" in p and "棋步：" in p for p in xiangqi_prompts))
        self.assertTrue(all("五子棋" not in p for p in xiangqi_prompts))
        record = json.load(open(answered["record_path"], encoding="utf-8"))
        self.assertEqual(record["game"], "xiangqi")
        self.assertEqual(record["mode"], "human_vs_ai")
        self.assertEqual(record["participants"]["red"]["kind"], "human")
        self.assertEqual(record["participants"]["black"]["kind"], "ai")
        self.assertNotIn(FAKE, json.dumps(record))

    def test_network_retry_still_works_for_the_ai_side_only(self):
        with mock.state_lock:
            mock.state.update(mode="503", fail_remaining=1, request_count=0)
        code, body = self.start({
            "game": "xiangqi",
            "mode": "human_vs_ai",
            "human_side": "second",
            "red_player": ai(self.base, "red-net", "红方模型"),
        })
        self.assertEqual(code, 200, body)
        self.wait_until(lambda s: s.get("move_count") >= 1, desc="recovered move", timeout=10)
        self.assertGreaterEqual(mock.state["request_count"], 2)
        self.assertTrue(any(name == "network_retry" for name, _ in self.events))
        self.assertNotIn(FAKE, json.dumps(self.events, ensure_ascii=False, default=str))

    def test_missing_ai_config_does_not_call_api(self):
        before = mock.state["request_count"]
        code, body = self.start({"game": "gomoku", "mode": "human_vs_ai", "human_side": "first"})
        self.assertEqual(code, 400, body)
        self.assertEqual(body["error_type"], "config")
        self.assertIn("AI", body["message"])
        self.assertEqual(mock.state["request_count"], before)
        self.assertEqual(self.status()["status"], "no_battle")


if __name__ == "__main__":
    unittest.main()
