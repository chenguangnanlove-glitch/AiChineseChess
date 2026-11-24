#!/usr/bin/env python3
"""验证网络错误不计入无效棋步、自动重试、暂停后点击继续，以及棋谱实时保存。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

# 测试用短退避，避免真的等 2–3 分钟
os.environ["AICHESS_NETWORK_BACKOFF"] = "0.15,0.15,0.15"
os.environ["AICHESS_MOVE_DELAY"] = "0.05"
os.environ["AICHESS_API_TIMEOUT"] = "3"

MOCK_HOST = "127.0.0.1"
MOCK_PORT = 8766
APP_HOST = "127.0.0.1"
APP_PORT = 5004
MOCK_URL = f"http://{MOCK_HOST}:{MOCK_PORT}/v1"
APP_URL = f"http://{APP_HOST}:{APP_PORT}"

# 必须在设置环境变量之后再导入 app
import mock_openai_server
import app as chess_app
import tempfile as _tempfile
chess_app.GAMES_DIR = _tempfile.mkdtemp(prefix="aichess-test-games-")  # 测试棋谱不写进项目 games/


def http_json(url, payload=None, method=None, timeout=8):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = method or "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def wait_http(url, timeout=15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status < 500:
                    return True
        except Exception as e:
            last = e
            time.sleep(0.1)
    raise RuntimeError(f"timeout waiting for {url}: {last}")


def wait_until(predicate, timeout=20, step=0.15, desc="condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            value = predicate()
            if value:
                return value
            last = value
        except Exception as e:
            last = e
        time.sleep(step)
    raise AssertionError(f"timeout waiting for {desc}: last={last!r}")


def mock_control(**kwargs):
    return http_json(f"http://{MOCK_HOST}:{MOCK_PORT}/control", kwargs)


def mock_state():
    return http_json(f"http://{MOCK_HOST}:{MOCK_PORT}/control", method="GET")


def battle_status():
    return http_json(f"{APP_URL}/api/get_battle_status", method="GET")


def start_battle(black_base=None):
    payload = {
        "red_player": {
            "model_name": "deepseek-flash",
            "api_key": "test-key",
            "base_url": MOCK_URL,
            "display_name": "DeepSeek V4 Flash",
            "thinking_mode": "disabled",
        },
        "black_player": {
            "model_name": "kimi-k3.1-pro-highspeed",
            "api_key": "test-key",
            "base_url": black_base or MOCK_URL,
            "display_name": "Kimi K3.1 Pro 高速版",
        },
    }
    return http_json(f"{APP_URL}/api/start_battle", payload)


def stop_battle():
    try:
        return http_json(f"{APP_URL}/api/stop_battle", {})
    except Exception:
        return None


def load_record(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_classify_dns_and_copy():
    from models.network_errors import is_network_error, friendly_network_message

    dns_text = (
        "API连接错误: HTTPSConnectionPool(host='api.moonshot.cn', port=443): "
        "Max retries exceeded with url: /v1/chat/completions "
        "(Caused by NameResolutionError(\"<urllib3.connection.HTTPSConnection object at 0x1>: "
        "Failed to resolve 'api.moonshot.cn' ([Errno 8] nodename nor servname provided, or not known)\"))"
    )
    assert is_network_error(error_text=dns_text), "DNS NameResolutionError should be network"
    assert is_network_error(status_code=502)
    assert is_network_error(status_code=503)
    assert is_network_error(status_code=504)
    assert is_network_error(status_code=500)
    assert is_network_error(status_code=429)
    assert is_network_error(error_text="ChunkedEncodingError: IncompleteRead")
    assert is_network_error(error_text="SSLError: certificate verify failed")
    assert is_network_error(error_text="Read timeout")
    msg = friendly_network_message("https://api.moonshot.cn/v1", dns_text)
    assert "api.moonshot.cn" in msg
    assert "请检查网络/代理" in msg
    assert "建议国内网站直连" in msg
    assert "棋步" not in msg
    assert "严格按照" not in msg
    print("PASS: classify DNS/network errors and user-facing copy")


def test_auto_retry_then_continue_playing():
    stop_battle()
    mock_control(mode="503", fail_remaining=2, reset_counts=True)
    result = start_battle()
    assert result.get("status") == "success", result
    record_path = result["record_path"]

    def ready():
        st = battle_status()
        return st.get("move_count", 0) >= 2 and st.get("status") == "playing"

    wait_until(ready, timeout=25, desc="auto-retry recovers and at least 2 moves")
    st = battle_status()
    rec = load_record(record_path)
    mock = mock_state()
    assert st["status"] == "playing"
    assert st["move_count"] >= 2
    assert len(rec["moves"]) >= 2
    assert rec["moves"][0]["move"]
    assert rec["red"]["model_name"] == "deepseek-flash"
    assert rec["black"]["model_name"] == "kimi-k3.1-pro-highspeed"
    assert mock["failed_count"] >= 2
    assert mock["success_count"] >= 2
    print(f"PASS: auto-retry (503 x2) then continued, moves={st['move_count']} record={record_path}")
    stop_battle()
    return record_path


def test_pause_and_resume_click():
    stop_battle()
    mock_control(mode="ok", fail_remaining=0, reset_counts=True)
    result = start_battle()
    assert result.get("status") == "success", result
    record_path = result["record_path"]

    wait_until(lambda: battle_status().get("move_count", 0) >= 2, timeout=20, desc="two moves before outage")
    mid = battle_status()
    mid_count = mid["move_count"]
    rec_mid = load_record(record_path)
    assert len(rec_mid["moves"]) >= 2

    # 中途断网，直到退避用尽（此时可能刚好又多走出一步，只要求已下棋谱保留）
    mock_control(mode="always", fail_remaining=0)
    wait_until(lambda: battle_status().get("status") == "paused", timeout=20, desc="battle pauses after retries exhausted")
    paused = battle_status()
    assert paused["status"] == "paused", paused
    assert paused["move_count"] >= mid_count
    rec_paused = load_record(record_path)
    assert rec_paused["status"] == "paused"
    assert len(rec_paused["moves"]) == paused["move_count"]
    assert rec_paused["moves"][:len(rec_mid["moves"])] == rec_mid["moves"]
    reason = rec_paused.get("pause_reason") or paused.get("pause_reason") or ""
    assert "严格按照" not in reason
    assert "棋步：" not in reason
    mid_count = paused["move_count"]

    # 网络恢复，点击继续
    mock_control(mode="ok", fail_remaining=0)
    resumed = http_json(f"{APP_URL}/api/resume_battle", {})
    assert resumed.get("status") == "success", resumed
    wait_until(
        lambda: battle_status().get("status") == "playing" and battle_status().get("move_count", 0) > mid_count,
        timeout=20,
        desc="resume continues from the same position",
    )
    after = battle_status()
    rec_after = load_record(record_path)
    assert after["move_count"] > mid_count
    assert rec_after["moves"][:mid_count] == rec_paused["moves"]
    assert rec_after["status"] in ("playing", "finished")
    print(f"PASS: pause then resume click, mid={mid_count} after={after['move_count']} record={record_path}")
    stop_battle()
    return record_path


def test_drop_stream_auto_retry():
    stop_battle()
    mock_control(mode="drop", fail_remaining=1, reset_counts=True)
    result = start_battle()
    assert result.get("status") == "success", result
    wait_until(lambda: battle_status().get("move_count", 0) >= 1, timeout=20, desc="recover after mid-stream drop")
    st = battle_status()
    assert st["status"] == "playing"
    assert st["move_count"] >= 1
    print(f"PASS: mid-stream drop auto-retry, moves={st['move_count']}")
    stop_battle()


def test_dns_fail_then_resume():
    """黑方指向无法解析的主机，模拟 Mac 上 NameResolutionError，暂停后改回 mock 再继续。"""
    stop_battle()
    mock_control(mode="ok", fail_remaining=0, reset_counts=True)
    bad_url = "http://api.moonshot.cn.invalid/v1"
    result = start_battle(black_base=bad_url)
    assert result.get("status") == "success", result
    record_path = result["record_path"]

    # 红方先走一步，随后黑方 DNS 失败并暂停
    wait_until(lambda: battle_status().get("move_count", 0) >= 1, timeout=20, desc="red moves before black DNS failure")
    wait_until(lambda: battle_status().get("status") == "paused", timeout=25, desc="pause after DNS failures")
    paused = battle_status()
    rec = load_record(record_path)
    assert paused["move_count"] >= 1
    assert rec["status"] == "paused"
    assert "严格按照" not in (rec.get("pause_reason") or "")
    reason = rec.get("pause_reason") or paused.get("pause_reason") or ""
    assert "api.moonshot.cn.invalid" in reason or "连不上" in reason

    # 恢复：把黑方改回 mock（相当于网络/DNS 恢复）
    if chess_app.current_battle is not None:
        chess_app.current_battle.black_player.base_url = MOCK_URL
    resumed = http_json(f"{APP_URL}/api/resume_battle", {})
    assert resumed.get("status") == "success", resumed
    wait_until(
        lambda: battle_status().get("move_count", 0) >= 2 and battle_status().get("status") == "playing",
        timeout=20,
        desc="resume after DNS recovery",
    )
    after = battle_status()
    rec_after = load_record(record_path)
    assert after["move_count"] >= 2
    assert rec_after["moves"][0]["move"]
    print(f"PASS: DNS failure pause then resume, moves={after['move_count']} reason={reason}")
    stop_battle()


def main():
    mock_server = ThreadingHTTPServer((MOCK_HOST, MOCK_PORT), mock_openai_server.Handler)
    mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    mock_thread.start()

    app_thread = threading.Thread(
        target=lambda: chess_app.socketio.run(
            chess_app.app,
            host=APP_HOST,
            port=APP_PORT,
            allow_unsafe_werkzeug=True,
            use_reloader=False,
        ),
        daemon=True,
    )
    app_thread.start()

    wait_http(f"http://{MOCK_HOST}:{MOCK_PORT}/health")
    wait_http(f"{APP_URL}/")

    failures = []
    for name, fn in [
        ("classify", test_classify_dns_and_copy),
        ("auto_retry", test_auto_retry_then_continue_playing),
        ("pause_resume", test_pause_and_resume_click),
        ("stream_drop", test_drop_stream_auto_retry),
        ("dns_resume", test_dns_fail_then_resume),
    ]:
        try:
            fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            failures.append((name, e))
            try:
                stop_battle()
            except Exception:
                pass

    mock_server.shutdown()
    if failures:
        print("FAILED:", failures)
        sys.exit(1)
    print("ALL NETWORK RESUME TESTS PASSED")


if __name__ == "__main__":
    main()
