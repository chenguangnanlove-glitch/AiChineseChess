#!/usr/bin/env python3
"""端到端测试：真实 Flask-SocketIO 服务 + mock OpenAI 兼容接口 + socket.io 客户端（模拟网页）。

覆盖：
- 残局开局，mock 引擎走棋，一直下到将死，game_over 事件 + 棋谱 JSON 写入结果和原因
- 用户 bug 局面（炮隔卒将军）：提示词带「你正被将军」，模型只能走应将着法
- 步数上限判和
- 网络重连一开始就有「立即重试」，点了立刻重发请求；重试用尽 → 暂停 → 继续对战
- 请求卡死（断网无响应）时「停止」「重置」「重新开始」立即生效；单步总时长超时按网络问题重试
- 对战线程异常 / 线程丢失 → 暂停并可「继续对战」；刷新页面后能拿到完整局面

运行：uv run python tests/test_e2e_battle.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.environ["AICHESS_NETWORK_BACKOFF"] = "0.2,0.2,0.2"
os.environ["AICHESS_MOVE_DELAY"] = "0.05"
os.environ["AICHESS_API_TIMEOUT"] = "60"

MOCK_HOST, MOCK_PORT = "127.0.0.1", 8767
APP_HOST, APP_PORT = "127.0.0.1", 5005
MOCK = f"http://{MOCK_HOST}:{MOCK_PORT}"
APP_URL = f"http://{APP_HOST}:{APP_PORT}"

import socketio as sio_client  # noqa: E402
import mock_openai_server  # noqa: E402
import app as chess_app  # noqa: E402
import tempfile as _tempfile
chess_app.GAMES_DIR = _tempfile.mkdtemp(prefix="aichess-test-games-")  # 测试棋谱不写进项目 games/
from models.chess_game import ChessGame  # noqa: E402
from tests.test_rules import board_from  # noqa: E402


def http_json(url, payload=None, method=None, timeout=10):
    data, headers = None, {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = method or "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method or "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def wait_until(pred, timeout=20, step=0.05, desc="condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = pred()
            if last:
                return last
        except Exception as e:  # noqa
            last = e
        time.sleep(step)
    raise AssertionError(f"timeout waiting for {desc}: last={last!r}")


def mock(**kw):
    return http_json(f"{MOCK}/control", kw)


def mock_state(prompts=False):
    return http_json(f"{MOCK}/control" + ("?prompts=1" if prompts else ""))


def status():
    return http_json(f"{APP_URL}/api/get_battle_status")


def post(path, payload=None):
    return http_json(f"{APP_URL}{path}", payload or {})


def start(style="engine", initial_board=None, initial_player=None, red_key="k", black_key="k"):
    base = f"{MOCK}/style={style}/v1"
    payload = {
        "red_player": {"model_name": "deepseek-flash", "api_key": red_key, "base_url": base,
                       "display_name": "红·DeepSeek", "thinking_mode": "disabled"},
        "black_player": {"model_name": "kimi-k3.1-pro-highspeed", "api_key": black_key, "base_url": base,
                         "display_name": "黑·Kimi"},
    }
    if initial_board:
        payload["initial_board"] = initial_board
        payload["initial_player"] = initial_player or "red"
    r = post("/api/start_battle", payload)
    assert r["status"] == "success", r
    return r


class Page:
    """用 socket.io 客户端模拟网页，记录收到的事件。"""

    def __init__(self):
        self.events = []
        self.lock = threading.Lock()
        self.c = sio_client.Client(reconnection=True)

        @self.c.on("*")
        def any_event(event, data=None):
            with self.lock:
                self.events.append((time.time(), event, data))

        self.c.connect(APP_URL, transports=["polling"])

    def clear(self):
        with self.lock:
            self.events.clear()

    def of(self, name):
        with self.lock:
            return [d for _, n, d in self.events if n == name]

    def first_time(self, name, pred=lambda d: True):
        with self.lock:
            for t, n, d in self.events:
                if n == name and pred(d):
                    return t
        return None


def reset_mock():
    mock(mode="ok", fail_remaining=0, reset_counts=True, hang_seconds=30)


def stop_all():
    try:
        post("/api/stop_battle")
    except Exception:
        pass


# ----------------------------------------------------------------------

def test_play_to_checkmate(page):
    reset_mock()
    page.clear()
    os.environ.pop("AICHESS_MAX_MOVES", None)
    board = board_from({"e0": "k", "d0": "a", "i6": "p", "a5": "R", "i4": "R", "d9": "K", "e9": "A"})
    r = start("engine", initial_board=board, initial_player="red")
    path = r["record_path"]
    wait_until(lambda: page.of("game_over"), timeout=30, desc="game_over")
    over = page.of("game_over")[-1]
    assert over["reason"] == "checkmate", over
    assert over["winner_color"] == "red", over
    assert "将死" in over["message"], over
    st = status()
    assert st["status"] == "finished" and st["result"]["reason"] == "checkmate", st
    assert not st["can_resume"] and not st["loop_alive"]
    rec = json.load(open(path, encoding="utf-8"))
    assert rec["status"] == "finished", rec["status"]
    assert rec["result"]["reason"] == "checkmate" and rec["end_reason"] == "checkmate"
    assert rec["result"]["winner"] == "红·DeepSeek"
    # 棋谱里每一步都合法
    g = ChessGame()
    g.load_board_state(board, "red")
    for m in rec["moves"]:
        assert g.make_move(m["move"]), m
    assert g.get_game_status()["reason"] == "checkmate"
    assert rec["moves"][-1]["gives_check"] is True
    print(f"PASS checkmate: {len(rec['moves'])} 步 {[m['move'] for m in rec['moves']]} → {over['message']}")


def test_user_bug_position(page):
    reset_mock()
    page.clear()
    g = ChessGame()
    g.board[2][7] = '.'
    g.board[2][4] = 'c'
    g.board[6][4] = '.'
    start("default", initial_board=g.get_board_state(), initial_player="red")
    wait_until(lambda: page.of("move_made"), timeout=15, desc="first move")
    stop_all()
    mv = page.of("move_made")[0]
    assert mv["player_color"] == "red"
    assert mv["move"] in {"b7e7", "h7e7", "d9e8", "f9e8", "c9e7", "g9e7"}, mv
    prompt = mock_state(prompts=True)["prompts"][0]
    assert "你正被将军" in prompt and "必须应将" in prompt
    assert "共6个" in prompt, prompt
    print(f"PASS user-bug position: red answered check with {mv['move']}，提示词只给 6 个应将着法")


def test_move_limit_draw(page):
    reset_mock()
    page.clear()
    os.environ["AICHESS_MAX_MOVES"] = "8"
    try:
        r = start("engine")
        wait_until(lambda: page.of("game_over"), timeout=30, desc="game_over draw")
    finally:
        os.environ.pop("AICHESS_MAX_MOVES", None)
    over = page.of("game_over")[-1]
    assert over["reason"] == "move_limit" and over["winner_color"] is None, over
    rec = json.load(open(r["record_path"], encoding="utf-8"))
    assert rec["result"]["reason"] == "move_limit" and len(rec["moves"]) == 8
    print(f"PASS move limit: {over['message']}")


def test_retry_button_appears_immediately_and_retries_now(page):
    reset_mock()
    page.clear()
    os.environ["AICHESS_NETWORK_BACKOFF"] = "30,30,30"
    try:
        mock(mode="503", fail_remaining=1000)
        t0 = time.time()
        start("default")
        wait_until(lambda: page.of("network_retry"), timeout=10, desc="network_retry event")
        t_evt = page.first_time("network_retry")
        ev = page.of("network_retry")[0]
        assert ev["can_retry_now"] is True and ev["attempt"] == 1, ev
        st = status()
        assert st["phase"] == "network_retry" and st["can_retry_now"], st
        n_before = mock_state()["request_count"]
        t_click = time.time()
        r = post("/api/retry_now")
        assert r["action"] == "retry_now", r
        wait_until(lambda: mock_state()["request_count"] > n_before, timeout=3, desc="immediate re-request")
        resend = time.time() - t_click
        assert resend < 2.0, resend
        # 网络恢复后再点一次，马上走出棋
        mock(mode="ok", fail_remaining=0)
        post("/api/retry_now")
        wait_until(lambda: page.of("move_made"), timeout=5, desc="move after retry now")
    finally:
        os.environ["AICHESS_NETWORK_BACKOFF"] = "0.2,0.2,0.2"
        stop_all()
    print(f"PASS retry-now: 第1次重连事件 {t_evt - t0:.2f}s 内到达页面，按钮可用；点击后 {resend:.2f}s 重新请求（原本要等 30s）")


def test_retries_exhausted_then_resume(page):
    reset_mock()
    page.clear()
    mock(mode="always")
    start("default")
    wait_until(lambda: page.of("battle_paused"), timeout=15, desc="paused after retries")
    p = page.of("battle_paused")[-1]
    assert p["can_resume"] and p["kind"] == "network", p
    st = status()
    assert st["status"] == "paused" and st["can_resume"] and not st["loop_alive"], st
    mock(mode="ok")
    r = post("/api/resume_battle")
    assert r["action"] == "resumed", r
    wait_until(lambda: page.of("move_made"), timeout=10, desc="move after resume")
    stop_all()
    print("PASS retries exhausted → 暂停 → 继续对战 → 接着下")


def test_stop_and_reset_during_hang(page):
    reset_mock()
    page.clear()
    mock(mode="hang", hang_seconds=20, fail_remaining=1000)
    start("default")
    wait_until(lambda: mock_state()["request_count"] >= 1, timeout=5, desc="request in flight")
    time.sleep(0.3)
    t = time.time()
    r = post("/api/stop_battle")
    dt = time.time() - t
    assert r["status"] == "success" and dt < 1.0, dt
    st = status()
    assert st["status"] == "stopped", st
    battle = chess_app.current_battle
    wait_until(lambda: not chess_app.loop_alive(battle), timeout=2, desc="loop thread exit after stop")
    # 卡住时直接重新开局也立即生效
    mock(mode="ok", fail_remaining=0)
    t = time.time()
    start("default")
    wait_until(lambda: page.of("move_made"), timeout=10, desc="new game moves while old request hangs")
    dt2 = time.time() - t
    # 卡住时重置
    mock(mode="hang", fail_remaining=1000)
    wait_until(lambda: chess_app.current_battle.phase == "thinking", timeout=3, desc="waiting on hung request")
    time.sleep(0.5)
    t = time.time()
    r = post("/api/reset_battle")
    dt3 = time.time() - t
    assert r["status"] == "success" and dt3 < 1.0, dt3
    assert status()["status"] == "no_battle"
    mock(mode="ok", fail_remaining=0)
    print(f"PASS hang: 停止 {dt:.2f}s 生效；卡住时新开局 {dt2:.2f}s 走出第一步；重置 {dt3:.2f}s 生效")


def test_step_timeout_counts_as_network(page):
    reset_mock()
    page.clear()
    os.environ["AICHESS_STEP_TIMEOUT"] = "1.0"
    try:
        mock(mode="hang", hang_seconds=5, fail_remaining=1000)
        start("default")
        wait_until(lambda: page.of("network_retry"), timeout=5, desc="retry after step timeout")
        ev = page.of("network_retry")[0]
        assert "秒没有给出回复" in ev["detail"], ev
        mock(mode="ok", fail_remaining=0)
        wait_until(lambda: page.of("move_made"), timeout=10, desc="move after timeout retry")
    finally:
        os.environ.pop("AICHESS_STEP_TIMEOUT", None)
        stop_all()
    print("PASS step timeout → 网络重连（带立即重试按钮）→ 恢复后继续")


def test_thread_exception_pauses_and_resumes(page):
    reset_mock()
    page.clear()
    original = chess_app.play_one_turn
    calls = {"n": 0}

    def boom(battle):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("模拟内部错误")
        return original(battle)

    chess_app.play_one_turn = boom
    try:
        start("default")
        wait_until(lambda: page.of("battle_paused"), timeout=10, desc="paused after exception")
    finally:
        chess_app.play_one_turn = original
    p = page.of("battle_paused")[-1]
    assert p["kind"] == "error" and "模拟内部错误" in p["message"], p
    st = status()
    assert st["can_resume"], st
    moves_before = st["move_count"]
    post("/api/resume_battle")
    wait_until(lambda: status()["move_count"] > moves_before, timeout=10, desc="move after resume from exception")
    stop_all()
    print("PASS 线程异常 → 暂停（不静默死掉）→ 继续对战")


def test_stalled_thread_detected_and_refresh_restore(page):
    reset_mock()
    page.clear()
    start("default")
    wait_until(lambda: status()["move_count"] >= 3, timeout=15, desc="3 moves")
    battle = chess_app.current_battle
    # 模拟线程丢失：先停掉线程，再把状态改回 playing
    battle.status = "paused"
    wait_until(lambda: not chess_app.loop_alive(battle), timeout=3, desc="loop stopped")
    battle.status = "playing"
    st = status()
    assert st["stalled"] and st["can_resume"] and st["phase"] == "stalled", st
    # 「刷新页面」：新的 socket 连接 + get_battle_status 拿到完整局面
    page2 = Page()
    st2 = status()
    assert len(st2["moves"]) == st2["move_count"] >= 3
    g = ChessGame()
    for m in st2["moves"]:
        assert g.make_move(m["move"])
    assert g.get_board_state() == st2["board_state"]
    post("/api/resume_battle")
    n = st2["move_count"]
    wait_until(lambda: status()["move_count"] > n, timeout=10, desc="move after stalled resume")
    wait_until(lambda: page2.of("move_made"), timeout=5, desc="refreshed page receives events")
    page2.c.disconnect()
    stop_all()
    print("PASS 线程丢失被识别为可继续；刷新后的页面能恢复局面并继续收到走子")


def test_auth_error_pauses(page):
    reset_mock()
    page.clear()
    start("default", red_key="invalid")
    wait_until(lambda: page.of("battle_paused"), timeout=10, desc="paused on 401")
    p = page.of("battle_paused")[-1]
    assert p["kind"] == "api" and "401" in p["message"], p
    stop_all()
    print("PASS key 无效 → 暂停并提示原因（改好后可继续）")


def main():
    mock_server = ThreadingHTTPServer((MOCK_HOST, MOCK_PORT), mock_openai_server.Handler)
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    threading.Thread(target=lambda: chess_app.socketio.run(
        chess_app.app, host=APP_HOST, port=APP_PORT, allow_unsafe_werkzeug=True, use_reloader=False
    ), daemon=True).start()
    wait_until(lambda: http_json(f"{MOCK}/health"), desc="mock up")
    wait_until(lambda: urllib.request.urlopen(f"{APP_URL}/", timeout=1).status == 200, desc="app up")
    page = Page()
    failures = []
    for fn in [
        test_play_to_checkmate,
        test_user_bug_position,
        test_move_limit_draw,
        test_retry_button_appears_immediately_and_retries_now,
        test_retries_exhausted_then_resume,
        test_stop_and_reset_during_hang,
        test_step_timeout_counts_as_network,
        test_thread_exception_pauses_and_resumes,
        test_stalled_thread_detected_and_refresh_restore,
        test_auth_error_pauses,
    ]:
        try:
            fn(page)
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
            failures.append((fn.__name__, e))
            stop_all()
        time.sleep(0.3)
    page.c.disconnect()
    mock_server.shutdown()
    if failures:
        print("FAILED:", [f[0] for f in failures], flush=True)
        os._exit(1)
    print("ALL E2E TESTS PASSED", flush=True)
    sys.stderr.flush()
    os._exit(0)  # 不等后台卡住的模拟请求线程


if __name__ == "__main__":
    main()
