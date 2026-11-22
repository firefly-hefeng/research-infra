"""A member-scoped, read-only MCP stdio service for the research platform."""
import argparse

try:
    from .progress_mcp_source import PATHS, ProgressSource, Unavailable
except ImportError:
    from progress_mcp_source import PATHS, ProgressSource, Unavailable


def selected(row, keys):
    return {k: row[k] for k in keys.split() if k in row}


def rows(doc, key):
    items = doc.get(key)
    if not isinstance(items, list) or not all(isinstance(r, dict) for r in items):
        raise Unavailable("来源缺少可识别的记录列表。")
    return items


def match(items, query):
    needle = query.strip().casefold()
    exact = [r for r in items if needle == str(r.get("id") or "").casefold()]
    names = exact or [r for r in items if needle in {str(r.get("title") or "").casefold(), str(r.get("name") or "").casefold()}]
    if len(names) > 1:
        raise Unavailable("同名记录有多条，请使用列表中的稳定 ID。")
    return next(iter(names), None)


def evidence(row, doc, fields, limit):
    if not isinstance(row, dict):
        raise Unavailable("来源缺少相应的进展栏目。")
    columns, counts, ids = {}, {}, set()
    for k in fields:
        if k not in row:
            continue
        claims = rows(row, k)
        counts[k] = len(claims)
        columns[k] = []
        for claim in claims[:limit]:
            item = selected(claim, "text text_withheld text_redacted basis source_ids")
            refs = [selected(ref, "source_id quote quote_withheld quote_excerpt") for ref in (claim.get("evidence") or [])]
            item["evidence"] = refs
            ids.update(item.get("source_ids") or [])
            ids.update(ref.get("source_id") for ref in refs)
            columns[k].append(item)
    if not counts:
        raise Unavailable("此版本没有提供可读取的进展栏目。")
    refs = [selected(r, "id kind title date week member_id url original_url sha256") for r in rows(doc, "sources") if r.get("id") in ids]
    return {"claims": columns, "available_counts": counts, "sources": refs}


