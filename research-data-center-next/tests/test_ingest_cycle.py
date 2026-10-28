"""Bounded automatic work; no approval, deletion, or unbounded retry loop."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

import ingestion as ing
from tests.test_ingestion import IngestionTests

spec = importlib.util.spec_from_file_location('rdc_ingest_cycle_test', Path(__file__).resolve().parents[1] / 'tools/ingest_cycle.py')
cycle_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle_module)


@unittest.skipUnless(sys.platform.startswith('linux') and os.getuid() != 0,
                     'Needs ordinary Linux account and flock')
class CycleTests(unittest.TestCase):
    setUp = IngestionTests.setUp
    submission = IngestionTests.submission
    coordinator = IngestionTests.coordinator
    approve = IngestionTests.approve

    def test_cycle_verifies_only_four_and_never_approves(self):
        for number in range(6):
            self.submission('job-' + str(number))
        with self.coordinator() as worker:
            with mock.patch.object(worker, 'approve', side_effect=AssertionError('must never approve')):
                result = cycle_module.cycle(worker)
            self.assertEqual(len(result['registered']), 6)
            self.assertEqual(len(result['verified']), 4)
            self.assertEqual(result['published'], [])
            self.assertEqual(ing.snapshot(self.db)['counts']['review_required'], 4)
            self.assertEqual(ing.snapshot(self.db)['counts']['submitted'], 2)

    def test_cycle_does_not_rehash_review_or_failed_jobs(self):
        directory = self.submission()
        with self.coordinator() as worker:
            cycle_module.cycle(worker)
            with mock.patch.object(worker, 'verify', side_effect=AssertionError('must not revisit review')):
                self.assertEqual(cycle_module.cycle(worker)['verified'], [])
            worker.change(self.username + '/' + directory.name, 'failed', 'test_failure')
            with mock.patch.object(worker, 'verify', side_effect=AssertionError('must not retry failed')):
                self.assertEqual(cycle_module.cycle(worker)['verified'], [])

    def test_cycle_disabled_performs_no_scan_or_heartbeat(self):
        with self.coordinator() as worker:
            worker.set_meta('worker_enabled', False); worker.connection.commit()
            with mock.patch.object(worker, 'scan', side_effect=AssertionError('disabled')):
                with mock.patch.object(worker, 'heartbeat', side_effect=AssertionError('disabled')):
                    self.assertEqual(cycle_module.cycle(worker)['mode'], 'disabled')

    def test_cycle_publishes_at_most_one_existing_authorization(self):
        one, two = self.submission('one'), self.submission('two')
        with self.coordinator() as worker:
            first = self.approve(worker, one, resource='first')
            second = self.approve(worker, two, resource='second')
            with mock.patch.object(worker, 'approve', side_effect=AssertionError('must never approve')):
                result = cycle_module.cycle(worker)
            self.assertEqual(len(result['published']), 1)
            self.assertEqual(ing.snapshot(self.db)['counts']['published'], 1)
            self.assertEqual(ing.snapshot(self.db)['counts']['ready'], 1)

    def test_cycle_stops_retrying_terminal_publication_mismatch(self):
        directory = self.submission()
        with self.coordinator() as worker:
            job = self.approve(worker, directory)
            worker.change(job['id'], 'publishing')
            with mock.patch.object(worker, 'publish', side_effect=ing.IngestionError('published_payload_changed')):
                result = cycle_module.cycle(worker)
            self.assertEqual(result['errors'][0]['status'], 'review_required')
            self.assertIsNone(worker.job(job['id'])['approval'])
            with mock.patch.object(worker, 'publish', side_effect=AssertionError('must not hash again')):
                self.assertEqual(cycle_module.cycle(worker)['published'], [])

    def test_cycle_reconciles_after_transient_io_failure_but_never_copies_over(self):
        directory = self.submission()
        with self.coordinator() as worker:
            job = self.approve(worker, directory)
            with mock.patch.object(worker, 'finalize', side_effect=OSError('fixture interrupted local state write')):
                result = cycle_module.cycle(worker)
            self.assertEqual(result['errors'][0]['status'], 'publishing')
            with mock.patch.object(worker, 'copy_payload', side_effect=AssertionError('must not copy twice')):
                next_result = cycle_module.cycle(worker)
            self.assertEqual(next_result['published'][0]['status'], 'published')

    def test_cycle_known_verify_exception_fails_job_and_processes_remaining(self):
        self.submission('one'); self.submission('two')
        with self.coordinator() as worker:
            real_verify = worker.verify
            def fail_one(job_id):
                if job_id.endswith('/one'):
                    raise OSError('fixture unreadable source')
                return real_verify(job_id)
            with mock.patch.object(worker, 'verify', side_effect=fail_one):
                result = cycle_module.cycle(worker)
            self.assertEqual(len(result['errors']), 1)
            self.assertEqual(len(result['verified']), 1)
            self.assertEqual(worker.job(self.username + '/one')['status'], 'failed')

    def test_cycle_negative_or_unbounded_limits_are_refused(self):
        with self.coordinator() as worker:
            for count in (-1, 0, 5, True):
                with self.assertRaisesRegex(ing.IngestionError, 'bounded_policy'):
                    cycle_module.cycle(worker, verify_limit=count)
            with self.assertRaisesRegex(ing.IngestionError, 'bounded_policy'):
                cycle_module.cycle(worker, publish_limit=2)


# Do not rediscover the imported core test case in this module.
del IngestionTests

if __name__ == '__main__':
    unittest.main()
