import io
import json

import pytest
from werkzeug.datastructures import MultiDict

from research_weekly import core, intake, report_sources, summaries, team_activity
from test_system import HEADERS, FIELDS, env, seed, upload


WEEK = '2026-W44'
DAY = '2026-10-28'
ENDPOINT = '/api/team/activity'


def test_live_coverage_before_and_after_submissions(env):
    cfg, app, _ = env
    client = app.test_client()

    def activity(member='alice', day=DAY):
        return client.get(ENDPOINT, query_string={'week': WEEK, 'member': member, 'date': day}).json

    initial = activity()
    assert initial['dates'] == ['2026-10-26', '2026-10-27', DAY, '2026-10-29', '2026-10-30', '2026-10-31', '2026-11-01']
    assert [row['weekly_status'] for row in initial['members']] == ['missing'] * 3
    assert initial['selected_daily'] is None

    # Existing clients do not have to set a visibility flag in a team deployment.
    legacy = client.post('/api/daily/uploads', headers=HEADERS, json={
        'member_id':'alice', 'date':DAY, 'fields':FIELDS,
    })
    assert legacy.status_code == 201
    assert activity()['members'][0]['days'] == [DAY]
    assert activity()['selected_daily'] == {'date':DAY, 'fields':FIELDS, 'attachment_count':0}

    shared = client.post('/api/daily/uploads', headers=HEADERS, json={
        'member_id':'bob', 'date':DAY, 'fields':FIELDS, 'team_visible':True,
    })
    assert shared.status_code == 201
    assert activity('bob')['selected_daily']['fields'] == FIELDS
    app.config['RESEARCH']['demo'] = False
    assert activity('bob')['selected_daily']['fields'] is None
    app.config['RESEARCH']['demo'] = True

    pending = client.post('/api/uploads', headers=HEADERS, data={
        'member_id':'carol', 'week':WEEK, 'file':(io.BytesIO(b'example'), 'weekly.txt'),
    })
    assert pending.status_code == 201
    assert upload(client, week=WEEK).status_code == 201
    assert [row['weekly_status'] for row in activity()['members']] == ['ready','missing','queued']
    weekly_query = {'week':WEEK, 'member':'alice', 'report':'weekly'}
    assert client.get(ENDPOINT, query_string=weekly_query).json['selected_weekly'] == {'fields':FIELDS}
    cfg['demo'] = False
    assert client.get(ENDPOINT, query_string=weekly_query).json['selected_weekly'] is None
    assert activity()['selected_daily']['fields'] is None
    cfg['security']['team_reports_shared'] = True
    assert client.get(ENDPOINT, query_string=weekly_query).json['selected_weekly'] == {'fields':FIELDS}
    assert activity()['selected_daily']['fields'] == FIELDS
    cfg['demo'] = True
    summaries.summarize(cfg, WEEK, 'extractive')
    updated = activity()
    assert updated['weekly_revision'] == 1
    assert [row['weekly_status'] for row in updated['members']] == ['published','missing','queued']
    assert 'weekly.txt' not in str(updated)
    seed(cfg, week=WEEK, text='修订后的报告，等待重新汇总')
    assert activity()['members'][0]['weekly_status'] == 'ready'


def test_historical_malformed_daily_keeps_coverage(env):
    cfg, app, _ = env
    daily = cfg['roots']['members'] / 'alice' / 'daily'
    daily.mkdir()
    (daily / f'{DAY}.md').write_text('历史文件待维护人员核对', encoding='utf-8')
    result = app.test_client().get(ENDPOINT, query_string={'week':WEEK, 'member':'alice', 'date':DAY})
    assert result.status_code == 200
    assert result.json['members'][0]['days'] == [DAY]
    assert result.json['selected_daily']['unavailable'] is True


def test_team_activity_bounds_and_asset_routes(env):
    _, app, _ = env
    client = app.test_client()
    assert client.get(ENDPOINT).status_code == 200
    for query in ('week=2026-W55', 'member=../../alice', 'week=2026-W44&date=2026-11-02', 'date=garbage'):
        assert client.get(f'{ENDPOINT}?{query}').status_code == 400
    for asset in ('activity.css', 'activity.js'):
        assert client.get('/assets/' + asset).status_code == 200


