"""Temporary files only: registration -> daily/weekly HTTP -> restart -> summary."""
import datetime as dt
import io
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import pytest
from werkzeug.datastructures import MultiDict
from research_weekly import core, daily_reports, summaries
from research_weekly.app import create_app
from research_weekly.members import registered_members
from test_system import env, HEADERS, FIELDS, upload

DAY = '2026-10-28'


def daily(c, uid='alice', fields=None, day=DAY):
    return c.post('/api/daily/uploads', json={'member_id':uid,'date':day,'fields':FIELDS if fields is None else fields}, headers=HEADERS)


def file_daily(c, text, uid='alice', filename='daily.md'):
    content = text.encode() if isinstance(text,str) else text
    return c.post('/api/daily/uploads',data={'member_id':uid,'date':DAY,'file':(io.BytesIO(content),filename)},headers=HEADERS)


def test_registration_daily_weekly_restart_and_summary(env):
    cfg, app, path = env
    c=app.test_client(); before=path.read_bytes()
    joined=c.post('/api/members',json={'name':' 新同学（语音组） '},headers=HEADERS)
    assert joined.status_code==201
    m=joined.json['member']; assert m['name']=='新同学(语音组)' and core.ID.fullmatch(m['id'])
    assert (cfg['roots']['members']/m['id']).is_dir()
    assert path.read_bytes()==before # Registration never edits service configuration.
    assert m in c.get('/api/public').json['members']
    t=c.get('/api/daily-template',query_string={'member_id':m['id'],'date':DAY})
    assert t.status_code==200 and '今日完成' in t.json['markdown'] and '明日计划' in t.json['markdown']
    assert daily(c,uid=m['id']).status_code==201
    stored=cfg['roots']['members']/m['id']/'daily'/f'{DAY}.md'
    assert stored.read_text()==daily_reports.markdown(m['name'],DAY,FIELDS)
    # Daily intake is durable, distinct from weekly inputs and survives restart.
    c=create_app(path).test_client()
    assert m in c.get('/api/public').json['members']
    repeated=file_daily(c,stored.read_text(),uid=m['id'])
    assert repeated.status_code==200 and repeated.json['duplicate']
    assert daily(c,uid=m['id'],fields={**FIELDS,'done':'changed'}).status_code==409
    manifest=summaries.collect(core.load_config(path),'2026-W44')
    assert manifest['reports']==[] and m in manifest['missing']
    assert upload(c,uid=m['id'],week='2026-W44').status_code==201
    assert len(summaries.collect(core.load_config(path),'2026-W44')['reports'])==1
    assert stored.read_text()==daily_reports.markdown(m['name'],DAY,FIELDS)
    for endpoint in ['/api/daily','/api/daily/'+DAY,'/api/members/'+m['id'],f'/data/members/{m["id"]}/daily/{DAY}.md']:
        assert c.get(endpoint).status_code==404


def test_names_duplicate_boundaries_and_csrf(env):
    cfg,app,_=env;c=app.test_client()
    for value in ['', ' '*4, 'n'*81, 'name\nother', '\x00']:
        assert c.post('/api/members',json={'name':value},headers=HEADERS).status_code==400
    assert c.post('/api/members',json={'name':'甲同学'},headers=HEADERS).status_code==409
    assert c.post('/api/members',json={'name':'A L I C E'},headers=HEADERS).status_code==201
    assert c.post('/api/members',json={'name':'ａ  ｌ ｉ ｃ ｅ'},headers=HEADERS).status_code==409
    assert c.post('/api/members',json={'name':'new','id':'../../x'},headers=HEADERS).status_code==400
    assert c.post('/api/members',json={'name':'new'}).status_code==403
    assert c.post('/api/members',json={'name':'new'},headers={**HEADERS,'Origin':'https://foreign.invalid'}).status_code==403
    assert c.post('/api/members',data='new',headers=HEADERS).status_code==415
    assert not (cfg['roots']['members']/'new').exists()


def test_concurrent_name_registration_is_unique(env):
    cfg,app,_=env
    def submit(_):
        with app.test_client() as c:
            return c.post('/api/members',json={'name':'并行测试'},headers=HEADERS).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit,range(2)))==[201,409]
    assert len([m for m in registered_members(cfg) if m['name']=='并行测试'])==1


@pytest.mark.parametrize('day',['2026-W44','2026-02-30','2026-1-01','../../escape','2026-10-28T12:00:00','２０２６-１０-２８',None,42])
def test_invalid_dates_rejected_before_write(env,day):
    cfg,app,_=env;c=app.test_client()
    assert daily(c,day=day).status_code==400
    assert not (cfg['roots']['members']/'alice/daily').exists()


