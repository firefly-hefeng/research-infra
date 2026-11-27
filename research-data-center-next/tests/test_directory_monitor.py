import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.name != 'posix':
    raise unittest.SkipTest('Storage monitor requires POSIX file locking and ownership')
from tools.monitor_directory import run

class MonitorTests(unittest.TestCase):
    def test_changes_privacy_and_no_link_traversal(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve(); datasets=root/'datasets';models=root/'models'
            datasets.mkdir();models.mkdir();state=root/'private'
            folder=datasets/'example';folder.mkdir()
            report=folder/'README.md';report.write_text('test')
            (folder/'outside').symlink_to('/etc',target_is_directory=True)
            roots={'dataset':datasets,'model':models}
            self.assertGreater(run(roots,state)['changes'],0)
            self.assertEqual(run(roots,state)['changes'],0)
            snapshot=json.loads((state/'latest.json').read_text())
            self.assertNotIn('dataset/example/outside/passwd',snapshot['entries'])
            self.assertEqual((state/'changes.jsonl').stat().st_mode & 0o777,0o600)
            report.write_text('updated')
            self.assertEqual(run(roots,state)['changes'],1)
            before=(state/'latest.json').read_bytes()
            with self.assertRaises(ValueError):run(roots,state,limit=1)
            self.assertEqual((state/'latest.json').read_bytes(),before)
            self.assertTrue((folder/'outside').is_symlink())
            with self.assertRaises(ValueError):run(roots,datasets/'logs')

    def test_unsafe_state_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve();data=root/'data';data.mkdir();state=root/'private';state.mkdir(mode=0o700)
            secret=root/'secret';secret.write_text('preserve')
            (state/'changes.jsonl').symlink_to(secret)
            with self.assertRaises(ValueError):run({'dataset':data},state)
            self.assertEqual(secret.read_text(),'preserve')

if __name__=='__main__':unittest.main()

class ResourceLogTests(unittest.TestCase):
    def test_resource_logs_baseline_updates_removal_and_separation(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve()
            datasets, models, state = root/'datasets', root/'models', root/'private'
            datasets.mkdir(); models.mkdir()
            resource = datasets/'example'; resource.mkdir()
            (resource/'README.md').write_text('Initial description')
            roots = {'dataset': datasets, 'model': models}
            first = run(roots, state)
            self.assertEqual(first['resource_updates'], {'datasets': 1, 'models': 0})
            def history(name):
                return [json.loads(line) for line in (state/(name+'-updates.jsonl')).read_text().splitlines()]
            self.assertEqual(history('datasets')[0]['action'], 'baseline')
            run(roots, state)
            self.assertEqual(len(history('datasets')), 1)
            (resource/'README.md').write_text('Updated explanation with more information')
            (resource/'data.bin').write_bytes(b'demo')
            (models/'model-a').mkdir()
            run(roots, state)
            event = history('datasets')[-1]
            self.assertEqual(event['action'], 'updated')
            self.assertEqual(event['before']['file_count'], 1)
            self.assertEqual(event['after']['file_count'], 2)
            self.assertIsNone(event['version']); self.assertIsNone(event['submitted_by'])
            self.assertEqual(history('models')[-1]['action'], 'added')
            (models/'model-a').rmdir()
            run(roots, state)
            self.assertEqual(history('models')[-1]['action'], 'removed')
            self.assertIn('更新资源', (state/'datasets-updates.md').read_text())
            for name in ('datasets-updates.md','datasets-updates.jsonl','models-updates.md','models-updates.jsonl'):
                self.assertEqual((state/name).stat().st_mode & 0o777, 0o600)

    def test_resource_log_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve(); data = root/'datasets'; data.mkdir()
            state = root/'state'; state.mkdir(mode=0o700)
            secret = root/'secret'; secret.write_text('unchanged')
            (state/'datasets-updates.md').symlink_to(secret)
            with self.assertRaises(ValueError): run({'dataset': data}, state)
            self.assertEqual(secret.read_text(), 'unchanged')
