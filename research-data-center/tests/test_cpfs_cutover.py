"""Linux fault-injection rehearsal confined to TemporaryDirectory.

Real renameat2, directory publication, fsync and metadata revalidation run on a
temporary filesystem. Fixed production paths, mount/ownership guards and process
inspection are replaced before any operation. No /data tree, rsync, server or
production process is touched, and no operator main() function is invoked.
"""
import copy
import ctypes
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux'), 'Real renameat2 rehearsal requires Linux')
class CutoverRehearsalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(ctypes.CDLL(None), 'renameat2'):
            raise unittest.SkipTest('libc.renameat2 unavailable')
        sys.path.insert(0, str(PROJECT / 'tools'))
        cls.cutover = importlib.import_module('cpfs_cutover')
        cls.revalidate = importlib.import_module('cpfs_revalidate')

    def patch(self, target, attribute, **kwargs):
        patcher = mock.patch.object(target, attribute, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rdc-cutover-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / 'data'
        self.share = self.data / 'share'
        self.base = self.root / 'evidence'
        self.stage = self.share / '.staging'
        self.rollback = self.data / '.rollback'
        for path in (self.data, self.share, self.base, self.stage):
            path.mkdir(parents=True, exist_ok=True)
        for name in ('models', 'datasets'):
            source = self.data / name
            source.mkdir()
            (source / 'payload.bin').write_bytes(b'model-v1' if name == 'models' else b'data-v01')
            (source / 'nested').mkdir()
            (source / 'nested' / 'metadata.json').write_text('{"fixture":true}', encoding='utf-8')
            (source / 'payload-link').symlink_to('payload.bin')
            shutil.copytree(source, self.stage / name, symlinks=True)
        self.root_ids = {name: (os.lstat(self.data / name).st_dev, os.lstat(self.data / name).st_ino)
                         for name in ('models', 'datasets')}
        self.root_metadata = {name: {key: getattr(os.lstat(self.data / name), 'st_' + key)
                                    for key in ('mode', 'uid', 'gid')} for name in ('models', 'datasets')}
        # A server TMPDIR can inherit POSIX ACL names. Keep the fixture's real
        # baseline without weakening the production expectation of no xattrs.
        self.root_xattrs = {name: tuple(sorted(os.listxattr(self.data / name, follow_symlinks=False)))
                            for name in ('models', 'datasets')}
        self.snapshot_sources()
        self.journal = {'migration_id': 'cpfs-20261027', 'host': os.uname().nodename,
                        'phase': 'prepared', 'roots': {'models': {}, 'datasets': {}}}

        # All fixed production Path('/data/...') calls are translated to this
        # fresh temporary root. /proc/self/mountinfo is read-only fixture context.
        def mapped_path(value='.', *parts):
            text = os.fspath(value)
            # Server TMPDIR may itself live under /data. Already translated
            # fixture paths must never be mapped a second time.
            if Path(value).is_absolute() and Path(value).is_relative_to(self.root):
                return Path(value, *parts)
            if text == '/data' or text.startswith('/data/'):
                return self.data.joinpath(*Path(text).parts[2:], *parts)
            return Path(value, *parts)
        self.mapped_path = mapped_path
        self.patch(self.cutover, 'Path', new=mapped_path)
        self.patch(self.revalidate, 'Path', new=mapped_path)
        for module in (self.cutover, self.revalidate):
            self.patch(module, 'BASE', new=self.base)
            self.patch(module, 'ROLLBACK', new=self.rollback)
            self.patch(module, 'ROOT_IDS', new=self.root_ids)
        self.patch(self.revalidate, 'ROOT_METADATA', new=self.root_metadata)
        self.patch(self.revalidate, 'ROOT_XATTRS', new=self.root_xattrs)
        self.patch(self.cutover, 'STAGE', new=self.stage)
        self.patch(self.cutover, 'JOURNAL', new=self.base / 'cutover-state.json')
        real_identity = self.cutover.identity

        def identity_for_guard(path):
            info = real_identity(path)
            # Production requires root and the fixed XFS device. The rehearsal
            # keeps real inode identities but needs neither root nor that device.
            info['uid'] = 0
            if Path(path) == self.rollback:
                info['dev'] = 66305
            return info
        self.patch(self.cutover, 'identity', new=identity_for_guard)
        real_sync_dir = self.cutover.sync_dir
        self.patch(self.cutover, 'sync_dir', new=lambda path: real_sync_dir(mapped_path(path)))
        real_statvfs = os.statvfs
        self.patch(self.cutover.os, 'statvfs', new=lambda path: real_statvfs(mapped_path(path)))
        self.patch(self.cutover, 'mount_guard', return_value={'fixture_only': True})
        self.patch(self.cutover, 'usage_gate', return_value={'processes': [], 'errors': [], 'mount_aliases': []})
        # Fail the test if any unmocked command tries to leave the rehearsal.
        self.patch(self.cutover.subprocess, 'run', side_effect=AssertionError('No subprocess allowed in rehearsal'))
        self.patch(self.cutover.subprocess, 'check_output', side_effect=AssertionError('No subprocess allowed in rehearsal'))
        self.write_receipts()

    def snapshot_sources(self):
        rows = []
        for name in ('models', 'datasets'):
            root = self.data / name
            for directory, dirs, files in os.walk(root, followlinks=False):
                for entry in sorted(dirs + files):
                    path = Path(directory) / entry
                    info = os.lstat(path)
                    row = {'root': '/data/' + name, 'relative_path': path.relative_to(root).as_posix(),
                           'kind': 'symlink' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'file'}
                    row.update({key: getattr(info, 'st_' + key)
                                for key in ('dev', 'ino', 'mode', 'uid', 'gid', 'size', 'mtime_ns', 'ctime_ns', 'nlink', 'blocks')})
                    if row['kind'] == 'symlink':
                        row['target'] = os.readlink(path)
                    rows.append(row)
        with gzip.open(self.base / 'source-files.jsonl.gz', 'wt', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row) + '\n')

    def write_receipts(self):
        digest = self.cutover.digest
        state = {'phase': 'verify', 'status': 'passed', 'roots': {},
                 'verification_binding': {'source_manifest_sha256': digest(self.base / 'source-files.jsonl.gz'),
                                          'staged_roots': {name: self.cutover.identity(self.stage / name)
                                                           for name in ('models', 'datasets')}}}
        for name in ('models', 'datasets'):
            state['roots'][name] = {}
            for phase in ('copy', 'verification'):
                log = self.base / (name + ('-copy.log' if phase == 'copy' else '-verification.log'))
                log.write_bytes(b'Synthetic rehearsal copy receipt\n' if phase == 'copy' else b'')
                state['roots'][name][phase] = {'status': 'passed', 'exit_code': 0, 'log': str(log),
                                               'log_sha256': digest(log),
                                               'command': ['rsync', '-aHnc', '--dry-run', '--delete']}
        self.state = state
        self.save_json('transfer-state.json', state)
        self.link_receipt = {'passed': True, 'complete': True,
                             'source_manifest_sha256': state['verification_binding']['source_manifest_sha256']}
        self.save_json('link-audit.json', self.link_receipt)

    def save_json(self, name, value):
        (self.base / name).write_text(json.dumps(value), encoding='utf-8')

    def destination_receipt(self):
        baseline = (PROJECT / 'data' / 'sources' / 'catalog-pre-migration.json').read_bytes()
        (self.base / 'catalog-baseline.json').write_bytes(baseline)
        paths = {asset['path'].replace('/data/', '/data/share/', 1) for asset in json.loads(baseline)['assets']}
        self.save_json('destination-entry-observations.json', {
            'complete': True, 'host': self.journal['host'], 'account': 'rmp', 'observer_uid': 1011,
            'observed_at': self.cutover.now(),
            'observations': [{'path': path, 'exists': True, 'readable': True} for path in sorted(paths)]})

    def assert_backup_survives(self):
        self.assertTrue((self.rollback / 'models' / 'payload.bin').exists())
        self.assertTrue((self.rollback / 'datasets' / 'payload.bin').exists())

    def test_path_translation_is_idempotent_when_tmpdir_is_under_data(self):
        # A lexical-only check: this path is never opened or created.
        real_root = self.root
        try:
            self.root = Path('/data/users/rehearsal/tmp/fixture-does-not-exist')
            translated = self.root / 'data' / 'share' / 'models'
            self.assertEqual(self.mapped_path(translated), translated)
            self.assertEqual(self.mapped_path(self.mapped_path(translated)), translated)
        finally:
            self.root = real_root

    def test_publish_refuses_existing_nonempty_target_without_overwriting(self):
        target = self.share / 'models'
        target.mkdir()
        sentinel = target / 'another-team-data'
        sentinel.write_text('preserve', encoding='utf-8')
        staged_inode = os.lstat(self.stage / 'models').st_ino
        with self.assertRaises(FileExistsError):
            self.cutover.publish(self.journal, 'models')
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'preserve')
        self.assertEqual(os.lstat(self.stage / 'models').st_ino, staged_inode)

    def test_publish_refuses_reservation_that_became_nonempty(self):
        target = self.share / 'models'
        target.mkdir(mode=0o700)
        self.journal['roots']['models'] = {'destination_inode': self.cutover.identity(self.stage / 'models'),
                                          'reservation_inode': self.cutover.identity(target)}
        (target / 'unexpected').write_text('preserve', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'Reservation not private and empty'):
            self.cutover.publish(self.journal, 'models')
        self.assertEqual((target / 'unexpected').read_text(encoding='utf-8'), 'preserve')

    def test_publish_reconciles_rename_success_followed_by_error(self):
        real_rename = os.rename
        def uncertain_rename(source, target):
            real_rename(source, target)
            raise OSError('fixture: server renamed but reply was lost')
        with mock.patch.object(self.cutover.os, 'rename', side_effect=uncertain_rename):
            self.cutover.publish(self.journal, 'models')
        self.assertEqual(self.journal['roots']['models']['publication'], 'published')
        self.assertFalse((self.stage / 'models').exists())
        self.assertTrue((self.share / 'models' / 'payload.bin').exists())

    def test_publish_reconciles_completed_rename_with_uncommitted_journal(self):
        real_save = self.cutover.save
        def crash_before_final_save(journal):
            if journal['roots']['models'].get('publication') == 'published':
                raise RuntimeError('fixture: crash before published journal')
            real_save(journal)
        with mock.patch.object(self.cutover, 'save', side_effect=crash_before_final_save):
            with self.assertRaisesRegex(RuntimeError, 'fixture: crash'):
                self.cutover.publish(self.journal, 'models')
        restored = json.loads((self.base / 'cutover-state.json').read_text())
        self.assertEqual(restored['roots']['models']['publication'], 'rename_started')
        with mock.patch.object(self.cutover.os, 'rename', side_effect=AssertionError('Must not rename again')):
            self.cutover.publish(restored, 'models')
        self.assertEqual(restored['roots']['models']['publication'], 'published')

    def test_exchange_completed_with_error_cannot_be_retried_backwards(self):
        real_exchange = self.cutover.exchange
        def uncertain_exchange(old, backup):
            real_exchange(old, backup)
            raise OSError('fixture: exchange completed before error')
        with mock.patch.object(self.cutover, 'exchange', side_effect=uncertain_exchange):
            with self.assertRaisesRegex(OSError, 'exchange completed'):
                self.cutover.switch(self.journal)
        self.assertTrue((self.data / 'models').is_symlink())
        self.assertTrue(self.cutover.expected_original(self.rollback / 'models', 'models'))
        restored = json.loads((self.base / 'cutover-state.json').read_text())
        self.assertEqual(restored['roots']['models']['switch'], 'exchange_started')
        with mock.patch.object(self.cutover, 'exchange', side_effect=AssertionError('Must not exchange backwards')):
            with self.assertRaises((RuntimeError, OSError)):
                self.cutover.switch(restored)
        self.assertTrue((self.data / 'models').is_symlink())
        self.assertTrue(self.cutover.expected_original(self.rollback / 'models', 'models'))

    def test_successful_switch_rejects_a_second_exchange(self):
        self.cutover.switch(self.journal)
        self.assertEqual(self.journal['phase'], 'switched')
        self.assert_backup_survives()
        with mock.patch.object(self.cutover, 'exchange', side_effect=AssertionError('Second exchange forbidden')):
            with self.assertRaises(RuntimeError):
                self.cutover.switch(self.journal)
        for name in ('models', 'datasets'):
            self.assertTrue((self.data / name).is_symlink())
            self.assertTrue(self.cutover.expected_original(self.rollback / name, name))

    def test_changed_source_content_metadata_blocks_cleanup(self):
        self.cutover.switch(self.journal)
        self.destination_receipt()
        payload = self.rollback / 'datasets' / 'payload.bin'
        before = os.lstat(payload)
        payload.write_bytes(b'CHANGED!')
        os.utime(payload, ns=(before.st_atime_ns, before.st_mtime_ns))
        # Same size and restored mtime still changes ctime, which must be checked.
        with self.assertRaisesRegex(RuntimeError, 'Original source changed'):
            self.cutover.cleanup(self.journal)
        self.assert_backup_survives()
        self.assertEqual(self.journal['phase'], 'switched')

    def test_replaced_original_root_inode_blocks_cleanup(self):
        self.cutover.switch(self.journal)
        self.destination_receipt()
        original = self.rollback / 'models'
        retained = self.root / 'retained-original-models'
        original.rename(retained)
        original.mkdir()
        (original / 'replacement-sentinel').write_text('preserve', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'Unexpected original source inode'):
            self.cutover.cleanup(self.journal)
        self.assertTrue((retained / 'payload.bin').exists())
        self.assertTrue((original / 'replacement-sentinel').exists())

    def test_changed_original_root_permissions_block_cleanup(self):
        self.cutover.switch(self.journal)
        self.destination_receipt()
        original = self.rollback / 'models'
        os.chmod(original, stat.S_IMODE(os.lstat(original).st_mode) ^ stat.S_IXGRP)
        with self.assertRaisesRegex(RuntimeError, 'original source root metadata'):
            self.cutover.cleanup(self.journal)
        self.assert_backup_survives()

    def test_added_original_root_extended_attribute_blocks_cleanup(self):
        self.cutover.switch(self.journal)
        self.destination_receipt()
        original = self.rollback / 'models'
        real_listxattr = os.listxattr
        def changed_names(path, **kwargs):
            names = real_listxattr(path, **kwargs)
            return names + ['user.rdc_rehearsal_injected'] if Path(path) == original else names
        with mock.patch.object(self.revalidate.os, 'listxattr', side_effect=changed_names):
            with self.assertRaisesRegex(RuntimeError, 'original root extended attributes'):
                self.cutover.cleanup(self.journal)
        self.assert_backup_survives()
        self.assertEqual(self.journal['phase'], 'switched')

    def test_missing_expected_original_root_attribute_is_rejected(self):
        # Exercise exact equality even on an xattr-free temporary filesystem.
        expected = {**self.root_xattrs,
                    'models': self.root_xattrs['models'] + ('user.rdc_expected_fixture',)}
        with mock.patch.object(self.revalidate, 'ROOT_XATTRS', expected):
            with self.assertRaisesRegex(RuntimeError, 'original root extended attributes'):
                self.revalidate.audit('source')
        self.assertTrue((self.data / 'models' / 'payload.bin').exists())

    def test_invalid_and_stale_verification_receipts_are_rejected(self):
        self.cutover.verify_gate()
        for mutation in ('not_passed', 'wrong_phase', 'wrong_binding', 'changed_log', 'dirty_checksum', 'changed_stage_mode'):
            with self.subTest(mutation=mutation):
                state = copy.deepcopy(self.state)
                verification_log = self.base / 'models-verification.log'
                verification_log.write_bytes(b'')
                mode = stat.S_IMODE(os.lstat(self.stage / 'models').st_mode)
                if mutation == 'not_passed':
                    state['status'] = 'running'
                elif mutation == 'wrong_phase':
                    state['phase'] = 'copy'
                elif mutation == 'wrong_binding':
                    state['verification_binding']['source_manifest_sha256'] = '0' * 64
                elif mutation == 'changed_log':
                    verification_log.write_bytes(b'changed since receipt')
                elif mutation == 'dirty_checksum':
                    verification_log.write_bytes(b'>f..s...... changed-file')
                    state['roots']['models']['verification']['log_sha256'] = self.cutover.digest(verification_log)
                else:
                    os.chmod(self.stage / 'models', mode ^ stat.S_IXUSR)
                self.save_json('transfer-state.json', state)
                try:
                    with self.assertRaises(RuntimeError):
                        self.cutover.verify_gate()
                finally:
                    os.chmod(self.stage / 'models', mode)
                    verification_log.write_bytes(b'')
                    self.save_json('transfer-state.json', self.state)

    def test_invalid_incomplete_and_stale_link_audit_are_rejected(self):
        for field, value in (('passed', False), ('complete', False), ('source_manifest_sha256', '0' * 64)):
            with self.subTest(field=field):
                receipt = {**self.link_receipt, field: value}
                self.save_json('link-audit.json', receipt)
                with self.assertRaisesRegex(RuntimeError, 'symlink relocation audit'):
                    self.cutover.verify_gate()

    def test_stale_destination_access_receipt_blocks_cleanup(self):
        self.cutover.switch(self.journal)
        self.destination_receipt()
        path = self.base / 'destination-entry-observations.json'
        receipt = json.loads(path.read_text())
        receipt['observed_at'] = '2000-01-01T00:00:00+00:00'
        path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(RuntimeError, 'destination entry observations'):
            self.cutover.cleanup(self.journal)
        self.assert_backup_survives()

    def test_cleanup_requires_complete_ordinary_account_access_receipt(self):
        self.cutover.switch(self.journal)
        self.destination_receipt()
        receipt_path = self.base / 'destination-entry-observations.json'
        original = json.loads(receipt_path.read_text())
        for mutation in ('wrong_account', 'privileged_observer', 'unreadable', 'missing_entry', 'incomplete'):
            with self.subTest(mutation=mutation):
                receipt = copy.deepcopy(original)
                if mutation == 'wrong_account':
                    receipt['account'] = 'root'
                elif mutation == 'privileged_observer':
                    receipt['observer_uid'] = 0
                elif mutation == 'unreadable':
                    receipt['observations'][0]['readable'] = False
                elif mutation == 'missing_entry':
                    receipt['observations'].pop()
                else:
                    receipt['complete'] = False
                receipt_path.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(RuntimeError, 'destination entry observations'):
                    self.cutover.cleanup(self.journal)
                self.assert_backup_survives()

    def test_successful_cleanup_removes_only_original_backups_and_is_idempotent(self):
        self.cutover.switch(self.journal)
        self.destination_receipt()
        self.cutover.cleanup(self.journal)
        self.assertEqual(self.journal['phase'], 'cleaned')
        for name in ('models', 'datasets'):
            self.assertFalse(os.path.lexists(self.rollback / name))
            self.assertTrue((self.data / name).is_symlink())
            self.assertTrue((self.share / name / 'payload.bin').exists())
        with mock.patch.object(self.cutover.shutil, 'rmtree', side_effect=AssertionError('Already-cleaned roots must not be deleted again')):
            self.cutover.cleanup(self.journal)

    def test_interrupted_cleaning_refuses_automatic_resume(self):
        self.cutover.switch(self.journal)
        self.destination_receipt()
        def partial_delete(path):
            self.assertEqual(Path(path), self.rollback / 'models')
            (Path(path) / 'payload.bin').unlink()
            raise RuntimeError('fixture: interrupted deletion')
        with mock.patch.object(self.cutover.shutil, 'rmtree', side_effect=partial_delete) as deletion:
            deletion.avoids_symlink_attacks = True
            with self.assertRaisesRegex(RuntimeError, 'fixture: interrupted'):
                self.cutover.cleanup(self.journal)
        restored = json.loads((self.base / 'cutover-state.json').read_text())
        self.assertEqual(restored['phase'], 'cleaning')
        self.assertEqual(restored['roots']['models']['cleanup'], 'delete_started')
        with mock.patch.object(self.cutover.shutil, 'rmtree', side_effect=AssertionError('No automatic deletion resume')):
            with self.assertRaisesRegex(RuntimeError, 'Interrupted deletion'):
                self.cutover.cleanup(restored)
        self.assertTrue((self.rollback / 'datasets' / 'payload.bin').exists())
        self.assertTrue((self.share / 'models' / 'payload.bin').exists())


if __name__ == '__main__':
    unittest.main()
