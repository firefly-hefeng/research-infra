"""Bounded, resumable copy and checksum verification. Never switches or deletes sources.

The only --delete invocation is paired with --dry-run to detect unexpected target files.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time

BASE=Path('/data/rmp/research-data-center/var/cpfs-migration-20261027')
STAGE=Path('/data/share/.rdc-migration-20261027')
ROOTS=('models','datasets')
STATE=BASE/'transfer-state.json'
EXPECTED_SOURCE_DEVICE=66305

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def save(value):
    value['updated_at']=now();p=STATE.with_suffix('.tmp')
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2));os.replace(p,STATE)
def mount_guard():
    m=json.loads(subprocess.check_output(['findmnt','-J','-T','/data/share','-o','TARGET,SOURCE,FSTYPE,OPTIONS']))['filesystems'][0]
    if m['target']!='/data/share' or m['source']!='10.0.0.202:/share' or m['fstype']!='nfs' or 'rw' not in m['options'].split(','):
        raise RuntimeError('Unexpected or non-writable CPFS mount: '+str(m))
    if os.lstat('/data/share').st_dev==EXPECTED_SOURCE_DEVICE:raise RuntimeError('Target is the local disk')
    fs=os.statvfs('/data/share')
    if fs.f_bavail*fs.f_frsize<128*1024**3 or fs.f_favail<100000:raise RuntimeError('CPFS reserve threshold reached')
    return m
def source_guard():
    for name in ROOTS:
        s=os.lstat('/data/'+name)
        if not stat.S_ISDIR(s.st_mode) or s.st_dev!=EXPECTED_SOURCE_DEVICE:
            raise RuntimeError('Source root is no longer the expected local directory: '+name)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def run(command,log,entry,state):
    entry.update(command=command,started_at=now(),log=str(log));save(state)
    with log.open('wb') as sink:
        proc=subprocess.Popen(command,stdout=sink,stderr=subprocess.STDOUT,start_new_session=True)
        entry['pid']=proc.pid;save(state)
        try:
            while proc.poll() is None:
                mount_guard();source_guard()
                entry['last_process_check_at']=now();save(state);time.sleep(20)
        except BaseException:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=20)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            raise
    entry.update(exit_code=proc.returncode,finished_at=now(),log_sha256=digest(log))
    save(state)
    if proc.returncode!=0:raise RuntimeError('rsync failed: '+str(log))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=('copy','verify'));args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError('Preserving numeric ownership requires root')
    lock=(BASE/'transfer-worker.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)  # This one orchestrator's local XFS lock, not an NFS distributed lock.
    mount=mount_guard();source_guard()
    if STATE.exists():state=json.loads(STATE.read_text())
    else:state=dict(migration_id='cpfs-20261027',stage=str(STAGE),host=os.uname().nodename,mount=mount,roots={},created_at=now())
    if state['stage']!=str(STAGE):raise RuntimeError('State directory mismatch')
    if not STAGE.exists():
        census=json.loads((BASE/'source-semantics.json').read_text())
        if not census['complete'] or any(g['xattr_counts'] for g in census['roots'].values()):raise RuntimeError('Unsupported source attributes or incomplete census')
        fs=os.statvfs('/data/share')
        if fs.f_bavail*fs.f_frsize<sum(g['unique_file_bytes'] for g in census['roots'].values())+128*1024**3:raise RuntimeError('Insufficient initial byte capacity')
        if fs.f_favail<sum(g['unique_inodes'] for g in census['roots'].values())+100000:raise RuntimeError('Insufficient initial inode capacity')
        STAGE.mkdir(mode=0o700)
        (STAGE/'migration-owner.json').write_text(json.dumps(dict(migration_id=state['migration_id'],host=state['host'],source_roots=['/data/'+n for n in ROOTS])))
    marker=json.loads((STAGE/'migration-owner.json').read_text())
    if marker['migration_id']!=state['migration_id'] or marker['host']!=state['host']:raise RuntimeError('Unrecognized staging owner')
    if STAGE.is_symlink() or STAGE.stat().st_uid!=0 or STAGE.stat().st_mode & 0o077:raise RuntimeError('Unsafe staging permissions')
    state['phase']=args.phase;state['status']='running';state['worker_pid']=os.getpid();save(state)
    if args.phase=='verify':
        state['verification_binding']={'source_manifest_sha256':digest(BASE/'source-files.jsonl.gz'),
            'staged_roots':{name:{key:getattr(os.lstat(STAGE/name),'st_'+key) for key in ('dev','ino','mode','uid','gid')} for name in ROOTS}}
        save(state)
    try:
        for name in ROOTS:
            entry=state['roots'].setdefault(name,{})
            if args.phase=='copy':
                if entry.get('copy',{}).get('status')=='passed':continue
                info=entry['copy']={'status':'running'}
                command=['rsync','-aH','--numeric-ids','--one-file-system','--bwlimit=204800','--stats','/data/'+name,str(STAGE)+'/']
                run(command,BASE/(name+'-copy.log'),info,state)
            else:
                if entry.get('copy',{}).get('status')!='passed':raise RuntimeError('Copy has not completed: '+name)
                info=entry['verification']={'status':'running'}
                command=['rsync','-aHnc','--numeric-ids','--one-file-system','--delete','--dry-run','--itemize-changes','--out-format=%i %n%L','/data/'+name+'/',str(STAGE/name)+'/']
                assert '--dry-run' in command
                log=BASE/(name+'-verification.log');run(command,log,info,state)
                if log.stat().st_size:raise RuntimeError('Verification found differences or diagnostics: '+str(log))
            info['status']='passed';save(state)
        state['status']='passed';save(state)
    except BaseException as exc:
        state['status']='failed';state['error']=repr(exc);save(state);raise

if __name__=='__main__':main()
