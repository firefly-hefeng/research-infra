"""Read-only deployment gates and real Linux exchange in temporary fixtures.

Never calls activate/main, systemctl, mount inspection, or a production path.
Only migration_complete's mount observations are replaced with fixture facts.
"""
import copy
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock


def load_operator():
    path = Path(__file__).resolve().parents[1] / 'tools/activate_shared_management.py'
    spec = importlib.util.spec_from_file_location('shared_management_test_operator', path)
    module = importlib.util.module_from_spec(spec)
    # grp/pwd are imported by the operator but never used by these pure tests.
    replacements = {} if sys.platform.startswith('linux') else {
        name: types.ModuleType(name) for name in ('grp', 'pwd')}
    with mock.patch.dict(sys.modules, replacements):
        spec.loader.exec_module(module)
    return module


OP = load_operator()


class ReleaseExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rdc-shared-release-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def archive(self, entries=None, manifest=None, extra=None):
        entries = entries or {'server.py': b'print("fixture")\n', 'docs/guide.md': b'# Fixture\n'}
        if manifest is None:
            manifest = {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}
        archive = self.root / 'candidate.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            for name, data in [*entries.items(), ('release-manifest.json', json.dumps(manifest).encode())]:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                output.addfile(member, io.BytesIO(data))
            for member, data in extra or []:
                output.addfile(member, io.BytesIO(data) if data is not None else None)
        return archive, OP.sha(archive), manifest

    def test_exact_release_extracts_bytes_and_manifest(self):
        archive, digest, manifest = self.archive()
        destination = self.root / 'release'
        self.assertEqual(OP.extract_release(archive, destination, digest), manifest)
        self.assertEqual((destination / 'server.py').read_bytes(), b'print("fixture")\n')
        if sys.platform.startswith('linux'):
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((destination / 'server.py').stat().st_mode), 0o644)

    def test_bad_archive_hash_prevents_destination_creation(self):
        archive, _, _ = self.archive()
        destination = self.root / 'release'
        with self.assertRaisesRegex(RuntimeError, 'archive checksum'):
            OP.extract_release(archive, destination, '0' * 64)
        self.assertFalse(destination.exists())

    def test_existing_destination_is_never_overwritten(self):
        archive, digest, _ = self.archive()
        destination = self.root / 'release'
        destination.mkdir()
        (destination / 'canary').write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            OP.extract_release(archive, destination, digest)
        self.assertEqual((destination / 'canary').read_bytes(), b'keep')

    def test_member_digest_mismatch_fails(self):
        archive, digest, _ = self.archive({'server.py': b'actual'}, {'server.py': '0' * 64})
        with self.assertRaisesRegex(RuntimeError, 'member checksum'):
            OP.extract_release(archive, self.root / 'release', digest)

    def test_unlisted_member_fails_complete_coverage(self):
        archive, digest, _ = self.archive({'server.py': b'actual'}, {})
        with self.assertRaisesRegex(RuntimeError, 'coverage mismatch'):
            OP.extract_release(archive, self.root / 'release', digest)

    def test_unsafe_paths_and_private_var_rejected(self):
        for index, name in enumerate(('../outside.txt', '/outside.txt', 'var/access-token',
                                      'docs/../../outside.txt', 'C:/outside.txt', 'docs\\outside.txt')):
            with self.subTest(name=name):
                archive, digest, _ = self.archive({name: b'do not extract'})
                with self.assertRaisesRegex(RuntimeError, 'Unsafe archive member'):
                    OP.extract_release(archive, self.root / ('release-' + str(index)), digest)
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_symlink_hardlink_and_duplicate_members_rejected(self):
        for index, kind in enumerate((tarfile.SYMTYPE, tarfile.LNKTYPE)):
            member = tarfile.TarInfo('shortcut')
            member.type = kind
            member.linkname = '/outside-target'
            archive, digest, _ = self.archive(extra=[(member, None)])
            with self.assertRaisesRegex(RuntimeError, 'Unsafe archive member'):
                OP.extract_release(archive, self.root / ('release-' + str(index)), digest)
        member = tarfile.TarInfo('server.py')
        member.size = 1
        archive, digest, _ = self.archive(extra=[(member, b'x')])
        with self.assertRaisesRegex(RuntimeError, 'Duplicate'):
            OP.extract_release(archive, self.root / 'duplicate-release', digest)


