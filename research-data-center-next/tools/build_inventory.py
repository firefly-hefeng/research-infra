"""Create a persistent, one-record-per-entry inventory from existing public metadata.

No source directory is traversed. Registry IDs are allocated once and persisted;
paths, apparent families and identical storage locations never merge identities.
"""
from __future__ import annotations

import argparse
import collections
import copy
import csv
import hashlib
import html
import json
import pathlib
import re
import sys
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from catalog import csv_safe, validate_document
from tools.path_migration import approved_path as public_path, source_path, catalog_storage
from tools.research_annotations import load_annotations, integrate_research, compact_gaps

ROLE_NAMES = {
    'dataset': '数据资料入口', 'feature': '按特征类型登记的资料记录',
    'annotation': '标注资料记录', 'collection': '资料集合或索引入口',
    'artifact': '研究工件记录', 'model_weights': '发现权重文件的模型目录',
    'directory_collection': '浅层发现的目录集合入口',
}
CSV_FIELDS = ('registry_id', 'asset_id', 'display_name', 'kind', 'subtype', 'group_id',
              'current_path', 'version_state', 'exists', 'access', 'filesystem_owner',
              'maintainer', 'primary_quantity', 'count_unit', 'size_bytes', 'file_count',
              'quantity_observed_at', 'path_observed_at', 'gap_count', 'card_url', 'proposed_path',
              'migration_state', 'legacy_aliases')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def clean_metadata(value):
    """Remove filesystem paths outside scope without mistaking URLs or HTML for paths.

    Values remain untrusted text and are escaped separately when rendered.
    """
    if isinstance(value, str):
        if re.search(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/](?!/)|\\\\', value):
            return ''
        if re.search(r'(?<![\w/])/(?:home|root|mnt|media|srv|opt|tmp|var|etc|proc|sys|workspace|Users|Volumes|private)(?:/|\b)', value):
            return ''
        for match in re.finditer(r'''/data(?:/[^\s<>"'，；。;,|]*)?(?=/|$|\s|[<>"'，；。;,|])''', value):
            if public_path(match.group(0).rstrip(')）]')) is None:
                return ''
        for match in re.finditer(r'''(?:^|[\s("'`=])(/(?!/)[^\s<>"'`，；。;,|]+)''', value):
            if public_path(match.group(1).rstrip(')）]')) is None:
                return ''
        return value
    if isinstance(value, dict):
        return {key: clean_metadata(item) for key, item in value.items() if clean_metadata(key) == key}
    if isinstance(value, list):
        return [clean_metadata(item) for item in value]
    return value


def group_for(asset):
    path = pathlib.PurePosixPath(source_path(asset['path']))
    parts = path.parts
    if asset['kind'] == 'model':
        branch = parts[3] if len(parts) > 3 else 'models'
        if branch not in ('huggingface', 'modelscope'):
            key, label = 'models/direct', '模型 · 公共根直属目录'
        else:
            key, label = 'models/' + branch, '模型 · ' + branch
    elif len(parts) > 5 and parts[3:5] == ('talkbank', 'audio'):
        key, label = 'talkbank/' + parts[5], 'TalkBank / ' + parts[5]
    elif len(parts) > 3 and parts[3] == 'wuwangwo':
        branch = parts[4] if len(parts) > 4 else 'root'
        key, label = 'wuwangwo/' + branch, 'wuwangwo / ' + branch
    elif len(parts) > 3 and parts[3] == 'easystore':
        branch = parts[4] if len(parts) > 4 else 'root'
        family = ('research_platform' if branch == 'research_platform' else
                  'clinical' if branch.startswith('clinical_') else
                  'parlo' if branch.startswith('parlo_') else 'other')
        key = 'easystore/' + family
        label = {'clinical': 'easystore · clinical 命名资料组', 'parlo': 'easystore · parlo 命名资料组',
                 'research_platform': 'easystore / research_platform', 'other': 'easystore · 其他资料入口'}[family]
    else:
        branch = parts[3] if len(parts) > 3 else 'root'
        key, label = 'datasets/' + branch, '数据区 / ' + branch
    return {'id': 'group-' + hashlib.sha256(key.encode()).hexdigest()[:12], 'key': key, 'label': label,
            'description': '按现有路径分支或明确命名前缀导航；组内记录未合并，不据此判定同一逻辑资源。',
            'basis': '逻辑库内相对目录分支或字面命名前缀，迁移保持组键；属于导航分组而非资源身份鉴定'}


