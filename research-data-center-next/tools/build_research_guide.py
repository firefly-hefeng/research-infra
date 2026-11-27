"""Build an editorial research guide, with membership/counts from the inventory."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(label, url, scope='介绍上游项目背景；不证明本地副本完整或可直接使用。'):
    return {'label': label, 'url': url, 'scope': scope}


CATEGORIES = [
    {'id': 'mood', 'label': '抑郁与情绪健康', 'group_keys': [],
     'intro': '当前清册暂无已确认的抑郁或情绪障碍专用数据。DepAlign、MMPsy 和 Daily Text Risk 的模型成果在成果进展中心展示，不用模型名称反推数据已入库。',
     'use_cases': ['后续接收经审核的抑郁访谈、严重度评分和情绪表达资料。'],
     'first_steps': ['先核对数据是否正式入库；研究成果与数据资源分开阅读。'], 'sources': []},
    {'id': 'cognitive', 'label': '认知障碍与认知健康',
     'group_keys': ['easystore/clinical', 'easystore/parlo', 'easystore/other', 'wuwangwo/experiments'],
     'intro': '包括 Pitt Cookie Theft 看图叙事、PARLO 目标话轮、认知语音质检和已有实验工件。原件、派生副本、代码和运行目录分别登记，适合追溯认知语音研究。',
     'use_cases': ['追溯认知语音实验的数据准备与处理过程。', '复用已确认的目标话轮或质量检查结果，核对与原始资料的对应关系。'],
     'first_steps': ['先看资料角色：来源数据、派生音频、索引、代码或运行目录的使用方式不同。', '优先从有明确来源和任务说明的条目开始；实验分支不是固定版本。'],
     'sources': [source('本地资源清册与原始台账', '/docs/resource-inventory.html', '依据本地台账、有限目录观察及已读取的说明文件；未把候选素材认定为临床标签数据。')]},
    {'id': 'parkinson', 'label': '帕金森与运动障碍', 'group_keys': [],
     'intro': '当前清册暂无已确认的帕金森或运动障碍专用数据。', 'use_cases': ['后续按正式来源接收相关语音与运动障碍资料。'],
     'first_steps': ['没有已确认资源时不生成代表性数据集或数量。'], 'sources': []},
    {'id': 'speech-disorder', 'label': '病理言语、流畅性与嗓音',
     'group_keys': ['talkbank/fluency'],
     'intro': '以 FluencyBank 流畅性研究材料为入口。这里按研究主题组织，不把流畅性材料扩写为特定疾病标签。',
     'use_cases': ['在任务和标签经过核对的条件下研究流畅性、发音或交流行为。'],
     'first_steps': ['先查看语料卡的研究背景、标注说明和来源，再确定分析指标。', '确认受试者分组、采集任务及上游访问条件；目录名和语音表现不能替代标签证据。'],
     'sources': [source('FluencyBank：流畅性研究', 'https://talkbank.org/fluency/')]},
    {'id': 'respiratory', 'label': '呼吸、咳嗽与睡眠声音', 'group_keys': [],
     'intro': '当前清册暂无已确认的呼吸、咳嗽或睡眠声音专用数据。', 'use_cases': ['后续接收有明确来源与使用条件的呼吸和睡眠声音资料。'],
     'first_steps': ['没有已确认资源时不生成代表性数据集或数量。'], 'sources': []},
    {'id': 'cardiovascular', 'label': '心音与循环系统', 'group_keys': [],
     'intro': '当前清册暂无已确认的心音或循环系统专用数据。', 'use_cases': ['后续接收心音、心电及循环系统相关研究资料。'],
     'first_steps': ['没有已确认资源时不生成代表性数据集或数量。'], 'sources': []},
    {'id': 'development', 'label': '儿童语言与发育',
     'group_keys': ['talkbank/asd', 'talkbank/childes', 'talkbank/phon', 'talkbank/homebank'],
     'intro': '以 ASDBank、CHILDES、PhonBank 和 HomeBank 为入口，理解儿童语言、发音和家庭交流环境中的发展研究。',
     'use_cases': ['研究词汇、句法与发音随发展阶段的变化。', '比较家庭互动、语言背景与儿童表达；先核对年龄、任务和标注是否可比。'],
     'first_steps': ['从 CHILDES 的语言分支或 PhonBank 的具体语料卡开始，确认研究对象与采集任务。', '需要转录分析时，再检查本地是否配有 CHAT 转录和时间对齐；音频镜像的存在不能替代这一步。'],
     'sources': [source('CHILDES：儿童语言资料体系', 'https://talkbank.org/childes/'), source('Frogs：无字图画书诱发的叙事研究', 'https://talkbank.org/childes/access/Frogs/'), source('PhonBank：儿童音系研究', 'https://talkbank.org/phon/')]},
    {'id': 'general-speech', 'label': '通用语音、多语与情绪',
     'group_keys': ['talkbank/biling', 'talkbank/ca', 'talkbank/class', 'talkbank/open', 'talkbank/psyling', 'talkbank/samtale', 'talkbank/slabank'],
     'intro': '覆盖自然对话、课堂互动、双语、心理语言和一般语音材料。没有足够疾病证据的条目留在通用类，不强行归入临床类别。',
     'use_cases': ['研究轮次交替、互动结构、课堂问答、多语和一般语音表达。', '为转写、说话人处理或语言分析寻找与研究任务接近的材料。'],
     'first_steps': ['先按交流场景选子库，再读具体语料的语言、参与方式和来源介绍。', '将录音、转录、说话人标注分开核对；课程材料和示例集不自动构成可比较的基准。'],
     'sources': [source('TalkBank：会话、语言发展与多语分库', 'https://talkbank.org/'), source('CORAAL：地区语言变异与 TalkBank 转换', 'https://talkbank.org/ca/access/CORAAL.html')]},
    {'id': 'cross-disease', 'label': '跨疾病与共享方法资源',
     'group_keys': ['datasets/talkbank', 'easystore/research_platform', 'models/direct', 'models/huggingface', 'models/modelscope'],
     'intro': '包括 TalkBank 总入口、共享特征库、转写/对齐模型和通用模型资源。它们服务多种疾病与非疾病研究，资源角色必须与疾病标签分开理解。',
     'use_cases': ['比较传统声学描述量与学习型表示，减少重复提取。', '为转写、对齐、文本处理与特征提取寻找已有模型，避免重复下载。'],
     'first_steps': ['核对原始音频或文本标识、截取窗口、工具版本与提取配置，再选择特征或模型。', '确认 revision、运行依赖与使用条件后再运行；缓存或权重入口不代表推理验收完成。'],
     'sources': [source('openSMILE：标准特征集与提取层级', 'https://audeering.github.io/opensmile-python/'), source('本地模型卡及逐模型官方链接', '/docs/resource-inventory.html', '具体官方模型文档列在各模型卡；这里不把缓存集合认定为完整模型。')]},
    {'id': 'unconfirmed', 'label': '待确认的研究资料',
     'group_keys': ['wuwangwo/fmn', 'wuwangwo/prod', 'wuwangwo/staging'],
     'intro': '包含公开候选素材、业务通话、量表交互录音、爬虫代码和运行目录。现有说明不足以确立具体疾病标签，不能整组提升为临床资源。',
     'use_cases': ['逐条核对候选素材、运行工件和公开媒体的真实身份与使用条件。'],
     'first_steps': ['先补齐资源名称、来源、角色和许可，再决定是否归入疾病类别。', '未知类别不是低质量或不可用，只是当前证据不足。'],
     'sources': [source('本地资源清册与原始台账', '/docs/resource-inventory.html', '保留未知项和待补说明，不凭路径推断疾病或数据血缘。')]},
]


def build_guide(mapping):
    groups = {group['key']: group for group in mapping['groups']}
    expected = [key for category in CATEGORIES for key in category['group_keys']]
    if len(expected) != len(set(expected)) or set(expected) != set(groups):
        raise ValueError('Inventory groups changed; review research categories before rebuilding.')
    categories = copy.deepcopy(CATEGORIES)
    seen = set()
    for category in categories:
        category['group_ids'] = [groups[key]['id'] for key in category.pop('group_keys')]
        members = [item for item in mapping['items'] if item['group_id'] in category['group_ids']]
        category['asset_ids'] = [item['asset_id'] for item in members]
        if seen.intersection(category['asset_ids']):
            raise ValueError('An entry belongs to multiple primary research categories.')
        seen.update(category['asset_ids'])
        category['counts'] = {'records': len(members), 'unique_paths': len({item['current_path'] for item in members})}
    if seen != {item['asset_id'] for item in mapping['items']}:
        raise ValueError('Research guide does not cover the inventory exactly once.')
    return {
        'schema_version': '1.0', 'generated_at': datetime.now(timezone.utc).isoformat(),
        'reviewed_at': '2026-10-31', 'catalog_sha256': mapping['catalog_sha256'],
        'title': '按疾病与研究方向找资料',
        'introduction': '先按疾病或研究领域展开，再按原始数据、派生资料、特征、模型和实验工件理解资源角色。没有证据的类别明确留空，待确认资料不强行归类。',
        'coverage': {'records': len(seen), 'category_count': len(categories), 'assignment': '每条登记记录归入一个主要疾病/研究领域；资源角色另列，类别不是数据血缘或实验结论。'},
        'categories': categories,
        'newcomer_steps': [
            {'title': '01 · 先选疾病领域与资源角色', 'description': '先确定研究领域，再区分原始数据、派生资料、特征、模型和实验工件。不同角色服务不同研究步骤。'},
            {'title': '02 · 读一张完整资料卡', 'description': '查看背景、用途、任务、语言、当前路径和数量单位；再对照来源与待补事项。迁移计划、旧路径兼容与已核验当前位置分别阅读。'},
            {'title': '03 · 在自己的实验目录验证', 'description': '取得相应使用权限后，用少量材料验证读取、转写或特征流程，记录资源ID、版本与配方；再开展完整实验。公共资料采用清册中已核验的当前位置；实验输出写入自己的工作区，不改公共原件。'},
        ],
        'terms': [
            {'term': '语料库 / corpus', 'description': '为语言或交流研究收集的材料集合，可能包含录音、视频、转录和标注；某个本地镜像不一定包含全部组成部分。'},
            {'term': '声学特征与学习型表示', 'description': '前者按预定义方法描述声音，后者由模型提取向量表示；二者都属于从原资料产生的特征，需要保留提取配置。'},
            {'term': 'ASR 与强制对齐', 'description': 'ASR 从语音生成文字；强制对齐通常结合语音和已有文字定位时间边界。两种任务不能用同一输出假定替代。'},
            {'term': '登记记录 / 集合 / 版本', 'description': '一条登记记录是目前的资料入口；集合可以包含多个语料，冻结版本才是可稳定复现的特定发布状态。'},
        ],
        'tips': [
            '数量先看单位：文件、音频、片段、参与者与目录记录是不同概念，不能互相代换。',
            '“经典”或“常用”应落实到具体语料与研究传统；本地保存、来源知名和质量验收是三件事。',
            '比较实验时先核对任务、语言、参与者切分和处理流程，避免把不同来源的差异误当成模型能力。',
            '公共区表示团队共享存放范围；许可、账户读取权限和研究用途仍以具体条目及来源条件为准。',
            '待确认只表示分类证据不足，不代表资料不可用；不得为了填满疾病类别而猜测。',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    root = parser.parse_args().root
    mapping = json.loads((root/'data/resource-mapping.json').read_text(encoding='utf-8'))
    guide = build_guide(mapping)
    (root/'data/research-guide.json').write_text(json.dumps(guide, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'categories': len(guide['categories']), 'records': guide['coverage']['records'],
                      'counts': {c['id']: c['counts']['records'] for c in guide['categories']}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
