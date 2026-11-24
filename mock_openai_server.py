#!/usr/bin/env python3
"""模拟 OpenAI 兼容与 Anthropic Messages 接口，供本地复现走法解析、兼容重试与网络中断。"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

state_lock = threading.Lock()
state = {
    "fail_remaining": 0,
    "mode": "ok",  # ok / 429 / 502 / 503 / 504 / drop / reset / always
    "retry_after": "1",
    "request_count": 0,
    "failed_count": 0,
    "success_count": 0,
    "hang_seconds": 30,
}


def extract_gomoku_moves(prompt: str):
    """五子棋提示词里的合法落点。象棋提示词返回空列表。"""
    if not prompt or ("五子棋" not in prompt and "合法落点" not in prompt):
        return []
    section = prompt
    # 开头的「请从合法落点中选」不是列表；用最后一处「合法落点」标题后面的那一行。
    markers = list(re.finditer(r"合法落点[^\n]*\n", prompt))
    if markers:
        section = prompt[markers[-1].end():]
        stop = re.search(r"\n\n", section)
        if stop:
            section = section[:stop.start()]
    return re.findall(r"\b([A-O](?:1[0-5]|[1-9]))\b", section)


def gomoku_reply(prompt: str):
    moves = extract_gomoku_moves(prompt)
    if not moves:
        return None
    move = moves[0]
    reasoning = f"不要下中国象棋。棋步：h7e7 和 a0a1 都不是这里的走法。真正该落 {move}。"
    content = f"分析：占住空点\n策略：往一条线上连\n落子：{move}"
    return content, reasoning, move


def extract_legal_moves(prompt: str):
    if not prompt:
        return []
    moves = re.findall(r"\b[a-i][0-9][a-i][0-9]\b", prompt.lower())
    # 提示词里会带一个示例走法，真实列表也含这些坐标；取合法列表段更稳
    m = re.search(r"合法棋步[^\n]*\n([^\n]+)", prompt)
    if m:
        listed = re.findall(r"[a-i][0-9][a-i][0-9]", m.group(1).lower())
        if listed:
            return listed
    return moves


def sse_chunk(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def parse_prompt_position(prompt: str):
    """从提示词里的坐标棋盘还原局面和执子方（mock 引擎用）。"""
    rows = {}
    for line in (prompt or "").splitlines():
        m = re.match(r"^(\d) ((?:\S ){8}\S) \1$", line.strip())
        if m:
            rows[int(m.group(1))] = m.group(2).split(" ")
    if len(rows) != 10:
        return None, None
    board = "/".join("".join(rows[i]) for i in range(10))
    side = "black" if "执黑方" in prompt else "red"
    return board, side


def engine_pick(prompt: str, legal):
    """极简“引擎”：能将死就将死，能将军就将军，能吃子就吃子，否则走合法列表第一步。"""
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from models.chess_game import ChessGame
    board, side = parse_prompt_position(prompt)
    if not board or not legal:
        return legal[0] if legal else "a0a1"
    g = ChessGame()
    g.load_board_state(board, side)
    best, best_score = legal[0], -1
    for mv in legal:
        captured = g.board[int(mv[3])][ord(mv[2]) - 97]
        if not g.make_move(mv):
            continue
        replies = len(g.get_legal_moves())
        score = 0
        if replies == 0:
            score = 1000  # 将死或困毙
        elif g.is_in_check(g.current_player):
            score = 100 - min(replies, 40)  # 将军，且对方应法越少越好
        if captured != ".":
            score += 10 + (100 if captured.lower() == "r" else 0)
        g.undo_last_move()
        if score > best_score:
            best, best_score = mv, score
    return best


def build_stream(prompt: str, style: str):
    gomoku = gomoku_reply(prompt)
    if gomoku:
        content, reasoning, _move = gomoku
        chunks = []
        chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": None}, "finish_reason": None}]})
        for i in range(0, len(reasoning), 8):
            chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"reasoning_content": reasoning[i:i+8]}, "finish_reason": None}]})
        for i in range(0, len(content), 6):
            chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": content[i:i+6]}, "finish_reason": None}]})
        chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
        chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        return chunks
    legal = extract_legal_moves(prompt)
    move = legal[0] if legal else "a0a1"
    if style == "engine":
        move = engine_pick(prompt, legal)
    # 推理里故意放一个很容易被误解析的「棋步」和红方坐标
    reasoning = f"先看看红方的 h7e7，还有示例棋步：a9a8。这些都不要采用。真正该走 {move}。"
    if style == "markdown_upper":
        content = f"分析：试探中路\n策略：先升炮\n棋步：**{move.upper()}**"
    elif style == "hyphen":
        content = f"走 {move[:2]}-{move[2:]}"
    elif style == "spaces":
        content = f"棋步： {move[0]} {move[1]} {move[2]} {move[3]}"
    elif style == "none_content_then_text":
        content = f"棋步：{move}"
    else:
        content = f"分析：局面平稳\n策略：出动右炮\n棋步：{move}"

    chunks = []
    chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": None}, "finish_reason": None}]})
    # reasoning first, like Kimi K3
    for i in range(0, len(reasoning), 8):
        chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"reasoning_content": reasoning[i:i+8]}, "finish_reason": None}]})
    if style == "none_content_then_text":
        chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": None}, "finish_reason": None}]})
    for i in range(0, len(content), 6):
        chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": content[i:i+6]}, "finish_reason": None}]})
    # usage chunk with empty choices, as Kimi does
    chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
    chunks.append({"id": "mock-1", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    return chunks


def should_fail():
    with state_lock:
        mode = state["mode"]
        remaining = state["fail_remaining"]
        retry_after = state["retry_after"]
        if mode in ("ok", "", None):
            return False, mode, retry_after
        if mode != "always" and remaining <= 0:
            return False, mode, retry_after
        if remaining > 0:
            state["fail_remaining"] = remaining - 1
        state["failed_count"] += 1
        return True, mode, retry_after



def extract_prompt(payload):
    messages = payload.get("messages") or []
    prompt = ""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content") or ""
            if isinstance(content, list):
                prompt = "".join(
                    (part.get("text") or "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            else:
                prompt = content
    return prompt


def anthropic_message_body(prompt, style="default", testing=False):
    gomoku = gomoku_reply(prompt)
    if gomoku:
        content, reasoning, move = gomoku
        return reasoning, content, move
    legal = extract_legal_moves(prompt)
    move = legal[0] if legal else "a0a1"
    if style == "engine":
        move = engine_pick(prompt, legal)
    reasoning = f"先看看红方的 h7e7，还有示例棋步：a9a8。这些都不要采用。真正该走 {move}。"
    content = "OK" if (testing or "Reply OK." in (prompt or "")) and style == "default" and not legal else (
        f"分析：局面平稳\n策略：出动右炮\n棋步：{move}"
    )
    if legal or style != "default":
        if style == "markdown_upper":
            content = f"分析：试探中路\n策略：先升炮\n棋步：**{move.upper()}**"
        elif style == "hyphen":
            content = f"走 {move[:2]}-{move[2:]}"
        elif style == "spaces":
            content = f"棋步： {move[0]} {move[1]} {move[2]} {move[3]}"
        else:
            content = f"分析：局面平稳\n策略：出动右炮\n棋步：{move}"
    return reasoning, content, move


def write_anthropic_sse(handler, prompt, style):
    reasoning, content, _move = anthropic_message_body(prompt, style)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()

    def ev(event, data):
        handler.wfile.write(f"event: {event}\n".encode("utf-8"))
        handler.wfile.write(f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))

    ev("message_start", {"type": "message_start", "message": {"id": "msg_mock", "type": "message", "role": "assistant", "content": []}})
    ev("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}})
    for i in range(0, len(reasoning), 8):
        ev("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": reasoning[i:i+8]}})
    ev("content_block_stop", {"type": "content_block_stop", "index": 0})
    ev("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}})
    for i in range(0, len(content), 6):
        ev("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": content[i:i+6]}})
    ev("content_block_stop", {"type": "content_block_stop", "index": 1})
    ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
    ev("message_stop", {"type": "message_stop"})


def chat_json_body(prompt, style="default"):
    gomoku = gomoku_reply(prompt)
    if gomoku:
        content, reasoning, _move = gomoku
        return {
            "id": "mock-json",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content, "reasoning_content": reasoning},
                "finish_reason": "stop",
            }],
        }
    legal = extract_legal_moves(prompt)
    move = legal[0] if legal else "a0a1"
    if style == "engine":
        move = engine_pick(prompt, legal)
    if "Reply OK." in (prompt or "") and not legal:
        content, reasoning = "OK", ""
    else:
        content, reasoning = f"棋步：{move}", "思考一下"
    return {
        "id": "mock-json",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content, "reasoning_content": reasoning},
            "finish_reason": "stop",
        }],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[mock]", fmt % args)

    def _json(self, code, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/control") or self.path.startswith("/health"):
            with state_lock:
                snapshot = dict(state)
            if "prompts=1" not in self.path:
                snapshot.pop("prompts", None)
            self._json(200, snapshot)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}

        if self.path.startswith("/control"):
            with state_lock:
                for key in ("fail_remaining", "mode", "retry_after", "hang_seconds"):
                    if key in payload:
                        state[key] = payload[key]
                if payload.get("reset_counts"):
                    state["prompts"] = []
                    state["requests"] = []
                    state["request_count"] = 0
                    state["failed_count"] = 0
                    state["success_count"] = 0
                snapshot = dict(state)
            print(f"[mock] control updated: {snapshot}")
            self._json(200, snapshot)
            return

        if self.path.startswith('/echo-error/'):
            self._json(400, {'error': {'message': 'Do not expose ' + (self.headers.get('Authorization') or '')}})
            return

        if self.path.startswith('/echo-ant-error/'):
            self._json(400, {'error': {'message': 'Do not expose ' + (self.headers.get('x-api-key') or self.headers.get('X-Api-Key') or '')}})
            return

        if self.path.startswith("/error/"):
            code = int(self.path.split("/error/")[1].split("?")[0].split("/")[0] or "401")
            self._json(code, {
                "error": {"message": "Invalid Authentication", "type": "invalid_authentication_error"}
            })
            return

        auth = self.headers.get("Authorization") or ""
        if "invalid" in auth.lower() or auth.endswith("fail"):
            self._json(401, {
                "error": {"message": "Invalid Authentication", "type": "invalid_authentication_error"}
            })
            return

        with state_lock:
            state["request_count"] += 1
            meta = {k: v for k, v in payload.items() if k not in ('messages', 'api_key', 'system')}
            meta['has_authorization'] = bool(self.headers.get('Authorization'))
            meta['has_x_api_key'] = bool(self.headers.get('x-api-key') or self.headers.get('X-Api-Key'))
            meta['anthropic_version'] = self.headers.get('anthropic-version') or self.headers.get('Anthropic-Version')
            meta['path'] = self.path
            state.setdefault('requests', []).append(meta)
            del state['requests'][:-50]

        fail, mode, retry_after = should_fail()
        if fail:
            print(f"[mock] simulated failure mode={mode} remaining={state['fail_remaining']}")
            if mode in ("429", "502", "503", "504") or str(mode).isdigit():
                code = int(mode) if str(mode).isdigit() else int(mode)
                headers = {}
                if code == 429:
                    headers["Retry-After"] = str(retry_after)
                self._json(code, {
                    "error": {"message": f"simulated {code}", "type": "server_error"}
                }, extra_headers=headers)
                return
            if mode == "drop":
                # 写一半 SSE 后突然断开，触发 ChunkedEncoding / 流中断
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(b'data: {"id":"mock-1","choices":[{"delta":{"content":"partial')
                try:
                    self.wfile.flush()
                except Exception:
                    pass
                try:
                    self.connection.shutdown(2)
                except Exception:
                    pass
                try:
                    self.connection.close()
                except Exception:
                    pass
                return
            if mode == "hang":
                # 模拟断网时连接建立后一直没有数据（请求卡住）
                import time as _t
                end = _t.time() + float(state.get("hang_seconds") or 30)
                while _t.time() < end:
                    _t.sleep(0.1)
                try:
                    self.connection.close()
                except Exception:
                    pass
                return
            if mode in ("reset", "close"):
                try:
                    self.connection.close()
                except Exception:
                    pass
                return
            # 未知失败模式也返回 503
            self._json(503, {"error": {"message": f"simulated {mode}", "type": "server_error"}})
            return

        prompt = extract_prompt(payload)
        style = "default"
        m_style = re.search(r"style=([a-z_]+)", self.path)
        if m_style:
            style = m_style.group(1)
        is_anthropic = self.path.rstrip("/").endswith("/messages") or "/anthropic" in self.path

        # OpenAI 兼容：要求 max_completion_tokens
        if "/require-max-completion" in self.path:
            if "max_tokens" in payload and "max_completion_tokens" not in payload:
                self._json(400, {"error": {"message": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."}})
                return

        # 不支持 stream: true
        if "/no-stream" in self.path and payload.get("stream") is True:
            self._json(400, {"error": {"message": "stream is not supported for this endpoint"}})
            return

        with state_lock:
            state["success_count"] += 1
            prompts = state.setdefault("prompts", [])
            prompts.append(prompt)
            del prompts[:-20]

        # 始终返回普通 Chat Completions JSON（即便请求 stream=true）
        if "/json-completion" in self.path:
            self._json(200, chat_json_body(prompt, style))
            return

        if is_anthropic:
            reasoning, content, _move = anthropic_message_body(prompt, style, testing=payload.get("stream") is False)
            if payload.get("stream") is False or "/json-message" in self.path:
                self._json(200, {
                    "id": "msg_mock",
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": reasoning},
                        {"type": "text", "text": content},
                    ],
                    "stop_reason": "end_turn",
                })
                return
            write_anthropic_sse(self, prompt, style)
            return

        if payload.get("stream") is False:
            # 测试连接用短回复；对局非流式则返回可解析棋步
            if "Reply OK." in (prompt or "") and not extract_legal_moves(prompt):
                self._json(200, {"choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]})
            else:
                self._json(200, chat_json_body(prompt, style))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for chunk in build_stream(prompt, style):
            self.wfile.write(sse_chunk(chunk))
        self.wfile.write(b"data: [DONE]\n\n")


def main(host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"mock OpenAI-compatible server on http://{host}:{port}/v1/chat/completions")
    print(f"control: POST http://{host}:{port}/control  {{\"mode\":\"503\",\"fail_remaining\":2}}")
    server.serve_forever()


if __name__ == "__main__":
    main()