def bind_registry(assets, previous, now):
    registry = copy.deepcopy(previous) if previous else {
        'schema_version': '1.0', 'created_at': now, 'entries': {}, 'aliases': {},
        'semantics': '一条来源记录一个登记ID；不是已确认的逻辑资源ID。重建不按路径哈希生成登记ID。',
    }
    if registry.get('schema_version') != '1.0' or not isinstance(registry.get('entries'), dict):
        raise ValueError('Invalid persistent registry format.')
    entries = registry['entries']
    for entry in entries.values():
        entry['active'] = False
        entry.setdefault('first_registered_at', entry.get('first_seen_at'))
        entry.setdefault('last_registered_at', entry.get('last_seen_at'))
        if 'time_semantics' not in registry:
            # Version 1 originally mislabeled rebuild times as observations.
            # Keep those times as registration evidence, never as new server scans.
            for history in entry.get('path_history', []):
                history['first_registered_at'] = history.pop('first_observed_at', None)
                history['last_registered_at'] = history.pop('last_observed_at', None)
                history['first_observed_at'] = None
                history['last_observed_at'] = None
    active_ids = set()
    for asset in assets:
        asset_id = asset['id']
        # Explicit aliases can preserve an ID after a reviewed source-ID change.
        # They must not cause two current records to collapse into one ID.
        previous_id = registry.get('aliases', {}).get(asset_id)
        if asset_id not in entries and previous_id in entries:
            entries[asset_id] = copy.deepcopy(entries[previous_id])
            entries[asset_id]['asset_id'] = asset_id
        if asset_id not in entries:
            entries[asset_id] = {'asset_id': asset_id, 'registry_id': 'reg-' + str(uuid.uuid4()),
                                 'first_seen_at': now, 'path_history': [],
                                 'logical_resource_id': None, 'identity_state': 'unconfirmed'}
        entry = entries[asset_id]
        entry.setdefault('first_registered_at', entry.get('first_seen_at', now))
        if not re.fullmatch(r'reg-[0-9a-f-]{36}', entry.get('registry_id', '')):
            raise ValueError('Invalid registry ID; refusing to generate unsafe filenames.')
        if entry['registry_id'] in active_ids:
            raise ValueError('Two current records share a registry ID; explicit identity review is required.')
        active_ids.add(entry['registry_id'])
        entry.update({'active': True, 'last_seen_at': now, 'last_registered_at': now,
                      'last_display_name': asset['name'], 'current_path': asset['path']})
        history = entry.setdefault('path_history', [])
        observed_at = asset.get('verified_at') or None
        if not history or history[-1]['path'] != asset['path']:
            history.append({'path': asset['path'], 'first_registered_at': now, 'last_registered_at': now,
                            'first_observed_at': observed_at, 'last_observed_at': observed_at})
        else:
            history[-1]['last_registered_at'] = now
            if observed_at:
                history[-1]['first_observed_at'] = history[-1].get('first_observed_at') or observed_at
                history[-1]['last_observed_at'] = observed_at
    registry['updated_at'] = now
    registry['time_semantics'] = {
        'first_seen_at/last_seen_at': '兼容字段，表示登记程序处理记录的时间，不是源目录观测时间。',
        'first_registered_at/last_registered_at': '登记或重建时间，不访问源目录。',
        'path_history.*_observed_at': '仅采用来源verified_at；没有来源观测证据时为null。',
    }
    return registry


def record_checks(asset):
    metadata = asset.get('metadata', {})
    raw = metadata.get('本次核验') or metadata.get('核验') or {}
    storage = asset.get('storage') or {}
    if storage.get('migration', {}).get('activated'):
        current = next(row for row in storage['observations']
                       if row['path'] == asset['path'] and row['observed_at'] == asset['verified_at']
                       and row['account'] == 'rmp' and row['host'] == storage['current_host'])
        raw = {**current, 'rmp_readable': current['readable']}
    exists = raw.get('exists') if type(raw.get('exists')) is bool else None
    readable = raw.get('rmp_readable') if type(raw.get('rmp_readable')) is bool else None
    return {'exists': exists, 'existence': 'present' if exists is True else 'missing' if exists is False else 'unknown',
            'readable': readable, 'access': 'readable' if readable is True else 'restricted' if readable is False else 'unknown',
            'account': 'rmp', 'observed_at': asset.get('verified_at') or None,
            'host': raw.get('host'),
            'filesystem_owner': raw.get('owner') or asset.get('owner') or None, 'mode': raw.get('mode') or None,
            'realpath': raw.get('realpath') or None, 'mtime_ns': raw.get('mtime_ns'),
            'source_fields': raw, 'scope': 'entry_only',
            'note': '存在性与当前账号的入口读取权限分别记录；入口存在不等于可读取，读取入口不等于所有子文件完整或可读取。快照并非实时状态。'}


