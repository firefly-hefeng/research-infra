import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from paperlib.library import Library, digest
from paperlib.worker import Scheduler, reading_items, run_batch
import test_library as fixtures
from test_library import pdf_bytes


class ReadingRefreshTests(unittest.TestCase):
    card = fixtures.LibraryTests.card

    def setUp(self):
        self.environment = patch.dict(os.environ, {
            k: v for k, v in os.environ.items() if not k.startswith('PAPER_')}, clear=True)
        self.environment.start()
        fixtures.LibraryTests.setUp(self)
        self.lib.commit(self.id, self.card())
        self.lib.edit(self.id, {'notes': 'User notes stay intact', 'favorite': True})
        self.before = self.lib.record(self.id)
        self.before_card_file = self.lib.pdf_path(self.id).with_name('card.json').read_bytes()
        self.extra = self.root / 'inbox' / 'untouched.pdf'
        self.extra.write_bytes(pdf_bytes('Another unindexed paper remains in the inbox. It must not be scanned or classified during a reading refresh.'))
        os.utime(self.extra, (0, 0))
        self.extra_bytes = self.extra.read_bytes()
        os.environ['PAPER_AGENT_COMMAND'] = json.dumps(['mock-agent'])

    def tearDown(self):
        fixtures.LibraryTests.tearDown(self)
        self.environment.stop()

    def detailed_card(self):
        card = self.card()
        card['reading'] = {'method': 'The study uses data selection to improve model quality.'}
        card['evidence'].append({'field': 'reading.method', 'page': 1, 'quote': self.text.strip()})
        return card

    def assert_archive_unchanged(self):
        self.assertEqual(self.lib.record(self.id), self.before)
        self.assertEqual(self.lib.pdf_path(self.id).with_name('card.json').read_bytes(), self.before_card_file)
        self.assertEqual(self.extra.read_bytes(), self.extra_bytes)
        self.assertEqual(len(self.lib.papers()), 1)

    def test_refresh_only_requested_archive_preserves_notes_and_directory(self):
        with patch('paperlib.worker.agent_card', return_value=self.detailed_card()) as provider, \
                patch.object(self.lib, 'scan', side_effect=AssertionError('Inbox scan forbidden')):
            result = run_batch(self.lib, paper_ids=[self.id])
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['task'], 'reading')
        self.assertEqual(result['paper_ids'], [self.id])
        self.assertEqual(result['scan'], {})
        updated = self.lib.record(self.id)
        self.assertEqual(updated['pdf'], self.before['pdf'])
        self.assertEqual(updated['notes'], self.before['notes'])
        self.assertEqual(updated['favorite'], self.before['favorite'])
        self.assertEqual(updated['card']['reading']['method'], self.detailed_card()['reading']['method'])
        self.assertEqual(len(self.lib.papers()), 1)
        self.assertEqual(self.extra.read_bytes(), self.extra_bytes)
        prompt = provider.call_args.args[1]
        self.assertEqual(prompt['operation'], 'reading')
        self.assertEqual(prompt['existing_card'], self.before['card'])
        self.assertEqual(json.loads(self.lib.safe(result['log_file']).read_text())['result']['paper_ids'], [self.id])

    def test_provider_failure_preserves_card_status_and_metadata(self):
        with patch('paperlib.worker.agent_card', side_effect=RuntimeError('Mock provider unavailable')), \
                patch.object(self.lib, 'error', side_effect=AssertionError('Do not replace archive status')):
            result = run_batch(self.lib, paper_ids=[self.id])
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['items'][0]['preserved_existing'])
        self.assert_archive_unchanged()

    def test_empty_reading_gets_one_repair_and_does_not_replace_card(self):
        with patch('paperlib.worker.agent_card', return_value=self.card()) as provider:
            result = run_batch(self.lib, paper_ids=[self.id])
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(result['repairs'], 1)
        self.assertEqual(result['completed'], 0)
        self.assertIn('reading', result['errors'][0]['message'])
        self.assert_archive_unchanged()

    def test_takeaway_alone_is_not_a_detailed_reading(self):
        candidate = self.card()
        candidate['reading'] = {'takeaway': 'The study uses data selection.'}
        candidate['evidence'].append({'field': 'reading.takeaway', 'page': 1, 'quote': self.text.strip()})
        with patch('paperlib.worker.agent_card', return_value=candidate) as provider:
            result = run_batch(self.lib, paper_ids=[self.id])
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(result['repairs'], 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('reading 正文', provider.call_args.args[1]['repair']['validation_error'])
        self.assert_archive_unchanged()

    def test_partial_refresh_cannot_erase_existing_sections_or_table(self):
        previous = self.detailed_card()
        previous['reading'].update(background='The paper studies data selection.',
                                   results='A verified experiment assesses model quality.',
                                   result_table={'caption': 'Experiment summary', 'columns': ['Method', 'Goal'],
                                                 'rows': [['Data selection', 'Model quality']]})
        for field in ('background', 'results', 'result_table'):
            previous['evidence'].append({'field': 'reading.' + field, 'page': 1, 'quote': self.text.strip()})
        self.lib.commit(self.id, previous)
        self.before = self.lib.record(self.id)
        self.before_card_file = self.lib.pdf_path(self.id).with_name('card.json').read_bytes()
        for empty_table in (False, True):
            candidate = self.detailed_card() if not empty_table else json.loads(json.dumps(previous))
            if empty_table:
                candidate['reading']['result_table']['rows'] = []
            with self.subTest(empty_table=empty_table), \
                    patch('paperlib.worker.agent_card', return_value=candidate) as provider, \
                    patch.object(self.lib, 'commit', wraps=self.lib.commit) as commit:
                result = run_batch(self.lib, paper_ids=[self.id])
                self.assertEqual(provider.call_count, 2)
                self.assertEqual(result['repairs'], 1)
                self.assertEqual(result['status'], 'failed')
                commit.assert_not_called()
                error = provider.call_args.args[1]['repair']['validation_error']
                self.assertIn('reading.result_table', error)
                if not empty_table:
                    self.assertIn('reading.background', error)
                    self.assertIn('reading.results', error)
                self.assert_archive_unchanged()

    def test_missing_existing_section_can_be_repaired_with_fresh_evidence(self):
        previous = self.detailed_card()
        previous['reading']['results'] = 'A verified experiment assesses model quality.'
        previous['evidence'].append({'field': 'reading.results', 'page': 1, 'quote': self.text.strip()})
        self.lib.commit(self.id, previous)
        with patch('paperlib.worker.agent_card', side_effect=[self.detailed_card(), previous]) as provider:
            result = run_batch(self.lib, paper_ids=[self.id])
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['repairs'], 1)
        self.assertIn('reading.results', provider.call_args.args[1]['repair']['validation_error'])
        self.assertEqual(self.lib.record(self.id)['card']['reading']['results'], previous['reading']['results'])

    def test_reading_without_evidence_can_be_repaired(self):
        bad = self.detailed_card()
        bad['evidence'] = self.card()['evidence']
        with patch('paperlib.worker.agent_card', side_effect=[bad, self.detailed_card()]):
            result = run_batch(self.lib, paper_ids=[self.id])
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['repairs'], 1)

    def test_invalid_selection_is_rejected_before_creating_job(self):
        for selection in ([], self.id, [self.id, self.id], [False], ['0' * 64], ['../outside']):
            with self.subTest(selection=selection), self.assertRaises((ValueError, KeyError)):
                run_batch(self.lib, paper_ids=selection)
        self.assertEqual(self.lib.jobs(), [])
        self.assert_archive_unchanged()

    def test_pending_and_missing_archives_are_not_refreshable(self):
        self.lib.scan(settle_seconds=0)
        with self.assertRaisesRegex(ValueError, '已归档'):
            reading_items(self.lib, [digest(self.extra)])
        self.lib.pdf_path(self.id).unlink()
        with self.assertRaises(FileNotFoundError):
            reading_items(self.lib, [self.id])

    def test_refresh_shares_exclusive_agent_lock(self):
        with self.lib.lock('agent', blocking=False), self.assertRaises(BlockingIOError):
            run_batch(self.lib, paper_ids=[self.id])
        self.assertEqual(self.lib.jobs(), [])

    def test_scheduler_forwards_scope_and_prevents_concurrent_run(self):
        scheduler = Scheduler(self.lib)
        entered, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(3)
        with patch('paperlib.worker.run_batch', side_effect=blocked) as batch:
            try:
                scheduler.trigger(paper_ids=[self.id])
                self.assertTrue(entered.wait(2))
                with self.assertRaisesRegex(ValueError, '正在运行'):
                    scheduler.trigger()
                self.assertEqual(batch.call_args.kwargs['paper_ids'], [self.id])
            finally:
                release.set()
                for _ in range(100):
                    if not scheduler.active.locked():
                        break
                    time.sleep(.01)
        self.assertFalse(scheduler.active.locked())


