"""Offline, fail-closed projection of an explicitly verified path migration.

This module never inspects, copies, renames or deletes source data. Receipts are
operator-produced evidence, not a substitute for copying or verifying files.
"""
import copy
import datetime as dt
import hashlib
import json
import pathlib
import re

ROOT_PAIRS = {
    'datasets': ('/data/datasets', '/data/share/datasets'),
    'models': ('/data/models', '/data/share/models'),
}
OLD_ROOTS = tuple(pair[0] for pair in ROOT_PAIRS.values())
NEW_ROOTS = tuple(pair[1] for pair in ROOT_PAIRS.values())
EVIDENCE_ROOTS = OLD_ROOTS + NEW_ROOTS
STATES = ('planned', 'copying', 'verified', 'switched')
MOUNT_SOURCE = '10.0.0.202:/share'


def within(path, root):
    return path == root or path.startswith(root + '/')


def approved_path(value, roots=EVIDENCE_ROOTS):
    if not isinstance(value, str) or not value.startswith('/') or '\\' in value:
        return None
    parts = pathlib.PurePosixPath(value).parts
    if '..' in parts or any(ord(char) < 32 for char in value):
        return None
    normalized = str(pathlib.PurePosixPath(value))
    return normalized if any(within(normalized, root) for root in roots) else None


def logical_root(path):
    normalized = approved_path(path)
    if normalized:
        for name, pair in ROOT_PAIRS.items():
            if any(within(normalized, root) for root in pair):
                return name
    raise ValueError('path_outside_approved_library_roots')


def source_path(path):
    """Stable logical coordinate for grouping/legacy path-derived identifiers."""
    name = logical_root(path)
    old, new = ROOT_PAIRS[name]
    normalized = approved_path(path)
    return old + normalized[len(new):] if within(normalized, new) else normalized


def destination_path(path):
    name = logical_root(path)
    old, new = ROOT_PAIRS[name]
    normalized = source_path(path)
    return new + normalized[len(old):]


def timestamp(value, field):
    if not isinstance(value, str) or not value:
        raise ValueError(field + '_timestamp_required')
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(field + '_invalid_timestamp') from exc
    if parsed.tzinfo is None:
        raise ValueError(field + '_timezone_required')
    return value


def evidence_file(project_root, reference):
    if not isinstance(reference, dict) or not isinstance(reference.get('ref'), str):
        raise ValueError('evidence_reference_required')
    relative = pathlib.PurePosixPath(reference['ref'])
    if relative.is_absolute() or '..' in relative.parts or '\\' in reference['ref'] or ':' in reference['ref']:
        raise ValueError('evidence_reference_must_be_project_relative')
    project_root = pathlib.Path(project_root).resolve()
    path = (project_root / reference['ref']).resolve(strict=True)
    if not path.is_relative_to(project_root) or not path.is_file():
        raise ValueError('evidence_reference_outside_project')
    digest = reference.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('evidence_sha256_required')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('evidence_sha256_mismatch: ' + reference['ref'])
    return data


def receipt(project_root, value, phase):
    if not isinstance(value, dict) or value.get('status') != 'passed':
        raise ValueError(phase + '_passed_receipt_required')
    if not isinstance(value.get('host'), str) or not value['host'].strip():
        raise ValueError(phase + '_host_required')
    timestamp(value.get('observed_at'), phase)
    evidence_file(project_root, value.get('evidence'))
    return value


def validate_mount(value):
    if (not isinstance(value, dict) or value.get('target') != '/data/share'
            or value.get('source') != MOUNT_SOURCE or value.get('fstype') not in ('nfs', 'nfs3')):
        raise ValueError('expected_cpfs_nfs_mount_receipt_required')
    return {key: value[key] for key in ('target', 'source', 'fstype')}