def build_mapping(document, previous_registry=None, catalog_sha256='', now=None, annotations=None):
    now = now or utc_now()
    document = validate_document(document)
    assets = document['assets']
    storage_by_id = {}
    for asset in assets:
        storage_by_id[asset['id']] = catalog_storage(asset)
        if public_path(asset['path']) is None or asset['kind'] not in ('dataset', 'model'):
            raise ValueError('Inventory entries must belong to the two public roots and dataset/model kinds.')
        raw_check = asset.get('metadata', {}).get('本次核验') or asset.get('metadata', {}).get('核验') or {}
        if raw_check.get('realpath') and public_path(raw_check['realpath']) is None:
            raise ValueError('Inventory cannot include a cross-boundary symlink target.')
    # Source links must occur in the catalog's own evidence-source whitelist.
    approved_urls = {safe_url(source.get('url')) for source in document.get('sources', []) if isinstance(source, dict)}
    approved_urls.discard(None)
    approved_urls = {url for url in approved_urls if clean_metadata(url) == url}
    assets = clean_metadata(assets)
    for asset in assets:
        if storage_by_id[asset['id']] is not None:
            original_storage = storage_by_id[asset['id']]
            asset['storage'] = clean_metadata(original_storage)
            for cleaned, original_location in zip(asset['storage']['observations'], original_storage['observations']):
                cleaned['mount'] = original_location['mount']
        asset['source_url'] = asset.get('source_url') if asset.get('source_url') in approved_urls else ''
    registry = bind_registry(assets, previous_registry, now)
    group_map, items = {}, []
    for asset in assets:
        metadata = asset.get('metadata', {})
        storage = asset.get('storage') or {}
        historical = storage.get('historical') or {}
        original_observed_at = historical.get('observed_at') or asset.get('verified_at')
        original = metadata.get('原始台账', {})
        subtype = metadata.get('subtype') or asset['kind']
        group = group_for(asset)
        group_map.setdefault(group['id'], {**group, 'asset_ids': []})['asset_ids'].append(asset['id'])
        registration = registry['entries'][asset['id']]
        registry_id = registration['registry_id']
        checks = record_checks(asset)
        role = ROLE_NAMES.get(subtype, '目录资料记录')
        quantity_scope = original.get('统计范围与版本说明') or original.get('行的含义') or (
            '模型目录直接文件逻辑字节；不是递归容量或唯一占盘量。' if subtype == 'model_weights' else
            '仅目录发现；未逐文件枚举，数量与大小未知。' if subtype == 'directory_collection' else
            '沿用来源台账口径，未重新扫描或去重。')
        quantity = {'primary_value': original.get('主要数量') or None, 'unit': original.get('计数单位') or None,
                    'size_bytes': asset.get('size_bytes'), 'file_count': asset.get('file_count'),
                    'record_count': asset.get('record_count'),
                    'as_of': original.get('快照时间') or (historical.get('quantity_observed_at') or original_observed_at if subtype == 'model_weights' else None),
                    'scope': quantity_scope,
                    'source_field': 'metadata.原始台账.主要数量 / 计数单位' if original else None}
        if subtype == 'model_weights' and quantity['primary_value'] is None and quantity['file_count'] is not None:
            quantity['primary_value'] = str(quantity['file_count'])
            quantity['unit'] = '目录直接文件数（不是权重数或样本数）'
            quantity['source_field'] = 'catalog.file_count：本次公共区模型目录直接文件元数据；权重文件数另列'
        hints = list(dict.fromkeys(re.findall(r'(?<![A-Za-z0-9])(?:20\d{6}|r\d+|v\d+(?:\.\d+)*)(?![A-Za-z0-9])', asset['name'])))
        evidence = [{'type': 'catalog_entry', 'label': '当前公共区目录快照', 'ref': 'data/catalog.json / ' + asset['id'],
                     'url': None, 'observed_at': document.get('generated_at'), 'sha256': catalog_sha256},
                    {'type': 'source_record', 'label': '公共区整理台账（非上游来源）' if original else '公共区发现回执（非上游来源）', 'ref': asset.get('source_ref'),
                     'url': safe_url(asset.get('source_url')), 'observed_at': original.get('快照时间') or original_observed_at}]
        if checks['exists'] is not None or checks['readable'] is not None:
            evidence.append({'type': 'public_scan', 'label': '公共区入口元数据核验',
                             'ref': 'data/sources/live-public-metadata.json / path_checks / ' + (historical.get('path') or asset['path']),
                             'url': None, 'observed_at': original_observed_at})
        if storage.get('migration', {}).get('activated'):
            evidence.append({'type': 'location_migration', 'label': '共享位置核验与切换回执（独立于历史数量）',
                             'ref': storage['migration']['verification_ref'], 'url': None,
                             'observed_at': asset.get('verified_at')})
        gaps = [
            {'field': 'logical_resource_id', 'label': '逻辑资源身份待确认', 'reason': '目前一对一登记来源记录；同名、同目录和父子目录都不自动合并为同一资源。'},
            {'field': 'version', 'label': '发布版本待确认', 'reason': '尚无经确认的冻结版本；名称日期、r/v编号和上游revision仅作为线索。'},
            {'field': 'license', 'label': '许可与复用条件待确认', 'reason': '公共区位置不等于公开许可；未知许可不影响此次编目。'},
            {'field': 'maintainer', 'label': '资料维护人待确认', 'reason': '文件系统属主不是已确认的维护人或审批联系人。'},
            {'field': 'content_validation', 'label': '内容完整性未核验', 'reason': '未逐样本读取、去重、校验医学标签、加载模型或核实全部内容。'},
        ]
        for field, label, value in (('file_count', '文件总数未知', quantity['file_count']),
                                    ('size_bytes', '目录大小未知', quantity['size_bytes']),
                                    ('count_unit', '主要数量与单位待补', quantity['unit'])):
            if value is None:
                gaps.append({'field': field, 'label': label, 'reason': '来源未提供可沿用值，保留null，不用0代替。'})
        if checks['access'] == 'restricted':
            gaps.append({'field': 'content_access', 'label': '内容读取受限', 'reason': '当前账号不能读取入口；不改源权限，原位编目可继续，内容工作另按既有授权办理。'})
        if asset['kind'] == 'model':
            gaps.append({'field': 'runtime', 'label': '模型可运行性待确认', 'reason': '权重存在或目录名称不能证明模型可加载，当前未推理或安装运行环境。'})
        item = {
            'asset_id': asset['id'], 'registry_id': registry_id, 'display_name': asset['name'],
            'kind': asset['kind'], 'subtype': subtype, 'group_id': group['id'], 'current_path': asset['path'],
            'category': asset.get('category'), 'formats': asset.get('formats', []), 'tags': asset.get('tags', []),
            'source_status': asset.get('status'), 'version_state': 'unconfirmed',
            'version': {'release_id': None, 'upstream_revision': metadata.get('上游revision') or metadata.get('revision'), 'naming_hints': hints,
                        'note': '目录命名线索不作为已确认发布版本；存储迁移不创建新发布版本。'},
            'identity': {'state': 'unconfirmed', 'logical_resource_id': None, 'location': asset['path'],
                         'note': 'registry_id 标识登记记录，asset_id 对应现有目录条目；资源、版本和物理位置尚未建立经确认的归并。'},
            'registration': {'first_registered_at': registration.get('first_registered_at'),
                             'last_registered_at': registration.get('last_registered_at'),
                             'note': '登记处理时间，不是服务器重新观测时间。'},
            'description': asset.get('description') or '现有目录元数据未提供详细内容说明。',
            'documentation': {
                'summary': asset.get('description') or '仅有目录发现证据，内容待补说明。',
                'category': asset.get('category') or '未分类', 'record_role': role, 'quantity': quantity,
                'source_fields': original, 'model_configuration': metadata.get('模型配置') or metadata.get('config') or {},
                'observation_fields': {key: value for key, value in metadata.items()
                                       if key not in ('原始台账', '模型配置', 'config', '本次核验', '核验', 'subtype')},
                'weight_file_count': metadata.get('weight_file_count'),
                'notes': [value for value in (asset.get('notes'), original.get('标注说明'), original.get('统计范围与版本说明')) if value],
                'license': {'state': 'unknown', 'detail': metadata.get('许可状态') or '未核实'},
                'maintainer': {'state': 'unknown', 'name': None, 'note': '未将文件系统属主自动填为维护人。'},
            },
            'evidence': evidence, 'checks': checks, 'relationships': [], 'gaps': gaps,
            'card_url': '/docs/cards/' + registry_id + '.html', 'card_markdown_url': '/docs/cards/' + registry_id + '.md',
            'proposed_path': {'path': None, 'status': 'not_proposed',
                              'reason': '本阶段原位索引；逻辑身份、版本和依赖未确认，不生成看似已批准的新位置。'},
        }
        if storage:
            item['storage'] = storage
            item['proposed_path'] = {'path': storage['planned_path'],
                                     'status': 'activated' if storage['migration']['activated'] else 'planned',
                                     'reason': '显式迁移映射；只有完整切换回执通过后才成为当前位置。'}
        if asset.get('physical_inventory'):
            item['physical_inventory'] = asset['physical_inventory']
            for gap in item['gaps']:
                known_count = asset['physical_inventory'].get('file_count')
                known_bytes = asset['physical_inventory'].get('apparent_file_bytes')
                if gap['field'] == 'file_count' and known_count is not None:
                    gap.update({'label': '历史台账文件数未记录', 'reason': '原台账计数保留未知；本次逐文件元数据清点已有文件路径数，见物理清点。两次观察不混写。'})
                if gap['field'] == 'size_bytes' and known_bytes is not None:
                    gap.update({'label': '历史台账目录大小未记录', 'reason': '原台账大小保留未知；本次物理清点另列regular file逻辑字节和源已分配字节，不等于CPFS占用。'})
        annotation = (annotations or {}).get('entries', {}).get(asset['id'])
        item['documentation']['research'] = integrate_research(asset, item, annotation)
        item['documentation']['original_description'] = asset.get('description')
        item['documentation']['summary'] = item['documentation']['research']['summary']
        item['gaps'] = compact_gaps(item)
        items.append(item)
    for item in items:
        same = [other for other in items if other['asset_id'] != item['asset_id'] and other['current_path'] == item['current_path']]
        parents = [other for other in items if item['current_path'].startswith(other['current_path'] + '/')]
        nearest_length = max((len(other['current_path']) for other in parents), default=0)
        nearest_parents = [other for other in parents if len(other['current_path']) == nearest_length]
        for other in same + nearest_parents:
            relation_type = 'same_location' if other in same else 'parent_location'
            item['relationships'].append({'type': relation_type, 'target_asset_id': other['asset_id'],
                'target_registry_id': other['registry_id'], 'status': 'candidate',
                'basis': '来源记录的绝对路径完全相同；可能按类型共享对象库，不据此合并。' if relation_type == 'same_location' else
                         '路径层级显示最近祖先入口；仅为位置包含线索，未确认逻辑组成或版本关系。'})
    by_id = {item['asset_id']: item for item in items}
    for item in items:
        for relation in list(item['relationships']):
            if relation['type'] == 'parent_location':
                by_id[relation['target_asset_id']]['relationships'].append({
                    'type': 'child_location', 'target_asset_id': item['asset_id'], 'target_registry_id': item['registry_id'],
                    'status': 'candidate', 'basis': '路径层级显示最近子入口；未确认逻辑组成，父子条目数量不可相加。'})
    groups = sorted(group_map.values(), key=lambda group: group['label'])
    for group in groups:
        group_items = [by_id[asset_id] for asset_id in group['asset_ids']]
        group['records'] = len(group_items)
        group['unique_paths'] = len({item['current_path'] for item in group_items})
    limits = [str(value) for key, value in document.get('scope', {}).items()
              if key in ('核验范围', '统计口径', '限制', '分支覆盖', '公共区含义')]
    limits += ['登记ID不是已确认资源ID；关系均为候选，存储迁移不自动合并记录或创建资源版本。',
               '数量沿用各来源快照和计数单位，文件数不能解释为样本数或参与者人数。']
    summary = {'records': len(items), 'unique_paths': len({item['current_path'] for item in items}), 'groups': len(groups),
               'exists': sum(item['checks']['exists'] is True for item in items),
               'missing': sum(item['checks']['exists'] is False for item in items),
               'existence_unknown': sum(item['checks']['exists'] is None for item in items),
               'readable': sum(item['checks']['readable'] is True for item in items),
               'restricted': sum(item['checks']['readable'] is False for item in items),
               'access_unknown': sum(item['checks']['readable'] is None for item in items),
               'known_weights': sum(item['subtype'] == 'model_weights' for item in items),
               'directory_collections': sum(item['subtype'] == 'directory_collection' for item in items),
               'by_kind': dict(collections.Counter(item['kind'] for item in items)),
               'by_subtype': dict(collections.Counter(item['subtype'] for item in items)),
               'records_with_gaps': sum(bool(item['gaps']) for item in items),
               'coverage_limits': limits}
    return {'schema_version': '1.0', 'generated_at': now, 'catalog_generated_at': document.get('generated_at'),
            'catalog_sha256': catalog_sha256,
            'annotation_provenance': (annotations or {}).get('files', []),
            'storage_migration': document.get('scope', {}).get('storage_migration'),
            'physical_inventory': document.get('scope', {}).get('physical_inventory'),
            'summary': summary, 'groups': groups, 'items': items}, registry


