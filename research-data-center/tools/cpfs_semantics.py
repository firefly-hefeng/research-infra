"""Read-only inode, ownership and extended-attribute census of the saved manifest."""
import collections
import gzip
import json
import os
from pathlib import Path
import time

base = Path('/data/rmp/research-data-center/var/cpfs-migration-20261027')
started = time.time()
groups = collections.defaultdict(lambda:dict(entries=0,unique_inodes=0,unique_file_bytes=0,unique_allocated_bytes=0,
                                           xattr_counts=collections.Counter(),owners=collections.Counter(),
                                           modes=collections.Counter(),absolute_symlinks=0,relative_symlinks=0,
                                           external_absolute_symlinks=0))
seen=set(); errors=[]; special_attrs=[]; external_links=[]
with gzip.open(base/'source-files.jsonl.gz','rt') as f:
    for line in f:
        row=json.loads(line); root=row['root']; p=Path(root)/row['relative_path']; g=groups[root]
        g['entries']+=1; key=(row['dev'],row['ino']); g['owners'][f"{row['uid']}:{row['gid']}"]+=1
        g['modes'][oct(row['mode'] & 0o7777)]+=1
        if row['kind']=='symlink':
            target=row['target']
            if target.startswith('/'):
                g['absolute_symlinks']+=1
                if not any(target==r or target.startswith(r+'/') for r in ('/data/models','/data/datasets')):
                    g['external_absolute_symlinks']+=1
                    if len(external_links)<100:external_links.append(dict(path=str(p),target=target))
            else:g['relative_symlinks']+=1
        if key in seen:continue
        seen.add(key);g['unique_inodes']+=1
        if row['kind']=='file':
            g['unique_file_bytes']+=row['size'];g['unique_allocated_bytes']+=row['blocks']*512
        try:
            attrs=os.listxattr(p,follow_symlinks=False)
            for name in attrs:g['xattr_counts'][name]+=1
            if attrs and len(special_attrs)<100:special_attrs.append(dict(path=str(p),names=attrs))
        except OSError as exc:errors.append(dict(path=str(p),error=str(exc)))
for root,g in groups.items():
    for k in ('xattr_counts','owners','modes'):g[k]=dict(g[k])
result=dict(complete=not errors,elapsed_seconds=time.time()-started,roots=dict(groups),
            attribute_samples=special_attrs,external_link_samples=external_links,errors=errors)
(base/'source-semantics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(dict(output=str(base/'source-semantics.json'),complete=result['complete'])))
