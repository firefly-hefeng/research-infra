"""Review a member-visible Feishu research tree locally; never edits Feishu or the portal."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

HERE = Path(__file__).resolve().parent
TENANT = "https://wcn5kauqqbj1.feishu.cn"
ROOT_TOKEN = "Md6wwmSJsi1CEhkgACWc3wYanvg"
SECTIONS = ("research-wiki", "research-planning", "weekly-seminar", "research-exploration",
            "research-data-specs", "algorithm-research")


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def private_output(path, obj):
    if HERE.parents[1] in path.resolve().parents:
        raise ValueError("Save the review in your private folder outside the portal.")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as out:
        json.dump(obj, out, indent=2, ensure_ascii=False)
        out.write("\n")


def wiki_token(url):
    match = re.fullmatch(re.escape(TENANT) + r"/wiki/([a-zA-Z0-9]+)", url)
    return match.group(1) if match else None


def observe(daemon, sections, all_levels=False):
    endpoint = urlsplit(daemon)
    if endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "::1", "localhost") or endpoint.username or endpoint.password or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment:
        raise ValueError("Use the local browser bridge HTTP address.")
    session = "origin-index-" + uuid.uuid4().hex
    opener = build_opener(ProxyHandler({}))

    def call(action, args):
        payload = json.dumps({"action": action, "args": args, "session": session}).encode()
        req = Request(daemon.rstrip("/") + "/command", data=payload, headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=100) as response:
            envelope = json.load(response)
        if not envelope.get("ok"):
            raise ValueError("Browser action failed. Check the local bridge and your member session.")
        return envelope["data"]

    reader = (HERE / "observe_origin_tree.js").read_text(encoding="utf-8")
    try:
        call("navigate", {"url": TENANT + "/wiki/" + ROOT_TOKEN, "newTab": True, "group_title": "原点目录核对"})
        observations = {}
        pending = [ROOT_TOKEN] if all_levels else list(sections)
        for key in pending:
            if len(pending) > 128:
                raise ValueError("The visible tree exceeds the bounded directory check.")
            scope = {"origin": TENANT, "root": ROOT_TOKEN, "sections": [key], "keepExpanded": all_levels}
            script = "(async()=>JSON.stringify(await (" + reader + ")(" + json.dumps(scope) + ")))()"
            result = call("evaluate", {"code": script})
            if result.get("type") != "string":
                raise ValueError("The research navigation was unavailable. Check your Feishu session.")
            branch = json.loads(result["value"])
            observations.update(branch)
            if all_levels:
                for child in branch[key].get("expandable_children", []):
                    if child not in pending:
                        pending.append(child)
        return observations
    finally:
        call("close_session", {})


def compare(items, observed, previous):
    known = {key: row for row in items if (key := wiki_token(row.get("url", "")))}
    visible = {}
    old_visible = {}
    removed = {}
    for key, data in observed.items():
        if data["status"] == "observed":
            visible[key] = data["title"]
            visible.update(data["children"])
        old = previous.get(key, {})
        if old.get("status") == "observed":
            old_visible[key] = old["title"]
            old_visible.update(old["children"])
            if data["status"] == "observed":
                removed.update({k: v for k, v in old["children"].items() if k not in data["children"]})
    return {
        "portal_entries_seen": [row["id"] for key, row in known.items() if key in visible],
        "portal_entries_outside_observation": [row["id"] for key, row in known.items() if key not in visible],
        "unlisted_visible": {k: v for k, v in visible.items() if k not in known},
        "new_in_observed_sections": {k: v for k, v in visible.items() if previous and k not in old_visible
                                     and any(k in data.get("children", {}) and previous.get(p, {}).get("status") == "observed"
                                             for p, data in observed.items())},
        "source_title_changed": {k: {"from": old_visible[k], "to": v} for k, v in visible.items()
                                 if k in old_visible and v != old_visible[k]},
        "no_longer_observed": {k: v for k, v in removed.items() if k not in visible},
        "sections_incomplete": [k for k, row in observed.items() if row["status"] != "observed"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=HERE.parent / "data/workspace-docs.json")
    parser.add_argument("--previous", type=Path, help="private JSON from an earlier run")
    parser.add_argument("--report", type=Path, help="new private JSON file; default prints aggregate counts only")
    parser.add_argument("--all-levels", action="store_true", help="expand all visible research branch folders in the navigation")
    parser.add_argument("--daemon-url", default="http://127.0.0.1:10086")
    args = parser.parse_args()
    items = load(args.index)["items"]
    by_id = {row["id"]: row for row in items}
    sections = [wiki_token(by_id[key]["url"]) for key in SECTIONS]
    if len(by_id) != len(items) or None in sections or sections[0] != ROOT_TOKEN:
        raise ValueError("Unexpected curated research index or root.")
    old = load(args.previous) if args.previous else {}
    if old and (old.get("root") != ROOT_TOKEN or bool(old.get("all_levels")) != args.all_levels
                or not args.all_levels and set(old.get("sections", {})) != set(sections)):
        raise ValueError("The previous review covered a different root or section set.")
    observed = observe(args.daemon_url, sections, args.all_levels)
    if (not args.all_levels and set(observed) != set(sections)) or all(x["status"] != "observed" for x in observed.values()):
        raise ValueError("No credible observation; the index and previous review are unchanged.")
    diff = compare(items, observed, old.get("sections", {}))
    if args.report:
        private_output(args.report, {"root": ROOT_TOKEN, "all_levels": args.all_levels, "checked": datetime.now(timezone.utc).isoformat(),
                                     "sections": observed, "review": diff})
    print(json.dumps({"ok": True, "counts": {k: len(v) for k, v in diff.items()},
                      "baseline_compared": bool(old)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
