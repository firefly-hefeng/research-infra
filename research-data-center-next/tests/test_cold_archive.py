"""Cold storage tests use temporary ordinary files only; no real OSS access."""
import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('rdc_cold_archive_test', Path(__file__).resolve().parents[1] / 'tools/cold_archive.py')
cold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cold)


class ColdStorageGuardTests(unittest.TestCase):
    """Real observed mount shapes, mocked namespace lookup; no OSS access."""
    def setUp(self):
        self.local = Path('/var/lib/research-data-center/state')
        self.prefix = Path('/data/share_cold/research-data-center')
        self.parent = Path('/data/share_cold')
        self.local_mount = {'target': self.local.as_posix(),
                            'source': '/dev/nvme0n1p3[/var/lib/research-data-center/state]',
                            'fstype': 'ext4', 'fsroot': '/var/lib/research-data-center/state'}
        self.parent_mount = {'target': self.parent.as_posix(), 'source': 'ossfs',
                             'fstype': 'fuse.ossfs', 'fsroot': '/'}
        # Exact findmnt output from the sandbox probe on the authorized host.
        self.prefix_mount = {'target': self.prefix.as_posix(), 'source': 'ossfs[/research-data-center]',
                             'fstype': 'fuse.ossfs', 'fsroot': '/research-data-center'}
        self.prefix_device, self.parent_device = 52, 52

    def guard(self, prefix=None):
        def mounted(path):
            return {self.local: self.local_mount, self.prefix: self.prefix_mount,
                    self.parent: self.parent_mount}[Path(path)]
        def status(path):
            return SimpleNamespace(st_dev={self.prefix: self.prefix_device,
                                            self.parent: self.parent_device}[Path(path)])
        with mock.patch.object(cold, 'no_links'), mock.patch.object(cold, 'mount', side_effect=mounted), \
                mock.patch.object(cold.os, 'stat', side_effect=status):
            return cold.storage_guards(self.local, prefix or self.prefix)

    def test_exact_service_bind_is_accepted(self):
        result = self.guard()
        self.assertEqual(result['cold'], self.prefix_mount)
        self.assertEqual(result['local'], self.local_mount)

    def test_original_unsandboxed_mount_is_still_accepted(self):
        self.prefix_mount = dict(self.parent_mount)
        self.assertEqual(self.guard()['cold'], self.parent_mount)

    def test_wrong_bind_source_subtree_or_target_is_rejected(self):
        expected = dict(self.prefix_mount)
        for field, wrong in (('source', 'ossfs[/other-team]'), ('fsroot', '/other-team'),
                             ('target', '/data/share_cold/research-data-center/snapshots'),
                             ('fstype', 'ext4')):
            with self.subTest(field=field):
                self.prefix_mount = {**expected, field: wrong}
                with self.assertRaisesRegex(ValueError, 'Unexpected cold mount'):
                    self.guard()

    def test_missing_bind_fsroot_is_rejected(self):
        del self.prefix_mount['fsroot']
        with self.assertRaisesRegex(ValueError, 'Unexpected cold mount'):
            self.guard()

    def test_correct_bind_does_not_hide_detached_or_replaced_parent(self):
        expected = dict(self.parent_mount)
        for field, wrong in (('target', '/data'), ('source', '/dev/nvme1n1p1'),
                             ('fsroot', '/other-prefix'), ('fstype', 'nfs')):
            with self.subTest(field=field):
                self.parent_mount = {**expected, field: wrong}
                with self.assertRaisesRegex(ValueError, 'Unexpected cold mount'):
                    self.guard()

    def test_other_device_is_rejected_even_if_mount_fields_match(self):
        self.prefix_device += 1
        with self.assertRaisesRegex(ValueError, 'not on the parent filesystem'):
            self.guard()

    def test_other_application_prefix_remains_forbidden(self):
        with self.assertRaisesRegex(ValueError, 'dedicated application prefix'):
            self.guard(Path('/data/share_cold/other-team'))

    def test_remote_working_state_is_forbidden(self):
        self.local_mount = {'target': str(self.local), 'source': '10.0.0.202:/share',
                            'fstype': 'nfs', 'fsroot': '/state'}
        with self.assertRaisesRegex(ValueError, 'local block filesystem'):
            self.guard()

    def test_findmnt_requests_explicit_fsroot(self):
        response = SimpleNamespace(stdout=json.dumps({'filesystems': [self.prefix_mount]}))
        with mock.patch.object(cold.subprocess, 'run', return_value=response) as run:
            self.assertEqual(cold.mount(self.prefix), self.prefix_mount)
        self.assertIn('TARGET,SOURCE,FSTYPE,FSROOT', run.call_args.args[0])


@unittest.skipUnless(sys.platform.startswith('linux') and os.getuid() != 0,
                     'Requires ordinary Linux account, local flock and openat')
class ColdArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rdc-cold-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'application'
        self.state = self.root / 'state'
        self.cold = self.root / 'cold-prefix'
        for path in (self.app / 'var', self.app / 'tools', self.state, self.cold):
            path.mkdir(parents=True, mode=0o700)
        self.release = self.app / 'release.tar.gz'
        self.release.write_bytes(b'fixture immutable application bundle')
        for path in (self.app / 'var' / 'catalog.sqlite3', self.state / 'ingestion.sqlite3'):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('CREATE TABLE facts(value TEXT)')
                connection.execute("INSERT INTO facts VALUES ('committed')")
        self.mounted = True
        def guards(local, target):
            cold.no_links(local); cold.no_links(target)
            if not self.mounted:
                raise ValueError('Unexpected cold mount')
            self.assertEqual(Path(target), self.cold)
            return {'local': {'target': str(self.root), 'source': '/dev/test', 'fstype': 'ext4'},
                    'cold': {'target': str(self.cold), 'source': 'fixture', 'fstype': 'fixture'}}
        self.guards = guards

    def archive(self):
        with mock.patch.object(cold, 'storage_guards', side_effect=self.guards):
            with mock.patch.object(cold.subprocess, 'run') as package:
                result = cold.archive(self.app, self.state, self.cold)
                self.assertEqual(package.call_count, 1)
                return result

    def test_complete_archive_has_checked_objects_and_both_sqlite_copies(self):
        receipt = self.archive()
        prefix = Path(receipt['cold_path'])
        self.assertEqual({row['name'] for row in receipt['objects']},
                         {'release.tar.gz', 'catalog.sqlite3', 'ingestion.sqlite3'})
        for item in receipt['objects']:
            self.assertEqual(cold.sha(prefix / item['name']), item['sha256'])
        self.assertEqual(cold.sha(prefix / 'COMPLETE.json'), receipt['receipt_sha256'])
        self.assertFalse(receipt['live_state_on_oss'])
        self.assertEqual(json.loads((self.state / 'cold-backup-status.json').read_text())['snapshot_id'], receipt['snapshot_id'])

    def test_missing_live_database_never_creates_completion_receipt(self):
        (self.state / 'ingestion.sqlite3').unlink()
        with self.assertRaisesRegex(ValueError, 'Required live database'):
            self.archive()
        self.assertEqual(list(self.cold.rglob('COMPLETE.json')), [])
        self.assertFalse((self.state / 'cold-backup-status.json').exists())

    def test_symlinked_snapshot_parent_cannot_escape_prefix(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.cold / 'snapshots').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.archive()
        self.assertEqual(list(outside.iterdir()), [])

    def test_put_object_is_exclusive_and_rejects_symlink_parent(self):
        target = self.cold / 'existing'
        target.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            cold.put_object(self.release, target)
        self.assertEqual(target.read_bytes(), b'preserve')
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.cold / 'linked'
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            cold.put_object(self.release, link / 'object')
        self.assertEqual(list(outside.iterdir()), [])

    def test_sqlite_online_snapshot_excludes_uncommitted_wal_writer(self):
        source = self.state / 'ingestion.sqlite3'
        writer = sqlite3.connect(source)
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("INSERT INTO facts VALUES ('not committed')")
            target = self.state / 'online-snapshot.sqlite3'
            cold.sqlite_snapshot(source, target)
            with closing(sqlite3.connect(target)) as backup:
                self.assertEqual(backup.execute('SELECT value FROM facts').fetchall(), [('committed',)])
                self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            writer.rollback(); writer.close()

    def test_mount_disappearing_before_put_has_no_valid_completion(self):
        original = cold.put_object
        def detach_before_put(*args, **kwargs):
            self.mounted = False
            return original(*args, **kwargs)
        with mock.patch.object(cold, 'put_object', side_effect=detach_before_put):
            with self.assertRaisesRegex(ValueError, 'Unexpected cold mount'):
                self.archive()
        self.assertEqual(list(self.cold.rglob('COMPLETE.json')), [])
        self.assertEqual(list(self.cold.rglob('release.tar.gz')), [])
        self.assertFalse((self.state / 'cold-backup-status.json').exists())

    def test_mount_disappearing_after_object_readback_aborts_before_complete(self):
        original = cold.put_object
        calls = 0
        def detach_after_one(*args, **kwargs):
            nonlocal calls
            result = original(*args, **kwargs)
            calls += 1
            if calls == 1:
                self.mounted = False
            return result
        with mock.patch.object(cold, 'put_object', side_effect=detach_after_one):
            with self.assertRaisesRegex(ValueError, 'Unexpected cold mount'):
                self.archive()
        self.assertEqual(list(self.cold.rglob('COMPLETE.json')), [])
        self.assertFalse((self.state / 'cold-backup-status.json').exists())

    def test_actual_storage_guard_rejects_detached_or_wrong_mount(self):
        local = {'target': '/', 'source': '/dev/test', 'fstype': 'ext4', 'fsroot': '/'}
        wrong = {'target': '/data', 'source': '/dev/test', 'fstype': 'ext4', 'fsroot': '/'}
        expected = {'target': '/data/share_cold', 'source': 'ossfs', 'fstype': 'fuse.ossfs', 'fsroot': '/'}
        with mock.patch.object(cold, 'mount', side_effect=[local, wrong, expected]):
            with self.assertRaisesRegex(ValueError, 'Unexpected cold mount'):
                cold.storage_guards(self.state, Path('/data/share_cold/research-data-center'))
        with mock.patch.object(cold, 'mount') as mount:
            with self.assertRaisesRegex(ValueError, 'dedicated application prefix'):
                cold.storage_guards(self.state, Path('/data/share_cold/other-team'))
            mount.assert_not_called()

    def test_local_lock_rejects_concurrent_backup_and_source_symlink(self):
        lock = os.open(self.state / 'cold-backup.lock', os.O_RDWR | os.O_CREAT, 0o600)
        try:
            cold.fcntl.flock(lock, cold.fcntl.LOCK_EX | cold.fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.archive()
        finally:
            os.close(lock)
        source = self.state / 'ingestion.sqlite3'
        retained = self.state / 'retained.sqlite3'
        source.rename(retained)
        source.symlink_to(retained)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            cold.sqlite_snapshot(source, self.state / 'must-not-exist.sqlite3')
        self.assertFalse((self.state / 'must-not-exist.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
