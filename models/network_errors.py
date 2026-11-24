"""网络类 API 错误的判定与用户可见文案。

把 DNS / 连接 / 超时 / SSL / 流中断 / 502/503/504 / 429 与模型走错区分开。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlparse

import requests

NETWORK_HTTP_STATUS = {408, 429, 500, 502, 503, 504, 522, 523, 524}

# 默认退避：约 5+10+20+30+30+30+45 = 170 秒（约 2–3 分钟），不含单次请求本身的耗时。
DEFAULT_NETWORK_BACKOFF = [5, 10, 20, 30, 30, 30, 45]
MAX_RETRY_AFTER = 60

NETWORK_TEXT_MARKERS = (
    "nameresolutionerror",
    "failed to resolve",
    "nodename nor servname",
    "name or service not known",
    "temporary failure in name resolution",
    "getaddrinfo failed",
    "max retries exceeded",
    "connection aborted",
    "connection reset",
    "connection refused",
    "remotely closed",
    "remote end closed",
    "broken pipe",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "sslerror",
    "ssl cert",
    "certificate verify failed",
    "chunkedencodingerror",
    "incomplete read",
    "protocolerror",
    "connectionerror",
    "newconnectionerror",
    "httpsconnectionpool",
)

_NETWORK_EXC = [
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectTimeout,
    requests.exceptions.ReadTimeout,
    requests.exceptions.SSLError,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
]
try:
    import urllib3.exceptions as _u3
    _NETWORK_EXC.extend([
        _u3.ProtocolError,
        _u3.SSLError,
        _u3.NewConnectionError,
        getattr(_u3, "NameResolutionError", _u3.NewConnectionError),
        getattr(_u3, "ConnectTimeoutError", _u3.ProtocolError),
        getattr(_u3, "ReadTimeoutError", _u3.ProtocolError),
        getattr(_u3, "IncompleteRead", type("Unused", (), {})),
    ])
except Exception:
    pass

NETWORK_EXCEPTIONS = tuple(_NETWORK_EXC)


def network_backoff_schedule():
    """可通过环境变量 AICHESS_NETWORK_BACKOFF=0.2,0.2 缩短测试等待。"""
    raw = os.environ.get("AICHESS_NETWORK_BACKOFF", "").strip()
    if raw:
        delays = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            delays.append(float(part))
        if delays:
            return delays
    return list(DEFAULT_NETWORK_BACKOFF)


def parse_retry_after(header_value) -> Optional[float]:
    if header_value is None or header_value == "":
        return None
    text = str(header_value).strip()
    try:
        seconds = float(text)
        return min(max(seconds, 0.0), MAX_RETRY_AFTER)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        seconds = (dt - datetime.now(dt.tzinfo)).total_seconds()
        return min(max(seconds, 0.0), MAX_RETRY_AFTER)
    except Exception:
        return None


def extract_api_host(base_url: Optional[str] = None, error_text: str = "") -> str:
    host = ""
    if base_url:
        host = urlparse(base_url).hostname or ""
    text = error_text or ""
    if not host:
        m = re.search(r"host=['\"]([^'\"]+)['\"]", text)
        if m:
            host = m.group(1)
    if not host:
        m = re.search(r"Failed to resolve ['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
        if m:
            host = m.group(1)
    return host or "API 服务器"


def friendly_network_message(base_url: Optional[str] = None, error_text: str = "") -> str:
    host = extract_api_host(base_url, error_text)
    return f"连不上 {host}，请检查网络/代理（建议国内网站直连）"


def is_network_error(exc=None, status_code=None, error_text: str = "") -> bool:
    if status_code in NETWORK_HTTP_STATUS:
        return True
    if exc is not None and isinstance(exc, NETWORK_EXCEPTIONS):
        return True
    cause = getattr(exc, "__cause__", None) if exc is not None else None
    reason = getattr(exc, "reason", None) if exc is not None else None
    for inner in (cause, reason):
        if inner is not None and inner is not exc:
            if is_network_error(exc=inner, error_text=str(inner)):
                return True
    text = f"{error_text} {exc if exc is not None else ''}".lower()
    return any(marker in text for marker in NETWORK_TEXT_MARKERS)


def network_error_payload(base_url: Optional[str], error: str, *,
                          exc=None, status_code=None, retry_after=None,
                          raw_response: str = "") -> dict:
    user_message = friendly_network_message(base_url, error)
    return {
        "content": "",
        "reasoning": "",
        "error": user_message,
        "detail": error,
        "fatal": False,
        "error_type": "network",
        "retry_after": retry_after,
        "raw_response": raw_response,
    }
