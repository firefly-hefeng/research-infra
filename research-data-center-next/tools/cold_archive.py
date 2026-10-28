"""Immutable application/catalog backups on OSS; never opens live SQLite on OSS.

Objects are written to fresh UUID names, read back, hashed, then referenced by a
completion receipt. No rename, shared lock, mutable latest pointer or hardlink is
assumed on ossfs. The small SQLite working copies and locks remain local.
"""
import argparse
from contextlib import closing
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import uuid
import sys

try:
    import fcntl
except ImportError:
    fcntl = None


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def no_links(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Absolute normalized path required')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError('Symlink in storage path')
    return path


def mount(path):
    result = subprocess.run(['findmnt', '-J', '-T', str(path), '-o', 'TARGET,SOURCE,FSTYPE,FSROOT'],
                            check=True, capture_output=True, text=True, timeout=15)
    rows = json.loads(result.stdout)['filesystems']
    if len(rows) != 1:
        raise ValueError('Ambiguous mount identity')
    return rows[0]


def storage_guards(local, cold):
    no_links(local)
    no_links(cold)
    if Path(cold) != Path('/data/share_cold/research-data-center'):
        raise ValueError('Only the dedicated application prefix is authorized')
    local_mount, cold_mount = mount(local), mount(cold)
    if local_mount['fstype'] not in ('xfs', 'ext4', 'btrfs') or not local_mount['source'].startswith('/dev/'):
        raise ValueError('Working state must be on a local block filesystem')
    parent = Path('/data/share_cold')
    parent_mount = mount(parent)
    expected_parent = {'target': '/data/share_cold', 'source': 'ossfs',
                       'fstype': 'fuse.ossfs', 'fsroot': '/'}
    # systemd ReadWritePaths creates precisely this bind in the service's
    # namespace. Its backing subtree must be the same authorized OSS prefix;
    # a matching filesystem type or a source-name prefix alone is insufficient.
    expected_bind = {'target': '/data/share_cold/research-data-center',
                     'source': 'ossfs[/research-data-center]', 'fstype': 'fuse.ossfs',
                     'fsroot': '/research-data-center'}
    if parent_mount != expected_parent or cold_mount not in (expected_parent, expected_bind):
        raise ValueError('Unexpected cold mount')
    if os.stat(cold).st_dev != os.stat(parent).st_dev:
        raise ValueError('Cold prefix is not on the parent filesystem')
    return {'local': local_mount, 'cold': cold_mount}


def sqlite_snapshot(source, destination):
    no_links(source)
    if not stat.S_ISREG(source.lstat().st_mode):
        raise ValueError('Snapshot source must be regular')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(destination)) as backup:
            original.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite backup integrity failure')


def open_directory(path):
    no_links(path)
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def put_object(source, target, check=None, expected_device=None):
    """No overwrite. Partial objects have no receipt and are not valid backups."""
    if check:
        check()
    expected = sha(source)
    directory = open_directory(target.parent)
    try:
        if expected_device is not None and os.fstat(directory).st_dev != expected_device:
            raise ValueError('Cold directory device changed')
        descriptor = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o640, dir_fd=directory)
        with source.open('rb') as incoming, os.fdopen(descriptor, 'wb') as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        descriptor = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        actual = hashlib.sha256()
        with os.fdopen(descriptor, 'rb') as incoming:
            size = os.fstat(incoming.fileno()).st_size
            for block in iter(lambda: incoming.read(1024 * 1024), b''):
                actual.update(block)
        if actual.hexdigest() != expected or size != source.stat().st_size or sha(source) != expected:
            raise ValueError('Cold object readback mismatch')
        if check:
            check()
        return {'name': str(target.name), 'sha256': expected, 'bytes': size}
    finally:
        os.close(directory)


def archive_locked(root, state_dir, cold):
    root, state_dir, cold = map(lambda p: Path(p).absolute(), (root, state_dir, cold))
    mounts = storage_guards(state_dir, cold)
    storage_guards(root, cold)
    # Build the current curated source/cards as well as SQLite snapshots. This
    # runs as the ordinary coordinator, never as a privileged metadata parser.
    subprocess.run([sys.executable, str(root / 'tools/package_release.py')], cwd=root, check=True,
                   stdout=subprocess.DEVNULL)
    release = root / 'release.tar.gz'
    if not release.is_file() or release.is_symlink():
        raise ValueError('Verified release.tar.gz required')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    for source in (root / 'var/catalog.sqlite3', state_dir / 'ingestion.sqlite3'):
        if not source.is_file():
            raise ValueError('Required live database is absent: ' + source.name)
    identity = cold.stat()
    def check():
        storage_guards(state_dir, cold)
        current = cold.stat()
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise ValueError('Cold mount or prefix identity changed')
    base = open_directory(cold)
    try:
        try:
            os.mkdir('snapshots', 0o755, dir_fd=base)
        except FileExistsError:
            pass
        snapshots = os.open('snapshots', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
        try:
            check()
            if os.fstat(snapshots).st_dev != identity.st_dev:
                raise ValueError('Nested cold mount rejected')
            os.mkdir(stamp, 0o750, dir_fd=snapshots)
        finally:
            os.close(snapshots)
    finally:
        os.close(base)
    prefix = cold / 'snapshots' / stamp
    receipt = {'schema_version': '1.0', 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'storage': mounts, 'snapshot_id': stamp, 'objects': [], 'live_state_on_oss': False}
    with tempfile.TemporaryDirectory(prefix='cold-backup-', dir=state_dir) as temporary:
        scratch = Path(temporary)
        receipt['objects'].append(put_object(release, prefix / 'release.tar.gz', check, identity.st_dev))
        for name, source in (('catalog.sqlite3', root / 'var/catalog.sqlite3'),
                             ('ingestion.sqlite3', state_dir / 'ingestion.sqlite3')):
            snapshot = scratch / name
            sqlite_snapshot(source, snapshot)
            receipt['objects'].append(put_object(snapshot, prefix / name, check, identity.st_dev))
        local_receipt = scratch / 'COMPLETE.json'
        local_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        completed = put_object(local_receipt, prefix / 'COMPLETE.json', check, identity.st_dev)
        receipt['receipt_sha256'] = completed['sha256']
    # Local status is atomic; no analogous atomicity is assumed on OSS.
    receipt['cold_path'] = str(prefix)
    descriptor, name = tempfile.mkstemp(prefix='cold-backup-status-', dir=state_dir)
    temporary = Path(name)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(receipt, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(state_dir / 'cold-backup-status.json')
    return receipt


def archive(root, state_dir, cold):
    state_dir = Path(state_dir).absolute()
    no_links(state_dir)
    info = state_dir.stat()
    if fcntl is None or os.getuid() == 0 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('Private ordinary-account local state required')
    storage_guards(state_dir, Path(cold).absolute())
    descriptor = os.open(state_dir / 'cold-backup.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return archive_locked(root, state_dir, cold)
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, default=Path('/var/lib/research-data-center/state'))
    parser.add_argument('--cold-root', type=Path, default=Path('/data/share_cold/research-data-center'))
    args = parser.parse_args()
    print(json.dumps(archive(args.root, args.state_dir, args.cold_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
