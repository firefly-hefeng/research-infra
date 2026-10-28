import datetime as dt
import io
import json
import sys
import shutil
import pytest
from research_weekly import core, summaries
from research_weekly.app import create_app
from research_weekly.reports import template

HEADERS={'X-Requested-With':'ResearchWeekly'}
FIELDS={'done':'完成字段检查','results':'数据核对清单已生成','blockers':'设备字段待补充','next':'开展特征验证'}

@pytest.fixture
def env(tmp_path):
    # Fully synthetic fixture: never depend on the server's roster or config.
    raw={'team_name':'测试团队','demo':True,'timezone':'Asia/Shanghai',
         'paths':dict.fromkeys(('members','team','knowledge','state'),'unused'),
         'security':{'allowed_origins':['http://127.0.0.1:8766'],'https':False},
         'summary':{'mode':'extractive','max_report_bytes':65536,
                    'max_total_bytes':1_000_000,'timeout_seconds':15}}
    raw['paths']={k:str(tmp_path/k) for k in raw['paths']}
    raw['members']=[{'id':'alice','name':'甲同学'},{'id':'bob','name':'乙同学'},{'id':'carol','name':'丙同学'}]
    p=tmp_path/'config.json'; p.write_text(json.dumps(raw))
    cfg=core.load_config(p); core.init_dirs(cfg,provision_members=True)
    app=create_app(p); app.testing=True
    return app.config['RESEARCH'], app, p


def seed(cfg,uid='alice',week='2026-W42',text='完成一项真实测试'):
    fields={k:text if k=='done' else '未说明' for k in core.FIELDS}
    core.atomic_write(core.child(cfg['roots']['members'],uid,'reports',week+'.md'),core.report_markdown(core.member(cfg,uid)['name'],week,fields))


def upload(c,uid='alice',fields=None,week='2026-W42'):
    return c.post('/api/uploads',json={'member_id':uid,'week':week,'fields':FIELDS if fields is None else fields},headers=HEADERS)


def file_upload(c,text,uid='alice',week='2026-W42',filename='weekly.md'):
    return c.post('/api/uploads',data={'member_id':uid,'week':week,'file':(io.BytesIO(text.encode() if isinstance(text,str) else text),filename)},headers=HEADERS)


def test_no_login_and_no_original_read_endpoints(env):
    cfg,app,_=env;c=app.test_client();seed(cfg)
    assert c.get('/').status_code==200
    assert 'login-form' not in c.get('/').text
    assert c.get('/api/public').json['members'][0]['id']=='alice'
    assert c.get('/api/team').status_code==200
    assert c.get('/api/knowledge').status_code==200
    for route in ['/api/me','/api/reports','/api/reports/2026-W42?member_id=alice','/api/files','/data/members/alice/reports/2026-W42.md','/.state/auth.sqlite3']:
        assert c.get(route).status_code==404
    assert c.post('/api/login',json={},headers=HEADERS).status_code==404


def test_member_folder_gate_and_no_auto_provision(env):
    cfg,app,p=env
    shutil.rmtree(cfg['roots']['members']/'alice')
    app=create_app(p);c=app.test_client()
    assert not (cfg['roots']['members']/'alice').exists()
    assert upload(c).status_code==403
    assert c.get('/api/report-template?member_id=alice&week=2026-W42').status_code==403
    assert 'alice' not in [x['id'] for x in c.get('/api/public').json['members']]
    assert upload(c,'unknown').status_code==403
    (cfg['roots']['members']/'unknown').mkdir()
    assert upload(c,'unknown').status_code==403 # Roster and directory are both required.
    assert not (cfg['roots']['members']/'alice').exists()


def test_json_multipart_same_contract_and_idempotence(env):
    cfg,app,_=env;c=app.test_client()
    first=upload(c);assert first.status_code==201 and not first.json['duplicate']
    text=core.report_markdown('甲同学','2026-W42',FIELDS)
    assert core.read_text(cfg['roots']['members']/'alice/reports/2026-W42.md')==text
    second=file_upload(c,text); assert second.status_code==200 and second.json['duplicate']
    assert first.json['sha256']==second.json['sha256']
    assert upload(c,fields={**FIELDS,'done':'恶意覆盖'}).status_code==409
    assert core.read_text(cfg['roots']['members']/'alice/reports/2026-W42.md')==text
    bob=file_upload(c,core.report_markdown('乙同学','2026-W42',FIELDS),uid='bob')
    assert bob.status_code==201
    assert len(summaries.collect(cfg,'2026-W42')['reports'])==2


