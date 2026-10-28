"""Migration projection tests use saved metadata and synthetic receipts only."""
import copy
import csv
import hashlib
import io
import json
import pathlib
import re
import tempfile
import unittest
from contextlib import closing, redirect_stdout

from catalog import export_catalog, export_csv, import_catalog, open_catalog
from tools import build_catalog, build_inventory
from tools.path_migration import (OLD_ROOTS, NEW_ROOTS, ROOT_PAIRS, approved_path,
                                  catalog_storage, destination_path, load_migration,
                                  planned_manifest, project_catalog, validate_manifest,
                                  attach_physical_inventory)

PROJECT = pathlib.Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        (self.root / 'data' / 'sources').mkdir(parents=True)
        (self.root / 'var').mkdir()
        # The active catalog can already contain a pending or applied projection.
        # These tests deliberately exercise the immutable pre-migration baseline.
        self.raw = (PROJECT / 'data' / 'sources' / 'catalog-pre-migration.json').read_bytes()
        self.baseline = json.loads(self.raw)
        self.registry = json.loads((PROJECT / 'data' / 'resource-registry.json').read_text(encoding='utf-8'))
        self.write('data/sources/catalog-pre-migration.json', self.raw)
        self.write('data/resource-registry.json', json.dumps(self.registry).encode())
        self.manifest = planned_manifest(self.baseline, self.registry, 'data/sources/catalog-pre-migration.json',
                                         hashlib.sha256(self.raw).hexdigest(), 'fixture-migration')

    def write(self, relative, data):
        path = self.root / relative
        path.write_bytes(data)
        return {'ref': relative, 'sha256': hashlib.sha256(data).hexdigest()}

    def switched(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['state'] = 'switched'
        receipts = {}
        for phase in ('copy', 'verification', 'cutover'):
            receipts[phase] = {'status': 'passed', 'host': 'fixture-host', 'observed_at': '2026-10-27T09:00:00Z',
                               'evidence': self.write('var/' + phase + '.txt', ('Synthetic test receipt ' + phase).encode())}
        observations = []
        for path in sorted({entry['to_path'] for entry in manifest['entries']}):
            observations.append({'host': 'fixture-host', 'path': path, 'realpath': path,
                                 'observed_at': '2026-10-27T08:59:00Z', 'account': 'rmp',
                                 'exists': True, 'readable': True, 'kind': 'directory',
                                 'owner': 'root', 'mode': '0o755', 'uid': 0, 'gid': 0})
        receipts['verification'].update({'strategy': 'synthetic fixture; not a server verification', 'errors': [],
                                         'observations': observations})
        receipts['cutover'].update({'mount': {'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'},
                                    'aliases': [{'path': old, 'target': new, 'kind': 'symlink', 'verified': True}
                                                for old, new in ROOT_PAIRS.values()]})
        manifest['receipts'] = receipts
        return manifest

    def project(self, manifest):
        observations = validate_manifest(manifest, self.baseline, self.registry, self.root)
        return project_catalog(self.baseline, manifest, observations)

    def test_pending_all_phases_keep_paths_ids_observations_and_counts(self):
        for state in ('planned', 'copying', 'verified'):
            manifest = copy.deepcopy(self.manifest)
            manifest['state'] = state
            projected = self.project(manifest)
            self.assertEqual([a['id'] for a in projected['assets']], [a['id'] for a in self.baseline['assets']])
            for before, after in zip(self.baseline['assets'], projected['assets']):
                self.assertEqual(before, {key: value for key, value in after.items() if key != 'storage'})
                self.assertFalse(after['storage']['migration']['activated'])
                self.assertEqual(after['storage']['legacy_aliases'], [])

    def test_full_switch_preserves_228_identities_groups_counts_and_historical_evidence(self):
        projected = self.project(self.switched())
        old_mapping, _ = build_inventory.build_mapping(self.baseline, self.registry, now='2026-10-27T10:00:00Z')
        new_mapping, registry = build_inventory.build_mapping(projected, self.registry, now='2026-10-27T10:00:00Z')
        self.assertEqual(new_mapping['summary']['records'], 228)
        self.assertEqual(new_mapping['summary']['unique_paths'], 221)
        self.assertEqual({g['id'] for g in old_mapping['groups']}, {g['id'] for g in new_mapping['groups']})
        for before, after in zip(old_mapping['items'], new_mapping['items']):
            self.assertEqual((before['asset_id'], before['registry_id'], before['group_id']),
                             (after['asset_id'], after['registry_id'], after['group_id']))
            self.assertEqual(after['current_path'], destination_path(before['current_path']))
            self.assertEqual(before['documentation']['quantity'], after['documentation']['quantity'])
            self.assertEqual(before['documentation']['model_configuration'], after['documentation']['model_configuration'])
            self.assertEqual(before['version']['upstream_revision'], after['version']['upstream_revision'])
            self.assertEqual(before['evidence'][1:3], after['evidence'][1:3])
            self.assertEqual(after['checks']['observed_at'], '2026-10-27T08:59:00Z')
            self.assertTrue(after['checks']['readable'])
            self.assertEqual(registry['entries'][after['asset_id']]['registry_id'], before['registry_id'])
        features = [item for item in new_mapping['items'] if item['subtype'] == 'feature']
        self.assertEqual(len(features), 8)
        self.assertEqual(len({item['current_path'] for item in features}), 1)
        self.assertEqual(len({item['registry_id'] for item in features}), 8)
        # Rebuilding does not advance observed times to registration time.
        _, again = build_inventory.build_mapping(projected, registry, now='2026-10-28T10:00:00Z')
        for entry in again['entries'].values():
            if entry.get('active'):
                self.assertEqual(entry['path_history'][-1]['last_observed_at'], '2026-10-27T08:59:00Z')

    def test_complete_receipts_required_and_hash_verified(self):
        for phase in ('copy', 'verification', 'cutover'):
            manifest = self.switched()
            del manifest['receipts'][phase]
            with self.assertRaises(ValueError):
                self.project(manifest)
        manifest = self.switched()
        (self.root / 'var' / 'copy.txt').write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'sha256_mismatch'):
            self.project(manifest)
        manifest = self.switched()
        manifest['receipts']['verification']['observations'].pop()
        with self.assertRaisesRegex(ValueError, 'all_target_observations'):
            self.project(manifest)
        manifest = self.switched()
        manifest['receipts']['cutover']['mount']['source'] = '/dev/local-disk'
        with self.assertRaisesRegex(ValueError, 'mount_receipt'):
            self.project(manifest)
        manifest = self.switched()
        manifest['receipts']['cutover']['aliases'][0]['verified'] = False
        with self.assertRaisesRegex(ValueError, 'alias_not_verified'):
            self.project(manifest)

    def test_mapping_requires_exact_registered_ids_and_root_pairs(self):
        for field, replacement in (('asset_id', 'unknown'), ('registry_id', 'reg-other'),
                                    ('to_path', '/data/share/public/not-a-library')):
            manifest = copy.deepcopy(self.manifest)
            manifest['entries'][0][field] = replacement
            with self.assertRaises(ValueError):
                self.project(manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest['roots'][0]['target_root'] = '/data/share'
        with self.assertRaises(ValueError):
            self.project(manifest)

    def test_other_hosts_need_their_own_mount_observation(self):
        manifest = self.switched()
        other = copy.deepcopy(manifest['receipts']['verification']['observations'][0])
        other['host'] = 'unobserved-other-client'
        other['readable'] = False
        manifest['receipts']['verification']['observations'].insert(0, other)
        with self.assertRaisesRegex(ValueError, 'mount_receipt'):
            self.project(manifest)
        other['mount'] = {'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'}
        result = self.project(manifest)
        self.assertTrue(result['scope']['storage_migration']['activated'])
        mapping, _ = build_inventory.build_mapping(result, self.registry)
        self.assertTrue(all(item['checks']['readable'] is True for item in mapping['items']))
        self.assertTrue(all(item['checks']['host'] == 'fixture-host' for item in mapping['items']))

    def test_shared_capacity_is_independent_of_old_disk_and_resource_sizes(self):
        manifest = self.switched()
        result = self.project(manifest)
        self.assertIn('未随切换回执提供', result['scope']['存储现状'])
        self.assertEqual(result['scope']['historical_storage_snapshot'], self.baseline['scope']['存储现状'])
        manifest['receipts']['cutover']['disk_snapshot'] = {'mount': '/data/share', 'total_bytes': 10000,
                                                         'available_bytes': 1234, 'observed_at': '2026-10-27T09:01:00Z'}
        result = self.project(manifest)
        self.assertEqual(result['scope']['disk_snapshot']['available_bytes'], 1234)
        self.assertIn('1234 字节', result['scope']['存储现状'])
        manifest['receipts']['cutover']['disk_snapshot']['available_bytes'] = 10001
        with self.assertRaisesRegex(ValueError, 'disk_snapshot'):
            self.project(manifest)

    def test_scoped_path_rules_and_schemas_reject_traversal_and_prefixes(self):
        forbidden = ['/data/share', '/data/share/public/a', '/data/users/private', '/data/datasets-other/a',
                     '/data/share/models-other/a', '/data/share/datasets/../public/a', '/data/datasets/../models/a',
                     '/data/share/datasets/a\\b', '/data/share/models/a\x00b', '/data/share/models/a\n']
        for path in forbidden:
            self.assertIsNone(approved_path(path), path)
        for name in ('resource-card', 'submission'):
            schema = json.loads((PROJECT / 'docs' / 'templates' / (name + '.schema.json')).read_text(encoding='utf-8'))
            pattern = (schema['properties']['locations']['items']['properties']['path']['pattern'] if name == 'resource-card'
                       else schema['properties']['delivery']['properties']['existing_path']['pattern'])
            for path in forbidden:
                self.assertIsNone(re.search(pattern, path), (name, path))
            for path in OLD_ROOTS + NEW_ROOTS:
                self.assertTrue(re.fullmatch(pattern, path + '/valid-name'))
        new_asset = copy.deepcopy(self.baseline['assets'][0])
        new_asset['path'] = destination_path(new_asset['path'])
        with self.assertRaisesRegex(ValueError, 'activated_migration'):
            catalog_storage(new_asset)

    def test_builder_rebuild_uses_pinned_baseline_not_previous_output(self):
        manifest = self.switched()
        manifest_path = self.root / 'data' / 'path-migration.json'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            first, _ = build_catalog.main(self.root)
            second, _ = build_catalog.main(self.root)
        self.assertEqual(first, second)
        self.assertEqual(len(first['assets']), 228)
        self.assertFalse((self.root / 'data' / 'sources' / build_catalog.PUBLIC_CSV).exists())
        # JSON and CSV exports keep the independently dated storage projection.
        db = self.root / 'catalog.sqlite3'
        import_catalog(first, db)
        with closing(open_catalog(db)) as connection:
            exported = export_catalog(connection)
            self.assertEqual(exported['assets'][0]['storage'], first['assets'][0]['storage'])
            csv_rows = list(csv.DictReader(io.StringIO(export_csv(connection))))
            self.assertIn('storage', csv_rows[0])
            self.assertIn('/data/share/', csv_rows[0]['path'])

    def test_failed_activation_does_not_overwrite_existing_output(self):
        self.write('data/catalog.json', self.raw)
        manifest = self.switched()
        manifest['receipts']['verification']['errors'] = ['fixture-failure']
        path = self.root / 'var' / 'manifest.json'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(ValueError):
            build_catalog.main(self.root, path)
        self.assertEqual((self.root / 'data' / 'catalog.json').read_bytes(), self.raw)

    def test_physical_inventory_is_separate_from_historical_quantities_and_ids(self):
        path = self.baseline['assets'][0]['path']
        stats = {'file_count': 12, 'directory_count': 3, 'symlink_count': 2, 'apparent_file_bytes': 120,
                 'unique_file_bytes': 100, 'allocated_file_bytes': 4096, 'unique_inodes': 10,
                 'external_absolute_symlink_count': 0, 'extension_counts': {'.wav': 10, '.json': 2},
                 'newest_mtime': '2026-10-26T12:00:00Z'}
        physical = {'schema_version': '1.0', 'source': 'source_manifest', 'observed_at': '2026-10-27T04:00:00Z',
                    'roots': {root: stats for root in OLD_ROOTS}, 'paths': {path: stats},
                    'summary': stats}
        target = self.root / 'data' / 'physical-inventory.json'
        target.write_text(json.dumps(physical), encoding='utf-8')
        updated = attach_physical_inventory(copy.deepcopy(self.baseline), target)
        self.assertEqual(updated['assets'][0]['size_bytes'], self.baseline['assets'][0]['size_bytes'])
        self.assertEqual(updated['assets'][0]['file_count'], self.baseline['assets'][0]['file_count'])
        self.assertEqual(updated['assets'][0]['physical_inventory']['file_count'], 12)
        self.assertNotIn('storage', updated['assets'][0])
        self.assertEqual(updated['scope']['physical_inventory']['paths_covered'], 1)
        mapping, _ = build_inventory.build_mapping(updated, self.registry)
        self.assertEqual(mapping['items'][0]['physical_inventory']['unique_file_bytes'], 100)
        rendered, markdown = build_inventory.make_card(mapping['items'][0], 'Fixture', mapping)
        self.assertIn('非目标占用预测', rendered)
        self.assertIn('源位置', markdown)
        physical['paths']['/data/users/private'] = stats
        target.write_text(json.dumps(physical), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unregistered_path'):
            attach_physical_inventory(copy.deepcopy(self.baseline), target)


if __name__ == '__main__':
    unittest.main()
