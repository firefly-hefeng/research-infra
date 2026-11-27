import io
import json

import pytest
from werkzeug.datastructures import MultiDict

from research_weekly import daily_reports, report_sources
from test_system import FIELDS, HEADERS, env, upload


DAY = '2026-11-14'
WEEK = '2026-W46'


def test_http_download_headers_and_shared_boundary(env):
    cfg, app, _ = env
    client = app.test_client()
    assert upload(client, week=WEEK).status_code == 201
    response = client.get(f'/api/report-source/weekly/alice/{WEEK}')
    assert response.status_code == 200
    assert response.headers['Content-Disposition'].startswith('attachment;')
    assert response.headers['Content-Security-Policy'] == "default-src 'none'; frame-ancestors 'none'; sandbox"
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.get(f'/api/report-source/weekly/unknown/{WEEK}').status_code == 404
    cfg['demo'] = False
    cfg['security']['team_reports_shared'] = False
    assert client.get(f'/api/report-source/weekly/alice/{WEEK}').status_code == 403
    assert client.get('/api/progress-digest').json['document'] is None


def test_digest_download_metadata_is_locally_resolved(env, monkeypatch):
    from research_weekly import progress_digest
    cfg, app, _ = env
    client = app.test_client()
    assert upload(client, week=WEEK).status_code == 201
    monkeypatch.setattr(progress_digest, 'read', lambda config: {'document': {'sources': [{
        'id': 'w', 'kind': 'weekly', 'member_id': 'alice', 'week': WEEK,
    }]}, 'status': {'state': 'ready'}})
    source = client.get('/api/progress-digest').json['document']['sources'][0]
    assert source['original_url'] == f'/progress/api/report-source/weekly/alice/{WEEK}'
    assert source['attachments'] == []


def test_legacy_daily_and_weekly_downloads_are_shared_records(env):
    cfg, app, _ = env
    client = app.test_client()
    assert client.post('/api/daily/uploads', headers=HEADERS, json={
        'member_id': 'alice', 'date': DAY, 'fields': FIELDS,
    }).status_code == 201
    assert upload(client, week=WEEK).status_code == 201
    for kind, period, expected in [('daily', DAY, '日报'), ('weekly', WEEK, '周报')]:
        entry = report_sources.describe(cfg, kind, 'alice', period)
        assert entry == {
            'url': f'/progress/api/report-source/{kind}/alice/{period}',
            'label': f'下载{expected}记录 Markdown', 'attachments': [],
        }
        source = report_sources.resolve(cfg, kind, 'alice', period)
        assert source['filename'] == period + '.md'
        assert expected in source['path'].read_text(encoding='utf-8')


def test_daily_original_and_numbered_attachments(env):
    cfg, app, _ = env
    body = '今日完成\n完成核验'.encode()
    response = app.test_client().post('/api/daily/uploads', headers=HEADERS, data=MultiDict([
        ('member_id', 'alice'), ('date', DAY), ('file', (io.BytesIO(body), '日报.txt')),
        ('attachments', (io.BytesIO(b'z'), 'z-evidence.csv')),
        ('attachments', (io.BytesIO(b'a'), 'a-evidence.txt')),
    ]))
    assert response.status_code == 201
    info = report_sources.describe(cfg, 'daily', 'alice', DAY)
    assert info['label'] == '下载日报原件'
    assert [entry['name'] for entry in info['attachments']] == ['a-evidence.txt', 'z-evidence.csv']
    assert info['attachments'][0]['url'].endswith('/1')
    original = report_sources.resolve(cfg, 'daily', 'alice', DAY)
    assert original['path'].read_bytes() == body
    assert original['filename'] == '日报.txt'
    attachment = report_sources.resolve(cfg, 'daily', 'alice', DAY, '2')
    assert attachment['filename'] == 'z-evidence.csv' and attachment['path'].read_bytes() == b'z'


