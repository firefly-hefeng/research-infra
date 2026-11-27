"""Read a direction across the existing platform sources, keeping retrieval distinct from evidence."""
from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import quote, urlsplit


FIELDS = {"done": "进展", "results": "成果", "blockers": "阻塞", "next": "下一步"}
TOPICS = ("空间音频", "语音健康", "多模态", "情绪", "严重度", "抑郁", "焦虑", "跨疾病", "抗捷径", "认知", "文本风险")
TOPIC_ALIASES = {"空间音频": ("spatial audio",), "情绪": ("emotion", "emotional"), "抑郁": ("depression", "depressive"),
                 "焦虑": ("anxiety",), "多模态": ("multimodal",), "认知": ("cognitive",),
                 "声音表征": ("语音表征", "speech representation", "voice representation"),
                 "跨疾病": ("cross-disease",), "严重度": ("severity",)}
SHAPES = {"directions": "items", "research": "models", "library": "items", "papers": "papers"}


def folded(value):
    return unicodedata.normalize("NFKC", str(value)).casefold().strip()


def selected(row, keys):
    return {k: row[k] for k in keys if row.get(k) is not None}


def resolve_direction(query, directions):
    needle = folded(query)
    if not needle:
        raise ValueError("请输入方向 ID 或名称。")
    for exact in (True, False):
        matches = []
        for row in directions:
            names = [folded(row.get(k, "")) for k in ("id", "title")]
            matched = needle in names if exact else any(needle in name for name in names)
            if matched:
                matches.append(row)
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError("匹配多个方向，请使用 ID：" + "、".join(r["id"] for r in matches))
    options = "、".join(f"{r['title']} ({r['id']})" for r in directions)
    raise ValueError("未找到这个方向。当前目录：" + (options or "暂无已登记方向"))


def keywords(direction, findings, explicit):
    if any(not w.strip() or len(w) > 64 for w in explicit) or len(explicit) > 8:
        raise ValueError("可提供最多 8 个非空关键词，每个最长 64 个字符。")
    if explicit:
        return list(dict.fromkeys(w.strip() for w in explicit)), "用户指定"
    focus = " ".join([str(direction.get(k) or "") for k in ("title", "question")] +
                     [f["report"].get("question", "") for f in findings])
    source = focus + " " + str(direction.get("progress") or "")
    latin = re.findall(r"(?<![A-Za-z0-9_-])[A-Za-z][A-Za-z0-9_-]{2,}(?![A-Za-z0-9_-])", source)
    omit = {"mae", "rmse", "macro-f1", "text", "daily", "risk", "encoder"}
    terms = [s for s in latin if s.casefold() not in omit] + [s for s in TOPICS if s in focus]
    for concept, equivalents in TOPIC_ALIASES.items():
        if concept in focus or concept == "声音表征" and concept in source:
            terms.extend((concept, *equivalents))
    return list(dict.fromkeys(terms))[:24], "方向与同 ID 成果中出现的术语及中英文同义词"


def candidates(items, terms, limit, paper=False, category_labels=None):
    hits = []
    for row in items:
        if paper:
            bib, card = row.get("bibliography") or {}, row.get("card") or {}
            title = bib.get("title") or card.get("title") or row.get("filename") or row["id"]
            insight = row.get("insight") or {}
            texts = [title, bib.get("title"), card.get("title"), bib.get("category"), card.get("category"), bib.get("doi"),
                     card.get("doi"), *(bib.get("tags") or []), *(card.get("tags") or []), *(insight.get("keywords") or []),
                     *((insight.get("author_keywords") or {}).get("terms") or [])]
            notice = bib.get("fulltext_policy") or "全文权限待核对"
            entry = {"id": row["id"], "title": title, "access": notice,
                     "review_state": bib.get("review_state") or row.get("status"), "doi": bib.get("doi") or card.get("doi"),
                     "fulltext_available": row.get("fulltext_available")}
        else:
            title = row["title"]
            texts = [title, row.get("summary"), row.get("theme_id"), row.get("subcategory_id"), *(row.get("aliases") or [])]
            if category_labels:
                texts.extend(category_labels.get(row.get(key), "") for key in ("theme_id", "category_id", "subcategory_id"))
            entry = selected(row, ("id", "registry_id", "kind", "title", "source_url", "detail_url", "usage_note", "status", "observed_at"))
        corpus = folded(" ".join(str(s) for s in texts if s))
        matched = []
        for term in terms:
            word = folded(term)
            # Latin acronyms should not match substrings of unrelated names.
            if word.isascii():
                present = re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", corpus)
            else:
                present = word in corpus
            if present:
                matched.append(term)
        if matched:
            hits.append((sum(folded(t) in folded(title) for t in matched), {**entry, "matched_terms": matched}))
    hits.sort(key=lambda pair: (-len(pair[1]["matched_terms"]), -pair[0], folded(pair[1]["title"]), pair[1]["id"]))
    return {"total": len(hits), "items": [entry for _, entry in hits[:limit]]}


