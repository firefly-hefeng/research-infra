"""Build a portable metadata catalog for the two server public areas only.

This reads evidence files, never the original dataset or model directories.
Public area means location, not an assertion of copyright or content access.
"""
import collections
import argparse
import csv
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.path_migration import load_migration, project_catalog, attach_physical_inventory
PUBLIC_ROOTS = ('/data/datasets', '/data/models')
SERVER = '阿里云训练服务器'
SOURCE_URL = 'https://wcn5kauqqbj1.feishu.cn/docx/UXRxdYjrcoyqKIx3DwAca9sPnbh'
PUBLIC_CSV = 'public-assets-20261018.csv'
LIVE_JSON = 'live-public-metadata.json'
# No original/source/member/cross-server path columns are copied to publication.
PUBLIC_FIELDS = (
    '资产ID', '服务器', '名称', '所属资源／检索别名', '语音方向', '实际采集或产生方式',
    '数据类型', '绝对路径', '原始或派生', '主要数量', '计数单位', '音频文件数',
    '音频字节', '音频大小', '目录字节', '目录大小', '全部文件数', '压缩包数',
    '压缩包字节', '标注说明', 'ASR数量', 'ASR字节', '特征数量', '特征字节',
    '特征大小', '疑似特征扩展文件数', '复用说明', '完整性与状态', '快照时间',
    '源记录序号', '行的含义', '数据库名称', '数据库逻辑字节', '数据库逻辑大小',
    '数据库统计摘要', '标注表行数', '统计范围与版本说明',
)
ABSOLUTE_PATH = re.compile(r'''(?<![\w/])/(?!/)[^\s<>"'，；。;,|]+''')
DATA_PATH = re.compile(r'''/data(?:/[^\s<>"'，；。;,|]*)?(?=/|$|\s|[<>"'，；。;,|])''')


def public_path(value):
    if not isinstance(value, str) or not value.startswith('/') or '\\' in value:
        return None
    path = pathlib.PurePosixPath(value)
    if '..' in path.parts or any(ord(char) < 32 for char in value):
        return None
    normalized = str(path)
    return normalized if any(normalized == root or normalized.startswith(root + '/') for root in PUBLIC_ROOTS) else None


def safe_text(value):
    """Drop a whole source field if it mentions an out-of-scope filesystem path."""
    value = str(value) if value is not None else ''
    if re.search(r'[A-Za-z]:[\\/]|\\\\', value):
        return ''
    paths = list(ABSOLUTE_PATH.finditer(value)) + list(DATA_PATH.finditer(value))
    if any(public_path(match.group(0).rstrip(')）]')) is None for match in paths):
        return ''
    return value


def safe_tree(value):
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, dict):
        return {key: safe_tree(item) for key, item in value.items() if safe_text(key) == key}
    if isinstance(value, list):
        return [safe_tree(item) for item in value]
    return value


def allowed_record(path, check=None):
    if public_path(path) is None:
        return False
    check = check or {}
    if check.get('reason') == 'outside_public_roots':
        return False
    return not check.get('realpath') or public_path(check['realpath']) is not None


def integer(value):
    return int(value) if value is not None and re.fullmatch(r'\d+', str(value)) else None


def subtype(row):
    label = row.get('数据类型', '')
    for kind, words in (
        ('annotation', ('配套转写', '标签/量表', '衍生标签')),
        ('feature', ('派生特征', '预处理/特征', '数字特征', '按工具聚合')),
        ('collection', ('索引/研究', '镜像根', '对象库', '资料根', '配套分项', '关系库', '项目输入')),
        ('artifact', ('复核索引', 'staging', '模型、特征及评估', '结果工件', '小工件', '历史研究')),
    ):
        if any(word in label for word in words):
            return kind
    return 'dataset'


def access_state(check):
    if not check:
        return 'documented', '公共区台账记载；本次入口权限未核验。'
    if check.get('exists') is False:
        return 'missing', '本次未找到此公共区路径；需确认迁移或失效原因。'
    if check.get('rmp_readable'):
        return 'verified', 'rmp 可读取目录入口；未验证所有子文件权限或内容完整性。'
    return 'restricted', '位于公共区，rmp 当前不可读；保留编目，内容读取按现有权限申请。'


