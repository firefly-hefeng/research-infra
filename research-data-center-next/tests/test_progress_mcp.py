import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.progress_mcp import ProgressTools
from tools.progress_mcp_source import PATHS, ProgressSource, Unavailable, loopback


def snapshot(path, state="ready"):
    source = {"id": "report-x", "title": "测试周报", "original_url": "/progress/#team?week=2026-W01"}
    claims = [{"text": "已完成两组对照", "source_ids": ["report-x"], "evidence": [{"source_id": "report-x", "quote": "两组对照"}]}]
    row = {"done": claims, "results": [], "blockers": [], "next": []}
    digest = {"status": {"state": state}, "document": {"team": row, "members": [{"id": "m-synthetic", "name": "示例成员", **row}],
              "directions": [{"id": "d-synthetic", "title": "示例主题", **row}], "sources": [source], "counts": {}, "revision": 1}}
    data = {"digest": digest, "directions": {"items": [{"id": "d-synthetic", "title": "示例主题"}]},
            "methods": {"directions": [{"id": "methods-a", "title": "示例对照", "registered_direction_id": "d-synthetic",
                                        "methods": [{"name": "固定划分", "comparison": "两组", "source_ids": ["orig"]}]}],
                        "sources": [{"id": "orig", "title": "合成记录", "quote": "固定划分"}]}}
    doc = {"mode": "offline_snapshot", "schema_version": "1.0", "generated_at": "2026-01-01",
           "sources": {k: {"status": "ok", "url": PATHS[k], "data": v} for k, v in data.items()}}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return doc


class ProgressMcpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "context.json"
        self.doc = snapshot(self.path)
        self.api = ProgressTools(ProgressSource(snapshot=self.path))

    def test_old_snapshot_found_zero_and_missing_are_different(self):
        data = self.api.query("member", "示例成员")
        self.assertEqual(data["status"], "partial")
        self.assertIn("未包含", data["issues"][0]["message"])
        m = data["data"]["digest"]
        self.assertEqual(m["source"]["snapshot_generated_at"], "2026-01-01")
        self.assertEqual(m["record"]["available_counts"]["blockers"], 0)
        self.assertEqual(m["record"]["sources"][0]["id"], "report-x")
        self.assertFalse(self.api.query("member", "absent")["data"]["digest"]["found"])
        snapshot(self.path, "stale")
        self.assertIn("stale", str(self.api.query("team")["issues"]))

    def test_direction_method_sources_and_ids(self):
        for query in ("示例对照", "methods-a", "d-synthetic"):
            record = self.api.query("methods", query)["data"]["methods"]
            self.assertEqual(record["directions"][0]["methods"][0]["comparison"], "两组")
            self.assertEqual(record["sources"][0]["id"], "orig")
        self.assertEqual(self.api.query("methods")["data"]["methods"]["items"][0]["method_count"], 1)
        self.doc["sources"]["methods"]["data"].update(status="not_published", directions=[])
        self.path.write_text(json.dumps(self.doc))
        with self.assertRaisesRegex(ValueError, "尚未发布"):
            self.api.query("methods")
        self.doc["sources"].pop("methods")
        self.path.write_text(json.dumps(self.doc))
        with self.assertRaisesRegex(ValueError, "未包含"):
            self.api.query("methods")

    def test_withheld_evidence_and_suggestions_survive(self):
        self.doc["sources"]["review"] = {"status": "ok", "url": PATHS["review"], "data": {
            "lab": {"next": [{"text_withheld": True, "basis": "model_suggestion", "evidence": [
                {"source_id": "ref", "quote_withheld": True}]}]}, "sources": [{"id": "ref", "kind": "weekly"}]}}
        self.path.write_text(json.dumps(self.doc))
        out = self.api.query("team")["data"]["review"]["claims"]["next"][0]
        self.assertEqual(out["basis"], "model_suggestion")
        self.assertTrue(out["evidence"][0]["quote_withheld"])
        self.doc["sources"]["review"]["data"]["audience"] = "internal"
        self.path.write_text(json.dumps(self.doc))
        self.assertNotIn("review", self.api.query("team")["data"])

    def test_new_method_edition_keeps_contacts_separate_and_traceable(self):
        raw = self.doc["sources"]["methods"]["data"]
        raw.update(status="published", as_of="2026-01-01")
        raw["directions"][0].update(owner={"status": "unconfirmed", "source_ids": []},
            next_step_basis="建议", verification_contacts=[{"member_id": "m-other", "basis": "项目空间", "source_ids": ["note-x"]}])
        raw["sources"].append({"id": "note-x", "kind": "weekly", "title": "模拟线索"})
        self.path.write_text(json.dumps(self.doc))
        result = self.api.query("methods", "methods-a")["data"]["methods"]
        self.assertEqual(result["as_of"], "2026-01-01")
        direction = result["directions"][0]
        self.assertEqual(direction["owner"]["status"], "unconfirmed")
        self.assertEqual(direction["verification_contacts"][0]["basis"], "项目空间")
        self.assertEqual({r["id"] for r in result["sources"]}, {"orig", "note-x"})

    def test_auth_and_loopback(self):
        for origin in ("http://example.org:8766", "http://p@127.0.0.1:8766", "http://127.0.0.1:8766/other"):
            with self.assertRaises(ValueError):
                loopback(origin)
        browser = ProgressSource()
        with patch.object(browser, "_command", side_effect=[
            {"tabs": [{"url": "https://rmp.wuwangwo.top.bad/other", "tabId": 1},
                      {"url": "https://rmp.wuwangwo.top/progress/", "tabId": 2}]}, {}, {"value": '{"status":401}'}]) as calls:
            with self.assertRaisesRegex(Unavailable, "飞书登录"):
                browser.get("methods")
        self.assertEqual(calls.call_args_list[1].args, ("attach_tab", {"tabId": 2}))
        self.assertIn("credentials:'same-origin'", calls.call_args_list[-1].args[1]["code"])

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "需安装 tools/requirements-progress-mcp.txt")
    def test_official_client_stdio_handshake_and_every_tool(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def run():
            file = Path(__file__).resolve().parents[1] / "tools" / "progress_mcp.py"
            params = StdioServerParameters(command=sys.executable, args=[str(file), "--snapshot", str(self.path)])
            async with stdio_client(params) as (rx, tx), ClientSession(rx, tx) as c:
                hello = await c.initialize()
                self.assertEqual(hello.serverInfo.name, "research-progress")
                listed = (await c.list_tools()).tools
                self.assertEqual({v.name for v in listed}, {"team_progress", "member_progress", "direction_progress", "direction_methods"})
                for entry in listed:
                    self.assertTrue(entry.annotations.readOnlyHint)
                    result = await c.call_tool(entry.name, {})
                    self.assertFalse(result.isError, result.content)
                    self.assertEqual(json.loads(result.content[0].text)["mode"], "member_snapshot")
                    self.assertEqual(result.structuredContent["mode"], "member_snapshot")
                self.assertTrue((await c.call_tool("team_progress", {"limit": -1})).isError)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