def recent(direction_id, payload):
    digest = payload.get("document") or {}
    progress = next((r for r in digest.get("directions", []) if r.get("id") == direction_id), None)
    result = {"status": payload.get("status", {}).get("state"), **selected(digest, ("period", "revision", "generated_at")),
              "direction_in_digest": progress is not None, "report_count": None, "claims": {}, "sources": []}
    if not progress:
        return result
    result["report_count"] = progress.get("report_count")
    source_by_id = {r["id"]: r for r in digest.get("sources", [])}
    used = set()
    for key in FIELDS:
        claims = []
        for item in progress.get(key, []):
            ids = item.get("source_ids", [])
            quotes = [selected(e, ("source_id", "quote")) for e in item.get("evidence", []) if e.get("source_id") in ids]
            unresolved = [i for i in ids if i not in source_by_id or not any(e.get("source_id") == i and e.get("quote") for e in quotes)]
            claims.append({"text": item["text"], "source_ids": ids, "evidence": quotes,
                           "citation_complete": bool(ids) and not unresolved, "unresolved": unresolved})
            used.update(ids)
        result["claims"][key] = claims
    result["sources"] = [selected(row, ("id", "title", "kind", "member_id", "date", "week", "url", "original_url", "sha256"))
                         for ident, row in source_by_id.items() if ident in used]
    return result


def dossier(query, sources, observations, *, mode, generated_at, search_terms=(), limit=5):
    if not 1 <= limit <= 25:
        raise ValueError("每组候选显示数量应在 1 至 25 之间。")
    for key, field in SHAPES.items():
        if key in sources and not isinstance(sources[key].get(field), list):
            observations[key]["status"] = "invalid_source"
            sources.pop(key)
    if "directions" not in sources:
        raise ValueError("方向目录未成功读取，无法判定方向。请在已授权环境刷新上下文。")
    direction = resolve_direction(query, sources["directions"]["items"])
    ident = direction["id"]
    archive = sources.get("research", {})
    results = []
    for kind in ("models", "research_tracks"):
        for row in archive.get(kind, []):
            if row.get("id") == ident:
                entry = selected(row, ("id", "name", "status_label", "summary", "validation", "metrics", "artifact_paths", "path", "interface", "code"))
                entry["report"] = selected(row.get("report", {}), ("question", "methods", "core_effects", "limitations", "next_step"))
                entry["type"] = kind
                results.append(entry)
    comparison = archive.get("comparison") or {}
    primary = {r.get("label") for r in comparison.get("rows", []) if r.get("primary")}
    comparison = comparison if any(r.get("name") in primary for r in results) else None
    terms, origin = keywords(direction, results, search_terms)
    library = sources.get("library", {})
    assets = library.get("items", [])
    category_labels = {c["id"]: c["label"] for c in library.get("themes", []) + library.get("categories", [])}
    category_labels.update({s["id"]: s["label"] for c in library.get("categories", []) for s in c.get("children", [])})
    catalog = {kind: candidates([i for i in assets if i.get("kind") == kind], terms, limit, category_labels=category_labels)
               if "library" in sources else None for kind in ("dataset", "model")}
    catalog["papers"] = candidates(sources["papers"]["papers"], terms, limit, paper=True) if "papers" in sources else None
    return {"schema_version": "1.0", "mode": mode, "assembled_at": generated_at, "sources": observations,
            "direction": selected(direction, ("id", "title", "lead", "updated_at", "question", "progress", "next", "evidence")),
            "direction_url": "/progress/#directions?item=" + quote(ident, safe=""),
            "reviewed_findings": {"reviewed_at": archive.get("reviewed_at"), "matched_by": "exact_direction_id",
                                  "items": results if "research" in sources else None, "comparison": comparison},
            "recent_progress": recent(ident, sources["progress"]) if "progress" in sources else None,
            "discovery": {"relation": "keyword_candidate_only", "terms": terms, "term_source": origin,
                          "limit_per_kind": limit, **catalog}}


def plain(value):
    text = html.escape(" ".join(str(value or "").split()))
    return re.sub(r"([\\`*_{}\[\]()#!|])", r"\\\1", text)


def source_link(label, path, *, progress=False):
    if not isinstance(path, str):
        return plain(label)
    if progress and path.startswith("#"):
        path = "/progress/" + path
    if path.startswith("https://"):
        parts = urlsplit(path)
        if parts.hostname and not parts.username and not parts.password and not any(c.isspace() or c in "<>\\" for c in path):
            return f"[{plain(label)}]({quote(path, safe=':/?=#&%-._~')})"
        return plain(label)
    if not path.startswith("/") or path.startswith("//") or "\\" in path or any(c.isspace() for c in path):
        return plain(label)
    if urlsplit(path).netloc:
        return plain(label)
    href = "https://rmp.wuwangwo.top" + quote(path, safe="/?=#&%-._~")
    return f"[{plain(label)}]({href})"