def filter_source_rows(rows, checks):
    result = []
    for row in rows:
        path = public_path(row.get('绝对路径'))
        if row.get('服务器') != SERVER or not path or not allowed_record(path, checks.get(path)):
            continue
        clean = {field: safe_text(row.get(field, '')) for field in PUBLIC_FIELDS}
        clean['服务器'], clean['绝对路径'] = SERVER, path
        identity = '|'.join((SERVER, row.get('输入来源', ''), row.get('名称', ''), path))
        aid = row.get('资产ID', '')
        clean['资产ID'] = aid if re.fullmatch(r'[A-Za-z0-9_-]{1,128}', aid) else 'asset-' + hashlib.sha256(identity.encode()).hexdigest()[:16]
        result.append(clean)
    return result


def clean_check(check):
    return safe_tree({key: value for key, value in (check or {}).items()
                      if key in ('exists', 'kind', 'owner', 'mode', 'realpath', 'mtime_ns', 'rmp_readable', 'reason')})


def is_within(path, parent):
    return path == parent or path.startswith(parent + '/')


def build_document(rows, live, source_hash):
    checks = live.get('path_checks', {})
    generated_at = live.get('generated_at', '')
    assets = []
    for number, row in enumerate(rows, 1):
        path = row['绝对路径']
        check = checks.get(path, {})
        status, access = access_state(check)
        name = row.get('所属资源／检索别名') or row.get('名称') or pathlib.PurePosixPath(path).name
        if row.get('名称') and name != row['名称']:
            name += ' · ' + row['名称']
        kind = 'model' if is_within(path, '/data/models') else 'dataset'
        assets.append({
            'id': row['资产ID'], 'name': name, 'kind': kind, 'server': SERVER,
            'category': row.get('语音方向') or ('模型公共区' if kind == 'model' else '公共数据'),
            'description': row.get('实际采集或产生方式') or row.get('数据类型') or '公共区台账入口。',
            'path': path, 'owner': safe_text(check.get('owner', '')), 'formats': [],
            'tags': [text for text in (row.get('原始或派生'), row.get('数据类型', '').split('；')[0]) if text],
            'size_bytes': integer(row.get('目录字节')), 'file_count': integer(row.get('全部文件数')), 'record_count': None,
            'status': status, 'access': access, 'source_url': SOURCE_URL,
            'source_ref': PUBLIC_CSV + ' #' + str(number),
            'verified_at': generated_at if check else row.get('快照时间', ''),
            'notes': ' '.join(text for text in (row.get('复用说明'), row.get('完整性与状态')) if text),
            'metadata': {'subtype': subtype(row), '原始台账': {key: value for key, value in row.items() if value and key != '资产ID'},
                         '本次核验': clean_check(check), '记录性质': '公共区目录/路径观察，不是冻结发布版本',
                         '许可状态': '未核实；不影响公共区编目，具体使用另核授权'},
        })
    models_added = 0
    for model in live.get('models', []):
        path = public_path(model.get('path'))
        check = checks.get(path, model.get('stat', {}))
        if not path or not allowed_record(path, check):
            continue
        cfg = safe_tree(model.get('config', {}))
        if not isinstance(cfg, dict):
            cfg = {}
        architectures = cfg.get('architectures', [])
        if not isinstance(architectures, list):
            architectures = []
        architectures = [item for item in architectures if isinstance(item, str)]
        status, access = access_state(check)
        name = safe_text(model.get('name', '')) or pathlib.PurePosixPath(path).name
        model_asset = {
            'id': 'model-' + hashlib.sha256(path.encode()).hexdigest()[:16], 'name': name, 'kind': 'model', 'server': SERVER,
            'category': '模型权重', 'description': '模型目录发现权重文件。' + ('架构：' + ', '.join(architectures) if architectures else '用途和加载环境待核。'),
            'path': path, 'owner': safe_text(check.get('owner', '')), 'formats': safe_tree(model.get('formats', [])),
            'tags': [value for value in (cfg.get('model_type'), cfg.get('torch_dtype') or cfg.get('dtype')) if isinstance(value, str) and value],
            'size_bytes': model.get('size_bytes'), 'file_count': model.get('file_count'), 'record_count': None,
            'status': status, 'access': access, 'source_url': '', 'source_ref': LIVE_JSON + ' / models', 'verified_at': generated_at,
            'notes': '只核验目录、文件元数据和有限配置；未加载权重或推理。大小为直接文件逻辑字节，不能跨条目求和为唯一占盘量。',
            'metadata': {'subtype': 'model_weights', '模型配置': cfg, '来源根': safe_text(model.get('root', '')),
                         '上游revision': safe_tree(model.get('revision')), '核验': clean_check(check),
                         'weight_file_count': model.get('weight_file_count'), '元数据采集完整': model.get('metadata_complete', True),
                         '许可状态': '未核实；不影响公共区编目', '可运行性': '未测试'},
        }
        existing = next((asset for asset in assets if asset['path'] == path), None)
        if existing:
            model_asset['id'] = existing['id']
            model_asset['metadata']['原始台账'] = existing['metadata'].get('原始台账', {})
            assets[assets.index(existing)] = model_asset
        else:
            assets.append(model_asset)
            models_added += 1
    covered = {asset['path'] for asset in assets}
    discoveries_added = 0
    candidates = sorted(live.get('collections', []), key=lambda item: (len(pathlib.PurePosixPath(item.get('path', '')).parts), item.get('path', '')))
    for item in candidates:
        path = public_path(item.get('path'))
        check = checks.get(path, item.get('stat', {}))
        if not path or path in PUBLIC_ROOTS or not allowed_record(path, check):
            continue
        # Skip existing resources, their descendants and their container ancestors.
        # Uncovered siblings remain eligible, with their shallowest entry selected.
        if any(is_within(path, known) or is_within(known, path) for known in covered):
            continue
        status, access = access_state(check)
        kind = 'model' if is_within(path, '/data/models') else 'dataset'
        assets.append({
            'id': 'discovered-' + hashlib.sha256(path.encode()).hexdigest()[:16],
            'name': safe_text(item.get('name', '')) or pathlib.PurePosixPath(path).name,
            'kind': kind, 'server': SERVER, 'category': '公共区目录集合',
            'description': '公共区目录发现入口，代表此分支集合；未逐文件扫描，不应解释为一个独立数据集或完整模型。',
            'path': path, 'owner': safe_text(check.get('owner', '')), 'formats': [], 'tags': ['目录集合', '浅层发现'],
            'size_bytes': None, 'file_count': None, 'record_count': None, 'status': status, 'access': access,
            'source_url': '', 'source_ref': LIVE_JSON + ' / collections', 'verified_at': generated_at,
            'notes': '以未被台账或权重入口覆盖的最浅目录代表分支；包含其后代内容，不按采样目录逐条制造数据集。',
            'metadata': {'subtype': 'directory_collection', '目录深度': item.get('depth'),
                         '核验': clean_check(check), '内容完整性': '未逐文件核验', '许可状态': '未核实；不影响公共区编目'},
        })
        covered.add(path)
        discoveries_added += 1
    errors = safe_tree(live.get('errors', []))
    kinds = dict(collections.Counter(asset['kind'] for asset in assets))
    disk = live.get('disk', {})
    total_bytes, available_bytes = disk.get('total_bytes'), disk.get('available_bytes')
    storage = '磁盘总量与可用量未提供；不由资产大小求和推算。'
    if isinstance(total_bytes, int) and isinstance(available_bytes, int) and total_bytes > 0:
        storage = (f'核验时间 {generated_at}；/data 文件系统总容量 {total_bytes} 字节（{total_bytes / 1024**4:.2f} TiB），'
                   f'可用 {available_bytes} 字节（{available_bytes / 1024**4:.2f} TiB），使用率约 {1 - available_bytes / total_bytes:.1%}。'
                   '这是整个挂载盘的容量快照，不是公共资产容量，也不能与条目 size_bytes 求和混用。')
    result = {
        'schema_version': '1.0', 'generated_at': generated_at,
        'scope': {
            '公共根': list(PUBLIC_ROOTS),
            '根入口定位': '两根入口及其全部内容均属于编目范围；未逐项展开的内容由所属目录入口定位，不因未细分而排除。根本身不额外增加资源计数。',
            '范围': '纳入两处公共区全部内容，不按版权、开源程度或业务用途筛选；域外路径和跨界符号链接不纳入。',
            '公共区含义': '公共区是服务器存放位置，不代表内容已获公开许可或当前账号可以读取。',
            '说明': f'{len(rows)} 条公共区台账记录（{len(set(row["绝对路径"] for row in rows))} 个路径）+ {models_added} 个新增权重入口 + {discoveries_added} 个未覆盖目录集合入口；共 {len(assets)} 条目录记录。',
            '核验范围': '本轮仅核验公共区目录元数据：数据区浅层目录深度≤3，模型识别有限深度≤5；不做深度逐文件扫描。',
            '统计口径': '目录入口不是独立数据集或样本数；台账父子目录、原件和派生物可能重叠。未知为null，0仅保留已有来源的真实零值，不求和全库容量。',
            '分支覆盖': '保留已有台账；其他已发现分支以未覆盖最浅目录代表，根及已覆盖的容器不重复计数。代表入口不证明其所有后代文件已被枚举。',
            '限制': '浅层目录、历史台账与有限模型识别结合；根层未登记文件、隐藏或特殊目录和更深内容不逐项展开。完整逐文件索引尚未建立。',
            '使用权限': 'rmp不可读的公共入口仍纳入并标为restricted；许可证和内容授权独立记录，不作为本次编目筛选条件。',
            '当前阶段': '只读整理和可视化；后续规划公共数据库整理与上传API，不要求前端上传页面。',
            '存储现状': storage,
            '采集缺口': '本次有限扫描未报告错误，仍受范围与深度限制。' if not errors else f'{len(errors)} 条采集缺口，详见来源errors。',
        },
        'sources': [
            {'name': '公共区过滤台账（2026-10-18）', 'url': SOURCE_URL, 'ref': 'data/sources/' + PUBLIC_CSV,
             'record_count': len(rows), 'sha256': source_hash, 'fields': '发布字段白名单，移除域外路径及跨服务器关联字段'},
            {'name': '公共区轻量核验', 'ref': 'data/sources/' + LIVE_JSON, 'generated_at': generated_at,
             'method': safe_text(live.get('method', '')), 'model_count': len(live.get('models', [])),
             'public_roots': list(PUBLIC_ROOTS), 'discovered_directories': len(live.get('collections', [])),
             'disk_snapshot': {'mount': '/data', 'total_bytes': total_bytes, 'available_bytes': available_bytes, 'observed_at': generated_at},
             'limits': safe_tree(live.get('limits', {})), 'errors': errors},
        ],
        'assets': assets,
    }
    report = {'total': len(assets), 'source_rows': len(rows), 'source_paths': len(set(row['绝对路径'] for row in rows)),
              'models_added': models_added, 'discovered_entries_added': discoveries_added,
              'by_kind': kinds, 'by_server': dict(collections.Counter(asset['server'] for asset in assets)),
              'by_status': dict(collections.Counter(asset['status'] for asset in assets)), 'public_roots': list(PUBLIC_ROOTS),
              'scan_errors': errors, 'counting_note': '台账、权重和目录集合入口，不是独立数据集或样本数'}
    return result, report


