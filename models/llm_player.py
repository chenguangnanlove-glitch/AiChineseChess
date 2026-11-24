import requests
import json
import time
import os
import re
import threading
from typing import Dict, Optional, List, Generator
from .api_config import (
    validate_config, build_payload, infer_provider, clean_text,
    request_headers, endpoint_url, run_compat_request, is_json_content_type,
    parse_chat_completion_json, parse_anthropic_message, parse_anthropic_sse_event,
)
from .network_errors import (
    is_network_error,
    friendly_network_message,
    parse_retry_after,
    network_error_payload,
    NETWORK_HTTP_STATUS,
)

class LLMPlayer:
    """大语言模型中国象棋玩家类"""
    
    def __init__(self, model_name: str, api_key: str, base_url: Optional[str] = None, display_name: str = "", socketio=None, thinking_mode: str = "disabled", provider=None, max_output=None, timeout=None):
        actual_provider = provider or infer_provider(model_name, base_url)
        if actual_provider == 'kimi' and thinking_mode == 'disabled' and provider is None:
            thinking_mode = 'low'  # 旧调用兼容
        raw = dict(model_name=model_name, api_key=api_key, base_url=base_url,
                   display_name=display_name, provider=actual_provider, thinking_mode=thinking_mode)
        if max_output is not None:
            raw['max_output'] = max_output
        if timeout is not None:
            raw['timeout'] = timeout
        self.api_config = validate_config(raw)
        self.provider = actual_provider
        self.timeout = self.api_config['timeout']
        self.max_output = self.api_config['max_output']
        base_url = self.api_config['base_url']
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.display_name = display_name or model_name
        self.kind = "ai"
        self.move_count = 0
        self.total_thinking_time = 0
        self.socketio = socketio
        # DeepSeek 官方参数：thinking.type = enabled/disabled，reasoning_effort = none/low/high/max
        self.thinking_mode = (thinking_mode or "disabled").strip().lower()
        # 可取消调用：对战循环在工作线程里调用 get_move，停止/立即重试时把令牌作废，
        # 旧请求的流式输出就不会再推到页面，并会尽快关闭连接。
        self._tls = threading.local()
        self._active_token = None
        self._active_response = None
        self._call_lock = threading.Lock()

    # ---- 可取消调用 ----
    def begin_call(self, token):
        """在工作线程里调用：登记本次调用的令牌。"""
        self._tls.token = token
        with self._call_lock:
            self._active_token = token

    def cancel_call(self, token=None):
        """作废当前（或指定）调用，并尽量关闭正在读取的 HTTP 流。"""
        with self._call_lock:
            if token is not None and self._active_token is not token:
                return
            self._active_token = None
            resp = self._active_response
            self._active_response = None
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def _call_active(self) -> bool:
        token = getattr(self._tls, "token", None)
        if token is None:
            return True  # 直接同步调用（测试/旧代码），永不取消
        return token is self._active_token

    def _emit(self, event, payload):
        if event == "thinking_stream" and getattr(self._tls, "suppress_stream", False):
            return
        allowed = getattr(self, "emit_allowed", None)
        if callable(allowed) and not allowed():
            return
        if self.socketio and self._call_active():
            if isinstance(payload, dict):
                payload = dict(payload)
                battle_id = getattr(self, "battle_id", None)
                if battle_id:
                    payload.setdefault("battle_id", battle_id)
            self.socketio.emit(event, payload)
    
    def get_move(self, board_state: str, move_history: List[dict], legal_moves: List[str] = None, retry_hint: str = None, strict_output: bool = False, in_check: bool = False, checkers: List[str] = None, player_color: str = None, rules=None, stream_thinking: bool = True, output_budget=None) -> Optional[Dict]:
        """获取模型的下一步棋（支持流式输出）
        
        Args:
            board_state: 当前棋盘状态
            move_history: 历史棋步列表
            legal_moves: 当前所有合法棋步列表
            retry_hint: 上次非法走法或解析失败时的错误说明，供重试时反馈给模型
            
        Returns:
            Dict: 包含棋步和思考过程的字典
        """
        start_time = time.time()
        self._tls.suppress_stream = not stream_thinking
        saved_budget = None
        if output_budget is not None:
            saved_budget = self.api_config.get('max_output')
            self.api_config['max_output'] = int(output_budget)
            self.max_output = int(output_budget)
        
        try:
            # 构建提示词。五子棋使用自己的棋盘说明和「落子」格式，不走象棋坐标。
            if rules is not None and hasattr(rules, "build_prompt"):
                prompt = rules.build_prompt(
                    board_state, move_history, legal_moves,
                    retry_hint=retry_hint, strict_output=strict_output,
                )
                system_prompt = rules.system_prompt() if hasattr(rules, "system_prompt") else None
            else:
                prompt = self.build_chess_prompt(board_state, move_history, legal_moves, retry_hint=retry_hint, strict_output=strict_output, in_check=in_check, checkers=checkers)
                system_prompt = None
            
            # 确定玩家颜色
            if not player_color:
                player_color = "red" if len(move_history) % 2 == 0 else "black"
            
            print(f"开始获取 {self.display_name} 的棋步...")
            
            # OpenAI 兼容与 Anthropic 原生都走统一请求入口（含自动兼容重试）。
            api_result = self._call_openai_compatible_stream(prompt, player_color, system_prompt=system_prompt)

            if isinstance(api_result, str):
                api_result = {'content': api_result, 'reasoning': ''}

            if api_result.get('error'):
                err = clean_text(api_result['error'], self.api_key)
                print(f"{self.display_name} API错误: {err}")
                if api_result.get('detail'):
                    print(f"{self.display_name} API错误详情: {clean_text(api_result.get('detail'), self.api_key)}")
                return {
                    'move': None,
                    'error': err,
                    'detail': clean_text(api_result.get('detail'), self.api_key) or err,
                    'fatal': api_result.get('fatal', False),
                    'error_type': api_result.get('error_type') or ('network' if is_network_error(error_text=err) else 'api'),
                    'retry_after': api_result.get('retry_after'),
                    'raw_response': clean_text(api_result.get('raw_response'), self.api_key),
                    'player': self.display_name,
                }

            content = clean_text(api_result.get('content'), self.api_key)
            reasoning = clean_text(api_result.get('reasoning'), self.api_key)
            print(f"API调用完成，content长度: {len(content)}，reasoning长度: {len(reasoning)}，finish_reason={api_result.get('finish_reason')}")
            finish_reason = api_result.get('finish_reason')
            if not content.strip():
                # 正文为空时不从 reasoning 里猜着法。length / max_tokens 是输出被截断，不是走法不合法。
                if finish_reason in ("length", "max_tokens"):
                    error_type = "truncated"
                    reason = "模型正文是空的，回答在写出最终着法前被输出上限截断（finish_reason=%s）" % finish_reason
                elif reasoning.strip():
                    error_type = "reasoning_only"
                    reason = "模型已结束，但正文是空的，只有思考内容"
                else:
                    error_type = "parse"
                    reason = "模型正文是空的"
                print(f"{self.display_name} {reason}")
                return {
                    'move': None,
                    'error': reason,
                    'error_type': error_type,
                    'finish_reason': finish_reason,
                    'thinking': reasoning,
                    'raw_response': content,
                    'player': self.display_name,
                }

            # 只根据最终 content 提取走法，不用推理过程里出现的坐标。
            # 五子棋只走自己的解析器，避免把象棋四字坐标套过来。
            if rules is not None and hasattr(rules, "parse_model_response"):
                move_info = rules.parse_model_response(content, legal_moves=legal_moves)
            else:
                move_info = self.parse_response(content, legal_moves=legal_moves)

            thinking_time = time.time() - start_time
            self.total_thinking_time += thinking_time
            self.move_count += 1

            if move_info:
                move_info['thinking_time'] = thinking_time
                move_info['player'] = self.display_name
                if reasoning:
                    move_info['thinking'] = (reasoning + "\n" + (move_info.get('thinking') or '')).strip()
                print(f"{self.display_name} 成功获取棋步: {move_info.get('move')}；是否在合法列表中: {move_info.get('in_legal_list')}")
                return move_info

            print(f"{self.display_name} 无法从content中解析出棋步。失败原因：未匹配到坐标格式或合法走法")
            # 正文被长度截断、里面还没有完整着法：同样按截断处理，仍不读 reasoning。
            if finish_reason in ("length", "max_tokens"):
                return {
                    'move': None,
                    'error': '回答被输出上限截断，正文里还没有完整着法（finish_reason=%s）' % finish_reason,
                    'error_type': 'truncated',
                    'finish_reason': finish_reason,
                    'thinking': reasoning,
                    'raw_response': content,
                    'player': self.display_name,
                }
            return {
                'move': None,
                'error': '模型有回复，但里面没有可识别的着法',
                'error_type': 'parse',
                'finish_reason': finish_reason,
                'thinking': reasoning,
                'raw_response': content,
                'player': self.display_name,
            }
            
        except Exception as e:
            print(f"获取{self.display_name}棋步时出错: {clean_text(e, self.api_key)}")
            import traceback
            if is_network_error(exc=e, error_text=clean_text(e, self.api_key)):
                payload = network_error_payload(self.base_url, f"获取棋步时网络错误: {clean_text(e, self.api_key)}", exc=e)
                payload["move"] = None
                payload["player"] = self.display_name
                return payload
            return {
                'move': None,
                'error': f'获取棋步时出错: {clean_text(e, self.api_key)}',
                'error_type': 'api',
                'fatal': False,
                'player': self.display_name,
            }
        finally:
            self._tls.suppress_stream = False
            if saved_budget is not None:
                self.api_config['max_output'] = saved_budget
                self.max_output = saved_budget
    
    def _live_config(self):
        """用实例上当前的 base_url / api_key（测试或恢复对局可能已改写）。"""
        cfg = dict(self.api_config)
        cfg['base_url'] = self.base_url
        cfg['api_key'] = self.api_key
        return cfg

    def _chat_completions_url(self) -> str:
        return endpoint_url(self._live_config())

    def call_deepseek_stream(self, prompt: str, player_color: str) -> str:
        """调用 DeepSeek 流式 API（官方 OpenAI 兼容接口）"""
        print(f"开始调用DeepSeek流式API，玩家颜色: {player_color}")
        return self._call_openai_compatible_stream(prompt, player_color)

    def call_kimi_stream(self, prompt: str, player_color: str) -> str:
        """调用 Kimi（Moonshot）流式 API（官方 OpenAI 兼容接口）"""
        print(f"开始调用Kimi流式API，玩家颜色: {player_color}")
        return self._call_openai_compatible_stream(prompt, player_color)

    def call_gemini_stream(self, prompt: str, player_color: str) -> str:
        """调用 Gemini 流式 API（Google OpenAI 兼容端点）"""
        print(f"开始调用Gemini流式API（OpenAI兼容接口），玩家颜色: {player_color}")
        system_prompt = "你是一位专业的中国象棋大师，擅长分析局面和制定策略。"
        return self._call_openai_compatible_stream(prompt, player_color, system_prompt=system_prompt)

    def _delta_text(self, value) -> str:
        """从流式 delta 字段取出文本；兼容 None、字符串、以及多模态 content 数组。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("text") or item.get("content") or "")
            return "".join(parts)
        return str(value)

    def _extract_api_error_message(self, status_code: int, body: str):
        body = clean_text(body, self.api_key)
        message = body.strip()
        try:
            data = json.loads(body)
            err = data.get("error", data)
            if isinstance(err, dict):
                message = err.get("message") or err.get("msg") or body.strip()
            elif isinstance(err, str):
                message = err
        except Exception:
            pass
        if len(message) > 500:
            message = message[:500] + "..."
        fatal = status_code in (400, 401, 402, 403, 404, 405, 422) or "authentication" in message.lower() or "invalid api key" in message.lower() or "余额" in message or "quota" in message.lower()
        return f"API {status_code}: {message}", fatal

    def _http_error_result(self, status_code: int, body: str, retry_after=None) -> dict:
        body = clean_text(body, self.api_key)
        message, fatal = self._extract_api_error_message(status_code, body)
        if status_code in NETWORK_HTTP_STATUS or is_network_error(status_code=status_code, error_text=message):
            return network_error_payload(
                self.base_url,
                message,
                status_code=status_code,
                retry_after=retry_after,
                raw_response=body,
            )
        error_type = "auth" if fatal else "api"
        return {
            "content": "",
            "reasoning": "",
            "error": message,
            "detail": message,
            "fatal": fatal,
            "error_type": "config" if status_code in (400, 404, 405, 422) else error_type,
            "retry_after": retry_after,
            "raw_response": body,
        }

    def _exception_error_result(self, prefix: str, exc: Exception) -> dict:
        text = clean_text(f"{prefix}: {exc}", self.api_key)
        if is_network_error(exc=exc, error_text=text):
            return network_error_payload(self.base_url, text, exc=exc)
        return {
            "content": "",
            "reasoning": "",
            "error": text,
            "detail": text,
            "fatal": False,
            "error_type": "api",
            "raw_response": "",
        }

    def _register_response(self, response):
        with self._call_lock:
            if self._call_active():
                self._active_response = response

    def _cancelled_result(self):
        return {"content": "", "reasoning": "", "error": "调用已取消", "error_type": "cancelled", "fatal": False}

    def _parse_success_response(self, response, player_color: str, streamed: bool) -> dict:
        """解析 200 响应：JSON（非流式或网关直接返回 JSON）或 SSE 流。"""
        content_type = response.headers.get("Content-Type") or ""
        if (not streamed) or is_json_content_type(content_type):
            try:
                data = response.json()
            except Exception as e:
                return self._exception_error_result("返回不是合法 JSON", e)
            try:
                if self.provider == "anthropic":
                    parsed = parse_anthropic_message(data)
                else:
                    parsed = parse_chat_completion_json(data)
            except ValueError as e:
                if "错误对象" in str(e):
                    body = clean_text(response.text if hasattr(response, "text") else str(data), self.api_key)
                    return self._http_error_result(response.status_code or 200, body)
                return {
                    "content": "", "reasoning": "", "error": "返回格式不兼容",
                    "detail": clean_text(str(e), self.api_key), "fatal": False, "error_type": "api",
                }
            content = clean_text(parsed.get("content"), self.api_key)
            reasoning = clean_text(parsed.get("reasoning"), self.api_key)
            if self.socketio and (content or reasoning):
                self._emit("thinking_stream", {
                    "player": player_color,
                    "content": clean_text((reasoning or "") + (content or ""), self.api_key),
                    "is_complete": False,
                })
            if self.socketio:
                self._emit("thinking_stream", {"player": player_color, "content": "", "is_complete": True})
            return {
                "content": content,
                "reasoning": reasoning,
                "finish_reason": parsed.get("finish_reason"),
                "raw_response": content,
            }
        if self.provider == "anthropic":
            return self._read_anthropic_sse(response, player_color)
        return self._read_openai_sse(response, player_color)

    def _emit_stream_buffer(self, player_color, buffer, piece, is_reasoning=False):
        # is_reasoning unused; buffer already contains displayed text
        buffer += piece
        key_len = len(self.api_key or "")
        if len(buffer) >= max(5, key_len * 2):
            buffer = buffer.replace(self.api_key, "[已隐藏密钥]") if self.api_key else buffer
            keep = max(0, key_len - 1)
            cut = len(buffer) - keep
            if cut > 0 and self.socketio:
                self._emit("thinking_stream", {"player": player_color, "content": buffer[:cut], "is_complete": False})
            buffer = buffer[cut:]
        return buffer

    def _finish_stream(self, player_color, full_content, full_reasoning, finish_reason, buffer, chunk_count):
        if buffer and self.socketio:
            self._emit("thinking_stream", {"player": player_color, "content": clean_text(buffer, self.api_key), "is_complete": False})
        print(f"流式响应完成，总块数: {chunk_count}, content长度: {len(full_content)}, reasoning长度: {len(full_reasoning)}, finish_reason={finish_reason}")
        if self.socketio:
            try:
                self._emit("thinking_stream", {"player": player_color, "content": "", "is_complete": True})
            except Exception as e:
                print(f"发送完成信号失败: {clean_text(e, self.api_key)}")
        return {
            "content": clean_text(full_content, self.api_key),
            "reasoning": clean_text(full_reasoning, self.api_key),
            "finish_reason": finish_reason,
            "raw_response": clean_text(full_content, self.api_key),
        }

    def _iter_sse_data(self, response):
        pending_json = ""
        for line in response.iter_lines():
            if not self._call_active():
                try:
                    response.close()
                except Exception:
                    pass
                yield None
                return
            if not line:
                continue
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue
            if line_str.startswith("event:") or line_str.startswith("id:") or line_str.startswith(":"):
                continue
            json_str = None
            if line_str.startswith("data:"):
                json_str = line_str[5:].lstrip()
            elif line_str.startswith("{"):
                json_str = line_str
            else:
                continue
            if json_str.strip() == "[DONE]":
                return
            try:
                chunk_data = json.loads(pending_json + json_str)
                pending_json = ""
            except json.JSONDecodeError:
                pending_json += json_str
                try:
                    chunk_data = json.loads(pending_json)
                    pending_json = ""
                except json.JSONDecodeError:
                    continue
            yield chunk_data

    def _read_openai_sse(self, response, player_color: str) -> dict:
        print("开始接收流式响应...")
        full_content = ""
        full_reasoning = ""
        chunk_count = 0
        buffer = ""
        finish_reason = None
        for chunk_data in self._iter_sse_data(response):
            if chunk_data is None:
                return self._cancelled_result()
            chunk_count += 1
            if chunk_data.get("error"):
                body = json.dumps(chunk_data, ensure_ascii=False)
                status = chunk_data.get("status") or 200
                result = self._http_error_result(status, body)
                result["content"] = clean_text(full_content, self.api_key)
                result["reasoning"] = clean_text(full_reasoning, self.api_key)
                result["finish_reason"] = finish_reason
                print(f"流式响应中包含error: {result.get('error')}")
                return result
            choices = chunk_data.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            if choice.get("finish_reason"):
                finish_reason = choice.get("finish_reason")
            delta = choice.get("delta") or {}
            if not delta and choice.get("message"):
                delta = choice.get("message") or {}
            piece = self._delta_text(delta.get("content"))
            if piece:
                full_content += piece
                buffer = self._emit_stream_buffer(player_color, buffer, piece)
            reasoning_piece = (
                self._delta_text(delta.get("reasoning_content"))
                or self._delta_text(delta.get("reasoning"))
                or self._delta_text(delta.get("thought"))
            )
            if reasoning_piece:
                full_reasoning += reasoning_piece
                buffer = self._emit_stream_buffer(player_color, buffer, reasoning_piece)
        return self._finish_stream(player_color, full_content, full_reasoning, finish_reason, buffer, chunk_count)

    def _read_anthropic_sse(self, response, player_color: str) -> dict:
        print("开始接收 Anthropic 流式响应...")
        full_content = ""
        full_reasoning = ""
        chunk_count = 0
        buffer = ""
        finish_reason = None
        for chunk_data in self._iter_sse_data(response):
            if chunk_data is None:
                return self._cancelled_result()
            chunk_count += 1
            if chunk_data.get("type") == "error" or chunk_data.get("error") and chunk_data.get("type") not in ("message", "message_start", "message_delta", "message_stop", "content_block_start", "content_block_delta", "content_block_stop"):
                body = json.dumps(chunk_data, ensure_ascii=False)
                result = self._http_error_result(chunk_data.get("status") or 200, body)
                result["content"] = clean_text(full_content, self.api_key)
                result["reasoning"] = clean_text(full_reasoning, self.api_key)
                result["finish_reason"] = finish_reason
                print(f"Anthropic 流式响应中包含error: {result.get('error')}")
                return result
            piece, reasoning_piece, stop = parse_anthropic_sse_event(chunk_data)
            if stop:
                finish_reason = stop
            if piece:
                full_content += piece
                buffer = self._emit_stream_buffer(player_color, buffer, piece)
            if reasoning_piece:
                full_reasoning += reasoning_piece
                buffer = self._emit_stream_buffer(player_color, buffer, reasoning_piece)
        return self._finish_stream(player_color, full_content, full_reasoning, finish_reason, buffer, chunk_count)

    def _call_openai_compatible_stream(self, prompt: str, player_color: str, system_prompt: str = None) -> dict:
        """调用当前 provider（OpenAI 兼容或 Anthropic 原生）。

        返回 dict: content / reasoning / error / fatal / finish_reason / raw_response。
        最终走法只应解析 content；reasoning / thinking 仅用于展示。
        自动兼容 max_completion_tokens、非流式 JSON 与 stream 降级。
        """
        try:
            url = endpoint_url(self._live_config())
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            data = build_payload(self.api_config, messages, stream=True)
            timeout = self.timeout

            env_timeout = os.environ.get("AICHESS_API_TIMEOUT", "").strip()
            if env_timeout:
                try:
                    timeout = float(env_timeout)
                except ValueError:
                    pass

            print(f"发送请求到: {url}")
            print(f"使用模型: {self.model_name}")
            print(
                "请求参数: "
                f"provider={self.provider}, "
                f"thinking={data.get('thinking')}, "
                f"reasoning_effort={data.get('reasoning_effort')}, "
                f"max_tokens={data.get('max_tokens')}, "
                f"max_completion_tokens={data.get('max_completion_tokens')}, "
                f"stream={data.get('stream')}, "
                f"timeout={timeout}"
            )

            response, data, status = run_compat_request(
                self._live_config(), data, timeout,
                should_continue=self._call_active,
                register_response=self._register_response,
            )
            if status == "cancelled":
                return self._cancelled_result()
            if status != "ok":
                body = clean_text(getattr(response, "text", "") if response is not None else "", self.api_key)
                code = getattr(response, "status_code", 0) or 0
                print(f"API请求失败，状态码: {code}")
                print(f"请求地址: {url}")
                print(f"模型名称: {self.model_name}")
                retry_after = parse_retry_after(response.headers.get("Retry-After") if response is not None else None)
                result = self._http_error_result(code, body, retry_after=retry_after)
                print(f"错误类型: {result.get('error_type')} 用户提示: {result.get('error')}")
                return result

            return self._parse_success_response(response, player_color, streamed=bool(data.get("stream", True)))

        except requests.exceptions.ReadTimeout as e:
            print(f"API读取超时: {clean_text(e, self.api_key)}")
            print(f"请求地址: {self._chat_completions_url()} 模型: {self.model_name}")
            return self._exception_error_result("API读取超时", e)
        except (requests.exceptions.SSLError, requests.exceptions.ChunkedEncodingError) as e:
            print(f"API传输中断: {clean_text(e, self.api_key)}")
            print(f"请求地址: {self._chat_completions_url()} 模型: {self.model_name}")
            return self._exception_error_result("API传输中断", e)
        except requests.exceptions.ConnectionError as e:
            print(f"API连接错误: {clean_text(e, self.api_key)}")
            print(f"请求地址: {self._chat_completions_url()} 模型: {self.model_name}")
            return self._exception_error_result("API连接错误", e)
        except requests.exceptions.RequestException as e:
            print(f"API请求异常: {clean_text(e, self.api_key)}")
            print(f"请求地址: {self._chat_completions_url()} 模型: {self.model_name}")
            return self._exception_error_result("API请求异常", e)
        except Exception as e:
            print(f"流式API调用失败: {clean_text(e, self.api_key)}")
            import traceback
            return self._exception_error_result("流式API调用失败", e)

    def format_board_display(self, board_state: str) -> str:
        """将棋盘状态转换为带坐标的显示。兼容换行或 FEN 风格的斜杠分隔。"""
        try:
            raw = (board_state or "").strip()
            if not raw:
                return board_state
            if "\n" in raw:
                lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
            elif "/" in raw:
                lines = raw.split("/")
            else:
                return board_state

            # 去掉可能的空格后再检查每行是否为 9 个格子
            cleaned = [ln.replace(" ", "") for ln in lines]
            if len(cleaned) != 10 or any(len(ln) != 9 for ln in cleaned):
                return board_state

            display = "  a b c d e f g h i\n"
            for i, line in enumerate(cleaned):
                display += f"{i} " + " ".join(line) + f" {i}\n"
            display += "  a b c d e f g h i"
            return display
        except Exception as e:
            print(f"格式化棋盘显示时出错: {clean_text(e, self.api_key)}")
            return board_state

    def build_chess_prompt(self, board_state: str, move_history: List[dict], legal_moves: List[str] = None, retry_hint: str = None, strict_output: bool = False, in_check: bool = False, checkers: List[str] = None) -> str:
        """构建精简的中国象棋提示词：保留带坐标的棋盘和全部合法走法。"""
        history_parts = []
        if move_history:
            for move in move_history[-10:]:
                notation = move.get('notation', move.get('move', ''))
                player = "红" if move.get('player') == 'red' else "黑"
                coord = move.get('move', '')
                history_parts.append(f"{player}:{coord or notation}")
        history_str = " ".join(history_parts) if history_parts else "开局"

        current_turn = "红方" if len(move_history) % 2 == 0 else "黑方"
        board_display = self.format_board_display(board_state)
        legal_list = list(legal_moves or [])
        legal_moves_str = ", ".join(legal_list) if legal_list else "（无）"
        example = legal_list[0] if legal_list else "a0a1"
        check_line = ""
        if in_check:
            src = f"（将军来自 {', '.join(checkers)}）" if checkers else ""
            check_line = f"⚠️ 你正被将军{src}，必须应将（走开将/帅、垫子挡住或吃掉将军的子）。下面列表里只剩能解将的着法。\n"

        prompt = f"""你正在下中国象棋，执{current_turn}，已走{len(move_history)}步。请从合法棋步中选一步。