@pytest.mark.parametrize('mutate',[
    lambda t:t.replace('## 结果与证据','## 其他结果'),
    lambda t:t.replace('## 结果与证据','## 本周完成'),
    lambda t:t.replace('数据核对清单已生成',''),
    lambda t:t.replace('甲同学','乙同学'),
    lambda t:t.replace('2026-W42','2026-W41'),
    lambda t:t+'\n## 附件\n隐藏内容',
    lambda t:t.replace('## 本周完成','额外段落\n## 本周完成'),
])
def test_malformed_markdown_rejected(env,mutate):
    cfg,app,_=env
    r=file_upload(app.test_client(),mutate(core.report_markdown('甲同学','2026-W42',FIELDS)))
    assert r.status_code==400
    assert not (cfg['roots']['members']/'alice/reports/2026-W42.md').exists()


def test_templates_json_validation_and_encoding(env):
    cfg,app,_=env;c=app.test_client()
    t=c.get('/api/report-template?member_id=alice&week=2026-W42')
    assert t.status_code==200 and '甲同学 · 2026-W42' in t.json['markdown']
    assert file_upload(c,t.json['markdown']).status_code==400 # Unfilled template.
    assert upload(c,fields={'done':'missing'}).status_code==400
    assert upload(c,fields={**FIELDS,'done':'## 额外栏目\ntext'}).status_code==400
    assert file_upload(c,b'\xff\xfe').status_code==400
    assert file_upload(c,'x',filename='../../team/weekly.md').status_code==400
    assert upload(c,uid='../bob').status_code==400
    assert upload(c,week='2026-W54').status_code==400
    assert file_upload(c,'x'*65537).status_code==413
    assert upload(c,fields={**FIELDS,'done':'x'*12001}).status_code==400


