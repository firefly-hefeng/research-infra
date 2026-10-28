"""One-shot, fail-closed continuation of the explicitly authorized CPFS migration.

Waits for the existing verification worker; never launches another copy. A sealed
policy pins the reviewed scripts and installed application release before any
cutover. Any exception stops the workflow for operator review, with data retained
wherever the last durably journaled operation left it. No automatic retries.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

APP = Path('/data/rmp/research-data-center')
BASE = APP / 'var/cpfs-migration-20261027'
PYTHON = '/data/services/miniforge3/bin/python'
HOST = 'iZuf6jc6bqdgxmhcci4k3wZ'
MIGRATION = 'cpfs-20261027'
STATE = BASE / 'finalization-state.json'
REQUIRED_PINS = {'var/cpfs_cutover.py', 'var/cpfs_revalidate.py', 'var/cpfs_usage.py',
                 'var/cpfs_transfer.py', 'var/cpfs_observe_destination.py',
                 'tools/cpfs_publish_evidence.py', 'tools/path_migration.py',
                 'tools/build_catalog.py', 'tools/build_inventory.py',
                 'tools/build_research_guide.py', 'tools/research_annotations.py',
                 'tools/check_docs.py', 'tools/verify_deployment.py',
                 'tools/collect_metadata.py', 'data/collection-config.json',
                 'catalog.py', 'release-manifest.json'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(state, phase, **values):
    state.update(phase=phase, updated_at=now(), **values)
    temporary = STATE.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.chown(temporary, 0, 1011)
    os.chmod(temporary, 0o640)
    os.replace(temporary, STATE)
    fd = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check_pins(policy):
    if policy.get('migration_id') != MIGRATION or policy.get('host') != HOST:
        raise RuntimeError('Policy belongs to another migration or host')
    if set(policy.get('pins', {})) != REQUIRED_PINS:
        raise RuntimeError('Policy must pin the exact reviewed execution surface')
    for relative, expected in policy['pins'].items():
        path = APP / relative
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) or sha(path) != expected:
            raise RuntimeError('Reviewed code or release changed: ' + relative)
    release = json.loads((APP / 'release-manifest.json').read_text())
    for relative, expected in release.items():
        path = APP / relative
        if (Path(relative).is_absolute() or '..' in Path(relative).parts
                or path.is_symlink() or not path.resolve().is_relative_to(APP)
                or not stat.S_ISREG(path.lstat().st_mode) or sha(path) != expected):
            raise RuntimeError('Installed release content changed: ' + relative)


def run(arguments, account=None):
    command = (["/usr/sbin/runuser", '-u', account, '--'] if account else []) + arguments
    with (BASE / 'finalization-run.log').open('a') as log:
        log.write('\n' + now() + ' ' + json.dumps(arguments) + '\n')
        log.flush()
        subprocess.run(command, cwd=APP, stdin=subprocess.DEVNULL,
                       stdout=log, stderr=subprocess.STDOUT, check=True)


def allow_receipt_reads():
    # Only receipts consumed by the ordinary-account observer/publisher. Never
    # recursively change ownership or expose raw process/file diagnostics.
    names = ('transfer-state.json', 'cutover-state.json', 'models-copy.log',
             'datasets-copy.log', 'models-verification.log', 'datasets-verification.log',
             'link-audit.json', 'source-semantics.json', 'source-before-switch.json',
             'source-after-switch.json', 'source-before-cleanup.json',
             'usage-before-switch.json', 'usage-after-switch.json',
             'usage-before-cleanup.json', 'usage-before-delete-models.json',
             'usage-before-delete-datasets.json')
    for name in names:
        path = BASE / name
        if path.exists():
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise RuntimeError('Unexpected receipt file: ' + name)
            os.chown(path, 0, 1011)
            os.chmod(path, 0o640)


def wait_verified(state):
    deadline = time.monotonic() + 48 * 3600
    while True:
        transfer = json.loads((BASE / 'transfer-state.json').read_text())
        if transfer.get('migration_id') != MIGRATION or transfer.get('host') != HOST:
            raise RuntimeError('Unexpected transfer identity')
        if transfer.get('status') == 'failed':
            raise RuntimeError('Copy or verification failed; no cutover attempted')
        if transfer.get('phase') == 'verify' and transfer.get('status') == 'passed':
            return
        if transfer.get('phase') not in ('copy', 'verify') or transfer.get('status') not in ('running', 'passed'):
            raise RuntimeError('Unexpected transfer state')
        if transfer.get('status') == 'running':
            os.kill(int(transfer['worker_pid']), 0)
        if time.monotonic() > deadline:
            raise RuntimeError('Transfer wait exceeded 48 hours; manual review required')
        save(state, 'waiting_for_verification', transfer_phase=transfer['phase'])
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute or os.geteuid() != 0 or os.uname().nodename != HOST:
        raise RuntimeError('Explicit execution as root on the authorized host is required')
    os.umask(0o077)
    with (BASE / 'finalization.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_locked()


def run_locked():
    if STATE.exists():
        raise RuntimeError('Prior finalizer state exists; inspect it before any restart')
    policy_path = BASE / 'finalization-policy.json'
    info = policy_path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Unsealed finalization policy')
    policy = json.loads(policy_path.read_text())
    check_pins(policy)
    state = dict(migration_id=MIGRATION, host=HOST, started_at=now(), worker_pid=os.getpid())
    try:
        wait_verified(state)
        check_pins(policy)
        if (BASE / 'cutover-state.json').exists():
            raise RuntimeError('Pre-existing cutover journal requires explicit operator review')
        save(state, 'switching')
        run([PYTHON, str(APP / 'var/cpfs_cutover.py'), 'switch', '--execute'])
        allow_receipt_reads()
        save(state, 'checking_ordinary_account')
        run([PYTHON, str(APP / 'var/cpfs_observe_destination.py')], 'rmp')
        check_pins(policy)
        run([PYTHON, str(APP / 'tools/cpfs_publish_evidence.py'), 'check'], 'rmp')
        save(state, 'reclaiming_verified_originals')
        run([PYTHON, str(APP / 'var/cpfs_cutover.py'), 'cleanup', '--execute'])
        allow_receipt_reads()
        # Refresh the observation after cleanup: its journal hash and timing must
        # describe the completed state, not claim a pre-cleanup check is current.
        run([PYTHON, str(APP / 'var/cpfs_observe_destination.py')], 'rmp')
        check_pins(policy)
        save(state, 'updating_catalog')
        run([PYTHON, str(APP / 'tools/cpfs_publish_evidence.py'), 'publish'], 'rmp')
        collection_code = (
            "import json; from pathlib import Path; from tools.path_migration import destination_path; "
            "p=Path('data/collection-config.json'); cfg=json.loads(p.read_text()); "
            "baseline=json.loads(Path('data/sources/catalog-pre-migration.json').read_text()); "
            "assert cfg['location_mode']=='legacy'; "
            "assert set(cfg['paths'])=={a['path'] for a in baseline['assets']}; "
            "cfg['paths']=[destination_path(p) for p in cfg['paths']]; "
            "cfg['model_roots']=[destination_path(p) for p in cfg['model_roots']]; "
            "cfg['location_mode']='shared'; "
            "temp=p.with_suffix('.tmp'); temp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)); "
            "temp.replace(p)"
        )
        run([PYTHON, '-c', collection_code], 'rmp')
        for script in ('build_catalog.py', 'build_inventory.py', 'build_research_guide.py', 'check_docs.py'):
            run([PYTHON, str(APP / 'tools' / script)], 'rmp')
        backup_code = (
            "import sqlite3; from pathlib import Path; "
            "base=Path('/data/rmp/research-data-center'); "
            "src=sqlite3.connect('file:'+str(base/'var/catalog.sqlite3')+'?mode=ro',uri=True); "
            "dst=sqlite3.connect(base/'var/cpfs-migration-20261027/catalog-before-activation.sqlite3'); "
            "src.backup(dst); assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
            "dst.close(); src.close()"
        )
        run([PYTHON, '-c', backup_code], 'rmp')
        run([PYTHON, str(APP / 'catalog.py'), 'import', '--input', 'data/catalog.json',
             '--db', 'var/catalog.sqlite3'], 'rmp')
        run([PYTHON, str(APP / 'tools/verify_deployment.py')], 'rmp')
        journal = json.loads((BASE / 'cutover-state.json').read_text())
        if journal.get('phase') != 'cleaned':
            raise RuntimeError('Unexpected final cleanup state')
        save(state, 'complete', completed_at=now(),
             available_before_bytes=journal['local_available_before_cleanup'],
             available_after_bytes=journal['local_available_after_cleanup'],
             available_space_increase_bytes=(journal['local_available_after_cleanup'] -
                                             journal['local_available_before_cleanup']))
    except BaseException as error:
        save(state, 'stopped_for_review', error=repr(error), last_phase=state.get('phase'))
        raise


if __name__ == '__main__':
    main()
