"""Build a direction-specific plan and execute supported, versioned experiments on existing evidence."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import quote

try:
    from . import direction_context as dc
    from . import research_experiment_audio as audio
except ImportError:  # portal and standalone deployments also import adjacent modules
    import direction_context as dc
    import research_experiment_audio as audio


VERSION = "1.0.0"
AUDIO = "mdvr-input-sensitivity"
SEARCH = "paper-retrieval-ablation"
SPEAKER = "ravdess-speaker-split"
SPECS = {
    AUDIO: {"id": AUDIO, "title": "录音预处理的门限与截取对照",
            "question": "在同一批录音上，提高低能量门限会舍弃多少片段？固定截取 10 或 30 秒能覆盖多少录音时长？",
            "method": "读取已核验的 MDVR-KCL 公开发行包。每条录音前两秒按 20 ms 分帧，所有声道共同计算 RMS；逐录音配对比较 −50 与 −40 dBFS 保留率。"},
    SEARCH: {"id": SEARCH, "title": "方向文献的检索对照",
             "question": "使用相同的方向词，在题名之外检索标签和关键词，能额外发现哪些待阅读文献？",
             "method": "冻结同一批题录和同一组检索词。以题名命中为基线，加入分类、标签及作者关键词后比较两组候选，并记录 DOI 覆盖率。"},
    SPEAKER: {"id": SPEAKER, "title": "情绪识别评测的演员隔离对照",
              "question": "同一批语音按录音或按演员分折，训练和测试之间的演员重叠及类别比例分别怎样？",
              "method": "只读获准使用的 RAVDESS 语音发行包索引。固定种子构造两种六折划分，比较测试录音的训练演员重叠率和单折类别占比最大偏差。"},
}
TOPICS = {
    "帕金森": ("Parkinson", "Parkinson's", "MDVR-KCL"), "声源定位": ("sound localization", "source localization"),
    "语音健康": ("speech health",), "空间音频": ("spatial audio", "spatial hearing"),
    "声音表征": ("speech representation", "voice representation"), "疾病声音": ("pathological speech",),
    "语音情绪": ("speech emotion", "emotional speech"), **dc.TOPIC_ALIASES,
}


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _direction(query, sources):
    rows = sources.get("directions", {}).get("items") or []
    if not isinstance(query, str) or not query.strip() or len(query.strip()) > 180:
        raise ValueError("请输入不超过 180 字的研究方向或方向 ID。")
    query = query.strip()
    if any(dc.folded(query) in dc.folded(r.get(k, "")) for r in rows for k in ("id", "title")):
        return dc.resolve_direction(query, rows), True
    return {"id": "topic-" + digest(dc.folded(query))[:16], "title": query}, False


def _catalog(sources):
    papers = (sources.get("papers") or {}).get("papers")
    if not isinstance(papers, list):
        return None
    if len(papers) > 10000:
        raise ValueError("题录超过本版单次一万条的处理预算。")
    by_id = {}
    for p in papers:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not p["id"] or p["id"] in by_id:
            raise ValueError("题录中存在缺失或重复的文献 ID，请先核对目录。")
        bib, card, insight = (p.get(x) or {} for x in ("bibliography", "card", "insight"))
        titles = [t for t in (bib.get("title"), card.get("title")) if t]
        title = next(iter(titles), None)
        # A filename is a display fallback, not a curated title.
        tags = [bib.get("category"), card.get("category"), *(bib.get("tags") or []), *(card.get("tags") or []),
                *(insight.get("keywords") or []), *((insight.get("author_keywords") or {}).get("terms") or [])]
        by_id[p["id"]] = {"id": p["id"], "title": title or p.get("filename") or p["id"],
                         "titles": list(dict.fromkeys(t for t in titles if isinstance(t, str))),
                         "tags": sorted({t for t in tags if isinstance(t, str) and t.strip()}),
                         "doi": bib.get("doi") or card.get("doi")}
    return [by_id[i] for i in sorted(by_id)]


def _terms(direction, archive, registered):
    terms = dc.keywords(direction, [{"report": r.get("report") or {}} for r in archive], [])[0]
    title = direction["title"]
    focus = dc.folded(title + " " + (direction.get("question") or ""))
    for term, aliases in TOPICS.items():
        if term in focus or any(dc.folded(a) in focus for a in aliases):
            terms.extend((term, *aliases))
    if not registered:
        terms.insert(0, title)
        if len(title.split()) > 1 and title.isascii():
            terms = [x for x in terms if dc.folded(x) not in {"the", "and", "for", "using", "with", "from", "research", "study"}]
    return list(dict.fromkeys(dc.folded(x) for x in terms if x.strip()))[:32]


def _matcher(terms):
    patterns = [r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])" if t.isascii() else re.escape(t) for t in terms]
    regex = re.compile("|".join(patterns) if patterns else r"(?!)")
    return lambda values: any(regex.search(dc.folded(v)) for v in values if v)


def _search(catalog, terms):
    hit = _matcher(terms)
    base, extra = [], []
    for paper in catalog:
        if hit(paper["titles"]):
            base.append(paper)
        elif hit(paper["tags"]):
            extra.append(paper)
    return base, extra


def _references(rows, keys=("id", "title")):
    return [dc.selected(x, keys) for x in rows]


def build_plan(query, sources, *, allow_noncommercial=False):
    """Sources are the five existing direction dossier payloads. No paths or execution parameters are accepted."""
    direction, registered = _direction(query, sources)
    archive = sources.get("research") or {}
    findings = [r for kind in ("models", "research_tracks") for r in archive.get(kind, []) if registered and r.get("id") == direction["id"]]
    terms = _terms(direction, findings, registered)
    library = sources.get("library") or {}
    assets = library.get("items") or []
    asset = next((r for r in assets if r.get("id") == audio.RECORD and r.get("kind") == "dataset" and
                  dc.folded(r.get("title", "")) == "mdvr-kcl"), None)
    recent = dc.recent(direction["id"], sources["progress"]) if registered and sources.get("progress") else None
    context = {"terms": terms, "archive": _references(findings, ("id", "name", "summary", "validation", "status_label")),
               "report_count": recent.get("report_count") if recent else None,
               "reports": _references(recent["sources"], ("id", "title", "original_url")) if recent else []}
    categories = {r["id"]: r["label"] for r in library.get("categories", []) + library.get("themes", [])}
    for kind in ("dataset", "model"):
        result = dc.candidates([r for r in assets if r.get("kind") == kind], terms, 5, category_labels=categories)
        context[kind] = {"total": result["total"], "items": _references(result["items"], ("id", "title", "source_url", "matched_terms"))}
    catalog = _catalog(sources)
    base, extra = _search(catalog or [], terms)
    context["papers"] = {"available": catalog is not None, "total": len(base) + len(extra),
                        "items": _references((base + extra)[:5])}
    focus = dc.folded(direction["title"])
    audio_scope = direction["id"] == "universal-voice-encoder" or any(word in focus for word in
                  ("mdvr", "帕金森", "parkinson", "语音健康", "疾病声音", "speech health", "pathological speech"))
    protocols, gaps = [], []
    if audio_scope and asset:
        protocols.append(dict(SPECS[AUDIO], parameters=dict(audio.PARAMETERS), sources=[audio.SOURCE]))
    elif audio_scope:
        gaps.append("本次目录中未找到已核版本的 MDVR-KCL 台账记录。")
    rav = next((r for r in assets if r.get("id") == audio.RAV_SOURCE["id"] and r.get("kind") == "dataset"
                and dc.folded(r.get("title", "")) == "ravdess speech"), None)
    emotion_scope = any(term in focus for term in ("语音情绪", "声音情绪", "情绪识别", "ravdess", "speech emotion", "emotional speech"))
    if emotion_scope and allow_noncommercial and rav:
        protocols.append(dict(SPECS[SPEAKER], parameters=dict(audio.SPLIT), sources=[audio.RAV_SOURCE]))
    elif emotion_scope and rav:
        gaps.append("RAVDESS 拆分实验仅在已获准的非商业成员环境中启用。")
    if catalog and terms and (registered or base or extra):
        protocols.append(dict(SPECS[SEARCH], parameters={"terms": terms}, sources=[{"id": "papers", "url": "/papers/api/catalog", "title": "团队文献题录"}]))
    elif not catalog:
        gaps.append("尚未取得可用于检索对照的团队题录。" if catalog is None else "当前团队题录含 0 条文献。")
    else:
        gaps.append("现有题录未找到可与该方向核对的候选。")
    if not protocols:
        gaps.append("暂无与该方向及现有可用资料同时匹配的运行方案。")
    plan = {"version": VERSION, "query": query.strip(), "direction": dc.selected(direction, ("id", "title", "question")),
            "registered_direction": registered, "status": "ready" if protocols else "no_protocol",
            "protocols": protocols, "context": context, "gaps": gaps,
            "input_fingerprints": {"paper_metadata": digest(catalog) if catalog is not None else None,
                                   "archive_record": audio.SHA256 if audio_scope and asset else None}}
    plan["fingerprint"] = digest(plan)
    return deepcopy(plan)


def _bibliographic_result(catalog, terms):
    base, extra = _search(catalog, terms)
    expanded = base + extra
    doi = sum(bool(r.get("doi")) for r in expanded)
    metrics = {"catalog_records": len(catalog), "with_titles": sum(bool(r["titles"]) for r in catalog),
               "title_matches": len(base), "expanded_matches": len(expanded), "incremental_matches": len(extra),
               "expanded_with_doi": doi, "expanded_doi_pct": round(100 * doi / len(expanded), 2) if expanded else None}
    evidence = [{"id": r["id"], "title": r["title"], "url": "/papers/#catalog?q=" + quote(r["title"], safe=""), "match": mode} for mode, rows in
                (("title", base), ("metadata_only", extra)) for r in rows]
    return {"status": "completed", "metrics": metrics, "matched_records": evidence,
            "observations": [f"在 {len(catalog)} 条现有题录中，题名检索命中 {len(base)} 条。扩展检索另找到 {len(extra)} 条候选，合计 {len(expanded)} 条，其中 {doi} 条登记了 DOI。"],
            "limitations": ["此对照覆盖团队现有题录。新增命中来自分类、标签或关键词，尚待人工核对相关性。未测量文献召回率、模型性能或学术影响。"],
            "next": "优先阅读仅由扩展检索命中的候选，记录纳入与排除依据，再评估增量相关文献的比例。"}


def execute_plan(plan, sources, *, allow_noncommercial=False):
    """Rebuild the whitelisted plan from current sources; reject stale plans or client-supplied overrides."""
    checked = build_plan(plan.get("query"), sources, allow_noncommercial=allow_noncommercial)
    if checked["fingerprint"] != plan.get("fingerprint") or digest({k: v for k, v in plan.items() if k != "fingerprint"}) != checked["fingerprint"]:
        raise ValueError("方向资料或实验计划已变化，请重新生成计划后运行。")
    started = datetime.now(timezone.utc).isoformat()
    results = []
    for spec in checked["protocols"]:
        if spec["id"] == AUDIO:
            result = audio.analyze()
        elif spec["id"] == SPEAKER:
            result = audio.analyze_splits()
        else:
            result = _bibliographic_result(_catalog(sources), checked["context"]["terms"])
        results.append({**spec, **result})
    states = {r["status"] for r in results}
    status = "completed" if states == {"completed"} else "unavailable" if not states or states == {"unavailable"} else "partial"
    return {"version": VERSION, "status": status, "direction": checked["direction"], "query": checked["query"],
            "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(), "plan_fingerprint": checked["fingerprint"],
            "fingerprint": digest([VERSION, checked["fingerprint"], results]), "results": results, "gaps": checked["gaps"]}
