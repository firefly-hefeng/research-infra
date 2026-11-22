"""A finite, member-readable projection of a shared research review."""
from datetime import date, datetime
import hashlib
import re

FIELDS = ('progress', 'result', 'limit', 'next')
# Quoted material is verbatim. Withhold the whole field when it contains an operational
# path, an external link or an account, and keep the member's original report address.
RESTRICTED_TEXT = re.compile(
    r'(?:https?|file|ssh|sftp|ftp)://|'
    r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\|(?:^|[\s`"\'（(=：:])~[A-Za-z0-9_-]*/|'
    r'/(?:data|mnt|home|Users|root|tmp|srv|opt|var|etc|private|run/user)/|'
    r'[\w.+-]+@[\w.-]+|\b(?:\d{1,3}\.){3}\d{1,3}\b|'
    r'(?:账号|帐号|用户名|登录名|密码|access[_ -]?token|api[_ -]?key|'
    r'password|user(?:name)?|account|email)\s*[:：=]\s*\S|'
    r'-----BEGIN [^\n]*PRIVATE KEY|\bsk-[A-Za-z0-9_-]{12,}|\bBearer\s+[A-Za-z0-9._-]{12,}',
    re.I,
)
WEB_URL = re.compile(r'https?://[^\s)）<>\]]+', re.I)


def public_text(value):
    if not isinstance(value,str) or not value.strip() or RESTRICTED_TEXT.search(value):
        return None
    return value


def iso_day(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        raise ValueError('复盘来源日期无效')
    return date.fromisoformat(value)


def reading_links(doc):
    """Index exact shared quotations and signed reports within this edition."""
    owners = {s['id']: s['member_id'] for s in doc['sources']
              if s.get('kind') in ('daily', 'weekly') and s.get('member_id')}
    members = [member['id'] for member in doc['members']]
    citations = {}
    topics = []
    used = set()
    for topic in doc['topics']:
        # The title keeps deep links stable when a later build reorders the topics.
        stem = 'topic-' + hashlib.sha256(topic['title'].strip().encode()).hexdigest()[:16]
        key = stem
        suffix = 1
        while key in used:
            suffix += 1
            key = f'{stem}-{suffix}'
        used.add(key)
        signed = set()
        for field in FIELDS:
            for claim in topic.get(field, []):
                for ref in claim['evidence']:
                    if ref['id'] in owners:
                        signed.add(owners[ref['id']])
                    if ref.get('quote'):
                        citations.setdefault((ref['id'], ref['quote']), set()).add(key)
        topics.append({'key': key, 'report_member_ids': [uid for uid in members if uid in signed]})
    related = {}
    for field in FIELDS:
        related[field] = []
        for claim in doc['lab'].get(field, []):
            hits = set()
            for ref in claim['evidence']:
                hits.update(citations.get((ref['id'], ref.get('quote')), ()))
            related[field].append([topic['key'] for topic in topics if topic['key'] in hits])
    return topics, related


def source_index(doc):
    from .core import ID, validate_week, week_id

    roster={member['id'] for member in doc['members']}
    if not all(isinstance(uid,str) and ID.fullmatch(uid) for uid in roster):
        raise ValueError('复盘成员标识无效')
    result={}
    for row in doc['sources']:
        kind=row.get('kind')
        key=row.get('id')
        source={'id':key,'kind':kind,'title':public_text(row.get('title'))}
        if kind=='project_note':
            if row.get('audience')!='team':
                raise PermissionError
            if not isinstance(key,str) or not re.fullmatch(r'note:[0-9a-f]{24}',key):
                raise ValueError('复盘项目来源标识无效')
        elif kind in ('daily','weekly'):
            uid,period=row.get('member_id'),row.get('date')
            if uid not in roster or not isinstance(period,str) or key!=f'{kind}:{uid}:{period}':
                raise ValueError('复盘报告标识与名册或日期不符')
            if kind=='daily':
                week=week_id(iso_day(period))
                query=f'week={week}&member={uid}&date={period}'
            else:
                week=validate_week(period)
                query=f'week={week}&member={uid}&report=weekly'
            canonical='https://rmp.wuwangwo.top/progress/#team?'+query
            source.update(member_id=uid,date=period)
            if row.get('url')==canonical:
                source['original_url']=canonical
        else:
            raise ValueError('复盘包含未知来源类型')
        if key in result:
            raise ValueError('复盘来源标识重复')
        result[key]=source
    return result


def project(doc, version, companion):
    if doc.get('audience','team')!='team':
        raise PermissionError
    sources=source_index(doc)
    topic_links, lab_links = reading_links(doc)

    def reference(ref):
        key=ref.get('id')
        if key not in sources:
            raise ValueError('复盘引文缺少可核对的来源')
        quote=public_text(ref.get('quote'))
        out={'source_id':key,'quote':quote}
        if quote is None:
            out['quote_withheld']=True
            original=ref.get('quote')
            if isinstance(original,str) and WEB_URL.search(original) and not RESTRICTED_TEXT.search(WEB_URL.sub('',original)):
                excerpt=max((part.strip(' \n\t[]()（）。；，：') for part in WEB_URL.split(original)),key=len)
                if len(excerpt)>=4:
                    out['quote_excerpt']=excerpt
        return out

    def fields(obj):
        result={}
        for field in FIELDS:
            items=[]
            for entry in obj.get(field,[]):
                text=public_text(entry.get('text'))
                item={'text':text,'evidence':[reference(ref) for ref in entry['evidence']]}
                if text is None:
                    original=entry.get('text')
                    safe=public_text(WEB_URL.sub('【外链略】',original)) if isinstance(original,str) else None
                    if safe:
                        item.update(text=safe,text_redacted=True)
                    else:
                        item['text_withheld']=True
                if field=='next' and entry.get('basis') in ('reported_plan','model_suggestion'):
                    item['basis']=entry['basis']
                items.append(item)
            result[field]=items
        return result

    topics=[]
    for group, links in zip(doc['topics'], topic_links):
        direction=group.get('direction_id')
        if direction is not None and (not isinstance(direction,str) or not re.fullmatch(r'[a-z0-9_-]{1,100}',direction)):
            raise ValueError('复盘方向标识无效')
        item={'title':public_text(group.get('title')),'direction_id':direction,**links,**fields(group)}
        if group.get('direction_evidence'):
            item['direction_evidence']=reference(group['direction_evidence'])
        topics.append(item)
    count=doc.get('evidence_corrections',{}).get('claim_count')
    count=count if type(count) is int and count>0 else 0
    edition='human_reviewed' if doc.get('editorial_review') else 'model_generated'
    result={'schema_version':1,'version':version,'edition':edition,'corrected_claim_count':count,
            'available_versions':[version]+([companion] if companion else []),
            'lab':fields(doc['lab']),'topics':topics,
            'members':[{'id':m['id'],'name':public_text(m.get('name')),**fields(m)} for m in doc['members']],
            'project_records':fields(doc.get('project_records') or {}),'sources':list(sources.values())}
    for field in FIELDS:
        for claim, keys in zip(result['lab'][field], lab_links[field]):
            claim['related_topic_keys'] = keys
    for member in result['members']:
        member['cited_in_topic_keys'] = [topic['key'] for topic in topics if member['id'] in topic['report_member_ids']]
    window=doc.get('source_window') or {}
    if window.get('from') and window.get('to'):
        result['source_window']={k:iso_day(window[k]).isoformat() for k in ('from','to')}
    timestamp=doc.get('generated_at')
    if isinstance(timestamp,str):
        try:
            result['generated_at']=datetime.fromisoformat(timestamp.replace('Z','+00:00')).isoformat()
        except ValueError:
            pass
    return result
