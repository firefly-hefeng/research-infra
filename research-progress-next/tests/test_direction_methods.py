import json
import pytest

from test_system import env


@pytest.fixture
def atlas(env):
    cfg,app,_=env
    path=cfg['roots']['team']/'direction-methods.json'
    digest='c'*64
    pub='ref-raw'
    doc={'schema_version':1,'as_of':'2026-11-22','audience':'team',
         'sources':[{'id':pub,'origin_id':'metric:'+digest,'kind':'aggregate_record',
                     'title':'核定样例的汇总结果','url':None,'quote':'相同条件 82%；样例统计。','fingerprint':digest,
                     'private_path':'/data/private/example'}],
         'directions':[{'id':'example','title':'示例研究方向','question':'这组方法可在何种条件比较？',
                       'summary':'当前已有一组同条件对照。','registered_direction_id':None,
                       'owner':{'status':'unconfirmed','name':None,'source_ids':[]},
                       'contributors':[], 'next_step':'扩大验证。','source_ids':[pub],
                       'methods':[{'name':'可复核方法','status':'measured','result':'样本内有改善。',
                                   'metric':'准确率 82%','comparison':'相同输入及评分协议。','scope':'仅限该项样例。','source_ids':[pub]}]}]}
    path.write_text(json.dumps(doc),encoding='utf8')
    return app,app.test_client(),path,doc


def test_readable_direction_and_original(atlas):
    _,client,_,_=atlas
    index=client.get('/direction-methods')
    assert index.status_code==200 and '示例研究方向' in index.text
    html=client.get('/direction-methods?direction=example')
    assert '准确率 82%' in html.text and '相同输入及评分协议' in html.text and '待核对' in html.text
    assert '/progress/api/direction-methods?source=ref-raw' in html.text
    assert client.get('/assets/direction-methods.css').mimetype=='text/css'
    assert '没有找到' in client.get('/direction-methods?q=nothing-matches').text
    assert '示例研究方向' in client.get('/direction-methods?q=可复核方法').text
    data=client.get('/api/direction-methods?direction=example').json
    assert len(data['directions'])==len(data['sources'])==1
    source=client.get('/api/direction-methods?source=ref-raw').json['source']
    assert source['fingerprint']=='c'*64 and 'private_path' not in source
    assert client.get('/api/direction-methods?direction=missing').status_code==404
    assert client.get('/api/direction-methods?source=missing').status_code==404
    assert client.get('/api/direction-methods?source=ref-raw&direction=example').status_code==400


def test_no_records_and_sharing(atlas):
    app,client,path,_=atlas
    path.unlink()
    result=client.get('/api/direction-methods').json
    assert result['status']=='not_published' and result['as_of'] is None and result['directions']==[]
    assert '索引尚未发布' in client.get('/direction-methods').text
    app.config['RESEARCH'].update(demo=False,security={'team_reports_shared':False})
    for url in ('/direction-methods','/api/direction-methods','/api/direction-methods?source=ref-raw'):
        assert client.get(url).status_code==403


def test_invalid_sources_fail_closed(atlas):
    _,client,path,doc=atlas
    doc['sources'][0]['url']='https://unverified.example/report'
    path.write_text(json.dumps(doc),encoding='utf8')
    assert client.get('/api/direction-methods').status_code==503
    doc['sources'][0]['url']=None
    doc['directions'][0]['methods'][0]['source_ids']=['missing']
    path.write_text(json.dumps(doc),encoding='utf8')
    assert client.get('/direction-methods').status_code==503


def test_suggested_and_unassigned_are_distinct_from_confirmed(atlas):
    _,client,path,doc=atlas
    owner=doc['directions'][0]['owner']
    owner.update(status='suggested',name='示例研究者',source_ids=['ref-raw'])
    path.write_text(json.dumps(doc),encoding='utf8')
    assert '建议负责人 · 示例研究者（待确认）' in client.get('/direction-methods').text
    owner.update(status='unassigned',name=None,source_ids=[])
    path.write_text(json.dumps(doc),encoding='utf8')
    assert '负责人待指派' in client.get('/direction-methods?direction=example').text
