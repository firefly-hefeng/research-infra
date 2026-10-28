"""Combine reviewed explanations with local evidence without changing observations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

LIST_FIELDS = ('research_uses', 'starter_notes', 'contents', 'caveats', 'modalities', 'languages', 'topics')
TEXT_FIELDS = ('summary', 'background', 'provenance_note')
CONFIDENCES = {'official_match', 'family_context', 'local_evidence'}


def unique(values):
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def load_annotations(root, asset_ids, clean, safe_url):
    """Read only checked-in JSON annotations, never paths mentioned inside them."""
    entries, files = {}, []
    directory = Path(root) / 'data' / 'annotations'
    for path in sorted(directory.glob('*.json')):
        raw = path.read_bytes()
        document = json.loads(raw.decode('utf-8-sig'))
        if document.get('schema_version') != '1.0' or not isinstance(document.get('entries'), dict):
            raise ValueError(f'Invalid annotation document: {path.name}')
        record = {'path': 'data/annotations/' + path.name, 'sha256': hashlib.sha256(raw).hexdigest(),
                  'reviewed_at': document.get('reviewed_at'), 'records': len(document['entries'])}
        files.append(record)
        for asset_id, original in document['entries'].items():
            if asset_id not in asset_ids:
                raise ValueError(f'Unknown asset ID in {path.name}: {asset_id}')
            if asset_id in entries:
                raise ValueError(f'Duplicate annotation for {asset_id}; consolidate the reviewed entry.')
            if not isinstance(original, dict):
                raise ValueError(f'Annotation must be an object: {asset_id}')
            for field in TEXT_FIELDS:
                if field in original and not isinstance(original[field], str):
                    raise ValueError(f'{asset_id}.{field} must be text.')
            for field in LIST_FIELDS:
                if field in original and (not isinstance(original[field], list) or not all(isinstance(value, str) for value in original[field])):
                    raise ValueError(f'{asset_id}.{field} must be a text array.')
            if original.get('confidence', 'local_evidence') not in CONFIDENCES:
                raise ValueError(f'Unsupported annotation confidence: {asset_id}')
            if not isinstance(original.get('sources', []), list) or not isinstance(original.get('evidence_basis', []), list):
                raise ValueError(f'Invalid annotation evidence arrays: {asset_id}')
            if 'inference_io' in original and (not isinstance(original['inference_io'], dict) or
                    not all(isinstance(value, str) for value in original['inference_io'].values())):
                raise ValueError(f'Invalid inference input/output explanation: {asset_id}')
            for source in original.get('sources', []):
                if not isinstance(source, dict) or not isinstance(source.get('title', source.get('label')), str):
                    raise ValueError(f'Invalid source title: {asset_id}')
                if source.get('url') is not None and (not safe_url(source['url']) or clean(source['url']) != source['url']):
                    raise ValueError(f'Invalid or out-of-scope source URL: {asset_id}')
            entry = clean(original)
            entry['_provenance'] = record
            entries[asset_id] = entry
    return {'entries': entries, 'files': files}


def local_research(asset, item):
    """Use each source row's actual content and count unit as the fallback."""
    raw = item['documentation']['source_fields']
    quantity = item['documentation']['quantity']
    subtype, name = item['subtype'], item['display_name']
    role = raw.get('数据类型') or item['documentation']['record_role']
    activity = raw.get('实际采集或产生方式') or asset.get('description') or ''
    summary = f'{name}：{activity.rstrip("。") or role}。'
    contents = [f'本地登记角色：{role}。']
    if quantity['primary_value'] is not None:
        contents.append(f'来源台账主要数量为 {quantity["primary_value"]}，单位为「{quantity["unit"] or "尚未记录"}」。')
    if raw.get('音频文件数') not in (None, ''):
        contents.append(f'台账列出音频文件 {raw["音频文件数"]} 个、全部可见文件 {raw.get("全部文件数", "未记录")} 个；沿用原统计范围。')
    if raw.get('压缩包数') not in (None, '', '0'):
        contents.append(f'其中压缩包 {raw["压缩包数"]} 个；压缩归档与解压内容不能重复计作两份语料。')
    if raw.get('标注说明'):
        contents.append('标注与附属资料：' + raw['标注说明'])
    if subtype == 'model_weights':
        config = item['documentation']['model_configuration']
        direct_count = quantity['file_count'] if quantity['file_count'] is not None else '数量未记录'
        weights = item['documentation']['weight_file_count'] if item['documentation']['weight_file_count'] is not None else '数量未记录'
        contents.append(f'目录直接文件：{direct_count}；权重文件：{weights}。二者的统计范围不同。')
        if config.get('architectures'):
            contents.append('已有配置架构：' + '、'.join(config['architectures']) + '。')
    if subtype == 'directory_collection':
        contents.append(f'入口位于 {item["current_path"]}；这是该分支的定位记录，尚没有逐文件内容清单或数量。')
    access = ('准备读取时先按既有授权申请入口访问；保存的 rmp 观察为不可读。' if item['checks']['readable'] is False else
              '先从现有说明或清单选取一个小范围，确认任务、文件对应关系与使用条件。')
    starter = [access]
    if subtype == 'feature':
        starter += ['按本条工具名定位对象元数据，核对原音频标识、提取配方、版本、维度与训练测试划分，再复用现有特征。']
    elif subtype == 'model_weights':
        starter += ['先核对本地配置、分词器或处理器和权重文件是否相互匹配，再在独立环境中用非敏感小样例验证输入输出。']
    elif subtype in ('artifact', 'collection'):
        starter += ['先读本条索引、清单或实验说明，沿原始记录 ID 找到真实输入；不把整理工件当作新增样本。']
    elif subtype == 'directory_collection':
        starter += ['先取得该分支的 README 或顶层清单，再确认实际内容与负责人；目录名称仅供定位，不据名称认定数据类型或用途。']
    else:
        starter += ['先核对来源、任务和标注映射；抽样检查可用性后再设计实验，保留原始 ID 与数据划分。']
    if raw.get('复用说明'):
        starter.append(raw['复用说明'])
    caveats = unique([raw.get('行的含义', ''), raw.get('复用说明', '')])
    if subtype == 'model_weights':
        caveats.append('配置与权重存在不代表已通过加载或推理；本次未运行模型。')
    if subtype == 'directory_collection':
        caveats.append('仅有浅层目录发现证据，未确认该分支是独立数据集或完整模型。')
    return {'summary': summary, 'background': activity,
            'research_uses': [], 'contents': unique(contents), 'getting_started': unique(starter),
            'caveats': caveats, 'sources': [], 'topics': [], 'modalities': [], 'languages': [],
            'confidence': 'local_evidence', 'provenance_note': '说明依据本条公共区台账或目录核验；没有补造未观察到的样本、标签或模型能力。',
            'evidence_basis': ['data/catalog.json / ' + asset['id']], 'provenance': []}