def validate_manifest(manifest, baseline, registry, project_root):
    if not isinstance(manifest, dict) or manifest.get('schema_version') != '1.0':
        raise ValueError('unsupported_path_migration_schema')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}', str(manifest.get('migration_id', ''))):
        raise ValueError('migration_id_required')
    if manifest.get('state') not in STATES:
        raise ValueError('invalid_migration_state')
    roots = manifest.get('roots')
    expected = [{'logical_root': name, 'source_root': pair[0], 'target_root': pair[1]}
                for name, pair in ROOT_PAIRS.items()]
    if (not isinstance(roots, list) or not all(isinstance(row, dict) for row in roots)
            or sorted(roots, key=lambda row: str(row.get('logical_root'))) != sorted(expected, key=lambda row: row['logical_root'])):
        raise ValueError('migration_requires_exact_two_library_root_pairs')
    assets = {asset['id']: asset for asset in baseline.get('assets', [])}
    entries = manifest.get('entries')
    if not isinstance(entries, list) or len(entries) != len(assets):
        raise ValueError('migration_must_cover_every_baseline_record')
    seen = set()
    registry_entries = (registry or {}).get('entries', {})
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('migration_entry_must_be_object')
        aid = entry.get('asset_id')
        if aid in seen or aid not in assets:
            raise ValueError('migration_asset_id_duplicate_or_unknown')
        seen.add(aid)
        old_path = assets[aid].get('path')
        if not approved_path(old_path, OLD_ROOTS) or entry.get('from_path') != old_path or entry.get('to_path') != destination_path(old_path):
            raise ValueError('migration_path_pair_mismatch: ' + aid)
        if not registry_entries.get(aid) or entry.get('registry_id') != registry_entries[aid].get('registry_id'):
            raise ValueError('migration_registry_id_mismatch: ' + aid)
    # Pending plans may include incomplete receipts; they never activate paths.
    if manifest['state'] != 'switched':
        return []
    receipts = manifest.get('receipts', {})
    receipt(project_root, receipts.get('copy'), 'copy')
    verification = receipt(project_root, receipts.get('verification'), 'verification')
    cutover = receipt(project_root, receipts.get('cutover'), 'cutover')
    if verification.get('errors') != [] or not isinstance(verification.get('strategy'), str) or not verification['strategy'].strip():
        raise ValueError('verification_strategy_and_zero_errors_required')
    mount = validate_mount(cutover.get('mount'))
    disk = cutover.get('disk_snapshot')
    if disk is not None:
        if (not isinstance(disk, dict) or disk.get('mount') != '/data/share'
                or type(disk.get('total_bytes')) is not int or type(disk.get('available_bytes')) is not int
                or not 0 <= disk['available_bytes'] <= disk['total_bytes'] or disk['total_bytes'] <= 0):
            raise ValueError('invalid_cutover_disk_snapshot')
        timestamp(disk.get('observed_at'), 'cutover_disk_snapshot')
    aliases = cutover.get('aliases')
    if not isinstance(aliases, list) or len(aliases) != 2:
        raise ValueError('both_legacy_root_alias_receipts_required')
    for old, new in ROOT_PAIRS.values():
        matches = [row for row in aliases if isinstance(row, dict) and row.get('path') == old]
        if len(matches) != 1 or matches[0].get('target') != new or matches[0].get('kind') != 'symlink' or matches[0].get('verified') is not True:
            raise ValueError('legacy_root_alias_not_verified')
    observations = verification.get('observations')
    if not isinstance(observations, list):
        raise ValueError('target_location_observations_required')
    required = {entry['to_path'] for entry in entries}
    seen_locations, current_host_paths, clean = set(), set(), []
    for item in observations:
        if not isinstance(item, dict) or item.get('path') not in required:
            raise ValueError('observation_unknown_target_path')
        path = item['path']
        host = item.get('host')
        key = (host, path)
        if not isinstance(host, str) or not host or key in seen_locations:
            raise ValueError('observation_host_missing_or_duplicate')
        seen_locations.add(key)
        root = ROOT_PAIRS[logical_root(path)][1]
        if (item.get('exists') is not True or not approved_path(item.get('realpath'), (root,))
                or item.get('account') != 'rmp' or type(item.get('readable')) is not bool
                or item.get('kind') not in ('directory', 'file')):
            raise ValueError('target_observation_incomplete_or_outside_root')
        timestamp(item.get('observed_at'), 'target_observation')
        if host == cutover['host']:
            current_host_paths.add(path)
        # Deliberate public-field projection: raw process/file manifests stay private.
        keep = ('host', 'path', 'realpath', 'observed_at', 'account', 'exists', 'readable',
                'kind', 'owner', 'mode', 'mtime_ns', 'uid', 'gid')
        observed = {field: item[field] for field in keep if field in item}
        # A receipt from one machine cannot certify a different client's mount.
        observed['mount'] = mount if host == cutover['host'] else validate_mount(item.get('mount'))
        observed['evidence_ref'] = verification['evidence']['ref']
        clean.append(observed)
    if current_host_paths != required:
        raise ValueError('cutover_host_must_have_all_target_observations')
    return clean


def load_migration(project_root, manifest_path, registry):
    manifest = json.loads(pathlib.Path(manifest_path).read_text(encoding='utf-8'))
    baseline_bytes = evidence_file(project_root, manifest.get('baseline_catalog'))
    baseline = json.loads(baseline_bytes)
    observations = validate_manifest(manifest, baseline, registry, project_root)
    return baseline, manifest, observations


