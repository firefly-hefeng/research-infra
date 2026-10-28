"""Reviewed operator transaction: publish verified copies, exchange aliases, then reclaim.

No operation is performed on import. switch/cleanup require an explicit --execute.
The source and target identities are fixed for this one migration, never user paths.
"""
import argparse
import ctypes
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

from cpfs_transfer import BASE, STAGE, mount_guard, digest
from cpfs_revalidate import ROOT_IDS, ROLLBACK, audit, reject_nested_mounts

JOURNAL=BASE/'cutover-state.json'
NAMES=('models','datasets')
PYTHON='/data/services/miniforge3/bin/python'

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def save(data):
    data['updated_at']=now();tmp=JOURNAL.with_suffix('.tmp')
    with tmp.open('w') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,JOURNAL);sync_dir(JOURNAL.parent)
def identity(path):
    s=os.lstat(path)
    return dict(dev=s.st_dev,ino=s.st_ino,mode=s.st_mode,uid=s.st_uid,gid=s.st_gid)
def same_inode(path,expected):
    s=os.lstat(path)
    return (s.st_dev,s.st_ino)==(expected['dev'],expected['ino']) and stat.S_ISDIR(s.st_mode)
def expected_original(path,name):
    s=os.lstat(path)
    return stat.S_ISDIR(s.st_mode) and (s.st_dev,s.st_ino)==ROOT_IDS[name]
def verify_gate(journal=None):
    state=json.loads((BASE/'transfer-state.json').read_text())
    if state.get('phase')!='verify' or state.get('status')!='passed':raise RuntimeError('Checksum phase not passed')
    binding=state.get('verification_binding',{})
    if binding.get('source_manifest_sha256')!=digest(BASE/'source-files.jsonl.gz'):raise RuntimeError('Source manifest verification binding changed')
    for name in NAMES:
        place=STAGE/name
        if not os.path.lexists(place):
            row=(journal or {}).get('roots',{}).get(name,{})
            if row.get('publication') not in ('prepared','rename_started','published'):
                raise RuntimeError('Missing staged root without publication journal')
            place=Path('/data/share')/name
        if identity(place)!=binding['staged_roots'][name]:raise RuntimeError('Verified root identity or permissions changed')
        for phase in ('copy','verification'):
            rec=state['roots'][name][phase]
            log=BASE/(name+('-copy.log' if phase=='copy' else '-verification.log'))
            if rec.get('status')!='passed' or rec.get('exit_code')!=0 or rec.get('log')!=str(log) or rec.get('log_sha256')!=digest(log):
                raise RuntimeError('Invalid '+name+' '+phase+' receipt')
            if phase=='verification' and (log.stat().st_size or '--dry-run' not in rec['command'] or '-aHnc' not in rec['command']):
                raise RuntimeError('Not a clean checksum dry run')
    links=json.loads((BASE/'link-audit.json').read_text())
    if (links.get('passed') is not True or links.get('complete') is not True
            or links.get('source_manifest_sha256')!=binding['source_manifest_sha256']):
        raise RuntimeError('Relative symlink relocation audit missing, stale or not passed')
    return state
def usage_gate(tag):
    output=BASE/(tag+'.json')
    subprocess.run([PYTHON,str(BASE.parent/'cpfs_usage.py'),output.name],stdout=subprocess.DEVNULL,check=True)
    report=json.loads(output.read_text())
    if report['processes'] or report['errors'] or report.get('mount_aliases'):
        raise RuntimeError('Original inodes are in use or visibility is incomplete: '+str(output))
    return report
