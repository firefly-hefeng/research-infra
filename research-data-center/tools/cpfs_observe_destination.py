"""Observe registered shared-library entrances as ordinary rmp, without reading data.

Run after a completed switch (or after completed cleanup). This writes only the
private destination-entry-observations.json receipt, never source/target content.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import pwd
import socket
import stat
import subprocess
import tempfile

BASE = Path('/data/rmp/research-data-center/var/cpfs-migration-20261027')
SHARE = Path('/data/share')
LIBRARIES = {'datasets': ('/data/datasets', '/data/share/datasets'),
             'models': ('/data/models', '/data/share/models')}
BASELINE_SHA256 = '5c05f387cf328e27367380a28db9fad9e8a92fd9e301349babfa4eaf9d903871'
MIGRATION_ID = 'cpfs-20261027'
MOUNT_SOURCE = '10.0.0.202:/share'
OBSERVER_UID = 1011
EXPECTED_RECORDS = 228
EXPECTED_PATHS = 221
OUTPUT_NAME = 'destination-entry-observations.json'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def within(path, root):
    return path == root or path.startswith(root + '/')


def approved_path(value, roots):
    if not isinstance(value, str) or not value.startswith('/') or '\\' in value:
        return None
    if '..' in PurePosixPath(value).parts or any(ord(char) < 32 for char in value):
        return None
    normalized = str(PurePosixPath(value))
    return normalized if any(within(normalized, root) for root in roots) else None


def ordinary_account():
    if os.getuid() != OBSERVER_UID or os.geteuid() != OBSERVER_UID:
        raise RuntimeError('ordinary_rmp_real_and_effective_uid_required')
    if pwd.getpwuid(OBSERVER_UID).pw_name != 'rmp':
        raise RuntimeError('observer_uid_does_not_resolve_to_rmp')
    return {'account': 'rmp', 'observer_uid': OBSERVER_UID, 'observer_gid': os.getgid(),
            'observer_groups': sorted(os.getgroups())}


def parse_time(value):
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        raise RuntimeError('invalid_cutover_timestamp') from None
    if result.tzinfo is None:
        raise RuntimeError('cutover_timestamp_requires_timezone')
    return result


def baseline_paths():
    raw = (BASE / 'catalog-baseline.json').read_bytes()
    if sha256(raw) != BASELINE_SHA256:
        raise RuntimeError('unexpected_asset_baseline_hash')
    document = json.loads(raw)
    assets = document.get('assets')
    if document.get('schema_version') != '1.0' or not isinstance(assets, list) or len(assets) != EXPECTED_RECORDS:
        raise RuntimeError('unexpected_asset_baseline_shape')
    ids, paths = set(), set()
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get('id'), str) or asset['id'] in ids:
            raise RuntimeError('duplicate_or_invalid_asset_identity')
        ids.add(asset['id'])
        path = approved_path(asset.get('path'), [pair[0] for pair in LIBRARIES.values()])
        if path is None or path != asset['path']:
            raise RuntimeError('baseline_path_outside_public_roots')
        for old, new in LIBRARIES.values():
            if within(path, old):
                paths.add(new + path[len(old):])
                break
    if len(paths) != EXPECTED_PATHS:
        raise RuntimeError('unexpected_distinct_baseline_path_count')
    return sorted(paths)


def load_journal(host):
    raw = (BASE / 'cutover-state.json').read_bytes()
    journal = json.loads(raw)
    if journal.get('migration_id') != MIGRATION_ID or journal.get('host') != host:
        raise RuntimeError('cutover_identity_or_host_mismatch')
    if journal.get('phase') not in ('switched', 'cleaned'):
        raise RuntimeError('cutover_not_fully_switched_or_cleaned')
    parse_time(journal.get('switched_at'))
    for name in LIBRARIES:
        row = journal.get('roots', {}).get(name, {})
        if row.get('publication') != 'published' or row.get('switch') != 'switched':
            raise RuntimeError('partial_root_cutover_refused')
        expected = row.get('destination_inode', {})
        if any(type(expected.get(key)) is not int for key in ('dev', 'ino', 'mode', 'uid', 'gid')):
            raise RuntimeError('destination_inode_binding_missing')
        if journal['phase'] == 'cleaned' and row.get('cleanup') != 'deleted':
            raise RuntimeError('partial_cleanup_refused')
    return journal, sha256(raw)


def mount_info(path):
    result = subprocess.run(['findmnt', '-J', '-T', str(path), '-o', 'TARGET,SOURCE,FSTYPE'],
                            check=True, capture_output=True, text=True, timeout=10)
    rows = json.loads(result.stdout).get('filesystems', [])
    if len(rows) != 1:
        raise RuntimeError('mount_identity_unavailable')
    mount = {key: rows[0].get(key) for key in ('target', 'source', 'fstype')}
    if mount['target'] != str(SHARE) or mount['source'] != MOUNT_SOURCE or mount['fstype'] not in ('nfs', 'nfs3'):
        raise RuntimeError('unexpected_shared_library_mount')
    return mount


def inode_info(info):
    return {key: getattr(info, 'st_' + key) for key in ('dev', 'ino', 'mode', 'uid', 'gid')}


def root_guard(journal):
    mount = mount_info(SHARE)
    share_info = os.stat(SHARE)
    checks = []
    for name, (old, new) in LIBRARIES.items():
        if mount_info(new) != mount:
            raise RuntimeError('library_mount_changed_or_nested')
        old_info = os.lstat(old)
        if not stat.S_ISLNK(old_info.st_mode) or os.readlink(old) != new:
            raise RuntimeError('legacy_root_alias_mismatch')
        actual = os.lstat(new)
        expected = journal['roots'][name]['destination_inode']
        if (not stat.S_ISDIR(actual.st_mode) or inode_info(actual) != expected
                or actual.st_dev != share_info.st_dev):
            raise RuntimeError('shared_library_root_identity_changed')
        checks.append({'path': old, 'target': new, 'kind': 'symlink', 'verified': True,
                       'realpath': new, 'observed_at': now(), 'destination_inode': inode_info(actual)})
    return mount, checks


def metadata(info):
    try:
        owner = pwd.getpwuid(info.st_uid).pw_name
    except KeyError:
        owner = str(info.st_uid)
    return {'uid': info.st_uid, 'gid': info.st_gid, 'owner': owner,
            'mode': oct(stat.S_IMODE(info.st_mode)), 'mtime_ns': info.st_mtime_ns}


def kind_of(mode):
    return 'symlink' if stat.S_ISLNK(mode) else 'directory' if stat.S_ISDIR(mode) else 'file' if stat.S_ISREG(mode) else 'special'


def resolve_open(path, root, root_fd, row):
    """Resolve links with anchored dirfds; never follow a link outside this library.

    Each pathname component is lstat-ed relative to an already opened directory.
    O_NOFOLLOW and inode comparisons reject replacement races before opening a
    child. Absolute legacy links are translated only after root_guard verified
    the exact compatibility aliases. No external link target is returned.
    """
    parts = list(PurePosixPath(path).relative_to(root).parts)
    current = os.dup(root_fd)
    resolved, hops = [], 0
    try:
        if not parts:
            info = os.fstat(current)
            row.update(entry_kind='directory', exists=True, kind='directory', realpath=root, **metadata(info))
            return os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
        while parts:
            component = parts.pop(0)
            info = os.stat(component, dir_fd=current, follow_symlinks=False)
            entry_kind = kind_of(info.st_mode)
            if not parts and row['entry_kind'] is None:
                row['entry_kind'] = entry_kind
                row['exists'] = True
            if entry_kind == 'symlink':
                hops += 1
                row['symlink']['is_symlink'] = row['entry_kind'] == 'symlink'
                if hops > 40:
                    raise RuntimeError('symlink_resolution_limit')
                target = os.readlink(component, dir_fd=current)
                if '\\' in target or any(ord(char) < 32 for char in target):
                    raise RuntimeError('unsafe_symlink_target')
                target = posixpath.normpath(target if target.startswith('/') else posixpath.join(root, *resolved, target))
                for old, new in LIBRARIES.values():
                    if within(target, old):
                        target = new + target[len(old):]
                        break
                if approved_path(target, [root]) is None:
                    row['symlink']['target_scope'] = 'outside_public_roots'
                    raise RuntimeError('symlink_target_outside_library')
                row['symlink']['target_scope'] = 'public_library'
                parts = list(PurePosixPath(target).relative_to(root).parts) + parts
                resolved = []
                os.close(current)
                current = os.dup(root_fd)
                if not parts:
                    info = os.fstat(current)
                    row.update(exists=True, kind='directory', realpath=root, **metadata(info))
                    return os.open('.', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                continue
            if parts:
                if entry_kind != 'directory':
                    raise NotADirectoryError()
                child = os.open(component, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                opened = os.fstat(child)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    os.close(child)
                    raise RuntimeError('path_component_changed')
                os.close(current)
                current = child
                resolved.append(component)
                continue
            row.update(exists=True, kind=entry_kind if entry_kind in ('directory', 'file') else None,
                       realpath=posixpath.join(root, *resolved, component), **metadata(info))
            if entry_kind not in ('directory', 'file'):
                raise RuntimeError('special_entry_not_opened')
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if entry_kind == 'directory':
                flags |= os.O_DIRECTORY
            opened_fd = os.open(component, flags, dir_fd=current)
            opened = os.fstat(opened_fd)
            if (opened.st_dev, opened.st_ino, stat.S_IFMT(opened.st_mode)) != (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)):
                os.close(opened_fd)
                raise RuntimeError('entry_changed_while_opening')
            row.update(**metadata(opened))
            return opened_fd
    finally:
        os.close(current)


def observe_path(path, host, mount, root_fds):
    roots = [pair[1] for pair in LIBRARIES.values()]
    if approved_path(path, roots) != path:
        raise RuntimeError('observation_path_outside_public_roots')
    root = next(value for value in roots if within(path, value))
    row = {'host': host, 'account': 'rmp', 'observer_uid': OBSERVER_UID,
           'path': path, 'observed_at': now(), 'exists': None, 'readable': False,
           'kind': None, 'entry_kind': None, 'realpath': None, 'mount': dict(mount),
           'symlink': {'is_symlink': False, 'target_scope': None}, 'reason': None}
    fd = None
    try:
        fd = resolve_open(path, root, root_fds[root], row)
        needed = os.R_OK | (os.X_OK if row['kind'] == 'directory' else 0)
        allowed = os.access('/proc/self/fd/' + str(fd), needed)
        if row['kind'] == 'directory':
            with os.scandir(fd) as entries:
                next(entries, None)  # Prove listing works, but never record names.
        row['readable'] = bool(allowed)
        if not allowed:
            row['reason'] = 'account_access_denied'
    except FileNotFoundError:
        row.update(exists=False, reason='not_found_or_dangling')
    except PermissionError:
        row['reason'] = 'permission_denied'
    except NotADirectoryError:
        row['reason'] = 'non_directory_path_component'
    except RuntimeError as exc:
        row['reason'] = str(exc)  # Only fixed local error codes, never target text.
    except OSError as exc:
        row['reason'] = 'os_error_' + str(exc.errno)
    finally:
        if fd is not None:
            os.close(fd)
        row['observed_at'] = now()
    return row


def observe():
    account = ordinary_account()
    started_at, host = now(), socket.gethostname()
    paths = baseline_paths()
    journal, journal_hash = load_journal(host)
    if parse_time(started_at) < parse_time(journal['switched_at']):
        raise RuntimeError('observer_clock_precedes_switch')
    mount, root_checks = root_guard(journal)
    report = {'schema_version': '1.0', 'migration_id': MIGRATION_ID, 'complete': False,
              'started_at': started_at, 'observed_at': None, 'host': host, **account,
              'baseline_sha256': BASELINE_SHA256, 'cutover_state_sha256': journal_hash,
              'cutover_phase': journal['phase'], 'switched_at': journal['switched_at'],
              'mount': mount, 'root_checks': root_checks, 'observations': [], 'errors': []}
    root_fds = {}
    try:
        for name, (_, target) in LIBRARIES.items():
            fd = os.open(target, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
            root_fds[target] = fd
            if inode_info(os.fstat(fd)) != journal['roots'][name]['destination_inode']:
                raise RuntimeError('root_changed_while_opening')
        for path in paths:
            row = observe_path(path, host, mount, root_fds)
            report['observations'].append(row)
            if row['exists'] is not True or row['readable'] is not True or row['reason']:
                report['errors'].append({'path': path, 'reason': row['reason'] or 'entry_not_readable'})
        final_mount, final_checks = root_guard(journal)
        if final_mount != mount or sha256((BASE / 'cutover-state.json').read_bytes()) != journal_hash:
            raise RuntimeError('mount_or_cutover_journal_changed_during_observation')
        report['root_checks'] = final_checks
        disk = os.statvfs(SHARE)
        report['disk_snapshot'] = {'mount': str(SHARE), 'total_bytes': disk.f_blocks * disk.f_frsize,
                                   'available_bytes': disk.f_bavail * disk.f_frsize, 'observed_at': now()}
    except RuntimeError as exc:
        report['errors'].append({'reason': str(exc)})
    except OSError as exc:
        report['errors'].append({'reason': 'observation_os_error_' + str(exc.errno)})
    finally:
        for fd in root_fds.values():
            os.close(fd)
    report['observed_at'] = now()
    report['complete'] = not report['errors'] and len(report['observations']) == EXPECTED_PATHS
    return report


def write_receipt(report):
    # The account check is repeated at the mutation boundary. The only mutation
    # is an atomic replacement of this fixed private metadata receipt.
    ordinary_account()
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.destination-observer-', suffix='.tmp', dir=BASE)
        temporary = Path(name)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, BASE / OUTPUT_NAME)
        temporary = None
        directory_fd = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    ordinary_account()
    try:
        report = observe()
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        # A failed rerun invalidates the previous success receipt. Error strings
        # are type/code only and cannot copy external symlink targets into output.
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        report = {'schema_version': '1.0', 'migration_id': MIGRATION_ID, 'complete': False,
                  'observed_at': now(), 'host': socket.gethostname(), **ordinary_account(),
                  'observations': [], 'errors': [{'reason': reason}]}
    write_receipt(report)
    print(json.dumps({'complete': report['complete'], 'observed_entries': len(report['observations']),
                      'error_count': len(report['errors']), 'receipt': str(BASE / OUTPUT_NAME)}, ensure_ascii=False))
    return 0 if report['complete'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
