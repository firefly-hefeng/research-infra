#!/usr/bin/env python3
"""Keep the lab NFS share readable; preserve every existing write bit.

Run only on the coordinator. Never follow symlinks or enter snapshots/mounts.
Each changed inode's original mode is recorded before modification.
"""
import datetime
from concurrent.futures import ThreadPoolExecutor
import fcntl
import gzip
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import threading

ROOT = '/data/share'
STATE = Path('/var/lib/research-share-permissions')


def main():
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    lock = (STATE / 'lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    mount = subprocess.check_output(
        ['findmnt', '-rn', '-M', ROOT, '-o', 'SOURCE,FSTYPE'], universal_newlines=True).strip()
    if mount != '10.0.0.202:/share nfs' or os.path.islink(ROOT):
        raise RuntimeError('Unexpected share mount: ' + mount)
    device = os.stat(ROOT).st_dev
    member_uids = {p.pw_uid for p in pwd.getpwall() if 1000 <= p.pw_uid < 60000}
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S.%fZ')
    counts = dict(directories=0, files=0, changed=0, vanished=0, errors=0)
    audit_path = STATE / ('before-' + stamp + '.jsonl.gz')
    audit_lock = threading.Lock()
    with gzip.open(str(audit_path), 'wt', encoding='utf-8') as audit, ThreadPoolExecutor(max_workers=4) as pool:
        def error(exc):
            if isinstance(exc, FileNotFoundError):
                counts['vanished'] += 1
            else:
                counts['errors'] += 1
                if counts['errors'] <= 20:
                    print(str(exc), flush=True)

        def repair(fd, path):
            info = os.fstat(fd)
            if info.st_dev != device:
                return 0
            isdir = stat.S_ISDIR(info.st_mode)
            if not isdir and not stat.S_ISREG(info.st_mode):
                return 0
            old = stat.S_IMODE(info.st_mode)
            new = old | (0o555 if isdir else 0o444)
            if new != old:
                with audit_lock:
                    audit.write(json.dumps(dict(path=path, dev=info.st_dev, inode=info.st_ino,
                                                mode=old, uid=info.st_uid, gid=info.st_gid)) + '\n')
                    audit.flush()
                os.fchmod(fd, new)
                return 1
            return 0

        def file_result(name, fd, path):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_dev != device:
                    return 0, 0, None
                if info.st_mode & 0o444 == 0o444:
                    return 1, 0, None
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    return 1, repair(child, os.path.join(path, name)), None
                finally:
                    os.close(child)
            except OSError as exc:
                return 0, 0, exc

        for path, dirs, files, fd in os.fwalk(ROOT, follow_symlinks=False, onerror=error):
            if os.fstat(fd).st_dev != device:
                dirs[:] = []
                continue
            if path == ROOT:
                # Member namespaces and member-owned project directories only.
                # Bulk managed datasets/models and NAS snapshots are not member workspaces.
                selected = []
                for name in dirs:
                    try:
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if (name != '.snapshots' and stat.S_ISDIR(info.st_mode)
                                and (name in ('incoming', 'public') or info.st_uid in member_uids)):
                            selected.append(name)
                    except OSError as exc:
                        error(exc)
                dirs[:] = sorted(selected, key=lambda name: (name not in ('incoming', 'public'), name))
            counts['directories'] += 1
            try:
                counts['changed'] += repair(fd, path)
            except OSError as exc:
                error(exc)
            # Bound queued work and keep this directory descriptor alive until all
            # workers finish. Four workers overlap NFS round trips, not file reads.
            for offset in range(0, len(files), 512):
                results = pool.map(lambda name: file_result(name, fd, path), files[offset:offset + 512])
                for seen, changed, exc in results:
                    counts['files'] += seen
                    counts['changed'] += changed
                    if exc is not None:
                        error(exc)
    result = dict(counts, started_utc=stamp,
                  completed_utc=datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S.%fZ'),
                  audit=str(audit_path))
    temporary = STATE / 'last-result.tmp'
    temporary.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    temporary.replace(STATE / 'last-result.json')
    print(json.dumps(result), flush=True)
    if counts['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
