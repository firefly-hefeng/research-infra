"""Local provider settings and bounded Agent / Chat Completions adapters."""
import json
import os
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

FIELDS = ('mode', 'api_base_url', 'api_model', 'api_key', 'api_json_mode',
          'api_timeout', 'agent_timeout')


def validate_settings(values):
    if values['mode'] not in ('auto', 'agent', 'api'):
        raise ValueError('整理方式必须为 auto、agent 或 api')
    for field, limit in (('api_base_url', 2000), ('api_model', 200), ('api_key', 4096)):
        value = values[field]
        if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError('设置字段不符合要求: ' + field)
        values[field] = value.strip()
    values['api_base_url'] = values['api_base_url'].rstrip('/')
    if values['api_base_url']:
        url = urlsplit(values['api_base_url'])
        try:
            port = url.port
        except ValueError:
            raise ValueError('API 地址端口无效') from None
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment or ' ' in values['api_base_url']):
            raise ValueError('API 地址必须为 http(s) Base URL，不能包含密钥、查询参数或片段')
        if url.path.endswith('/chat/completions'):
            raise ValueError('请填写 Base URL（如 https://api.example.com/v1），无需 /chat/completions')
    if type(values['api_json_mode']) is not bool:
        raise ValueError('JSON 模式必须为布尔值')
    for field in ('api_timeout', 'agent_timeout'):
        if type(values[field]) is not int or not 1 <= values[field] <= 600:
            raise ValueError('超时应为 1–600 秒的整数')
    return values


def load_settings(library=None):
    values = {
        'mode': os.environ.get('PAPER_PROVIDER_MODE', 'auto'),
        'api_base_url': os.environ.get('PAPER_API_BASE_URL', ''),
        'api_model': os.environ.get('PAPER_API_MODEL', ''),
        'api_key': os.environ.get('PAPER_API_KEY', ''),
        'api_json_mode': os.environ.get('PAPER_API_JSON_MODE', '1') == '1',
        'api_timeout': int(os.environ.get('PAPER_API_TIMEOUT', '120')),
        'agent_timeout': int(os.environ.get('PAPER_AGENT_TIMEOUT', '600')),
    }
    if library:
        path = library.safe('.paperlib/providers.json')
        if path.exists():
            saved = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(saved, dict) or set(saved) - set(FIELDS):
                raise ValueError('整理配置文件格式错误')
            values.update(saved)
    return validate_settings(values)


def save_settings(library, payload):
    if set(payload) - set(FIELDS) - {'clear_api_key'}:
        raise ValueError('包含不支持的设置字段')
    if type(payload.get('clear_api_key', False)) is not bool:
        raise ValueError('clear_api_key 必须为布尔值')
    with library.lock('providers'):
        values = load_settings(library)
        for field in FIELDS:
            if field in payload and (field != 'api_key' or payload[field] != ''):
                values[field] = payload[field]
        if payload.get('clear_api_key'):
            values['api_key'] = ''
        validate_settings(values)
        path = library.safe('.paperlib/providers.json')
        fd, name = tempfile.mkstemp(prefix='providers-', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(values, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def public_settings(config):
    result = {k: config[k] for k in FIELDS if k != 'api_key'}
    result.update({k: config[k] for k in ('configured', 'agent_configured', 'api_configured',
                                         'agent_error', 'enabled', 'time', 'timezone')})
    result['api_key_set'] = bool(config['api_key'])
    return result


def parse_card(raw):
    if not isinstance(raw, str) or len(raw) > 128000:
        raise ValueError('输出为空或超出卡片长度限制')
    try:
        card = json.loads(raw)
    except (ValueError, RecursionError):
        raise ValueError('未返回有效的单个 JSON 卡片') from None
    if not isinstance(card, dict):
        raise ValueError('卡片必须是 JSON 对象')
    return card


def agent_card(config, prompt, project):
    if not config['command']:
        raise RuntimeError(config['agent_error'] or 'Agent 未配置')
    # Files bound memory usage; no raw stdout/stderr enters user-visible errors.
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8') as output, tempfile.TemporaryFile() as errors:
        try:
            proc = subprocess.run(config['command'], input=json.dumps(prompt, ensure_ascii=False),
                                  text=True, stdout=output, stderr=errors,
                                  timeout=config['agent_timeout'], cwd=project)
        except subprocess.TimeoutExpired:
            raise RuntimeError('Agent 调用超时') from None
        except OSError:
            raise RuntimeError('Agent 无法启动，请检查服务器命令及权限') from None
        if proc.returncode:
            raise RuntimeError('Agent 退出码 ' + str(proc.returncode))
        output.seek(0)
        return parse_card(output.read(128001))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_card(config, prompt):
    if not config['api_configured']:
        raise ValueError('API 尚未配置 Base URL 和模型')
    instructions = '\n\n'.join(prompt.get(k, '') for k in ('task', 'skill', 'contract'))
    data = {k: v for k, v in prompt.items() if k not in ('task', 'skill', 'contract')}
    payload = {'model': config['api_model'], 'stream': False, 'messages': [
        {'role': 'system', 'content': instructions},
        {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]}
    if config['api_json_mode']:
        payload['response_format'] = {'type': 'json_object'}
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if config['api_key']:
        headers['Authorization'] = 'Bearer ' + config['api_key']
    request = Request(config['api_base_url'] + '/chat/completions',
                      data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method='POST')
    # Direct connection supports local model servers; never forward keys via redirects.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=config['api_timeout']) as response:
            raw = response.read(2_000_001)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        raise RuntimeError(f'API HTTP {code}；请检查地址、密钥、模型及服务额度') from None
    except (URLError, OSError, ValueError):
        raise RuntimeError('API 连接失败或超时，请检查服务器网络和 API 地址') from None
    if len(raw) > 2_000_000:
        raise ValueError('API 响应超过大小限制')
    try:
        response = json.loads(raw)
        choice = response['choices'][0]
        if choice.get('finish_reason') not in ('stop', None):
            raise ValueError()
        content = choice['message']['content']
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise ValueError('API 返回格式无效，或生成被截断 / 拒绝') from None
    return parse_card(content)
