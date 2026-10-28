"""Read-only portal adapter tests. Temporary SQLite fixtures; no worker execution."""
from contextlib import closing
import datetime as dt
import http.client
import json
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import sys
import threading
import unittest
from unittest import mock
from contextlib import redirect_stdout

import server


class IngestionHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.token = 'ingestion-test-token-01234567890123456789'
        cls.server = server.create_server(cls.root / 'unused-catalog.sqlite3', port=0,
                                          root=cls.root, token=cls.token)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def setUp(self):
        self.server.state_dir = None

    def request(self, path, method='GET', auth=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, headers={'Authorization': 'Bearer ' + self.token} if auth else {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def database(self):
        directory = self.root / self._testMethodName
        directory.mkdir()
        path = directory / 'ingestion.sqlite3'
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
            con.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,user TEXT,status TEXT,submitted_at TEXT,updated_at TEXT,document TEXT,ready TEXT,plan TEXT,reason_code TEXT,content_digest TEXT,publication TEXT)')
            con.execute('INSERT INTO meta VALUES (?,?)', ('worker_enabled', 'true'))
        self.server.state_dir = directory
        return path

    def test_manifest_and_status_are_authenticated_get_only(self):
        for endpoint in ('/api/ingestion/manifest', '/api/ingestion/status', '/api/ingestion/published'):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.request(endpoint, auth=False)[0], 401)
                self.assertEqual(self.request(endpoint)[0], 200)
                self.assertEqual(self.request(endpoint, 'HEAD')[2], b'')
                for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                    self.assertEqual(self.request(endpoint, method)[0], 405)
                    self.assertEqual(self.request(endpoint, method, auth=False)[0], 405)
                self.assertEqual(self.request(endpoint + '?scan=1')[0], 400)
        manifest = json.loads(self.request('/api/ingestion/manifest')[2])
        self.assertEqual(manifest['worker_kind'], 'rules')
        self.assertFalse(manifest['llm_enabled'])
        self.assertEqual(manifest['incoming_root'], '/data/share/incoming')
        self.assertIn('management', manifest['roles'])

    def test_default_and_missing_state_never_create_or_scan(self):
        with mock.patch('ingestion.snapshot', side_effect=AssertionError('must not read implicit state')):
            payload = json.loads(self.request('/api/ingestion/status')[2])
            self.assertEqual(payload['mode'], 'not-configured')
            self.assertIsNone(payload['counts'])
        absent = self.root / 'must-not-be-created'
        self.server.state_dir = absent
        payload = json.loads(self.request('/api/ingestion/status')[2])
        self.assertEqual(payload['mode'], 'not-configured')
        self.assertIsNone(payload['counts'])
        self.assertEqual(payload['jobs'], [])
        self.assertFalse(absent.exists())
        self.assertFalse((self.root / 'unused-catalog.sqlite3').exists())

    def test_runtime_modes_come_from_real_readonly_database(self):
        path = self.database()
        before = path.read_bytes()
        result = json.loads(self.request('/api/ingestion/status')[2])
        self.assertEqual(result['mode'], 'planned')
        self.assertEqual(path.read_bytes(), before)
        for enabled, heartbeat, expected in (
            (False, None, 'disabled'),
            (True, dt.datetime.now(dt.timezone.utc).isoformat(), 'active'),
            (True, '2020-01-01T00:00:00+00:00', 'worker-stale'),
        ):
            with closing(sqlite3.connect(path)) as con, con:
                con.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('worker_enabled', json.dumps(enabled)))
                con.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('last_heartbeat_at', json.dumps(heartbeat)))
            before = path.read_bytes()
            result = json.loads(self.request('/api/ingestion/status')[2])
            self.assertEqual(result['mode'], expected)
            self.assertEqual(result['worker']['kind'], 'rules')
            self.assertFalse(result['worker']['llm_enabled'])
            self.assertEqual(path.read_bytes(), before)

    def test_queue_is_bounded_and_strips_private_payload_and_credentials(self):
        path = self.database()
        stamp = '2026-10-27T09:00:00+00:00'
        document = {'title': 'Shared dataset', 'type': 'dataset', 'token': 'SECRET_CREDENTIAL',
                    'payload': '/private/RAW_PAYLOAD'}
        with closing(sqlite3.connect(path)) as con, con:
            for i in range(25):
                con.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,NULL)',
                            ('job-%02d' % i, 'PRIVATE_USERNAME', 'submitted', stamp, stamp,
                             json.dumps(document), '{"file_count":2}',
                             '{"target_path":"/private/STAGING_PATH"}', 'awaiting_rules', 'ab' * 32))
        status, _, body = self.request('/api/ingestion/status')
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result['counts']['submitted'], 25)
        self.assertEqual(len(result['jobs']), 20)
        self.assertEqual(set(result['jobs'][0]), {'id', 'display_name', 'kind', 'status', 'submitted_at', 'updated_at', 'reason_code'})
        for forbidden in (b'SECRET_CREDENTIAL', b'RAW_PAYLOAD', b'STAGING_PATH', b'PRIVATE_USERNAME', str(path).encode()):
            self.assertNotIn(forbidden, body)

    def test_bad_snapshot_fails_safely_without_private_error_details(self):
        self.server.state_dir = self.root
        with mock.patch('ingestion.snapshot', side_effect=sqlite3.DatabaseError('/private/db SECRET')):
            status, _, body = self.request('/api/ingestion/status')
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)['error']['code'], 'ingestion_unavailable')
        self.assertNotIn(b'SECRET', body)
        self.assertNotIn(b'/private', body)

    def test_published_resources_are_separate_and_only_public_managed_paths_are_exposed(self):
        path = self.database()
        receipt = {'resource_id': 'test-resource', 'version': 'v1', 'kind': 'dataset',
                   'target_path': '/data/share/datasets/managed/test-resource/v1', 'title': 'New resource',
                   'published_at': '2026-10-27T09:00:00+00:00', 'file_count': 2, 'total_bytes': 1024,
                   'content_digest': 'a' * 64, 'curation_status': 'team_card_pending',
                   'source_identity': '/private/NEVER_PUBLIC', 'maintainer_authority': {'token': 'SECRET'}}
        with closing(sqlite3.connect(path)) as con, con:
            for i, target in enumerate((receipt['target_path'], '/private/OUTSIDE')):
                candidate = dict(receipt, target_path=target)
                con.execute('INSERT INTO jobs(id,status,publication) VALUES (?,?,?)',
                            ('published-%d' % i, 'published', json.dumps(candidate)))
        before = path.read_bytes()
        status, _, body = self.request('/api/ingestion/published')
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result['registration'], 'independent_tracking')
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['curation_status'], 'team_card_pending')
        self.assertEqual(result['items'][0]['resource_id'], 'test-resource')
        for private in (b'/private', b'SECRET', b'maintainer_authority', b'source_identity'):
            self.assertNotIn(private, body)
        self.assertEqual(path.read_bytes(), before)

    def test_cli_serving_root_and_local_state_environment_are_forwarded(self):
        fake_server = mock.Mock(server_address=('127.0.0.1', 8765), server_port=8765)
        workspace = self.root / 'workspace'
        state_dir = self.root / 'runtime-state'
        with mock.patch.dict(os.environ, {'RCA_STATE_DIR': str(state_dir)}), \
                mock.patch.object(sys, 'argv', ['server.py', '--root', str(workspace)]), \
                mock.patch('server.open_catalog', return_value=mock.Mock()), \
                mock.patch('server.get_summary'), \
                mock.patch('server.create_server', return_value=fake_server) as factory, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(server.main(), 0)
        self.assertEqual(factory.call_args.kwargs['root'], workspace)
        self.assertEqual(factory.call_args.kwargs['state_dir'], state_dir)
        self.assertFalse(workspace.exists())
        self.assertFalse(state_dir.exists())

    def test_openapi_and_agent_manifest_expose_get_contract(self):
        document = json.loads(self.request('/api/openapi.json')[2])
        for endpoint in ('/api/ingestion/manifest', '/api/ingestion/status', '/api/ingestion/published'):
            self.assertEqual(set(document['paths'][endpoint]), {'get'})
        agent = json.loads(self.request('/api/agent/manifest')[2])
        self.assertEqual(agent['endpoints']['ingestion_status'], '/api/ingestion/status')
        self.assertEqual(set(server.INGESTION_MODES), set(document['paths']['/api/ingestion/status']['get']['responses']['200']['content']['application/json']['schema']['properties']['mode']['enum']))

    def test_existing_progress_proxy_is_preserved(self):
        with mock.patch('server.proxy_progress', side_effect=lambda handler: handler._json({'retained': True})) as proxy:
            self.assertEqual(json.loads(self.request('/progress/')[2]), {'retained': True})
            self.assertEqual(json.loads(self.request('/progress/api/uploads', 'POST')[2]), {'retained': True})
            self.assertEqual(proxy.call_count, 2)

    def test_optional_auth_development_mode_remains_read_only(self):
        token = self.server.auth_token
        self.server.auth_token = None
        try:
            self.assertEqual(self.request('/api/ingestion/status', auth=False)[0], 200)
            self.assertEqual(self.request('/api/ingestion/status', 'POST', auth=False)[0], 405)
        finally:
            self.server.auth_token = token


if __name__ == '__main__':
    unittest.main()
