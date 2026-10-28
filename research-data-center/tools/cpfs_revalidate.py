"""Compare every source inode to the original snapshot without following symlinks."""
import argparse
import collections
import datetime as dt
import gzip
import json
import os
import re
from pathlib import Path
import stat
import time

BASE=Path('/data/rmp/research-data-center/var/cpfs-migration-20261027')
ROLLBACK=Path('/data/.rdc-rollback-20261027')
ROOT_IDS={'datasets':(66305,131),'models':(66305,2147483776)}
ROOT_METADATA={name:{'mode':0o40755,'uid':0,'gid':0} for name in ROOT_IDS}
ROOT_XATTRS={name:() for name in ROOT_IDS}

def reject_nested_mounts(roots):
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        mount=re.sub(r'\\([0-7]{3})',lambda m:chr(int(m.group(1),8)),line.split()[4])
        if any(mount==str(r) or mount.startswith(str(r)+'/') for r in roots):
            raise RuntimeError('Unexpected nested mount: '+mount)

def audit(location):
    started=time.monotonic();errors=[];expected=collections.Counter();actual=collections.Counter()
    roots={name:(Path('/data')/name if location=='source' else ROLLBACK/name) for name in ROOT_IDS}
    reject_nested_mounts(roots.values())
    for name,root in roots.items():
        s=os.lstat(root)
        if not stat.S_ISDIR(s.st_mode) or (s.st_dev,s.st_ino)!=ROOT_IDS[name]:raise RuntimeError('Unexpected original source inode: '+str(root))
        if any(getattr(s,'st_'+key)!=value for key,value in ROOT_METADATA[name].items()):
            raise RuntimeError('Unexpected original source root metadata: '+str(root))
        if tuple(sorted(os.listxattr(root,follow_symlinks=False)))!=tuple(sorted(ROOT_XATTRS[name])):
            raise RuntimeError('Unexpected original root extended attributes: '+str(root))
    def fail(path,error):
        if len(errors)<1000:errors.append(dict(path=str(path),error=error))
    with gzip.open(BASE/'source-files.jsonl.gz','rt') as f:
        for line in f:
            row=json.loads(line);name=Path(row['root']).name;p=roots[name]/row['relative_path'];expected[name]+=1
            try:
                s=os.lstat(p)
                for key in ('dev','ino','mode','uid','gid','size','mtime_ns','ctime_ns','nlink'):
                    if getattr(s,'st_'+key)!=row[key]:fail(p,'changed_'+key);break
                if row['kind']=='symlink' and os.readlink(p)!=row['target']:fail(p,'changed_link_target')
            except OSError as exc:fail(p,str(exc))
    # Detect additions as well as changes/deletions to recorded entries.
    for name,root in roots.items():
        queue=[root]
        while queue:
            current=queue.pop()
            try:
                with os.scandir(current) as it:
                    for ent in it:
                        actual[name]+=1
                        if ent.is_dir(follow_symlinks=False):
                            s=ent.stat(follow_symlinks=False)
                            if s.st_dev!=ROOT_IDS[name][0]:fail(ent.path,'unexpected_mount_device')
                            else:queue.append(Path(ent.path))
            except OSError as exc:fail(current,str(exc))
        if actual[name]!=expected[name]:fail(root,'entry_count_changed')
    return dict(observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),host=os.uname().nodename,
                location=location,passed=not errors,errors=errors,expected_entries=dict(expected),
                actual_entries=dict(actual),elapsed_seconds=time.monotonic()-started)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('location',choices=('source','rollback'));parser.add_argument('--output',required=True)
    args=parser.parse_args();result=audit(args.location)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
