#!/usr/bin/env python3
"""Repair read access and default ACLs on local XFS member workspaces."""
import argparse
import base64
import errno
import fcntl
import grp
import gzip
import json
import os
from pathlib import Path
import pwd
import stat
import struct
import subprocess
import time

ROOT = '/data/users'
ACCESS = 'system.posix_acl_access'
DEFAULT = 'system.posix_acl_default'
# Linux UAPI posix_acl.h and posix_acl_xattr.h.
USER, GROUP, OTHER = 0x01, 0x04, 0x20
UNDEFINED_ID = 0xffffffff
VERSION = struct.pack('<I', 2)
FULL_INTERVAL_SECONDS = 7 * 24 * 60 * 60


def acl(fd_or_path, key):
    try:
        if isinstance(fd_or_path, int):
            return os.getxattr(fd_or_path, key)
        return os.getxattr(fd_or_path, key, follow_symlinks=False)
    except OSError as error:
        if error.errno != errno.ENODATA:
            raise
        return None


def readable_acl(original, permissions):
    if original[:4] != VERSION:
        raise ValueError('Unsupported POSIX ACL version')
    entries = struct.iter_unpack('<HHI', original[4:])
    # The mask and each matching named user/group can otherwise cap access.
    # OR only read/traverse bits so masked write entries remain masked.
    return VERSION + b''.join(struct.pack('<HHI', tag,
        mode if tag == USER else mode | permissions, identifier)
        for tag, mode, identifier in entries)


def repair(fd, path, info, audit):
    mode = stat.S_IMODE(info.st_mode)
    is_directory = stat.S_ISDIR(info.st_mode)
    permissions = 5 if is_directory else 4
    old_access = acl(fd, ACCESS)
    old_default = acl(fd, DEFAULT) if is_directory else None
    new_access = readable_acl(old_access, permissions) if old_access else None
    new_mode = mode | (permissions << 3) | permissions
    new_default = old_default
    if is_directory:
        base = VERSION + b''.join(struct.pack('<HHI', tag, value, UNDEFINED_ID)
                                 for tag, value in [(USER, 7), (GROUP, 5), (OTHER, 5)])
        new_default = readable_acl(old_default or base, 5)
    if new_mode == mode and new_access == old_access and new_default == old_default:
        return False
    audit.write(json.dumps(dict(path=path, inode=info.st_ino, device=info.st_dev, mode=mode,
                                access=encode(old_access), default=encode(old_default))) + '\n')
    audit.flush()
    if new_access is not None and new_access != old_access:
        os.setxattr(fd, ACCESS, new_access)
    elif new_access is None and new_mode != mode:
        os.fchmod(fd, new_mode)
    if new_default != old_default:
        os.setxattr(fd, DEFAULT, new_default)
    return True


