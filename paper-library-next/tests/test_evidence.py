import json
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import patch

from paperlib.evidence import source_context, resolve_evidence
from paperlib.providers import save_settings
from paperlib.worker import run_batch
import test_library as fixtures


class EvidenceTests(unittest.TestCase):
    card = fixtures.LibraryTests.card

    def setUp(self):
        self.env = patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith('PAPER_')}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        fixtures.LibraryTests.setUp(self)
        self.addCleanup(self.tmp.cleanup)
        save_settings(self.lib, {'mode': 'api', 'api_base_url': 'https://mock.invalid/v1',
                                 'api_model': 'mock', 'api_key': 'secret-not-for-logs'})

    def anchored_card(self):
        card = self.card()
        card['evidence'] = [{'field': e['field'], 'source_id': 'p1-b1'} for e in card['evidence']]
        return card

    def test_source_ids_resolve_to_exact_original_text(self):
        excerpt, sources, coverage = source_context(self.text)
        card = self.anchored_card()
        resolved = resolve_evidence(card, sources)
        self.assertIn('SOURCE p1-b1', excerpt)
        self.assertEqual(resolved['evidence'][0]['quote'], self.text.strip())
        self.assertEqual(resolved['evidence'][0]['page'], 1)
        self.lib.validate_card(self.id, resolved)
        self.assertNotIn('quote', card['evidence'][0])
        self.assertFalse(coverage['text_truncated'])

    def test_unknown_source_id_is_rejected(self):
        _, sources, _ = source_context(self.text)
        card = self.anchored_card()
        card['evidence'][0]['source_id'] = 'p999-b1'
        with self.assertRaisesRegex(ValueError, 'source_id'):
            resolve_evidence(card, sources)

    def test_long_context_keeps_conclusion_page_number_and_budget(self):
        pages = ['Introduction\n' + 'A long source sentence. ' * 900]
        pages.extend(['Method\n' + 'A different source sentence. ' * 900] * 18)
        pages.append('20 Conclusion\nThis is the actual conclusion, with limitations and future work. ' * 50)
        content = '\f'.join(pages) + '\f'
        excerpt, sources, coverage = source_context(content, limit=16000)
        self.assertLessEqual(len(excerpt), 16000)
        self.assertIn(1, coverage['included_pages'])
        self.assertIn(20, coverage['included_pages'])
        self.assertTrue(coverage['text_truncated'])
        self.assertTrue(coverage['omitted_pages'])
        self.assertTrue(coverage['partial_pages'])
        for entry in sources.values():
            self.assertIn(entry['quote'], pages[entry['page'] - 1])

    def test_invalid_evidence_repaired_once_then_committed_once(self):
        bad = self.anchored_card()
        bad['evidence'][0]['source_id'] = 'unknown'
        bad['debug'] = 'secret-not-for-logs'
        with patch('paperlib.worker.api_card', side_effect=[bad, self.anchored_card()]) as provider, \
                patch.object(self.lib, 'commit', wraps=self.lib.commit) as commit:
            result = run_batch(self.lib)
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(commit.call_count, 1)
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['repairs'], 1)
        repair = provider.call_args_list[1].args[1]['repair']
        self.assertIn('source_id', repair['validation_error'])
        self.assertEqual(repair['previous_card'], bad)
        trace = self.lib.safe(result['items'][0]['attempts'][0]['diagnostic_file'])
        self.assertEqual(stat.S_IMODE(trace.stat().st_mode), 0o600)
        self.assertNotIn('secret-not-for-logs', trace.read_text())
        self.assertEqual(json.loads(trace.read_text())['candidate']['debug'], '[REDACTED]')
        log = json.loads(self.lib.safe(result['log_file']).read_text())
        self.assertEqual(log['status'], 'completed')
        self.assertEqual(log['result']['completed'], 1)
        self.assertFalse(self.source.exists())

    def test_legacy_literal_quote_error_receives_specific_feedback(self):
        bad = self.card()
        bad['evidence'][3]['quote'] = 'A fabricated quote that never appears in this paper.'
        with patch('paperlib.worker.api_card', side_effect=[bad, self.anchored_card()]) as provider:
            result = run_batch(self.lib)
        self.assertEqual(result['completed'], 1)
        feedback = provider.call_args_list[1].args[1]['repair']['validation_error']
        self.assertIn('evidence[3]', feedback)
        self.assertIn('summary', feedback)

    def test_failed_repair_stops_and_preserves_pdf(self):
        bad = self.card()
        bad['evidence'][0]['quote'] = 'A fabricated quote that never appears in this paper.'
        with patch('paperlib.worker.api_card', return_value=bad) as provider:
            result = run_batch(self.lib)
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(self.source.exists())
        self.assertIsNone(self.lib.record(self.id)['card'])
        self.assertEqual(len(list(self.lib.safe('.paperlib/jobs/job-1').glob('*.json'))), 2)

    def test_network_error_not_retried(self):
        with patch('paperlib.worker.api_card', side_effect=RuntimeError('API HTTP 401')) as provider:
            result = run_batch(self.lib)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result['repairs'], 0)
        self.assertTrue(self.source.exists())

    def test_archive_error_not_retried(self):
        with patch('paperlib.worker.api_card', return_value=self.anchored_card()) as provider, \
                patch.object(self.lib, 'commit', side_effect=OSError('disk full')):
            result = run_batch(self.lib)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result['failed'], 1)

    def test_partial_read_forces_review_after_repair(self):
        excerpt, sources, coverage = source_context(self.text)
        coverage['text_truncated'] = True
        with patch('paperlib.worker.source_context', return_value=(excerpt, sources, coverage)), \
                patch('paperlib.worker.api_card', side_effect=[{}, self.anchored_card()]):
            result = run_batch(self.lib)
        self.assertEqual(result['completed'], 1)
        self.assertEqual(self.lib.record(self.id)['status'], 'review')
        self.assertIn('选读', self.lib.record(self.id)['card']['review_reason'])


if __name__ == '__main__':
    unittest.main()