def markdown(pack):
    direction = pack["direction"]
    lines = ["# " + plain(direction["title"]), "", source_link("方向原文", pack["direction_url"])]
    if pack.get("snapshot_generated_at"):
        lines += ["", "快照导出于 " + plain(pack["snapshot_generated_at"]) + "。"]
    lines += [
             "", "## 研究问题与基线", "", plain(direction.get("question")), "", plain(direction.get("progress")),
             "", "基线更新于 " + plain(direction.get("updated_at") or "日期未知") + "。"]
    if direction.get("next"):
        lines += ["", "**下一步**　" + plain(direction["next"])]
    findings = pack["reviewed_findings"]
    lines += ["", "## 成果档案", ""]
    if findings.get("reviewed_at"):
        lines += ["成果档案核对日期：" + plain(findings["reviewed_at"]) + "。", ""]
    if findings["items"] is None:
        lines.append("本次未读取到成果档案。")
    elif not findings["items"]:
        lines.append("当前档案未找到与方向 ID 一致的成果。")
    for result in findings["items"] or []:
        report = result["report"]
        lines += ["### " + plain(result["name"]), "", plain(result.get("summary")), ""]
        for item in report.get("core_effects", []):
            lines.append("- " + plain(item.get("detail")) + "　依据：" + plain(item.get("evidence") or "待补"))
        for metric in result.get("metrics", []):
            lines.append("- " + plain(metric.get("label")) + "　" + plain(metric.get("display")) + "　" + plain(metric.get("scope")))
        if result.get("validation") or report.get("limitations"):
            lines += ["", "**验证范围**　" + plain(result.get("validation")) + " " + plain(report.get("limitations"))]
        code = result.get("code") or {}
        if code.get("url"):
            lines += ["", source_link("归档研究代码", code["url"])]
        paths = result.get("artifact_paths") or ([{"label": "路线归档", "path": result["path"]}] if result.get("path") else [])
        if paths:
            lines += ["", "**登记工件**", ""] + ["- " + plain(row.get("label")) + "　" + plain(row.get("path")) for row in paths]
    comp = findings.get("comparison")
    if comp:
        lines += ["", "**同协议对照**　" + plain(comp.get("scope")) + " " + plain(comp.get("metric")), ""]
        lines += ["- " + plain(row["label"]) + "　" + plain(row["display"]) for row in comp.get("rows", [])]
    progress = pack["recent_progress"]
    lines += ["", "## 近期进展与原报告", ""]
    if not progress or not progress["direction_in_digest"]:
        lines.append("本次没有可查的该方向汇总。")
    else:
        period = progress.get("period") or {}
        count = progress.get("report_count")
        lines.append(plain(period.get("from", "?")) + " 至 " + plain(period.get("to", "?")) +
                     "，关联成员报告 " + (str(count) if count is not None else "未知") + " 份。")
        if count == 0:
            lines.append("本期共享汇总未关联成员报告；此前的研究基线见上文。")
        if progress.get("status") and progress["status"] != "ready":
            lines.append("整理状态：" + plain(progress["status"]) + "。")
        anchors = {r["id"]: r for r in progress["sources"]}
        for key, label in FIELDS.items():
            for item in progress["claims"].get(key, []):
                lines += ["", "**" + label + "**　" + plain(item["text"])]
                for evidence in item["evidence"]:
                    origin = anchors.get(evidence["source_id"], {})
                    ref = source_link(origin.get("title", evidence["source_id"]), origin.get("original_url") or origin.get("url"), progress=True)
                    lines.append("> " + plain(evidence.get("quote")) + "　" + ref)
                if not item["citation_complete"]:
                    lines.append("该条来源或摘录待复核。")
    discovery = pack["discovery"]
    lines += ["", "## 可继续查阅的资料", "", "检索词：" + "、".join(plain(t) for t in discovery["terms"]) + "。下列匹配只用于发现，实际使用与授权需从原件核对。"]
    for key, label in (("dataset", "数据"), ("model", "模型"), ("papers", "文献")):
        group = discovery[key]
        if group is None:
            lines += ["", f"**{label}**　来源未取得。"]
            continue
        lines += ["", f"**{label}**　匹配 {group['total']} 条，展示 {len(group['items'])} 条。", ""]
        for item in group["items"]:
            if key == "papers":
                doi = item.get("doi") or ""
                url = "https://doi.org/" + doi if re.fullmatch(r"10\.[0-9]+/[^\s]+", doi) else "/papers/#catalog?q=" + quote(item["title"], safe="")
            else:
                url = item.get("detail_url") or item.get("source_url")
            lines.append("- " + source_link(item["title"], url) + "　" + plain(item["id"]) + "　匹配：" +
                         "、".join(plain(w) for w in item["matched_terms"]) + "。" +
                         plain(item.get("usage_note") or item.get("access")))
    lines += ["", "## 来源覆盖", ""]
    for name, source in pack["sources"].items():
        lines.append("- " + source_link(name, source["url"]) + "　" + plain(source["status"]) + "　" + plain(source.get("fetched_at")))
    return "\n".join(lines)