棋盘：列a-i（左到右），行0-9（上到下）。大写是红方，小写是黑方。K/k帅将 A/a仕士 B/b相象 N/n马 R/r车 C/c炮 P/p兵卒，.为空。
{board_display}
最近棋步：{history_str}

{check_line}合法棋步（必须从中选一个，共{len(legal_list)}个；已排除走完后己方仍被将军或将帅照面的着法）：
{legal_moves_str}

按下面三行回复，分析与策略各用一句话即可。棋步必须是上面列表中的一项，使用小写字母，例如 {example}：
分析：...
策略：...
棋步：{example}
"""
        if retry_hint:
            prompt += f"\n上次错误：{retry_hint}\n请改选另一个合法棋步，棋步必须是上面列表中的一项。\n"
        if strict_output:
            prompt += f"\n这是最后一次机会。请只输出一行：\n棋步：{example}\n不要输出其他内容，xxxx 必须替换为合法列表中的一步。\n"
        return prompt

    def _normalize_move_text(self, text: str) -> str:
        """把全角字母、数字、冒号转成半角，便于提取走法。"""
        if not text:
            return ""
        trans = {}
        for i in range(26):
            trans[ord("Ａ") + i] = ord("a") + i
            trans[ord("ａ") + i] = ord("a") + i
        for i in range(10):
            trans[ord("０") + i] = ord("0") + i
        trans[ord("：")] = ord(":")
        trans[ord("．")] = ord(".")
        return text.translate(trans)

    def parse_response(self, response: str, legal_moves: List[str] = None) -> Optional[Dict]:
        """从模型最终正文中提取棋步；优先匹配合法走法列表。"""
        if not response:
            return None

        try:
            text = self._normalize_move_text(response)
            print(f"开始解析响应，响应长度: {len(text)}")

            analysis_match = re.search(r'分析[:：]\s*(.+?)(?=策略|棋步|$)', text, re.DOTALL | re.IGNORECASE)
            analysis = analysis_match.group(1).strip() if analysis_match else ""
            strategy_match = re.search(r'策略[:：]\s*(.+?)(?=棋步|$)', text, re.DOTALL | re.IGNORECASE)
            strategy = strategy_match.group(1).strip() if strategy_match else ""

            legal_set = {m.lower() for m in (legal_moves or []) if m}

            def assemble(a, b, c, d):
                return f"{a}{b}{c}{d}".lower()

            labeled = []
            # 棋步：后允许出现 markdown/引号/括号
            for m in re.finditer(r'棋步\s*[:：]\s*[\*`\[\(\s"“”]*([a-i])\s*([0-9])\s*[-–—到至]?\s*([a-i])\s*([0-9])', text, re.IGNORECASE):
                labeled.append(assemble(m.group(1), m.group(2), m.group(3), m.group(4)))

            all_moves = []
            for m in re.finditer(r'([a-i])\s*([0-9])\s*[-–—到至]?\s*([a-i])\s*([0-9])', text, re.IGNORECASE):
                all_moves.append(assemble(m.group(1), m.group(2), m.group(3), m.group(4)))

            move = None
            source = None
            if legal_set:
                legal_labeled = [x for x in labeled if x in legal_set]
                legal_all = [x for x in all_moves if x in legal_set]
                if legal_labeled:
                    move = legal_labeled[-1]
                    source = "棋步标签+合法列表"
                elif legal_all:
                    move = legal_all[-1]
                    source = "正文中最后一个合法坐标"
            if not move and labeled:
                move = labeled[-1]
                source = "棋步标签（未必合法）"
            if not move and all_moves:
                move = all_moves[-1]
                source = "正文中的坐标（未必合法）"

            if move:
                in_legal = (move in legal_set) if legal_set else None
                print(f"解析到棋步: {move}（来源: {source}，在合法列表中: {in_legal}）")
                return {
                    'move': move,
                    'analysis': analysis,
                    'strategy': strategy,
                    'thinking': f"分析: {analysis}\n策略: {strategy}",
                    'raw_response': response,
                    'in_legal_list': in_legal,
                }

            print("无法从响应中提取有效棋步")
            return None

        except Exception as e:
            print(f"解析响应时出错: {clean_text(e, self.api_key)}")
            import traceback
            return None

    def get_stats(self) -> Dict:
        """获取玩家统计信息"""
        avg_thinking_time = self.total_thinking_time / self.move_count if self.move_count > 0 else 0
        return {
            'display_name': self.display_name,
            'model_name': self.model_name,
            'move_count': self.move_count,
            'total_thinking_time': self.total_thinking_time,
            'avg_thinking_time': avg_thinking_time
        }
