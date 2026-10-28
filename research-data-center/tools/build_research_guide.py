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
    {'id': 'language-development', 'label': '儿童语言与语音发展',
     'group_keys': ['talkbank/childes', 'talkbank/phon', 'talkbank/homebank'],
     'intro': '以 CHILDES、PhonBank 和 HomeBank 分支为入口，理解儿童如何学习语言、形成发音，以及家庭交流环境中的语言使用。CHILDES 是长期积累的儿童语言研究资料体系；例如 Frogs 集合通过无字图画书诱发叙事，可帮助理解跨语言的故事表达研究。',
     'use_cases': ['研究词汇、句法与发音随发展阶段的变化。', '比较家庭互动、语言背景与儿童表达；先核对年龄、任务和标注是否可比。'],
     'first_steps': ['从 CHILDES 的语言分支或 PhonBank 的具体语料卡开始，确认研究对象与采集任务。', '需要转录分析时，再检查本地是否配有 CHAT 转录和时间对齐；音频镜像的存在不能替代这一步。'],
     'sources': [source('CHILDES：儿童语言资料体系', 'https://talkbank.org/childes/'), source('Frogs：无字图画书诱发的叙事研究', 'https://talkbank.org/childes/access/Frogs/'), source('PhonBank：儿童音系研究', 'https://talkbank.org/phon/')]},
    {'id': 'conversation-multilingual', 'label': '会话、多语与综合语料',
     'group_keys': ['talkbank/ca', 'talkbank/biling', 'talkbank/class', 'talkbank/samtale', 'talkbank/slabank', 'talkbank/open', 'datasets/talkbank'],
     'intro': '覆盖自然对话、课堂互动、双语与第二语言学习等场景。例如 CORAAL 关注非裔美国英语的地区语言变异，适合认识方言、社会语言学及语音识别的误差差异。TalkBank 各子库承担不同研究任务，本类也保留整个镜像的导航入口。',
     'use_cases': ['研究轮次交替、互动结构、课堂问答与多语交流。', '为转写、说话人处理或语言分析寻找与研究任务接近的材料。'],
     'first_steps': ['先按交流场景选子库，再读具体语料的语言、参与方式和来源介绍。', '将录音、转录、说话人标注分开核对；课程材料和示例集不自动构成可比较的基准。'],
     'sources': [source('TalkBank：会话、语言发展与多语分库', 'https://talkbank.org/'), source('CORAAL：地区语言变异与 TalkBank 转换', 'https://talkbank.org/ca/access/CORAAL.html')]},
    {'id': 'speech-communication', 'label': '言语流畅性与交流研究',
     'group_keys': ['talkbank/fluency', 'talkbank/asd', 'talkbank/psyling'],
     'intro': '包含 FluencyBank 的流畅性研究材料、ASDBank 的交流互动材料，以及本地 PsyLing 命名分支。它们关注的研究对象、任务和访问条件各不相同；PsyLing 的具体实验身份需要按条目继续核对。',
     'use_cases': ['在任务和标签经过核对的条件下研究流畅性、发音或交流行为。', '区分研究语料、教学示例和心理语言材料，选择与问题相符的比较对象。'],
     'first_steps': ['先查看语料卡的研究背景、标注说明和来源，再确定分析指标。', '确认受试者分组、采集任务及上游访问条件；目录名和语音表现不能替代标签证据。'],
     'sources': [source('FluencyBank：流畅性研究', 'https://talkbank.org/fluency/'), source('ASDBank：交流互动资料', 'https://talkbank.org/asd/'), source('PsyLing：官方站点当前定位', 'https://talkbank.org/psyling/')]},
    {'id': 'cognitive-projects', 'label': '认知健康与项目研究资料',
     'group_keys': ['easystore/clinical', 'easystore/parlo', 'easystore/other', 'wuwangwo/experiments', 'wuwangwo/fmn', 'wuwangwo/prod', 'wuwangwo/staging'],
     'intro': '来自现有研究与应用流程：包括 Pitt Cookie Theft 看图叙事的实验副本、PARLO 目标话轮与处理工件，以及质检结果、候选公开音视频和通话流程资料。它们适合追溯已有实验；原件、派生副本、代码和运行目录分别登记。',
     'use_cases': ['追溯已有认知语音实验的数据准备与处理过程。', '复用已确认的目标话轮或质量检查结果，核对与原始资料的对应关系。'],
     'first_steps': ['先看“资料角色”：来源数据、派生音频、索引、代码或运行目录的使用方式不同。', '优先从有明确来源和任务说明的条目开始；prod / staging 只表示现有存放分支，不是固定实验版本。'],
     'sources': [source('本地资源清册与原始台账', '/docs/resource-inventory.html', '依据本地台账、有限目录观察及已读取的说明文件；未把候选素材认定为临床标签数据。')]},
    {'id': 'reusable-features', 'label': '可复用声学与语言特征',
     'group_keys': ['easystore/research_platform'],
     'intro': '研究平台中已有声学描述量、语音表征和文本表征的派生缓存。eGeMAPS 属于预定义声学特征集；wav2vec 2.0、WavLM、Whisper 等条目对应不同的学习型表示。它们与原始录音、模型权重是不同层次的资源。',
     'use_cases': ['比较传统声学描述量与学习型表示，减少重复提取。', '在来源、切分和提取配方一致时复用特征开展基线实验。'],
     'first_steps': ['核对原始音频或文本标识、截取窗口、工具版本与提取配置，再选择特征。', '八种特征记录共享对象存储位置，不能把同一路径视为同一种特征，也不能将文件数相加当成样本数。'],
     'sources': [source('openSMILE：标准特征集与提取层级', 'https://audeering.github.io/opensmile-python/'), source('本地特征登记与路径映射', '/docs/resource-inventory.html', '本地特征名称、对象位置和原台账证据；各配方与输出维度以条目说明为准。')]},
    {'id': 'models', 'label': '语言、语音与检索模型',
     'group_keys': ['models/direct', 'models/huggingface', 'models/modelscope'],
     'intro': '按任务理解模型：Qwen3 用于文本生成，Qwen3-ASR 与 faster-whisper 用于语音转写，ForcedAligner 将已有文字与音频对齐；另有文本表示、检索和语音表示相关模型入口。具体卡片说明输入输出、已观察配置与本地缓存状态。',
     'use_cases': ['为转写、对齐、文本处理与特征提取寻找已有模型，避免重复下载。', '比较参数规模、架构和已有配置，再安排独立的加载与小样本验证。'],
     'first_steps': ['从模型卡查看任务、输入输出、官方用法和已观察配置。', '确认具体 revision、运行依赖与使用条件后再运行；发现权重文件并不代表已完成推理验收。'],
     'sources': [source('本地模型卡及逐模型官方链接', '/docs/resource-inventory.html', '具体官方模型文档列在各模型卡；这里不把缓存集合认定为完整模型。')]},
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
        'reviewed_at': '2026-10-19', 'catalog_sha256': mapping['catalog_sha256'],
        'title': '先理解资料，再开始研究',
        'introduction': '这座资料库以语音、语言与认知健康研究为主线：从真实交流语料，到已有研究项目，再到可复用特征和模型。下面按主要研究用途组织六个入口，帮助你先了解数据的来历与角色，再进入具体资料卡。',
        'coverage': {'records': len(seen), 'category_count': len(categories), 'assignment': '每条登记记录归入一个主要导览类别；类别不是数据血缘或实验结论。'},
        'categories': categories,
        'newcomer_steps': [
            {'title': '01 · 先选问题和资料角色', 'description': '先想清楚你要分析交流行为、做语音转写、提取特征还是复现实验。语料、派生结果、代码与模型权重分别服务这些步骤。'},
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
