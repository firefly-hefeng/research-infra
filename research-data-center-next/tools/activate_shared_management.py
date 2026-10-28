"""One-time, fail-closed relocation after the sealed hot-data finalizer completes.

Run only from a root-owned bootstrap directory. Does not migrate/delete payloads.
Preserves the previous application as a local rollback copy. The active service
uses local verified code/state, backed by immutable releases/snapshots on ossfs.
"""
import argparse
import ctypes
import datetime as dt
import grp
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import shutil
import socket
import stat
import subprocess
import tarfile
import time
import urllib.request

try:
    import fcntl
except ImportError:
    fcntl = None

HOST = 'iZuf6jc6bqdgxmhcci4k3wZ'
MIGRATION = 'cpfs-20261027'
APP = Path('/data/rmp/research-data-center')
MIGRATION_BASE = APP / 'var/cpfs-migration-20261027'
BOOT = Path('/var/lib/research-data-center-upgrade-20261027')
LOCAL = Path('/var/lib/research-data-center')
WORKSPACE = LOCAL / 'workspace'
STATE = LOCAL / 'state'
CODE = Path('/opt/research-data-center/releases/20261027-incoming-rules-mountfix')
COLD = Path('/data/share_cold/research-data-center')
BACKUP = Path('/data/rmp/.research-data-center-before-cold-20261027')
PYTHON = '/data/services/miniforge3/bin/python'
UID, GID, SHARED_GID = 1011, 1011, 992
UNIT = Path('/etc/systemd/system/research-data-center.service')
NEW_UNITS = ('research-data-ingestion.service', 'research-data-ingestion.timer',
             'research-data-cold-backup.service', 'research-data-cold-backup.timer')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def run(arguments, user=None):
    command = (['/usr/sbin/runuser', '-u', user, '--'] if user else []) + [str(x) for x in arguments]
    with (BOOT / 'activation.log').open('a') as log:
        log.write(now() + ' ' + json.dumps(command) + '\n')
        log.flush()
        subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                       cwd=WORKSPACE if WORKSPACE.exists() else (APP if user else BOOT), check=True)


