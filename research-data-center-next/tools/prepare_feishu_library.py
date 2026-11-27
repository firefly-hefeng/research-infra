"""Project a Feishu ledger export to the two classification fields and public cards."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
RESTRICTED = {"E-DAIC", "DAIC-WOZ（普通版）", "IEMOCAP官方发布包", "UASpeech", "CMDC"}
COLLECTIONS = {"DementiaBank既有抓取 / ADReSS-M版本核对", "TalkBank全库整理范围与其他索引"}
DERIVED = {"IEMOCAP整理包", "江苏省机关医院：33条标准化录音/索引", "袁老师方向：北京人工校正目录"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def previous_count_dates(source_url):
    try:
        snapshot = read_json(DATA_ROOT / "feishu-library.json")
    except FileNotFoundError:
        return {}
    if snapshot["url"] != source_url:
        return {}
    return {
        (item["id"], item["title"], item["count_label"]): item["count_observed_at"]
        for item in snapshot["items"]
        if item.get("count_label") and item.get("count_observed_at")
    }


def prepare(rows, observed_at):
    document = read_json(DATA_ROOT / "feishu-library-editorial.json")
    taxonomy = read_json(DATA_ROOT / "library-taxonomy.json")
    classes = {child["id"]: (parent, child) for parent in taxonomy["categories"] for child in parent["children"]}
    source_url = document["table_url"]
    entries = document["entries"]
    count_dates = previous_count_dates(source_url)
    cards = []
    assignments = []
    for row in rows:
        name = row["数据名称"].strip()
        record = row["id"]
        status = row.get("当前进度", "").strip() or "待核对"
        subcategory_id, summary, *counts = entries.get(name, ["directory-only", "请查阅飞书原记录，核对资源内容和使用条件。"])
        count = counts[0] if counts else None
        category, subcategory = classes[subcategory_id]
        assignments.append({
            "id": record, "title": name, "category_id": category["id"],
            "subcategory_id": subcategory["id"], "研究大类": category["label"], "细分类": subcategory["label"],
        })
        if name.startswith("MiDasheng autonomous"):
            kind, role = "model", "训练交付"
        elif name in COLLECTIONS:
            kind, role = "dataset", "资料索引"
        elif name in DERIVED:
            kind, role = "dataset", "整理版本"
        elif name.startswith("Novoic"):
            kind, role = "dataset", "特征表"
        elif status in {"已验收", "已取得并验收", "文件已核实", "原始文件已清点", "发现空文件", "部分已验收"}:
            kind, role = "dataset", "数据资料"
        else:
            kind, role = "dataset", "获取线索"
        if name in RESTRICTED:
            usage_note = "使用前核对飞书原记录中的获批主体、允许用途和访问范围。"
        elif status == "访问受限":
            usage_note = "访问受限，按飞书原记录所述条件核对可获取范围。"
        else:
            usage_note = "取得范围与使用许可见飞书原记录。"
        cards.append({
            "id": record, "title": name, "kind": kind, "category_id": category["id"],
            **({"theme_label": row["一级标签"]} if "一级标签" in row else {}),
            "subcategory_id": subcategory["id"], "role": role, "summary": summary, "use_cases": [],
            "usage_note": usage_note, "status": status, "count_label": count,
            "count_observed_at": count_dates.get((record, name, count)),
            "observed_at": observed_at, "source": "feishu",
            "source_url": source_url + "&" + urlencode({"record": record}), "detail_url": None,
            "reference_url": document.get("references", {}).get(name),
        })
    return {"url": source_url, "observed_at": observed_at, "items": cards}, assignments


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="JSON array with Feishu record ID, 数据名称 and 当前进度")
    parser.add_argument("--observed-at", required=True, help="ISO 8601 time of export")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--assignments", type=Path)
    args = parser.parse_args()
    snapshot, assignments = prepare(read_json(args.export), args.observed_at)
    write_json(args.snapshot, snapshot)
    if args.assignments:
        write_json(args.assignments, assignments)
    print(f"Prepared {len(assignments)} records")


if __name__ == "__main__":
    main()
