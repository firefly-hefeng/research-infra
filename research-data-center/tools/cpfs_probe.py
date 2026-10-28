"""Exercise only freshly created private scratch paths; retain proof for inspection."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import uuid

mount = json.loads(subprocess.check_output(['findmnt','-J','-T','/data/share','-o','TARGET,SOURCE,FSTYPE,OPTIONS']))['filesystems'][0]
assert mount['target'] == '/data/share' and mount['source'] == '10.0.0.202:/share' and mount['fstype'] == 'nfs', mount
shared = Path('/data/share') / ('.rdc-probe-' + uuid.uuid4().hex)
local = Path('/data/rmp/research-data-center/var') / ('cpfs-probe-' + uuid.uuid4().hex)
shared.mkdir(mode=0o700)
local.mkdir(mode=0o700)
result = dict(mount=mount, shared_probe=str(shared), local_probe=str(local), tests={})
def run(name, action):
    try:
        result['tests'][name] = dict(ok=True, detail=action())
    except Exception as exc:
        result['tests'][name] = dict(ok=False, error=repr(exc))
def basic():
    p=shared/'file'; p.write_bytes(b'CPFS migration capability probe\n')
    with p.open('rb') as f: os.fsync(f.fileno())
    os.chmod(p,0o640); os.chown(p,1011,992)
    os.utime(p, ns=(1700000000123456789,1700000000123456789))
    s=p.stat(); assert (s.st_uid,s.st_gid,s.st_mode & 0o777)==(1011,992,0o640)
    return dict(uid=s.st_uid,gid=s.st_gid,mode=oct(s.st_mode & 0o777),mtime_ns=s.st_mtime_ns)
def links():
    os.link(shared/'file',shared/'hardlink'); os.symlink('file',shared/'symlink')
    assert (shared/'hardlink').stat().st_ino==(shared/'file').stat().st_ino
    return dict(nlink=(shared/'file').stat().st_nlink,symlink=os.readlink(shared/'symlink'))
def xattrs():
    os.setxattr(shared/'file','user.rdc-probe',b'probe'); assert os.getxattr(shared/'file','user.rdc-probe')==b'probe'
    return os.listxattr(shared/'file')
def acl():
    p=subprocess.run(['setfacl','-m','u:1011:r--',str(shared/'hardlink')],capture_output=True,text=True)
    if p.returncode: raise RuntimeError(p.stderr)
    return subprocess.check_output(['getfacl','-cp',str(shared/'hardlink')],text=True)
def directory_rename():
    p=shared/'dir-before';p.mkdir();(p/'child').write_bytes(b'probe')
    p.rename(shared/'dir-after');assert (shared/'dir-after'/'child').read_bytes()==b'probe'
    return True
def sparse():
    p=shared/'sparse'
    with p.open('wb') as f: f.seek(1024*1024);f.write(b'x')
    s=p.stat();return dict(size=s.st_size,allocated=s.st_blocks*512)
def exchange():
    a=local/'original';a.mkdir();(a/'proof').write_bytes(b'probe')
    b=local/'alias';b.symlink_to(str(shared))
    libc=ctypes.CDLL(None,use_errno=True)
    rc=libc.renameat2(-100,os.fsencode(a),-100,os.fsencode(b),2)
    if rc: raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
    assert a.is_symlink() and (b/'proof').read_bytes()==b'probe'
    return True
def noreplace():
    a=shared/'noreplace-source';a.mkdir();(a/'proof').write_bytes(b'probe')
    b=shared/'noreplace-target'
    libc=ctypes.CDLL(None,use_errno=True)
    rc=libc.renameat2(-100,os.fsencode(a),-100,os.fsencode(b),1)
    if rc:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
    a.mkdir();(a/'other').write_bytes(b'keep')
    rc=libc.renameat2(-100,os.fsencode(a),-100,os.fsencode(b),1)
    assert rc==-1 and ctypes.get_errno()==17 and (a/'other').read_bytes()==b'keep' and (b/'proof').read_bytes()==b'probe'
    return True
def empty_reservation():
    a=shared/'reserved-source';a.mkdir();(a/'proof').write_bytes(b'probe')
    source_inode=a.stat().st_ino
    b=shared/'reserved-target';b.mkdir(mode=0o700)
    os.rename(a,b)
    assert not a.exists() and b.stat().st_ino==source_inode and (b/'proof').read_bytes()==b'probe'
    return True
for name,fn in [('basic',basic),('links',links),('xattrs',xattrs),('acl',acl),('nonempty_directory_rename',directory_rename),('sparse',sparse),('local_directory_symlink_exchange',exchange),('cpfs_noreplace_publish',noreplace),('cpfs_replace_own_empty_reservation',empty_reservation)]:
    run(name,fn)
print(json.dumps(result,ensure_ascii=False,indent=2))
