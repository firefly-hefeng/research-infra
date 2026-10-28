"""Exercise documentation/download access and the new read-only registry API."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import import_catalog
from server import create_server


class InventoryHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        (cls.root / "data").mkdir()
        (cls.root / "docs" / "templates").mkdir(parents=True)
        cls.mapping = {"schema_version": "1.0", "items": [{"asset_id": "a", "registry_id": "reg-stable", "current_path": "/data/datasets/a"}]}
        (cls.root / "data" / "resource-mapping.json").write_text(json.dumps(cls.mapping), encoding="utf-8")
        cls.guide = {"schema_version": "1.0", "categories": [{"id": "language", "asset_ids": ["a"]}]}
        (cls.root / "data" / "research-guide.json").write_text(json.dumps(cls.guide), encoding="utf-8")
        (cls.root / "data" / "resource-mapping.csv").write_text("registry_id,asset_id\nreg-stable,a\n", encoding="utf-8-sig")
        (cls.root / "docs" / "templates" / "schema.json").write_text('{"type":"object"}', encoding="utf-8")
        (cls.root / "docs" / "templates" / "manifest.jsonl").write_text('{"path":"example"}\n', encoding="utf-8")
        (cls.root / "docs" / "templates" / "templates.zip").write_bytes(b"PK-test-fixture")
        (cls.root / "docs" / "templates" / "private.py").write_text("not public", encoding="utf-8")
        cls.db = cls.root / "catalog.sqlite3"
        import_catalog({"schema_version": "1.0", "assets": [{"id": "a", "name": "A", "kind": "dataset", "status": "documented"}]}, cls.db)
        cls.token = "inventory-test-token-01234567890123456789"
        cls.server = create_server(cls.db, port=0, root=cls.root, token=cls.token)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def request(self, path, authenticated=True, method="GET"):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Authorization": "Bearer " + self.token} if authenticated else {}
        client.request(method, path, headers=headers)
        response = client.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        client.close()
        return result

    def test_registry_and_templates_require_authentication(self):
        for path in ("/api/research-guide", "/api/resource-mapping", "/api/resource-mapping.csv", "/api/resource-mapping/reg-stable",
                     "/docs/templates/schema.json", "/docs/templates/manifest.jsonl", "/docs/templates/templates.zip"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, authenticated=False)[0], 401)
                self.assertEqual(self.request(path)[0], 200)

    def test_registry_preserves_ids_and_rejects_writes(self):
        self.assertEqual(json.loads(self.request("/api/resource-mapping")[2]), self.mapping)
        self.assertEqual(json.loads(self.request("/api/resource-mapping/reg-stable")[2]), self.mapping["items"][0])
        self.assertEqual(self.request("/api/resource-mapping/missing")[0], 404)
        self.assertEqual(self.request("/api/resource-mapping?path=/etc/passwd")[0], 400)
        self.assertEqual(self.request("/api/resource-mapping", method="POST")[0], 405)
        self.assertEqual(self.request("/api/resource-mapping", method="HEAD")[2], b"")
        status, headers, body = self.request("/api/resource-mapping.csv")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))

    def test_document_download_types_and_path_boundary(self):
        self.assertEqual(self.request("/docs/templates/schema.json")[1]["Content-Type"], "application/json")
        self.assertIn("text/plain", self.request("/docs/templates/manifest.jsonl")[1]["Content-Type"])
        self.assertIn("attachment", self.request("/docs/templates/templates.zip")[1]["Content-Disposition"])
        for path in ("/data/resource-mapping.json", "/docs/templates/private.py", "/docs/%2e%2e/data/resource-mapping.json"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/docs/templates/schema.json")[1]["X-Content-Type-Options"], "nosniff")

    def test_research_guide_rejects_ambiguous_membership_and_queries(self):
        self.assertEqual(json.loads(self.request("/api/research-guide")[2]), self.guide)
        self.assertEqual(self.request("/api/research-guide?path=/etc/passwd")[0], 400)
        self.assertEqual(self.request("/api/research-guide", method="POST")[0], 405)
        target = self.root / "data" / "research-guide.json"
        before = target.read_bytes()
        try:
            for categories in ([None], [{"id": "x", "asset_ids": "a"}],
                               [{"id": "x", "asset_ids": ["a", "a"]}],
                               [{"id": "x", "asset_ids": ["a"]}, {"id": "y", "asset_ids": ["a"]}]):
                target.write_text(json.dumps({"categories": categories}), encoding="utf-8")
                self.assertEqual(self.request("/api/research-guide")[0], 503)
        finally:
            target.write_bytes(before)

    def test_malformed_registry_returns_controlled_unavailable_error(self):
        target = self.root / "data" / "resource-mapping.json"
        before = target.read_bytes()
        try:
            for malformed in ({"items": [None]}, {"items": ["entry"]}, {"items": [{}]},
                              {"items": [self.mapping["items"][0]] * 2}):
                target.write_text(json.dumps(malformed), encoding="utf-8")
                for path in ("/api/resource-mapping", "/api/resource-mapping/reg-stable"):
                    status, _, body = self.request(path)
                    self.assertEqual(status, 503)
                    self.assertEqual(json.loads(body)["error"]["code"], "mapping_unavailable")
        finally:
            target.write_bytes(before)


if __name__ == "__main__":
    unittest.main()
