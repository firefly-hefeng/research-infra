"""Isolated public-receipt tests. No production path, mount or operation is used."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import cpfs_publish_evidence as publisher
from tools import path_migration as migration


PROJECT = Path(__file__).resolve().parents[1]


def when(minute):
    return '2026-10-27T00:%02d:00+00:00' % minute


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / 'project'
        self.base = self.root / 'private'
        (self.project / 'data/sources').mkdir(parents=True)
        self.base.mkdir()
        raw = (PROJECT / publisher.BASELINE_REF).read_bytes()
        self.baseline = json.loads(raw)
        self.registry = json.loads((PROJECT / 'data/resource-registry.json').read_text(encoding='utf-8'))
        (self.project / publisher.BASELINE_REF).write_bytes(raw)
        self.write('catalog-baseline.json', raw=raw)
        self.project_write('data/resource-registry.json', self.registry)
        manifest = b'PRIVATE_RAW_FILE_MANIFEST_NEVER_PUBLIC'
        self.write('source-files.jsonl.gz', raw=manifest)
        self.policy = publisher.Policy(project=self.project, base=self.base, host='fixture-host',
                                       baseline_sha256=publisher.sha256(raw),
                                       manifest_sha256=publisher.sha256(manifest),
                                       root_counts={'datasets': 2220141, 'models': 234})
        self.plan = migration.planned_manifest(self.baseline, self.registry, publisher.BASELINE_REF,
                                              self.policy.baseline_sha256, publisher.MIGRATION_ID)
        self.plan['state'] = 'copying'
        self.project_write('data/path-migration.json', self.plan)
        self.mount = {'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'}
        self.inodes = {name: {'dev': 20, 'ino': number, 'mode': 0o40755, 'uid': 0, 'gid': 0}
                       for name, number in (('models', 100), ('datasets', 200))}
        self.transfer = {'migration_id': publisher.MIGRATION_ID, 'host': self.policy.host,
                         'stage': self.policy.stage, 'phase': 'verify', 'status': 'passed',
                         'mount': dict(self.mount, options='rw'), 'roots': {},
                         'verification_binding': {'source_manifest_sha256': self.policy.manifest_sha256,
                                                  'staged_roots': self.inodes}}
        for name in publisher.NAMES:
            self.transfer['roots'][name] = {}
            for phase in ('copy', 'verification'):
                log = name + ('-copy.log' if phase == 'copy' else '-verification.log')
                payload = b'PRIVATE_COPY_LOG_FILE_NAME\n' if phase == 'copy' else b''
                self.write(log, raw=payload)
                command = (['rsync', '-aH', '--numeric-ids', '--one-file-system', '--bwlimit=204800', '--stats',
                            '/data/' + name, self.policy.stage + '/'] if phase == 'copy' else
                           ['rsync', '-aHnc', '--numeric-ids', '--one-file-system', '--delete', '--dry-run',
                            '--itemize-changes', '--out-format=%i %n%L', '/data/' + name + '/',
                            self.policy.stage + '/' + name + '/'])
                self.transfer['roots'][name][phase] = {
                    'status': 'passed', 'exit_code': 0, 'log': str(self.base / log),
                    'log_sha256': publisher.sha256(payload), 'command': command,
                    'started_at': when(0 if phase == 'copy' else 2),
                    'finished_at': when(1 if phase == 'copy' else 3),
                    'pid': 923456, 'private_process_detail': 'PRIVATE_PROCESS_DETAIL'}
        self.write('transfer-state.json', self.transfer)
        self.journal = {'migration_id': publisher.MIGRATION_ID, 'host': self.policy.host,
                        'phase': 'switched', 'switched_at': when(11), 'roots': {}}
        for index, name in enumerate(publisher.NAMES):
            self.journal['roots'][name] = {'publication': 'published', 'published_at': when(6),
                                           'switch': 'switched', 'switched_at': when(7 + index),
                                           'destination_inode': self.inodes[name]}
        self.write('cutover-state.json', self.journal)
        self.source_audit('source-before-switch.json', 4, 'source')
        self.source_audit('source-after-switch.json', 9, 'rollback')
        self.usage_audit('usage-before-switch.json', 5)
        self.usage_audit('usage-after-switch.json', 10)
        # Mirrors real census: no timestamp or source-manifest field is present.
        self.write('source-semantics.json', {
            'complete': True, 'elapsed_seconds': 35.9,
            'roots': {'/data/' + name: {'entries': self.policy.root_counts[name], 'xattr_counts': {}}
                      for name in publisher.NAMES},
            'external_link_samples': [{'target': '/outside/PRIVATE_LINK_TARGET'}]})
        self.write('link-audit.json', {
            'complete': True, 'passed': True, 'errors': [], 'observed_at': when(3),
            'source_manifest_sha256': self.policy.manifest_sha256,
            'counts': {'manifest_rows': sum(self.policy.root_counts.values()), 'errors': 0,
                       'new_cycles': 0, 'new_depth_limits': 0, 'relative_relocation_hazards': 0,
                       'other_relocation_hazards': 0, 'symlinks': 174722, 'relative_links': 58,
                       'absolute_internal_alias_dependencies': 74,
                       'absolute_external_node_dependencies': 174590,
                       'preexisting_cycles': 0, 'preexisting_depth_limits': 0},
            'symlinks': [{'path': 'PRIVATE_INDIVIDUAL_FILENAME', 'target': '/outside/PRIVATE_LINK_TARGET'}]})
        self.refresh_observation()

    def write(self, name, value=None, raw=None):
        (self.base / name).write_bytes(raw if raw is not None else publisher.json_bytes(value))

    def project_write(self, name, value):
        (self.project / name).write_bytes(publisher.json_bytes(value))

    def read(self, name):
        return json.loads((self.base / name).read_bytes())

    def source_audit(self, name, minute, location):
        self.write(name, {'host': self.policy.host, 'observed_at': when(minute), 'location': location,
                          'passed': True, 'errors': [], 'expected_entries': self.policy.root_counts,
                          'actual_entries': self.policy.root_counts})

    def usage_audit(self, name, minute):
        # Real cpfs_usage emits no complete/status booleans.
        self.write(name, {'host': self.policy.host, 'observed_at': when(minute),
                          'visibility': 'local_host_only_inode_match', 'processes': [], 'errors': [],
                          'mount_aliases': [], 'private_extra': 'PRIVATE_PROCESS_DETAIL'})

    def refresh_observation(self):
        cleaned = self.journal['phase'] == 'cleaned'
        start, row_time, end = (23, 24, 25) if cleaned else (12, 13, 14)
        rows = []
        for path in sorted({migration.destination_path(row['path']) for row in self.baseline['assets']}):
            rows.append({'host': self.policy.host, 'account': 'rmp', 'observer_uid': 1011,
                         'path': path, 'realpath': path, 'observed_at': when(row_time),
                         'exists': True, 'readable': True, 'kind': 'directory', 'entry_kind': 'directory',
                         'owner': 'root', 'mode': '0o755', 'uid': 0, 'gid': 0, 'mtime_ns': 1700000000,
                         'mount': self.mount, 'reason': None,
                         'symlink': {'is_symlink': False, 'target_scope': None},
                         'raw_target': 'PRIVATE_LINK_TARGET'})
        self.observation = {
            'schema_version': '1.0', 'migration_id': publisher.MIGRATION_ID, 'complete': True,
            'host': self.policy.host, 'account': 'rmp', 'observer_uid': 1011, 'observer_gid': 1011,
            'observer_groups': [1011], 'started_at': when(start), 'observed_at': when(end),
            'baseline_sha256': self.policy.baseline_sha256,
            'cutover_state_sha256': publisher.sha256((self.base / 'cutover-state.json').read_bytes()),
            'cutover_phase': self.journal['phase'], 'switched_at': self.journal['switched_at'],
            'observations': rows, 'errors': [], 'mount': self.mount,
            'disk_snapshot': {'mount': '/data/share', 'total_bytes': 10000000000000,
                              'available_bytes': 6000000000000, 'observed_at': when(row_time)},
            'root_checks': [{'path': old, 'target': new, 'realpath': new, 'kind': 'symlink',
                             'verified': True, 'observed_at': when(row_time),
                             'destination_inode': self.inodes[name]}
                            for name, (old, new) in migration.ROOT_PAIRS.items()]}
        self.write('destination-entry-observations.json', self.observation)

    def cleaned(self, refresh=True):
        self.journal.update(phase='cleaned', cleanup_started_at=when(17), cleaned_at=when(22),
                            local_available_before_cleanup=1000, local_available_after_cleanup=900)
        self.source_audit('source-before-cleanup.json', 15, 'rollback')
        self.usage_audit('usage-before-cleanup.json', 16)
        for index, name in enumerate(publisher.NAMES):
            self.journal['roots'][name].update(cleanup='deleted', deleted_at=when(19 + 2 * index))
            self.usage_audit('usage-before-delete-' + name + '.json', 18 + 2 * index)
        self.write('cutover-state.json', self.journal)
        if refresh:
            self.refresh_observation()

    def prepare(self):
        return publisher.prepare_bundle(self.policy, host_provider=lambda: self.policy.host)

    def assert_rejected(self, pattern):
        original = (self.project / 'data/path-migration.json').read_bytes()
        with self.assertRaisesRegex(publisher.PublishError, pattern):
            self.prepare()
        self.assertEqual(original, (self.project / 'data/path-migration.json').read_bytes())
        self.assertFalse((self.project / 'data/migration-evidence').exists())

    def test_check_is_read_only_and_sanitizes_actual_receipt_shapes(self):
        before = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        bundle = self.prepare()
        self.assertEqual(before, {p.relative_to(self.project): p.read_bytes()
                                  for p in self.project.rglob('*') if p.is_file()})
        self.assertEqual(bundle['reports']['cleanup']['status'], 'not_completed')
        self.assertEqual(len(bundle['manifest']['entries']), 228)
        self.assertEqual(len(bundle['reports']['verification']['observations']), 221)
        self.assertEqual(len(bundle['files']), 11)
        public = b'\n'.join(bundle['files'].values())
        for private in (b'PRIVATE_', b'923456', str(self.base).encode(), b'source-files.jsonl.gz'):
            self.assertNotIn(private, public)
        self.assertEqual(bundle['reports']['preflight']['link_relocation_audit']['counts']
                         ['absolute_external_node_dependencies'], 174590)
        self.assertIn('not_all_links_usable', bundle['reports']['preflight']['link_relocation_audit']['scope'])

    def test_publish_matches_strict_schema_and_is_idempotent(self):
        result = publisher.publish_bundle(self.prepare())
        self.assertEqual(result['observed_paths'], 221)
        baseline, manifest, observed = migration.load_migration(
            self.project, self.project / 'data/path-migration.json', self.registry)
        self.assertEqual(manifest['state'], 'switched')
        self.assertEqual(len(observed), 221)
        self.assertEqual([a['id'] for a in baseline['assets']], [a['id'] for a in self.baseline['assets']])
        for name in publisher.REPORT_NAMES:
            reference = manifest['receipts'][name]['evidence']
            self.assertEqual((self.project / reference['ref']).read_bytes(),
                             (self.project / ('data/migration-evidence/' + name + '.json')).read_bytes())
            self.assertEqual(reference['sha256'] + '.json', Path(reference['ref']).name)
        repeated = publisher.publish_bundle(self.prepare())
        self.assertEqual(result['manifest_sha256'], repeated['manifest_sha256'])

    def test_cleanup_requires_fresh_observation_and_keeps_old_objects(self):
        publisher.publish_bundle(self.prepare())
        old_manifest = json.loads((self.project / 'data/path-migration.json').read_bytes())
        old_objects = {row['evidence']['ref']: (self.project / row['evidence']['ref']).read_bytes()
                       for row in old_manifest['receipts'].values()}
        self.cleaned(refresh=False)
        with self.assertRaisesRegex(publisher.PublishError, 'observation_binding_stale'):
            self.prepare()
        self.refresh_observation()
        bundle = self.prepare()
        self.assertEqual(bundle['reports']['cleanup']['status'], 'passed')
        self.assertEqual(bundle['reports']['cleanup']['local_space_observation']['net_available_change_bytes'], -100)
        publisher.publish_bundle(bundle)
        for reference, raw in old_objects.items():
            self.assertEqual((self.project / reference).read_bytes(), raw)
        # The old active manifest is still hash-verifiable after convenience reports update.
        self.assertEqual(len(migration.validate_manifest(old_manifest, self.baseline, self.registry, self.project)), 221)

    def test_copy_log_tampering_or_manifest_misbinding_rejected(self):
        self.write('models-copy.log', raw=b'changed')
        self.assert_rejected('log_binding_failed')
        self.write('models-copy.log', raw=b'PRIVATE_COPY_LOG_FILE_NAME\n')
        self.write('source-files.jsonl.gz', raw=b'another manifest')
        self.assert_rejected('source_manifest_hash_mismatch')

    def test_nonempty_verification_even_with_matching_hash_rejected(self):
        data = b'>fcs....... changed-file\n'
        self.write('datasets-verification.log', raw=data)
        self.transfer['roots']['datasets']['verification']['log_sha256'] = publisher.sha256(data)
        self.write('transfer-state.json', self.transfer)
        self.assert_rejected('checksum_dry_run_has_differences')

    def test_wrong_transfer_command_or_incomplete_phase_rejected(self):
        self.transfer['roots']['models']['verification']['command'].remove('--dry-run')
        self.write('transfer-state.json', self.transfer)
        self.assert_rejected('unexpected_transfer_command')
        self.transfer['status'] = 'running'
        self.write('transfer-state.json', self.transfer)
        self.assert_rejected('checksum_phase_not_passed')

    def test_no_activation_for_missing_or_unreadable_registered_entry(self):
        self.observation['observations'].pop()
        self.write('destination-entry-observations.json', self.observation)
        self.assert_rejected('all_destination_entries_required')
        self.refresh_observation()
        self.observation['observations'][0]['readable'] = False
        self.write('destination-entry-observations.json', self.observation)
        self.assert_rejected('ordinary_entry_check_not_passed')

    def test_wrong_ordinary_account_and_external_realpath_rejected(self):
        self.observation['observer_uid'] = 0
        self.write('destination-entry-observations.json', self.observation)
        self.assert_rejected('ordinary_observer_identity_required')
        self.refresh_observation()
        self.observation['observations'][0]['realpath'] = '/outside/somewhere'
        self.write('destination-entry-observations.json', self.observation)
        self.assert_rejected('entry_realpath_outside_own_library')

    def test_alias_mount_disk_and_inode_identity_fail_closed(self):
        cases = [
            (lambda row: row['root_checks'][0].update(verified=False), 'current_alias_check_failed'),
            (lambda row: row['root_checks'][0]['destination_inode'].update(ino=999), 'current_root_inode_changed'),
            (lambda row: row['mount'].update(source='/dev/wrong'), 'cpfs_mount_mismatch'),
            (lambda row: row['disk_snapshot'].update(available_bytes=-1), 'invalid_integer'),
        ]
        original = copy.deepcopy(self.observation)
        for mutate, error in cases:
            with self.subTest(error=error):
                candidate = copy.deepcopy(original)
                mutate(candidate)
                self.write('destination-entry-observations.json', candidate)
                self.assert_rejected(error)

    def test_partial_cutover_or_cleanup_never_published(self):
        self.journal['phase'] = 'cleaning'
        self.write('cutover-state.json', self.journal)
        self.assert_rejected('complete_cutover_required')
        self.cleaned()
        self.journal['roots']['datasets']['cleanup'] = 'deleting'
        self.write('cutover-state.json', self.journal)
        self.refresh_observation()
        self.assert_rejected('both_original_trees_must_be_deleted')

    def test_source_changes_processes_and_relocation_hazards_are_blockers(self):
        candidate = self.read('source-after-switch.json')
        candidate['actual_entries'] = {'models': 235, 'datasets': 2220141}
        self.write('source-after-switch.json', candidate)
        self.assert_rejected('source_revalidation_count_mismatch')
        self.source_audit('source-after-switch.json', 9, 'rollback')
        candidate = self.read('usage-after-switch.json')
        candidate['processes'] = [{'pid': 1234, 'cmd': 'PRIVATE_PROCESS_DETAIL'}]
        self.write('usage-after-switch.json', candidate)
        self.assert_rejected('source_usage_not_clear')
        self.usage_audit('usage-after-switch.json', 10)
        candidate = self.read('link-audit.json')
        candidate['counts']['relative_relocation_hazards'] = 1
        self.write('link-audit.json', candidate)
        self.assert_rejected('link_relocation_audit_counts_invalid')

    def test_input_change_between_prepare_and_publish_does_not_activate(self):
        bundle = self.prepare()
        self.write('cutover-state.json', dict(self.journal, updated_at=when(26)))
        with self.assertRaisesRegex(publisher.PublishError, 'input_changed_before_publication'):
            publisher.publish_bundle(bundle)
        self.assertEqual(json.loads((self.project / 'data/path-migration.json').read_bytes())['state'], 'copying')
        self.assertFalse((self.project / 'data/migration-evidence').exists())

    def test_existing_immutable_object_tampering_refused(self):
        bundle = self.prepare()
        reference = bundle['manifest']['receipts']['copy']['evidence']['ref']
        target = self.project / reference
        target.parent.mkdir(parents=True)
        target.write_bytes(b'wrong object')
        with self.assertRaisesRegex(publisher.PublishError, 'immutable_object_already_differs'):
            publisher.publish_bundle(bundle)
        self.assertEqual(json.loads((self.project / 'data/path-migration.json').read_bytes())['state'], 'copying')

    def test_production_host_and_baseline_binding_are_required(self):
        with self.assertRaisesRegex(publisher.PublishError, 'publisher_host_mismatch'):
            publisher.prepare_bundle(self.policy, host_provider=lambda: 'another-host')
        self.write('catalog-baseline.json', raw=b'wrong baseline')
        self.assert_rejected('private_baseline_hash_mismatch')

    def test_failure_writing_fixed_report_keeps_active_manifest_and_old_objects(self):
        publisher.publish_bundle(self.prepare())
        before = (self.project / 'data/path-migration.json').read_bytes()
        self.cleaned()
        bundle = self.prepare()
        original = publisher.atomic_write

        def fail_fixed(path, data):
            if path.name == 'verification.json':
                raise OSError('fixture write failure')
            original(path, data)

        with mock.patch.object(publisher, 'atomic_write', side_effect=fail_fixed):
            with self.assertRaisesRegex(OSError, 'fixture write failure'):
                publisher.publish_bundle(bundle)
        self.assertEqual((self.project / 'data/path-migration.json').read_bytes(), before)
        self.assertEqual(len(migration.load_migration(self.project, self.project / 'data/path-migration.json', self.registry)[2]), 221)

    def test_symlink_input_and_output_refused(self):
        target = self.base / 'models-copy.log'
        backing = self.root / 'copy-log'
        target.replace(backing)
        try:
            target.symlink_to(backing)
        except OSError:
            backing.replace(target)
            self.skipTest('local filesystem does not permit symlink creation')
        self.assert_rejected('symlink_receipt_or_output_refused')
        target.unlink()
        backing.replace(target)
        outside = self.root / 'outside'
        outside.mkdir()
        (self.project / 'data/migration-evidence').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(publisher.PublishError, 'symlink_receipt_or_output_refused'):
            publisher.publish_bundle(self.prepare())
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
