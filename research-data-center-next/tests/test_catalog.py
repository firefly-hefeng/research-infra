"""Meaningful integrity and read-only HTTP boundary tests; no external services."""
import copy
import csv
import http.client
import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import CatalogError, export_catalog, export_csv, get_summary, import_catalog, open_catalog, query_assets
from server import create_server, loopback_host


def sample_document():
    return {
        "schema_version": "1.0", "generated_at": "2026-10-19T03:00:00+08:00",
        "scope": {"limitation": "document inventory only"}, "sources": [{"id": "manual", "name": "数据台账"}],
        "custom_top": {"preserve": True},
        "assets": [
            {"id": "ds-中文", "name": "中文 100% RNA Straße", "kind": "dataset", "server": "alpha",
             "category": "single-cell", "path": "/data/never-read", "description": "Cell Atlas", "status": "documented",
             "tags": ["免疫", "scRNA"], "size_bytes": None, "metadata": {"revision": "v1"}, "extra": {"nested": [1, 2]}},
            {"id": "model-1", "name": " =SUM(1,2)", "kind": "model", "server": "beta",
             "category": "language", "path": "/data/models/a", "status": "verified", "size_bytes": 0,
             "notes": "+external", "source_url": "@suspicious", "formats": ["safetensors"]},
        ],
    }


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "catalog.sqlite3"
        self.document = sample_document()
        import_catalog(self.document, self.db)

    def snapshot(self):
        with closing(open_catalog(self.db)) as connection:
            return export_catalog(connection)

    def test_duplicate_or_invalid_import_preserves_existing_snapshot(self):
        before = self.snapshot()
        for change in ("duplicate", "invalid_count", "invalid_kind", "nan"):
            broken = copy.deepcopy(self.document)
            if change == "duplicate":
                broken["assets"].append(copy.deepcopy(broken["assets"][0]))
            elif change == "invalid_count":
                broken["assets"][1]["file_count"] = -1
            elif change == "invalid_kind":
                broken["assets"][1]["kind"] = "unknown"
            else:
                broken["assets"][1]["metadata"] = {"score": float("nan")}
            with self.subTest(change=change), self.assertRaises(CatalogError):
                import_catalog(broken, self.db)
            self.assertEqual(before, self.snapshot())

    def test_sql_failure_rolls_back_deletes_and_metadata(self):
        before = self.snapshot()
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute("CREATE TRIGGER fail_import BEFORE INSERT ON assets BEGIN SELECT RAISE(ABORT, 'simulate failure'); END")
            connection.commit()
        changed = copy.deepcopy(self.document)
        changed["generated_at"] = "changed"
        with self.assertRaises(sqlite3.DatabaseError):
            import_catalog(changed, self.db)
        self.assertEqual(before, self.snapshot())

    def test_unknown_fields_nulls_and_input_are_preserved(self):
        original = copy.deepcopy(self.document)
        import_catalog(self.document, self.db)
        self.assertEqual(original, self.document)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["custom_top"], {"preserve": True})
        self.assertEqual(snapshot["assets"][0]["extra"], {"nested": [1, 2]})
        self.assertIsNone(snapshot["assets"][0]["size_bytes"])
        self.assertEqual(snapshot["assets"][1]["size_bytes"], 0)
        with closing(open_catalog(self.db)) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM assets")

    def test_unicode_literal_search_filters_and_pagination(self):
        with closing(open_catalog(self.db)) as connection:
            for query in ("中文", "STRASSE", "cell 免疫", "100%"):
                result = query_assets(connection, q=query)
                self.assertEqual(result["total"], 1, query)
                self.assertEqual(result["items"][0]["id"], "ds-中文")
            self.assertEqual(query_assets(connection, q="% OR 1=1 --")["total"], 0)
            self.assertEqual(query_assets(connection, server="alpha' OR 1=1--")["total"], 0)
            self.assertEqual(query_assets(connection, kind="model", server="beta")["total"], 1)
            self.assertEqual(query_assets(connection, page=2, page_size=1)["items"][0]["id"], "model-1")
            self.assertEqual(query_assets(connection, page=99)["items"], [])
            for kwargs in ({"page": 0}, {"page_size": 0}, {"page_size": 201}, {"page": 1.5}, {"q": "x" * 501}):
                with self.subTest(kwargs=kwargs), self.assertRaises(CatalogError):
                    query_assets(connection, **kwargs)

    def test_csv_formula_cells_are_escaped(self):
        with closing(open_catalog(self.db)) as connection:
            rows = list(csv.DictReader(io.StringIO(export_csv(connection))))
        self.assertEqual(rows[1]["name"], "' =SUM(1,2)")
        self.assertEqual(rows[1]["notes"], "'+external")
        self.assertEqual(rows[1]["source_url"], "'@suspicious")
        self.assertEqual(rows[0]["name"], "中文 100% RNA Straße")
        self.assertEqual(rows[0]["size_bytes"], "")
        self.assertEqual(rows[1]["size_bytes"], "0")

    def test_reimport_replaces_not_duplicates(self):
        document = sample_document()
        document["assets"] = document["assets"][:1]
        import_catalog(document, self.db)
        with closing(open_catalog(self.db)) as connection:
            summary = get_summary(connection)
            self.assertEqual(summary["total"], 1)
            self.assertEqual(summary["by_kind"], {"dataset": 1})
            self.assertEqual(summary["scope"], document["scope"])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.db = cls.root / "var" / "catalog.sqlite3"
        import_catalog(sample_document(), cls.db)
        (cls.root / "static").mkdir()
        (cls.root / "static" / "index.html").write_text("<!doctype html><p>目录</p>", encoding="utf-8")
        (cls.root / "static" / "app.js").write_text("console.log('ready')", encoding="utf-8")
        (cls.root / "static" / "private.py").write_text("SECRET", encoding="utf-8")
        (cls.root / "docs").mkdir()
        (cls.root / "docs" / "plan.md").write_text("# plan", encoding="utf-8")
        (cls.root / "docs" / "plan.html").write_text("<h1>plan</h1>", encoding="utf-8")
        cls.server = create_server(cls.db, port=0, root=cls.root)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def request(self, path, method="GET", headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {}, body=body)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_readonly_routes_json_and_unknown_id(self):
        for path in ("/api/health", "/api/summary", "/api/assets", "/api/export.json", "/api/agent/manifest", "/api/openapi.json", "/api/docs"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertIsInstance(json.loads(body), dict)
                self.assertNotIn("Access-Control-Allow-Origin", headers)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        status, _, body = self.request("/api/assets/" + quote("ds-中文"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["id"], "ds-中文")
        status, _, body = self.request("/api/assets/missing")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "asset_not_found")
        status, headers, body = self.request("/api/export.csv")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_invalid_queries_return_400_without_sql_errors(self):
        for query in ("page=0", "page=abc", "page_size=201", "page_size=-1", "kind=a&kind=b", "unknown=1", "q=" + "a" * 501):
            with self.subTest(query=query):
                status, _, body = self.request("/api/assets?" + query)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(body))
        status, _, body = self.request("/api/assets?q=" + quote("' OR 1=1 --"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["total"], 0)

    def test_static_allowlist_and_traversal(self):
        for path in ("/", "/app.js", "/docs/plan.md", "/docs/plan.html"):
            self.assertEqual(self.request(path)[0], 200)
        for path in ("/../var/catalog.sqlite3", "/%2e%2e/var/catalog.sqlite3", "/docs/%2e%2e/var/catalog.sqlite3",
                     "/var/catalog.sqlite3", "/data/catalog.json", "/private.py", "/.hidden.html", "/docs/", "/C:/Windows/test.html"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"SECRET", body)
        self.assertEqual(self.request("/%5c..%5cvar%5ccatalog.sqlite3")[0], 400)
        self.assertEqual(self.request("/%00.html")[0], 400)

    def test_mutation_methods_and_dns_rebinding_rejected(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            status, headers, body = self.request("/api/assets", method=method)
            self.assertEqual(status, 405)
            self.assertEqual(headers["Allow"], "GET, HEAD")
            self.assertEqual(json.loads(body)["error"]["code"], "method_not_allowed")
        self.assertEqual(self.request("/api/summary", headers={"Host": "evil.example"})[0], 403)
        status, _, body = self.request("/api/summary", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        for host in ("0.0.0.0", "::", "192.168.0.1", "example.com"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                loopback_host(host)

    def test_missing_database_returns_safe_503(self):
        previous = self.server.db_path
        try:
            self.server.db_path = self.root / "not-existing.sqlite3"
            status, _, body = self.request("/api/summary")
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body)["error"]["code"], "catalog_unavailable")
            self.assertNotIn(str(self.root).encode(), body)
            self.assertEqual(self.request("/api/does-not-exist")[0], 404)
        finally:
            self.server.db_path = previous


class AuthenticationTests(unittest.TestCase):
    token = "test-only-0123456789abcdef0123456789abcdef"
    request = HTTPTests.request

    @classmethod
    def setUpClass(cls):
        HTTPTests.setUpClass.__func__(cls)
        cls.server.auth_token = cls.token

    @classmethod
    def tearDownClass(cls):
        HTTPTests.tearDownClass.__func__(cls)

    def test_private_routes_require_authentication_but_shell_is_public(self):
        for path in ("/api/summary", "/api/assets", "/api/assets/model-1", "/api/export.json", "/api/export.csv", "/api/docs", "/docs/plan.html", "/api/agent/manifest", "/api/openapi.json"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 401)
                self.assertEqual(json.loads(body)["error"]["code"], "unauthenticated")
                self.assertNotIn(b"model-1", body)
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/app.js")[0], 200)
        status, _, body = self.request("/api/health")
        self.assertEqual(status, 200)
        health = json.loads(body)
        self.assertTrue(health["authentication_required"])
        self.assertNotIn("sources", health)
        self.assertEqual(json.loads(self.request("/api/session")[2]), {"auth_enabled": True, "authenticated": False})

    def test_bearer_auth_and_forwarded_host_port(self):
        self.assertEqual(self.request("/api/summary", headers={"Authorization": "Bearer wrong"})[0], 401)
        for path in ("/api/summary", "/api/export.json", "/api/assets/model-1", "/docs/plan.html"):
            self.assertEqual(self.request(path, headers={"Authorization": "Bearer " + self.token})[0], 200)
        self.assertEqual(self.request("/api/summary", headers={"Authorization": "Bearer " + self.token, "Host": "localhost:9876"})[0], 200)
        self.assertEqual(self.request("/api/summary", headers={"Authorization": "Bearer " + self.token, "Host": "localhost:99999"})[0], 403)

    def test_session_cookie_login_tamper_and_logout(self):
        headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.server.server_port}"}
        status, _, _ = self.request("/api/session", method="POST", headers=headers, body=json.dumps({"token": "wrong"}))
        self.assertEqual(status, 401)
        status, response_headers, body = self.request("/api/session", method="POST", headers=headers, body=json.dumps({"token": self.token}))
        self.assertEqual(status, 200)
        cookie = response_headers["Set-Cookie"]
        for attribute in ("HttpOnly", "SameSite=Strict", "Max-Age=43200", "Path=/"):
            self.assertIn(attribute, cookie)
        self.assertNotIn(self.token, cookie)
        self.assertTrue(json.loads(body)["authenticated"])
        session_headers = {"Cookie": cookie.split(";", 1)[0]}
        self.assertEqual(self.request("/api/export.json", headers=session_headers)[0], 200)
        self.assertTrue(json.loads(self.request("/api/session", headers=session_headers)[2])["authenticated"])
        self.assertEqual(self.request("/api/export.json", headers={"Cookie": session_headers["Cookie"] + "tampered"})[0], 401)
        status, response_headers, _ = self.request("/api/session", method="DELETE", headers=session_headers)
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", response_headers["Set-Cookie"])

    def test_cross_origin_and_session_body_limits(self):
        for origin in ("https://evil.example", "null", "http://localhost:9999"):
            headers = {"Content-Type": "application/json", "Origin": origin, "Authorization": "Bearer " + self.token}
            self.assertEqual(self.request("/api/session", method="POST", headers=headers, body=json.dumps({"token": self.token}))[0], 403)
            self.assertEqual(self.request("/api/summary", headers=headers)[0], 403)
        headers = {"Content-Type": "application/json"}
        self.assertEqual(self.request("/api/session", method="POST", headers=headers, body="x" * 4097)[0], 413)
        self.assertEqual(self.request("/api/session", method="POST", headers=headers, body="not json")[0], 400)
        self.assertEqual(self.request("/api/session", method="POST", headers=headers, body="[]")[0], 400)
        headers = {"Content-Type": "application/json", "Host": "localhost:9876", "Origin": "http://localhost:9876"}
        self.assertEqual(self.request("/api/session", method="POST", headers=headers, body=json.dumps({"token": self.token}))[0], 200)


if __name__ == "__main__":
    unittest.main()