def encode(value):
    return base64.b64encode(value).decode('ascii') if value is not None else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audit', nargs='?', type=Path, help='New gzip audit file in a root-owned directory')
    parser.add_argument('--member', help='Limit the sweep to one member')
    parser.add_argument('--state-directory', type=Path, help='Run recurring maintenance with an incremental checkpoint')
    args = parser.parse_args()
    if bool(args.audit) == bool(args.state_directory) or (args.member and args.state_directory):
        parser.error('Specify an audit path or --state-directory, and use --member only with an audit path')
    os.umask(0o077)
    directory = args.state_directory or args.audit.parent
    with (directory / 'workspace.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sweep(args)


def sweep(args):
    mount = subprocess.check_output(['findmnt', '-rn', '-T', ROOT, '-o', 'TARGET,FSTYPE'],
                                    universal_newlines=True).strip()
    if (mount not in ('/data xfs', ROOT + ' xfs') or os.path.realpath(ROOT) != ROOT
            or os.stat(ROOT).st_dev != os.stat('/data').st_dev):
        raise RuntimeError('Unexpected local workspace mount: ' + mount)
    device = os.stat(ROOT).st_dev
    members = {user: pwd.getpwnam(user).pw_uid for user in grp.getgrnam('ml-readers').gr_mem}
    members = {user: uid for user, uid in members.items() if uid >= 1000}
    if args.member:
        if args.member not in members:
            raise ValueError('Not a lab member: ' + args.member)
        members = {args.member: members[args.member]}
    started = time.time()
    cutoff = 0
    last_full_at = started
    audit_path = args.audit
    if args.state_directory:
        audit_path = args.state_directory / ('before-{}.jsonl.gz'.format(int(started * 1000000)))
        checkpoint = args.state_directory / 'last-success.json'
        try:
            previous = json.loads(checkpoint.read_text(encoding='utf-8'))
            prior_full = previous.get('last_full_at', previous['started_at'] if previous.get('cutoff') == 0 else 0)
            if (previous['members'] == members and previous['device'] == device
                    and 0 < prior_full <= previous['started_at'] <= started
                    and started - prior_full < FULL_INTERVAL_SECONDS):
                # Overlap to cover filesystem timestamp granularity. Use the
                # previous start so changes during that sweep remain eligible.
                cutoff = max(0, previous['started_at'] - 2)
                last_full_at = prior_full
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            pass
    counts = dict(members=0, directories=0, files=0, changed_directories=0,
                  changed_files=0, inspected_directories=0, inspected_files=0, missing_workspaces=0,
                  vanished=0, errors=0)

    def error(exc):
        if isinstance(exc, FileNotFoundError) or exc.errno == errno.ELOOP:
            counts['vanished'] += 1
        else:
            counts['errors'] += 1
            if counts['errors'] <= 20:
                print(str(exc), flush=True)

    with gzip.open(str(audit_path), 'xt', encoding='utf-8') as audit:
        for member in sorted(members):
            root = os.path.join(ROOT, member)
            try:
                root_info = os.lstat(root)
            except FileNotFoundError:
                counts['missing_workspaces'] += 1
                continue
            if not stat.S_ISDIR(root_info.st_mode) or root_info.st_dev != device:
                raise RuntimeError('Unexpected member workspace: ' + root)
            counts['members'] += 1
            for path, dirs, files, fd in os.fwalk(root, follow_symlinks=False, onerror=error):
                info = os.fstat(fd)
                if info.st_dev != device:
                    dirs[:] = []
                    continue
                counts['directories'] += 1
                try:
                    if info.st_ctime >= cutoff:
                        counts['inspected_directories'] += 1
                        counts['changed_directories'] += repair(fd, path, info, audit)
                except OSError as exc:
                    error(exc)
                for name in files:
                    try:
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if not stat.S_ISREG(info.st_mode) or info.st_dev != device:
                            continue
                        counts['files'] += 1
                        if info.st_ctime < cutoff:
                            continue
                        counts['inspected_files'] += 1
                        if info.st_mode & 0o044 == 0o044:
                            old = acl('/proc/self/fd/{}/{}'.format(fd, name), ACCESS)
                            if old is None or old == readable_acl(old, 4):
                                continue
                        child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                        try:
                            current = os.fstat(child)
                            if (current.st_dev, current.st_ino) == (device, info.st_ino):
                                counts['changed_files'] += repair(child, os.path.join(path, name), current, audit)
                            else:
                                counts['vanished'] += 1
                        finally:
                            os.close(child)
                    except OSError as exc:
                        error(exc)
            print(json.dumps(dict(counts, completed_member=member)), flush=True)
    result = dict(counts, audit=str(audit_path), started_at=started, completed_at=time.time(), cutoff=cutoff)
    print(json.dumps(result), flush=True)
    if counts['errors']:
        raise SystemExit(1)
    if args.state_directory:
        pending = checkpoint.with_suffix('.tmp')
        pending.write_text(json.dumps(dict(result, members=members, device=device, last_full_at=last_full_at),
                                      indent=2) + '\n', encoding='utf-8')
        pending.replace(checkpoint)


if __name__ == '__main__':
    main()
