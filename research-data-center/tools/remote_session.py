"""Interactive SSH transport; credentials are accepted only through hidden stdin."""
import base64
import getpass
import json
import sys
import shlex
from pathlib import Path
import paramiko

sys.stdout.reconfigure(encoding='utf-8')
client = paramiko.SSHClient()
client.load_system_host_keys()
known = Path.home() / '.ssh' / 'known_hosts'
if known.exists():
    client.load_host_keys(str(known))
# Accept the user-provided host for this session; never persist credentials.
client.set_missing_host_key_policy(paramiko.WarningPolicy())
password = getpass.getpass('SSH password (hidden): ')
client.connect('101.132.97.146', username='rmp', password=password, timeout=20, look_for_keys=False, allow_agent=False)
print('SSH_READY', flush=True)
for line in sys.stdin:
    try:
        req = json.loads(line)
        if req.get('action') == 'close':
            break
        if req.get('action') == 'get':
            with client.open_sftp() as sftp:
                Path(req['local']).parent.mkdir(parents=True, exist_ok=True)
                sftp.get(req['remote'], req['local'])
            result = {'downloaded': req['local']}
        elif req.get('action') == 'put':
            with client.open_sftp() as sftp:
                sftp.put(req['local'], req['remote'])
            result = {'uploaded': req['remote']}
        else:
            command = req['command']
            if req.get('sudo'):
                command = 'sudo -S -p "" -- sh -c ' + shlex.quote(command)
            inp, out, err = client.exec_command(command, timeout=req.get('timeout', 60))
            if req.get('sudo'):
                inp.write(password + '\n')
                inp.flush()
            result = {'stdout': out.read().decode('utf-8', 'replace'), 'stderr': err.read().decode('utf-8', 'replace'), 'exit_code': out.channel.recv_exit_status()}
            if req.get('save'):
                Path(req['save']).parent.mkdir(parents=True, exist_ok=True)
                Path(req['save']).write_text(result['stdout'], encoding='utf-8')
                result['stdout'] = 'Saved to ' + req['save']
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({'error': str(exc)}), flush=True)
client.close()