def main(root=ROOT, migration_manifest=None):
    root = pathlib.Path(root)
    manifest_path = pathlib.Path(migration_manifest) if migration_manifest else root / 'data' / 'path-migration.json'
    if migration_manifest and not manifest_path.exists():
        raise ValueError('explicit_migration_manifest_missing')
    if manifest_path.exists():
        # A migration rebuild is based on the pinned original snapshot. Never
        # re-hash destination paths to manufacture new model/discovery IDs.
        registry = json.loads((root / 'data' / 'resource-registry.json').read_text(encoding='utf-8'))
        baseline, manifest, observations = load_migration(root, manifest_path, registry)
        from catalog import validate_document
        result = project_catalog(validate_document(baseline), manifest, observations)
        report = {'total': len(result['assets']), 'public_roots': result['scope']['公共根'],
                  'migration': result['migration'], 'by_kind': dict(collections.Counter(a['kind'] for a in result['assets'])),
                  'by_status': dict(collections.Counter(a['status'] for a in result['assets'])),
                  'counting_note': '迁移保持原记录身份与数量；物理文件清点独立，不等于资源记录数。'}
        _write_result(root, result, report)
        return result, report
    source_dir = root / 'data' / 'sources'
    live = json.loads((source_dir / LIVE_JSON).read_text(encoding='utf-8'))
    original = source_dir / 'assets-20261018.csv'
    published = source_dir / PUBLIC_CSV
    source = original if original.exists() else published
    with source.open(encoding='utf-8-sig', newline='') as handle:
        rows = filter_source_rows(list(csv.DictReader(handle)), live.get('path_checks', {}))
    with published.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=PUBLIC_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    source_hash = hashlib.sha256(published.read_bytes()).hexdigest()
    result, report = build_document(rows, live, source_hash)
    _write_result(root, result, report)
    return result, report


def _write_result(root, result, report):
    physical = root / 'data' / 'physical-inventory.json'
    if physical.exists():
        attach_physical_inventory(result, physical)
        report['physical_inventory_paths'] = result['scope']['physical_inventory']['paths_covered']
    for filename, value in (('catalog.json', result), ('build-report.json', report)):
        target = root / 'data' / filename
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(target)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=ROOT)
    parser.add_argument('--migration-manifest', type=pathlib.Path,
                        help='Explicit migration plan; otherwise data/path-migration.json is used when present.')
    args = parser.parse_args()
    main(args.root, args.migration_manifest)