def test_feeds_show_every_saved_report_and_stable_source_links(env):
    cfg, app, _ = env
    client = app.test_client()
    initial = client.get(ENDPOINT, query_string={'week': WEEK}).json
    assert initial['daily_records'] == [] and initial['weekly_reports'] == []
    for uid, day in [('alice', DAY), ('bob', DAY), ('alice', '2026-10-29')]:
        assert client.post('/api/daily/uploads', headers=HEADERS, json={
            'member_id':uid, 'date':day, 'fields':FIELDS,
        }).status_code == 201
    assert upload(client, uid='alice', week=WEEK).status_code == 201
    assert upload(client, uid='bob', week=WEEK).status_code == 201
    assert client.post('/api/uploads', headers=HEADERS, data={
        'member_id':'carol', 'week':WEEK, 'file':(io.BytesIO(b'synthetic pending report'), 'pending.txt'),
    }).status_code == 201
    result = client.get(ENDPOINT, query_string={'week': WEEK}).json
    assert [record['date'] for record in result['daily_records']] == ['2026-10-29', DAY, DAY]
    same_day = [record for record in result['daily_records'] if record['date'] == DAY]
    assert [record['member_name'] for record in same_day] == sorted(record['member_name'] for record in same_day)
    assert len(result['weekly_reports']) == 3
    assert [record['member_name'] for record in result['weekly_reports']] == sorted(record['member_name'] for record in result['weekly_reports'])
    alice = next(record for record in result['weekly_reports'] if record['member_id'] == 'alice')
    assert alice['fields'] == FIELDS and alice['status'] == 'ready'
    assert alice['url'] == f'#team?week={WEEK}&member=alice&report=weekly'
    assert alice['original_url'] == f'/progress/api/report-source/weekly/alice/{WEEK}'
    pending = next(record for record in result['weekly_reports'] if record['member_id'] == 'carol')
    assert pending['fields'] is None and pending['status'] == 'queued'
    assert pending['original_label'] == '下载周报原件'
    assert 'pending.txt' not in str(result)
    for record in result['daily_records']:
        assert record['fields'] == FIELDS
        assert record['attachment_count'] == 0 and record['imported_body'] is False
        assert record['url'] == f'#team?week={WEEK}&member={record["member_id"]}&date={record["date"]}'
        assert record['original_label'] == '下载日报记录 Markdown'
        response = client.get(record['original_url'].removeprefix('/progress'))
        assert response.status_code == 200
    before = {str(path):path.read_bytes() for root in (cfg['roots']['members'], cfg['roots']['team'])
              for path in root.rglob('*') if path.is_file()}
    client.get(ENDPOINT, query_string={'week': WEEK})
    after = {str(path):path.read_bytes() for root in (cfg['roots']['members'], cfg['roots']['team'])
             for path in root.rglob('*') if path.is_file()}
    assert after == before


def test_feed_imported_daily_exposes_existing_original_and_attachments(env):
    _, app, _ = env
    client = app.test_client()
    assert client.post('/api/daily/uploads', headers=HEADERS, data=MultiDict([
        ('member_id','alice'), ('date',DAY), ('file',(io.BytesIO('今日完成：合成正文'.encode()),'日报.txt')),
        ('attachments',(io.BytesIO(b'z'),'z.csv')), ('attachments',(io.BytesIO(b'a'),'a.txt')),
    ])).status_code == 201
    record = client.get(ENDPOINT, query_string={'week': WEEK}).json['daily_records'][0]
    assert record['member_id'] == 'alice' and record['member_name'] == '甲同学'
    assert record['imported_body'] is True and record['attachment_count'] == 2
    assert record['fields']['done'] == '合成正文'
    assert record['original_label'] == '下载日报原件'
    assert record['original_url'] == f'/progress/api/report-source/daily/alice/{DAY}'
    assert [entry['name'] for entry in record['attachments']] == ['a.txt','z.csv']
    for attachment in record['attachments']:
        assert client.get(attachment['url'].removeprefix('/progress')).status_code == 200


def test_shared_off_feeds_reveal_only_presence_and_no_source_metadata(env, monkeypatch):
    cfg, app, _ = env
    client = app.test_client()
    private = {**FIELDS, 'done':'PRIVATE_SYNTHETIC_REPORT'}
    assert client.post('/api/daily/uploads', headers=HEADERS, data=MultiDict([
        ('member_id','alice'), ('date',DAY), ('fields',json.dumps(private)),
        ('attachments',(io.BytesIO(b'private'),'PRIVATE_ATTACHMENT_NAME.txt')),
    ])).status_code == 201
    assert upload(client, uid='alice', week=WEEK, fields=private).status_code == 201
    cfg['demo'] = False
    cfg['security']['team_reports_shared'] = False
    monkeypatch.setattr(report_sources, 'describe', lambda *args: pytest.fail('未共享时不应解析原件'))
    result = client.get(ENDPOINT, query_string={'week':WEEK, 'member':'alice', 'date':DAY}).json
    assert result['selected_daily']['fields'] is None
    for record in result['daily_records'] + result['weekly_reports']:
        assert record['fields'] is None and record['unavailable'] is True and record['shared'] is False
        assert 'original_url' not in record and 'attachments' not in record
    assert result['daily_records'][0]['attachment_count'] == 0
    assert 'PRIVATE_' not in str(result)