def test_origin_header_shared_readonly_and_symlinks(env,tmp_path):
    cfg,app,_=env;c=app.test_client()
    body={'member_id':'alice','week':'2026-W42','fields':FIELDS}
    assert c.post('/api/uploads',json=body).status_code==403
    assert c.post('/api/uploads',json=body,headers={**HEADERS,'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/uploads',data='x',headers=HEADERS).status_code==415
    for method,path in [('put','/api/team/2026-W42'),('post','/api/knowledge'),('post','/api/summarize')]:
        assert getattr(c,method)(path,json={},headers=HEADERS).status_code in (404,405)
    secret=tmp_path/'secret';secret.mkdir()
    shutil.rmtree(cfg['roots']['members']/'alice')
    (cfg['roots']['members']/'alice').symlink_to(secret,target_is_directory=True)
    assert upload(c).status_code==400
    assert list(secret.iterdir())==[]
    assert c.get('/api/public').status_code==200


def test_publish_readable_sources_not_exposed_and_template_checked(env):
    cfg,app,_=env;seed(cfg);seed(cfg,'bob','2026-W41')
    core.atomic_write(core.child(cfg['roots']['members'],'alice','files','note.md'),'PRIVATE_NOTE')
    m=summaries.collect(cfg,'2026-W42')
    assert [x['id'] for x in m['reports']]==['alice']
    assert 'PRIVATE_NOTE' not in json.dumps(m)
    doc,_=summaries.summarize(cfg,'2026-W42','extractive')
    c=app.test_client();r=c.get('/api/team/2026-W42')
    assert r.status_code==200 and r.json['submitted']==1
    assert 'content' not in r.json['members'][0]
    assert c.get('/api/reports/2026-W42').status_code==404
    core.atomic_write(cfg['roots']['members']/'bob/reports/2026-W42.md','格式错误的直接写入')
    with pytest.raises(ValueError):summaries.collect(cfg,'2026-W42')
def test_idempotence_revision_and_stale_rejection(env):
    cfg,_,_=env;seed(cfg)
    first,_=summaries.summarize(cfg,'2026-W42','extractive')
    second,changed=summaries.summarize(cfg,'2026-W42','extractive')
    assert not changed and second['revision']==1 and second['generated_at']==first['generated_at']
    job,manifest=summaries.prepare(cfg,'2026-W42');result=summaries.extractive(manifest)
    seed(cfg,text='更新后的工作')
    with pytest.raises(ValueError,match='输入发生变化'):summaries.publish(cfg,manifest,result,'agent')
    current=json.loads(core.read_text(cfg['roots']['team']/'weekly/2026-W42.json',2_000_000))
    assert current['revision']==1
    new,changed=summaries.summarize(cfg,'2026-W42','extractive')
    assert changed and new['revision']==2
    assert list((cfg['roots']['state']/'history').glob('*.json'))


def test_invalid_agent_output_and_failed_job_preserve_old(env):
    cfg,_,_=env;seed(cfg);summaries.summarize(cfg,'2026-W42','extractive')
    m=summaries.collect(cfg,'2026-W42');r=summaries.extractive(m)
    r['members'][0]['source_sha256']='invented'
    with pytest.raises(ValueError):summaries.publish(cfg,m,r,'agent')
    r=summaries.extractive(m);r['members']=[]
    with pytest.raises(ValueError):summaries.publish(cfg,m,r,'agent')
    with pytest.raises(ValueError,match='尚未配置'):summaries.summarize(cfg,'2026-W42','agent')
    assert json.loads(core.read_text(cfg['roots']['team']/'weekly/2026-W42.json',2_000_000))['revision']==1
    assert any(json.loads(p.read_text())['status']=='failed' for p in (cfg['roots']['state']/'jobs').glob('*/status.json'))


def test_agent_command_contract(env,tmp_path):
    cfg,_,_=env;seed(cfg)
    fake=tmp_path/'fixture_agent.py'
    fake.write_text('''import json,sys,pathlib
m=json.loads(pathlib.Path('manifest.json').read_text())
r={"week":m["week"],"overview":["测试适配器输出"],"members":[{"id":x["id"],"source_sha256":x["sha256"],"done":["测试内容"],"results":[],"blockers":[],"next":[]} for x in m["reports"]],"team_risks":[],"next_actions":[]}
pathlib.Path(sys.argv[1]).write_text(json.dumps(r))
''')
    cfg['summary']['agent_command']=[sys.executable,str(fake),'{result_file}']
    doc,changed=summaries.summarize(cfg,'2026-W42','agent')
    assert changed and doc['engine']=='agent' and doc['overview']==['测试适配器输出']




def test_week_boundary_and_config_isolation(env,monkeypatch):
    cfg,_,p=env
    monkeypatch.setattr(core,'now',lambda _:dt.datetime(2026,10,19,9,tzinfo=core.ZoneInfo('Asia/Shanghai')))
    assert core.select_week(cfg,'previous')=='2026-W42'
    assert core.date_range('2026-W42')==['2026-10-12','2026-10-18']
    assert core.week_id(dt.date(2027,1,1))=='2026-W53'
    raw=json.loads(p.read_text());raw['paths']['team']=str(cfg['roots']['members']/'public')
    p.write_text(json.dumps(raw))
    with pytest.raises(ValueError,match='不能嵌套'):core.load_config(p)


def test_ssh_transport_and_relative_frontend(env,monkeypatch):
    cfg,app,p=env
    raw=json.loads(p.read_text()); raw['demo']=False
    raw['security'].update(https=False,transport='ssh-tunnel')
    p.write_text(json.dumps(raw));assert core.load_config(p)['security']['transport']=='ssh-tunnel'
    html=app.test_client().get('/').text
    assert 'href="assets/style.css"' in html and 'src="assets/app.js"' in html
    from research_weekly import cli
    monkeypatch.setattr(sys,'argv',['weekly','--config',str(p),'serve','--host','0.0.0.0'])
    assert cli.main()==1