def project_catalog(baseline, manifest, observations):
    """Keep historical evidence/counts verbatim; add independently dated location evidence."""
    document = copy.deepcopy(baseline)
    active = manifest['state'] == 'switched'
    receipts = manifest.get('receipts') or {}
    cutover = receipts.get('cutover') or {}
    verification = receipts.get('verification') or {}
    migration = {'migration_id': manifest['migration_id'], 'state': manifest['state'], 'activated': active,
                 'cutover_at': cutover.get('observed_at') if active else None,
                 'verification_ref': verification.get('evidence', {}).get('ref') if active else None}
    document['source_snapshot_generated_at'] = baseline.get('generated_at')
    if active:
        document['generated_at'] = cutover['observed_at']
    for asset in document['assets']:
        path = asset['path']
        target = destination_path(path)
        metadata = asset.get('metadata', {})
        historical_check = copy.deepcopy(metadata.get('本次核验') or metadata.get('核验') or {})
        historical = {'path': path, 'observed_at': asset.get('verified_at'), 'check': historical_check,
                      'quantity_observed_at': (metadata.get('原始台账') or {}).get('快照时间') or asset.get('verified_at')}
        matching = [copy.deepcopy(row) for row in observations if row['path'] == target]
        aliases = []
        if active:
            current = next(row for row in matching if row['host'] == cutover['host'])
            asset['path'] = target
            asset['verified_at'] = current['observed_at']
            asset['owner'] = current.get('owner', '')
            asset['status'] = 'verified' if current['readable'] else 'restricted'
            asset['access'] = ('rmp 可读取共享区目录入口；未据此推断所有子文件权限或模型可运行性。' if current['readable']
                               else '共享区入口已核验存在；rmp 当前不可读，内容授权另行核实。')
            aliases = [{'path': path, 'target': target, 'kind': 'symlink', 'state': 'verified',
                        'host': cutover['host'], 'verified_at': cutover['observed_at'],
                        'scope': '通过已核验的旧根符号链接兼容；不是每条子路径各建软链'}]
        asset['storage'] = {'logical_root': logical_root(path), 'canonical_path': asset['path'],
                            'current_host': cutover.get('host') if active else None,
                            'planned_path': target, 'legacy_aliases': aliases, 'migration': copy.deepcopy(migration),
                            'observations': matching, 'historical': historical}
    scope = document.setdefault('scope', {})
    roots = {name: pair[1 if active else 0] for name, pair in ROOT_PAIRS.items()}
    scope['canonical_roots'] = roots
    scope['planned_roots'] = {name: pair[1] for name, pair in ROOT_PAIRS.items()}
    scope['公共根'] = list(roots.values())
    scope['storage_migration'] = migration
    scope['迁移证据口径'] = '当前位置按已核验切换回执投影；原始台账、计数与历史权限时间不改写。迁移不改变资产或登记ID，不证明其他主机可读。'
    if active:
        scope['historical_storage_snapshot'] = baseline.get('scope', {}).get('存储现状')
        scope['存储现状'] = '共享盘当前容量未随切换回执提供；原 /data 盘容量是历史快照，不能用目录条目或迁移文件大小推算共享盘总量与可用量。'
        if cutover.get('disk_snapshot'):
            disk = cutover['disk_snapshot']
            scope['disk_snapshot'] = {key: disk[key] for key in ('mount', 'total_bytes', 'available_bytes', 'observed_at')}
            scope['存储现状'] = (f"共享盘 /data/share 容量观察于 {disk['observed_at']}：总容量 {disk['total_bytes']} 字节，"
                              f"可用 {disk['available_bytes']} 字节；这是整个挂载文件系统的容量，不等于公共资源容量或文件逻辑字节之和。")
    document['migration'] = {**migration, 'baseline_catalog_sha256': manifest['baseline_catalog']['sha256']}
    return document


