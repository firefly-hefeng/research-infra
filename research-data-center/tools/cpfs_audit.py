"""Read-only source and process audit. Never traverses symlinks or other mounts."""
import argparse
import collections
import datetime as dt
import gzip
import heapq
import json
import os
from pathlib import Path
import pwd
import stat
import time

ROOTS = ('/data/datasets', '/data/models')

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def matching(path):
    clean = path.removesuffix(' (deleted)')
    return any(clean == r or clean.startswith(r + '/') for r in ROOTS)

def processes():
    report = dict(observed_at=now(), host=os.uname().nodename, scope=list(ROOTS),
                  processes=[], errors=[], visibility='local_host_only')
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            uid = proc.stat().st_uid
            comm = (proc / 'comm').read_text().strip()
            refs = []
            for name in ('cwd', 'exe'):
                try:
                    value = os.readlink(proc / name)
                    if matching(value):
                        refs.append(dict(kind=name, path=value))
                except (FileNotFoundError, ProcessLookupError):
                    pass
            for fd in (proc / 'fd').iterdir():
                try:
                    value = os.readlink(fd)
                    if not matching(value):
                        continue
                    info = (proc / 'fdinfo' / fd.name).read_text()
                    flags = next(int(line.split()[1], 8) for line in info.splitlines() if line.startswith('flags:'))
                    refs.append(dict(kind='fd', fd=int(fd.name), path=value,
                                     access={0:'read', 1:'write', 2:'read_write'}.get(flags & 3, 'unknown')))
                except (FileNotFoundError, ProcessLookupError):
                    pass
            for line in (proc / 'maps').read_text().splitlines():
                fields = line.split(None, 5)
                if len(fields) == 6 and matching(fields[5]):
                    refs.append(dict(kind='mmap', path=fields[5], permissions=fields[1],
                                     shared_writable='w' in fields[1] and 's' in fields[1]))
            # Report only source-root path arguments, never full command lines or secrets.
            args = (proc / 'cmdline').read_bytes().decode('utf-8', 'replace').split('\0')
            for arg in args:
                if arg.startswith(ROOTS) and matching(arg):
                    refs.append(dict(kind='path_argument', path=arg))
            if refs:
                try:
                    user = pwd.getpwuid(uid).pw_name
                except KeyError:
                    user = str(uid)
                report['processes'].append(dict(pid=int(proc.name), uid=uid, user=user, comm=comm, references=refs))
        except (FileNotFoundError, ProcessLookupError):
            pass
        except Exception as exc:
            report['errors'].append(dict(pid=int(proc.name), error=type(exc).__name__ + ': ' + str(exc)))
    return report

def inventory(out, max_seconds):
    started = time.monotonic()
    report = dict(started_at=now(), host=os.uname().nodename, complete=False, roots={}, errors=[],
                  hardlink_groups=[], symlinks=[], special_files=[], recent_files=[], mutable_candidates=[])
    hardlinks = collections.defaultdict(list)
    recent = []
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / 'source-files.jsonl.gz'
    with gzip.open(manifest, 'wt', encoding='utf-8') as sink:
        for root in ROOTS:
            st_root = os.lstat(root)
            if not stat.S_ISDIR(st_root.st_mode):
                raise RuntimeError('Source is not a plain directory: ' + root)
            groups = collections.defaultdict(lambda: dict(files=0, directories=0, symlinks=0, special=0,
                                                         bytes=0, allocated_bytes=0, sparse_files=0))
            queue = [Path(root)]
            while queue:
                current = queue.pop()
                if time.monotonic() - started > max_seconds:
                    raise TimeoutError('Inventory time budget exhausted; manifest is partial')
                try:
                    with os.scandir(current) as entries:
                        for ent in entries:
                            p = Path(ent.path)
                            rel = str(p.relative_to(root))
                            top = rel.split('/', 1)[0]
                            s = ent.stat(follow_symlinks=False)
                            row = dict(root=root, relative_path=rel, mode=s.st_mode, uid=s.st_uid, gid=s.st_gid,
                                       size=s.st_size, mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns,
                                       dev=s.st_dev, ino=s.st_ino, nlink=s.st_nlink, blocks=s.st_blocks)
                            g = groups[top]
                            if s.st_dev != st_root.st_dev:
                                row['kind'] = 'other_mount'
                                report['errors'].append(dict(path=str(p), error='different_device_not_traversed'))
                            elif stat.S_ISDIR(s.st_mode):
                                row['kind'] = 'directory'; g['directories'] += 1
                                queue.append(p)
                            elif stat.S_ISREG(s.st_mode):
                                row['kind'] = 'file'; g['files'] += 1
                                g['bytes'] += s.st_size; g['allocated_bytes'] += s.st_blocks * 512
                                if s.st_size > s.st_blocks * 512 + 4096:
                                    g['sparse_files'] += 1
                                if s.st_nlink > 1:
                                    hardlinks[(s.st_dev, s.st_ino)].append(str(p))
                                heapq.heappush(recent, (s.st_mtime_ns, str(p), s.st_size))
                                if len(recent) > 100:
                                    heapq.heappop(recent)
                                if p.suffix.lower() in ('.db', '.sqlite', '.sqlite3') or p.name.endswith(('-wal', '-shm', '.lock', '.incomplete')):
                                    if len(report['mutable_candidates']) < 2000:
                                        report['mutable_candidates'].append(dict(path=str(p), bytes=s.st_size, mtime_ns=s.st_mtime_ns))
                            elif stat.S_ISLNK(s.st_mode):
                                row['kind'] = 'symlink'; g['symlinks'] += 1
                                row['target'] = os.readlink(p)
                                if len(report['symlinks']) < 2000:
                                    report['symlinks'].append(dict(path=str(p), target=row['target']))
                            else:
                                row['kind'] = 'special'; g['special'] += 1
                                report['special_files'].append(dict(path=str(p), mode=s.st_mode))
                            sink.write(json.dumps(row, ensure_ascii=False) + '\n')
                except (PermissionError, FileNotFoundError, OSError) as exc:
                    report['errors'].append(dict(path=str(current), error=str(exc)))
            report['roots'][root] = dict(device=st_root.st_dev, groups=dict(groups),
                                        totals={k:sum(v[k] for v in groups.values()) for k in ('files','directories','symlinks','special','bytes','allocated_bytes','sparse_files')})
            (out / 'inventory-progress.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    report['hardlink_groups'] = [dict(device=key[0], inode=key[1], paths=paths) for key, paths in hardlinks.items()]
    report['recent_files'] = [dict(mtime_ns=m, path=p, bytes=b) for m,p,b in sorted(recent, reverse=True)]
    report['completed_at'] = now()
    report['elapsed_seconds'] = round(time.monotonic() - started, 2)
    report['complete'] = not report['errors']
    report['manifest'] = str(manifest)
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('processes', 'inventory'))
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-seconds', type=int, default=7200)
    args = parser.parse_args()
    target = Path(args.output)
    result = processes() if args.mode == 'processes' else inventory(target.parent, args.max_seconds)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(target), complete=result.get('complete'), processes=len(result.get('processes',[])), errors=len(result['errors']))))
