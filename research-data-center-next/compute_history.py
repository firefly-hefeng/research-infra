"""Sample the saved monitor snapshot and publish calendar resource reports."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import datetime as dt
import json
from pathlib import Path
import sqlite3

from platform_data import SERVERS, metrics, now, read_public_json, stamp

INTERVAL = 300
MAX_AGE = 150
ACTIVE_THRESHOLD = 10
RAW_RETENTION_DAYS = 400
SHANGHAI = dt.timezone(dt.timedelta(hours=8))
KINDS = ('week', 'month')
DB_NAME = 'compute-history.sqlite3'
SCHEMA = """
CREATE TABLE IF NOT EXISTS tracking (started INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS samples (
    slot INTEGER NOT NULL, server TEXT NOT NULL, attempted REAL NOT NULL,
    status TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (slot, server), UNIQUE (server, attempted)
);
CREATE TABLE IF NOT EXISTS reports (
    kind TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
    generated INTEGER NOT NULL, complete INTEGER NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (kind, start)
);
"""


def timestamp(value):
    valid = stamp(value)
    return dt.datetime.fromisoformat(valid.replace('Z', '+00:00')).timestamp() if valid else None


def slot_at(at):
    return int(at.timestamp()) // INTERVAL * INTERVAL


def local_date(seconds):
    return dt.datetime.fromtimestamp(seconds, SHANGHAI).date()


def midnight(date):
    return int(dt.datetime.combine(date, dt.time(), SHANGHAI).timestamp())


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, SHANGHAI).isoformat()


def period_start(kind, date):
    return date - dt.timedelta(days=date.weekday()) if kind == 'week' else date.replace(day=1)


def next_period(kind, start):
    return start + dt.timedelta(days=7) if kind == 'week' else (start + dt.timedelta(days=32)).replace(day=1)


def sample_rows(snapshot, at):
    generated = timestamp(snapshot.get('generated_at'))
    if (snapshot.get('schema_version') != '1.0' or generated is None
            or not -5 <= at.timestamp() - generated <= MAX_AGE):
        return
    permitted = {server['id'] for server in SERVERS}
    for row in snapshot.get('servers', []):
        server, status = row.get('id'), row.get('status')
        attempted = timestamp(row.get('attempted_at'))
        if (server not in permitted or status not in ('online', 'partial', 'unreachable')
                or attempted is None or not 0 <= generated - attempted <= MAX_AGE):
            continue
        data = {}
        if status != 'unreachable':
            observed = timestamp(row.get('observed_at'))
            if observed is None or not attempted <= observed <= generated:
                continue
            values = metrics(row)
            data = {
                'cpu': values['cpu']['usage_percent'],
                'memory': values['memory']['used_percent'],
                'gpus': [[gpu['uuid'] or str(gpu['index']), gpu['index'], gpu['utilization_percent'],
                          gpu['memory_used_bytes']] for gpu in values['gpus'] or []],
                'disks': [[disk['mount'], disk['used_percent']] for disk in values['disks']
                          if disk['used_percent'] is not None],
            }
        yield slot_at(at), server, attempted, status, json.dumps(data, separators=(',', ':'))


class Series:
    def __init__(self):
        self.samples = self.total = 0
        self.peak = self.latest = None

    def add(self, value):
        if value is not None:
            self.samples += 1
            self.total += value
            self.peak = value if self.peak is None else max(value, self.peak)
            self.latest = value

    def result(self):
        return {'samples': self.samples, 'mean': round(self.total / self.samples, 2) if self.samples else None,
                'peak': self.peak, 'latest': self.latest}


class Host:
    def __init__(self):
        self.status = Counter()
        self.cpu, self.memory, self.gpu, self.active = (Series() for _ in range(4))
        self.cards, self.disks = {}, defaultdict(Series)

    def add(self, status, data, detail=False):
        self.status[status] += 1
        self.cpu.add(data.get('cpu'))
        self.memory.add(data.get('memory'))
        for identity, index, utilization, memory in data.get('gpus', []):
            self.gpu.add(utilization)
            active = None if utilization is None else 100 * (utilization >= ACTIVE_THRESHOLD)
            self.active.add(active)
            if detail:
                if identity not in self.cards:
                    self.cards[identity] = [index, Series(), Series(), Series()]
                card = self.cards[identity]
                card[0] = index
                card[1].add(utilization)
                card[2].add(active)
                card[3].add(memory)
        if detail:
            for mount, usage in data.get('disks', []):
                self.disks[mount].add(usage)

    def result(self):
        return {'observed_slots': sum(self.status.values()), 'status': dict(self.status),
                'cpu': self.cpu.result(), 'memory': self.memory.result(), 'gpu': self.gpu.result(),
                'gpu_active_percent': self.active.result()['mean']}

    def detail(self):
        return {**self.result(), 'cards': [
            {'index': index, 'gpu': gpu.result(), 'gpu_active_percent': active.result()['mean'],
             'vram_bytes': memory.result()} for index, gpu, active, memory in sorted(
                 self.cards.values(), key=lambda card: card[0])],
            'disks': [{'mount': mount, **series.result()} for mount, series in sorted(self.disks.items())]}


def summarize(db, kind, start, end, first, current_slot, at):
    lower, upper = max(midnight(start), first), min(midnight(end), current_slot + INTERVAL)
    hosts, daily = defaultdict(Host), defaultdict(Host)
    for slot, server, status, payload in db.execute(
            'SELECT slot, server, status, data FROM samples WHERE slot >= ? AND slot < ? ORDER BY slot, server',
            (lower, upper)):
        data = json.loads(payload)
        hosts[server].add(status, data, detail=True)
        daily[local_date(slot), server].add(status, data)

    names = {server['id']: server['name'] for server in SERVERS}
    for server in hosts:
        names.setdefault(server, server)
    days = []
    day = local_date(lower)
    while midnight(day) < upper:
        tomorrow = day + dt.timedelta(days=1)
        expected = (min(upper, midnight(tomorrow)) - max(lower, midnight(day))) // INTERVAL
        days.append({'date': day.isoformat(), 'expected_slots': expected,
                     'servers': [{'id': server, **daily[day, server].result()} for server in names]})
        day = tomorrow
    return {'schema_version': '1.0', 'kind': kind, 'start': start.isoformat(),
            'end': (end - dt.timedelta(days=1)).isoformat(), 'complete': current_slot >= midnight(end),
            'generated_at': at.astimezone(SHANGHAI).isoformat(), 'tracked_from': iso(lower),
            'expected_slots': max(0, (upper - lower) // INTERVAL), 'interval_minutes': INTERVAL // 60,
            'gpu_active_threshold_percent': ACTIVE_THRESHOLD,
            'servers': [{'id': server, 'name': name, **hosts[server].detail()} for server, name in names.items()],
            'days': days}


def publish(db, first, current_slot, at, force):
    for kind in KINDS:
        current = period_start(kind, local_date(current_slot))
        last_complete = db.execute('SELECT MAX(start) FROM reports WHERE kind = ? AND complete = 1', (kind,)).fetchone()[0]
        start = (next_period(kind, dt.date.fromisoformat(last_complete)) if last_complete
                 else period_start(kind, local_date(first)))
        while start <= current:
            end = next_period(kind, start)
            saved = db.execute('SELECT generated FROM reports WHERE kind = ? AND start = ?',
                               (kind, start.isoformat())).fetchone()
            if start != current or force or not saved or saved[0] // 3600 < current_slot // 3600:
                report = summarize(db, kind, start, end, first, current_slot, at)
                db.execute('INSERT OR REPLACE INTO reports VALUES (?, ?, ?, ?, ?, ?)',
                           (kind, report['start'], report['end'], int(at.timestamp()),
                            report['complete'], json.dumps(report, ensure_ascii=False, separators=(',', ':'))))
            start = end


def update(path, snapshot, at, force=False):
    current_slot = slot_at(at)
    with closing(sqlite3.connect(path, timeout=15)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)
        with db:
            db.execute('BEGIN IMMEDIATE')
            first = db.execute('SELECT started FROM tracking').fetchone()
            if first is None:
                first = (current_slot,)
                db.execute('INSERT INTO tracking VALUES (?)', first)
            before = db.total_changes
            db.executemany('INSERT OR IGNORE INTO samples VALUES (?, ?, ?, ?, ?)', sample_rows(snapshot, at))
            captured = db.total_changes - before
        # Keep a good sample even if report publication fails and needs a retry.
        with db:
            db.execute('BEGIN IMMEDIATE')
            publish(db, first[0], current_slot, at, force)
            db.execute('DELETE FROM samples WHERE slot < ?', (current_slot - RAW_RETENTION_DAYS * 86400,))
        return captured


def read_reports(state_dir, kind=None, start=None):
    empty = {'schema_version': '1.0', 'reports': []}
    path = state_dir / DB_NAME if state_dir else None
    if path is None or not path.is_file():
        return None if kind else empty
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if kind:
            row = db.execute('SELECT data FROM reports WHERE kind = ? AND start = ?', (kind, start)).fetchone()
            return json.loads(row[0]) if row else None
        rows = db.execute('SELECT kind, start, end, complete FROM reports ORDER BY start DESC, kind')
        return {**empty, 'reports': [{'kind': kind, 'start': start, 'end': end, 'complete': bool(complete)}
                                     for kind, start, end, complete in rows]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--publish', action='store_true', help='Refresh the current reports immediately.')
    args = parser.parse_args()
    snapshot = read_public_json(args.root, 'data/server-resources.json') or {}
    print(json.dumps({'captured_servers': update(args.state_dir / DB_NAME, snapshot, now(), args.publish)}))


if __name__ == '__main__':
    main()
