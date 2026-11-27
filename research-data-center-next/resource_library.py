"""Read-only browsing view of the server catalog and the supplemental Feishu ledger."""

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit


TALKBANK_CLASS = {
    "asd": "autism", "biling": "conversation", "ca": "conversation",
    "childes": "child-language", "class": "language-learning", "fluency": "fluency",
    "homebank": "child-language", "open": "linguistics-material", "phon": "speech-sound",
    "psyling": "linguistics-material", "samtale": "conversation", "slabank": "language-learning",
}
TALKBANK_LABEL = {
    "asd": "ASDBank", "biling": "双语语料", "ca": "CABank", "childes": "CHILDES",
    "class": "ClassBank", "fluency": "FluencyBank", "homebank": "HomeBank",
    "open": "开放材料", "phon": "PhonBank", "psyling": "PsyLing",
    "samtale": "丹麦口语资料", "slabank": "SLABank",
}
TALKBANK_NON_CORPUS = {"ca/Examples", "fluency/Examples", "open/APROCSA-training", "open/general"}
LANGUAGE_LABEL = {
    "Chinese": "中文", "Clinical": "临床资料", "Clinical-Eng": "英语临床资料",
    "Clinical-Other": "其他临床资料", "Dutch": "荷兰语", "EastAsian": "东亚语种",
    "Eng-AAE": "非裔美国英语", "Eng-NA": "北美英语", "Eng-UK": "英国英语",
    "English": "英语", "French": "法语", "German": "德语", "Greek": "希腊语",
    "Italian": "意大利语", "Japanese": "日语", "Mandarin": "普通话",
    "Spanish": "西班牙语", "Biling": "双语", "Other": "其他语言",
}
LOCAL_TITLES = {
    "clinical_audio_date_label_lexical_20260929_r360": "临床录音日期与标签词汇核对",
    "clinical_audio_date_lead_20260929_r357": "临床录音日期线索",
    "clinical_audio_date_lead_catalog_20260929_r359": "临床录音日期线索目录",
    "clinical_audio_date_lead_overlap_20260929_r358": "临床录音日期线索交叉核对",
    "clinical_audio_date_lead_semantics_20260929_r361": "临床录音日期字段释义",
    "clinical_candidate_context_20260929_r356": "临床语音候选来源说明",
    "clinical_other_roots_20260929_r362": "其他临床语音目录排查",
    "clinical_other_roots_db_20260929_r363": "其他临床语音索引",
    "clinical_sheet_full_20260929_r355": "临床语音清点表",
    "clinical_voice_agent_candidate_20260929_r364": "临床语音候选条目",
    "cross_language_task_moe_v1_sources": "跨语言认知语音研究的公开来源包",
    "BedeSpeech公开原始ZIP": "BedeSpeech 孟加拉语认知语音原始包",
    "parlo_campplus_cross_task_20260929_r353": "PARLO 跨任务说话人分析",
    "parlo_campplus_role_reference_20260929_r354": "PARLO 说话人角色参考资料",
    "parlo_target_turns_r337_code": "PARLO 目标话轮整理代码",
    "parlo_target_turns_r337_private": "PARLO 目标话轮音频",
    "parlo_target_turns_r337_receipts": "PARLO 目标话轮整理回执",
    "picture_audio_gateway_v1_20260918": "看图语音质检与说话人复核",
    "picture_feature_bundle_v1_staging_20260919": "看图语音特征整理记录",
    "research_platform": "科研共享数据与特征总入口",
    "feature_library/common": "统一特征库的公共输入",
    "ad_speech_full_feature_benchmark_20260622_v1": "认知语音多组特征对照实验",
    "ad_speech_interpretable_8group_first_result_20260628_v2_progress": "认知语音八组可解释特征实验进展",
    "ad_speech_interpretable_8group_mingfan_full_strict_schema_20260627_v1": "认知语音八组可解释特征实验（严格字段版）",
    "ad_speech_multilingual_benchmark_20260623_v6_pitt_cookie_interpretable_qwen": "Pitt Cookie Theft 多语言认知实验工件",
    "costa-reproduction-20260906": "COSTA 复现实验记录",
    "hc_mci_ad_temporal_v15_20260810": "认知分组的时序建模实验",
    "stateful-cognitive-gate1": "认知状态建模第一阶段实验",
    "stateful-cognitive-real-r24-20260907": "认知状态建模 R24 实验",
    "voice-health-encoder-20260908": "声音健康编码器早期实验",
    "chinese_dementia_audio_pilot": "中文认知相关公开音频试点",
    "topic_patient_audio": "病理主题公开素材的检索与审阅入口",
    "topic_precision_review_20260717_v2": "公开语音主题筛选复核",
}
FEATURE_TITLES = {
    "egemaps_voice_quality": "eGeMAPS 声学特征", "emotion2vec_plus_large_20s": "emotion2vec+ 情绪语音表示",
    "qwen3_embedding_06b_s4_text": "Qwen3-Embedding 文本向量", "time-frequency": "时频特征",
    "wav2vec2_large_lv60": "Wav2Vec2 Large LV60 语音表示", "wavlm_large": "WavLM Large 语音表示",
    "whisper_large_v3_encoder": "Whisper Large v3 编码器表示", "xlm_roberta_asr": "XLM-RoBERTa 文本表示",
}
PUBLIC_STATUS = {
    "verified": "已登记", "documented": "有来源记录", "discovered": "目录已发现",
    "missing": "待定位", "partial": "已核对部分", "restricted": "访问受限",
}
COUNT_SUFFIX = {
    "全部可见文件（不等于数据样本）": "个可见文件",
    "音频文件/候选文件（非独立录音或人数）": "个音频或候选文件",
    "已识别特征文件（非独立录音或人数）": "个特征文件",
    "压缩包文件（包内音频数量未据此推定）": "个压缩包",
    "目录直接文件数（不是权重数或样本数）": "个模型目录文件",
}
FEISHU_RECORD_ID = re.compile(r"rec[A-Za-z0-9]{4,60}\Z")
CARD_URL = re.compile(r"/docs/cards/reg-[a-zA-Z0-9-]+\.html\Z")
SECRET_PARAMS = {"access_token", "api_key", "app_secret", "key", "password", "signature", "token"}