def test_bad_individual_reports_keep_other_feed_entries_and_old_detail_contract(env):
    cfg, app, _ = env
    client = app.test_client()
    for uid in ('alice','bob'):
        assert client.post('/api/daily/uploads', headers=HEADERS, json={
            'member_id':uid, 'date':DAY, 'fields':FIELDS,
        }).status_code == 201
        assert upload(client, uid=uid, week=WEEK).status_code == 201
    core.atomic_write(cfg['roots']['members'] / 'bob' / 'daily' / f'{DAY}.md', 'PRIVATE_INVALID_DAILY')
    core.atomic_write(cfg['roots']['members'] / 'bob' / 'reports' / f'{WEEK}.md', 'PRIVATE_INVALID_WEEKLY')
    result = client.get(ENDPOINT, query_string={'week':WEEK}).json
    assert len(result['daily_records']) == len(result['weekly_reports']) == 2
    for records in (result['daily_records'], result['weekly_reports']):
        good = next(record for record in records if record['member_id'] == 'alice')
        bad = next(record for record in records if record['member_id'] == 'bob')
        assert good['fields'] == FIELDS
        assert bad['fields'] is None and bad['unavailable'] is True
        assert 'original_url' not in bad
    assert 'PRIVATE_INVALID' not in str(result)
    daily_detail = client.get(ENDPOINT, query_string={'week':WEEK,'member':'bob','date':DAY}).json
    assert daily_detail['selected_daily'] == {'date':DAY,'fields':None,'attachment_count':0,'unavailable':True}
    weekly_detail = client.get(ENDPOINT, query_string={'week':WEEK,'member':'bob','report':'weekly'}).json
    assert weekly_detail['selected_weekly'] is None


def test_feed_member_week_filters_and_single_report_budget_fallback(env):
    cfg, app, _ = env
    client = app.test_client()
    for uid in ('alice','bob'):
        assert client.post('/api/daily/uploads', headers=HEADERS, json={
            'member_id':uid, 'date':DAY, 'fields':FIELDS,
        }).status_code == 201
        assert upload(client, uid=uid, week=WEEK).status_code == 201
    cfg['summary']['max_total_bytes'] = len(json.dumps(FIELDS, ensure_ascii=False).encode())
    filtered = client.get(ENDPOINT, query_string={'week':WEEK,'member':'alice','date':DAY}).json
    assert len(filtered['members']) == 3
    assert [record['member_id'] for record in filtered['daily_records']] == ['alice']
    assert [record['member_id'] for record in filtered['weekly_reports']] == ['alice']
    assert filtered['daily_records'][0]['fields'] == FIELDS
    deferred = filtered['weekly_reports'][0]
    assert deferred['fields'] is None and deferred['content_deferred'] is True
    assert not deferred.get('unavailable')
    assert filtered['selected_daily'] == {'date':DAY,'fields':FIELDS,'attachment_count':0}
    selected = client.get(ENDPOINT, query_string={'week':WEEK,'member':'alice','report':'weekly'}).json
    assert selected['selected_weekly'] == {'fields':FIELDS}
    empty = client.get(ENDPOINT, query_string={'week':'2026-W43','member':'alice'}).json
    assert empty['daily_records'] == empty['weekly_reports'] == []
    assert empty['selected_daily'] is None and empty['selected_weekly'] is None
    unknown = client.get(ENDPOINT, query_string={'week':WEEK,'member':'unknown'}).json
    assert unknown['daily_records'] == unknown['weekly_reports'] == []


