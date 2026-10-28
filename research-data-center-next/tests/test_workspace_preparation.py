"""Prepare-workspace rehearsal with real metadata builders, only temporary paths.

Never calls activate(), systemctl, a mount tool, a production path or source data.
The installed application/code/state constants and run() are fixture substitutes.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from catalog import import_catalog
from tests.test_shared_management import load_operator
from tools import build_catalog, build_inventory, build_research_guide, path_migration

PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux'), 'Ownership rehearsal uses a temporary Linux filesystem')
class WorkspacePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rdc-workspace-preparation-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app, self.code, self.local = (self.root / name for name in ('existing-app', 'verified-code', 'local-runtime'))
        self.workspace, self.state = self.local / 'workspace', self.local / 'state'
        self.operator = load_operator()
        for name, value in {'APP': self.app, 'CODE': self.code, 'LOCAL': self.local,
                            'WORKSPACE': self.workspace, 'STATE': self.state, 'BACKUP': self.root / 'rollback-app',
                            'UID': os.getuid(), 'GID': os.getgid()}.items():
            patch = mock.patch.object(self.operator, name, value)
            patch.start(); self.addCleanup(patch.stop)
        (self.app / 'var').mkdir(parents=True)
        (self.app / 'var' / 'private-sentinel').write_bytes(b'private stays local')
        (self.app / 'data' / 'sources').mkdir(parents=True)
        (self.code / 'data' / 'sources').mkdir(parents=True)
        (self.code / 'docs').mkdir()
        (self.code / 'docs' / 'resource-inventory.css').write_text('/* fixture css */', encoding='utf-8')
        self.baseline_raw = (PROJECT / 'data/sources/catalog-pre-migration.json').read_bytes()
        self.baseline = json.loads(self.baseline_raw)
        self.registry = json.loads((PROJECT / 'data/resource-registry.json').read_text(encoding='utf-8'))
        planned = path_migration.planned_manifest(self.baseline, self.registry,
                    'data/sources/catalog-pre-migration.json', hashlib.sha256(self.baseline_raw).hexdigest(), 'fixture-workspace')
        self.live = copy.deepcopy(planned)
        self.live['state'] = 'switched'
        observations = [{'host': 'fixture-host', 'path': path, 'realpath': path,
                         'observed_at': '2026-10-27T09:00:00Z', 'account': 'rmp', 'exists': True,
                         'readable': True, 'kind': 'directory', 'owner': 'root', 'uid': 0, 'gid': 0, 'mode': '0o755'}
                        for path in sorted({entry['to_path'] for entry in planned['entries']})]
        self.objects = []
        for phase in ('copy', 'verification', 'cutover'):
            raw = ('Synthetic ' + phase + ' evidence; never a live migration receipt').encode()
            digest = hashlib.sha256(raw).hexdigest()
            reference = 'data/migration-evidence/objects/' + digest + '.json'
            destination = self.app / reference
            destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(raw)
            self.objects.append(reference)
            self.live['receipts'][phase] = {'status': 'passed', 'host': 'fixture-host',
                'observed_at': '2026-10-27T09:00:00Z', 'evidence': {'ref': reference, 'sha256': digest}}
        self.live['receipts']['verification'].update(strategy='synthetic fixture', errors=[], observations=observations)
        self.live['receipts']['cutover'].update(
            mount={'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'},
            aliases=[{'path': old, 'target': new, 'kind': 'symlink', 'verified': True}
                     for old, new in path_migration.ROOT_PAIRS.values()])
        projected = path_migration.project_catalog(self.baseline, self.live, observations)
        for destination, migration, catalog in ((self.code, planned, self.baseline), (self.app, self.live, projected)):
            (destination / 'data/sources/catalog-pre-migration.json').write_bytes(self.baseline_raw)
            for name, data in [('path-migration.json', migration), ('catalog.json', catalog),
                               ('resource-registry.json', self.registry)]:
                (destination / 'data' / name).write_text(json.dumps(data), encoding='utf-8')
        self.package_manifest = {path.relative_to(self.code).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in self.code.rglob('*') if path.is_file()}
        self.calls = []
        self.force_legacy = False

    def local_run(self, arguments, user=None):
        self.assertEqual(user, 'rmp')
        script = Path(arguments[1])
        self.assertTrue(script.is_relative_to(self.workspace))
        self.calls.append(script.name)
        with redirect_stdout(io.StringIO()):
            if script.name == 'build_catalog.py':
                build_catalog.main(self.workspace)
                if self.force_legacy:
                    (self.workspace / 'data/catalog.json').write_bytes(self.baseline_raw)
            elif script.name == 'build_inventory.py':
                build_inventory.main(self.workspace)
            elif script.name == 'build_research_guide.py':
                mapping = json.loads((self.workspace / 'data/resource-mapping.json').read_text())
                (self.workspace / 'data/research-guide.json').write_text(json.dumps(build_research_guide.build_guide(mapping)))
            elif script.name == 'catalog.py':
                import_catalog(json.loads((self.workspace / 'data/catalog.json').read_text()),
                               self.workspace / 'var/catalog.sqlite3')
            elif script.name == 'package_release.py':
                # Keep packaging out of this fixture; capture exactly the live
                # metadata the real packager receives after the identity gate.
                self.packaged = json.loads((self.workspace / 'data/catalog.json').read_text())
            else:
                self.assertEqual(script.name, 'check_docs.py')

    def prepare(self):
        with mock.patch.object(self.operator, 'run', side_effect=self.local_run):
            return self.operator.prepare_workspace(self.package_manifest)

    def test_latest_switch_evidence_overrides_stale_candidate_without_changing_228_ids(self):
        original = (self.app / 'data/catalog.json').read_bytes()
        self.assertEqual(self.prepare(), 228)
        after = json.loads((self.workspace / 'data/catalog.json').read_text())
        before = json.loads(original)
        self.assertEqual({a['id']: a['path'] for a in before['assets']}, {a['id']: a['path'] for a in after['assets']})
        self.assertEqual((self.app / 'data/catalog.json').read_bytes(), original)
        self.assertTrue(all(a['path'].startswith('/data/share/') for a in self.packaged['assets']))
        for reference in self.objects:
            self.assertEqual((self.workspace / reference).read_bytes(), (self.app / reference).read_bytes())
        self.assertEqual((self.workspace / 'var/private-sentinel').read_bytes(), b'private stays local')
        self.assertFalse((self.code / 'var').exists())
        self.assertEqual((self.state.stat().st_mode & 0o777), 0o700)
        registry = json.loads((self.workspace / 'data/resource-registry.json').read_text())
        self.assertEqual({key: value['registry_id'] for key, value in self.registry['entries'].items()},
                         {key: value['registry_id'] for key, value in registry['entries'].items()})

    def test_bad_live_object_hash_stops_before_running_any_builder(self):
        (self.app / self.objects[0]).write_bytes(b'tampered synthetic evidence')
        with self.assertRaisesRegex(RuntimeError, 'Evidence hash mismatch'):
            self.prepare()
        self.assertEqual(self.calls, [])

    def test_builder_legacy_regression_is_stopped_before_import_or_packaging(self):
        self.force_legacy = True
        original = (self.app / 'data/catalog.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'changed existing resource IDs or migrated paths'):
            self.prepare()
        self.assertNotIn('catalog.py', self.calls)
        self.assertNotIn('package_release.py', self.calls)
        self.assertEqual((self.app / 'data/catalog.json').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