def catalog_storage(asset):
    """Validate the exported location projection before using it in a card.

    Hash/file receipt validation occurs in load_migration. This check protects
    downstream consumers from malformed or contradictory hand-edited catalogs.
    """
    storage = asset.get('storage')
    path = asset.get('path')
    if storage is None:
        if not approved_path(path, OLD_ROOTS):
            raise ValueError('shared_current_path_requires_activated_migration')
        return None
    if not isinstance(storage, dict) or not isinstance(storage.get('migration'), dict):
        raise ValueError('invalid_storage_projection')
    migration = storage['migration']
    active = migration.get('activated') is True
    if migration.get('state') not in STATES or active != (migration['state'] == 'switched'):
        raise ValueError('storage_activation_state_mismatch')
    historical = storage.get('historical') or {}
    old = historical.get('path')
    if not approved_path(old, OLD_ROOTS) or path != (destination_path(old) if active else old):
        raise ValueError('storage_current_path_mismatch')
    if storage.get('canonical_path') != path or storage.get('planned_path') != destination_path(old) or storage.get('logical_root') != logical_root(old):
        raise ValueError('storage_root_projection_mismatch')
    observations = storage.get('observations')
    if not isinstance(observations, list):
        raise ValueError('storage_observations_required')
    for row in observations:
        if row.get('path') != destination_path(old) or not approved_path(row.get('realpath'), (ROOT_PAIRS[logical_root(old)][1],)):
            raise ValueError('storage_observation_outside_destination')
        validate_mount(row.get('mount'))
    if active and not any(row.get('observed_at') == asset.get('verified_at') and row.get('account') == 'rmp'
                          and row.get('host') == storage.get('current_host') for row in observations):
        raise ValueError('storage_current_observation_missing')
    # Builder-generated storage contains no source contents; preserve its typed
    # mount metadata without passing /data/share through the free-text scrubber.
    return copy.deepcopy(storage)


def planned_manifest(document, registry, baseline_ref, baseline_sha256, migration_id):
    return {'schema_version': '1.0', 'migration_id': migration_id, 'state': 'planned',
            'baseline_catalog': {'ref': baseline_ref, 'sha256': baseline_sha256},
            'roots': [{'logical_root': name, 'source_root': pair[0], 'target_root': pair[1]}
                      for name, pair in ROOT_PAIRS.items()],
            'entries': [{'asset_id': asset['id'], 'registry_id': registry['entries'][asset['id']]['registry_id'],
                         'from_path': asset['path'], 'to_path': destination_path(asset['path'])}
                        for asset in document['assets']], 'receipts': {}}


INVENTORY_COUNTS = ('file_count', 'directory_count', 'symlink_count', 'apparent_file_bytes',
                    'unique_file_bytes', 'allocated_file_bytes', 'unique_inodes', 'unique_file_inodes',
                    'external_absolute_symlink_count', 'inode_observation_conflicts', 'catalog_record_count')


def inventory_stats(value):
    if not isinstance(value, dict):
        raise ValueError('physical_inventory_stats_must_be_object')
    result = {}
    if 'entry_observed' in value:
        if value['entry_observed'] is not None and type(value['entry_observed']) is not bool:
            raise ValueError('physical_inventory_entry_observed_must_be_boolean_or_null')
        result['entry_observed'] = value['entry_observed']
    if 'entry_kind' in value:
        if value['entry_kind'] not in (None, 'dir', 'directory', 'file', 'symlink', 'special', 'unknown'):
            raise ValueError('physical_inventory_invalid_entry_kind')
        result['entry_kind'] = value['entry_kind']
    for key in INVENTORY_COUNTS:
        number = value.get(key)
        if number is not None and (type(number) is not int or number < 0):
            raise ValueError('physical_inventory_nonnegative_integer_required: ' + key)
        result[key] = number
    result['newest_mtime'] = timestamp(value['newest_mtime'], 'physical_inventory_mtime') if value.get('newest_mtime') is not None else None
    extensions = value.get('extension_counts', {})
    if extensions is None:
        result['extension_counts'] = None
        return result
    if not isinstance(extensions, dict) or len(extensions) > 12:
        raise ValueError('physical_inventory_extensions_must_be_top12_object')
    if any(not isinstance(key, str) or '/' in key or '\\' in key or len(key) > 80
           or any(ord(char) < 32 for char in key) or type(count) is not int or count < 0
           for key, count in extensions.items()):
        raise ValueError('invalid_physical_inventory_extension_count')
    result['extension_counts'] = extensions
    return result


