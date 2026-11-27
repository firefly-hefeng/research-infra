import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import agent_client


class DirectionContextTests(unittest.TestCase):
    def setUp(self):
        report = {"id": "weekly:member:w1", "title": "成员周报", "url": "#team?week=w1", "original_url": "/progress/api/report-source/weekly/member/w1"}
        source_id = report["id"]
        self.data = {
            "directions": {"items": [{"id": "depalign-final", "title": "抑郁模型", "progress": "DAIC 访谈。"},
                                      {"id": "independent", "title": "抑郁研究方案"}]},
            "research": {"models": [{"id": "depalign-final", "name": "A", "validation": "开发集", "metrics": [{"display": "3", "scope": "开发集"}]},
                                     {"id": "unrelated", "name": "抑郁模型"}], "research_tracks": [],
                         "comparison": {"rows": [{"label": "无关的首选", "primary": True}]}},
            "progress": {"document": {"sources": [report, {"id": "unrelated"}], "directions": [{"id": "depalign-final", "report_count": 1,
                "results": [{"text": "本周已完成复核。", "source_ids": [source_id], "evidence": [{"source_id": source_id, "quote": "完成复核"}]}]}]}},
            "library": {"items": [{"id": "assetA", "title": "DAIC 条目", "kind": "dataset", "usage_note": "具名使用"},
                                  {"id": "assetB", "title": "daicology", "kind": "model"}]},
            "papers": {"papers": [{"id": "p1", "bibliography": {"title": "DAIC study", "fulltext_policy": "restricted"}}]},
        }

    def run_snapshot(self, *args, failed=None):
        with tempfile.TemporaryDirectory() as directory:
            src = {k: {"url": agent_client.ENDPOINTS[k], "status": "ok", "data": v} for k, v in self.data.items()}
            if failed:
                src[failed] = {"url": agent_client.ENDPOINTS[failed], "status": "failed", "error_code": 503}
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps({"mode": "offline_snapshot", "schema_version": "1.0", "sources": src}), encoding="utf-8")
            output, error = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), patch.object(agent_client, "fetch_json", side_effect=AssertionError("Offline only")):
                status = agent_client.main(["--snapshot", str(path), "direction", *args])
            return status, output.getvalue(), error.getvalue()

    def test_provenance_partial_coverage_and_candidates(self):
        rc, out, err = self.run_snapshot("depalign-final", "--format", "json", "--keyword", "DAIC", failed="papers")
        self.assertEqual((rc, err), (0, ""))
        pack = json.loads(out)
        self.assertEqual([x["id"] for x in pack["reviewed_findings"]["items"]], ["depalign-final"])
        self.assertIsNone(pack["reviewed_findings"]["comparison"])
        self.assertEqual([s["id"] for s in pack["recent_progress"]["sources"]], ["weekly:member:w1"])
        self.assertTrue(pack["recent_progress"]["claims"]["results"][0]["citation_complete"])
        self.assertEqual(pack["discovery"]["dataset"]["items"][0]["usage_note"], "具名使用")
        self.assertEqual(pack["discovery"]["model"]["total"], 0)
        self.assertIsNone(pack["discovery"]["papers"])
        self.assertEqual(pack["sources"]["papers"]["error_code"], 503)

    def test_ambiguous_unknown_directions_and_human_output(self):
        for query, message in [("抑郁", "匹配多个方向"), ("missing", "未找到")]:
            rc, _, err = self.run_snapshot(query)
            self.assertEqual(rc, 1)
            self.assertIn(message, err)
        rc, out, _ = self.run_snapshot("抑郁模型")
        self.assertEqual(rc, 0)
        for marker in ["DAIC", "具名使用", "完成复核", "https://rmp.wuwangwo.top/progress/api/report-source/", "开发集", "restricted"]:
            self.assertIn(marker, out)

    def test_stale_or_missing_digest_distinguished_from_no_reports(self):
        self.data["progress"] = {"status": {"state": "stale"}, "document": None}
        rc, out, _ = self.run_snapshot("depalign-final", "--format", "json")
        self.assertEqual(rc, 0)
        progress = json.loads(out)["recent_progress"]
        self.assertEqual(progress["status"], "stale")
        self.assertIsNone(progress["report_count"])
        self.assertFalse(progress["direction_in_digest"])
        rc, _, err = self.run_snapshot("depalign-final", failed="directions")
        self.assertEqual(rc, 1)
        self.assertIn("方向目录未成功读取", err)

    def test_live_command_reads_only_documented_urls(self):
        calls = []
        def fetch(base, path, headers):
            calls.append(path)
            name = 'papers' if path == '/papers/api/catalog' else next(k for k in self.data if agent_client.ENDPOINTS[k] == path)
            return self.data[name]
        with patch.object(agent_client, "fetch_json", fetch), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(agent_client.main(["direction", "depalign-final", "--format", "json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["mode"], "live")
        self.assertEqual(calls, [agent_client.ENDPOINTS[k] for k in self.data if k != 'papers'] + ['/papers/api/catalog'])

    def test_paper_card_and_author_keywords_remain_candidates(self):
        self.data['papers']['papers'] = [{'id': 'p2', 'card': {'title': 'A method', 'category': 'Speech', 'tags': ['声学']},
                                          'insight': {'keywords': ['PQRST'], 'author_keywords': {'terms': ['DAIC']}}}]
        rc, out, _ = self.run_snapshot("depalign-final", "--format", "json", "--keyword", "DAIC", "--keyword", "PQRST", "--keyword", "声学")
        self.assertEqual(rc, 0)
        item = json.loads(out)['discovery']['papers']['items'][0]
        self.assertEqual(item['matched_terms'], ['DAIC', 'PQRST', '声学'])
