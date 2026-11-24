"""模型接口适配：校验、provider 参数、请求头/地址、兼容重试与错误脱敏。

支持：
- OpenAI Chat Completions 兼容接口（Bearer + /chat/completions）
- Anthropic 官方 Messages API（x-api-key + /messages）
- 自动把 max_tokens 切换为 max_completion_tokens
- 自动降级非流式，以及直接解析 JSON（非 SSE）响应
- 本机地址（localhost / 127.0.0.1 / ::1）允许不填 API key

暂不支持 Azure OpenAI 原生、AWS Bedrock / Vertex AI 云签名、纯 Responses API。
TLS 证书校验保持 requests 默认开启。
"""
import re
from urllib.parse import urlsplit, urlunsplit

PROVIDERS = {'deepseek', 'kimi', 'gemini', 'anthropic', 'custom'}
DEFAULT_URLS = {
    'deepseek': 'https://api.deepseek.com/v1',
    'kimi': 'https://api.moonshot.cn/v1',
    'gemini': 'https://generativelanguage.googleapis.com/v1beta/openai/',
    'anthropic': 'https://api.anthropic.com/v1',
}
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
ANTHROPIC_VERSION = '2023-06-01'
_SUFFIXES = ('/chat/completions', '/messages')


class ConfigError(ValueError):
    pass


def infer_provider(model, base=''):
    """仅兼容旧调用方；新 UI 必须明确传 provider，不根据模型名覆盖显式选择。"""
    name = str(model).lower()
    if 'deepseek' in name:
        return 'deepseek'
    if 'kimi' in name or 'moonshot' in name:
        return 'kimi'
    if 'gemini' in name:
        return 'gemini'
    if 'claude' in name or 'anthropic' in name:
        return 'anthropic'
    return 'custom'


def is_local_hostname(host):
    if not host:
        return False
    return host.strip('[]').lower() in LOCAL_HOSTS


def is_local_base_url(base):
    try:
        return is_local_hostname(urlsplit(str(base) or '').hostname)
    except ValueError:
        return False


def clean_text(text, key=''):
    text = str(text or '')
    if key:
        text = text.replace(key, '[已隐藏密钥]')
    text = re.sub(r'(?i)Bearer\s+[^\s"\'<>]+', 'Bearer [已隐藏密钥]', text)
    text = re.sub(r'(?i)x-api-key\s*[:=]\s*[^\s"\'<>]+', 'x-api-key: [已隐藏密钥]', text)
    text = re.sub(r'(?i)x-api-key\s+[^\s"\'<>]+', 'x-api-key [已隐藏密钥]', text)
    text = re.sub(r'\bsk-ant-[A-Za-z0-9_-]{8,}', '[已隐藏密钥]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[已隐藏密钥]', text)
    return text


def _number(value, name, lo, hi):
    if isinstance(value, bool):
        raise ConfigError(f'{name}必须是 {lo}–{hi} 之间的整数')
    try:
        n = int(str(value))
    except (ValueError, TypeError):
        raise ConfigError(f'{name}必须是 {lo}–{hi} 之间的整数')
    if not lo <= n <= hi:
        raise ConfigError(f'{name}必须是 {lo}–{hi} 之间的整数')
    return n


def normalize_base_url(base):
    """去掉用户多填的 /chat/completions 或 /messages 尾缀，返回规范根地址。"""
    url = urlsplit(base.strip())
    path = url.path.rstrip('/')
    for suffix in _SUFFIXES:
        if path.endswith(suffix):
            path = path[:-len(suffix)].rstrip('/')
            break
    return urlunsplit((url.scheme, url.netloc, path, '', ''))


def _validate_url_parts(base):
    if not isinstance(base, str) or len(base) > 1000 or re.search(r'[\s\\\x00-\x1f\x7f]', base):
        raise ConfigError('base_url 格式不正确，不得含空白、反斜线或控制字符')
    try:
        url = urlsplit(base)
        if url.scheme not in ('https', 'http') or not url.hostname or (not url.port and url.netloc.endswith(':')):
            raise ValueError()
        _ = url.port
        if url.username or url.password or url.query or url.fragment:
            raise ValueError()
    except ValueError:
        raise ConfigError('base_url 必须是完整 http(s) 地址，不得含账号、密码、查询参数或 #；请填 API 根地址（多填的 /chat/completions 或 /messages 会自动去掉）')


