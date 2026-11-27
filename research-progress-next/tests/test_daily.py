"""Temporary files only: registration -> daily/weekly HTTP -> restart -> summary."""
import datetime as dt
import io
import json
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
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


def daily_with_attachments(client, files, *, text=None, share='true'):
    data = MultiDict([('member_id', 'alice'), ('date', DAY), ('team_visible', share)])
    if text is None:
        data.add('fields', json.dumps(FIELDS))
    else:
        data.add('file', (io.BytesIO(text.encode()), 'daily.md'))
    for filename, contents in files:
        data.add('attachments', (io.BytesIO(contents), filename))
    return client.post('/api/daily/uploads', data=data, headers=HEADERS)


def test_daily_attachment_bundle_and_team_visibility(env, monkeypatch):
    cfg, app, path = env
    client = app.test_client()
    member = core.member(cfg, 'alice')
    files = [('图表.png', b'private-png'), ('metrics.csv', b'x,y\n1,2')]
    assert daily_reports.read_for_team(cfg, member, DAY) is None
    result = daily_with_attachments(client, files)
    assert result.status_code == 201
    assert result.json['team_visible'] is True and result.json['attachment_count'] == 2
    bundle = cfg['roots']['members'] / 'alice' / 'daily' / DAY
    assert (bundle / 'attachment-1').read_bytes() == files[1][1]
    assert (bundle / 'attachment-2').read_bytes() == files[0][1]
    client = create_app(path).test_client()
    text = daily_reports.markdown(member['name'], DAY, FIELDS)
    duplicate = daily_with_attachments(client, reversed(files), text=text)
    assert duplicate.status_code == 200 and duplicate.json['duplicate']
    assert duplicate.json['sha256'] == result.json['sha256']
    assert daily_with_attachments(client, [('metrics.csv', b'new')]).status_code == 409
    assert daily_with_attachments(client, files, share='false').status_code == 200
    assert client.get(f'/data/members/alice/daily/{DAY}/attachment-1').status_code == 404
    assert daily_reports.read_for_team(cfg, member, DAY) == {'date': DAY, 'fields': FIELDS, 'attachment_count': 2}
    with monkeypatch.context() as patch:
        def unexpected_read(*args):
            raise AssertionError('status-only checks must not parse the Markdown')
        patch.setattr(daily_reports, 'parse_report', unexpected_read)
        assert daily_reports.read_for_team(cfg, member, DAY, include_fields=False) == {
            'date': DAY, 'fields': None, 'attachment_count': 0,
        }
    cfg['demo'] = False
    assert daily_reports.read_for_team(cfg, member, DAY)['fields'] is None


def test_daily_sharing_opt_in_and_legacy_contract(env):
    cfg, app, _ = env
    cfg['demo'] = False
    member = core.member(cfg, 'alice')
    client = app.test_client()
    private = {'date': DAY, 'fields': None, 'attachment_count': 0}
    body = {'member_id': 'alice', 'date': DAY, 'fields': FIELDS, 'team_visible': True}
    assert client.get('/api/public').json['daily_team_sharing'] is False
    assert client.post('/api/daily/uploads', json=body, headers=HEADERS).status_code == 403
    assert daily_with_attachments(client, [('metrics.csv', b'x')]).status_code == 403
    assert daily(client).status_code == 201
    assert daily_reports.read_for_team(cfg, member, DAY) == private
    cfg['security']['team_reports_shared'] = True
    assert client.get('/api/public').json['daily_team_sharing'] is True
    assert client.post('/api/daily/uploads', json=body, headers=HEADERS).status_code == 200
    assert daily_reports.read_for_team(cfg, member, DAY) == {'date': DAY, 'fields': FIELDS, 'attachment_count': 0}


def test_old_private_bundles_auto_share_only_text_and_count(env):
    cfg, app, _ = env
    client = app.test_client()
    files = [('notes.txt', b'private'), ('log.txt', b'private')]
    cfg['demo'] = False
    assert daily_with_attachments(client, files, share='false').status_code == 201
    assert daily_reports.read_for_team(cfg, core.member(cfg, 'alice'), DAY) == {
        'date': DAY, 'fields': None, 'attachment_count': 0,
    }
    cfg['security']['team_reports_shared'] = True
    assert daily_reports.read_for_team(cfg, core.member(cfg, 'alice'), DAY) == {
        'date': DAY, 'fields': FIELDS, 'attachment_count': 2,
    }