@pytest.mark.parametrize('mutate',[
    lambda t:t.replace('今日完成','本周完成'),
    lambda t:t.replace(DAY,'2026-10-27'),
    lambda t:t.replace('甲同学','乙同学'),
    lambda t:t.replace('## 结果与证据','## 今日完成'),
    lambda t:t+'\n## 其他\nextra',
    lambda t:t.replace('## 今日完成','extra\n## 今日完成'),
    lambda t:t.replace('数据核对清单已生成',''),
])
def test_strict_daily_markdown(env,mutate):
    cfg,app,_=env
    assert file_daily(app.test_client(),mutate(daily_reports.markdown('甲同学',DAY,FIELDS))).status_code==400
    assert not (cfg['roots']['members']/'alice/daily').exists()


def test_size_encoding_headers_fields_and_file_names(env):
    cfg,app,_=env;c=app.test_client()
    assert file_daily(c,daily_reports.template('甲同学',DAY)).status_code==400
    assert file_daily(c,b'\xff\xfe').status_code==400
    assert file_daily(c,b'x'*65537).status_code==413
    assert file_daily(c,'text',filename='../../escape.md').status_code==400
    assert daily(c,fields={'done':'only'}).status_code==400
    assert daily(c,fields={**FIELDS,'done':'## injected'}).status_code==400
    assert daily(c,fields=dict.fromkeys(FIELDS,'中'*12000)).status_code==413
    body={'member_id':'alice','date':DAY,'fields':FIELDS}
    assert c.post('/api/daily/uploads',json=body).status_code==403
    assert c.post('/api/daily/uploads',json=body,headers={**HEADERS,'Origin':'https://foreign.invalid'}).status_code==403
    assert c.post('/api/daily/uploads',data='x',headers=HEADERS).status_code==415
    assert c.post('/api/daily/uploads',json={**body,'week':'2026-W44'},headers=HEADERS).status_code==400
    duplicate=MultiDict([('member_id','alice'),('member_id','bob'),('date',DAY),('file',(io.BytesIO(b'x'),'daily.md'))])
    assert c.post('/api/daily/uploads',data=duplicate,headers=HEADERS).status_code==400


def test_missing_member_symlink_and_unknown_id(env,tmp_path):
    cfg,app,path=env;c=app.test_client()
    assert daily(c,uid='../escape').status_code==400
    assert daily(c,uid='unknown').status_code==403
    shutil.rmtree(cfg['roots']['members']/'alice')
    assert daily(create_app(path).test_client()).status_code==403
    assert not (cfg['roots']['members']/'alice').exists()
    outside=tmp_path/'outside';outside.mkdir()
    (cfg['roots']['members']/'alice').symlink_to(outside,target_is_directory=True)
    assert daily(c).status_code==400
    assert list(outside.iterdir())==[]


def test_daily_subdir_and_roster_symlinks_rejected(env,tmp_path):
    cfg,app,_=env;c=app.test_client()
    outside=tmp_path/'outside';outside.mkdir()
    (cfg['roots']['members']/'alice/daily').symlink_to(outside,target_is_directory=True)
    assert daily(c).status_code==400 and list(outside.iterdir())==[]
    secret=tmp_path/'secret.json';secret.write_text('{}')
    (cfg['roots']['state']/'members.json').symlink_to(secret)
    assert c.post('/api/members',json={'name':'new'},headers=HEADERS).status_code==400
    assert secret.read_text()=='{}'


def test_calendar_date_timezone_and_browser_contract(env,monkeypatch):
    cfg,app,_=env;c=app.test_client()
    import importlib
    module=importlib.import_module('research_weekly.app')
    monkeypatch.setattr(module,'now',lambda _:dt.datetime(2027,1,1,0,10,tzinfo=core.ZoneInfo('Asia/Shanghai')))
    data=c.get('/api/public').json
    assert data['date']=='2027-01-01' and data['week']=='2026-W53'
    assert data['registration_enabled'] and data['daily_enabled']
    ids=[]
    class IDs(HTMLParser):
        def handle_starttag(self,tag,attrs):
            ids.extend(value for key,value in attrs if key=='id')
    html=c.get('/').text;IDs().feed(html)
    assert len(ids)==len(set(ids))
    assert {'daily-form','daily-member','daily-date','daily-submit','registration-form'} <= set(ids)
    assert 'type="date"' in html and '不会自动生成周报' in html
    js=c.get('/assets/app.js').text
    assert "api('/api/daily/uploads',options)" in js
    assert "api('/api/members'" in js and "path.replace(/^\\//, '')" in js