def test_weekly_timetable_four_iso_weeks_cross_year_without_historical_bodies(env, monkeypatch):
    cfg, app, _ = env
    weeks = ['2027-W01', '2026-W53', '2026-W52', '2026-W51']
    for week in [*weeks, '2026-W50', '2027-W02']:
        seed(cfg, uid='alice', week=week)
    seed(cfg, uid='bob', week='2026-W53')
    read_text = team_activity.read_text
    def guard_historical_body(path, *args):
        assert not (path.parent.name == 'reports' and path.stem in weeks[1:]), '时间表不应读取历史全文'
        return read_text(path, *args)
    monkeypatch.setattr(team_activity, 'read_text', guard_historical_body)
    result = app.test_client().get(ENDPOINT, query_string={'week': weeks[0]}).json
    table = result['weekly_timetable']
    assert table['weeks'] == weeks
    assert len(table['records']) == 5
    assert {(record['member_id'], record['week']) for record in table['records']} == {
        ('alice', week) for week in weeks
    } | {('bob', '2026-W53')}
    assert [record['member_name'] for record in table['records']] == sorted(record['member_name'] for record in table['records'])
    for record in table['records']:
        uid, week = record['member_id'], record['week']
        assert record['url'] == f'#team?week={week}&member={uid}&report=weekly'
        assert record['original_url'] == f'/progress/api/report-source/weekly/{uid}/{week}'
        assert record['readable'] is True
        assert 'status' not in record and 'fields' not in record
    assert result['selected_weekly'] is None
    assert [record['week'] for record in result['weekly_reports']] == ['2027-W01']


def test_weekly_timetable_existing_original_missing_source_and_bad_metadata(env):
    cfg, app, _ = env
    client = app.test_client()
    selected = '2026-W46'
    previous = '2026-W45'
    assert client.post('/api/uploads', headers=HEADERS, data={
        'member_id':'alice', 'week':previous, 'file':(io.BytesIO(b'synthetic original'), 'source.pdf'),
    }).status_code == 201
    original = intake.original_path(cfg, 'alice', previous, '.pdf')
    table = client.get(ENDPOINT, query_string={'week':selected}).json['weekly_timetable']
    assert len(table['records']) == 1
    assert table['records'][0]['week'] == previous
    assert table['records'][0]['readable'] is True
    assert table['records'][0]['original_label'] == '下载周报原件'
    assert not (cfg['roots']['members'] / 'alice' / 'reports' / f'{previous}.md').exists()
    original.unlink()
    assert client.get(ENDPOINT, query_string={'week':selected}).json['weekly_timetable']['records'] == []
    seed(cfg, uid='bob', week='2026-W44')
    core.atomic_write(cfg['roots']['members'] / 'bob' / 'uploads' / '2026-W44.json', 'PRIVATE_BAD_METADATA')
    core.atomic_write(cfg['roots']['members'] / 'carol' / 'uploads' / '2026-W45.json', 'PRIVATE_BAD_METADATA')
    seed(cfg, uid='alice', week=selected)
    result = client.get(ENDPOINT, query_string={'week':selected}).json
    table = result['weekly_timetable']
    assert {(record['member_id'], record['week']) for record in table['records']} == {('bob','2026-W44'),('alice',selected)}
    broken = next(record for record in table['records'] if record['member_id'] == 'bob')
    assert broken['readable'] is False and 'original_url' not in broken
    assert next(record for record in table['records'] if record['member_id'] == 'alice')['readable'] is True
    assert 'PRIVATE_BAD_METADATA' not in str(result)


def test_weekly_timetable_sharing_and_member_filter_keep_other_contracts(env, monkeypatch):
    cfg, app, _ = env
    client = app.test_client()
    for uid, week in [('alice','2026-W44'),('bob','2026-W43')]:
        seed(cfg, uid=uid, week=week)
    filtered = client.get(ENDPOINT, query_string={'week':WEEK,'member':'bob'}).json
    assert len(filtered['members']) == 3
    assert [(record['member_id'], record['week']) for record in filtered['weekly_timetable']['records']] == [('bob','2026-W43')]
    assert filtered['weekly_reports'] == []
    assert filtered['selected_daily'] is None and filtered['selected_weekly'] is None
    cfg['demo'] = False
    cfg['security']['team_reports_shared'] = False
    monkeypatch.setattr(report_sources, 'describe', lambda *args: pytest.fail('未共享时不应解析下载信息'))
    table = client.get(ENDPOINT, query_string={'week':WEEK}).json['weekly_timetable']
    assert len(table['records']) == 2
    for record in table['records']:
        assert record['readable'] is False
        assert set(record) == {'member_id','member_name','week','url','readable'}
    unknown = client.get(ENDPOINT, query_string={'week':WEEK,'member':'unknown'}).json
    assert unknown['weekly_timetable']['records'] == []
    assert unknown['weekly_timetable']['weeks'] == ['2026-W44','2026-W43','2026-W42','2026-W41']
