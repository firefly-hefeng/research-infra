import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from paperlib.library import Library
from paperlib.providers import save_settings, load_settings, public_settings, api_card
from paperlib.worker import configuration, run_batch
import test_library as fixtures


class ProviderTests(unittest.TestCase):
    card = fixtures.LibraryTests.card

    def setUp(self):
        self.env = patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith('PAPER_')}, clear=True)
        self.env.start()
        fixtures.LibraryTests.setUp(self)
        self.calls = []
        self.response_card = self.card()
        self.http_status = 200
        self.delay = 0
        self.response_raw = None
        self.finish_reason = 'stop'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append({'path': self.path, 'body': payload, 'authorization': self.headers.get('Authorization')})
                time.sleep(owner.delay)
                body = owner.response_raw or json.dumps({'choices': [{'finish_reason': owner.finish_reason,
                    'message': {'content': json.dumps(owner.response_card)}}]}).encode()
                self.send_response(owner.http_status)
                self.send_header('Content-Type', 'application/json')
                if owner.http_status == 302:
                    self.send_header('Location', '/redirected')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port) + '/v1'
        save_settings(self.lib, {'api_base_url': self.base, 'api_model': 'test-model', 'api_key': 'secret-test-key'})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        fixtures.LibraryTests.tearDown(self)
        self.env.stop()

    def agent(self, code):
        file = Path(self.tmp.name) / 'agent.py'
        file.write_text(code)
        os.environ['PAPER_AGENT_COMMAND'] = json.dumps([sys.executable, str(file)])

    def test_agent_success_does_not_call_api(self):
        self.agent('print(' + repr(json.dumps(self.card())) + ')')
        result = run_batch(self.lib)
        self.assertEqual(result['providers'], {'agent': 1, 'api': 0})
        self.assertEqual(self.calls, [])
        self.assertEqual(result['fallbacks'], 0)

    def test_agent_failure_falls_back_and_archives_once(self):
        self.agent('import sys; sys.exit(7)')
        with patch.object(self.lib, 'commit', wraps=self.lib.commit) as commit:
            result = run_batch(self.lib)
            self.assertEqual(commit.call_count, 1)
        self.assertEqual(result['providers'], {'agent': 0, 'api': 1})
        self.assertEqual(result['fallbacks'], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('7', result['items'][0]['attempts'][0]['error'])
        self.assertEqual(Library(self.root).record(self.id)['status'], 'ready')
        self.assertFalse(self.source.exists())
        request = self.calls[0]
        self.assertEqual(request['path'], '/v1/chat/completions')
        self.assertEqual(request['authorization'], 'Bearer secret-test-key')
        self.assertEqual(request['body']['model'], 'test-model')
        self.assertIn('Paper Curator', request['body']['messages'][0]['content'])
        data = json.loads(request['body']['messages'][1]['content'])
        self.assertIn('PDF PAGE 1', data['pdf_text'])
        self.assertIn('existing_tags', data)

    def test_invalid_agent_evidence_falls_back(self):
        bad = self.card()
        bad['evidence'][0]['quote'] = 'This invented quote does not exist in the source.'
        self.agent('print(' + repr(json.dumps(bad)) + ')')
        result = run_batch(self.lib)
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['providers']['api'], 1)
        self.assertIn('证据', result['items'][0]['attempts'][0]['error'])

    def test_agent_timeout_falls_back(self):
        save_settings(self.lib, {'agent_timeout': 1})
        self.agent('import time; time.sleep(10)')
        result = run_batch(self.lib)
        self.assertEqual(result['providers']['api'], 1)
        self.assertIn('超时', result['items'][0]['attempts'][0]['error'])

    def test_missing_or_malformed_agent_uses_api(self):
        os.environ['PAPER_AGENT_COMMAND'] = '{invalid'
        result = run_batch(self.lib)
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['fallbacks'], 1)

    def test_api_only_never_calls_agent(self):
        save_settings(self.lib, {'mode': 'api', 'api_json_mode': False})
        with patch('paperlib.worker.agent_card', side_effect=AssertionError('Agent called')):
            result = run_batch(self.lib)
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['fallbacks'], 0)
        self.assertNotIn('response_format', self.calls[0]['body'])

    def test_agent_only_never_falls_back(self):
        save_settings(self.lib, {'mode': 'agent'})
        self.agent('print("invalid JSON")')
        result = run_batch(self.lib)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.source.exists())

    def test_both_fail_keep_source_and_safe_errors(self):
        self.agent('print("invalid JSON")')
        self.http_status = 401
        self.response_raw = b'secret-test-key provider raw response must never be logged'
        result = run_batch(self.lib)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(self.source.exists())
        self.assertIn('401', self.lib.record(self.id)['error'])
        self.assertNotIn('secret-test-key', json.dumps(self.lib.jobs()))

    def test_invalid_api_card_keeps_source(self):
        self.response_card = {'title': 'not a complete card'}
        result = run_batch(self.lib)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(self.source.exists())

    def test_archive_failure_does_not_fallback(self):
        self.agent('print(' + repr(json.dumps(self.card())) + ')')
        with patch.object(self.lib, 'commit', side_effect=OSError('disk unavailable')):
            result = run_batch(self.lib)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(self.calls, [])
        self.assertTrue(self.source.exists())

    def test_settings_persist_mask_and_clear_key(self):
        path = self.lib.safe('.paperlib/providers.json')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        save_settings(self.lib, {'api_key': '', 'mode': 'api'})
        self.assertEqual(load_settings(Library(self.root))['api_key'], 'secret-test-key')
        public = public_settings(configuration(self.lib))
        self.assertTrue(public['api_key_set'])
        self.assertNotIn('secret-test-key', json.dumps(public))
        self.assertNotIn('command', public)
        save_settings(self.lib, {'clear_api_key': True})
        self.assertFalse(public_settings(configuration(self.lib))['api_key_set'])

    def test_settings_validation_atomic(self):
        before = self.lib.safe('.paperlib/providers.json').read_bytes()
        for payload in ({'api_timeout': 0}, {'agent_timeout': True}, {'mode': 'parallel'},
                        {'api_base_url': 'file:///etc/passwd'}, {'api_base_url': 'https://key@host/v1'},
                        {'api_base_url': 'https://host/v1?key=secret'}, {'command': ['bad']},
                        {'api_key': 'abc\nInjected: bad'}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                save_settings(self.lib, payload)
            self.assertEqual(self.lib.safe('.paperlib/providers.json').read_bytes(), before)

    def test_api_timeout_and_redirect_are_bounded(self):
        prompt = {'task': 'Return JSON'}
        self.http_status = 302
        with self.assertRaisesRegex(RuntimeError, '302'):
            api_card(configuration(self.lib), prompt)
        self.assertEqual(len(self.calls), 1)
        self.http_status = 200
        self.delay = 1.3
        save_settings(self.lib, {'api_timeout': 1})
        with self.assertRaisesRegex(RuntimeError, '超时'):
            api_card(configuration(self.lib), prompt)

    def test_api_response_format_and_truncation_errors(self):
        prompt = {'task': 'Return JSON'}
        for raw in (b'not JSON', b'{}', b'{"choices":[]}', b'x' * 2_000_001):
            self.response_raw = raw
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                api_card(configuration(self.lib), prompt)
        self.response_raw = None
        self.finish_reason = 'length'
        with self.assertRaisesRegex(ValueError, '截断'):
            api_card(configuration(self.lib), prompt)

    def test_scheduler_can_use_api_without_agent(self):
        os.environ['PAPER_SCHEDULE_ENABLED'] = '1'
        self.assertTrue(configuration(self.lib)['enabled'])
        save_settings(self.lib, {'mode': 'agent'})
        self.assertFalse(configuration(self.lib)['enabled'])


if __name__ == '__main__':
    unittest.main()