def validate_config(raw, require_key=True):
    if not isinstance(raw, dict):
        raise ConfigError('模型配置应为对象')
    model = raw.get('model_name', '')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}', model):
        raise ConfigError('model 名不能为空，只能含英文字母、数字和 . _ : / @ + -，最长 200 字符')
    provider = raw.get('provider') or infer_provider(model)
    if not isinstance(provider, str) or provider not in PROVIDERS:
        raise ConfigError('provider 必须是 DeepSeek、Kimi、Gemini、Anthropic Claude 或 OpenAI 兼容自定义')
    base = raw.get('base_url') or DEFAULT_URLS.get(provider, '')
    _validate_url_parts(base)
    base = normalize_base_url(base)
    if not urlsplit(base).hostname:
        raise ConfigError('base_url 必须是完整 http(s) 地址，不得含账号、密码、查询参数或 #')
    name = raw.get('display_name') or model
    if not isinstance(name, str) or not name.strip() or len(name) > 100 or re.search(r'[\x00-\x1f\x7f]', name):
        raise ConfigError('显示名称须为 1–100 字符，不能含控制字符')
    key = raw.get('api_key') or ''
    if not isinstance(key, str) or len(key) > 4096 or re.search(r'[^\x21-\x7e]', key):
        raise ConfigError('API key 格式不正确（仅支持可打印 ASCII，不能含空白或换行）')
    if require_key and not key and not is_local_base_url(base):
        raise ConfigError('请重新输入 API key；保存配置不会保存 key。本地模型（Ollama / LM Studio 等，地址为 localhost）可留空')
    thinking = raw.get('thinking_mode') or ('low' if provider == 'kimi' else 'disabled')
    allowed = ('disabled', 'low', 'high') if provider == 'deepseek' else (('low', 'high') if provider == 'kimi' else ('disabled',))
    if thinking not in allowed:
        raise ConfigError('此 provider 不支持该思考模式；自定义/Gemini/Anthropic 不发送思考参数，Kimi 仅支持低/高')
    default_max = 16384 if provider == 'kimi' else (4096 if provider == 'anthropic' or (provider == 'deepseek' and thinking != 'disabled') else 1024)
    default_timeout = 90 if provider in ('deepseek', 'kimi') else 180
    return {
        'provider': provider, 'display_name': name.strip(), 'base_url': base,
        'model_name': model, 'api_key': key, 'thinking_mode': thinking,
        'max_output': _number(raw.get('max_output', default_max), '最大输出 token', 64, 65536),
        'timeout': _number(raw.get('timeout', default_timeout), '读取超时（秒）', 2, 600),
    }


def request_headers(config):
    """构造请求头。本机空 key 时不发送 Authorization / x-api-key。"""
    headers = {'Content-Type': 'application/json'}
    key = config.get('api_key') or ''
    if not key:
        return headers
    if config.get('provider') == 'anthropic':
        headers['x-api-key'] = key
        headers['anthropic-version'] = ANTHROPIC_VERSION
    else:
        headers['Authorization'] = 'Bearer ' + key
    return headers


def endpoint_url(config):
    base = (config.get('base_url') or '').rstrip('/')
    if config.get('provider') == 'anthropic':
        return base if base.endswith('/messages') else base + '/messages'
    return base if base.endswith('/chat/completions') else base + '/chat/completions'


def _delta_text(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get('text') or item.get('content') or '')
        return ''.join(parts)
    return str(value)


def build_payload(config, messages, stream=True, testing=False):
    provider = config['provider']
    if provider == 'kimi':
        cap = 512
    elif provider == 'anthropic':
        cap = 128
    else:
        cap = 64
    maximum = min(config['max_output'], cap) if testing else config['max_output']
    if provider == 'anthropic':
        system_parts, chat = [], []
        for msg in messages or []:
            role, content = msg.get('role'), msg.get('content')
            if role == 'system':
                system_parts.append(content or '')
            else:
                chat.append({'role': role, 'content': content})
        data = {'model': config['model_name'], 'messages': chat, 'max_tokens': maximum, 'stream': stream}
        if system_parts:
            data['system'] = '\n\n'.join(system_parts)
        return data
    data = {'model': config['model_name'], 'messages': messages, 'stream': stream}
    if provider == 'deepseek':
        mode = 'disabled' if testing else config['thinking_mode']
        data.update(thinking={'type': 'disabled' if mode == 'disabled' else 'enabled'},
                    reasoning_effort='none' if mode == 'disabled' else mode, max_tokens=maximum)
    elif provider == 'kimi':
        data.update(reasoning_effort='low' if testing else config['thinking_mode'], max_completion_tokens=maximum)
    else:
        data['max_tokens'] = maximum
    return data


def player_kwargs(config):
    return {k: config[k] for k in ('model_name', 'api_key', 'base_url', 'display_name', 'provider', 'thinking_mode', 'max_output', 'timeout')}


def is_json_content_type(content_type):
    ct = (content_type or '').lower()
    return 'application/json' in ct and 'event-stream' not in ct


def needs_max_completion_tokens(status, error_text, provider=None):
    if provider == 'anthropic' or status != 400:
        return False
    text = (error_text or '').lower()
    if 'max_completion_tokens' in text:
        return True
    if 'max_tokens' in text and any(token in text for token in (
        'unsupported', 'not supported', 'not be used', 'is not allowed',
        'invalid', 'unknown parameter', 'unrecognized', '不支持',
    )):
        return True
    return False


