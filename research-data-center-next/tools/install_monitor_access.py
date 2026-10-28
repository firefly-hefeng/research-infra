"""Prepare a dedicated local key or authorize its fixed read-only probe.

No remote connection or deployment is made by this tool. Run prepare-key as rmp
on the central host, then authorize as root separately on each approved server.
Only one restricted key line is appended; existing authorized_keys are retained.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import tempfile

try:
    import fcntl
    import pwd
except ImportError:
    fcntl = pwd = None

REMOTE_PROBE = Path(__file__).with_name('server_resource_probe.py').read_text(encoding='utf-8')
SERVERS = ({'address': '47.117.138.84'}, {'address': '101.132.97.146'}, {'address': '139.196.25.53'})

KEY_DIR = Path('/var/lib/research-data-center/state/monitor-ssh')
PROBE_DIR = Path('/var/lib/research-data-center-monitor')
PROBE_PATH = PROBE_DIR / 'probe.py'
CENTRAL_HOST = 'iZuf6jc6bqdgxmhcci4k3wZ'
FORCED_COMMAND = '/usr/bin/python3 ' + str(PROBE_PATH)


def require(condition, code):
    if not condition:
        raise ValueError(code)


def no_symlinks(path):
    require(path.is_absolute() and '..' not in path.parts, 'absolute_safe_path_required')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        require(not current.is_symlink(), 'symlink_path_refused')


def public_key(value):
    fields = value.strip().split()
    require(len(fields) >= 2 and fields[0] == 'ssh-ed25519', 'dedicated_ed25519_key_required')
    try:
        raw = base64.b64decode(fields[1], validate=True)
        size = struct.unpack('>I', raw[:4])[0]
        algorithm = raw[4:4+size]
        key_length = struct.unpack('>I', raw[4+size:8+size])[0]
        require(algorithm == b'ssh-ed25519' and key_length == 32 and len(raw) == 8+size+32, 'invalid_ed25519_key')
    except (ValueError, struct.error):
        raise ValueError('invalid_ed25519_key') from None
    return 'ssh-ed25519 ' + fields[1]


def authorized_line(key):
    return 'restrict,command="' + FORCED_COMMAND + '" ' + public_key(key) + ' rdc-readonly-monitor'


def append_restricted(existing, key):
    require(len(existing) <= 1024 * 1024, 'authorized_keys_size_limit')
    line = authorized_line(key)
    text = existing.decode('utf-8')
    blob = public_key(key).split()[1]
    found = [row for row in text.splitlines() if blob in row.split()]
    if found:
        require(found == [line], 'same_key_exists_with_different_restrictions')
        return existing, False
    return existing + (b'\n' if existing and not existing.endswith(b'\n') else b'') + line.encode() + b'\n', True


def atomic(path, data, uid, gid, mode):
    no_symlinks(path)
    fd, name = tempfile.mkstemp(prefix='.monitor-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.chown(temporary, uid, gid);os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def prepare_key(execute):
    require(pwd is not None and os.getuid() == os.geteuid() == 1011 and socket.gethostname() == CENTRAL_HOST,
            'ordinary_central_rmp_required')
    no_symlinks(KEY_DIR)
    require(KEY_DIR.parent.is_dir() and KEY_DIR.parent.stat().st_uid == 1011
            and stat.S_IMODE(KEY_DIR.parent.stat().st_mode) & 0o077 == 0, 'private_local_state_required')
    if not execute:
        return {'planned': True, 'key_directory': str(KEY_DIR), 'private_key_written': False}
    KEY_DIR.mkdir(mode=0o700, exist_ok=True)
    require(KEY_DIR.stat().st_uid == 1011 and stat.S_IMODE(KEY_DIR.stat().st_mode) == 0o700, 'private_key_directory_required')
    key = KEY_DIR / 'id_ed25519'
    no_symlinks(key)
    if not key.exists():
        subprocess.run(['ssh-keygen', '-t', 'ed25519', '-N', '', '-C', 'rdc-readonly-monitor', '-f', str(key)],
                       check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    require(key.stat().st_uid == 1011 and stat.S_IMODE(key.stat().st_mode) == 0o600, 'private_key_permissions_invalid')
    no_symlinks(Path(str(key) + '.pub'))
    return {'key_path': str(key), 'public_key': public_key(Path(str(key) + '.pub').read_text()),
            'probe_sha256': hashlib.sha256(REMOTE_PROBE.encode()).hexdigest(), 'passwords_stored': False}


def authorize(key, address, expected_host_key, execute):
    require(fcntl is not None and os.getuid() == os.geteuid() == 0, 'root_required_for_fixed_probe_installation')
    require(address in {row['address'] for row in SERVERS}, 'unapproved_server')
    key = public_key(key)
    server_key = public_key(Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text())
    require(server_key == public_key(expected_host_key), 'server_host_key_does_not_match_pin')
    account = pwd.getpwnam('rmp')
    require(account.pw_uid >= 1000, 'unexpected_rmp_identity')
    ssh_dir = Path(account.pw_dir) / '.ssh'
    no_symlinks(ssh_dir);no_symlinks(PROBE_DIR)
    if not execute:
        return {'planned': True, 'server': address, 'account_uid': account.pw_uid,
                'forced_command': FORCED_COMMAND, 'authorized_key_line': authorized_line(key),
                'probe_sha256': hashlib.sha256(REMOTE_PROBE.encode()).hexdigest()}
    PROBE_DIR.mkdir(mode=0o755, exist_ok=True)
    require(PROBE_DIR.stat().st_uid == 0 and not stat.S_IMODE(PROBE_DIR.stat().st_mode) & 0o022,
            'probe_directory_must_be_root_controlled')
    if PROBE_PATH.exists():
        no_symlinks(PROBE_PATH)
        require(PROBE_PATH.stat().st_uid == 0 and PROBE_PATH.read_bytes() == REMOTE_PROBE.encode(),
                'existing_different_probe_requires_review')
        require(not stat.S_IMODE(PROBE_PATH.stat().st_mode) & 0o022, 'existing_probe_must_not_be_writable')
    else:
        atomic(PROBE_PATH, REMOTE_PROBE.encode(), 0, 0, 0o644)
    if not ssh_dir.exists():
        ssh_dir.mkdir(mode=0o700);os.chown(ssh_dir, account.pw_uid, account.pw_gid)
    require(ssh_dir.stat().st_uid == account.pw_uid and not stat.S_IMODE(ssh_dir.stat().st_mode) & 0o022,
            'ssh_directory_owner_or_permissions_invalid')
    lock = os.open(ssh_dir / '.rdc-monitor-install.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = ssh_dir / 'authorized_keys'
        no_symlinks(target)
        if target.exists():
            require(target.is_file() and target.stat().st_uid in (0, account.pw_uid)
                    and not stat.S_IMODE(target.stat().st_mode) & 0o022, 'authorized_keys_permissions_invalid')
        previous = target.read_bytes() if target.exists() else b''
        ownership = (target.stat().st_uid, target.stat().st_gid, stat.S_IMODE(target.stat().st_mode)) if target.exists() else (account.pw_uid, account.pw_gid, 0o600)
        updated, changed = append_restricted(previous, key)
        require((target.read_bytes() if target.exists() else b'') == previous, 'authorized_keys_changed_during_install')
        if changed:
            atomic(target, updated, *ownership)
    finally:
        os.close(lock)
    return {'server': address, 'authorized': True, 'appended': changed,
            'forced_command': FORCED_COMMAND, 'existing_keys_preserved': True,
            'previous_authorized_keys_sha256': hashlib.sha256(previous).hexdigest(),
            'authorized_keys_sha256': hashlib.sha256(updated).hexdigest(),
            'known_hosts_line': address + ' ' + server_key}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare-key', 'authorize'))
    parser.add_argument('--server', choices=[row['address'] for row in SERVERS])
    parser.add_argument('--expected-host-key', help='Pinned ssh-ed25519 public host key, never a password.')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'prepare-key':
            result = prepare_key(args.execute)
        else:
            require(args.server and args.expected_host_key, 'server_and_pinned_host_key_required')
            require(not sys.stdin.isatty(), 'pipe_the_dedicated_public_key_on_stdin')
            result = authorize(sys.stdin.read(8193), args.server, args.expected_host_key, args.execute)
        print(json.dumps({'ok': True, **result}))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
