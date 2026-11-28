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
    assert index.text.count('<details class="algorithm-group')==7
    assert index.text.count('class="direction-browser"')==1
    assert '<details class="direction-browser" id="direction-browser">' in index.text
    html=client.get('/direction-methods?direction=example')
    assert '准确率 82%' in html.text and '相同输入及评分协议' in html.text and '待核对' in html.text
    assert '<details class="method"><summary><span class="status status-measured">实测结果</span><span class="method-title">可复核方法</span></summary>' in html.text
    assert html.text.index('<div class="method-body">')>html.text.index('<details class="method"><summary>')
    assert '/progress/api/direction-methods?source=ref-raw' in html.text
    assert client.get('/assets/direction-methods.css').mimetype=='text/css'
    missing=client.get('/direction-methods?q=nothing-matches')
    assert '没有找到' in missing.text and '<details class="direction-browser" id="direction-browser" open>' in missing.text
    found=client.get('/direction-methods?q=可复核方法')
    assert '示例研究方向' in found.text and '<details class="direction-browser" id="direction-browser" open>' in found.text
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


def test_algorithm_core_map_groups_stable_ids_and_leaves_unknowns_pending(atlas):
    from research_weekly.direction_methods import algorithm_core_map

    _,client,path,doc=atlas
    expected=[('representation','表征学习与多模态融合','depalign-final'),
              ('retrieval-memory','检索与长时记忆','audio-memory-retrieval'),
              ('trustworthy-output','可信输出拒答与 OOD','answer-abstention'),
              ('task-intervention','任务建模与受控干预','pause-cognition'),
              ('generation-editing','生成编辑与数据增强','paralinguistic-editing'),
              ('speech-infrastructure','语音工程数据与协作基础设施','speech-annotation')]
    rows=[dict(doc['directions'][0],id=direction_id,title=title) for _,title,direction_id in expected]
    rows.append(dict(doc['directions'][0],id='new-unregistered-id',title='新方向'))
    core=algorithm_core_map(rows)
    assert [(g['id'],len(g['directions']),g['method_count']) for g in core['groups']]==[
        (key,1,1) for key,_,_ in expected]
    assert [row['id'] for row in core['unclassified']]==['new-unregistered-id']
    assert core['unclassified_method_count']==1

    doc['directions']=rows
    path.write_text(json.dumps(doc),encoding='utf8')
    html=client.get('/direction-methods').text
    assert '算法核心地图' in html and '不构成跨任务、指标或数据划分的排名' in html
    for _,title,direction_id in expected:
        assert title in html and f'<code>{direction_id}</code>' in html
    assert '待归类' in html and '<code>new-unregistered-id</code>' in html
    assert html.count('可复核方法')==len(rows)
    assert html.count('<details class="algorithm-group')==len(rows)
    detail=client.get('/direction-methods?direction=depalign-final').text
    assert 'id="algorithm-map"' not in detail and '准确率 82%' in detail
    api=client.get('/api/direction-methods').json
    assert 'core_map' not in api and len(api['directions'])==len(rows)


def test_unmapped_direction_remains_visible_in_core_map_and_index(atlas):
    _,client,_,_=atlas
    html=client.get('/direction-methods').text
    assert '待归类' in html and '<code>example</code>' in html
    assert '这些稳定方向 ID 尚未登记到六类核心地图' in html
    assert '示例研究方向' in html and '可复核方法' in html
