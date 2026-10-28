"""Name-only registration; directories are generated, never chosen by clients."""
import json
import unicodedata
import uuid
from .core import ID, atomic_write, child, locked, now, read_text


class NameExists(ValueError):
    pass


def clean_name(value):
    if not isinstance(value, str) or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('请填写姓名，不包含控制字符')
    value = ' '.join(unicodedata.normalize('NFKC', value).split())
    if not value or len(value) > 80:
        raise ValueError('姓名须为 1–80 个字符；重名时请附加组别等区分信息')
    return value


def name_key(value):
    return clean_name(value).casefold()


def registered_members(cfg):
    """Read the latest roster for both long-running HTTP and CLI summaries."""
    result = [dict(m) for m in cfg['members']]
    path = child(cfg['roots']['state'], 'members.json')
    if not path.exists():
        return result
    doc = json.loads(read_text(path, 1_000_000))
    if not isinstance(doc, dict) or doc.get('version') != 1 or not isinstance(doc.get('members'), list):
        raise ValueError('成员登记文件无效，请联系维护人员')
    ids = {m['id'] for m in result}
    names = {name_key(m['name']) for m in result}
    for m in doc['members']:
        if (not isinstance(m, dict) or set(m) != {'id', 'name', 'created_at'}
                or not isinstance(m['id'], str) or not ID.fullmatch(m['id'])
                or not isinstance(m['created_at'], str)):
            raise ValueError('成员登记记录无效，请联系维护人员')
        key = name_key(m['name'])
        if m['id'] in ids or key in names:
            raise ValueError('成员登记存在重复，请联系维护人员')
        ids.add(m['id']); names.add(key)
        result.append({'id': m['id'], 'name': m['name']})
    return result


def register(cfg, value):
    name = clean_name(value)
    with locked(cfg):
        members = registered_members(cfg)
        if any(name_key(m['name']) == name_key(name) for m in members):
            raise NameExists('该姓名已登记。若确为你的登记，请在成员列表选择；若是同名同学，请增加组别等区分信息后登记。')
        if len(members) >= 1000:
            raise ValueError('成员数量已达上限，请联系维护人员')
        path = child(cfg['roots']['state'], 'members.json')
        doc = json.loads(read_text(path, 1_000_000)) if path.exists() else {'version': 1, 'members': []}
        uid = 'm_' + uuid.uuid4().hex[:20]
        directory = child(cfg['roots']['members'], uid)
        # An unexpected pre-existing path is never claimed, even if empty.
        directory.mkdir(mode=0o700)
        doc['members'].append({'id': uid, 'name': name, 'created_at': now(cfg).isoformat()})
        atomic_write(path, json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
        return {'id': uid, 'name': name}
