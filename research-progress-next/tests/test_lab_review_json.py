import json

import pytest

from research_weekly.lab_review import revision
from test_system import env


@pytest.fixture
def editions(env):
    cfg,app,_=env
    uid='m_0123456789abcdef1234'
    source_id=f'daily:{uid}:2026-11-16'
    note_id='note:'+'b'*24
    link=f'https://rmp.wuwangwo.top/progress/#team?week=2026-W47&member={uid}&date=2026-11-16'
    empty={k:[] for k in ('progress','result','limit','next')}
    person={'id':uid,'name':'测试成员','email':'hidden@example.org',**empty}
    note={'text':'项目更新。','evidence':[{'id':note_id,'quote':'共享摘录。','path':'/data/users/hidden'}]}
    report={'text':'结果详见 https://external.example/secret。','evidence':[
        {'id':source_id,'quote':'外部原文可查 https://external.example/secret'},
        {'id':source_id,'quote':'住址：/home/hidden/work'}]}
    primary={'audience':'team','generated_at':'2026-11-21T00:00:00+00:00','editorial_review':{'editor':'hidden@example.org'},
             'members':[person],'topics':[{'title':'主题','direction_id':None,**empty}],
             'lab':{**empty,'result':[report]},'sources':[
                 {'id':source_id,'kind':'daily','title':'成员日报','member_id':uid,'date':'2026-11-16','url':link}],
             'scope':{},'raw_model_response':'PRIVATE_OBJECT'}
    automatic={k:v for k,v in primary.items() if k!='editorial_review'}
    automatic.update(based_on_review=revision(primary),
                     evidence_corrections={'claim_count':18,'internal_note':'PRIVATE_OBJECT'},
                     project_records={**empty,'progress':[note]},
                     sources=primary['sources']+[{'kind':'project_note','audience':'team','id':note_id,
                                                  'title':'共享摘录','workspace_member_id':'hidden-login',
                                                  'path':'/data/users/hidden','url':'https://external.example/private'}])
    paths=[cfg['roots']['team']/name for name in ('lab-review.json','lab-review-auto.json')]
    for path,doc in zip(paths,[primary,automatic]):
        path.write_text(json.dumps(doc),encoding='utf8')
    return cfg,app.test_client(),paths,primary,automatic


def test_member_json_is_a_whitelist_with_the_same_versions(editions):
    _,client,_,_,_=editions
    assert client.get('/api/lab-review').mimetype=='text/html'
    assert client.get('/api/lab-review?format=html').mimetype=='text/html'
    reviewed=client.get('/api/lab-review?format=json').json
    assert reviewed['edition']=='human_reviewed' and reviewed['available_versions']==['reviewed','auto']
    assert reviewed['corrected_claim_count']==0
    response=client.get('/api/lab-review?version=auto&format=json')
    data=response.json
    assert response.mimetype=='application/json' and response.headers['Cache-Control']=='no-store'
    assert data['version']=='auto' and data['edition']=='model_generated' and data['corrected_claim_count']==18
    assert all(set(group)>={'progress','result','limit','next'} for group in [data['lab'],*data['members'],*data['topics'],data['project_records']])
    assert data['sources'][0]['original_url'].endswith('&date=2026-11-16') and 'original_url' not in data['sources'][1]
    claim=data['lab']['result'][0]
    assert claim['text_redacted'] and claim['evidence'][0]['quote_excerpt']=='外部原文可查'
    assert claim['evidence'][1]['quote'] is None and claim['evidence'][1]['quote_withheld']
    assert data['project_records']['progress'][0]['evidence'][0]['source_id']==data['sources'][1]['id']
    for secret in ('hidden','external.example','PRIVATE_OBJECT','/data/','/home/','workspace_member_id','raw_model_response'):
        assert secret not in response.text


def test_formats_access_and_stale_editions_follow_existing_route(editions):
    cfg,client,paths,primary,automatic=editions
    for query in ('format=xml','format=json&format=xml','format='):
        assert client.get('/api/lab-review?'+query).status_code==400
    assert client.get('/api/lab-review?format=json&version=private').status_code==404
    automatic['based_on_review']='stale'
    paths[1].write_text(json.dumps(automatic),encoding='utf8')
    assert client.get('/api/lab-review?format=json&version=auto').status_code==404
    assert client.get('/api/lab-review?format=json').json['available_versions']==['reviewed']
    primary['audience']='internal'
    paths[0].write_text(json.dumps(primary),encoding='utf8')
    for query in ('format=json','format=html'):
        assert client.get('/api/lab-review?'+query).status_code==403
    primary['audience']='team'
    paths[0].write_text(json.dumps(primary),encoding='utf8')
    cfg['demo']=False
    cfg['security']['team_reports_shared']=False
    # No separate machine credentials: both formats use the same sharing decision.
    client.application.config['RESEARCH'].update(demo=False)
    client.application.config['RESEARCH']['security']['team_reports_shared']=False
    assert client.get('/api/lab-review?format=json').status_code==403


def test_untrusted_urls_and_identifiers_are_never_exported(editions):
    _,client,paths,primary,_=editions
    primary['sources'][0]['url']='https://rmp.wuwangwo.top/progress/#team?week=x&email=hidden@example.org'
    paths[0].write_text(json.dumps(primary),encoding='utf8')
    assert 'original_url' not in client.get('/api/lab-review?format=json').json['sources'][0]
    primary['sources'][0]['id']='hidden-login@example.org'
    paths[0].write_text(json.dumps(primary),encoding='utf8')
    response=client.get('/api/lab-review?format=json')
    assert response.status_code==400 and 'hidden' not in response.text


def test_cross_level_navigation_requires_the_exact_passage_and_signed_authorship(editions):
    _, client, paths, _, doc = editions
    uid = doc['members'][0]['id']
    signed, project = [source['id'] for source in doc['sources']]
    doc['sources'][1]['workspace_member_id'] = uid
    empty = {key: [] for key in ('progress', 'result', 'limit', 'next')}

    def cited(source, quote):
        return {'text': '有出处的阶段判断。', 'evidence': [{'id': source, 'quote': quote}]}

    measured = cited(signed, '已完成对照。')
    proposal = {**cited(project, '后续可复核。'), 'basis':'model_suggestion'}
    doc.update(topics=[
        {'title':'有署名依据', **empty, 'result':[measured]},
        {'title':'仅由项目记录支持', **empty, 'next':[proposal]},
    ], lab={**empty, 'result':[measured, cited(project, '已完成对照。'), cited(signed, '另一段观察。')], 'next':[proposal]})
    paths[1].write_text(json.dumps(doc), encoding='utf8')
    endpoint = '/api/lab-review?version=auto'
    out = client.get(endpoint+'&format=json').json
    first, second = out['topics']
    assert first['report_member_ids'] == [uid] and second['report_member_ids'] == []
    assert out['members'][0]['cited_in_topic_keys'] == [first['key']]
    assert [item['related_topic_keys'] for item in out['lab']['result']] == [[first['key']], [], []]
    assert out['lab']['next'][0]['related_topic_keys'] == [second['key']]
    html = client.get(endpoint).text
    for anchor in [first['key'], second['key'], 'member-'+uid]:
        assert html.count(f'id="{anchor}"') == 1 and f'href="#{anchor}"' in html
    assert '复盘建议' in html and '周报 0 · 日报 1' in html
    doc['topics'].reverse()
    paths[1].write_text(json.dumps(doc), encoding='utf8')
    assert client.get(endpoint+'&format=json').json['topics'][1]['key'] == first['key']
