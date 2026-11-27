"""Merge editor-selected original document entries into a new staging file."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from check_origin_index import load, wiki_token


def merge(index_bytes, approval, review):
    if hashlib.sha256(index_bytes).hexdigest() != approval["index_sha256"]:
        raise ValueError("The live index changed. Review against its current contents.")
    index = json.loads(index_bytes)
    items = index["items"]
    by_id = {row["id"]: row for row in items}
    known_urls = {row["url"]: row["id"] for row in items}
    if len(by_id) != len(items) or len(known_urls) != len(items):
        raise ValueError("Resolve duplicate IDs or URLs in the source index first.")
    observed = set()
    for section, values in review["sections"].items():
        if values["status"] == "observed":
            observed.update([section, *values["children"]])
    changed = set()
    for entry in approval["items"]:
        required = {"id", "url", "category", "title", "summary"}
        if not required <= entry.keys() or entry.keys() - required - {"team_week_label", "source_mode"}:
            raise ValueError("An approved entry requires id, url, category, title, summary.")
        key, url = entry["id"], entry["url"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key) or key in changed:
            raise ValueError("Repeated or invalid approved ID.")
        if wiki_token(url) not in observed or not all(isinstance(v, str) and v.strip() for v in entry.values()):
            raise ValueError("Missing fields or a source outside this member's reviewed navigation.")
        old = by_id.get(key)
        if old and old["url"] != url or url in known_urls and known_urls[url] != key:
            raise ValueError("The approved ID or URL belongs to a different original.")
        fields = {k: v for k, v in entry.items() if k in required}
        if old:
            if {"team_week_label", "source_mode"} & entry.keys():
                raise ValueError("Preserve the current item's reading mode and sections on incremental edits.")
            old.update(fields)
        else:
            mode = entry.get("source_mode", "feishu_live")
            if mode not in {"feishu_live", "feishu_window"}:
                raise ValueError("Unsupported Feishu original reading mode.")
            item = dict(fields, source_mode=mode)
            if "team_week_label" in entry:
                if not key.startswith("seminar-"):
                    raise ValueError("Week links belong to dated meeting originals.")
                year, week, _ = date.fromisoformat(key.removeprefix("seminar-")).isocalendar()
                link = {"label": entry["team_week_label"], "url": f"/progress/#team?week={year}-W{week:02}"}
                item["sections"] = [{"title": "平台关联", "links": [link]}]
            items.append(item)
            by_id[key] = item
            known_urls[url] = key
        changed.add(key)
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, type=Path, help="copy of the current live index")
    parser.add_argument("--review", required=True, type=Path, help="private observed directory report")
    parser.add_argument("--approved", required=True, type=Path, help="editor-selected entries and index_sha256")
    parser.add_argument("--output", required=True, type=Path, help="new staging file")
    args = parser.parse_args()
    result = merge(args.index.read_bytes(), load(args.approved), load(args.review))
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2, ensure_ascii=False)
        out.write("\n")
    print(json.dumps({"staged_items": len(result["items"])}))


if __name__ == "__main__":
    main()
