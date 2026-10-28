import copy
import json
import unittest

from paperlib.evidence import resolve_evidence, source_context
from paperlib.library import Library, READING_FIELDS
import test_library as fixtures


class ReadingTests(unittest.TestCase):
    card = fixtures.LibraryTests.card

    def setUp(self):
        fixtures.LibraryTests.setUp(self)
        self.addCleanup(self.tmp.cleanup)

    def detailed_card(self):
        card = self.card()
        card['reading'] = {
            'takeaway': '通过数据选择提高模型质量。',
            'background': '论文关注数据对模型质量的作用。',
            'problem': '研究如何通过选择数据提高模型质量。',
            'method': '采用数据选择方法。\n\n这里保留段落结构。',
            'experiments': '作者报告了一项实验。',
            'results': '文中报告了模型质量改善。',
            'discussion': '该结论仅反映本文报告的实验。',
            'reproduction': '具体实现条件尚需在正文中核对。',
            'result_table': {'caption': '测试表格格式', 'columns': ['方法', '结果'], 'rows': [['数据选择', '改善']]},
            'resources': [{'label': '测试用资源', 'url': 'https://example.org/project?version=1#code', 'kind': 'code'}],
        }
        card['evidence'].extend({'field': 'reading.' + key, 'page': 1, 'quote': self.text.strip()}
                                for key in card['reading'])
        return card

    def test_optional_reading_keeps_legacy_cards_valid(self):
        card = self.card()
        clean = self.lib.validate_card(self.id, card)
        self.assertEqual(clean['reading'], {})
        self.assertEqual(clean['schema_version'], 1)
        card['reading'] = {'background': ' \n ', 'resources': [], 'result_table': None}
        self.assertEqual(self.lib.validate_card(self.id, card)['reading'], {})

    def test_full_reading_survives_commit_disk_and_recuration(self):
        card = self.detailed_card()
        self.lib.commit(self.id, self.card())
        original_pdf = self.lib.record(self.id)['pdf']
        self.lib.edit(self.id, {'notes': '保留已有笔记', 'favorite': True})
        self.lib.commit(self.id, card)
        record = Library(self.root).record(self.id)
        self.assertEqual(record['card']['reading'], card['reading'])
        self.assertEqual(record['pdf'], original_pdf)
        self.assertEqual(record['notes'], '保留已有笔记')
        self.assertTrue(record['favorite'])
        saved = json.loads(self.lib.pdf_path(self.id).with_name('card.json').read_text())
        self.assertEqual(saved['reading'], card['reading'])

    def test_every_nonempty_reading_field_requires_matching_evidence(self):
        for key in READING_FIELDS:
            with self.subTest(field=key):
                card = self.detailed_card()
                card['evidence'] = [entry for entry in card['evidence'] if entry['field'] != 'reading.' + key]
                with self.assertRaisesRegex(ValueError, 'reading\\.' + key):
                    self.lib.commit(self.id, card)
                self.assertTrue(self.source.exists())
                self.assertIsNone(self.lib.record(self.id)['card'])

    def test_reading_source_id_resolves_without_special_worker_changes(self):
        card = self.detailed_card()
        card['evidence'] = [{'field': entry['field'], 'source_id': 'p1-b1'} for entry in card['evidence']]
        _, sources, _ = source_context(self.text)
        clean = self.lib.validate_card(self.id, resolve_evidence(card, sources))
        self.assertEqual(clean['reading']['method'], card['reading']['method'])
        self.assertEqual(clean['evidence'][-1]['field'], 'reading.resources')
        self.assertIn('source_id', card['evidence'][-1])

    def test_reading_quotes_still_have_to_exist_on_cited_page(self):
        card = self.detailed_card()
        card['evidence'][-1]['quote'] = 'This invented resource link is absent from the source.'
        with self.assertRaisesRegex(ValueError, 'reading.resources'):
            self.lib.validate_card(self.id, card)

    def test_invalid_sections_and_limits_are_rejected(self):
        for reading in [None, [], 'text', {'unknown_section': 'text'}, {'takeaway': 'a' * 401},
                        {'method': 'a' * 8001}, {'results': ['not a string']}, {'resources': None}]:
            with self.subTest(reading=str(reading)[:60]):
                card = self.card()
                card['reading'] = reading
                with self.assertRaisesRegex(ValueError, 'reading'):
                    self.lib.validate_card(self.id, card)

    def test_result_table_rejects_nonrectangular_and_oversized_data(self):
        base = self.detailed_card()['reading']['result_table']
        invalid = [None, [], {'columns': ['one'], 'rows': []}, {'columns': ['a'] * 9, 'rows': []},
                   {**base, 'columns': ['a', ' ']}, {**base, 'rows': [['one']]},
                   {**base, 'rows': [[1, 2]]}, {**base, 'rows': [['a', 'b']] * 31},
                   {**base, 'rows': [['a', 'b' * 1501]]}, {**base, 'caption': 'a' * 1001}]
        for table in invalid[1:]:  # null explicitly means no result table.
            with self.subTest(table=str(table)[:80]):
                card = self.detailed_card()
                card['reading']['result_table'] = table
                with self.assertRaisesRegex(ValueError, 'result_table'):
                    self.lib.validate_card(self.id, card)

    def test_resource_urls_reject_unsafe_or_malformed_addresses(self):
        urls = ['javascript:alert(1)', '//example.org/code', 'file:///tmp/source',
                'https://alice:password@example.org', 'https://@example.org',
                'https://example.org:70000', 'https://example.org:0', 'https://example.org:',
                'https://example.org/not a path', 'https://example.org/\ncode',
                'https://example.org\\@another.org', 'https://example.org/%ZZ',
                'https://', 'https://-bad.example.org', 'https://example..org', 'https://999.999.999.999',
                'https://[::not-an-ip]/', 'https://example.org' + '/' * 2048]
        for url in urls:
            with self.subTest(url=url[:80]):
                card = self.detailed_card()
                card['reading']['resources'][0]['url'] = url
                with self.assertRaisesRegex(ValueError, 'resources.url'):
                    self.lib.validate_card(self.id, card)

    def test_valid_resource_addresses_are_preserved_without_network_verification(self):
        for url in ['https://example.org/path?q=one%20two#section', 'http://localhost:8080/code',
                    'https://[2001:db8::1]/data', 'https://例子.测试/代码']:
            with self.subTest(url=url):
                card = self.detailed_card()
                card['reading']['resources'][0]['url'] = url
                clean = self.lib.validate_card(self.id, card)
                self.assertEqual(clean['reading']['resources'][0]['url'], url)

    def test_resource_structure_and_count_limits(self):
        resource = self.detailed_card()['reading']['resources'][0]
        invalid = [[resource] * 13, ['https://example.org'], [{**resource, 'label': ''}],
                   [{**resource, 'label': 'a' * 161}], [{**resource, 'kind': 'script'}],
                   [{**resource, 'url': None}]]
        for resources in invalid:
            with self.subTest(resources=str(resources)[:80]):
                card = self.detailed_card()
                card['reading']['resources'] = resources
                with self.assertRaisesRegex(ValueError, 'resources'):
                    self.lib.validate_card(self.id, card)

    def test_expanded_evidence_limit_remains_bounded(self):
        card = self.detailed_card()
        card['evidence'] += [copy.deepcopy(card['evidence'][0])] * (100 - len(card['evidence']))
        self.assertEqual(len(self.lib.validate_card(self.id, card)['evidence']), 100)
        card['evidence'].append(copy.deepcopy(card['evidence'][0]))
        with self.assertRaisesRegex(ValueError, '100'):
            self.lib.validate_card(self.id, card)


if __name__ == '__main__':
    unittest.main()
