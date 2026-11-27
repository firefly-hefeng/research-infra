import copy
import datetime as dt
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from research_weekly import core, daily_reports, directions, model_api, progress_digest
from test_system import env


@pytest.fixture
def context(env, monkeypatch):
    cfg, _, _ = env
    cfg['progress_digest'] = {'enabled': True}
    cfg['summary'].update(api_base='https://api.deepseek.com', model='deepseek-flash')
    clock = [dt.datetime(2026, 11, 15, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))]
    monkeypatch.setattr(progress_digest, 'now', lambda config: clock[0])
    root = cfg['roots']['team'] / 'directions'
    root.mkdir()
    monkeypatch.setattr(directions, 'direction_roots', lambda config: (root,))
    for direction in ('alpha', 'beta'):
        core.atomic_write(root / (direction + '.md'), f'# {direction} 研究\n\n核对日期：2026-10-01\n\n'
                          f'## 研究问题\n\n{direction} 问题\n\n## 当前进展\n\n旧的 {direction} 基线\n\n'
                          '## 下一步\n\n开展外部验证\n')
    return cfg, clock


def report(cfg, uid, when, kind='daily', done=None):
    member = core.member(cfg, uid)
    fields = {'done': done or ('完成 alpha 数据核验' if uid == 'alice' else '完成 beta 特征检查'),
              'results': '合成结果见核验记录', 'blockers': '设备字段待补齐', 'next': '继续小样本检验'}
    if kind == 'daily':
        text = daily_reports.markdown(member['name'], when, fields)
        path = core.child(cfg['roots']['members'], uid, 'daily', when + '.md')
    else:
        text = core.report_markdown(member['name'], when, fields)
        path = core.child(cfg['roots']['members'], uid, 'reports', when + '.md')
    core.atomic_write(path, text)
    return path


def recent_reports(cfg):
    report(cfg, 'alice', '2026-11-14')
    report(cfg, 'bob', '2026-11-10')
    report(cfg, 'alice', '2026-W46', 'weekly')
    report(cfg, 'bob', '2026-W45', 'weekly')


def fields():
    return {key: [] for key in progress_digest.FIELDS}


def evidence(source):
    quote = next(line for line in source['content'].splitlines() if line.strip() and not line.startswith('#'))
    return {'text': quote, 'source_ids': [source['id']], 'evidence': [{'source_id': source['id'], 'quote': quote}]}


def result_for(manifest):
    rows, recent = [], []
    for person in manifest['members']:
        row = {'id': person['id'], **fields()}
        source = next((source for source in manifest['sources'] if source.get('member_id') == person['id']), None)
        if source:
            row['done'] = [evidence(source)]
            recent.append(evidence(source))
        rows.append(row)
    direction_rows = []
    for index, direction in enumerate(manifest['directions']):
        row = {'id': direction['id'], **fields()}
        if index < len(recent):
            row['done'] = [copy.deepcopy(recent[index])]
        direction_rows.append(row)
    return {'team': {**fields(), 'done': recent}, 'members': rows,
            'directions': direction_rows, 'unassigned': fields()}


def mock_model(monkeypatch, calls):
    def complete(settings, messages, *, purpose):
        assert purpose == 'progress'
        assert '不可信资料' in messages[-1]['content']
        manifest = json.loads(messages[-1]['content'].split('以下是唯一输入\n')[1])
        calls.append(manifest)
        return result_for(manifest)
    monkeypatch.setattr(model_api, 'complete_json', complete)


def test_collect_complete_window_shared_sources_and_stable_links(context):
    cfg, _ = context
    recent_reports(cfg)
    report(cfg, 'alice', '2026-10-18', done='窗口外旧报告')
    report(cfg, 'alice', '2026-11-16', done='未来报告')
    report(cfg, 'alice', '2026-W39', 'weekly', done='窗口外旧周报')
    core.atomic_write(core.child(cfg['roots']['members'], 'alice', 'files', 'private.md'), 'PRIVATE_UNRELATED')
    core.atomic_write(core.child(cfg['roots']['members'], 'alice', 'daily', '2026-11-14', 'attachment-1'), 'PRIVATE_ATTACHMENT')
    manifest = progress_digest.collect(cfg)
    assert manifest['period'] == {'from': '2026-10-19', 'to': '2026-11-15', 'days': 28}
    assert len(manifest['sources']) == 6
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert not any(text in serialized for text in ('窗口外', '未来报告', 'PRIVATE_ATTACHMENT', 'PRIVATE_UNRELATED'))
    source = next(source for source in manifest['sources'] if source['id'] == 'daily:alice:2026-11-14')
    assert source['url'] == '#team?week=2026-W46&member=alice&date=2026-11-14'
    assert source['sha256'] == core.digest(source['content'])
    weekly = next(source for source in manifest['sources'] if source['id'] == 'weekly:alice:2026-W46')
    assert weekly['url'].endswith('member=alice&report=weekly')
    assert manifest['directions'][0]['baseline']['progress'] == '旧的 alpha 基线'


