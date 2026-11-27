import io
import json

import pytest

from research_weekly import model_api


@pytest.mark.parametrize('finish,content,error', [
    ('stop', '{"ok":true}', None),
    ('length', '{"unfinished":', '长度上限'),
    ('stop', '{"unfinished":', '完整 JSON'),
])
def test_progress_output_budget_and_incomplete_response(monkeypatch, finish, content, error):
    settings = {'api_base': 'https://api.deepseek.com', 'model': 'deepseek-flash',
                'api_key_env': 'TEST_PROGRESS_KEY', 'allow_remote_progress': True, 'timeout_seconds': 15}
    monkeypatch.setenv('TEST_PROGRESS_KEY', 'synthetic-key')
    class Opener:
        def open(self, request, timeout):
            payload = json.loads(request.data)
            assert payload['max_tokens'] == 16384
            assert payload['thinking'] == {'type': 'disabled'}
            return io.BytesIO(json.dumps({'choices': [{'finish_reason': finish,
                                                     'message': {'content': content}}]}).encode())
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *handlers: Opener())
    if error:
        with pytest.raises(model_api.ModelOutputError, match=error) as result:
            model_api.complete_json(settings, [], purpose='progress')
        assert 'synthetic-key' not in str(result.value)
        assert content not in str(result.value)
    else:
        assert model_api.complete_json(settings, [], purpose='progress') == {'ok': True}


def _settings(**options):
    return {'api_base': 'https://api.deepseek.com', 'model': 'deepseek-v4-pro',
            'api_key_env': 'TEST_PROGRESS_KEY', 'allow_remote_progress': True,
            'allow_remote_intake': True, 'allow_remote_summary': True,
            'timeout_seconds': 15, **options}


@pytest.mark.parametrize('purpose,budget', [('progress', 16384), ('summary', 8192), ('intake', 8192)])
def test_existing_purposes_keep_non_thinking_defaults(monkeypatch, purpose, budget):
    monkeypatch.setenv('TEST_PROGRESS_KEY', 'synthetic-key')
    class Opener:
        def open(self, request, timeout):
            payload = json.loads(request.data)
            assert payload['max_tokens'] == budget
            assert payload['thinking'] == {'type': 'disabled'}
            assert 'reasoning_effort' not in payload
            return io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *handlers: Opener())
    assert model_api.complete_json(_settings(), [], purpose=purpose) == {}


@pytest.mark.parametrize('effort', ['low', 'high', 'max'])
def test_deepseek_thinking_configuration_and_private_reasoning(monkeypatch, effort):
    monkeypatch.setenv('TEST_PROGRESS_KEY', 'synthetic-key')
    class Opener:
        def open(self, request, timeout):
            payload = json.loads(request.data)
            assert payload['model'] == 'deepseek-v4-pro'
            assert payload['thinking'] == {'type': 'enabled'}
            assert payload['reasoning_effort'] == effort
            assert payload['max_tokens'] == 65536
            assert payload['response_format'] == {'type': 'json_object'}
            return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
                'content': '{"headline":"已更新"}',
                'reasoning_content': 'private reasoning canary',
            }}]}).encode())
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *handlers: Opener())
    result = model_api.complete_json(_settings(thinking={'type': 'enabled'},
                                             reasoning_effort=effort, max_tokens=65536),
                                     [], purpose='progress')
    assert result == {'headline': '已更新'}
    assert 'private reasoning canary' not in json.dumps(result)


@pytest.mark.parametrize('options', [
    {'thinking': True}, {'thinking': {'type': 'automatic'}},
    {'thinking': {'type': 'enabled', 'unexpected': True}},
    {'max_tokens': 0}, {'max_tokens': 131073}, {'max_tokens': True},
    {'max_tokens': '65536'}, {'max_tokens': 8192.0},
    {'reasoning_effort': 'medium'}, {'reasoning_effort': ['max']},
])
def test_invalid_deepseek_configuration_does_not_send(monkeypatch, options):
    monkeypatch.setenv('TEST_PROGRESS_KEY', 'synthetic-key')
    def unexpected_request(*args):
        pytest.fail('Invalid model settings must be rejected before opening a connection')
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', unexpected_request)
    with pytest.raises(model_api.ModelUnavailable) as error:
        model_api.complete_json(_settings(**options), [], purpose='progress')
    assert 'synthetic-key' not in str(error.value)


def test_large_thinking_response_uses_bounded_read_and_returns_content_only(monkeypatch):
    monkeypatch.setenv('TEST_PROGRESS_KEY', 'synthetic-key')
    raw = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
        'content': '{"ok":true}', 'reasoning_content': 'x' * 2_100_000,
    }}]}).encode()
    class Response(io.BytesIO):
        def read(self, size=-1):
            assert size == model_api.MAX_RESPONSE_BYTES + 1
            return super().read(size)
    class Opener:
        def open(self, request, timeout):
            return Response(raw)
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *handlers: Opener())
    assert model_api.complete_json(_settings(thinking={'type': 'enabled'}, reasoning_effort='max',
                                             max_tokens=65536), [], purpose='progress') == {'ok': True}


def test_over_budget_response_and_reasoning_are_not_exposed(monkeypatch):
    monkeypatch.setenv('TEST_PROGRESS_KEY', 'synthetic-key')
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(b'private reasoning canary' + b'x' * model_api.MAX_RESPONSE_BYTES)
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *handlers: Opener())
    with pytest.raises(ValueError) as error:
        model_api.complete_json(_settings(), [], purpose='progress')
    assert 'private reasoning canary' not in str(error.value)
    assert 'synthetic-key' not in str(error.value)


def test_incomplete_response_does_not_expose_reasoning(monkeypatch):
    monkeypatch.setenv('TEST_PROGRESS_KEY', 'synthetic-key')
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(json.dumps({'choices': [{'finish_reason': 'length', 'message': {
                'content': '{"unfinished":', 'reasoning_content': 'private reasoning canary',
            }}]}).encode())
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *handlers: Opener())
    with pytest.raises(model_api.ModelOutputError, match='长度上限') as error:
        model_api.complete_json(_settings(thinking={'type': 'enabled'}, reasoning_effort='max',
                                         max_tokens=65536), [], purpose='progress')
    assert 'private reasoning canary' not in str(error.value)
