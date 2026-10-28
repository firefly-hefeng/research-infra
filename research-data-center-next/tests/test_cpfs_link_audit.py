import contextlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'cpfs_link_audit', Path(__file__).resolve().parents[1] / 'tools' / 'cpfs_link_audit.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def link(relative, target, root='/data/datasets'):
    return dict(kind='symlink', root=root, relative_path=relative, target=target)


class LinkAuditTests(unittest.TestCase):
    def test_same_library_relative_link(self):
        r = audit.audit_rows([link('corpus/refs/audio', '../content/audio.wav')])
        self.assertTrue(r['passed'])
        self.assertEqual(r['symlinks'][0]['after']['path'],
                         '/data/share/datasets/corpus/content/audio.wav')

    def test_cross_library_relative_link(self):
        r = audit.audit_rows([link('data', '../datasets/corpus', '/data/models')])
        self.assertTrue(r['passed'])
        self.assertEqual(r['symlinks'][0]['after']['path'],
                         '/data/share/datasets/corpus')

    def test_relative_escape_changes_external_target(self):
        r = audit.audit_rows([link('outside', '../../outside/resource')])
        self.assertFalse(r['passed'])
        self.assertEqual(r['counts']['relative_relocation_hazards'], 1)
        self.assertEqual(r['symlinks'][0]['old_lexical_target'], '/outside/resource')
        self.assertEqual(r['symlinks'][0]['new_lexical_target'], '/data/outside/resource')

    def test_existing_absolute_external_target_is_not_a_failure_or_followed(self):
        with patch('os.stat', side_effect=AssertionError('must not touch target')):
            r = audit.audit_rows([link('external', '/home/member/private/old.wav')])
        self.assertTrue(r['passed'])
        self.assertEqual(r['counts']['absolute_external_node_dependencies'], 1)
        self.assertNotIn('before', r['symlinks'][0])

    def test_internal_absolute_link_requires_compatibility_alias(self):
        r = audit.audit_rows([link('model', '/data/models/weights/model.bin')])
        self.assertTrue(r['passed'])
        self.assertEqual(r['counts']['absolute_internal_alias_dependencies'], 1)
        self.assertEqual(r['symlinks'][0]['after']['path'],
                         '/data/share/models/weights/model.bin')

    def test_known_prefix_link_chain(self):
        r = audit.audit_rows([link('alias', 'content'), link('entry', 'alias/a.wav')])
        self.assertTrue(r['passed'])
        self.assertEqual(r['symlinks'][1]['after']['path'],
                         '/data/share/datasets/content/a.wav')

    def test_preexisting_cycle_does_not_become_migration_blocker(self):
        r = audit.audit_rows([link('a', 'b'), link('b', 'a')])
        self.assertTrue(r['passed'])
        self.assertEqual(r['counts']['preexisting_cycles'], 2)
        self.assertEqual(r['counts']['new_cycles'], 0)

    def test_preexisting_internal_unknown_target_is_not_called_broken(self):
        r = audit.audit_rows([link('unknown', 'not-in-symlink-dictionary.wav')])
        self.assertTrue(r['passed'])
        self.assertEqual(r['symlinks'][0]['before']['status'],
                         'internal_availability_unchecked')

    def test_existing_chain_to_external_target_does_not_fail(self):
        r = audit.audit_rows([link('a', 'b'), link('b', '/outside/existing')])
        self.assertTrue(r['passed'])
        self.assertEqual(r['symlinks'][0]['after']['status'], 'external_unchecked')

    def test_preexisting_external_path_can_acquire_a_new_cycle_in_published_root(self):
        r = audit.audit_rows([link('a', '/data/share/datasets/a')])
        self.assertFalse(r['passed'])
        self.assertEqual(r['counts']['new_cycles'], 1)

    def test_alias_can_introduce_a_new_depth_limit(self):
        r = audit.audit_rows([link('a', '/data/datasets/b'),
                              link('b', '/data/datasets/c'), link('c', 'content')],
                             max_links=3)
        self.assertFalse(r['passed'])
        self.assertGreater(r['counts']['new_depth_limits'], 0)

    def test_invalid_and_duplicate_records_make_audit_incomplete(self):
        r = audit.audit_rows([link('../escape', 'target'), link('a', 'content'),
                              link('a', 'other')])
        self.assertFalse(r['complete'])
        self.assertFalse(r['passed'])
        self.assertEqual(r['counts']['errors'], 2)

    def test_cli_gzip_report_private_and_stdout_counts_only(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest = directory / 'source-files.jsonl.gz'
            report = directory / 'private' / 'links.json'
            with gzip.open(manifest, 'wt', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(kind='file', relative_path='ignored')) + '\n')
                stream.write(json.dumps(link('secret-link', '/private/sensitive-target')) + '\n')
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = audit.main(['--manifest', str(manifest), '--output', str(report)])
            self.assertEqual(code, 0)
            self.assertNotIn('secret-link', output.getvalue())
            self.assertNotIn('sensitive-target', output.getvalue())
            data = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(data['counts']['manifest_rows'], 2)
            self.assertEqual(data['symlinks'][0]['target'], '/private/sensitive-target')
            self.assertEqual(data['source_manifest_sha256'], audit.manifest_digest(manifest))
            if os.name == 'posix':
                self.assertEqual(report.stat().st_mode & 0o777, 0o600)

    def test_parse_failure_replaces_stale_success_report(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest = directory / 'broken.jsonl'
            report = directory / 'report.json'
            manifest.write_text('{not valid json', encoding='utf-8')
            report.write_text('{"passed":true}', encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                code = audit.main(['--manifest', str(manifest), '--output', str(report)])
            self.assertEqual(code, 2)
            self.assertFalse(json.loads(report.read_text(encoding='utf-8'))['passed'])


if __name__ == '__main__':
    unittest.main()
