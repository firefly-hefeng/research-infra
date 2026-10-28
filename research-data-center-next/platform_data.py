"""Public, read-only projections for compute snapshots and source references."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SERVERS = (
    {'id': 'server-47', 'name': '科研服务器 47', 'address': '47.117.138.84'},
    {'id': 'server-101', 'name': '科研服务器 101', 'address': '101.132.97.146'},
    {'id': 'server-139', 'name': '科研服务器 139', 'address': '139.196.25.53'},
)
MOUNTS = {'/', '/data', '/data/share', '/data/share_cold'}
STALE_SECONDS = 300


def now():
    return dt.datetime.now(dt.timezone.utc)


def stamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value if parsed.tzinfo else None
    except ValueError:
        return None


def plain(value, length=200):
    return value[:length] if isinstance(value, str) and not any(ord(c) < 32 for c in value) else None


def number(value, maximum=None, integer=False):
    if type(value) not in (int, float):
        return None
    try:
        if not math.isfinite(value) or value < 0 or maximum is not None and value > maximum:
            return None
    except OverflowError:
        return None
    return int(value) if integer and int(value) == value else None if integer else value


def metrics(raw):
    raw = raw if isinstance(raw, dict) else {}
    cpu = raw.get('cpu') if isinstance(raw.get('cpu'), dict) else {}
    memory = raw.get('memory') if isinstance(raw.get('memory'), dict) else {}
    result = {'cpu': {'model': plain(cpu.get('model')), 'logical_cores': number(cpu.get('logical_cores'), 100000, True),
                      'usage_percent': number(cpu.get('usage_percent'), 100), 'load_1m': number(cpu.get('load_1m'))},
              'memory': {'total_bytes': number(memory.get('total_bytes'), integer=True),
                         'available_bytes': number(memory.get('available_bytes'), integer=True),
                         'used_percent': number(memory.get('used_percent'), 100)}, 'gpus': None, 'disks': [], 'errors': []}
    if isinstance(raw.get('gpus'), list):
        result['gpus'] = []
        for gpu in raw['gpus'][:64]:
            if not isinstance(gpu, dict) or number(gpu.get('index'), 1024, True) is None:
                continue
            result['gpus'].append({'index': int(gpu['index']), 'name': plain(gpu.get('name')),
                'memory_total_bytes': number(gpu.get('memory_total_bytes'), integer=True),
                'memory_used_bytes': number(gpu.get('memory_used_bytes'), integer=True),
                'utilization_percent': number(gpu.get('utilization_percent'), 100),
                'temperature_c': number(gpu.get('temperature_c'), 150)})
    for row in raw.get('disks', []) if isinstance(raw.get('disks'), list) else []:
        if not isinstance(row, dict) or row.get('mount') not in MOUNTS:
            continue
        object_storage = row.get('filesystem') in ('fuse.ossfs', 'ossfs')
        result['disks'].append({'mount': row['mount'], 'filesystem': plain(row.get('filesystem'), 40),
            'total_bytes': None if object_storage else number(row.get('total_bytes'), integer=True),
            'available_bytes': None if object_storage else number(row.get('available_bytes'), integer=True),
            'used_percent': None if object_storage else number(row.get('used_percent'), 100),
            'capacity_note': 'object_storage_capacity_not_applicable' if object_storage else None})
    for row in raw.get('errors', []) if isinstance(raw.get('errors'), list) else []:
        if isinstance(row, dict) and row.get('component') in ('cpu', 'memory', 'gpu', 'disk'):
            code = row.get('code')
            if isinstance(code, str) and re.fullmatch('[a-z_]{1,64}', code):
                result['errors'].append({'component': row['component'], 'code': code})
    return result


def public_server(raw, definition, at=None):
    at = at or now()
    raw = raw if isinstance(raw, dict) else {}
    observed = stamp(raw.get('observed_at'))
    age = (at - dt.datetime.fromisoformat(observed.replace('Z', '+00:00'))).total_seconds() if observed else None
    status = raw.get('status') if raw.get('status') in ('online', 'partial', 'unreachable') else 'not_configured'
    code = raw.get('error_code')
    code = code if code in ('timeout', 'authentication_failed', 'host_key_unknown', 'host_key_mismatch',
                           'connection_failed', 'probe_failed', 'invalid_probe', 'credentials_not_configured',
                           'transport_unavailable') else None
    return {**definition, 'status': status, 'observed_at': observed, 'attempted_at': stamp(raw.get('attempted_at')),
            'remote_observed_at': stamp(raw.get('remote_observed_at')),
            'last_success_at': observed, 'age_seconds': max(0, round(age)) if age is not None else None,
            'stale': age is None or age < -60 or age > STALE_SECONDS or status == 'unreachable',
            'error_code': code, **metrics(raw)}


def read_public_json(root, relative, max_bytes=16 * 1024 * 1024):
    root = Path(root).resolve()
    path = root / relative
    if not path.exists():
        return None
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or path.is_symlink() or not resolved.is_file() or resolved.stat().st_size > max_bytes:
        raise ValueError('invalid_public_metadata_path')
    value = json.loads(resolved.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('public_metadata_must_be_object')
    return value


def servers_snapshot(root, at=None):
    at = at or now()
    raw = read_public_json(root, 'data/server-resources.json')
    if raw is not None and (raw.get('schema_version') != '1.0' or not isinstance(raw.get('servers'), list)):
        raise ValueError('invalid_server_snapshot')
    rows = {row.get('id'): row for row in (raw or {}).get('servers', []) if isinstance(row, dict)}
    return {'schema_version': '1.0', 'mode': 'snapshot' if raw else 'not_configured',
            'generated_at': stamp((raw or {}).get('generated_at')), 'served_at': at.isoformat(),
            'stale_after_seconds': STALE_SECONDS,
            'servers': [public_server(rows.get(server['id']), server, at) for server in SERVERS],
            'notes': ['只读中央快照；刷新页面不会连接服务器。',
                      'GPU 利用率是采样瞬时值，不代表空闲、预约或独占；不采集进程与命令行。',
                      '失联时保留上次成功观察并显示时间；挂载容量可能由多机共享，不能跨机器相加。']}


def safe_url(value):
    if not isinstance(value, str) or len(value) > 3000 or any(ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            return None
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if any(key.lower() in ('password', 'token', 'access_token', 'secret', 'signature', 'api_key') for key, _ in query):
            return None
        query = [(key, val) for key, val in query if not key.lower().startswith('utm_')]
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', urlencode(query), ''))
    except ValueError:
        return None


def literature_index(root):
    root = Path(root)
    catalog = read_public_json(root, 'data/catalog.json') or {}
    mapping = read_public_json(root, 'data/resource-mapping.json') or {}
    guide = read_public_json(root, 'data/research-guide.json') or {}
    assets = {row['id']: row for row in catalog.get('assets', []) if isinstance(row, dict) and isinstance(row.get('id'), str)}
    mapped = {row['asset_id']: row for row in mapping.get('items', []) if isinstance(row, dict) and isinstance(row.get('asset_id'), str)}
    categories, membership = {}, {}
    for row in guide.get('categories', []):
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            continue
        label = plain(row.get('label') or row.get('title')) or row['id']
        categories[row['id']] = {'id': row['id'], 'label': label}
        for aid in row.get('asset_ids', []):
            membership.setdefault(aid, []).append(categories[row['id']])
    references, annotation_files = {}, []
    directory = root / 'data/annotations'
    if directory.exists() and (directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve())):
        raise ValueError('invalid_annotation_directory')
    paths = sorted(directory.glob('*.json')) if directory.exists() else []
    if len(paths) > 50:
        raise ValueError('too_many_annotation_files')
    for path in paths:
        annotation = read_public_json(root, path.relative_to(root).as_posix())
        entries = (annotation or {}).get('entries')
        if not isinstance(entries, dict):
            raise ValueError('invalid_annotation_entries')
        annotation_files.append(path.name)
        for aid, entry in entries.items():
            if aid not in assets or not isinstance(entry, dict):
                continue
            asset, item = assets[aid], mapped.get(aid, {})
            card = item.get('card_url')
            card = card if isinstance(card, str) and re.fullmatch(r'/docs/cards/[A-Za-z0-9._-]+\.html', card) else None
            uses = [text for value in entry.get('research_uses', []) if (text := plain(value, 500))][:5]
            resource = {'asset_id': aid, 'name': plain(asset.get('name')) or aid, 'kind': asset.get('kind'),
                        'card_url': card, 'uses': uses}
            for source in entry.get('sources', []):
                if not isinstance(source, dict):
                    continue
                url = safe_url(source.get('url'))
                if not url:
                    continue
                document = references.setdefault(url, {'id': 'ref-' + hashlib.sha256(url.encode()).hexdigest()[:20],
                    'title': plain(source.get('title') or source.get('label'), 400) or urlsplit(url).hostname,
                    'url': url, 'domain': urlsplit(url).hostname, 'categories': {}, 'resources': {},
                    'source_kind': 'existing_reference', 'annotation_files': set()})
                document['resources'][aid] = resource
                for category in membership.get(aid, []):
                    document['categories'][category['id']] = category
                document['annotation_files'].add(path.name)
    items = []
    for row in references.values():
        items.append({**row, 'categories': list(row['categories'].values()),
                      'resources': sorted(row['resources'].values(), key=lambda x: x['name'].casefold()),
                      'annotation_files': sorted(row['annotation_files'])})
    items.sort(key=lambda row: (row['title'].casefold(), row['url']))
    return items, annotation_files


def literature(root, q='', category='', domain='', asset_id='', page=1, page_size=24):
    if (type(page) is not int or not 1 <= page <= 1000000 or type(page_size) is not int or not 1 <= page_size <= 100
            or any(not isinstance(value, str) or len(value) > 300 for value in (q, category, domain, asset_id))):
        raise ValueError('invalid_literature_query')
    items, files = literature_index(root)
    categories, domains = {}, {}
    for row in items:
        domains[row['domain']] = domains.get(row['domain'], 0) + 1
        for cat in row['categories']:
            categories.setdefault(cat['id'], {**cat, 'count': 0})['count'] += 1
    tokens = q.casefold().split()
    def matches(row):
        if category and category not in {item['id'] for item in row['categories']}:
            return False
        if domain and row['domain'] != domain.casefold():
            return False
        if asset_id and asset_id not in {item['asset_id'] for item in row['resources']}:
            return False
        haystack = json.dumps([row['title'], row['url'], row['categories'], row['resources']], ensure_ascii=False).casefold()
        return all(token in haystack for token in tokens)
    matched = [row for row in items if matches(row)]
    start = (page - 1) * page_size
    return {'schema_version': '1.0', 'total': len(matched), 'page': page, 'page_size': page_size,
            'items': matched[start:start + page_size], 'categories': sorted(categories.values(), key=lambda row: row['label']),
            'domains': [{'domain': key, 'count': domains[key]} for key in sorted(domains)],
            'coverage': {'resources': len({resource['asset_id'] for row in items for resource in row['resources']}),
                         'references': len(items), 'annotation_files': files},
            'capabilities': {'personal_reading_progress': False, 'full_text_library': False},
            'note': '现有资源说明中的真实来源引用库，包含官方资料、模型说明与论文链接；不是个人阅读进度或全文管理平台。'}
