from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import prepare_feishu_library as builder
from resource_library import library_payload


class FeishuLibraryPreparationTests(unittest.TestCase):
    def test_browse_uses_explicit_topic_and_keeps_historical_cache_from_reverting_the_ledger(self):
        current = library_payload(builder.DATA_ROOT)
        ordered = [theme["id"] for theme in current["themes"]]
        rows = [item for item in current["items"] if item["source"] == "feishu"]
        self.assertEqual([ordered.index(item["theme_id"]) for item in rows],
                         sorted(ordered.index(item["theme_id"]) for item in rows))
        examples = {item["title"]: item for item in rows}
        self.assertEqual(examples["E-DAIC"]["theme_id"], "speech-health")
        self.assertEqual(examples["IEMOCAP官方发布包"]["theme_id"], "speech-emotion")
        self.assertEqual(examples["HF-Lung-V1"]["theme_id"], "physiological-sounds")
        self.assertTrue(all(item["theme_id"] in ordered for item in current["items"]))
        old = {"observed_at": "2020-01-01T00:00:00Z", "rows": []}
        self.assertEqual(library_payload(builder.DATA_ROOT, ledger_override=old), current)

        sample = examples["HF-Lung-V1"]
        feed = {"observed_at": "2099-01-01T00:00:00Z", "rows": [
            {"id": sample["id"], "数据名称": sample["title"], "一级标签": "待核对"},
            {"id": "recTestNew", "数据名称": "待登记资料", "一级标签": "空间音频"},
        ]}
        result = library_payload(builder.DATA_ROOT, ledger_override=feed)
        actual = [(item["id"], item["theme_id"]) for item in result["items"] if item["source"] == "feishu"]
        self.assertEqual(actual, [("recTestNew", "spatial-audio"), (sample["id"], "unconfirmed")])

    def test_rebuild_keeps_quantity_date_only_for_the_same_table_record_and_quantity(self):
        table = "https://example.com/ledger?table=test"
        quantity_date = "2026-11-13T13:02:44Z"
        export_date = "2026-11-14T01:00:00Z"
        entries = {
            "录音库": ["directory-only", "录音资料。", "73 条录音"],
            "改名的录音库": ["directory-only", "录音资料。", "73 条录音"],
            "规模已更新": ["directory-only", "录音资料。", "74 条录音"],
        }
        rows = [
            {"id": "recA", "数据名称": "录音库"},
            {"id": "recB", "数据名称": "改名的录音库"},
            {"id": "recC", "数据名称": "规模已更新"},
            {"id": "recD", "数据名称": "录音库"},
            {"id": "recE", "数据名称": "待补说明"},
        ]
        previous = [
            {"id": record, "title": title, "count_label": "73 条录音", "count_observed_at": quantity_date}
            for record, title in [("recA", "录音库"), ("recB", "录音库"), ("recC", "规模已更新")]
        ]

        with TemporaryDirectory() as directory, patch.object(builder, "DATA_ROOT", Path(directory)):
            builder.write_json(builder.DATA_ROOT / "feishu-library-editorial.json", {"table_url": table, "entries": entries})
            builder.write_json(builder.DATA_ROOT / "library-taxonomy.json", {"categories": [
                {"id": "unconfirmed", "label": "待核对", "children": [{"id": "directory-only", "label": "仅目录"}]}
            ]})
            snapshot, _ = builder.prepare(rows, export_date)
            self.assertTrue(all(item["count_observed_at"] is None for item in snapshot["items"]))

            history = builder.DATA_ROOT / "feishu-library.json"
            builder.write_json(history, {"url": table, "items": previous})
            snapshot, assignments = builder.prepare(rows, export_date)
            self.assertEqual([item["count_observed_at"] for item in snapshot["items"]], [quantity_date, None, None, None, None])
            self.assertEqual([item["count_label"] for item in snapshot["items"]], ["73 条录音"] * 2 + ["74 条录音", "73 条录音", None])
            self.assertEqual(snapshot["observed_at"], export_date)
            self.assertTrue(all(item["observed_at"] == export_date for item in snapshot["items"]))
            self.assertEqual([item["id"] for item in assignments], [row["id"] for row in rows])

            builder.write_json(history, {"url": table + "2", "items": previous})
            snapshot, _ = builder.prepare(rows, export_date)
            self.assertTrue(all(item["count_observed_at"] is None for item in snapshot["items"]))
