"""Public-area scope and portable rebuild regression tests using synthetic evidence."""
import csv
import importlib.util
import io
import json
from contextlib import closing, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import export_catalog, export_csv, import_catalog, open_catalog

SPEC = importlib.util.spec_from_file_location('public_catalog_builder', Path(__file__).resolve().parents[1] / 'tools' / 'build_catalog.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def row(path, name='Public feature', server=builder.SERVER):
    return {'服务器': server, '名称': name, '绝对路径': path, '输入来源': 'historical-source',
            '源记录序号': '1', '数据类型': '派生特征', '语音方向': '任意业务用途',
            '目录字节': '0', '全部文件数': '', '原件路径': '/data/users/member/private-original',
            'ASR路径': '/home/member/transcripts', '实际采集或产生方式': '派生自 /data/users/member/session',
            '复用说明': '仅记录，不以许可或用途筛掉公共区内容。'}


def check(path):
    return {'exists': True, 'realpath': path, 'rmp_readable': False, 'owner': 'fixture-owner'}


def evidence():
    known = '/data/datasets/group/known'
    model = '/data/models/model-a'
    collections = [
        {'path': '/data/datasets', 'container': True},
        {'path': '/data/datasets/group', 'container': True},
        {'path': known, 'container': True},
        {'path': known + '/subject-001'},
        {'path': '/data/datasets/new-branch', 'container': True},
        {'path': '/data/datasets/new-branch/subject-001'},
        {'path': '/data/models', 'container': True},
        {'path': model},
        {'path': '/data/models/not-loaded-yet', 'container': True},
        {'path': '/data/models/not-loaded-yet/cache'},
        {'path': '/data/users/never-scan', 'container': True},
        {'path': '/data/datasets/escape-link'},
    ]
    paths = {item['path']: check(item['path']) for item in collections}
    paths['/data/datasets/escape-link']['realpath'] = '/data/users/member/secret'
    return {'generated_at': '2026-10-19T01:00:00Z', 'path_checks': paths,
            'models': [{'path': model, 'name': 'Model A', 'root': '/data/models', 'config': {
                'model_type': 'test', 'architectures': ['ExampleModel'], '_name_or_path': '/data/users/member/checkpoint'},
                'size_bytes': 10, 'file_count': 1, 'weight_file_count': 1, 'formats': ['.safetensors']}],
            'collections': collections, 'errors': [], 'method': 'public metadata fixture',
            'limits': {'public_roots': list(builder.PUBLIC_ROOTS), 'dataset_depth': 3}}


class PublicCatalogTests(unittest.TestCase):
    def test_scope_rejects_private_prefix_traversal_cross_server_and_cross_boundary_link(self):
        live = evidence()
        rows = [row('/data/datasets/group/known'), row('/data/models/model-a', 'A model'),
                row('/data/users/member/private'), row('/data/datasets/../users/member'),
                row('/data/datasets-other/resource'), row('/data/models-old/resource'),
                row('/data/datasets/group/known', server='学校训练服务器'), row('/data/datasets/escape-link')]
        filtered = builder.filter_source_rows(rows, live['path_checks'])
        self.assertEqual([item['绝对路径'] for item in filtered], ['/data/datasets/group/known', '/data/models/model-a'])
        for item in filtered:
            self.assertNotIn('原件路径', item)
            self.assertNotIn('ASR路径', item)
            self.assertEqual(item['实际采集或产生方式'], '')
        for value in ('/data/datasets/../users/a', '/data/datasets-other/a', '/data/models-old/a', '/data/users/a', '/home/a'):
            self.assertIsNone(builder.public_path(value), value)
        self.assertEqual(builder.public_path('/data/datasets/a/'), '/data/datasets/a')

    def test_frontier_collapses_uncovered_subtrees_without_swallowing_known_resources(self):
        live = evidence()
        rows = builder.filter_source_rows([row('/data/datasets/group/known')], live['path_checks'])
        document, report = builder.build_document(rows, live, 'test-hash')
        paths = {asset['path'] for asset in document['assets']}
        self.assertEqual(paths, {'/data/datasets/group/known', '/data/models/model-a',
                                 '/data/datasets/new-branch', '/data/models/not-loaded-yet'})
        self.assertEqual(report['discovered_entries_added'], 2)
        known = next(asset for asset in document['assets'] if asset['path'].endswith('/known'))
        self.assertEqual(known['kind'], 'dataset')
        self.assertEqual(known['metadata']['subtype'], 'feature')
        self.assertEqual(known['status'], 'restricted')
        self.assertEqual(known['size_bytes'], 0)
        for asset in document['assets']:
            self.assertIn(asset['kind'], {'dataset', 'model'})
            if asset['metadata']['subtype'] == 'directory_collection':
                self.assertIsNone(asset['size_bytes'])
                self.assertIsNone(asset['file_count'])

    def test_published_only_rebuild_and_database_exports_do_not_leak_private_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = root / 'data' / 'sources'
            sources.mkdir(parents=True)
            original = sources / 'assets-20261018.csv'
            rows = [row('/data/datasets/group/known'), row('/data/users/member/private')]
            with original.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            (sources / builder.LIVE_JSON).write_text(json.dumps(evidence()), encoding='utf-8')
            with redirect_stdout(io.StringIO()):
                first, first_report = builder.main(root)
            published_before = (sources / builder.PUBLIC_CSV).read_bytes()
            original.unlink()  # Only the synthetic fixture is removed, never real evidence.
            with redirect_stdout(io.StringIO()):
                rebuilt, rebuilt_report = builder.main(root)
            self.assertEqual(first, rebuilt)
            self.assertEqual(first_report, rebuilt_report)
            self.assertEqual(published_before, (sources / builder.PUBLIC_CSV).read_bytes())
            database = root / 'catalog.sqlite3'
            import_catalog(rebuilt, database)
            with closing(open_catalog(database)) as connection:
                outputs = [json.dumps(export_catalog(connection), ensure_ascii=False), export_csv(connection),
                           published_before.decode('utf-8-sig'), json.dumps(rebuilt_report)]
            for output in outputs:
                for forbidden in ('/data/users', '/home/', '/root/', '/data/datasets-other', '/data/datasets/../'):
                    self.assertNotIn(forbidden, output)
            self.assertEqual(rebuilt['sources'][0]['ref'], 'data/sources/' + builder.PUBLIC_CSV)


if __name__ == '__main__':
    unittest.main()
