import io
import json
import zipfile

import pytest

from research_weekly import core, intake, model_api, summaries
from test_system import FIELDS, HEADERS, env, file_upload, seed


def test_any_format_original_status_idempotence_and_pending(env):
    cfg, app, _ = env
    client = app.test_client()
    response = file_upload(client, b'\x00\x01PRIVATE', filename='weekly.custom')
    assert response.status_code == 201
    assert response.json['summary_status'] == 'queued'
    original = cfg['roots']['members']/'alice/uploads/2026-W42.original.custom'
    assert original.read_bytes() == b'\x00\x01PRIVATE'
    assert 'uploads' not in json.dumps(response.json)
    status = client.get('/api/upload-status?member_id=alice&week=2026-W42')
    assert status.status_code == 200 and status.json['status'] == 'queued'
    assert file_upload(client, b'\x00\x01PRIVATE', filename='weekly.custom').status_code == 200
    assert file_upload(client, b'different', filename='weekly.custom').status_code == 409
    manifest = summaries.collect(cfg, '2026-W42')
    assert len(manifest['pending']) == 1 and len(manifest['missing']) == 2
    doc, _ = summaries.summarize(cfg, '2026-W42', 'extractive')
    assert (doc['submitted'], doc['received'], doc['expected']) == (0, 1, 3)
    assert len(doc['pending']) == 1


def test_valid_markdown_is_ready_without_model(env):
    cfg, app, _ = env
    text = core.report_markdown('甲同学', '2026-W42', FIELDS)
    response = file_upload(app.test_client(), text)
    assert response.status_code == 201 and response.json['summary_status'] == 'ready'
    assert core.read_text(cfg['roots']['members']/'alice/reports/2026-W42.md') == text
    assert (cfg['roots']['members']/'alice/uploads/2026-W42.original.md').read_bytes() == text.encode()


def make_docx(text):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="urn:test"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def test_office_agent_normalization_and_summary_trigger(env, monkeypatch):
    cfg, app, _ = env
    response = file_upload(app.test_client(), make_docx('完成数据核验，指标见附录'), filename='weekly.docx')
    assert response.status_code == 201 and response.json['summary_status'] == 'queued'
    document = intake.extract_document('weekly.docx', '.docx', make_docx('完成数据核验，指标见附录'))
    assert document['content'] == '完成数据核验，指标见附录'
    monkeypatch.setattr(intake, 'agent_fields', lambda *args: FIELDS)
    result = intake.process_pending(cfg)
    assert result['ready'] == 1 and result['summarized'] == 1
    assert core.read_text(cfg['roots']['members']/'alice/reports/2026-W42.md') == core.report_markdown('甲同学', '2026-W42', FIELDS)
    assert intake.load_status(cfg, 'alice', '2026-W42')['status'] == 'ready'
    assert app.test_client().get('/api/upload-status?member_id=alice&week=2026-W42').json['status_detail'] == '已进入团队周报'


def test_pdf_extraction(env, monkeypatch):
    class Page:
        def extract_text(self):
            return 'PDF 中的研究记录'
    class Reader:
        pages = [Page()]
    monkeypatch.setattr('pypdf.PdfReader', lambda stream: Reader())
    document = intake.extract_document('weekly.pdf', '.pdf', b'%PDF-test')
    assert document == {'kind': 'text', 'content': 'PDF 中的研究记录'}


def test_image_uses_local_multimodal_json(env, monkeypatch):
    cfg, _, _ = env
    cfg['summary'].update(api_base='http://127.0.0.1:8000/v1', model='local-vision')
    captured = {}
    raw = json.dumps({'choices': [{'message': {'content': json.dumps(FIELDS)}}]}).encode()
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return raw
    class Opener:
        def open(self, request, timeout):
            captured.update(json.loads(request.data), timeout=timeout)
            assert request.get_header('Authorization') is None
            assert request.full_url == 'http://127.0.0.1:8000/v1/chat/completions'
            return Response()
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *handlers: Opener())
    document = intake.extract_document('weekly.png', '.png', b'not-a-real-image-but-base64-is-safe')
    assert intake.agent_fields(cfg, {'name': '甲同学'}, '2026-W42', document) == FIELDS
    assert captured['model'] == 'local-vision'
    content = captured['messages'][0]['content']
    assert content[1]['type'] == 'image_url' and content[1]['image_url']['url'].startswith('data:image/png;base64,')