@unittest.skipUnless(sys.platform.startswith('linux'), 'Real inode/symlink rehearsal requires Linux')
class MigrationGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rdc-shared-gate-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.aliases, rows = {}, {}
        for name in ('datasets', 'models'):
            destination = self.root / 'share' / name
            destination.mkdir(parents=True)
            legacy = self.root / name
            legacy.symlink_to(destination, target_is_directory=True)
            self.aliases[legacy] = destination
            info = destination.lstat()
            rows[name] = {'publication': 'published', 'switch': 'switched', 'cleanup': 'deleted',
                          'destination_inode': {key: getattr(info, 'st_' + key)
                                                for key in ('dev', 'ino', 'mode', 'uid', 'gid')}}
        self.final = {'migration_id': OP.MIGRATION, 'host': OP.HOST, 'phase': 'complete'}
        self.journal = {'migration_id': OP.MIGRATION, 'host': OP.HOST, 'phase': 'cleaned', 'roots': rows}
        patcher = mock.patch.object(OP, 'mount', return_value={
            'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'})
        self.mount = patcher.start()
        self.addCleanup(patcher.stop)

    def gate(self, final=None, journal=None):
        OP.migration_complete(final or self.final, journal or self.journal, self.aliases)

    def test_completed_bound_roots_pass_without_mutation(self):
        before = {str(path): OP.inode(path) for path in self.aliases.values()}
        self.gate()
        self.assertEqual(before, {str(path): OP.inode(path) for path in self.aliases.values()})

    def test_incomplete_or_foreign_receipts_rejected(self):
        for document, field, value in (('final', 'phase', 'waiting_for_verification'),
                                       ('final', 'host', 'other-host'),
                                       ('journal', 'phase', 'cleaning'),
                                       ('journal', 'migration_id', 'other-migration')):
            final, journal = copy.deepcopy(self.final), copy.deepcopy(self.journal)
            (final if document == 'final' else journal)[field] = value
            with self.subTest(document=document, field=field), self.assertRaises(RuntimeError):
                self.gate(final, journal)
        journal = copy.deepcopy(self.journal)
        journal['roots']['datasets']['cleanup'] = 'delete_started'
        with self.assertRaisesRegex(RuntimeError, 'per-root'):
            self.gate(journal=journal)

    def test_recorded_inode_and_metadata_drift_rejected(self):
        for field in ('dev', 'ino', 'mode', 'uid', 'gid'):
            journal = copy.deepcopy(self.journal)
            journal['roots']['datasets']['destination_inode'][field] += 1
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'identity changed'):
                self.gate(journal=journal)

    def test_replaced_destination_and_wrong_alias_rejected(self):
        legacy, target = next(iter(self.aliases.items()))
        target.rename(target.with_name(target.name + '-original'))
        target.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.gate()
        legacy.unlink()
        legacy.symlink_to(self.root / 'stranger')
        with self.assertRaisesRegex(RuntimeError, 'Compatibility alias'):
            self.gate()

    def test_mount_source_and_nested_mount_drift_rejected(self):
        self.mount.return_value = {'target': '/data/share', 'source': 'wrong:/share', 'fstype': 'nfs'}
        with self.assertRaisesRegex(RuntimeError, 'mount identity'):
            self.gate()
        expected = {'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'}
        self.mount.side_effect = lambda path: expected if path == Path('/data/share') else {
            'target': str(path), 'source': 'another:/mount', 'fstype': 'nfs'}
        with self.assertRaisesRegex(RuntimeError, 'Nested'):
            self.gate()


@unittest.skipUnless(sys.platform.startswith('linux'), 'Real renameat2 exchange requires Linux')
class ApplicationRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(ctypes.CDLL(None), 'renameat2'):
            raise unittest.SkipTest('libc.renameat2 unavailable')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rdc-application-exchange-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.app, self.backup, self.workspace = (self.root / name for name in ('application', 'backup', 'workspace'))
        self.app.mkdir()
        (self.app / 'canary').write_bytes(b'original application')
        self.workspace.mkdir()
        (self.workspace / 'canary').write_bytes(b'new workspace')
        self.original_inode = OP.inode(self.app)

    def restore(self):
        OP.restore_application(self.app, self.backup, self.workspace, self.original_inode)

    def assert_original(self):
        self.assertFalse(self.app.is_symlink())
        self.assertEqual(OP.inode(self.app), self.original_inode)
        self.assertEqual((self.app / 'canary').read_bytes(), b'original application')
        self.assertEqual((self.workspace / 'canary').read_bytes(), b'new workspace')

    def test_before_exchange_without_placeholder_is_unchanged(self):
        self.restore()
        self.assert_original()
        self.assertFalse(os.path.lexists(self.backup))

    def test_before_exchange_placeholder_removed_only_if_expected(self):
        self.backup.symlink_to(self.workspace, target_is_directory=True)
        self.restore()
        self.assert_original()
        self.assertFalse(os.path.lexists(self.backup))

    def test_after_real_exchange_restores_original_and_removes_placeholder(self):
        self.backup.symlink_to(self.workspace, target_is_directory=True)
        OP.exchange(self.app, self.backup)
        self.assertTrue(self.app.is_symlink())
        self.assertEqual(OP.inode(self.backup), self.original_inode)
        self.restore()
        self.assert_original()
        self.assertFalse(os.path.lexists(self.backup))
        self.restore()  # Already-restored topology is harmless.
        self.assert_original()

    def test_foreign_backup_cannot_replace_original(self):
        self.app.rename(self.root / 'preserved-original')
        self.app.symlink_to(self.workspace, target_is_directory=True)
        self.backup.mkdir()
        (self.backup / 'canary').write_bytes(b'stranger')
        with self.assertRaisesRegex(RuntimeError, 'rollback identity'):
            self.restore()
        self.assertTrue(self.app.is_symlink())
        self.assertEqual((self.backup / 'canary').read_bytes(), b'stranger')

    def test_foreign_application_never_overwritten(self):
        self.app.rename(self.backup)
        self.app.mkdir()
        (self.app / 'canary').write_bytes(b'stranger')
        with self.assertRaisesRegex(RuntimeError, 'identity unavailable'):
            self.restore()
        self.assertEqual((self.app / 'canary').read_bytes(), b'stranger')
        self.assertEqual(OP.inode(self.backup), self.original_inode)

    def test_foreign_placeholder_is_preserved_for_review(self):
        self.backup.symlink_to(self.root / 'unrelated-target')
        with self.assertRaisesRegex(RuntimeError, 'Unexpected rollback placeholder'):
            self.restore()
        self.assert_original()
        self.assertTrue(self.backup.is_symlink())


if __name__ == '__main__':
    unittest.main()
