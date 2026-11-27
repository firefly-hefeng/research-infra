import datetime as dt
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from compute_history import DB_NAME, read_reports, update


def sample(at, *, status='online', gpu=25):
    return {'schema_version': '1.0', 'generated_at': at.isoformat(), 'servers': [{
        'id': 'server-47', 'status': status, 'attempted_at': (at - dt.timedelta(seconds=5)).isoformat(),
        'observed_at': at.isoformat(), 'cpu': {'usage_percent': 40},
        'gpus': [{'index': 0, 'uuid': 'GPU-0', 'utilization_percent': gpu,
                  'memory_used_bytes': 1024, 'processes': [{'user': 'private-user'}]}],
        'disks': [{'mount': '/data/share', 'used_percent': 80},
                  {'mount': '/data/share_cold', 'filesystem': 'ossfs', 'used_percent': 90}],
    }]}


class ComputeHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.state = Path(temp.name)
        self.db = self.state / DB_NAME

    def test_capture_deduplicates_and_excludes_missing_metrics(self):
        at = dt.datetime.fromisoformat('2026-11-11T01:15:00+08:00')
        original = sample(at)
        self.assertEqual(update(self.db, original, at), 1)
        self.assertEqual(update(self.db, original, at + dt.timedelta(seconds=20)), 0)
        later = at + dt.timedelta(minutes=5)
        self.assertEqual(update(self.db, original, later), 0)
        self.assertEqual(update(self.db, sample(later, status='unreachable'), later), 1)
        last = later + dt.timedelta(minutes=10)
        self.assertEqual(update(self.db, sample(last, gpu=0), last, force=True), 1)
        report = read_reports(self.state, 'week', '2026-11-09')
        server = report['servers'][0]
        self.assertEqual(report['expected_slots'], 4)
        self.assertEqual(server['observed_slots'], 3)
        self.assertEqual(server['status']['unreachable'], 1)
        self.assertEqual(server['gpu']['mean'], 12.5)
        self.assertEqual(server['gpu_active_percent'], 50)
        self.assertEqual(server['cpu']['samples'], 2)
        self.assertEqual(server['disks'][0]['mount'], '/data/share')
        self.assertEqual(len(server['disks']), 1)
        self.assertIsNone(report['servers'][1]['gpu']['mean'])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertNotIn('private-user', json.dumps(db.execute('SELECT data FROM samples').fetchall()))

    def test_local_week_and_month_finalize_and_survive_raw_pruning(self):
        first = dt.datetime.fromisoformat('2026-11-30T23:55:00+08:00')
        december = first + dt.timedelta(minutes=5)
        monday = dt.datetime.fromisoformat('2026-12-07T00:00:00+08:00')
        for at in (first, december, monday):
            update(self.db, sample(at), at)
        november = read_reports(self.state, 'month', '2026-11-01')
        self.assertTrue(november['complete'])
        self.assertEqual(november['end'], '2026-11-30')
        self.assertEqual(november['expected_slots'], 1)
        self.assertEqual(november['days'][0]['date'], '2026-11-30')
        week = read_reports(self.state, 'week', '2026-11-30')
        self.assertTrue(week['complete'])
        self.assertEqual(week['expected_slots'], 1729)
        self.assertEqual(week['servers'][0]['observed_slots'], 2)
        self.assertFalse(read_reports(self.state, 'week', '2026-12-07')['complete'])
        after = monday + dt.timedelta(days=401)
        update(self.db, {}, after)
        self.assertEqual(read_reports(self.state, 'month', '2026-11-01'), november)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 0)

    def test_missing_state_is_read_only(self):
        self.assertEqual(read_reports(self.state)['reports'], [])
        self.assertIsNone(read_reports(self.state, 'week', '2026-11-09'))
        self.assertFalse(self.db.exists())
