import json

import pytest

from research_weekly import lab_review as review
from research_weekly import lab_review_page, daily_reports
from test_system import env, seed


def test_scanner_coverage_and_scope(tmp_path):
    root = tmp_path / 'hefeng'
    root.mkdir()
    (root/'研究进展.md').write_text('已核对语音结果。', encoding='utf-8')
    excluded = root/'TF-BS-study'
    excluded.mkdir()
    (excluded/'README.md').write_text('excluded')
    (root/'result-note.md').write_text('提到 TF_BS',encoding='utf-8')
    (root/'weekly-secret.txt').write_text('password=test-example')
    (root/'result-big.txt').write_bytes(b'x'*200001)
    (root/'weekly-symlink.md').symlink_to(root/'研究进展.md')
    inputs, scope = review.collect({'members':[{'id':'a'}],'sources':[]},[{'member_id':'a','path':str(root)}])
    assert len(inputs) == 1
    assert scope['disk_roots'][0]['oversized'] == 1
    assert scope['disk_roots'][0]['excluded'] == 3
    with pytest.raises(ValueError,match='重叠'):
        review.collect({'members':[{'id':'a'}],'sources':[]},[{'member_id':'a','path':str(root)}]*2)


def test_grounded_only_exact_and_owned():
    sources={'weekly:a:W01':{'member_id':'a','content':'规模小，未稳定。'}}
    row={'text':'待复验','evidence':[{'id':'weekly:a:W01','quote':'未稳定'}]}
    assert review.grounded([row],sources,'a') == [row]
    with pytest.raises(ValueError):
        review.grounded([row],sources,'b')
    row['evidence'][0]['quote']='已经稳定'
    with pytest.raises(ValueError):
        review.grounded([row],sources)


def test_imported_project_excludes_directory_and_body_independently():
    note = dict(kind='project_note', workspace_member_id='a', title='周会记录', content='整理了语音任务的指标。')
    rows = [
        dict(note, id='s1', path='/data/users/hefeng/projects/ＴＦ－ＢＳ/phase/work.md'),
        dict(note, id='s2', path='/data/users/hefeng/projects/review/work.md', content='TF_BS 研究。'),
        dict(note, id='s3', path='/data/users/hefeng/projects/audio/work.md'),
    ]
    inputs, scope = review.collect({'members':[{'id':'a'}], 'sources':rows}, [])
    assert list(inputs) == ['s3'] and scope['imported_project_notes'] == 1


def test_explicit_project_files_and_directory_ownership(tmp_path):
    base = tmp_path / '项目'
    base.mkdir()
    (base / '里程碑.md').write_text('项目记录了指标。', encoding='utf-8')
    (base / 'README.md').write_text('旁边的记录。', encoding='utf-8')
    selected = {'member_id':'a', 'path':str(base), 'include_files':['里程碑.md']}
    bundle = {'members':[{'id':'a'}], 'sources':[]}
    inputs, scope = review.collect(bundle, [selected])
    note, = inputs.values()
    assert note['member_id'] is None and note['workspace_member_id'] == 'a'
    assert note['content'] == '项目记录了指标。' and scope['disk_roots'][0]['candidate'] == 1
    (base / '链接.md').symlink_to(base / 'README.md')
    for invalid in (['../README.md'], ['里程碑.md']*2, ['链接.md'], ['absent.md'], 'README.md', ['C:/README.md']):
        with pytest.raises(ValueError):
            review.collect(bundle, [{**selected,'include_files':invalid}])


def test_direction_must_be_named_in_topic_evidence():
    direction = {'id':'depalign-final','title':'DepAlign 抑郁程度预测'}
    def proof(quote):
        ref = {'id':'daily:a:2026-11-21','quote':quote}
        return review.direction_evidence(direction, [ref])
    assert proof('已在 DAIC 与 MMPsy 上比较二分类模型。') is None
    assert proof('参考 DepAlign 抑郁程度预测 的基线。') is None
    assert proof('已在 depalign-final 完成验证集复核。')['id'].startswith('daily:')