def attach_physical_inventory(document, inventory_path):
    """Import an approved aggregate only; raw inode/file manifests are not opened."""
    path = pathlib.Path(inventory_path)
    raw = path.read_bytes()
    inventory = json.loads(raw)
    if inventory.get('schema_version') != '1.0' or inventory.get('source') != 'source_manifest':
        raise ValueError('unsupported_physical_inventory_schema_or_source')
    observed_at = timestamp(inventory.get('observed_at'), 'physical_inventory')
    roots, paths = inventory.get('roots'), inventory.get('paths')
    if not isinstance(roots, dict) or set(roots) != set(OLD_ROOTS) or not isinstance(paths, dict):
        raise ValueError('physical_inventory_exact_source_roots_required')
    known_paths = {source_path(asset['path']) for asset in document['assets']}
    if not set(paths).issubset(known_paths):
        raise ValueError('physical_inventory_contains_unregistered_path')
    clean_paths = {key: inventory_stats(value) for key, value in paths.items()}
    digest = hashlib.sha256(raw).hexdigest()
    common = {'observed_at': observed_at, 'source': 'source_manifest', 'sha256': digest,
              'evidence_ref': 'data/physical-inventory.json',
              'location_role': 'pre_migration_source',
              'note': '源位置逐文件元数据清点；不读取样本或权重内容，不代替内容校验。计数独立于目录记录数；源已分配字节不是CPFS占用预测。'}
    manifest_hash = inventory.get('source_manifest_sha256')
    if manifest_hash is not None:
        if not isinstance(manifest_hash, str) or not re.fullmatch('[a-f0-9]{64}', manifest_hash):
            raise ValueError('invalid_source_manifest_sha256')
        common['source_manifest_sha256'] = manifest_hash
    definitions = inventory.get('definitions', {})
    if not isinstance(definitions, dict) or any(not isinstance(key, str) or not isinstance(value, str)
            or not re.fullmatch('[a-z0-9_]+', key) or not re.fullmatch('[a-z0-9_]+', value)
            for key, value in definitions.items()):
        raise ValueError('invalid_physical_inventory_definitions')
    common['definitions'] = definitions
    for asset in document['assets']:
        old = source_path(asset['path'])
        if old in clean_paths:
            asset['physical_inventory'] = {**copy.deepcopy(common), **clean_paths[old], 'observed_path': old}
    aggregate = {**common, 'roots': {key: inventory_stats(value) for key, value in roots.items()},
                 'paths_covered': len(clean_paths), 'registered_paths': len(known_paths),
                 'limitations': ['每个目录只统计严格后代，不含入口自身；登记路径可父子重叠，不能把逐条统计相加当全库总量。',
                                 '文件数按路径计；unique_inodes 对全部类型的设备号与inode去重，unique_file_inodes/unique_file_bytes 仅对regular file去重。',
                                 '不跟随符号链接扫描内容；入口可达性、内容许可和科研完整性单独核验。',
                                 '清单不是原子快照；inode_observation_conflicts大于0时，容量保留首条观察，不能解释为一致时点精确值。',
                                 '这是迁移前源位置快照，迁移后不刷新为当前共享盘实测容量。']}
    if isinstance(inventory.get('totals'), dict):
        aggregate['totals'] = inventory_stats(inventory['totals'])
    summary = inventory.get('summary', {})
    if not isinstance(summary, dict):
        raise ValueError('physical_inventory_summary_must_be_object')
    aggregate['summary'] = {}
    for field in ('catalog_records', 'registered_paths', 'paths_with_multiple_records', 'manifest_records',
                  'observed_registered_paths', 'unobserved_registered_paths'):
        value = summary.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('physical_inventory_summary_nonnegative_integer_required')
        if field in summary:
            aggregate['summary'][field] = value
    complete = summary.get('source_scan_complete')
    if complete is not None and type(complete) is not bool:
        raise ValueError('physical_inventory_source_scan_complete_boolean_or_null')
    aggregate['summary']['source_scan_complete'] = complete
    if 'root_manifest_records' in summary:
        root_counts = summary['root_manifest_records']
        if not isinstance(root_counts, dict) or set(root_counts) != set(OLD_ROOTS) or any(type(v) is not int or v < 0 for v in root_counts.values()):
            raise ValueError('physical_inventory_root_manifest_records_invalid')
        aggregate['summary']['root_manifest_records'] = dict(root_counts)
    scope = document.setdefault('scope', {})
    scope['physical_inventory'] = aggregate
    scope.setdefault('historical_discovery_scope', {
        key: scope.get(key) for key in ('核验范围', '限制', '分支覆盖')
    })
    scope['核验范围'] = '登记身份与研究说明沿用原台账及有限目录发现；另附本次逐文件元数据清单的物理统计，范围、时间和完整性口径见physical_inventory。'
    scope['限制'] = '逐文件清单的聚合不等于独立科研资源已逐项识别，也不代替内容校验、许可核实或各机器访问测试。原目录发现的限制保留在historical_discovery_scope。'
    document.setdefault('sources', []).append({'name': '迁移前物理元数据清点聚合', 'ref': common['evidence_ref'],
                                               'generated_at': observed_at, 'sha256': digest,
                                               'counting_note': common['note']})
    return document