class ReadingRefreshHTTPTests(unittest.TestCase):
    card = fixtures.LibraryTests.card

    def test_http_refresh_is_explicit_scoped_and_protected(self):
        fixtures.LibraryTests.setUp(self)
        process = None
        try:
            self.lib.commit(self.id, self.card())
            original_pdf = self.lib.record(self.id)['pdf']
            pending = self.root / 'inbox' / 'pending.pdf'
            pending.write_bytes(pdf_bytes('This separate pending paper must remain outside the reading refresh. There is enough text to classify if mistakenly invoked.'))
            self.lib.scan(settle_seconds=0)
            pending_id = digest(pending)
            card = self.card()
            card['reading'] = {'method': 'The study uses data selection to improve model quality.'}
            card['evidence'].append({'field': 'reading.method', 'page': 1, 'quote': self.text.strip()})
            agent = Path(self.tmp.name) / 'mock-agent.py'
            agent.write_text('import json, sys\nrequest = json.load(sys.stdin)\n'
                             'assert request["operation"] == "reading"\n'
                             'print(' + repr(json.dumps(card)) + ')\n')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            env = {k: v for k, v in os.environ.items() if not k.startswith('PAPER_')}
            env.update(PAPER_AGENT_COMMAND=json.dumps([sys.executable, str(agent)]), PAPER_SCHEDULE_ENABLED='0')
            with tempfile.TemporaryFile() as log:
                process = subprocess.Popen([sys.executable, 'manage.py', '--root', str(self.root),
                                            'serve', '--port', str(port)], env=env, stdout=log, stderr=log)
                for _ in range(100):
                    try:
                        with urlopen(url) as response:
                            if response.status == 200:
                                break
                    except URLError:
                        time.sleep(.05)
                else:
                    log.seek(0)
                    self.fail(log.read().decode())
                def post(ident, headers=None):
                    request = Request(url + '/api/papers/' + ident + '/reading', data=b'{}',
                                      headers={'Content-Type': 'application/json', 'X-Paper-Library': '1', **(headers or {})})
                    try:
                        with urlopen(request) as response:
                            return response.status, json.load(response)
                    except HTTPError as error:
                        return error.code, json.load(error)
                self.assertEqual(post(self.id, {'Origin': 'https://untrusted.example'})[0], 403)
                self.assertEqual(post(self.id, {'X-Paper-Library': ''})[0], 403)
                self.assertEqual(post(pending_id)[0], 400)
                self.assertEqual(post('0' * 64)[0], 400)
                code, body = post(self.id)
                self.assertEqual(code, 202)
                self.assertEqual(body, {'started': True, 'task': 'reading', 'paper_id': self.id})
                for _ in range(100):
                    jobs = self.lib.jobs()
                    if jobs and jobs[0]['status'] != 'running':
                        break
                    time.sleep(.05)
                self.assertEqual(jobs[0]['status'], 'completed')
                self.assertEqual(jobs[0]['result']['paper_ids'], [self.id])
                self.assertEqual(self.lib.record(self.id)['pdf'], original_pdf)
                self.assertIn('method', self.lib.record(self.id)['card']['reading'])
                self.assertEqual(self.lib.record(pending_id)['status'], 'pending')
                self.assertTrue(pending.exists())
        finally:
            if process:
                process.terminate()
                process.wait(timeout=10)
            fixtures.LibraryTests.tearDown(self)


if __name__ == '__main__':
    unittest.main()