def read_document(root, filename):
    return json.loads((root / filename).read_text(encoding="utf-8"))


def taxonomy_index(categories):
    return {child["id"]: (category, child) for category in categories for child in category["children"]}


def safe_url(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
        query = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    except ValueError:
        return None
    if parsed.scheme == "https" and parsed.hostname and not (parsed.username or parsed.password) and not (query & SECRET_PARAMS):
        return value
    return None


def first_source(research):
    for source in research.get("sources", []):
        url = safe_url(source.get("url"))
        if url:
            return url
    return None


def model_subcategory(name):
    lowered = name.lower()
    if "midasheng" in lowered:
        return "spatial-audio"
    if any(part in lowered for part in ("asr", "whisper", "forcedaligner")):
        return "speech-recognition"
    if any(part in lowered for part in ("wav2vec", "wavlm")):
        return "audio-representation"
    if any(part in lowered for part in ("qwen", "bge", "roberta")):
        return "language-models"
    return "directory-only"


def catalog_subcategory(entry, group, legacy_name):
    if entry["kind"] == "model":
        return model_subcategory(legacy_name)
    if group.startswith("talkbank/"):
        bank = group.split("/", 1)[1]
        return TALKBANK_CLASS.get(bank, "voice-collection")
    if group == "datasets/talkbank":
        return "voice-collection"
    if group == "easystore/research_platform":
        return "shared-feature"
    if group in {"easystore/clinical", "easystore/parlo", "wuwangwo/experiments"}:
        return "cognitive-research"
    if group == "easystore/other":
        return "picture-description" if legacy_name.startswith("picture_") else "cognitive-cohorts"
    if group in {"wuwangwo/prod", "wuwangwo/staging"}:
        return "application-material" if entry["subtype"] != "directory_collection" else "directory-only"
    if group == "wuwangwo/fmn" and legacy_name.startswith(("topic", "public_audio_crawler", "chinese_dementia")):
        return "candidate-material"
    return "directory-only"


def catalog_title(entry, group, legacy_name):
    if group.startswith("talkbank/"):
        parts = entry["display_name"].split("/")
        label = TALKBANK_LABEL.get(parts[1], parts[1]) if len(parts) > 1 else "TalkBank"
        if len(parts) == 2:
            return label + " 资料入口"
        return LANGUAGE_LABEL.get(parts[-1], parts[-1]) + " · " + label
    if entry["display_name"] in LOCAL_TITLES:
        return LOCAL_TITLES[entry["display_name"]]
    if legacy_name in LOCAL_TITLES:
        return LOCAL_TITLES[legacy_name]
    if group.startswith("wuwangwo/"):
        titles = {"call_transcripts": "应用通话与转写", "scale_recordings": "量表交互录音", "demo": "演示资料目录",
                  "migrations": "数据迁移目录", "public_media": "媒体资料目录", "storage": "存储目录",
                  "call-transcripts-dev": "通话转写开发目录", "family_guard_avatars": "家庭守护形象资料",
                  "family_guard_avatars-dev": "家庭守护形象开发目录"}
        if legacy_name in titles:
            environment = {"prod": "生产环境", "staging": "预发布环境"}.get(group.split("/")[1])
            return titles[legacy_name] + (f" · {environment}" if environment else "")
        platform = next((label for key, label in (("bilibili", "哔哩哔哩"), ("douyin", "抖音"), ("xiaohongshu", "小红书")) if key in legacy_name), None)
        if platform:
            phase = "预筛选" if "prefilter" in legacy_name else "整理"
            revision = " · 第二版" if legacy_name.endswith("-v2") else ""
            return platform + "主题语音候选" + phase + revision
    return FEATURE_TITLES.get(legacy_name, entry["display_name"])


def catalog_role(entry, group, research, legacy_name):
    kind, subtype = entry["kind"], entry["subtype"]
    if kind == "model":
        return "训练交付" if "MiDasheng" in legacy_name else {"model_weights": "模型权重", "directory_collection": "模型目录"}.get(subtype, "模型资料")
    if group.startswith("talkbank/"):
        name = entry["display_name"].removeprefix("TalkBank/")
        if name in TALKBANK_NON_CORPUS or group in {"talkbank/open", "talkbank/psyling"}:
            return "样例与学术资料"
        return "子库目录" if research.get("confidence") != "official_match" else "语料入口"
    if legacy_name.startswith("parlo_target_turns_r337_private"):
        return "派生录音"
    if legacy_name.startswith("topic_patient_crawler-code"):
        return "工程工件"
    if group == "wuwangwo/fmn" and legacy_name.startswith(("topic", "public_audio_crawler", "chinese_dementia")):
        return "候选素材" if subtype == "dataset" else "候选整理工件"
    return {"artifact": "实验与整理工件", "feature": "派生特征", "directory_collection": "目录入口", "collection": "清单或资料集合"}.get(subtype, "数据资料")


def concise_text(value):
    text = " ".join(value.split())
    for prefix in ("官方介绍", "官方说明", "官方索引", "官方将此语料描述为", "官方将该组描述为"):
        if text.startswith(prefix):
            return text.removeprefix(prefix).lstrip("：: ")
    return text


def catalog_summary(entry, group, research, legacy_name, title):
    if group == "easystore/clinical":
        return f"{title}的历史整理文件。适合追溯原数据入口与清点过程，正式分析前需核对所引用的录音清单。"
    if group == "easystore/parlo":
        details = {
            "parlo_target_turns_r337_code": "整理派生话轮的代码目录，可用于复现切段与说话人筛选。",
            "parlo_target_turns_r337_private": "从原始访谈整理出的目标说话人话轮，可用于提取角色相关的语音特征。",
            "parlo_target_turns_r337_receipts": "话轮整理回执，可用于追溯派生文件和处理批次。",
            "parlo_campplus_cross_task_20260929_r353": "用于检查不同任务中说话人表示的研究记录，可追溯到相应清单。",
            "parlo_campplus_role_reference_20260929_r354": "用于复核参与者和访谈者角色的参考资料，适合与原始清单对照。",
        }
        return "PARLO 是面向认知研究的德语临床语音库，包含命名、叙事和复述等任务。" + details.get(legacy_name, "这个入口保存团队已有的整理资料。")
    if group == "wuwangwo/experiments":
        lead = {
            "ad_speech_full_feature_benchmark_20260622_v1": "比较多类语音特征在认知任务中的表现。",
            "ad_speech_interpretable_8group_first_result_20260628_v2_progress": "记录八组可解释特征的初步实验结果。",
            "ad_speech_interpretable_8group_mingfan_full_strict_schema_20260627_v1": "记录八组语音特征在统一字段约定下的历史实验。",
            "ad_speech_multilingual_benchmark_20260623_v6_pitt_cookie_interpretable_qwen": "围绕 Pitt 看图叙事整理的认知语音实验资料。",
            "costa-reproduction-20260906": "用于追溯 COSTA 实验的复现内容和产物。",
            "hc_mci_ad_temporal_v15_20260810": "研究健康对照、轻度认知障碍与阿尔茨海默病分组中的时序表示。",
            "stateful-cognitive-gate1": "保存认知状态建模第一阶段的准备与实验记录。",
            "stateful-cognitive-real-r24-20260907": "保存认知状态建模 R24 批次的历史工件。",
            "voice-health-encoder-20260908": "保存声音健康编码器的早期研究包。",
        }.get(legacy_name, "保存历史认知语音实验资料。")
        return lead + "复用时从原实验说明核对输入、划分和指标。"
    if group == "wuwangwo/fmn" and legacy_name.startswith("topic_patient_crawler-code"):
        return "按病理主题寻找公开语音的工程整理版本，可追溯检索、转写或筛查的实现。术语与筛选结果需回原资料核对。"
    if group == "wuwangwo/fmn" and legacy_name.startswith("topic_patient_media"):
        return f"{title}阶段留下的公开录音线索和审阅记录。适合复核采样来源、标注依据与使用条件。"
    if legacy_name == "research_platform":
        return "已有共享科研资料的导航入口。通过目录、清单和版本说明寻找公共输入、派生特征及相应研究。"
    if entry["display_name"] == "feature_library/common":
        return "统一特征库的公共输入和派生资料，含音频引用及转写、表达、时间线和言语行为等结构化结果。复用时需核对清单、处理版本和授权。"
    if legacy_name == "modelscope":
        return "ModelScope 模型缓存的目录入口，可从此定位已登记的模型存放位置。具体模型列表及权重完整性仍需核对。"
    if entry["subtype"] == "directory_collection" and not research.get("sources"):
        return "历史目录登记，可从原卡查询位置和上级资料。目录中的文件范围、标签与用途待核对。"
    if legacy_name.startswith("Qwen3-") and model_subcategory(legacy_name) == "language-models":
        return f"{legacy_name} 是 Qwen3 系列的文本生成模型，可用于总结、信息提取和问答。比较不同尺寸时可固定提示词与评测集。"
    if legacy_name == "faster-whisper-large-v3-turbo":
        return "Whisper large-v3-turbo 的 CTranslate2 转换权重，适合用 faster-whisper 运行语音转写。使用前需核对本地模型版本和加载配置。"
    background = research.get("background")
    if background:
        summary = concise_text(background)
        if summary and summary[-1] not in ".。！？":
            summary += "。"
        return summary
    return "现有科研资料的登记入口，可通过原卡核对来源与研究条件。"


def count_label(documentation):
    quantity = documentation.get("quantity", {})
    value = quantity.get("primary_value")
    unit = quantity.get("unit")
    if value is None or not unit:
        return None
    display = f"{int(value):,}" if str(value).isdigit() else str(value)
    return f"{display} {COUNT_SUFFIX.get(unit, unit)}"


def catalog_cards(mapping, classifications):
    groups = {group["id"]: group["key"] for group in mapping["groups"]}
    items = []
    for entry in mapping["items"]:
        group = groups.get(entry["group_id"], "")
        original_title = entry["display_name"]
        legacy_name = original_title.split(" · ")[-1].split("/")[-1]
        title = catalog_title(entry, group, legacy_name)
        documentation = entry.get("documentation", {})
        research = documentation.get("research", {})
        category, child = classifications[catalog_subcategory(entry, group, legacy_name)]
        card_url = entry.get("card_url")
        detail_url = card_url if isinstance(card_url, str) and CARD_URL.fullmatch(card_url) else None
        use_cases = [concise_text(text.removeprefix("研究建议：")) for text in research.get("research_uses", [])][:2]
        items.append({
            "id": entry["asset_id"], "registry_id": entry["registry_id"], "title": title,
            "aliases": [original_title] if original_title != title else [], "kind": entry["kind"],
            "category_id": category["id"], "subcategory_id": child["id"],
            "role": catalog_role(entry, group, research, legacy_name),
            "summary": catalog_summary(entry, group, research, legacy_name, title), "use_cases": use_cases,
            "usage_note": "使用前核对原资料范围、版本和授权。" if entry["kind"] == "dataset" else "使用前核对权重版本、配置和许可。",
            "source": "catalog", "source_url": first_source(research) or detail_url, "detail_url": detail_url,
            "api_url": f"/api/resource-mapping/{entry['registry_id']}",
            "status": PUBLIC_STATUS.get(entry.get("source_status"), "已登记"),
            "count_label": count_label(documentation), "count_observed_at": documentation.get("quantity", {}).get("as_of"),
            "observed_at": (entry.get("checks") or {}).get("observed_at"),
            "languages": research.get("languages", []), "formats": entry.get("formats", []),
        })
    return items


def feishu_live_cards(snapshot, override, classifications):
    known = {row["id"]: row for row in snapshot["items"]}
    labels = {(parent["label"], child["label"]): (parent, child) for parent, child in classifications.values()}
    items, seen = [], set()
    if not isinstance(override, dict) or not isinstance(override.get("rows"), list):
        raise ValueError("invalid Feishu library response")
    observed_at = override.get("observed_at")
    if not isinstance(observed_at, str) or datetime.fromisoformat(observed_at.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("missing timezone in Feishu observation")
    for row in override["rows"]:
        if not isinstance(row, dict):
            raise ValueError("invalid Feishu record")
        record_id = row.get("id")
        name = row.get("数据名称")
        if not isinstance(record_id, str) or not FEISHU_RECORD_ID.fullmatch(record_id) or record_id in seen:
            raise ValueError("invalid Feishu record identity")
        seen.add(record_id)
        if not isinstance(name, str) or not name.strip():
            continue
        record = known.get(record_id)
        # A renamed record may represent a replacement. Review the original description before reusing it.
        if record and record["title"] == name.strip():
            item = dict(record)
        else:
            item = {
                "id": record_id, "kind": "dataset", "role": "飞书台账资料", "source": "feishu",
                "category_id": "unconfirmed", "subcategory_id": "directory-only",
                "summary": "请查阅飞书原记录，核对资料内容、获取进展与使用条件。",
                "use_cases": [], "usage_note": "使用条件见原表。", "count_label": None, "detail_url": None,
            }
        item["title"] = name.strip()[:200]
        parent_label, child_label = row.get("研究大类"), row.get("细分类")
        pair = labels.get((parent_label, child_label)) if isinstance(parent_label, str) and isinstance(child_label, str) else None
        if pair:
            item["category_id"], item["subcategory_id"] = pair[0]["id"], pair[1]["id"]
        if "一级标签" in row:
            item["theme_label"] = row["一级标签"] if isinstance(row["一级标签"], str) else ""
        status = row.get("当前进度")
        item["status"] = " ".join(status.split())[:64] if isinstance(status, str) and status.strip() else "待核对"
        item["observed_at"] = observed_at
        item["source_url"] = snapshot["url"] + "&" + urlencode({"record": record_id})
        items.append(item)
    return items


def library_payload(data_root, *, ledger_override=None):
    """Build the library projection. Optional Feishu rows override the bundled dated snapshot."""
    data_root = Path(data_root)
    mapping = read_document(data_root, "resource-mapping.json")
    taxonomy = read_document(data_root, "library-taxonomy.json")
    categories = taxonomy["categories"]
    classifications = taxonomy_index(categories)
    catalog = catalog_cards(mapping, classifications)
    snapshot = read_document(data_root, "feishu-library.json")
    ledger_items, ledger_observation, ledger_mode = snapshot["items"], snapshot["observed_at"], "snapshot"
    if ledger_override is not None:
        cached = feishu_live_cards(snapshot, ledger_override, classifications)
        cache_time = datetime.fromisoformat(ledger_override["observed_at"].replace("Z", "+00:00"))
        bundled_time = datetime.fromisoformat(ledger_observation.replace("Z", "+00:00"))
        if cache_time >= bundled_time:
            ledger_items = cached
            ledger_observation, ledger_mode = ledger_override["observed_at"], "live"
    themes = taxonomy.get("themes", [])
    by_label = {theme["label"]: theme["id"] for theme in themes}
    by_subcategory = {child: theme["id"] for theme in themes for child in theme["subcategories"]}
    for item in catalog + ledger_items:
        if "theme_label" in item:
            item["theme_id"] = by_label.get(item.pop("theme_label"), "unconfirmed")
        else:
            item["theme_id"] = by_subcategory.get(item["subcategory_id"], "unconfirmed")
    theme_order = {theme["id"]: position for position, theme in enumerate(themes)}
    ledger_items.sort(key=lambda item: theme_order.get(item["theme_id"], len(themes)))
    return {
        "schema_version": "1.0",
        "themes": [{"id": theme["id"], "label": theme["label"]} for theme in themes],
        "categories": categories,
        "sources": [
            {"id": "catalog", "label": "服务器资料目录", "url": "/api/summary", "count": len(catalog),
             "observed_at": mapping.get("generated_at"), "mode": "snapshot"},
            {"id": "feishu", "label": "飞书数据与申请台账", "url": snapshot["url"], "count": len(ledger_items),
             "observed_at": ledger_observation, "mode": ledger_mode},
        ],
        "items": catalog + ledger_items,
    }
