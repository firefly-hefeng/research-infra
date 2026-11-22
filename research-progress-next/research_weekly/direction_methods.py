"""Read-only, evidence-linked index of team research methods."""
from datetime import date
from functools import lru_cache
import json
import re
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from .core import ID, PROJECT, child
from .daily_reports import team_sharing_enabled
from .lab_review_json import public_text

blueprint = Blueprint('direction_methods', __name__, template_folder=str(PROJECT / 'web'))
STATUS = {'measured':'实测结果', 'reported':'报告记录', 'planned':'计划验证', 'asset':'资料准备'}
KINDS = {'daily':'原始日报', 'weekly':'原始周报', 'project_note':'共享项目摘录', 'direction_document':'方向文档',
         'aggregate_record':'聚合记录'}
GROUPS = {'research':'研究方向', 'research_support':'研究支持', 'collaboration':'协作机制'}


def check(ok):
    if not ok:
        raise ValueError('方向方法索引未通过来源校验')


def string(value, optional=False):
    if optional and (value is None or value == ''):
        return ''
    check(isinstance(value,str) and bool(value.strip()) and public_text(value) is not None)
    return value


def ids(value):
    check(isinstance(value,list) and all(isinstance(i,str) and i for i in value)
          and len(set(value)) == len(value))
    return list(value)


def source_address(value):
    if not value:
        return None
    check(isinstance(value,str) and not any(c in value for c in ('\\','\r','\n','\t')))
    url=urlsplit(value)
    check((not url.scheme and not url.netloc) or (url.scheme=='https' and url.netloc=='rmp.wuwangwo.top'))
    check(url.path.startswith('/progress/') and not any(p in ('.','..') for p in url.path.split('/')))
    return value