def test_direction_anchor_can_identify_another_sentence_in_same_original(monkeypatch):
    direction={'id':'universal-voice-encoder','title':'通用疾病声音 Encoder'}
    sources={'a':dict(id='a',kind='daily',member_id='p',title='日报',content='和远超讨论了语音通用encoder的方案。正在进一步核对损失曲线。'),
             'b':dict(id='b',kind='daily',member_id='p',title='次日',content='另一项分类工作仍在收集数据。')}
    def reply(settings,instruction,data):
        fields={f:[] for f in review.FIELDS}
        def item(k):
            return {'text':'本轮记录了实施进展。','evidence':[k]}
        if isinstance(data,list):
            return {**fields,'progress':[item('E2'),item('E3')]}
        anchors=data['directions'][0]['named_in']
        assert list(anchors)==['E1']
        return {'lab':fields,'topics':[dict(**{**fields,'progress':[item(k)]},title='研究主题',direction_id=direction['id'],direction_anchor='E1') for k in ('E2','E3')]}
    monkeypatch.setattr(review,'ask',reply)
    topics=review.generate(sources,{'members':[{'id':'p','name':'甲'}],'directions':[direction]}, {})['topics']
    assert topics[0]['direction_evidence']['id']=='a' and topics[0]['direction_id']==direction['id']
    assert topics[1]['direction_id'] is None


def test_future_work_baseline_and_ranking_provenance():
    source = [{'quote':'训练参考三种基线，已达到成员登记的公开目标数值。'}]
    for assertion in ('成功复现三种基线', '取得公开第一'):
        with pytest.raises(ValueError):
            review.claim_role('result', assertion, source, ['result'])
    assert review.claim_role('result','成员测量值超过登记目标；评估协议待核对。', source, ['result'])
    assert review.claim_role('result','已复现基线。',[{'quote':'复现并检查了基线。'}],['progress'])
    with pytest.raises(ValueError):
        review.claim_role('progress', '完成重跑。', [{'quote':'计划重跑'}], ['next'])
    assert review.claim_role('next', '核对设置。', source, ['result'])['text'].startswith('建议')
    assert review.claim_role('next', '核对设置。', [{'quote':'核对设置。'}], ['next'])['basis'] == 'reported_plan'


def test_project_only_sources_reach_lab_but_never_member(monkeypatch):
    bundle={'members':[{'id':'a','name':'甲'}], 'directions':[]}
    source={'n':dict(id='n',kind='project_note',member_id=None,workspace_member_id='a',title='项目',content='项目生成了数据字典。')}
    def reply(settings,instruction,data):
        item={'text':'项目生成了数据字典。','evidence':['E1']}
        fields={key:[] for key in review.FIELDS}
        row={**fields,'progress':[item]}
        if isinstance(data, list):
            return row
        assert data['members'][0]['progress'] == [] and data['project_records']['progress']
        return {'lab':row,'topics':[dict(title='字典', direction_id=None, **row)]}
    monkeypatch.setattr(review, 'ask', reply)
    result=review.generate(source,bundle,{})
    assert result['members'][0]['progress'] == []
    assert result['project_records']['progress'][0]['evidence'][0]['id'] == 'n'
    page=lab_review_page.render(dict(**result,sources=[source['n']],scope={},generated_at='now'))
    assert '其中 0 人有本期署名报告' in page and 'id="projects"' in page


def test_all_dates_and_reader_access(env):
    cfg, app, config = env
    seed(cfg, week='2023-W01')
    bundle=review.server_reports(config)
    assert [row['id'] for row in bundle['sources']] == ['weekly:alice:2023-W01']
    assert bundle['source_window']['from'] == '2023-01-02'
    sample={'text':'边界 <JS>','evidence':[{'id':bundle['sources'][0]['id'],'quote':'原文'}]}
    fields={key:[] for key in review.FIELDS}
    doc=dict(engine='test', generated_at='2026-11-21',scope={'disk_roots':[{'root':'/private-test-path'}]},
             sources=bundle['sources'],members=[{'name':'甲','id':'alice',**fields}],topics=[],
             lab={**fields,'progress':[sample]})
    c=app.test_client()
    assert c.get('/api/lab-review').status_code == 404
    review.save(cfg['roots']['team']/'lab-review.json',doc)
    assert c.get('/api/progress-digest').json['has_lab_review'] is True
    html=c.get('/api/lab-review').text
    assert '边界 &lt;JS&gt;' in html and '/private-test-path' not in html
    assert 'rmp.wuwangwo.top/progress/#team?' in html
    cfg['demo']=False
    cfg['security']['team_reports_shared']=False
    assert not daily_reports.team_sharing_enabled(cfg)
    assert c.get('/api/lab-review').status_code == 403
    assert c.get('/api/progress-digest').json['has_lab_review'] is False


def test_shared_reader_refuses_internal_project_quotes(env):
    cfg, app, _=env
    dest=cfg['roots']['team']/'lab-review.json'
    c=app.test_client()
    for doc in ({'audience':'internal','sources':[]},
                {'sources':[{'kind':'project_note','audience':'internal'}]},
                {'sources':[{'kind':'project_note'}]}):
        dest.write_text(json.dumps(doc),encoding='utf-8')
        assert c.get('/api/lab-review').status_code==403
        assert c.get('/api/progress-digest').json['has_lab_review'] is False


