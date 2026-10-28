"""Record coverage, identity persistence and evidence-safe inventory tests."""
import copy
import csv
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rdc_inventory_test', PROJECT / 'tools' / 'build_inventory.py')
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def asset(asset_id='first', path='/data/datasets/example', **fields):
    result = {'id': asset_id, 'name': 'Example', 'kind': 'dataset', 'path': path,
              'status': 'documented', 'metadata': {}, 'size_bytes': None, 'file_count': None}
    result.update(fields)
    return result


def document(assets):
    return {'schema_version': '1.0', 'generated_at': '2026-10-18T19:46:35.062887+00:00',
            'scope': {}, 'sources': [], 'assets': assets}


class InventoryTests(unittest.TestCase):
    def test_actual_catalog_is_fully_covered_without_merging_same_location_features(self):
        actual = json.loads((PROJECT / 'data' / 'catalog.json').read_text(encoding='utf-8'))
        mapping, _ = inventory.build_mapping(actual, now='2026-10-19T01:00:00Z')
        self.assertEqual(len(actual['assets']), 228)
        self.assertEqual(mapping['summary']['records'], 228)
        self.assertEqual({item['asset_id'] for item in mapping['items']}, {item['id'] for item in actual['assets']})
        self.assertEqual(len({item['registry_id'] for item in mapping['items']}), 228)
        self.assertEqual(mapping['summary']['unique_paths'], 221)
        features = [item for item in mapping['items'] if item['subtype'] == 'feature']
        self.assertEqual(len(features), 8)
        self.assertEqual(len({item['current_path'] for item in features}), 1)
        self.assertEqual(len({item['registry_id'] for item in features}), 8)
        for item in features:
            same_location = [relation for relation in item['relationships'] if relation['type'] == 'same_location']
            self.assertEqual(len(same_location), 7)
            self.assertTrue(all(relation['status'] == 'candidate' for relation in same_location))
            self.assertIsNone(item['identity']['logical_resource_id'])
        self.assertEqual(sum(group['records'] for group in mapping['groups']), 228)
        ledger_items = [item for item in mapping['items'] if item['documentation']['source_fields']]
        self.assertEqual(len(ledger_items), 198)
        for item in ledger_items:
            source = next(evidence for evidence in item['evidence'] if evidence['type'] == 'source_record')
            self.assertTrue(source['url'].startswith('https://wcn5kauqqbj1.feishu.cn/'))
            self.assertIn('非上游来源', source['label'])
        qwen = next(item for item in mapping['items'] if item['display_name'] == 'Qwen3-8B')
        self.assertEqual(qwen['documentation']['model_configuration']['model_type'], 'qwen3')
        actual_by_id = {entry['id']: entry for entry in actual['assets']}
        for item in mapping['items']:
            if item['subtype'] == 'model_weights':
                metadata = actual_by_id[item['asset_id']]['metadata']
                self.assertEqual(item['documentation']['model_configuration'], metadata['模型配置'])
                self.assertEqual(item['version']['upstream_revision'], metadata['上游revision'])
                self.assertEqual(item['documentation']['observation_fields']['元数据采集完整'], metadata['元数据采集完整'])
                # The active location has its own receipt; historical model
                # configuration/count observations remain in metadata.
                storage = actual_by_id[item['asset_id']].get('storage') or {}
                if storage.get('migration', {}).get('activated'):
                    current = next(observation for observation in storage['observations']
                                   if observation['path'] == item['current_path']
                                   and observation['host'] == storage['current_host'])
                    self.assertEqual(item['checks']['mtime_ns'], current.get('mtime_ns'))
                    self.assertEqual(item['checks']['observed_at'], current['observed_at'])
                else:
                    self.assertEqual(item['checks']['mtime_ns'], metadata['核验']['mtime_ns'])
                quantity = item['documentation']['quantity']
                self.assertEqual(quantity['primary_value'], str(actual_by_id[item['asset_id']]['file_count']))
                self.assertEqual(quantity['unit'], '目录直接文件数（不是权重数或样本数）')
                self.assertIn('catalog.file_count', quantity['source_field'])
                self.assertNotIn('count_unit', [gap['field'] for gap in item['gaps']])

    def test_registry_id_survives_rename_and_path_change_but_does_not_guess_new_identity(self):
        first = document([asset('same-source')])
        mapping, registry = inventory.build_mapping(first, now='2026-10-19T01:00:00Z')
        registry_before = copy.deepcopy(registry)
        changed = document([asset('same-source', '/data/datasets/new-location', name='Changed name'),
                            asset('different-source', '/data/datasets/new-location', name='Changed name')])
        second, updated = inventory.build_mapping(changed, registry, now='2026-10-19T02:00:00Z')
        self.assertEqual(registry, registry_before)
        self.assertEqual(mapping['items'][0]['registry_id'], second['items'][0]['registry_id'])
        self.assertNotEqual(second['items'][0]['registry_id'], second['items'][1]['registry_id'])
        self.assertEqual([item['path'] for item in updated['entries']['same-source']['path_history']],
                         ['/data/datasets/example', '/data/datasets/new-location'])
        empty, retired = inventory.build_mapping(document([]), updated, now='2026-10-19T03:00:00Z')
        self.assertEqual(empty['items'], [])
        self.assertFalse(retired['entries']['same-source']['active'])
        restored, _ = inventory.build_mapping(first, retired, now='2026-10-19T04:00:00Z')
        self.assertEqual(restored['items'][0]['registry_id'], mapping['items'][0]['registry_id'])

    def test_unknown_identity_version_access_maintainer_and_counts_are_not_invented(self):
        observed = asset(name='Example_20261019_v1', owner='filesystem-owner', status='verified',
                         size_bytes=0, file_count=0,
                         metadata={'原始台账': {'主要数量': '0', '计数单位': '全部文件，不等于样本',
                                               '快照时间': '2026-10-18'}})
        mapping, _ = inventory.build_mapping(document([observed]))
        item = mapping['items'][0]
        self.assertIsNone(item['checks']['exists'])
        self.assertIsNone(item['checks']['readable'])
        self.assertEqual(item['checks']['access'], 'unknown')
        self.assertEqual(item['checks']['filesystem_owner'], 'filesystem-owner')
        self.assertIsNone(item['documentation']['maintainer']['name'])
        self.assertEqual(item['version_state'], 'unconfirmed')
        self.assertIsNone(item['version']['release_id'])
        self.assertIn('v1', item['version']['naming_hints'])
        self.assertEqual(item['documentation']['quantity']['size_bytes'], 0)
        self.assertEqual(item['documentation']['quantity']['file_count'], 0)
        self.assertIsNone(item['documentation']['quantity']['record_count'])
        self.assertEqual(item['documentation']['quantity']['as_of'], '2026-10-18')
        self.assertIsNone(item['proposed_path']['path'])

    def test_registry_observation_time_does_not_advance_on_rebuild_and_legacy_labels_are_migrated(self):
        observed_at = '2026-10-18T19:46:35.062887+00:00'
        source = document([asset(verified_at=observed_at)])
        _, registered = inventory.build_mapping(source, now='2026-10-19T01:00:00Z')
        first_entry = registered['entries']['first']
        self.assertEqual(first_entry['path_history'][0]['first_observed_at'], observed_at)
        _, rebuilt = inventory.build_mapping(source, registered, now='2026-10-20T01:00:00Z')
        rebuilt_entry = rebuilt['entries']['first']
        self.assertEqual(rebuilt_entry['first_registered_at'], '2026-10-19T01:00:00Z')
        self.assertEqual(rebuilt_entry['last_registered_at'], '2026-10-20T01:00:00Z')
        self.assertEqual(rebuilt_entry['path_history'][0]['last_observed_at'], observed_at)
        legacy = copy.deepcopy(registered)
        legacy.pop('time_semantics')
        legacy['entries']['first']['path_history'] = [{
            'path': '/data/datasets/example', 'first_observed_at': '2026-10-19T01:00:00Z',
            'last_observed_at': '2026-10-19T02:00:00Z'}]
        _, migrated = inventory.build_mapping(source, legacy, now='2026-10-20T01:00:00Z')
        history = migrated['entries']['first']['path_history'][0]
        self.assertEqual(history['first_registered_at'], '2026-10-19T01:00:00Z')
        self.assertEqual(history['first_observed_at'], observed_at)
        self.assertEqual(history['last_observed_at'], observed_at)

    def test_outside_public_roots_and_cross_boundary_symlinks_are_rejected(self):
        for path in ('/data/users/member/secret', '/data/datasets-other/a', '/data/datasets/../users/a'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                inventory.build_mapping(document([asset(path=path)]))
        crossing = asset(metadata={'核验': {'realpath': '/home/member/secret'}})
        with self.assertRaises(ValueError):
            inventory.build_mapping(document([crossing]))
        cleaned, _ = inventory.build_mapping(document([asset(description='See /data/users/member/private',
                                                             metadata={'原始台账': {'备注': '/root/private'}})]))
        self.assertNotIn('/data/users', json.dumps(cleaned))
        self.assertNotIn('/root/private', json.dumps(cleaned))
        internal, _ = inventory.build_mapping(document([asset(path='/data/datasets/private/archive')]))
        self.assertEqual(internal['items'][0]['current_path'], '/data/datasets/private/archive')

    def test_cards_escape_source_markup_links_and_csv_formulas(self):
        source = asset(name='=HYPERLINK("unsafe")', description='<script>alert(1)</script>',
                       source_url='javascript:alert(1)', metadata={'原始台账': {'标注说明': '<img src=x onerror=alert(2)>'}})
        mapping, _ = inventory.build_mapping(document([source]))
        item = mapping['items'][0]
        rendered, markdown = inventory.make_card(item, 'Test group', mapping)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('<img src=x', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertNotIn('<script>', markdown)
        self.assertIn('&lt;script&gt;', rendered)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'mapping.csv'
            inventory.write_csv(mapping, output)
            with output.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]['display_name'], "'" + source['name'])

    def test_rebuild_preserves_registry_and_creates_both_card_formats_and_catalog_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            raw = json.dumps(document([asset('a'), asset('b')]), ensure_ascii=False).encode('utf-8')
            (root / 'data' / 'catalog.json').write_bytes(raw)
            (root / 'docs').mkdir()
            (root / 'docs' / 'resource-inventory.css').write_text('/* frontend-owned */', encoding='utf-8')
            with redirect_stdout(io.StringIO()):
                first, _ = inventory.main(root)
                second, _ = inventory.main(root)
            self.assertEqual([item['registry_id'] for item in first['items']], [item['registry_id'] for item in second['items']])
            self.assertEqual(second['catalog_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(second['catalog_generated_at'], '2026-10-18T19:46:35.062887+00:00')
            for item in second['items']:
                for key in ('card_url', 'card_markdown_url'):
                    self.assertTrue((root / item[key].lstrip('/')).is_file())
            page = (root / 'docs' / 'resource-inventory.html').read_text(encoding='utf-8')
            self.assertIn('/api/resource-mapping.csv', page)
            self.assertIn('<details', page)
            self.assertEqual((root / 'docs' / 'resource-inventory.css').read_text(encoding='utf-8'), '/* frontend-owned */')

    def test_reviewed_annotations_preserve_identity_observations_and_unknowns(self):
        observed_at = '2026-10-18T19:46:35.062887+00:00'
        source = document([asset(verified_at=observed_at, description='Original local description', file_count=7)])
        old_mapping, registry = inventory.build_mapping(source)
        annotations = {'entries': {'first': {
            'summary': 'Reviewed scientific purpose', 'background': 'Upstream background',
            'research_uses': ['Compare representations'], 'starter_notes': ['Check the local recipe'],
            'modalities': ['音频', '文本'], 'languages': ['中文', '英语'],
            'sources': [{'title': 'Official description', 'url': 'https://example.org/model', 'scope': 'Upstream only'}],
            'confidence': 'official_match', '_provenance': {'path': 'data/annotations/test.json', 'sha256': 'a' * 64, 'reviewed_at': '2026-10-19'}}}}
        mapped, _ = inventory.build_mapping(source, registry, annotations=annotations)
        item = mapped['items'][0]
        self.assertEqual(item['registry_id'], old_mapping['items'][0]['registry_id'])
        self.assertEqual(item['description'], 'Original local description')
        self.assertEqual(item['checks']['observed_at'], observed_at)
        self.assertEqual(item['documentation']['quantity']['file_count'], 7)
        self.assertIsNone(item['documentation']['maintainer']['name'])
        self.assertEqual(item['documentation']['license']['state'], 'unknown')
        self.assertIsNone(item['version']['release_id'])
        self.assertTrue({'logical_resource_id', 'version', 'license', 'maintainer'}.issubset({gap['field'] for gap in item['gaps']}))
        self.assertEqual(item['documentation']['research']['reviewed_at'], '2026-10-19')
        self.assertEqual(item['documentation']['research']['sources'][0]['label'], 'Official description')
        rendered, markdown = inventory.make_card(item, 'Group', mapped)
        self.assertLess(rendered.index('可以研究什么'), rendered.index('身份、位置与数量'))
        self.assertIn('本地来源证据', rendered)
        self.assertIn('Official description', markdown)
        self.assertIn('音频、文本', rendered)
        self.assertIn('中文、英语', rendered)
        self.assertIn('- 资料或方法模态：音频、文本', markdown)
        self.assertIn('- 语言背景：中文、英语', markdown)
        self.assertNotIn('[&quot;音频&quot;', rendered)
        self.assertNotIn('["音频",', markdown)

    def test_annotation_loader_validates_sources_ids_duplicates_and_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / 'data' / 'annotations'
            directory.mkdir(parents=True)
            path = directory / 'review.json'
            reviewed = {'schema_version': '1.0', 'reviewed_at': '2026-10-19', 'entries': {'first': {
                'summary': '<script>untrusted</script>', 'confidence': 'local_evidence',
                'evidence_basis': ['See /data/users/member/private'],
                'sources': [{'title': 'Source', 'url': 'https://example.org/model'}]}}}
            path.write_text(json.dumps(reviewed), encoding='utf-8')
            bundle = inventory.load_annotations(root, {'first'}, inventory.clean_metadata, inventory.safe_url)
            self.assertEqual(bundle['files'][0]['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertNotIn('/data/users', json.dumps(bundle))
            mapped, _ = inventory.build_mapping(document([asset()]), annotations=bundle)
            rendered, _ = inventory.make_card(mapped['items'][0], 'Group', mapped)
            self.assertNotIn('<script>', rendered)
            self.assertIn('&lt;script&gt;', rendered)
            with self.assertRaises(ValueError):
                inventory.load_annotations(root, {'different'}, inventory.clean_metadata, inventory.safe_url)
            (directory / 'duplicate.json').write_bytes(path.read_bytes())
            with self.assertRaises(ValueError):
                inventory.load_annotations(root, {'first'}, inventory.clean_metadata, inventory.safe_url)
            (directory / 'duplicate.json').unlink()
            reviewed['entries']['first']['sources'][0]['url'] = 'javascript:alert(1)'
            path.write_text(json.dumps(reviewed), encoding='utf-8')
            with self.assertRaises(ValueError):
                inventory.load_annotations(root, {'first'}, inventory.clean_metadata, inventory.safe_url)

    def test_non_talkbank_annotations_cover_every_real_entry_without_promoting_collections_to_weights(self):
        actual = json.loads((PROJECT / 'data' / 'catalog.json').read_text(encoding='utf-8'))
        authored = json.loads((PROJECT / 'data/annotations/local-and-models.json').read_text(encoding='utf-8'))
        talkbank_roots = ('/data/datasets/talkbank', '/data/share/datasets/talkbank')
        expected = {entry['id'] for entry in actual['assets']
                    if not any(entry['path'] == root or entry['path'].startswith(root + '/')
                               for root in talkbank_roots)}
        self.assertEqual(set(authored['entries']), expected)
        self.assertEqual(len(expected), 86)
        bundle = inventory.load_annotations(PROJECT, {entry['id'] for entry in actual['assets']}, inventory.clean_metadata, inventory.safe_url)
        mapped, _ = inventory.build_mapping(actual, annotations=bundle)
        self.assertTrue(all(item['documentation']['research']['contents'] and item['documentation']['research']['getting_started'] for item in mapped['items']))
        bge = next(item for item in mapped['items'] if 'models--BAAI--' in item['display_name'])
        self.assertEqual(bge['subtype'], 'directory_collection')
        self.assertIsNone(bge['documentation']['quantity']['file_count'])
        self.assertEqual(bge['documentation']['research']['confidence'], 'family_context')
        self.assertEqual(mapped['summary']['known_weights'], 7)

    def test_all_reviewed_explanations_cover_catalog_without_changing_local_evidence(self):
        actual = json.loads((PROJECT / 'data/catalog.json').read_text(encoding='utf-8'))
        expected = {entry['id'] for entry in actual['assets']}
        bundle = inventory.load_annotations(PROJECT, expected, inventory.clean_metadata, inventory.safe_url)
        self.assertEqual(set(bundle['entries']), expected)
        baseline, registry = inventory.build_mapping(actual, now='2026-10-19T01:00:00Z')
        enriched, _ = inventory.build_mapping(actual, registry, now='2026-10-19T02:00:00Z', annotations=bundle)
        before = {entry['asset_id']: entry for entry in baseline['items']}
        self.assertEqual(enriched['summary'], baseline['summary'])
        for item in enriched['items']:
            prior = before[item['asset_id']]
            for field in ('registry_id', 'current_path', 'checks', 'identity', 'version', 'evidence', 'description'):
                self.assertEqual(item[field], prior[field], (item['asset_id'], field))
            for field in ('source_fields', 'model_configuration', 'observation_fields', 'quantity', 'license', 'maintainer'):
                self.assertEqual(item['documentation'][field], prior['documentation'][field], (item['asset_id'], field))
            research = item['documentation']['research']
            for field in ('summary', 'background', 'research_uses', 'contents', 'getting_started', 'topics', 'reviewed_at'):
                self.assertTrue(research[field], (item['asset_id'], field))
            historical = (item.get('storage') or {}).get('historical') or {}
            self.assertEqual(research['local_observed_at'],
                             historical.get('observed_at') or item['checks']['observed_at'])
            self.assertEqual(research['local_observed_at'], prior['documentation']['research']['local_observed_at'])
            self.assertTrue({'logical_resource_id', 'version', 'license', 'maintainer'}.issubset({gap['field'] for gap in item['gaps']}))
        serialized = json.dumps(enriched, ensure_ascii=False)
        self.assertNotIn('/data/users', serialized)
        self.assertNotIn('/home/', serialized)


if __name__ == '__main__':
    unittest.main()