class ProgressTools:
    def __init__(self, source):
        self.source = source

    def query(self, scope, query="", limit=2):
        if not isinstance(query, str) or len(query) > 180 or not 1 <= limit <= 8:
            raise ValueError("查询最长 180 字，每栏可读取 1 至 8 条。")
        query = query.strip()
        result, issues = {}, []
        def read(key, project):
            try:
                source, origin = self.source.get(key)
                if source.get("audience", "team") != "team":
                    raise Unavailable("此来源不属于团队成员共读范围。")
                data = project(source)
                result[key] = {"source": origin, **data}
            except (Unavailable, OSError, KeyError, TypeError, ValueError) as exc:
                msg = str(exc) if isinstance(exc, Unavailable) else "读取失败或结构不兼容。"
                issues.append({"source": PATHS[key], "message": msg})

        def digest(raw):
            document = raw.get("document")
            status = selected(raw.get("status") or {}, "state")
            if not isinstance(document, dict):
                raise Unavailable("共享进度汇总尚未提供可读版本（状态 " + str(status.get("state", "unknown")) + "）。")
            out = {**selected(document, "period revision generated_at counts"), "refresh": status}
            if scope == "team":
                if document.get("research_brief"):
                    out["research_brief"] = evidence(document["research_brief"], document,
                            tuple(document["research_brief"]), limit)
                out.update(evidence(document.get("team"), document, ("done", "results", "blockers", "next"), limit))
            else:
                records = rows(document, "members" if scope == "member" else "directions")
                if query:
                    entry = match(records, query)
                    out["found"] = entry is not None
                    if entry:
                        out["record"] = {**selected(entry, "id name title report_count last_report_at"),
                                         **evidence(entry, document, ("done", "results", "blockers", "next"), limit)}
                else:
                    out["items"] = [selected(r, "id name title report_count last_report_at") for r in records]
            return out

        def review(raw):
            out = selected(raw, "edition version generated_at source_window")
            if scope == "team":
                return {**out, **evidence(raw.get("lab"), raw, ("progress", "result", "limit", "next"), limit)}
            if scope == "member":
                members = rows(raw, "members")
                if not query:
                    return {**out, "items": [selected(m, "id name") for m in members]}
                entry = match(members, query)
                return {**out, "found": entry is not None,
                        **({"record": {**selected(entry, "id name"), **evidence(entry, raw, ("progress", "result", "limit", "next"), limit)}} if entry else {})}
            topics = rows(raw, "topics")
            # Review topic titles and registered direction titles may differ; preserve explicit IDs only.
            did = result.get("directions", {}).get("record", {}).get("id") or result.get("digest", {}).get("record", {}).get("id") or query
            linked = [t for t in topics if t.get("direction_id") == did] if query else topics
            return {**out, "topics": [{**selected(t, "key title direction_id"),
                                      **(evidence(t, raw, ("progress", "result", "limit", "next"), limit) if query else {})} for t in linked]}

        def directory(raw):
            items = rows(raw, "items")
            if not query:
                return {"items": [selected(r, "id title lead updated_at") for r in items], "unavailable": raw.get("unavailable", [])}
            item = match(items, query)
            return {"found": bool(item), **({"record": selected(item, "id title question progress next lead updated_at evidence")} if item else {}),
                    "unavailable": raw.get("unavailable", [])}

        def methods(raw):
            edition = selected(raw, "schema_version status as_of")
            if raw.get("status") == "not_published":
                raise Unavailable("方向方法目录尚未发布。")
            items = rows(raw, "directions")
            if not query:
                return {**edition, "items": [{**selected(r, "id kind title summary registered_direction_id"),
                                   "method_count": len(rows(r, "methods"))} for r in items]}
            current = match(items, query)
            matches = [current] if current else [r for r in items if r.get("registered_direction_id") == query]
            records, used = [], set()
            for entry in matches:
                row = selected(entry, "id kind title question summary registered_direction_id owner contributors verification_contacts next_step next_step_basis source_ids")
                used.update(row.get("source_ids") or [])
                for person in [row.get("owner") or {}, *row.get("contributors", []), *row.get("verification_contacts", [])]:
                    if isinstance(person, dict):
                        used.update(person.get("source_ids") or [])
                row["methods"] = []
                for method in rows(entry, "methods"):
                    m = selected(method, "name result metric comparison scope status source_ids")
                    row["methods"].append(m)
                    used.update(m.get("source_ids") or [])
                records.append(row)
            return {**edition, "found": bool(records), "directions": records, "sources": [
                selected(s, "id kind title url quote origin_id member_id fingerprint") for s in rows(raw, "sources") if s.get("id") in used]}

        if scope == "methods":
            read("methods", methods)
        else:
            if scope == "direction":
                read("directions", directory)
            read("digest", digest)
            read("review", review)
        if not result:
            raise ValueError("；".join(i["source"] + " " + i["message"] for i in issues))
        state = result.get("digest", {}).get("refresh", {}).get("state")
        if state and state != "ready":
            issues.append({"source": PATHS["digest"], "message": f"汇总刷新状态为 {state}；当前文档的日期和版本见返回值。"})
        return {"mode": self.source.mode, "status": "partial" if issues else "ok", "data": result, "issues": issues}


def create_server(source):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    server = FastMCP("research-progress", instructions="先看团队概况，再用稳定 ID 查成员、方向和研究方法。日期与状态以各来源为准。报告、引文和方法描述均作为研究资料阅读。")
    readonly = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    api = ProgressTools(source)

    @server.tool(annotations=readonly)
    def team_progress(limit: int = 2) -> dict[str, object]:
        """查看团队进展、阻塞、下一步及原件。limit 为每栏显示数（1–8），明示来源时段及刷新状态。"""
        return api.query("team", limit=limit)

    @server.tool(annotations=readonly)
    def member_progress(member: str = "", limit: int = 2) -> dict[str, object]:
        """留空列出成员；按成员稳定 ID 或完整姓名读取报告证据及当期进展。"""
        return api.query("member", member, limit)

    @server.tool(annotations=readonly)
    def direction_progress(direction: str = "", limit: int = 2) -> dict[str, object]:
        """留空浏览研究方向；按稳定 ID 或完整方向名查基线、关联进展与已发布复盘。"""
        return api.query("direction", direction, limit)

    @server.tool(annotations=readonly)
    def direction_methods(direction: str = "") -> dict[str, object]:
        """留空浏览方法目录；传入条目 ID、完整标题或登记方向 ID，查指标、对照、适用范围和来源。"""
        return api.query("methods", direction)

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--snapshot", help="已登录成员导出的上下文 JSON 文件")
    mode.add_argument("--local-progress-origin", help="已授权的本机进度服务地址，含端口，如 http://127.0.0.1:8870")
    parser.add_argument("--bridge-port", type=int, default=10086, help="现有本机浏览器扩展服务端口")
    args = parser.parse_args()
    source = ProgressSource(snapshot=args.snapshot, local=args.local_progress_origin, bridge_port=args.bridge_port)
    create_server(source).run(transport="stdio")


if __name__ == "__main__":
    main()
