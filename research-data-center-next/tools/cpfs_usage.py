"""Match live descriptors/maps by inode, including bind mounts and external hard links."""
import collections
import datetime as dt
import gzip
import json
import os
from pathlib import Path
import pwd
import sys

base=Path('/data/rmp/research-data-center/var/cpfs-migration-20261027')
known={}; counts=collections.Counter(); nlinks={}; sizes={}
with gzip.open(base/'source-files.jsonl.gz','rt') as f:
    for line in f:
        row=json.loads(line); key=(row['dev'],row['ino'])
        known.setdefault(key,row['root']+'/'+row['relative_path'])
        if row['kind']=='file':counts[key]+=1;nlinks[key]=row['nlink'];sizes[key]=row['blocks']*512
for root,inode in (('/data/models',2147483776),('/data/datasets',131)):
    known[(66305,inode)]=root
result=dict(observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),host=os.uname().nodename,
            visibility='local_host_only_inode_match',processes=[],errors=[],mount_aliases=[],
            source_inodes_with_external_hardlinks=sum(nlinks[k]>v for k,v in counts.items()),
            allocated_bytes_with_no_external_hardlinks=sum(sizes[k] for k,v in counts.items() if nlinks[k]==v))
namespaces=set()
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
    try:
        refs=[];uid=proc.stat().st_uid;comm=(proc/'comm').read_text().strip()
        namespace=os.readlink(proc/'ns/mnt')
        if namespace not in namespaces:
            mount_lines=(proc/'mountinfo').read_text().splitlines()
            for line in mount_lines:
                fields=line.split();major,minor=(int(x) for x in fields[2].split(':'))
                mounted_root=fields[3]
                if os.makedev(major,minor)==66305 and any(mounted_root==r or mounted_root.startswith(r+'/') for r in ('/datasets','/models','/.rdc-rollback-20261027/datasets','/.rdc-rollback-20261027/models')):
                    result['mount_aliases'].append(dict(pid=int(proc.name),namespace=namespace,root=mounted_root,mountpoint=fields[4]))
            namespaces.add(namespace)
        for item in [proc/'cwd',proc/'root',proc/'exe',*(proc/'fd').iterdir()]:
            try:
                s=os.stat(item);key=(s.st_dev,s.st_ino)
                if key not in known:continue
                if item.name in ('cwd','root','exe'):access=item.name
                else:
                    info=(proc/'fdinfo'/item.name).read_text()
                    flags=next(int(x.split()[1],8) for x in info.splitlines() if x.startswith('flags:'))
                    access={0:'read',1:'write',2:'read_write'}.get(flags&3,'unknown')
                refs.append(dict(kind=item.name if item.name in ('cwd','root','exe') else 'fd',source_path=known[key],
                                 observed_path=os.readlink(item),access=access,inode=s.st_ino))
            except (FileNotFoundError,ProcessLookupError):pass
            except PermissionError as exc:result['errors'].append(dict(pid=int(proc.name),error=str(exc)))
        for line in (proc/'maps').read_text().splitlines():
            fields=line.split(None,5)
            if len(fields)<5:continue
            major,minor=(int(x,16) for x in fields[3].split(':'));key=(os.makedev(major,minor),int(fields[4]))
            if key in known:
                refs.append(dict(kind='mmap',source_path=known[key],observed_path=fields[5] if len(fields)>5 else '',
                                 permissions=fields[1],shared_writable='w' in fields[1] and 's' in fields[1]))
        if refs:
            try:user=pwd.getpwuid(uid).pw_name
            except KeyError:user=str(uid)
            result['processes'].append(dict(pid=int(proc.name),uid=uid,user=user,comm=comm,references=refs))
    except (FileNotFoundError,ProcessLookupError):pass
    except Exception as exc:result['errors'].append(dict(pid=int(proc.name),error=repr(exc)))
target=base/(sys.argv[1] if len(sys.argv)>1 else 'inode-usage-before.json')
target.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