def needs_disable_stream(status, error_text):
    if status not in (400, 422):
        return False
    text = (error_text or '').lower()
    mentions_stream = any(token in text for token in ('stream', 'streaming', 'sse', '流式'))
    hints = ('not support', 'unsupported', 'not supported', 'disabled', 'must be false',
             'cannot', 'can\'t', 'not enabled', 'not allowed', 'invalid', '不支持', '无法')
    return mentions_stream and any(token in text for token in hints)


def apply_max_completion_tokens(payload):
    data = dict(payload)
    value = data.pop('max_tokens', None)
    if value is not None:
        data['max_completion_tokens'] = value
    return data


def parse_chat_completion_json(data):
    if not isinstance(data, dict):
        raise ValueError('返回不兼容')
    if data.get('error'):
        raise ValueError('上游返回错误对象')
    choices = data.get('choices')
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError('返回不兼容')
    choice = choices[0]
    message = choice.get('message') or choice.get('delta') or {}
    if not isinstance(message, dict):
        raise ValueError('返回不兼容')
    content = _delta_text(message.get('content'))
    reasoning = _delta_text(message.get('reasoning_content') or message.get('reasoning') or message.get('thought'))
    return {
        'content': content,
        'reasoning': reasoning,
        'finish_reason': choice.get('finish_reason'),
        'raw_response': content,
    }


def parse_anthropic_message(data):
    if not isinstance(data, dict):
        raise ValueError('返回不兼容')
    if data.get('type') == 'error' or data.get('error') and data.get('type') != 'message':
        raise ValueError('上游返回错误对象')
    content, reasoning = '', ''
    blocks = data.get('content')
    if isinstance(blocks, str):
        content = blocks
    elif isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get('type')
            if btype == 'text':
                content += block.get('text') or ''
            elif btype in ('thinking', 'reasoning'):
                reasoning += block.get('thinking') or block.get('text') or block.get('reasoning') or ''
    return {
        'content': content,
        'reasoning': reasoning,
        'finish_reason': data.get('stop_reason'),
        'raw_response': content,
    }


def parse_anthropic_sse_event(data):
    """从 Anthropic SSE data 对象取出增量文本。(content_piece, reasoning_piece, stop_reason)"""
    if not isinstance(data, dict):
        return '', '', None
    event_type = data.get('type')
    if event_type == 'content_block_delta':
        delta = data.get('delta') or {}
        dtype = delta.get('type')
        if dtype == 'text_delta':
            return delta.get('text') or '', '', None
        if dtype == 'thinking_delta':
            return '', delta.get('thinking') or '', None
    if event_type == 'message_delta':
        return '', '', (data.get('delta') or {}).get('stop_reason')
    return '', '', None


def error_body_text(response, limit=65536):
    """读取错误响应正文（已安全截断）。成功响应请不要调用，以免提前消耗流。"""
    try:
        text = response.text
    except Exception:
        text = ''
    if len(text) > limit:
        text = text[:limit]
    return text


def run_compat_request(config, payload, timeout, connect_timeout=None, allow_redirects=False,
                       should_continue=None, register_response=None):
    """向当前 provider 发请求，必要时自动切换 max_completion_tokens 或关闭 stream。

    返回 (response, payload, status)，status 为 'ok' / 'http_error' / 'cancelled'。
    非 200 时已读取错误正文（可再用 response.text）；200 时未消费响应体。
    网络异常向上抛出，由调用方分类处理。
    """
    import requests
    url = endpoint_url(config)
    headers = request_headers(config)
    connect_timeout = connect_timeout if connect_timeout is not None else min(15.0, float(timeout))
    retried = set()
    last = None
    provider = config.get('provider')
    while True:
        if should_continue is not None and not should_continue():
            if last is not None:
                try:
                    last.close()
                except Exception:
                    pass
            return None, payload, 'cancelled'
        if last is not None:
            try:
                last.close()
            except Exception:
                pass
        response = requests.post(
            url, headers=headers, json=payload, stream=True,
            timeout=(connect_timeout, timeout), allow_redirects=allow_redirects,
        )
        last = response
        if register_response is not None:
            register_response(response)
        if should_continue is not None and not should_continue():
            try:
                response.close()
            except Exception:
                pass
            return None, payload, 'cancelled'
        if response.status_code == 200:
            return response, payload, 'ok'
        body = error_body_text(response)
        if 'max_tokens_switch' not in retried and payload.get('max_tokens') is not None and needs_max_completion_tokens(response.status_code, body, provider):
            payload = apply_max_completion_tokens(payload)
            retried.add('max_tokens_switch')
            continue
        if 'disable_stream' not in retried and payload.get('stream') and needs_disable_stream(response.status_code, body):
            payload = dict(payload)
            payload['stream'] = False
            retried.add('disable_stream')
            continue
        return response, payload, 'http_error'