def test_remote_policy_blocks_disallowed_input_before_network(env, monkeypatch):
    cfg, _, _ = env
    cfg['summary'].update(api_base='https://api.deepseek.com', model='deepseek-flash')
    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *args: pytest.fail('不应调用模型'))
    with pytest.raises(model_api.ModelUnavailable):
        summaries.run_api(cfg, summaries.collect(cfg, '2026-W42'))
    cfg['summary']['allow_remote_summary'] = True
    with pytest.raises(model_api.ModelUnavailable):
        intake.agent_fields(cfg, {'name': '甲同学'}, '2026-W42', {'kind': 'text', 'content': '测试文字'})
    cfg['summary']['allow_remote_intake'] = True
    with pytest.raises(model_api.ModelUnavailable):
        intake.agent_fields(cfg, {'name': '甲同学'}, '2026-W42', {'kind': 'image', 'content': '测试图片'})


def test_approved_deepseek_requests_text_only_json(env, monkeypatch):
    cfg, _, _ = env
    cfg['summary'].update(api_base='https://api.deepseek.com', model='deepseek-flash',
                          api_key_env='TEST_DEEPSEEK_KEY', allow_remote_summary=True)
    monkeypatch.setenv('TEST_DEEPSEEK_KEY', 'test-only')
    seed(cfg)
    manifest = summaries.collect(cfg, '2026-W42')
    expected = summaries.extractive(manifest)

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://api.deepseek.com/chat/completions'
            assert request.get_header('Authorization') == 'Bearer test-only'
            payload = json.loads(request.data)
            assert payload['response_format'] == {'type': 'json_object'}
            assert payload['stream'] is False
            prompt = payload['messages'][-1]['content']
            model_input = json.loads(prompt.split('以下是唯一的数据来源：\n')[1])
            assert set(model_input) == {'week', 'reports'}
            assert set(model_input['reports'][0]) == {'id', 'sha256', 'content'}
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(expected)}}]}).encode())

    monkeypatch.setattr(model_api.urllib.request, 'build_opener', lambda *handlers: Opener())
    assert summaries.run_api(cfg, manifest) == expected


def test_ready_standard_report_retries_and_coalesces_same_week(env, monkeypatch):
    cfg, app, _ = env
    reports = [('alice', '甲同学'), ('bob', '乙同学')]
    for uid, name in reports:
        with core.locked(cfg):
            status, _ = intake.store_upload(cfg, {'id': uid, 'name': name}, '2026-W42', 'weekly.md',
                                           core.report_markdown(name, '2026-W42', FIELDS).encode())
        assert status['status'] == 'ready'
    summarize = summaries.summarize
    calls = []
    def flaky(cfg, week):
        calls.append(week)
        if len(calls) == 1:
            raise ValueError('测试中第一次调用失败')
        return summarize(cfg, week)
    monkeypatch.setattr(summaries, 'summarize', flaky)
    client = app.test_client()
    assert intake.process_pending(cfg)['summarized'] == 0
    assert '将自动重试' in client.get('/api/upload-status?member_id=alice&week=2026-W42').json['status_detail']
    assert intake.process_pending(cfg)['summarized'] == 1
    assert intake.process_pending(cfg)['summarized'] == 0
    assert calls == ['2026-W42', '2026-W42']
    assert client.get('/api/team/2026-W42').json['submitted'] == 2
    assert 'summary_error' not in intake.load_status(cfg, 'alice', '2026-W42')


def test_unknown_format_needs_review_without_calling_agent(env, monkeypatch):
    cfg, app, _ = env
    file_upload(app.test_client(), b'binary', filename='weekly.unknown')
    monkeypatch.setattr(intake, 'agent_fields', lambda *args: pytest.fail('不应调用模型'))
    result = intake.process_pending(cfg)
    assert result['needs_review'] == 1
    assert intake.load_status(cfg, 'alice', '2026-W42')['status'] == 'needs_review'
    assert not (cfg['roots']['members']/'alice/reports/2026-W42.md').exists()


def test_conflicting_formal_report_is_preserved(env, monkeypatch):
    cfg, app, _ = env
    file_upload(app.test_client(), '自由文本周报', filename='weekly.txt')
    seed(cfg, text='维护人员已经确认的正式内容')
    before = core.read_text(cfg['roots']['members']/'alice/reports/2026-W42.md')
    monkeypatch.setattr(intake, 'agent_fields', lambda *args: FIELDS)
    result = intake.process_pending(cfg)
    assert result['needs_review'] == 1
    assert core.read_text(cfg['roots']['members']/'alice/reports/2026-W42.md') == before
    assert intake.load_status(cfg, 'alice', '2026-W42')['status'] == 'needs_review'
