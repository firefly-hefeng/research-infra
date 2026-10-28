"""Destination-observer tests inspect temporary fixtures only, never /data."""
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux'), 'Anchored dirfd/O_PATH observer requires Linux')
class DestinationObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(PROJECT / 'tools'))
        cls.observer = importlib.import_module('cpfs_observe_destination')

    def patch(self, target, name, **kwargs):
        patcher = mock.patch.object(target, name, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rdc-observer-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = self.root / 'private-evidence'
        self.share = self.root / 'share'
        self.base.mkdir()
        self.share.mkdir()
        self.libraries = {}
        for name in ('datasets', 'models'):
            old = self.root / name
            new = self.share / name
            new.mkdir()
            old.symlink_to(new, target_is_directory=True)
            self.libraries[name] = (str(old), str(new))
        self.dataset = self.share / 'datasets' / 'corpus'
        self.dataset.mkdir()
        (self.dataset / 'one-name-that-must-not-be-exported').write_text('fixture data', encoding='utf-8')
        self.weights = self.share / 'models' / 'weights.bin'
        self.weights.write_bytes(b'Never read these fixture contents')
        self.assets = [{'id': 'dataset-a', 'path': str(self.root / 'datasets' / 'corpus')},
                       {'id': 'model-a', 'path': str(self.root / 'models' / 'weights.bin')}]
        self.document = {'schema_version': '1.0', 'assets': self.assets}
        raw = json.dumps(self.document).encode()
        (self.base / 'catalog-baseline.json').write_bytes(raw)
        self.journal = {'migration_id': 'cpfs-20261027', 'host': socket.gethostname(), 'phase': 'switched',
                        'switched_at': '2026-01-01T00:00:00+00:00', 'roots': {}}
        for name, (_, target) in self.libraries.items():
            info = os.lstat(target)
            self.journal['roots'][name] = {'publication': 'published', 'switch': 'switched',
                                           'destination_inode': {key: getattr(info, 'st_' + key)
                                                                 for key in ('dev', 'ino', 'mode', 'uid', 'gid')}}
        self.save_journal()
        self.patch(self.observer, 'BASE', new=self.base)
        self.patch(self.observer, 'SHARE', new=self.share)
        self.patch(self.observer, 'LIBRARIES', new=self.libraries)
        self.patch(self.observer, 'BASELINE_SHA256', new=hashlib.sha256(raw).hexdigest())
        self.patch(self.observer, 'EXPECTED_RECORDS', new=2)
        self.patch(self.observer, 'EXPECTED_PATHS', new=2)
        self.account = {'account': 'rmp', 'observer_uid': 1011, 'observer_gid': os.getgid(), 'observer_groups': os.getgroups()}
        self.real_account_guard = self.observer.ordinary_account
        self.patch(self.observer, 'ordinary_account', return_value=dict(self.account))
        self.mount = {'target': str(self.share), 'source': '10.0.0.202:/share', 'fstype': 'nfs'}
        self.patch(self.observer, 'mount_info', return_value=dict(self.mount))

    def save_journal(self):
        (self.base / 'cutover-state.json').write_text(json.dumps(self.journal), encoding='utf-8')

    def update_assets(self, assets):
        raw = json.dumps({'schema_version': '1.0', 'assets': assets}).encode()
        (self.base / 'catalog-baseline.json').write_bytes(raw)
        self.observer.BASELINE_SHA256 = hashlib.sha256(raw).hexdigest()
        self.observer.EXPECTED_RECORDS = len(assets)
        self.observer.EXPECTED_PATHS = len({row['path'] for row in assets})

    def test_reads_no_file_bytes_and_exports_no_child_names(self):
        with mock.patch.object(self.observer.os, 'read', side_effect=AssertionError('No data read allowed')):
            report = self.observer.observe()
        self.assertTrue(report['complete'])
        self.assertEqual(len(report['observations']), 2)
        self.assertTrue(all(row['exists'] and row['readable'] for row in report['observations']))
        self.assertEqual({row['kind'] for row in report['observations']}, {'directory', 'file'})
        self.assertEqual(report['cutover_state_sha256'], hashlib.sha256((self.base / 'cutover-state.json').read_bytes()).hexdigest())
        self.assertEqual(len(report['root_checks']), 2)
        self.assertTrue(all(row['verified'] for row in report['root_checks']))
        self.assertGreater(report['disk_snapshot']['total_bytes'], 0)
        encoded = json.dumps(report)
        self.assertNotIn('one-name-that-must-not-be-exported', encoded)
        self.assertNotIn('Never read these fixture contents', encoded)

    def test_root_and_mismatched_effective_uid_are_rejected_before_observation(self):
        for uid, euid in ((0, 0), (1011, 0), (0, 1011), (1012, 1012)):
            with self.subTest(uid=uid, euid=euid):
                with mock.patch.object(self.observer.os, 'getuid', return_value=uid), mock.patch.object(self.observer.os, 'geteuid', return_value=euid):
                    with self.assertRaisesRegex(RuntimeError, 'ordinary_rmp'):
                        self.real_account_guard()
        with mock.patch.object(self.observer.os, 'getuid', return_value=1011), mock.patch.object(self.observer.os, 'geteuid', return_value=1011):
            with mock.patch.object(self.observer.pwd, 'getpwuid', return_value=type('User', (), {'pw_name': 'someone_else'})()):
                with self.assertRaisesRegex(RuntimeError, 'resolve_to_rmp'):
                    self.real_account_guard()

    def test_wrong_baseline_partial_cutover_and_host_are_refused(self):
        with mock.patch.object(self.observer, 'BASELINE_SHA256', '0' * 64):
            with self.assertRaisesRegex(RuntimeError, 'baseline_hash'):
                self.observer.observe()
        for phase in ('prepared', 'copying', 'cleaning'):
            self.journal['phase'] = phase
            self.save_journal()
            with self.assertRaisesRegex(RuntimeError, 'not_fully_switched'):
                self.observer.observe()
        self.journal['phase'] = 'switched'
        self.journal['host'] = 'different-client'
        self.save_journal()
        with self.assertRaisesRegex(RuntimeError, 'host_mismatch'):
            self.observer.observe()

    def test_completed_cleanup_can_refresh_current_journal_binding(self):
        self.journal['phase'] = 'cleaned'
        for row in self.journal['roots'].values():
            row['cleanup'] = 'deleted'
        self.save_journal()
        report = self.observer.observe()
        self.assertTrue(report['complete'])
        self.assertEqual(report['cutover_phase'], 'cleaned')

    def test_scope_rejects_traversal_prefix_and_non_library_paths(self):
        roots = [pair[1] for pair in self.libraries.values()]
        for path in (str(self.share), str(self.share / 'public' / 'other'),
                     str(self.share / 'datasets-other' / 'entry'),
                     str(self.share / 'datasets' / '..' / 'models' / 'entry'),
                     str(self.share / 'datasets' / 'name') + '\\escape'):
            self.assertIsNone(self.observer.approved_path(path, roots))
        invalid = [{'id': 'outside', 'path': str(self.root / 'not-a-library')}]
        self.update_assets(invalid)
        with self.assertRaisesRegex(RuntimeError, 'outside_public_roots'):
            self.observer.observe()

    def test_internal_and_legacy_absolute_symlinks_are_recorded_separately(self):
        link = self.share / 'datasets' / 'linked-corpus'
        link.symlink_to(self.root / 'datasets' / 'corpus', target_is_directory=True)
        self.update_assets(self.assets + [{'id': 'linked', 'path': str(self.root / 'datasets' / 'linked-corpus')}])
        report = self.observer.observe()
        row = next(row for row in report['observations'] if row['path'] == str(link))
        self.assertTrue(report['complete'])
        self.assertEqual(row['kind'], 'directory')
        self.assertEqual(row['entry_kind'], 'symlink')
        self.assertEqual(row['realpath'], str(self.dataset))
        self.assertEqual(row['symlink'], {'is_symlink': True, 'target_scope': 'public_library'})

    def test_external_link_is_never_followed_or_exposed(self):
        outside = self.root / 'private-target-that-must-not-be-recorded'
        outside.mkdir()
        (outside / 'secret').write_bytes(b'private fixture')
        link = self.share / 'datasets' / 'outside-link'
        link.symlink_to(outside, target_is_directory=True)
        self.update_assets(self.assets + [{'id': 'outside-link', 'path': str(self.root / 'datasets' / 'outside-link')}])
        report = self.observer.observe()
        self.assertFalse(report['complete'])
        row = next(row for row in report['observations'] if row['path'] == str(link))
        self.assertFalse(row['readable'])
        self.assertIsNone(row['realpath'])
        self.assertEqual(row['reason'], 'symlink_target_outside_library')
        self.assertNotIn(str(outside), json.dumps(report))

    def test_dangling_link_and_special_file_fail_without_blocking(self):
        link = self.share / 'datasets' / 'dangling'
        link.symlink_to('nonexistent-public-entry')
        fifo = self.share / 'datasets' / 'pipe'
        os.mkfifo(fifo)
        self.update_assets(self.assets + [
            {'id': 'dangling', 'path': str(self.root / 'datasets' / 'dangling')},
            {'id': 'pipe', 'path': str(self.root / 'datasets' / 'pipe')}])
        report = self.observer.observe()
        self.assertFalse(report['complete'])
        rows = {row['path']: row for row in report['observations']}
        self.assertFalse(rows[str(link)]['exists'])
        self.assertEqual(rows[str(fifo)]['reason'], 'special_entry_not_opened')

    def test_changed_journal_or_root_identity_invalidates_result(self):
        real_observe = self.observer.observe_path
        changed = False
        def observe_then_change(*args):
            nonlocal changed
            row = real_observe(*args)
            if not changed:
                self.journal['changed_while_observing'] = True
                self.save_journal()
                changed = True
            return row
        with mock.patch.object(self.observer, 'observe_path', side_effect=observe_then_change):
            report = self.observer.observe()
        self.assertFalse(report['complete'])
        self.assertTrue(any('journal_changed' in row['reason'] for row in report['errors']))

    def test_missing_mount_or_alias_refuses_observation(self):
        with mock.patch.object(self.observer, 'mount_info', side_effect=RuntimeError('unexpected_shared_library_mount')):
            with self.assertRaisesRegex(RuntimeError, 'mount'):
                self.observer.observe()
        old = Path(self.libraries['datasets'][0])
        old.unlink()
        old.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'alias_mismatch'):
            self.observer.observe()

    def test_failed_rerun_replaces_stale_success_receipt_with_failure(self):
        target = self.base / self.observer.OUTPUT_NAME
        target.write_text('{"complete":true}', encoding='utf-8')
        with mock.patch.object(self.observer, 'observe', side_effect=RuntimeError('fixture_guard_failed')):
            with mock.patch.object(sys, 'argv', ['cpfs_observe_destination.py']), redirect_stdout(io.StringIO()):
                code = self.observer.main()
        self.assertEqual(code, 2)
        report = json.loads(target.read_text())
        self.assertFalse(report['complete'])
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(list(self.base.glob('.destination-observer-*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