def test_untrusted_original_link_does_not_leave_platform():
    src=dict(id='n1',kind='project_note',title='<unsafe>',url='https://example.org/',member_id='x')
    point=dict(text='<tag>',evidence=[dict(id='n1',quote='<script>')])
    fields=dict.fromkeys(review.FIELDS,[])
    doc=dict(lab={**fields,'progress':[point]},topics=[],members=[],scope={},sources=[src],generated_at='now')
    html=lab_review_page.render(doc)
    assert 'https://example.org/' not in html
    assert '&lt;unsafe&gt;' in html and '&lt;script&gt;' in html and '<script>' not in html


def test_pyramid_guide_counts_levels_and_preserves_evidence_links():
    fields=dict.fromkeys(review.FIELDS,[])
    point=dict(text='已完成同条件核对。',evidence=[dict(id='daily:a:2026-11-21',quote='同条件核对。')])
    src=dict(id='daily:a:2026-11-21',kind='daily',member_id='a',title='甲的日报',quote='同条件核对。')
    doc=dict(lab={**fields,'progress':[point]},
             topics=[{'title':'验证主题','direction_id':None,**fields,'progress':[point]}],
             members=[dict(id='a',name='甲',**fields),dict(id='b',name='乙',**fields)],
             scope={},sources=[src],generated_at='now')
    html=lab_review_page.render(doc,companion='auto')
    assert '三级金字塔导读' in html and 'class="guide-heading"' in html
    assert html.count('class="pyramid-')==3
    assert 'class="section-intro"' not in html
    assert '1 条四栏判断' in html
    assert '1 个主题 · 1 条结论联系' in html
    assert '1 / 2 人有署名报告 · 1 条主题联系' in html
    assert 'href="#lab"' in html and 'href="#topics"' in html and 'href="#people"' in html
    assert '同段引文见' in html and '引用署名报告' in html and '本人报告被以下问题引用' in html
    assert '核对出处' in html and '<blockquote>同条件核对。</blockquote>' in html
    assert '阅读新材料的自动复盘' in html
    for title in ('本期进展','结果与证据','局限与阻塞','下一步'):
        assert title in html


def test_weekly_refresh_reuses_authorization_and_preserves_previous(env,monkeypatch):
    cfg, _, _ = env
    assert review.weekly_review(cfg) == 'disabled'
    cfg['progress_digest'] = {'enabled':True}
    cfg['lab_review'] = {'weekly':True}
    cfg['summary'].update(model='test',api_base='https://example.test',allow_remote_progress=False)
    seed(cfg)
    with pytest.raises(ValueError,match='本机模型处理'):
        review.weekly_review(cfg)
    assert not (cfg['roots']['team']/'lab-review.json').exists()
    calls=[]
    def selected(inputs,bundle,settings):
        calls.append(len(inputs))
        assert settings['allow_remote_progress'] is False
        return dict(lab={},topics=[],members=[])
    monkeypatch.setattr(review,'generate',selected)
    assert review.weekly_review(cfg) == 'updated'
    dest=cfg['roots']['team']/'lab-review.json'
    old=dest.read_bytes()
    assert review.weekly_review(cfg) == 'unchanged' and calls == [1]
    seed(cfg,week='2025-W01')
    def failed(*args):
        raise ValueError('model unavailable')
    monkeypatch.setattr(review,'generate',failed)
    with pytest.raises(ValueError,match='model unavailable'):
        review.weekly_review(cfg)
    assert dest.read_bytes()==old
    monkeypatch.setattr(review,'generate',selected)
    assert review.weekly_review(cfg) == 'updated'
    archives=list((cfg['roots']['state']/'lab-review-history').glob('*.json'))
    assert len(archives)==1 and json.loads(archives[0].read_bytes())==json.loads(old)


def test_optional_review_failure_preserves_normal_weekly_success(env, monkeypatch, capsys):
    import sys
    from research_weekly import cli
    cfg, _, config = env
    cfg['lab_review'] = {'weekly':True}
    monkeypatch.setattr(cli,'load_config',lambda _:cfg)
    monkeypatch.setattr(cli.summaries,'summarize',lambda *args:({'week':'2026-W45','revision':2,'engine_label':'test'}, True))
    def failed(_):
        raise ValueError('private provider message')
    monkeypatch.setattr(review,'weekly_review',failed)
    monkeypatch.setattr(sys,'argv',['cli','--config',str(config),'summarize','--week','previous'])
    assert cli.main() == 0
    printed=capsys.readouterr()
    assert '2026-W45' in printed.out and 'failed' in printed.err and 'private provider' not in printed.err


