"""Research navigation must cover records, not double-count shared paths."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rdc_guide_test', ROOT/'tools/build_research_guide.py')
guide = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guide)


class ResearchGuideTests(unittest.TestCase):
    def setUp(self):
        self.mapping = json.loads((ROOT/'data/resource-mapping.json').read_text(encoding='utf-8'))

    def test_each_record_has_one_primary_category_with_honest_path_counts(self):
        before = copy.deepcopy(self.mapping)
        result = guide.build_guide(self.mapping)
        members = [entry for category in result['categories'] for entry in category['asset_ids']]
        self.assertEqual(set(members), {item['asset_id'] for item in self.mapping['items']})
        self.assertEqual(len(members), len(set(members)))
        features = next(category for category in result['categories'] if category['id'] == 'reusable-features')
        self.assertEqual(features['counts'], {'records': 10, 'unique_paths': 3})
        self.assertEqual(self.mapping, before)

    def test_new_group_or_orphan_record_requires_editorial_review(self):
        self.mapping['groups'].append({'key': 'unexpected/group', 'id': 'new'})
        with self.assertRaises(ValueError):
            guide.build_guide(self.mapping)
        self.mapping['groups'].pop()
        self.mapping['items'][0]['group_id'] = 'not-in-navigation'
        with self.assertRaises(ValueError):
            guide.build_guide(self.mapping)


if __name__ == '__main__':
    unittest.main()