def source_gate(location,tag):
    report=audit(location)
    (BASE/(tag+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:raise RuntimeError('Original source changed: '+tag)
    return report
def alias_gate(journal):
    mount_guard()
    for name in NAMES:
        old=Path('/data')/name;new=Path('/data/share')/name
        if not old.is_symlink() or os.readlink(old)!=str(new) or not same_inode(new,journal['roots'][name]['destination_inode']):
            raise RuntimeError('Canonical or compatibility location changed: '+name)
        if old.resolve()!=new or identity(new)['uid']!=0:raise RuntimeError('Alias resolution or owner mismatch')
def exchange(old,new):
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.renameat2(-100,os.fsencode(old),-100,os.fsencode(new),2):
        code=ctypes.get_errno();raise OSError(code,os.strerror(code))

def publish(journal,name):
    row=journal['roots'][name];source=STAGE/name;target=Path('/data/share')/name
    if 'destination_inode' not in row:
        if not source.is_dir() or source.is_symlink():raise RuntimeError('Missing staged root')
        row['destination_inode']=identity(source);row['publication']='prepared';save(journal)
    if os.path.lexists(target) and same_inode(target,row['destination_inode']):
        if os.path.lexists(source):raise RuntimeError('Both staged and published roots exist')
        row['publication']='published';save(journal);return
    if not same_inode(source,row['destination_inode']):raise RuntimeError('Staging identity changed')
    if 'reservation_inode' not in row:
        # mkdir is exclusive; never take over an existing central library directory.
        target.mkdir(mode=0o700)
        row['reservation_inode']=identity(target);save(journal)
    if not same_inode(target,row['reservation_inode']):raise RuntimeError('Reservation identity changed')
    info=identity(target)
    if info['uid']!=0 or stat.S_IMODE(info['mode'])!=0o700 or any(target.iterdir()):raise RuntimeError('Reservation not private and empty')
    mount_guard();reject_nested_mounts((source,target))
    row['publication']='rename_started';save(journal)
    try:os.rename(source,target)
    except OSError:
        # NFS can report an error after the server completed a rename.
        if os.path.lexists(source) or not os.path.lexists(target) or not same_inode(target,row['destination_inode']):raise
    if os.path.lexists(source) or not same_inode(target,row['destination_inode']):raise RuntimeError('Published inode mismatch')
    sync_dir('/data/share');sync_dir(STAGE)
    row['publication']='published';row['published_at']=now();save(journal)

def switch(journal):
    verify_gate(journal);mount_guard()
    if any(row.get('switch')=='switched' for row in journal['roots'].values()):
        raise RuntimeError('Partial switch requires explicit recovery review; never blindly exchange twice')
    source_gate('source','source-before-switch');usage_gate('usage-before-switch')
    if not ROLLBACK.exists():ROLLBACK.mkdir(mode=0o700)
    rb=identity(ROLLBACK)
    if ROLLBACK.is_symlink() or rb['dev']!=66305 or rb['uid']!=0 or stat.S_IMODE(rb['mode'])!=0o700:raise RuntimeError('Unsafe rollback parent')
    reject_nested_mounts((ROLLBACK,))
    for name in NAMES:publish(journal,name)
    for name in NAMES:
        old=Path('/data')/name;backup=ROLLBACK/name;new=Path('/data/share')/name;row=journal['roots'][name]
        if not expected_original(old,name):raise RuntimeError('Original root inode changed')
        if not os.path.lexists(backup):backup.symlink_to(new)
        if not backup.is_symlink() or os.readlink(backup)!=str(new):raise RuntimeError('Rollback slot already occupied')
        row['switch']='exchange_started';save(journal)
        exchange(old,backup);sync_dir('/data');sync_dir(ROLLBACK)
        if not old.is_symlink() or os.readlink(old)!=str(new) or not expected_original(backup,name):raise RuntimeError('Exchange topology mismatch')
        row['switch']='switched';row['switched_at']=now();save(journal)
    alias_gate(journal)
    source_gate('rollback','source-after-switch')
    usage_gate('usage-after-switch')
    journal['phase']='switched';journal['switched_at']=now();save(journal)

def cleanup(journal):
    if journal.get('phase') not in ('switched','cleaning','cleaned'):raise RuntimeError('Both roots must be fully switched')
    alias_gate(journal);reject_nested_mounts((ROLLBACK,))
    if journal.get('phase')=='cleaning':raise RuntimeError('Interrupted deletion requires remaining-tree review; automatic resume is disabled')
    if journal.get('phase')=='cleaned':return
    if not shutil.rmtree.avoids_symlink_attacks:raise RuntimeError('fd-safe rmtree required')
    if journal.get('phase')=='switched':
        source_gate('rollback','source-before-cleanup');usage_gate('usage-before-cleanup')
        # The caller must have verified ordinary-account access after the switch.
        receipt=json.loads((BASE/'destination-entry-observations.json').read_text())
        baseline_file=BASE/'catalog-baseline.json'
        if digest(baseline_file)!='5c05f387cf328e27367380a28db9fad9e8a92fd9e301349babfa4eaf9d903871':raise RuntimeError('Unexpected asset baseline')
        baseline=json.loads(baseline_file.read_text())
        expected_paths={a['path'].replace('/data/','/data/share/',1) for a in baseline['assets']}
        rows=receipt.get('observations',[])
        if (receipt.get('complete') is not True or len(rows)!=len(expected_paths)
                or {x.get('path') for x in rows}!=expected_paths
                or receipt.get('host')!=journal['host'] or receipt.get('account')!='rmp' or receipt.get('observer_uid')!=1011
                or dt.datetime.fromisoformat(receipt['observed_at'])<dt.datetime.fromisoformat(journal['switched_at'])
                or not all(x.get('readable') is True and x.get('exists') is True for x in rows)):
            raise RuntimeError('All 221 destination entry observations are required')
        journal['phase']='cleaning';journal['cleanup_started_at']=now()
        fs=os.statvfs('/data');journal['local_available_before_cleanup']=fs.f_bavail*fs.f_frsize;save(journal)
    for name in NAMES:
        row=journal['roots'][name];backup=ROLLBACK/name
        if row.get('cleanup')=='deleted':continue
        alias_gate(journal);reject_nested_mounts((ROLLBACK,));usage_gate('usage-before-delete-'+name)
        if os.path.lexists(backup):
            if not expected_original(backup,name):raise RuntimeError('Refusing to delete a non-original tree')
            row['cleanup']='delete_started';save(journal)
            shutil.rmtree(backup)
            sync_dir(ROLLBACK)
        elif row.get('cleanup')!='delete_started':raise RuntimeError('Original tree disappeared without a recorded deletion')
        row['cleanup']='deleted';row['deleted_at']=now();save(journal)
    alias_gate(journal)
    fs=os.statvfs('/data');journal['local_available_after_cleanup']=fs.f_bavail*fs.f_frsize
    journal['phase']='cleaned';journal['cleaned_at']=now();save(journal)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=('check','switch','cleanup'));parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError('Root required')
    lock=(BASE/'transfer-worker.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if args.phase!='check' and not args.execute:raise RuntimeError('Explicit --execute required')
    if JOURNAL.exists():journal=json.loads(JOURNAL.read_text())
    else:journal=dict(migration_id='cpfs-20261027',host=os.uname().nodename,created_at=now(),phase='prepared',roots={n:{} for n in NAMES})
    if journal['migration_id']!='cpfs-20261027' or journal['host']!=os.uname().nodename:raise RuntimeError('Wrong transaction')
    if args.phase=='check':verify_gate();source_gate('source','source-final-check');usage_gate('usage-final-check')
    elif args.phase=='switch':switch(journal)
    else:cleanup(journal)
    print(json.dumps(journal,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