def test_human_review_preserved_with_distinct_automatic_edition(env,monkeypatch):
    cfg,app,config=env
    cfg['progress_digest']={'enabled':True}
    cfg['lab_review']={'weekly':True}
    cfg['summary'].update(model='test',api_base='http://localhost',allow_remote_progress=False)
    seed(cfg)
    bundle=review.server_reports(config)
    inputs,scope=review.collect(bundle,[])
    fields={f:[] for f in review.FIELDS}
    result={'lab':fields,'topics':[],'members':[{**m,**fields} for m in bundle['members']]}
    approved={**review.material(bundle,inputs,scope),**result,'generated_at':'2026-11-21','editorial_review':{'reviewed_at':'2026-11-21'}}
    primary=cfg['roots']['team']/'lab-review.json'
    review.save(primary,approved)
    original=primary.read_bytes()
    calls=[]
    def regenerate(*args):
        calls.append(1)
        return result
    monkeypatch.setattr(review,'generate',regenerate)
    assert review.weekly_review(cfg)=='reviewed_unchanged' and not calls
    seed(cfg,week='2025-W01')
    assert review.weekly_review(cfg)=='auto_update_alongside_review'
    assert review.weekly_review(cfg)=='unchanged' and calls==[1]
    assert primary.read_bytes()==original
    c=app.test_client()
    assert '阅读新材料的自动复盘' in c.get('/api/lab-review').text
    assert '返回人工校审稿' in c.get('/api/lab-review?version=auto').text
    auto=primary.with_name('lab-review-auto.json')
    candidate=json.loads(auto.read_bytes())
    candidate['evidence_corrections']={'input_basis':review.evidence_basis(candidate,review.server_reports(config))}
    auto.write_text(json.dumps(candidate),encoding='utf-8')
    corrected=auto.read_bytes()
    monkeypatch.setattr(review,'REVIEW_RULE_VERSION',review.REVIEW_RULE_VERSION+1)
    assert review.weekly_review(cfg)=='unchanged' and auto.read_bytes()==corrected and calls==[1]
    seed(cfg,week='2025-W02')
    assert review.weekly_review(cfg)=='auto_update_alongside_review' and calls==[1,1]
    assert auto.read_bytes()!=corrected and primary.read_bytes()==original
    approved['editorial_review']['reviewed_at']='2026-11-22'
    primary.write_text(json.dumps(approved),encoding='utf-8')
    assert c.get('/api/lab-review?version=auto').status_code==404


@pytest.mark.parametrize('field,text,quotes,sections,error',[
    ('next','成员已复核 T13 逐折配置。',['复核 T13 逐折配置。','五折 AUROC 提升。'],['next','result'],'完成复核'),
    ('limit','四路比较均不显著。',['四路注入未见稳定提升。'],['limit'],'统计显著'),
    ('limit','模型将所有人分到最低档。',['模型基本把所有人都分到最低档。'],['limit'],'限定'),
    ('result','MCQ 分数不可直接采信。',['构造的拒答例子的测试说明：MCQ 分数不可直接采信。'],['result'],'样例'),
])
def test_claim_cannot_strengthen_original_scope(field,text,quotes,sections,error):
    with pytest.raises(ValueError,match=error):
        review.claim_role(field,text,[{'quote':q} for q in quotes],sections)


def test_measurements_and_plans_keep_their_original_scope():
    role=lambda field,text,quote,section:review.claim_role(field,text,[{'quote':quote}],[section])
    assert role('result','已复核逐折配置。','已完成逐折配置复核。','result')['text']=='已复核逐折配置。'
    assert role('limit','8项比较未达到统计显著。','8项校正比较未达到统计显著。','limit')['text']
    assert role('limit','几乎所有人分到最低档。','模型基本把所有人都分到最低档。','limit')['text']
    assert role('result','在成员构造的样例中，MCQ 有局限。','构造的拒答例子显示 MCQ 有局限。','result')['text']
    assert role('next','周会需决定实验顺序。','先验证三个组件。','next')['basis']=='model_suggestion'
    assert role('next','周会讨论验证顺序。','周会将讨论验证顺序。','next')['basis']=='reported_plan'
    assert role('next','训练完成后冻结检查点。','仍等待六组训练完成，然后冻结检查点。','')['basis']=='reported_plan'