def test_weekly_upload_original_and_missing_original_fallback(env):
    cfg, app, _ = env
    client = app.test_client()
    original = b'not yet normalized'
    assert client.post('/api/uploads', headers=HEADERS, data={
        'member_id': 'alice', 'week': WEEK, 'file': (io.BytesIO(original), 'source.pdf'),
    }).status_code == 201
    result = report_sources.resolve(cfg, 'weekly', 'alice', WEEK)
    assert result['path'].read_bytes() == original and result['filename'] == 'source.pdf'
    result['path'].unlink()
    with pytest.raises(FileNotFoundError):
        report_sources.resolve(cfg, 'weekly', 'alice', WEEK)
    canonical = cfg['roots']['members'] / 'alice' / 'reports' / f'{WEEK}.md'
    canonical.write_text('record', encoding='utf-8')
    assert report_sources.describe(cfg, 'weekly', 'alice', WEEK)['label'] == '下载周报记录 Markdown'


def test_permissions_roster_and_strict_identifiers(env):
    cfg, _, _ = env
    cfg['demo'] = False
    with pytest.raises(PermissionError):
        report_sources.describe(cfg, 'daily', 'alice', DAY)
    cfg['security']['team_reports_shared'] = True
    for kind, uid, period in [('daily', '../alice', DAY), ('daily', 'alice', '../date'),
                              ('weekly', 'alice', '2026-W99'), ('files', 'alice', DAY)]:
        with pytest.raises(ValueError):
            report_sources.resolve(cfg, kind, uid, period)
    with pytest.raises(FileNotFoundError):
        report_sources.resolve(cfg, 'daily', 'unknown', DAY)


@pytest.mark.parametrize('index', [0, -1, '0', '01', '../1', 1.0, True])
def test_malformed_attachment_indices(env, index):
    cfg, app, _ = env
    app.test_client().post('/api/daily/uploads', headers=HEADERS, json={
        'member_id': 'alice', 'date': DAY, 'fields': FIELDS,
    })
    with pytest.raises(ValueError):
        report_sources.resolve(cfg, 'daily', 'alice', DAY, index)
    with pytest.raises(FileNotFoundError):
        report_sources.resolve(cfg, 'daily', 'alice', DAY, 9)


def test_symlink_or_metadata_paths_cannot_be_downloaded(env, tmp_path):
    cfg, app, _ = env
    client = app.test_client()
    client.post('/api/daily/uploads', headers=HEADERS, data=MultiDict([
        ('member_id', 'alice'), ('date', DAY), ('fields', json.dumps(FIELDS)),
        ('attachments', (io.BytesIO(b'evidence'), 'notes.txt')),
    ]))
    bundle = cfg['roots']['members'] / 'alice' / 'daily' / DAY
    hidden = tmp_path / 'private.txt'
    hidden.write_text('private', encoding='utf-8')
    attachment = bundle / 'attachment-1'
    attachment.unlink()
    attachment.symlink_to(hidden)
    with pytest.raises(ValueError):
        report_sources.describe(cfg, 'daily', 'alice', DAY)
    attachment.unlink()
    attachment.write_bytes(b'evidence')
    metadata_path = bundle / 'metadata.json'
    metadata = json.loads(metadata_path.read_text())
    metadata['attachments'][0]['name'] = '../../private.txt'
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        report_sources.resolve(cfg, 'daily', 'alice', DAY, 1)


def test_corrupt_daily_metadata_and_weekly_status_are_rejected(env):
    cfg, app, _ = env
    client = app.test_client()
    assert client.post('/api/daily/uploads', headers=HEADERS, data=MultiDict([
        ('member_id', 'alice'), ('date', DAY), ('fields', json.dumps(FIELDS)),
        ('attachments', (io.BytesIO(b'evidence'), 'notes.txt')),
    ])).status_code == 201
    bundle = cfg['roots']['members'] / 'alice' / 'daily' / DAY
    (bundle / 'metadata.json').write_text('[]', encoding='utf-8')
    with pytest.raises(ValueError):
        report_sources.describe(cfg, 'daily', 'alice', DAY)
    assert client.post('/api/uploads', headers=HEADERS, data={
        'member_id': 'alice', 'week': WEEK, 'file': (io.BytesIO(b'raw'), 'source.pdf'),
    }).status_code == 201
    path = cfg['roots']['members'] / 'alice' / 'uploads' / (WEEK + '.json')
    record = json.loads(path.read_text(encoding='utf-8'))
    record['extension'] = '.txt'
    path.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(ValueError):
        report_sources.resolve(cfg, 'weekly', 'alice', WEEK)