def value_text(value):
    if value is None or value == '':
        return '未知 / 未确认'
    if value is True:
        return '是'
    if value is False:
        return '否'
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def esc(value):
    return html.escape(value_text(value), quote=True)


def md(value):
    return esc(value).replace('\\', '\\\\').replace('|', '\\|').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`').replace('\n', '<br>')


def table(rows):
    return '<table><tbody>' + ''.join('<tr><th scope="row">' + esc(key) + '</th><td>' + esc(value) + '</td></tr>' for key, value in rows) + '</tbody></table>'


def html_page(title, content, css='/docs/resource-inventory.css'):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + esc(title) + '</title><link rel="stylesheet" href="' + css + '"></head><body><main>' + content + '</main></body></html>')


def card_rows(item):
    quantity, checks = item['documentation']['quantity'], item['checks']
    rows = [
        ('登记 ID', item['registry_id']), ('目录 asset_id', item['asset_id']), ('记录角色', item['documentation']['record_role']),
        ('首次登记时间（非现场观测）', item['registration']['first_registered_at']),
        ('逻辑资源 ID', None), ('冻结发布版本', None), ('当前路径', item['current_path']),
        ('入口是否存在', checks['exists']), ('rmp 是否可读入口', checks['readable']),
        ('路径核验时间', checks['observed_at']), ('文件系统属主', checks['filesystem_owner']),
        ('资料维护人', None), ('目录权限', checks['mode']), ('解析后路径', checks['realpath']),
        ('入口 mtime 纳秒（不是核验时间）', checks['mtime_ns']),
        ('主要数量（来源原值）', quantity['primary_value']), ('主要数量单位', quantity['unit']),
        ('目录字节（来源口径）', quantity['size_bytes']), ('文件数（不等于样本）', quantity['file_count']),
        ('样本或记录数', quantity['record_count']), ('数量来源时间', quantity['as_of']), ('数量统计范围', quantity['scope']),
        ('主要数量字段来源', quantity['source_field']),
        ('研究方向 / 导航分类', item['category']), ('格式', item['formats']),
        ('已发现权重文件数', item['documentation']['weight_file_count']), ('上游 revision', item['version']['upstream_revision']),
        ('命名中的版本线索（未确认）', item['version']['naming_hints']),
        ('许可', item['documentation']['license']['detail']),
    ]
    storage = item.get('storage')
    if storage:
        rows += [('迁移阶段', storage['migration']['state']), ('目标位置（未激活时仅计划）', storage['planned_path']),
                 ('历史登记路径', storage['historical']['path']), ('历史入口观察时间', storage['historical']['observed_at']),
                 ('旧路径兼容', '；'.join(alias['path'] + ' → ' + alias['target'] for alias in storage['legacy_aliases']) or '尚无已核验兼容回执'),
                 ('切换核验时间', storage['migration']['cutover_at']), ('本次观察主机', checks.get('host'))]
    physical = item.get('physical_inventory')
    if physical:
        rows += [('物理清点观察时间（源位置）', physical['observed_at']),
                 ('清点位置（迁移前）', physical['observed_path']),
                 ('实际文件路径数（不是资源/样本数）', physical['file_count']),
                 ('子目录数', physical['directory_count']), ('符号链接数（未跟随）', physical['symlink_count']),
                 ('全类型唯一 inode 数（含目录和符号链接）', physical['unique_inodes']),
                 ('文件逻辑字节（路径口径）', physical['apparent_file_bytes']),
                 ('文件逻辑字节（inode去重）', physical['unique_file_bytes']),
                 ('源已分配字节（inode去重，非目标占用预测）', physical['allocated_file_bytes']),
                 ('清点范围', '严格后代，不含入口自身；嵌套登记位置可能重叠，不相加。'),
                 ('inode元数据观察冲突数', physical['inode_observation_conflicts']),
                 ('容量观察限制', '清单不是原子快照；若存在inode观察冲突，容量保留首条观察，不代表一致时点精确值。')]
    return rows


def make_card(item, group_label, mapping):
    title = item['display_name']
    research = item['documentation']['research']
    rows = card_rows(item)
    references = []
    md_references = []
    for evidence in item['evidence']:
        label = esc(evidence['label'])
        url = safe_url(evidence.get('url'))
        link = '<a href="' + html.escape(url, quote=True) + '" rel="noreferrer">来源文档</a>' if url else ''
        references.append('<li><strong>' + label + '</strong>：' + esc(evidence.get('ref')) + ' ' + link + '<br><small>来源时间：' + esc(evidence.get('observed_at')) + '</small></li>')
        md_references.append('- ' + md(evidence['label']) + '：' + md(evidence.get('ref')) + '；时间：' + md(evidence.get('observed_at')) +
                             ('；[来源文档](' + url.replace(')', '%29') + ')' if url else ''))
    relations = []
    md_relations = []
    for relation in item['relationships']:
        url = relation['target_registry_id'] + '.html'
        relations.append('<li><span class="tag">未确认候选</span> ' + esc(relation['type']) + ' · <a href="' + url + '">' + esc(relation['target_asset_id']) + '</a><p>' + esc(relation['basis']) + '</p></li>')
        md_relations.append('- 未确认候选 ' + md(relation['type']) + ' → ' + md(relation['target_asset_id']) + '：' + md(relation['basis']))
    source_fields = list(item['documentation']['source_fields'].items())
    configs = list(item['documentation']['model_configuration'].items())
    observed_fields = list(item['documentation']['observation_fields'].items())
    body = '<nav><a href="/">数据中心</a> / <a href="/docs/resource-inventory.html#' + item['group_id'] + '">资源清册 · ' + esc(group_label) + '</a></nav>'
    body += '<header class="research-intro"><p class="eyebrow">科研资料说明 · 阅读与复用</p><h1>' + esc(title) + '</h1><p>' + esc(research['summary']) + '</p>'
    body += '<a class="button" href="' + item['card_markdown_url'] + '">下载 Markdown 说明</a></header>'
    body += '<div class="evidence-note"><strong>当前位置</strong> <code>' + esc(item['current_path']) + '</code><p>' + esc(research['provenance_note']) + '</p></div>'
    if research['background'] and research['background'] not in research['summary']:
        body += '<section class="research-section"><h2>研究背景</h2><p>' + esc(research['background']) + '</p></section>'
    research_dimensions = [(label, '、'.join(research[key])) for key, label in (('modalities', '资料或方法模态'), ('languages', '语言背景')) if research[key]]
    if research_dimensions:
        body += '<section class="research-section"><h2>研究对象</h2>' + table(research_dimensions) + '</section>'
    research_lists = [('research_uses', '可以研究什么'), ('contents', '本地有什么'),
                      ('getting_started', '第一次使用，从这里开始'), ('caveats', '理解与复用时注意')]
    for key, heading in research_lists:
        if research[key]:
            tag = 'ol' if key == 'getting_started' else 'ul'
            body += '<section class="research-section"><h2>' + heading + '</h2><' + tag + ' class="research-list">' + ''.join('<li>' + esc(value) + '</li>' for value in research[key]) + '</' + tag + '></section>'
    if research.get('inference_io'):
        body += '<section class="research-section"><h2>方法的输入与输出</h2>' + table([('输入', research['inference_io'].get('input')), ('输出', research['inference_io'].get('output'))]) + '</section>'
    if research['sources']:
        body += '<section class="research-section research-sources"><h2>研究背景来源</h2><p class="evidence-note">下列来源解释上游语料或方法，不证明本地副本完整、已获具体使用许可或已经通过运行验证。</p><ul>'
        for source in research['sources']:
            url = safe_url(source.get('url'))
            label = '<a href="' + html.escape(url, quote=True) + '" rel="noreferrer">' + esc(source['label']) + '</a>' if url else esc(source['label'])
            body += '<li>' + label + '<small>' + esc(source['scope']) + '</small></li>'
        body += '</ul><p>说明审阅：' + esc(research.get('reviewed_at')) + '；与下方本地观察时间分别记录。</p></section>'
    body += '<details class="audit-details"><summary>查看本地登记、位置与计数依据</summary><section><h2>身份、位置与数量</h2>' + table(rows) + '</section>'
    body += '<section><h2>原台账描述与说明</h2><p>' + esc(item['description']) + '</p><ul>' + ''.join('<li>' + esc(note) + '</li>' for note in item['documentation']['notes']) + '</ul><p>' + esc(item['checks']['note']) + '</p></section>'
    if source_fields:
        body += '<section><h2>原始台账字段</h2><p>保留来源已有信息及其计数口径；历史 readable 描述不替代本次 rmp 入口权限结果。</p>' + table(source_fields) + '</section>'
    if configs:
        body += '<section><h2>已观察到的模型配置</h2>' + table(configs) + '<p>仅配置元数据，不代表已加载或验证可运行。</p></section>'
    if observed_fields:
        body += '<section><h2>其他已有观察证据</h2>' + table(observed_fields) + '</section>'
    body += '<section><h2>本地来源证据</h2><ul>' + ''.join(references) + '</ul></section>'
    if research['evidence_basis']:
        body += '<section><h2>说明补充依据</h2><ul>' + ''.join('<li>' + esc(value) + '</li>' for value in research['evidence_basis']) + '</ul>' + table([('研究说明文件与 SHA-256', research['provenance'])]) + '</section>'
    body += '</details>'
    body += '<details class="audit-details"><summary>目录关系候选 · ' + str(len(relations)) + '</summary>' + ('<ul>' + ''.join(relations) + '</ul>' if relations else '<p>现有证据未形成具体关系候选。导航分组不等于身份合并。</p>') + '</details>'
    body += '<details class="audit-details"><summary>尚待确认的发布与核验事项 · ' + str(len(item['gaps'])) + '</summary><ul>' + ''.join('<li><strong>' + esc(gap['label']) + '</strong>：' + esc(gap['reason']) + '</li>' for gap in item['gaps']) + '</ul></details>'
    body += '<footer>目录快照：' + esc(mapping['catalog_generated_at']) + '<br>说明生成：' + esc(mapping['generated_at']) + '<br>说明由已保存公共区元数据与所列资料来源整理；本生成过程不访问或修改源数据。</footer>'
    markdown = ['# ' + md(title), '', '公共区资源说明卡；一条来源记录一个登记 ID，不等于已确认的逻辑资源或发布版本。', '',
                md(research['summary']), '', '当前位置：' + md(item['current_path']), '', '## 研究背景', '', md(research['background'])]
    markdown += ['', '## 研究对象', ''] + ['- ' + label + '：' + md(value) for label, value in research_dimensions] if research_dimensions else []
    for key, heading in research_lists:
        if research[key]:
            markdown += ['', '## ' + heading, ''] + [('- ' + md(value)) for value in research[key]]
    if research.get('inference_io'):
        markdown += ['', '## 方法的输入与输出', '', '- 输入：' + md(research['inference_io'].get('input')), '- 输出：' + md(research['inference_io'].get('output'))]
    markdown += ['', '## 研究背景来源', '', '上游说明不代表本地完整性、许可、版本或运行结果。']
    for source in research['sources']:
        url = safe_url(source.get('url'))
        label = '[' + md(source['label']) + '](' + url.replace(')', '%29') + ')' if url else md(source['label'])
        markdown.append('- ' + label + '；适用范围：' + md(source['scope']))
    markdown += ['', '说明依据：' + md(research['provenance_note']), '', '说明审阅：' + md(research.get('reviewed_at')),
                 '', '## 身份、位置与数量', '', '| 字段 | 当前证据 |', '| --- | --- |']
    markdown += ['| ' + md(key) + ' | ' + md(value) + ' |' for key, value in rows]
    markdown += ['', '## 已有说明', ''] + ['- ' + md(note) for note in item['documentation']['notes']]
    for heading, values in (('原始台账字段', source_fields), ('模型配置字段', configs), ('其他已有观察证据', observed_fields)):
        if values:
            markdown += ['', '## ' + heading, '', '| 字段 | 来源值 |', '| --- | --- |']
            markdown += ['| ' + md(key) + ' | ' + md(value) + ' |' for key, value in values]
    markdown += ['', '## 来源证据', ''] + md_references
    markdown += ['', '## 说明补充依据', ''] + ['- ' + md(value) for value in research['evidence_basis']]
    markdown += ['', '说明文件与 SHA-256：' + md(research['provenance'])]
    markdown += ['', '## 关系候选', ''] + (md_relations or ['现有证据未形成具体关系候选；导航分组不等于身份合并。'])
    markdown += ['', '## 待补说明', ''] + ['- ' + md(gap['label']) + '：' + md(gap['reason']) for gap in item['gaps']]
    markdown += ['', '目录快照：' + md(mapping['catalog_generated_at']), '', '本说明生成过程不读取或修改源数据；位置变化以独立迁移回执为准。', '']
    return html_page(title, body), '\n'.join(markdown)


def make_index(mapping):
    summary = mapping['summary']
    by_id = {item['asset_id']: item for item in mapping['items']}
    body = '<nav><a href="/">数据中心</a> / 公共区资源清册</nav><header><p class="eyebrow">现有资料 · 证据整理与身份映射</p><h1>公共区资源清册</h1><p>为每条现有记录保留持久登记 ID、可读说明和待确认事项，迁移不改变登记身份。导航分组不自动合并资源。</p></header>'
    body += '<aside class="notice">本页为生成时清册，路径与访问情况并非实时；CPFS 当前阶段见<a href="/#storage-status">首页存储状态</a>，使用方法见<a href="/docs/cpfs-team-guide.html">团队指南</a>。未核验目标不能当作可用位置。</aside>'
    body += '<div class="metrics">' + ''.join('<article><strong>' + str(count) + '</strong><span>' + label + '</span></article>' for count, label in (
        (summary['records'], '登记记录'), (summary['unique_paths'], '唯一位置'), (summary['known_weights'], '有权重存在证据'), (summary['directory_collections'], '浅层发现集合'))) + '</div>'
    body += '<section><h2>四个概念分别登记</h2><div class="concepts"><article><h3>记录</h3><p>现有资产条目，一对一保留 asset_id 与登记 ID。</p></article><article><h3>资源</h3><p>逻辑身份待确认；同位置或同名不自动合并。</p></article><article><h3>版本</h3><p>命名日期和 revision 是线索，尚无确认的冻结发布版本。</p></article><article><h3>位置</h3><p>当前位置、历史登记与旧路径兼容分别记录，迁移完成须有明确核验证据。</p></article></div></section>'
    body += '<aside class="notice">' + str(summary['exists']) + ' 条记录有入口存在证据；rmp 可读 ' + str(summary['readable']) + ' 条、受限 ' + str(summary['restricted']) + ' 条。以上按记录计数，权限与存在性不同，且都是快照。共享特征对象库的多条记录仍各自保留。</aside>'
    body += '<section><h2>完整映射与来源口径</h2><div class="actions"><a class="button" href="/api/resource-mapping.csv">下载完整映射 CSV</a><a class="button secondary" href="/api/resource-mapping">查看结构化 JSON</a></div><details><summary>展开覆盖限制与计数说明</summary><ul>' + ''.join('<li>' + esc(limit) + '</li>' for limit in summary['coverage_limits']) + '</ul></details></section>'
    body += '<section><h2>按资料位置与命名组浏览</h2><p>每组默认折叠；展开后进入逐条说明。组数量只是导航口径。</p><div class="groups">'
    for group in mapping['groups']:
        body += '<details id="' + group['id'] + '"><summary><strong>' + esc(group['label']) + '</strong><span>' + str(group['records']) + ' 条记录 · ' + str(group['unique_paths']) + ' 个位置</span></summary><p>' + esc(group['description']) + '</p><div class="table-wrap"><table><thead><tr><th>记录 / 说明卡</th><th>角色</th><th>当前位置</th><th>rmp 读取</th></tr></thead><tbody>'
        for asset_id in group['asset_ids']:
            item = by_id[asset_id]
            body += '<tr><td><a href="' + item['card_url'] + '">' + esc(item['display_name']) + '</a><small>' + esc(item['registry_id']) + '</small></td><td>' + esc(item['documentation']['record_role']) + '</td><td><code>' + esc(item['current_path']) + '</code></td><td>' + esc({'readable': '可读入口', 'restricted': '受限', 'unknown': '未知'}[item['checks']['access']]) + '</td></tr>'
        body += '</tbody></table></div></details>'
    body += '</div></section><footer>目录快照：' + esc(mapping['catalog_generated_at']) + '<br>清册生成：' + esc(mapping['generated_at']) + '<br>目录 SHA-256：<code>' + esc(mapping['catalog_sha256']) + '</code><br>全部说明来自已有元数据；本过程未扫描源目录或运行模型。</footer>'
    return html_page('公共区资源清册', body)


STYLES = '''*{box-sizing:border-box}body{margin:0;background:#f4f7fb;color:#17283e;font:15px/1.75 system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:1200px;margin:auto;padding:30px 28px 70px}nav{font-size:13px;color:#66758c;margin-bottom:28px}a{color:#1667ac;text-decoration:none}a:hover{text-decoration:underline}header{padding:30px 0 25px;max-width:900px}h1{font-size:38px;line-height:1.3;margin:8px 0 18px;overflow-wrap:anywhere}h2{font-size:23px;margin:0 0 18px}h3{font-size:17px;margin:0 0 8px}p{margin:8px 0 15px}.eyebrow{font-size:12px;letter-spacing:.12em;color:#356d92}.metrics,.concepts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.metrics article,.concepts article{background:white;border:1px solid #dce5ef;border-radius:12px;padding:20px}.metrics strong{display:block;font-size:32px;color:#155c86}.metrics span{font-size:13px;color:#63758a}section{margin-top:30px;padding:26px;background:white;border:1px solid #dce5ef;border-radius:14px}.concepts article{padding:16px;background:#f8fbff}.notice{margin:25px 0;padding:18px 22px;background:#e9f3f8;border-left:4px solid #33819f;border-radius:5px}table{width:100%;border-collapse:collapse;font-size:14px;table-layout:fixed}th,td{padding:12px 14px;text-align:left;border-bottom:1px solid #e3eaf1;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}th{background:#f2f6fa;color:#4c6179;font-weight:600}tbody th{width:25%}code{font:12px/1.65 ui-monospace,Consolas,monospace;overflow-wrap:anywhere}small{display:block;color:#78889a;font-size:11px;margin-top:5px}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}.button{display:inline-block;background:#17688f;color:white;padding:9px 16px;border-radius:7px;font-size:14px}.button.secondary{background:#eaf1f7;color:#20516e}.groups{display:grid;gap:12px}details{border:1px solid #dbe5ef;border-radius:9px;padding:13px 17px}summary{cursor:pointer;color:#204961;line-height:1.9}summary span{float:right;font-size:12px;color:#718197}.groups details[open]{background:#fbfdff}.table-wrap{overflow:auto}.tag{font-size:11px;background:#fff0d7;color:#8c611d;padding:3px 8px;border-radius:20px}li{margin:8px 0}footer{margin-top:35px;color:#75859a;font-size:12px;overflow-wrap:anywhere}@media(max-width:760px){main{padding:20px 14px 40px}h1{font-size:28px}.metrics,.concepts{grid-template-columns:repeat(2,minmax(0,1fr))}section{padding:17px}.groups table{min-width:700px}summary span{float:none;display:block}tbody th{width:34%}}'''


def write_csv(mapping, path):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in mapping['items']:
            quantity, checks = item['documentation']['quantity'], item['checks']
            row = {key: item.get(key) for key in CSV_FIELDS}
            row.update({'exists': checks['exists'], 'access': checks['access'], 'filesystem_owner': checks['filesystem_owner'],
                        'maintainer': None, 'primary_quantity': quantity['primary_value'], 'count_unit': quantity['unit'],
                        'size_bytes': quantity['size_bytes'], 'file_count': quantity['file_count'],
                        'quantity_observed_at': quantity['as_of'], 'path_observed_at': checks['observed_at'],
                        'gap_count': len(item['gaps']), 'proposed_path': item['proposed_path'].get('path'),
                        'migration_state': (item.get('storage') or {}).get('migration', {}).get('state'),
                        'legacy_aliases': (item.get('storage') or {}).get('legacy_aliases', [])})
            writer.writerow({key: csv_safe(value) for key, value in row.items()})
    temporary.replace(path)


def atomic_text(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(value, encoding='utf-8')
    temporary.replace(path)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def main(root=ROOT):
    root = pathlib.Path(root)
    catalog_path = root / 'data' / 'catalog.json'
    raw = catalog_path.read_bytes()
    document = json.loads(raw.decode('utf-8-sig'))
    registry_path = root / 'data' / 'resource-registry.json'
    previous = json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else None
    annotations = load_annotations(root, {asset['id'] for asset in document['assets']}, clean_metadata, safe_url)
    mapping, registry = build_mapping(document, previous, hashlib.sha256(raw).hexdigest(), annotations=annotations)
    cards = root / 'docs' / 'cards'
    cards.mkdir(parents=True, exist_ok=True)
    # Save the registry before rendering so an interrupted build reuses its IDs.
    atomic_json(registry_path, registry)
    labels = {group['id']: group['label'] for group in mapping['groups']}
    for item in mapping['items']:
        rendered, markdown = make_card(item, labels[item['group_id']], mapping)
        atomic_text(cards / (item['registry_id'] + '.html'), rendered)
        atomic_text(cards / (item['registry_id'] + '.md'), markdown)
    # CSS is a checked-in design artifact owned by the frontend. Never overwrite it.
    css_path = root / 'docs' / 'resource-inventory.css'
    if not css_path.exists():
        checked_in = ROOT / 'docs' / 'resource-inventory.css'
        atomic_text(css_path, checked_in.read_text(encoding='utf-8') if checked_in.exists() else STYLES)
    atomic_text(root / 'docs' / 'resource-inventory.html', make_index(mapping))
    write_csv(mapping, root / 'data' / 'resource-mapping.csv')
    # The new index is exposed only after all referenced cards exist.
    atomic_json(root / 'data' / 'resource-mapping.json', mapping)
    print(json.dumps(mapping['summary'], ensure_ascii=False))
    return mapping, registry


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=ROOT)
    main(parser.parse_args().root)