def test_publish_exact_schema_and_source_provenance(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    calls = []
    mock_model(monkeypatch, calls)
    assert progress_digest.refresh(cfg) == {'changed': True, 'state': 'ready', 'revision': 1}
    public = progress_digest.read(cfg)
    doc = public['document']
    assert public['status']['last_success_at'] == doc['generated_at']
    assert doc['schema_version'] == 1 and doc['engine'] == 'DeepSeek Flash'
    assert doc['strategy_version'] == progress_digest.STRATEGY_VERSION
    assert doc['research_brief']['overview'] == doc['team']['done']
    assert doc['research_brief']['findings'] == doc['team']['results']
    assert doc['research_brief']['constraints'] == doc['team']['blockers']
    assert doc['research_brief']['priorities'] == doc['team']['next']
    assert doc['counts'] == {'members': 3, 'active_members': 2, 'daily': 2, 'weekly': 2, 'directions': 2}
    assert [row['report_count'] for row in doc['members']] == [2, 2, 0]
    assert doc['members'][0]['last_report_at'] == '2026-11-15'
    assert doc['members'][2]['done'] == []
    assert doc['directions'][0]['baseline']['updated_at'] == '2026-10-01'
    assert [row['report_count'] for row in doc['directions']] == [1, 1]
    assert all('content' not in source for source in doc['sources'])
    assert len(calls) == 1
    assert set(progress_digest.refresh(cfg)) == {'changed', 'state', 'revision'}
    assert len(calls) == 1


def test_dedicated_model_policy_isolated_and_part_of_fingerprint(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    calls = []
    settings_seen = []
    cfg['summary']['api_key_env'] = 'EXISTING_RESEARCH_KEY'
    original = copy.deepcopy(cfg['summary'])
    def complete(settings, messages, **kwargs):
        settings_seen.append(copy.deepcopy(settings))
        manifest = json.loads(messages[-1]['content'].split('以下是唯一输入\n')[1])
        calls.append(manifest)
        return result_for(manifest)
    monkeypatch.setattr(model_api, 'complete_json', complete)
    progress_digest.refresh(cfg)
    previous = progress_digest.read(cfg)['document']
    cfg['progress_digest'].update(model='deepseek-v4-pro', thinking={'type': 'enabled'},
                                  reasoning_effort='max', max_tokens=65536, api_key_env='IGNORED_OVERRIDE')
    assert progress_digest.read(cfg)['status']['state'] == 'stale'
    assert progress_digest.refresh(cfg)['revision'] == 2
    document = progress_digest.read(cfg)['document']
    assert document['engine'] == 'DeepSeek V4 Pro · Max'
    assert document['fingerprint'] != previous['fingerprint']
    assert settings_seen[-1]['thinking'] == {'type': 'enabled'}
    assert settings_seen[-1]['reasoning_effort'] == 'max'
    assert settings_seen[-1]['max_tokens'] == 65536
    assert settings_seen[-1]['api_key_env'] == 'EXISTING_RESEARCH_KEY'
    assert cfg['summary'] == original
    cfg['summary']['api_key_env'] = 'ROTATED_RESEARCH_KEY'
    assert progress_digest.collect(cfg)['fingerprint'] == document['fingerprint']
    monkeypatch.setattr(progress_digest, 'STRATEGY_VERSION', 'test-next-strategy')
    assert progress_digest.collect(cfg)['fingerprint'] != document['fingerprint']
    assert progress_digest.refresh(cfg)['revision'] == 3
    archived = json.loads((cfg['roots']['state'] / 'progress-digest-history' / 'r2.json').read_text())
    assert archived == document
    assert 'DeepSeek V4 Pro · Max' in (cfg['roots']['state'] / 'progress-digest-history' / 'r2.md').read_text()
    assert 'api_key_env' not in json.dumps(progress_digest.collect(cfg)['generation'])
    assert 'generation' not in calls[-1]


def test_engine_label_describes_configured_model_without_claiming_max(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    cfg['progress_digest'].update(model='deepseek-v4-pro', thinking={'type': 'disabled'}, reasoning_effort='max')
    mock_model(monkeypatch, [])
    progress_digest.refresh(cfg)
    assert progress_digest.read(cfg)['document']['engine'] == 'DeepSeek V4 Pro'


def test_research_brief_preserves_verified_evidence_and_proposals(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    manifest = progress_digest.collect(cfg)
    result = result_for(manifest)
    item = copy.deepcopy(result['team']['done'][0])
    proposed = copy.deepcopy(item)
    proposed['text'] = '建议先核对采集设备，再开展跨来源验证。'
    result['research_brief'] = {'overview': [item], 'findings': [copy.deepcopy(item)],
                                'constraints': [], 'priorities': [proposed]}
    monkeypatch.setattr(model_api, 'complete_json', lambda *args, **kwargs: result)
    assert progress_digest.refresh(cfg)['state'] == 'ready'
    document = progress_digest.read(cfg)['document']
    assert document['research_brief'] == result['research_brief']
    markdown = (cfg['roots']['team'] / 'progress-digest.md').read_text()
    assert '## 科研总览' in markdown and '### 验证优先级' in markdown
    assert '建议先核对采集设备' in markdown
    assert '归纳引擎 DeepSeek Flash' in markdown
    assert markdown.index('## 科研总览') < markdown.index('## 团队进展')
    assert '#team?week=' in markdown


@pytest.mark.parametrize('case', ['invented_quote', 'only_baseline', 'unlabelled_proposal', 'empty_overview'])
def test_research_brief_requires_report_evidence_and_clear_proposals(context, monkeypatch, case):
    cfg, _ = context
    recent_reports(cfg)
    manifest = progress_digest.collect(cfg)
    result = result_for(manifest)
    result['research_brief'] = {'overview': copy.deepcopy(result['team']['done']),
                                'findings': [], 'constraints': [], 'priorities': []}
    if case == 'invented_quote':
        result['research_brief']['overview'][0]['evidence'][0]['quote'] = '原文不存在的置信区间'
    elif case == 'only_baseline':
        baseline = next(source for source in manifest['sources'] if source['kind'] == 'direction')
        result['research_brief']['overview'] = [evidence(baseline)]
    elif case == 'unlabelled_proposal':
        proposed = copy.deepcopy(result['team']['done'][0])
        proposed['text'] = '立即采用跨疾病模型方案'
        result['research_brief']['priorities'] = [proposed]
    else:
        result['research_brief']['overview'] = []
    monkeypatch.setattr(model_api, 'complete_json', lambda *args, **kwargs: result)
    assert progress_digest.refresh(cfg)['state'] == 'failed'
    assert progress_digest.read(cfg)['document'] is None


def test_new_topic_can_stay_unassigned_without_creating_direction_ids(context, monkeypatch):
    cfg, _ = context
    report(cfg, 'alice', '2026-11-14', done='开展胰腺疾病配对研究，尚未形成独立测试结论')
    manifest = progress_digest.collect(cfg)
    result = result_for(manifest)
    result['unassigned']['done'] = copy.deepcopy(result['team']['done'])
    for row in result['directions']:
        row.update(fields())
    prompt = progress_digest._prompt(manifest)
    assert '不能作为同一方向的依据' in prompt
    monkeypatch.setattr(model_api, 'complete_json', lambda *args, **kwargs: result)
    assert progress_digest.refresh(cfg)['state'] == 'ready'
    document = progress_digest.read(cfg)['document']
    assert document['unassigned']['done']
    assert all(direction['report_count'] == 0 for direction in document['directions'])
    assert {direction['id'] for direction in document['directions']} == {'alpha', 'beta'}


def test_unchanged_inputs_skip_calls_across_dates_and_detect_updates(context, monkeypatch):
    cfg, clock = context
    recent_reports(cfg)
    calls = []
    mock_model(monkeypatch, calls)
    progress_digest.refresh(cfg)
    clock[0] += dt.timedelta(days=1)
    assert progress_digest.refresh(cfg)['changed'] is False
    assert len(calls) == 1
    report(cfg, 'alice', '2026-11-14', done='新增的合成数据核验')
    assert progress_digest.read(cfg)['status']['state'] == 'stale'
    assert progress_digest.read(cfg)['document']['revision'] == 1
    assert progress_digest.refresh(cfg)['revision'] == 2
    assert len(calls) == 2


def test_failure_keeps_previous_version_and_retries_after_cooldown(context, monkeypatch):
    cfg, clock = context
    recent_reports(cfg)
    calls = []
    mock_model(monkeypatch, calls)
    progress_digest.refresh(cfg)
    previous = (cfg['roots']['team'] / 'progress-digest.json').read_bytes()
    report(cfg, 'alice', '2026-11-14', done='更新后的合成核验')
    failures = []
    def fail(*args, **kwargs):
        failures.append(True)
        raise ValueError('合成模型暂不可用')
    monkeypatch.setattr(model_api, 'complete_json', fail)
    assert progress_digest.refresh(cfg) == {'changed': False, 'state': 'failed', 'revision': 1}
    state = progress_digest.read(cfg)['status']
    assert state['error'] == '合成模型暂不可用'
    assert dt.datetime.fromisoformat(state['next_retry_at']) - clock[0] == dt.timedelta(minutes=5)
    assert progress_digest.refresh(cfg)['state'] == 'failed'
    assert len(failures) == 1
    assert progress_digest.refresh(cfg, force=True)['state'] == 'failed'
    assert len(failures) == 2
    assert (cfg['roots']['team'] / 'progress-digest.json').read_bytes() == previous
    clock[0] += dt.timedelta(seconds=301)
    mock_model(monkeypatch, calls)
    assert progress_digest.refresh(cfg)['revision'] == 2
    assert 'error' not in progress_digest.read(cfg)['status']


def test_input_changed_during_model_cannot_publish(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    calls = []
    mock_model(monkeypatch, calls)
    progress_digest.refresh(cfg)
    previous = progress_digest.read(cfg)['document']
    def change(settings, messages, **kwargs):
        before = json.loads(messages[-1]['content'].split('以下是唯一输入\n')[1])
        report(cfg, 'alice', '2026-11-14', done='模型运行时新增的记录')
        return result_for(before)
    monkeypatch.setattr(model_api, 'complete_json', change)
    result = progress_digest.refresh(cfg, force=True)
    assert result == {'changed': False, 'state': 'failed', 'revision': 1}
    current = progress_digest.read(cfg)
    assert current['document'] == previous
    assert '输入发生变化' in current['status']['error']


@pytest.mark.parametrize('case', ['quote', 'missing_member', 'unknown_direction', 'cross_member', 'baseline_only', 'uncited', 'empty_active'])
def test_invalid_model_evidence_never_publishes(context, monkeypatch, case):
    cfg, _ = context
    recent_reports(cfg)
    manifest = progress_digest.collect(cfg)
    result = result_for(manifest)
    if case == 'quote':
        result['team']['done'][0]['evidence'][0]['quote'] = '原文并不存在的实验结论'
    elif case == 'missing_member':
        result['members'].pop()
    elif case == 'unknown_direction':
        result['directions'][0]['id'] = 'invented-direction'
    elif case == 'cross_member':
        result['members'][0]['done'] = copy.deepcopy(result['members'][1]['done'])
    elif case == 'baseline_only':
        baseline = next(source for source in manifest['sources'] if source['kind'] == 'direction')
        result['team']['done'] = [evidence(baseline)]
    elif case == 'uncited':
        result['team']['done'][0]['source_ids'].append(result['team']['done'][1]['source_ids'][0])
    elif case == 'empty_active':
        result['members'][0].update(fields())
    monkeypatch.setattr(model_api, 'complete_json', lambda *args, **kwargs: result)
    assert progress_digest.refresh(cfg)['state'] == 'failed'
    assert progress_digest.read(cfg)['document'] is None


def test_one_bounded_repair_can_remove_unsupported_old_baseline(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    manifest = progress_digest.collect(cfg)
    correct = result_for(manifest)
    invalid = copy.deepcopy(correct)
    baseline = next(source for source in manifest['sources'] if source['kind'] == 'direction')
    invalid['directions'][0]['done'] = [evidence(baseline)]
    calls = []
    def complete(settings, messages, **kwargs):
        calls.append(copy.deepcopy(messages))
        return invalid if len(calls) == 1 else correct
    monkeypatch.setattr(model_api, 'complete_json', complete)
    assert progress_digest.refresh(cfg)['state'] == 'ready'
    assert len(calls) == 2
    assert '校验未通过' in calls[1][-1]['content']
    assert progress_digest.read(cfg)['document']['revision'] == 1


def test_unused_model_metadata_is_discarded_without_weakening_evidence(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    result = result_for(progress_digest.collect(cfg))
    result['schema_version'] = 'untrusted-model-value'
    result['sources'] = [{'url': 'https://untrusted.invalid'}]
    result['team']['done'][0]['extra'] = 'ignored'
    result['team']['done'][0]['evidence'][0]['extra'] = 'ignored'
    monkeypatch.setattr(model_api, 'complete_json', lambda *args, **kwargs: result)
    assert progress_digest.refresh(cfg)['state'] == 'ready'
    document = progress_digest.read(cfg)['document']
    assert document['schema_version'] == 1
    assert 'extra' not in document['team']['done'][0]
    assert 'extra' not in document['team']['done'][0]['evidence'][0]
    assert all('untrusted.invalid' not in source['url'] for source in document['sources'])


def test_disabled_empty_and_budget_have_no_model_calls(context, monkeypatch):
    cfg, _ = context
    monkeypatch.setattr(model_api, 'complete_json', lambda *args, **kwargs: pytest.fail('不应调用模型'))
    assert progress_digest.refresh(cfg) == {'changed': False, 'state': 'pending'}
    cfg['progress_digest']['enabled'] = False
    assert progress_digest.read(cfg)['status']['state'] == 'disabled'
    assert progress_digest.refresh(cfg)['state'] == 'disabled'
    cfg['progress_digest']['enabled'] = True
    recent_reports(cfg)
    cfg['summary']['max_total_bytes'] = 100
    assert progress_digest.refresh(cfg)['state'] == 'failed'
    assert progress_digest.read(cfg)['document'] is None


def test_disabled_sharing_hides_saved_document(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    mock_model(monkeypatch, [])
    progress_digest.refresh(cfg)
    cfg['progress_digest']['enabled'] = False
    assert progress_digest.read(cfg)['document'] is None
    cfg['progress_digest']['enabled'] = True
    cfg['demo'] = False
    cfg['security']['team_reports_shared'] = False
    assert progress_digest.read(cfg)['document'] is None
    assert progress_digest.refresh(cfg)['state'] == 'disabled'


def test_json_publish_failure_restores_markdown_and_keeps_history(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    mock_model(monkeypatch, [])
    progress_digest.refresh(cfg)
    path = cfg['roots']['team'] / 'progress-digest.json'
    old_json = path.read_bytes()
    old_markdown = path.with_suffix('.md').read_bytes()
    report(cfg, 'alice', '2026-11-14', done='新的合成核验结果')
    write_json = progress_digest.write_json
    def fail_on_main(target, document):
        if target == path:
            raise OSError('synthetic atomic write failure')
        write_json(target, document)
    monkeypatch.setattr(progress_digest, 'write_json', fail_on_main)
    assert progress_digest.refresh(cfg) == {'changed': False, 'state': 'failed', 'revision': 1}
    assert path.read_bytes() == old_json
    assert path.with_suffix('.md').read_bytes() == old_markdown
    archive = cfg['roots']['state'] / 'progress-digest-history' / 'r1.json'
    assert json.loads(archive.read_text()) == json.loads(old_json)
    assert archive.with_suffix('.md').read_bytes() == old_markdown


def test_concurrent_refresh_has_one_model_call_and_running_status(context, monkeypatch):
    cfg, _ = context
    recent_reports(cfg)
    started, finish = threading.Event(), threading.Event()
    calls = []
    def complete(settings, messages, **kwargs):
        manifest = json.loads(messages[-1]['content'].split('以下是唯一输入\n')[1])
        calls.append(True)
        started.set()
        assert finish.wait(3)
        return result_for(manifest)
    monkeypatch.setattr(model_api, 'complete_json', complete)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(progress_digest.refresh, cfg)
        assert started.wait(3)
        second = workers.submit(progress_digest.refresh, cfg)
        assert progress_digest.read(cfg)['status']['state'] == 'running'
        finish.set()
        results = [first.result(timeout=3), second.result(timeout=3)]
    assert sorted(result['changed'] for result in results) == [False, True]
    assert len(calls) == 1