def test_review_processing_plan_and_provider_accounting(monkeypatch):
    from research_weekly import model_api
    import io
    bundle={'members':[{'id':'a','name':'甲'}],'directions':[]}
    s={'a':dict(id='a',member_id='a',kind='daily',title='日报',content='测试。')}
    assert review.material(bundle,s,{})['processing_plan']==dict(source_characters=3,extraction_batches=1,
                   requests_first_pass=2,requests_with_all_validation_retries=6)
    fields={f:[] for f in review.FIELDS}
    row={'text':'报告测试。','evidence':['E1']}
    fields['progress']=[row]
    results=iter([fields,{'lab':fields,'topics':[dict(**fields,title='测试',direction_id=None)]}])
    class Opener:
        def open(self,*args,**kwargs):
            content=json.dumps(next(results))
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':content}}],
                 'usage':{'prompt_tokens':11,'completion_tokens':5,'total_tokens':16,'private_details':'omit'}}).encode())
    monkeypatch.setattr(model_api.urllib.request,'build_opener',lambda *handlers:Opener())
    usage=review.generate(s,bundle,dict(model='test',api_base='http://localhost',timeout_seconds=2))['model_usage']
    assert usage['requests']==usage['responses_with_usage']==2
    assert usage['provider_token_subtotals']=={'prompt_tokens':22,'completion_tokens':10,'total_tokens':32}


def test_validated_extract_cache_reuses_other_member_after_evidence_renumbering(tmp_path,monkeypatch):
    bundle={'members':[{'id':'aa','name':'甲'},{'id':'bb','name':'乙'}],'directions':[]}
    sources={uid:dict(id=uid,member_id=uid,kind='daily',title='记录',content=content) for uid,content in [('aa','工作一。'),('bb','工作二。')]}
    calls=[]
    def reply(settings,instruction,data):
        fields={f:[] for f in review.FIELDS}
        if isinstance(data,list):
            calls.append(data[0]['id'])
            key=next(iter(data[0]['excerpts']))
            fields['progress']=[{'text':'原件记录了工作。','evidence':[key]}]
            return fields
        refs=data['members'][1]['progress'][0]['evidence']
        assert data['evidence'][refs[0]]['id']=='bb' and data['evidence'][refs[0]]['quote']=='工作二。'
        calls.append('lab')
        return {'lab':fields,'topics':[dict(**fields,title='工作',direction_id=None)]}
    monkeypatch.setattr(review,'ask',reply)
    cfg={'_cache_dir':tmp_path}
    assert review.generate(sources,bundle,cfg)['model_usage']['requests']==3
    sources['aa']['content']='新记录。工作一。'
    calls.clear()
    usage=review.generate(sources,bundle,cfg)['model_usage']
    assert calls==['aa','lab'] and usage['reused_extraction_batches']==1 and usage['requests']==2


def test_private_offline_bundle_requires_configured_model(tmp_path,monkeypatch):
    import sys
    src=tmp_path/'internal.json'
    src.write_text(json.dumps({'members':[{'id':'aa','name':'甲'}],'directions':[],
          'sources':[{'id':'n','kind':'project_note','workspace_member_id':'aa','title':'项目','content':'本次归档。'}]}),encoding='utf-8')
    dest=tmp_path/'out.json'
    monkeypatch.setattr(sys,'argv',['review',str(src),'--output',str(dest)])
    with pytest.raises(SystemExit) as err:
        review.main()
    assert err.value.code==2 and not dest.exists()
    model=tmp_path/'model.json'
    model.write_text(json.dumps({'progress_digest':{'enabled':True,'model':'custom'},'summary':{'allow_remote_progress':False,'model':'base'}}))
    def selected(inputs,bundle,settings):
        assert settings['model']=='custom' and settings['allow_remote_progress'] is False
        return {}
    monkeypatch.setattr(review,'generate',selected)
    monkeypatch.setattr(sys,'argv',['review',str(src),'--model-config',str(model),'--output',str(dest)])
    review.main()
    assert json.loads(dest.read_bytes())['audience']=='internal'


def test_report_updated_during_generation_keeps_last_snapshot(env,monkeypatch):
    cfg,_,_=env
    cfg['progress_digest']={'enabled':True}
    cfg['lab_review']={'weekly':True}
    cfg['summary'].update(model='local',api_base='http://localhost')
    seed(cfg)
    def changed(*_):
        seed(cfg,week='2024-W23')
        return dict(lab={},members=[],topics=[])
    monkeypatch.setattr(review,'generate',changed)
    with pytest.raises(ValueError,match='输入发生变化'):
        review.weekly_review(cfg)
    assert not (cfg['roots']['team']/'lab-review.json').exists()