def save(state, phase, **values):
    state.update(phase=phase, updated_at=now(), **values)
    temporary = BOOT / 'state.tmp'
    with temporary.open('w') as output:
        json.dump(state, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(BOOT / 'state.json')


def no_links(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        require(not current.is_symlink(), 'Symlink in deployment path: ' + str(current))


def mount(path):
    result = subprocess.run(['findmnt', '-J', '-T', str(path), '-o', 'TARGET,SOURCE,FSTYPE'],
                            check=True, capture_output=True, text=True, timeout=15)
    rows = json.loads(result.stdout)['filesystems']
    require(len(rows) == 1, 'Ambiguous mount')
    return rows[0]


def migration_complete(final, journal, aliases):
    require(final.get('migration_id') == MIGRATION and final.get('host') == HOST,
            'Foreign migration finalization state')
    require(final.get('phase') == 'complete' and journal.get('phase') == 'cleaned',
            'Hot migration is not complete and cleaned')
    require(journal.get('migration_id') == MIGRATION and journal.get('host') == HOST
            and set(journal.get('roots', {})) == {'datasets', 'models'}, 'Foreign or incomplete cutover journal')
    require(mount(Path('/data/share')) == {'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'},
            'Shared mount identity changed')
    for legacy, destination in aliases.items():
        require(legacy.is_symlink() and os.readlink(legacy) == str(destination) and destination.is_dir(),
                'Compatibility alias does not point to published CPFS root')
        row = journal['roots'][destination.name]
        require(row.get('publication') == 'published' and row.get('switch') == 'switched'
                and row.get('cleanup') == 'deleted', 'Incomplete per-root cutover')
        info = destination.lstat()
        observed = dict(dev=info.st_dev, ino=info.st_ino, mode=info.st_mode, uid=info.st_uid, gid=info.st_gid)
        require(stat.S_ISDIR(info.st_mode) and observed == row.get('destination_inode'), 'Published root identity changed')
        require(mount(destination) == mount(Path('/data/share')), 'Nested destination mount')


def inode(path):
    info = path.lstat()
    return [info.st_dev, info.st_ino]


def exchange(first, second):
    library = ctypes.CDLL(None, use_errno=True)
    if library.renameat2(-100, os.fsencode(first), -100, os.fsencode(second), 2):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def restore_application(app, backup, workspace, original_inode):
    """Recover either side of the atomic exchange, without replacing strangers."""
    if app.is_symlink() and os.readlink(app) == str(workspace):
        require(backup.is_dir() and not backup.is_symlink() and inode(backup) == original_inode,
                'Original application rollback identity changed')
        exchange(app, backup)
    require(app.is_dir() and not app.is_symlink() and inode(app) == original_inode,
            'Original application identity unavailable')
    if backup.is_symlink():
        require(os.readlink(backup) == str(workspace), 'Unexpected rollback placeholder')
        backup.unlink()


def wait_for_migration(state):
    deadline = time.monotonic() + 48 * 3600
    while True:
        final = json.loads((MIGRATION_BASE / 'finalization-state.json').read_text())
        require(final.get('migration_id') == MIGRATION and final.get('host') == HOST, 'Foreign finalizer')
        require(final.get('phase') != 'stopped_for_review', 'Hot migration requires review; upgrade stopped')
        if final.get('phase') == 'complete':
            journal = json.loads((MIGRATION_BASE / 'cutover-state.json').read_text())
            migration_complete(final, journal, {Path('/data/datasets'): Path('/data/share/datasets'),
                                                Path('/data/models'): Path('/data/share/models')})
            unit_state = subprocess.check_output(['systemctl', 'show', '-p', 'SubState', '--value',
                                                 'rdc-cpfs-finalize-20261027.service'], text=True).strip()
            if unit_state == 'exited':
                return final
        require(time.monotonic() < deadline, '48 hour migration wait expired')
        save(state, 'waiting_for_hot_migration', hot_migration_phase=final.get('phase'))
        time.sleep(30)


def extract_release(archive, destination, expected):
    require(sha(archive) == expected, 'Release archive checksum mismatch')
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, 'r:gz') as package:
        members = package.getmembers()
        names = [member.name for member in members]
        require(len(names) == len(set(names)) and sum(member.size for member in members) < 100_000_000,
                'Duplicate or oversized archive')
        for member in members:
            parts = PurePosixPath(member.name).parts
            require(member.isfile() and parts and not member.name.startswith('/') and '..' not in parts
                    and '\\' not in member.name and ':' not in member.name and parts[0] != 'var',
                    'Unsafe archive member')
            output = destination / member.name
            output.parent.mkdir(parents=True, exist_ok=True)
            with package.extractfile(member) as source, output.open('xb') as target:
                shutil.copyfileobj(source, target)
            output.chmod(0o644)
    manifest = json.loads((destination / 'release-manifest.json').read_text())
    require(set(names) == set(manifest) | {'release-manifest.json'}, 'Archive coverage mismatch')
    for relative, expected_hash in manifest.items():
        require(sha(destination / relative) == expected_hash, 'Release member checksum mismatch')
    for parent, _, _ in os.walk(destination):
        Path(parent).chmod(0o755)
    return manifest


def copy_regular(source, target):
    no_links(source)
    require(stat.S_ISREG(source.lstat().st_mode), 'Regular public metadata required')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    require(sha(source) == sha(target), 'Metadata copy mismatch')


def prepare_workspace(manifest):
    require(not LOCAL.exists() and not BACKUP.exists(), 'Prior relocation needs manual review')
    LOCAL.mkdir(mode=0o755)
    STATE.mkdir(mode=0o700)
    shutil.copytree(CODE, WORKSPACE)
    # Preserve current migration evidence and IDs, not the copying-phase catalog
    # embedded in the development archive. Only curated public release paths.
    for name in manifest:
        if name.startswith('data/') and (APP / name).is_file():
            copy_regular(APP / name, WORKSPACE / name)
    live_manifest = json.loads((APP / 'data/path-migration.json').read_text())
    for receipt in live_manifest.get('receipts', {}).values():
        reference = receipt.get('evidence', {}) if isinstance(receipt, dict) else {}
        relative, digest = reference.get('ref', ''), reference.get('sha256', '')
        if relative.startswith('data/migration-evidence/objects/'):
            require(relative == 'data/migration-evidence/objects/' + digest + '.json', 'Invalid evidence object')
            copy_regular(APP / relative, WORKSPACE / relative)
            require(sha(WORKSPACE / relative) == digest, 'Evidence hash mismatch')
    # Private state is copied only to local storage. Secrets and raw migration
    # diagnostics never enter the public release or cold snapshot manifest.
    shutil.copytree(APP / 'var', WORKSPACE / 'var', symlinks=True)
    for parent, directories, files in os.walk(LOCAL, followlinks=False):
        os.chown(parent, UID, GID)
        for name in directories + files:
            os.chown(Path(parent) / name, UID, GID, follow_symlinks=False)
    STATE.chmod(0o700)
    (WORKSPACE / 'var').chmod(0o700)
    before = json.loads((APP / 'data/catalog.json').read_text())
    for tool in ('build_catalog.py', 'build_inventory.py', 'build_research_guide.py', 'check_docs.py'):
        run([PYTHON, WORKSPACE / 'tools' / tool], user='rmp')
    after = json.loads((WORKSPACE / 'data/catalog.json').read_text())
    require({a['id']: a['path'] for a in before['assets']} == {a['id']: a['path'] for a in after['assets']},
            'Upgrade changed existing resource IDs or migrated paths')
    require(all(a['path'].startswith(('/data/share/datasets', '/data/share/models')) for a in after['assets']),
            'Stale legacy catalog')
    run([PYTHON, WORKSPACE / 'catalog.py', 'import', '--input', WORKSPACE / 'data/catalog.json',
         '--db', WORKSPACE / 'var/catalog.sqlite3'], user='rmp')
    run([PYTHON, WORKSPACE / 'tools/package_release.py'], user='rmp')
    return len(after['assets'])


def new_directory(path, uid, gid, mode):
    no_links(path)
    require(not path.exists(), 'Target already exists: ' + str(path))
    path.mkdir(mode=mode)
    os.chown(path, uid, gid)
    path.chmod(mode)
    info = path.stat()
    require((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (uid, gid, mode),
            'Permission roundtrip failed: ' + str(path))


def provision_namespaces():
    require(mount(Path('/data/share')) == {'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'},
            'Unexpected CPFS mount')
    require(grp.getgrnam('ml-readers').gr_gid == SHARED_GID, 'Shared group identity changed')
    incoming = Path('/data/share/incoming')
    targets = [incoming, Path('/data/share/datasets/managed'), Path('/data/share/models/managed')]
    require(all(not p.exists() and not p.is_symlink() for p in targets), 'Incoming/managed namespace already exists')
    new_directory(incoming, 0, SHARED_GID, 0o2755)
    members = sorted(set(grp.getgrnam('ml-readers').gr_mem) | {'rmp'})
    for name in members:
        entry = pwd.getpwnam(name)
        require(entry.pw_uid >= 1000 and '/' not in name and name not in ('.', '..'), 'Unexpected contributor identity')
        new_directory(incoming / name, entry.pw_uid, SHARED_GID, 0o2750)
    for path in targets[1:]:
        new_directory(path, UID, SHARED_GID, 0o2755)
    return {'incoming': str(incoming), 'local_member_buckets': members,
            'other_node_identity_verified': False, 'coordinator_host': HOST}


def unit_text():
    return f'''[Unit]
Description=Research Data Center (local runtime, OSS persistence)
After=network.target
RequiresMountsFor={WORKSPACE} /data/services
[Service]
Type=simple
User=rmp
Group=rmp
WorkingDirectory={WORKSPACE}
ExecStart={PYTHON} {CODE}/server.py --root {WORKSPACE} --state-dir {STATE} --db {WORKSPACE}/var/catalog.sqlite3 --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths={WORKSPACE}/var {STATE}
Nice=10
IOSchedulingClass=idle
MemoryMax=256M
CPUQuota=25%
[Install]
WantedBy=multi-user.target
'''


def install_units(installed):
    for name in NEW_UNITS:
        target = Path('/etc/systemd/system') / name
        require(not target.exists(), 'Existing service requires review: ' + name)
        copy_regular(CODE / 'deploy' / name, target)
        target.chmod(0o644)
        installed.append(name)
    UNIT.write_text(unit_text())
    UNIT.chmod(0o644)
    run(['systemctl', 'daemon-reload'])


def healthcheck():
    result = None
    for attempt in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/api/summary', timeout=5) as response:
                result = json.load(response)
            break
        except OSError:
            time.sleep(1)
    require(result and result.get('total') == 228, 'Existing catalog HTTP regression')
    for route in ('/api/ingestion/manifest', '/api/ingestion/status', '/api/ingestion/published', '/progress/'):
        with urllib.request.urlopen('http://127.0.0.1:8765' + route, timeout=20) as response:
            require(response.status == 200, 'HTTP route failed: ' + route)


def activate(args):
    require(os.geteuid() == 0 and socket.gethostname() == HOST and args.execute, 'Explicit authorized root host required')
    no_links(BOOT)
    require(BOOT.stat().st_uid == 0 and not BOOT.stat().st_mode & 0o022, 'Bootstrap directory must be root owned')
    require(not (BOOT / 'state.json').exists(), 'Previous upgrade state requires review')
    require(sha(args.archive) == args.sha256, 'Candidate changed before launch')
    state = {'started_at': now(), 'host': HOST, 'pid': os.getpid(), 'candidate_sha256': args.sha256}
    service_stopped = False
    original_inode = None
    installed_units = []
    try:
        wait_for_migration(state)
        require(not APP.is_symlink(), 'Application already relocated')
        no_links(CODE)
        no_links(LOCAL)
        require(mount(Path('/var/lib'))['fstype'] in ('xfs', 'ext4', 'btrfs'), 'Local runtime filesystem required')
        require(mount(Path('/data/share_cold')) == {'target': '/data/share_cold', 'source': 'ossfs', 'fstype': 'fuse.ossfs'},
                'Unexpected cold mount')
        require(shutil.disk_usage('/var/lib').free > 5 * 1024 ** 3, 'Insufficient local runtime space')
        require(all(not os.path.lexists(Path('/etc/systemd/system') / name) for name in NEW_UNITS),
                'Existing ingestion/backup units require review')
        save(state, 'preparing_verified_release')
        manifest = extract_release(args.archive, CODE, args.sha256)
        for directory in (Path('/opt/research-data-center'), CODE.parent):
            directory.chmod(0o755)
        shutil.copy2(UNIT, BOOT / 'previous.service')
        original_inode = inode(APP)
        # This is the existing reviewed public-evidence validator. It is run as
        # rmp and performs no publication in check mode.
        run([PYTHON, APP / 'tools/cpfs_publish_evidence.py', 'check'], user='rmp')
        # No migration worker remains. Stop catalog service before its SQLite
        # copy so the application rollback and runtime snapshots are consistent.
        run(['systemctl', 'stop', 'research-data-center.service'])
        service_stopped = True
        records = prepare_workspace(manifest)
        namespaces = provision_namespaces()
        new_directory(COLD, UID, GID, 0o755)
        run([PYTHON, CODE / 'tools/ingest_cycle.py', '--state-db', STATE / 'ingestion.sqlite3'], user='rmp')
        run([PYTHON, CODE / 'tools/cold_archive.py', '--root', WORKSPACE, '--state-dir', STATE], user='rmp')
        save(state, 'activating', records=records, namespaces=namespaces, original_app_inode=original_inode)
        install_units(installed_units)
        run(['systemctl', 'start', 'research-data-center.service'])
        healthcheck()
        require(inode(APP) == original_inode and not APP.is_symlink(), 'Application changed before alias activation')
        BACKUP.symlink_to(WORKSPACE, target_is_directory=True)
        exchange(APP, BACKUP)
        require(APP.is_symlink() and os.readlink(APP) == str(WORKSPACE) and inode(BACKUP) == original_inode,
                'Application exchange verification failed')
        run(['systemctl', 'enable', '--now', 'research-data-ingestion.timer', 'research-data-cold-backup.timer'])
        save(state, 'complete', completed_at=now(), runtime=str(WORKSPACE), state_dir=str(STATE),
             cold=str(COLD), compatibility_path=str(APP), rollback_copy=str(BACKUP),
             note='Original application retained for recovery; hot-data cleanup is managed separately.')
    except BaseException as exc:
        # Restore the original application service; never undo a successful hot
        # migration and never delete a new incoming or managed namespace.
        recovery_errors = []
        if service_stopped:
            try:
                for name in sorted(installed_units, key=lambda name: not name.endswith('.timer')):
                    command = ['systemctl', 'disable', '--now', name] if name.endswith('.timer') else ['systemctl', 'stop', name]
                    result = subprocess.run(command, capture_output=True, text=True)
                    if result.returncode:
                        recovery_errors.append(name + ': stop/disable failed: ' + result.stderr[-500:])
                run(['systemctl', 'stop', 'research-data-center.service'])
                if original_inode is not None:
                    restore_application(APP, BACKUP, WORKSPACE, original_inode)
                shutil.copy2(BOOT / 'previous.service', UNIT)
                run(['systemctl', 'daemon-reload'])
                run(['systemctl', 'start', 'research-data-center.service'])
            except BaseException as rollback_exc:
                recovery_errors.append(repr(rollback_exc))
        save(state, 'stopped_for_review', error=repr(exc), recovery_error='; '.join(recovery_errors) or None,
             last_phase=state.get('phase'))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    require(fcntl is not None, 'Linux deployment required')
    with (BOOT / 'activation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        activate(args)


if __name__ == '__main__':
    main()
