"""Bounded JSON calls for the local report worker and approved remote providers."""
import json
import os
import urllib.request
from urllib.parse import urlsplit

MAX_RESPONSE_BYTES = 8_000_000
MAX_DEEPSEEK_TOKENS = 131072


class ModelUnavailable(ValueError):
    """The configured provider cannot receive this kind of input."""


class ModelOutputError(ValueError):
    """A safe explanation of an incomplete provider response, without its contents."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _deepseek_options(settings, purpose):
    thinking = settings.get('thinking', {'type': 'disabled'})
    if (not isinstance(thinking, dict) or set(thinking) != {'type'}
            or thinking['type'] not in ('enabled', 'disabled')):
        raise ModelUnavailable('DeepSeek thinking 须配置为 enabled 或 disabled')
    max_tokens = settings.get('max_tokens', 16384 if purpose == 'progress' else 8192)
    if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_DEEPSEEK_TOKENS:
        raise ModelUnavailable('DeepSeek max_tokens 须为 1–131072 之间的整数')
    options = {'response_format': {'type': 'json_object'},
               'thinking': {'type': thinking['type']}, 'max_tokens': max_tokens}
    if 'reasoning_effort' in settings:
        effort = settings['reasoning_effort']
        if not isinstance(effort, str) or effort not in {'low', 'high', 'max'}:
            raise ModelUnavailable('DeepSeek reasoning_effort 须为 low、high 或 max')
        options['reasoning_effort'] = effort
    return options


def progress_settings(cfg):
    settings = dict(cfg['summary'])
    overrides = cfg.get('progress_digest', {})
    for key in ('api_base', 'model', 'thinking', 'reasoning_effort', 'max_tokens', 'timeout_seconds'):
        if key in overrides:
            settings[key] = overrides[key]
    return settings


def complete_json(settings, messages, *, purpose, image=False, record_usage=None):
    base = settings.get('api_base', '').rstrip('/')
    endpoint = urlsplit(base)
    local = endpoint.hostname in {'127.0.0.1', 'localhost', '::1'}
    if (not endpoint.hostname or endpoint.username is not None or endpoint.password is not None
            or endpoint.query or endpoint.fragment or '\\' in base or any(char.isspace() for char in base)
            or endpoint.scheme not in ({'http', 'https'} if local else {'https'})
            or not settings.get('model')):
        raise ModelUnavailable('请配置本机模型地址或 HTTPS 模型地址及模型名')
    if not local and (image or settings.get('allow_remote_' + purpose) is not True):
        raise ModelUnavailable('当前材料需在本机模型处理，或由维护人员整理')

    default_env = 'DEEPSEEK_API_KEY' if purpose == 'intake' else 'RESEARCH_MODEL_API_KEY'
    headers = {'Content-Type': 'application/json'}
    # A local model uses an Authorization header only when its token is explicitly configured.
    key_env = settings.get('api_key_env', '' if local else default_env)
    key = os.environ.get(key_env, '') if key_env else ''
    if key:
        headers['Authorization'] = 'Bearer ' + key
    elif not local:
        raise ModelUnavailable('请通过环境变量配置远程模型凭据')

    payload = {'model': settings['model'], 'messages': messages, 'stream': False}
    if endpoint.hostname == 'api.deepseek.com':
        payload.update(_deepseek_options(settings, purpose))
    request = urllib.request.Request(base + '/chat/completions', data=json.dumps(payload).encode(), headers=headers)
    # Loopback inference must stay local even when the process inherits proxy variables.
    handlers = [_NoRedirect()]
    if local:
        handlers.append(urllib.request.ProxyHandler({}))
    try:
        with urllib.request.build_opener(*handlers).open(request, timeout=settings['timeout_seconds']) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('模型响应超过大小限制')
        envelope = json.loads(raw)
        if record_usage is not None and isinstance(envelope.get('usage'), dict):
            usage = {key:envelope['usage'][key] for key in ('prompt_tokens','completion_tokens','total_tokens',
                     'prompt_cache_hit_tokens','prompt_cache_miss_tokens') if type(envelope['usage'].get(key)) is int}
            if usage:
                record_usage(usage)
        choice = envelope['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise ModelOutputError('模型输出达到长度上限，本轮未发布；请压缩摘要后重试')
        # Reasoning is transient provider data, never a report field or an error detail.
        content = choice['message']['content']
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            raise ModelOutputError('模型未返回完整 JSON，本轮未发布，请稍后重试') from None
    except ModelOutputError:
        raise
    except Exception as exc:
        # Do not emit request data, response bodies or credentials.
        raise ValueError(f'模型调用或 JSON 解析失败（{type(exc).__name__}）') from None
