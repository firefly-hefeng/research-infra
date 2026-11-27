import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_origin_index import compare, TENANT
from merge_origin_index import merge


class OriginReviewTests(unittest.TestCase):
    def test_member_visible_changes_and_incomplete_branches(self):
        items = [{"id": "kept", "url": TENANT + "/wiki/known", "title": "门户策展标题"}]
        before = {"A": {"status": "observed", "title": "A", "children": {"known": "甲", "gone": "乙"}},
                  "B": {"status": "observed", "title": "B", "children": {"hidden": "丙"}}}
        after = {"A": {"status": "observed", "title": "A", "children": {"known": "新甲", "new": "新增"}},
                 "B": {"status": "incomplete", "title": "B", "children": {}}}
        diff = compare(items, after, before)
        self.assertEqual(diff["source_title_changed"], {"known": {"from": "甲", "to": "新甲"}})
        self.assertEqual(diff["new_in_observed_sections"], {"new": "新增"})
        self.assertEqual(diff["no_longer_observed"], {"gone": "乙"})
        self.assertEqual(diff["sections_incomplete"], ["B"])
        self.assertFalse(compare(items, after, {})["source_title_changed"])

    def test_only_approved_entries_reach_new_candidate(self):
        current = {"items": [{"id": "one", "url": TENANT + "/wiki/original", "sections": ["retained"]}]}
        raw = json.dumps(current).encode()
        review = {"sections": {"group": {"status": "observed", "children": {"original": "甲", "new": "乙", "extra": "丙"}}}}
        def entry(key, node):
            return {"id": key, "url": TENANT + "/wiki/" + node, "title": key, "category": "示例", "summary": "示例导读"}
        decision = {"index_sha256": hashlib.sha256(raw).hexdigest(), "items": [entry("one", "original"), entry("two", "new")]}
        items = merge(raw, decision, review)["items"]
        self.assertEqual([x["id"] for x in items], ["one", "two"])
        self.assertEqual(items[0]["sections"], ["retained"])
        self.assertEqual(items[1]["source_mode"], "feishu_live")
        for choices in ([entry("one", "new")], [entry("changed", "original")], [entry("missing", "unseen")]):
            with self.assertRaises(ValueError):
                merge(raw, dict(decision, items=choices), review)
        with self.assertRaises(ValueError):
            merge(raw + b" ", decision, review)


if __name__ == "__main__":
    unittest.main()