def docx_with_text(*lines):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as doc:
        text = ''.join(f'<w:p><w:r><w:t>{line}</w:t></w:r></w:p>' for line in lines)
        doc.writestr('word/document.xml',
                     '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                     f'<w:body>{text}</w:body></w:document>')
    return output.getvalue()


def pdf_with_text():
    output = io.BytesIO()
    pdf = PdfWriter()
    page = pdf.add_blank_page(width=200, height=100)
    name = NameObject
    page[name('/Resources')] = DictionaryObject({name('/Font'): DictionaryObject({
        name('/F1'): DictionaryObject({name('/Type'): name('/Font'),
                                       name('/Subtype'): name('/Type1'),
                                       name('/BaseFont'): name('/Helvetica')}),
    })})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 50 Td (MAE = 4, protocol v2) Tj ET')
    page.replace_contents(stream)
    pdf.write(output)
    return output.getvalue()


@pytest.mark.parametrize(('filename', 'content', 'expected'), [
    ('report.txt', '今日完成：完成去重\n结果与证据\n已跑通基线'.encode(), ('完成去重', '已跑通基线')),
    ('results.csv', '指标,数值\nMAE,4'.encode(), ('指标,数值\nMAE,4', '未说明')),
    ('report.docx', docx_with_text('今日完成', '完成表格核验', '结果与证据', '原始文件另存'), ('完成表格核验', '原始文件另存')),
    ('report.pdf', pdf_with_text(), ('MAE = 4, protocol v2', '未说明')),
])
def test_daily_report_import_keeps_original_and_extracts_fields(env, filename, content, expected):
    cfg, app, path = env
    client = app.test_client()
    first = file_daily(client, content, filename=filename)
    assert first.status_code == 201
    assert first.json['team_visible'] is True and first.json['attachment_count'] == 0
    client = create_app(path).test_client()
    assert file_daily(client, content, filename=filename).status_code == 200
    bundle = cfg['roots']['members'] / 'alice' / 'daily' / DAY
    assert (bundle / 'original').read_bytes() == content
    row = daily_reports.read_for_team(cfg, core.member(cfg, 'alice'), DAY)
    assert row == {'date': DAY, 'fields': dict(zip(FIELDS, (*expected, '未说明', '未说明'))),
                   'attachment_count': 0, 'imported_body': True}
    assert client.get(f'/data/members/alice/daily/{DAY}/original').status_code == 404


def test_daily_file_import_rejects_empty_unparseable_or_oversized_files(env):
    cfg, app, _ = env
    client = app.test_client()
    blank_pdf = io.BytesIO()
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    pdf.write(blank_pdf)
    assert file_daily(client, blank_pdf.getvalue(), filename='scan.pdf').status_code == 400
    assert file_daily(client, b'bad pdf', filename='bad.pdf').status_code == 400
    assert file_daily(client, b'bad doc', filename='bad.docx').status_code == 400
    assert file_daily(client, b'photo', filename='photo.jpg').status_code == 415
    assert file_daily(client, b'\xff', filename='bad.txt').status_code == 400
    cfg['summary']['max_upload_bytes'] = 10
    data = MultiDict([('member_id', 'alice'), ('date', DAY), ('file', (io.BytesIO(b'xx'), 'daily.txt')),
                      ('attachments', (io.BytesIO(b'y' * 9), 'figure.txt'))])
    assert client.post('/api/daily/uploads', data=data, headers=HEADERS).status_code == 413
    assert not (cfg['roots']['members'] / 'alice' / 'daily').exists()


def test_invalid_daily_attachments_leave_no_report_and_can_retry(env, monkeypatch):
    cfg, app, _ = env
    client = app.test_client()
    cfg['summary']['max_upload_bytes'] = 10
    assert daily_with_attachments(client, [('../outside', b'a')]).status_code == 400
    assert daily_with_attachments(client, [('a.txt', b'')]).status_code == 400
    assert daily_with_attachments(client, [('x.txt', b'a'), ('X.txt', b'b')]).status_code == 400
    assert daily_with_attachments(client, [('a.bin', b'123456'), ('b.bin', b'123456')]).status_code == 413
    assert daily_with_attachments(client, [(f'{i}.txt', b'a') for i in range(9)]).status_code == 413
    root = cfg['roots']['members'] / 'alice' / 'daily'
    assert not root.exists()
    files = [('a.bin', b'1'), ('b.bin', b'2')]
    with monkeypatch.context() as patch:
        def fail(*args):
            raise OSError('test interruption')
        patch.setattr(daily_reports, 'write_json', fail)
        assert daily_with_attachments(client, files).status_code == 500
    assert list(root.iterdir()) == []
    assert daily_with_attachments(client, files).status_code == 201


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
