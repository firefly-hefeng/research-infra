"""Read-only storage observation. Writes only private agent state; never publishes data."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def scan(roots, limit=100000):
    records = {}
    count = 0
    for kind, root in roots.items():
        root = Path(root)
        if not root.is_dir():
            raise ValueError('Missing storage root: ' + str(root))
        # No symlink traversal: targets can live on another host or contain private data.
        for base, directories, files in os.walk(root, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
            for name in sorted(directories + files):
                path = Path(base) / name
                info = path.lstat()
                count += 1
                if count > limit:
                    raise ValueError('Scan limit exceeded; previous snapshot retained')
                relative = path.relative_to(root).as_posix()
                key = kind + '/' + relative
                record = {'kind': kind, 'relative_path': relative, 'entry_type': 'link' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'file', 'bytes': info.st_size if stat.S_ISREG(info.st_mode) else None, 'mtime_ns': info.st_mtime_ns}
                if stat.S_ISLNK(info.st_mode):
                    record['target'] = os.readlink(path)
                # Hash small documentation only; don't read payloads or follow links.
                if name == 'README.md' and stat.S_ISREG(info.st_mode) and info.st_size <= 1024 * 1024:
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, 'rb') as stream:
                        record['readme_sha256'] = hashlib.sha256(stream.read(1024 * 1024 + 1)).hexdigest()
                records[key] = record
    return records


def atomic_json(path, data):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.snapshot-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)



def resource_events(kind, root, previous, records, observed_at, baseline=False, transition=''):
    """Group observed differences by first-level resource directory, not sample."""
    prefix = kind + '/'
    before = {k: v for k, v in previous.items() if k.startswith(prefix)}
    after = {k: v for k, v in records.items() if k.startswith(prefix)}
    names = sorted({k.split('/')[1] for k in before.keys() | after.keys()})
    events = []
    for name in names:
        key = prefix + name
        def group(entries):
            return {k: v for k, v in entries.items() if k == key or k.startswith(key + '/')}
        old, new = group(before), group(after)
        if old == new:
            continue
        changes = [{'path': k[len(prefix):], 'change': 'removed' if k not in new else 'added' if k not in old else 'modified',
                    'before': old.get(k), 'after': new.get(k)}
                   for k in sorted(old.keys() | new.keys()) if old.get(k) != new.get(k)]
        action = 'baseline' if baseline else 'removed' if not new else 'added' if not old else 'updated'
        def stats(entries):
            files = [v for v in entries.values() if v['entry_type'] == 'file']
            return {'file_count': len(files), 'bytes': sum(v['bytes'] or 0 for v in files),
                    'link_count': sum(v['entry_type'] == 'link' for v in entries.values())}
        event = {'resource': name, 'kind': kind, 'action': action, 'location': str(Path(root) / name),
                 'version': None, 'submitted_by': None, 'before': stats(old), 'after': stats(new), 'changes': changes}
        event['event_id'] = hashlib.sha256((transition + json.dumps({k: v for k, v in event.items() if k != 'action'}, sort_keys=True)).encode()).hexdigest()
        event['observed_at'] = observed_at
        event['note'] = '首次建立清单，不代表今天上传。' if baseline else '扫描发现的变化；时间为发现时间，版本和提交人尚未确认。'
        events.append(event)
    return events


def write_resource_logs(state, roots, previous, records, now, transition):
    result = {}
    for kind, label in (('dataset', 'datasets'), ('model', 'models')):
        if kind not in roots:
            continue
        path = state / (label + '-updates.jsonl')
        exists = path.exists()
        history = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if exists else []
        ids = {e['event_id'] for e in history}
        events = resource_events(kind, roots[kind], previous if exists else {}, records, now,
                                 baseline=not exists, transition=transition)
        fresh = [e for e in events if e['event_id'] not in ids]
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            for event in fresh:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        history.extend(fresh)
        lines = ['# ' + label + ' 资源更新日志', '',
                 '仅供管理员与 Agent 使用。按顶层资源目录汇总；时间为扫描发现时间。首次记录是基线，不代表新增上传。',
                 '文件数和字节数仅统计普通文件；不跟随软链接。版本及提交人未核验时保持未知。', '']
        actions = {'baseline': '首次登记', 'added': '新增资源', 'updated': '更新资源', 'removed': '资源入口移除'}
        for event in reversed(history):
            lines += ['## ' + actions[event['action']] + ' · ' + event['observed_at'], '']
            # Indented JSON treats filenames and descriptions as data, not Markdown/HTML.
            readable = {'资源': event['resource'], '位置': event['location'], '版本': event['version'] or '待核验',
                        '提交人': event['submitted_by'] or '未记录', '变更前': event['before'], '变更后': event['after'],
                        '变更条目数': len(event['changes']), '说明': event['note'], '事件ID': event['event_id']}
            lines += ['    ' + line for line in json.dumps(readable, ensure_ascii=False, indent=2).splitlines()] + ['']
        target = state / (label + '-updates.md')
        fd, temp = tempfile.mkstemp(dir=state, prefix='.updates-')
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write('\n'.join(lines))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        result[label] = len(fresh)
    return result


def run(roots, state, limit=100000):
    state = Path(state).absolute()
    if any(p.is_symlink() for p in (state, *state.parents)):
        raise ValueError('State path must not contain symlinks')
    forbidden = [ROOT / 'static', ROOT / 'docs', ROOT / 'data', *(Path(p).resolve() for p in roots.values())]
    if any(state.is_relative_to(p.resolve()) for p in forbidden):
        raise ValueError('State must be outside storage and served metadata directories')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = state.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('State directory must be owned by runner and mode 0700')
    for name in ('lock', 'latest.json', 'changes.jsonl', 'datasets-updates.jsonl', 'datasets-updates.md', 'models-updates.jsonl', 'models-updates.md'):
        path = state / name
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError('Unsafe state file: ' + name)
    fd = os.open(state / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        latest = state / 'latest.json'
        old = json.loads(latest.read_text()) if latest.exists() else {}
        binding = {k: str(Path(v).resolve()) for k, v in roots.items()}
        if old and old['roots'] != binding:
            raise ValueError('Root configuration changed; use a separate state directory')
        records = scan(roots, limit)
        previous = old.get('entries', {})
        now = datetime.now(timezone.utc).isoformat()
        changes = [{'entry': key, 'change': 'removed' if key not in records else 'added' if key not in previous else 'modified'} for key in sorted(records.keys() | previous.keys()) if records.get(key) != previous.get(key)]
        folders = sorted({k.split('/')[0] + '/' + k.split('/')[1] for k in records})
        snapshot = {'schema_version': '1.0', 'observed_at': now, 'roots': binding, 'entries': records, 'agent_review_queue': folders, 'notice': 'Observed entries only; no license, completeness, sample count or version inferred. Links are not traversed. Queue requires human/agent review; not publication.'}
        digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
        if changes:
            fd = os.open(state / 'changes.jsonl', os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a') as log:
                log.write(json.dumps({'observed_at': now, 'snapshot_sha256': digest, 'changes': changes}, ensure_ascii=False) + '\n')
                log.flush()
                os.fsync(log.fileno())
        resource_updates = write_resource_logs(state, binding, previous, records, now, old.get('observed_at', 'initial'))
        atomic_json(latest, snapshot)
        return {'entries': len(records), 'changes': len(changes), 'review_folders': len(folders), 'resource_updates': resource_updates, 'state': str(state)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--datasets', type=Path, default=Path('/data/share/datasets'))
    parser.add_argument('--models', type=Path, default=Path('/data/share/models'))
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--max-entries', type=int, default=100000)
    args = parser.parse_args()
    print(json.dumps(run({'dataset': args.datasets, 'model': args.models}, args.state, args.max_entries), ensure_ascii=False))


if __name__ == '__main__':
    main()