def integrate_research(asset, item, annotation=None):
    research = local_research(asset, item)
    annotation = annotation or {}
    for field in TEXT_FIELDS:
        if annotation.get(field):
            research[field] = annotation[field]
    for source_key, target_key in (('research_uses', 'research_uses'), ('contents', 'contents'),
                                   ('starter_notes', 'getting_started'), ('caveats', 'caveats'),
                                   ('topics', 'topics'), ('modalities', 'modalities'), ('languages', 'languages')):
        research[target_key] = unique(annotation.get(source_key, []) + research[target_key])
    research['confidence'] = annotation.get('confidence', research['confidence'])
    research['evidence_basis'] = annotation.get('evidence_basis', []) + research['evidence_basis']
    research['sources'] = [{**source, 'label': source.get('title', source.get('label')),
                            'scope': source.get('scope') or '研究背景与工具用途；不作为本地完整性、许可、发布版本或可运行性证据。'}
                           for source in annotation.get('sources', [])]
    if annotation.get('_provenance'):
        research['provenance'] = [annotation['_provenance']]
    if annotation.get('inference_io'):
        research['inference_io'] = annotation['inference_io']
    research['reviewed_at'] = annotation.get('_provenance', {}).get('reviewed_at')
    # A location/permission check does not re-observe the local content used by
    # these explanations. Keep that evidence date separate from current checks.
    historical = (item.get('storage') or {}).get('historical') or {}
    research['local_observed_at'] = historical.get('observed_at') or item['checks']['observed_at']
    return research


def compact_gaps(item):
    """Remove only explained editorial gaps; preserve every publication unknown."""
    research = item['documentation']['research']
    completed = {'description'} if research.get('summary') else set()
    if research.get('background'):
        completed.add('background')
    if research.get('research_uses'):
        completed.add('research_uses')
    gaps = [dict(gap) for gap in item['gaps'] if gap['field'] not in completed]
    for gap in gaps:
        if gap['field'] == 'content_validation':
            gap['reason'] = ('未验证模型能否在本机加载或完成推理。' if item['kind'] == 'model' else
                             '尚未逐文件或逐样本核验完整性与内容；本地文件统计和官方背景不能替代该核验。')
    return gaps
