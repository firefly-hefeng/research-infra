"""One-shot continuation of this authorized transfer; verification only, no cutover."""
import fcntl
import json
from pathlib import Path
import subprocess
import time

base=Path('/data/rmp/research-data-center/var/cpfs-migration-20261027')
lock=(base/'verify-continuation.lock').open('a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
while True:
    state=json.loads((base/'transfer-state.json').read_text())
    if state.get('migration_id')!='cpfs-20261027':raise RuntimeError('Wrong transfer')
    if state.get('status')=='failed':raise RuntimeError('Transfer failed; source retained')
    if state.get('phase')=='verify':
        print('Verification already started; no duplicate worker.',flush=True);break
    if state.get('phase')=='copy' and state.get('status')=='passed':
        if not all(state['roots'][n]['copy']['status']=='passed' for n in ('datasets','models')):
            raise RuntimeError('Incomplete copy receipts')
        subprocess.run(['/data/services/miniforge3/bin/python',str(base.parent/'cpfs_transfer.py'),'verify'],check=True)
        print('Both roots checksum verified. Cutover has NOT been executed.',flush=True);break
    time.sleep(30)
