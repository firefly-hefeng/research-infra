import datetime as dt
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from catalog import import_catalog
from platform_data import SERVERS, literature, metrics, servers_snapshot
from server import create_server
from tools.collect_server_resources import collect, save_snapshot


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data/annotations').mkdir(parents=True)
        self.catalog = {'schema_version': '1.0', 'assets': [
            {'id': 'a', 'name': '汉语会话', 'kind': 'dataset', 'status': 'verified'},
            {'id': 'b', 'name': '语音模型', 'kind': 'model', 'status': 'verified'}]}
        self.write('data/catalog.json', self.catalog)
        self.write('data/resource-mapping.json', {'items': [
            {'asset_id': 'a', 'card_url': '/docs/cards/reg-a.html'},
            {'asset_id': 'b', 'card_url': 'javascript:unsafe'}]})
        self.write('data/research-guide.json', {'categories': [
            {'id': 'speech', 'title': '语音研究', 'asset_ids': ['a']},
            {'id': 'models', 'title': '模型', 'asset_ids': ['b']}]})
        self.write('data/annotations/test.json', {'entries': {
            'a': {'research_uses': ['用于语言发展'], 'sources': [{'title': '真实官方说明', 'url': 'https://example.org/page#section'}]},
            'b': {'research_uses': ['语音转写'], 'sources': [
                {'title': '同一来源', 'url': 'https://example.org/page?utm_source=test'},
                {'title': '拒绝脚本', 'url': 'javascript:alert(1)'},
                {'title': '拒绝凭据', 'url': 'https://u:p@example.org/secret'},
                {'title': '拒绝口令参数', 'url': 'https://example.org/?access_token=private'}]},
            'unknown': {'sources': [{'title': '未知资源不凭空加入', 'url': 'https://unknown.org/'}]}}})

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def test_literature_deduplicates_real_urls_with_exact_resource_categories_and_uses(self):
        result = literature(self.root)
        self.assertEqual(result['total'], 1)
        row = result['items'][0]
        self.assertEqual(row['url'], 'https://example.org/page')
        self.assertEqual({item['asset_id'] for item in row['resources']}, {'a', 'b'})
        self.assertEqual({item['id'] for item in row['categories']}, {'speech', 'models'})
        self.assertEqual(row['resources'][0]['uses'], ['用于语言发展'])
        self.assertIsNone(next(item for item in row['resources'] if item['asset_id'] == 'b')['card_url'])
        self.assertFalse(result['capabilities']['personal_reading_progress'])
        self.assertFalse(result['capabilities']['full_text_library'])
        self.assertEqual(literature(self.root, q='语言发展', category='speech', domain='example.org', asset_id='a')['total'], 1)
        self.assertEqual(literature(self.root, q='not present')['total'], 0)
        self.assertEqual(literature(self.root, page=2, page_size=1)['items'], [])

    def test_server_whitelist_drops_processes_secrets_private_mounts_and_object_capacity(self):
        raw = {'cpu': {'logical_cores': 256, 'command': 'secret'}, 'password': 'never public',
               'processes': ['/data/users/person/private'], 'disks': [
                   {'mount': '/data/users/person', 'filesystem': 'xfs', 'total_bytes': 100},
                   {'mount': '/data/share_cold', 'filesystem': 'fuse.ossfs', 'total_bytes': 2**64,
                    'available_bytes': 2**64, 'used_percent': 0}],
               'gpus': [{'index': 0, 'name': 'GPU', 'utilization_percent': 101, 'processes': ['private'],
                         'memory_total_bytes': 10**1000}]}
        result = metrics(raw)
        encoded = json.dumps(result)
        self.assertNotIn('private', encoded)
        self.assertNotIn('password', encoded)
        self.assertIsNone(result['disks'][0]['total_bytes'])
        self.assertEqual(result['disks'][0]['capacity_note'], 'object_storage_capacity_not_applicable')
        self.assertIsNone(result['gpus'][0]['utilization_percent'])
        self.assertIsNone(result['gpus'][0]['memory_total_bytes'])

    def test_missing_and_stale_snapshots_do_not_imply_zero_usage_or_online(self):
        result = servers_snapshot(self.root)
        self.assertEqual(result['mode'], 'not_configured')
        self.assertTrue(all(row['stale'] and row['gpus'] is None for row in result['servers']))
        self.write('data/server-resources.json', {'schema_version': '1.0', 'generated_at': '2026-10-28T00:00:00Z',
            'servers': [{'id': 'server-101', 'status': 'online', 'observed_at': '2026-10-28T00:00:00Z',
                         'cpu': {'usage_percent': 91}}]})
        result = servers_snapshot(self.root, dt.datetime(2026, 10, 28, 1, tzinfo=dt.timezone.utc))
        row = result['servers'][1]
        self.assertTrue(row['stale']);self.assertEqual(row['age_seconds'], 3600)
        self.assertEqual(row['cpu']['usage_percent'], 91)

    def test_failed_collection_retains_last_observation_and_sanitizes_error(self):
        old = {'servers': [{'id': 'server-101', 'status': 'online', 'observed_at': '2026-10-28T00:00:00Z',
                            'cpu': {'usage_percent': 17}, 'password': 'never public'}]}
        result = collect(old, {}, {'timeout': 20}, selected=['101.132.97.146'],
                         collector=lambda *args: {'error_code': 'timeout'})
        row = result['servers'][1]
        self.assertEqual(row['status'], 'unreachable')
        self.assertEqual(row['observed_at'], '2026-10-28T00:00:00Z')
        self.assertEqual(row['cpu']['usage_percent'], 17)
        self.assertNotIn('password', json.dumps(result))
        save_snapshot(self.root / 'data/server-resources.json', result)
        self.assertEqual(servers_snapshot(self.root)['servers'][1]['error_code'], 'timeout')

    def test_http_routes_are_readonly_authenticated_and_never_collect(self):
        database = self.root / 'catalog.sqlite3'
        import_catalog(self.catalog, database)
        token = 'platform-test-token-01234567890123456789'
        server = create_server(database, port=0, root=self.root, token=token)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        def request(path, authorized=True, method='GET'):
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            client.request(method, path, headers={'Authorization': 'Bearer ' + token} if authorized else {})
            response = client.getresponse();data = response.read();client.close()
            return response.status, data
        try:
            with mock.patch('subprocess.run', side_effect=AssertionError('HTTP must never connect SSH')):
                for path in ('/api/platform/servers', '/api/platform/literature'):
                    self.assertEqual(request(path, False)[0], 401)
                    self.assertEqual(request(path)[0], 200)
                    self.assertEqual(request(path, method='POST')[0], 405)
                for path in ('/api/platform/servers?host=unknown', '/api/platform/literature?q=a&q=b',
                             '/api/platform/literature?page=0', '/api/platform/literature?page_size=101',
                             '/api/platform/literature?file=/etc/passwd'):
                    self.assertEqual(request(path)[0], 400)
                self.write('data/server-resources.json', {'schema_version': 'bad'})
                self.assertEqual(request('/api/platform/servers')[0], 503)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