def export_document(raw):
    check(isinstance(raw,dict) and raw.get('schema_version')==1 and raw.get('audience')=='team' and
          isinstance(raw.get('sources'),list) and isinstance(raw.get('directions'),list))
    date.fromisoformat(raw['as_of'])
    sources={}
    for row in raw['sources']:
        key=string(row['id'])
        check(re.fullmatch(r'[A-Za-z0-9:_-]{1,120}',key) and key not in sources and row['kind'] in KINDS)
        sources[key]=dict(id=key, kind=row['kind'], title=string(row['title']), url=source_address(row.get('url')),
                          quote=string(row['quote']), origin_id=string(row['origin_id']))
        if row['kind']=='aggregate_record':
            digest=row['fingerprint']
            check(isinstance(digest,str) and re.fullmatch(r'[a-f0-9]{64}',digest) and row['origin_id']=='metric:'+digest)
            sources[key].update(fingerprint=digest,url='/progress/api/direction-methods?source='+key)
        if row.get('member_id'):
            check(row['kind'] in ('daily','weekly') and ID.fullmatch(row['member_id']))
            sources[key]['member_id']=row['member_id']

    def refs(values, required=True):
        values=ids(values)
        check((values or not required) and all(v in sources for v in values))
        return values

    directions=[]
    seen=set()
    for row in raw['directions']:
        key=row['id']
        check(isinstance(key,str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}',key) and key not in seen)
        seen.add(key)
        formal=row.get('registered_direction_id')
        check(formal is None or isinstance(formal,str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}',formal))
        owner=row['owner']
        check(owner['status'] in ('confirmed','suggested','unassigned','unconfirmed'))
        named=owner['status'] in ('confirmed','suggested')
        check(named or not owner.get('name'))
        owner=dict(status=owner['status'],name=string(owner['name']) if named else None,
                   source_ids=refs(owner['source_ids'],required=named))
        people=[]
        for p in row['contributors']:
            uid=p['member_id']
            check(isinstance(uid,str) and ID.fullmatch(uid))
            people.append(dict(name=string(p['name']),member_id=uid,source_ids=refs(p['source_ids'])))
        contacts=[]
        for p in row.get('verification_contacts',[]):
            uid=p['member_id']
            check(isinstance(uid,str) and ID.fullmatch(uid) and p['basis'] in ('署名报告','项目空间'))
            contacts.append(dict(name=string(p['name']),member_id=uid,basis=p['basis'],source_ids=refs(p['source_ids'])))
        methods=[]
        for m in row['methods']:
            check(m['status'] in STATUS)
            method={f:string(m.get(f),optional=f in ('metric','comparison','scope')) for f in ('name','result','metric','comparison','scope')}
            methods.append({**method,'status':m['status'],'source_ids':refs(m['source_ids'])})
        kind=row.get('kind','research')
        check(kind in GROUPS)
        directions.append(dict(id=key,kind=kind,title=string(row['title']),question=string(row['question']),
            summary=string(row['summary']),registered_direction_id=formal,owner=owner,contributors=people,methods=methods,
            next_step=string(row.get('next_step'),optional=True),next_step_basis=string(row.get('next_step_basis'),optional=True),
            verification_contacts=contacts,source_ids=refs(row['source_ids'],required=False)))
    return dict(schema_version=1,status='published',as_of=raw['as_of'],audience='team',directions=directions,sources=list(sources.values()))


@lru_cache(maxsize=2)
def read_version(path, inode, modified, size):
    check(size <= 2_000_000)
    return export_document(json.loads(path.read_bytes()))


def read():
    cfg=current_app.config['RESEARCH']
    if not team_sharing_enabled(cfg):
        abort(403,'团队共享尚未启用')
    try:
        path=child(cfg['roots']['team'],'direction-methods.json')
        stat=path.stat()
        return read_version(path,stat.st_ino,stat.st_mtime_ns,stat.st_size)
    except FileNotFoundError:
        return dict(schema_version=1,status='not_published',as_of=None,audience='team',directions=[],sources=[])
    except (KeyError,TypeError,ValueError,OSError):
        abort(503,'方向方法索引读取失败，请稍后重试')


def references(row):
    groups=[row,row['owner'],*row['contributors'],*row['methods'],*row['verification_contacts']]
    return {key for group in groups for key in group['source_ids']}


def coverage(directions,sources):
    return {'directions':len(directions),'methods':sum(len(d['methods']) for d in directions),
            'cited_passages':len(sources),'cited_originals':len({s['origin_id'] for s in sources})}


def selected(doc):
    key=request.args.get('direction','')
    if not key or doc['status']=='not_published':
        return None
    for row in doc['directions']:
        if row['id']==key:
            return row
    abort(404,'未找到这个研究方向')


@blueprint.get('/api/direction-methods')
def direction_methods_api():
    doc=read()
    if 'source' in request.args:
        if 'direction' in request.args:
            abort(400,'请分别按方向或来源读取')
        sid=request.args['source']
        for source in doc['sources']:
            if source['id']==sid:
                return jsonify({k:doc[k] for k in ('schema_version','status','as_of','audience')} | {'source':source})
        abort(404,'未找到该来源')
    row=selected(doc)
    if row:
        cited=references(row)
        doc={**doc,'directions':[row],'sources':[s for s in doc['sources'] if s['id'] in cited]}
    return jsonify({**doc,'coverage':coverage(doc['directions'],doc['sources'])})


@blueprint.get('/direction-methods')
def direction_methods_page():
    doc=read()
    row=selected(doc)
    query=request.args.get('q','').strip()
    if len(query)>120:
        abort(400,'检索词过长')
    listed=doc['directions']
    if query:
        needle=query.casefold()
        listed=[d for d in listed if any(needle in t.casefold() for t in
                 [d['title'],d['question'],d['summary'],*(m['name'] for m in d['methods']),*(p['name'] for p in d['contributors'])])]
    return render_template('direction-methods.html',doc=doc,selected=row,directions=listed,query=query,
                           counts=coverage(doc['directions'],doc['sources']),
                           source_by_id={s['id']:s for s in doc['sources']},statuses=STATUS,kinds=KINDS,groups=GROUPS)
