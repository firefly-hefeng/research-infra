import json

from research_weekly import progress_digest
from test_system import env


def test_member_api_reads_registered_material_and_flags_stale(env):
    cfg, app, _ = env
    client = app.test_client()
    team = cfg['roots']['team']
    notes = team / 'directions'
    notes.mkdir()
    (notes / 'example.md').write_text('# Example\n\n## 研究问题\n\nHow reproducible is this test?\n', encoding='utf8')
    assert client.get('/api/directions').json['items'][0]['id'] == 'example'
    assert 'How reproducible' in client.get('/api/directions/example').json['question']
    state = app.config['RESEARCH']
    state['progress_digest'] = {'enabled': True}
    current = progress_digest.collect(state)
    doc = {'revision': 1, 'fingerprint': current['fingerprint'], 'team': {'done': []},
           'members': [], 'directions': [], 'sources': []}
    (team / 'progress-digest.json').write_text(json.dumps(doc), encoding='utf8')
    live = client.get('/api/progress-digest').json
    assert live['status']['state'] == 'ready' and live['document']['revision'] == 1
    (notes / 'example.md').write_text('# Example\n\n## 研究问题\n\nUpdated protocol\n', encoding='utf8')
    assert client.get('/api/progress-digest').json['status']['state'] == 'stale'
    review = {'audience': 'team', 'topics': [], 'members': [], 'lab': {}, 'sources': []}
    target = team / 'lab-review.json'
    target.write_text(json.dumps(review), encoding='utf8')
    reviewed = client.get('/api/lab-review?format=json')
    assert reviewed.status_code == 200 and reviewed.json['version'] == 'reviewed'
    assert client.get('/api/lab-review?version=auto').status_code == 404
    review['audience'] = 'internal'
    target.write_text(json.dumps(review), encoding='utf8')
    assert client.get('/api/lab-review?format=json').status_code == 403


def test_private_sharing_stays_closed(env):
    _, app, _ = env
    app.config['RESEARCH'].update(demo=False, security={'team_reports_shared': False})
    for path in ('/api/progress-digest', '/api/lab-review?format=json', '/api/directions', '/api/direction-methods'):
        assert app.test_client().get(path).status_code == 403
