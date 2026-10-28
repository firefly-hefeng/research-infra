"""Explicit operator installer for the dedicated three-server read-only monitor.

Passwords are prompted invisibly and remain in memory. Only the dedicated probe,
restricted key line, private monitor key and two new systemd units are installed.
"""
import argparse
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CENTRAL = '101.132.97.146'
HOSTS = (CENTRAL, '47.117.138.84', '139.196.25.53')
BOOTSTRAP = '/var/lib/research-data-center-monitor/bootstrap'
KEYDIR = '/var/lib/research-data-center/state/monitor-ssh'
WORKSPACE = '/var/lib/research-data-center/workspace'
PYTHON = '/data/services/miniforge3/bin/python'
FILES = ('platform_data.py', 'tools/collect_server_resources.py', 'tools/install_monitor_access.py', 'tools/server_resource_probe.py')


def command(client, code, password=None, timeout=45, python='/usr/bin/python3'):
    args = ([python, '-c', code] if password is None else ['sudo', '-k', '-S', '-p', '', '--', python, '-c', code])
    stdin, stdout, stderr = client.exec_command(' '.join(shlex.quote(value) for value in args), timeout=timeout)
    if password is not None:
        stdin.write(password + '\n');stdin.flush()
    stdin.channel.shutdown_write()
    output = stdout.read(262145)
    error = stderr.read(8193)
    status = stdout.channel.recv_exit_status()
    if status:
        # Never print arbitrary command output, environment or secret-bearing input.
        last = error.decode('utf-8', errors='replace').strip().splitlines()
        category = last[-1].split(':', 1)[0][:80] if last else 'no_stderr'
        raise RuntimeError('remote_operation_failed_' + str(status) + ':' + category)
    if len(output) > 262144:
        raise RuntimeError('remote_response_too_large')
    return json.loads(output) if output.strip() else {}


def bootstrap(client, password, stage):
    sftp = client.open_sftp()
    try:
        sftp.mkdir(stage, mode=0o700)
        sftp.mkdir(stage + '/tools', mode=0o700)
        hashes = {}
        for relative in FILES:
            raw = (ROOT / relative).read_bytes()
            hashes[relative] = hashlib.sha256(raw).hexdigest()
            with sftp.file(stage + '/' + relative, 'wb') as stream:
                stream.write(raw)
    finally:
        sftp.close()
    code = '''import hashlib,json,os,shutil
from pathlib import Path
stage=Path(%r);dest=Path(%r);hashes=%r
for relative,digest in hashes.items():
 p=stage/relative
 assert p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==digest
dest.mkdir(parents=True,exist_ok=True)
for p in [dest.parent,dest]:
 assert not p.is_symlink() and p.stat().st_uid==0 and not p.stat().st_mode & 0o022
 p.chmod(0o755)
for relative,digest in hashes.items():
 target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True)
 assert not target.is_symlink()
 if target.exists():assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
 else:shutil.copyfile(stage/relative,target)
 os.chown(target,0,0);os.chmod(target,0o644)
for directory,_,_ in os.walk(dest):os.chown(directory,0,0);os.chmod(directory,0o755)
print(json.dumps({'bootstrap':str(dest),'verified_files':len(hashes)}))
''' % (stage, BOOTSTRAP, hashes)
    return command(client, code, password)


def units():
    service = '''[Unit]
Description=Read-only three-server resource snapshots
After=network-online.target
RequiresMountsFor=/var/lib/research-data-center /data/services
ConditionHost=iZuf6jc6bqdgxmhcci4k3wZ
[Service]
Type=oneshot
User=rmp
Group=rmp
WorkingDirectory=/var/lib/research-data-center/workspace
ExecStart=%s %s/tools/collect_server_resources.py --identity-file %s/id_ed25519 --known-hosts %s/known_hosts --output %s/data/server-resources.json --timeout 20
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=%s/data
ReadOnlyPaths=%s
Nice=19
IOSchedulingClass=idle
CPUQuota=20%%
MemoryMax=256M
TasksMax=48
TimeoutStartSec=35
''' % (PYTHON, BOOTSTRAP, KEYDIR, KEYDIR, WORKSPACE, WORKSPACE, KEYDIR)
    timer = '''[Unit]
Description=Refresh research server snapshots every minute
[Timer]
OnBootSec=30
OnUnitInactiveSec=60
RandomizedDelaySec=5
Unit=research-server-monitor.service
[Install]
WantedBy=timers.target
'''
    return {'research-server-monitor.service': service, 'research-server-monitor.timer': timer}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--host', action='append', choices=HOSTS,
                        help='Authorize only selected hosts plus the central coordinator; already-authorized hosts are retained.')
    parser.add_argument('--receipt', type=Path, default=ROOT / 'var/private/monitor-installation.json')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'planned': True, 'hosts': HOSTS, 'bootstrap': BOOTSTRAP,
                          'units': list(units()), 'credentials_written': False}))
        return 0
    import paramiko  # Optional operator dependency; runtime key collection uses stdlib/OpenSSH.
    clients, passwords, receipts, pins = {}, {}, [], {}
    try:
        known = paramiko.HostKeys(str(Path.home() / '.ssh/known_hosts'))
        pins = {address: 'ssh-ed25519 ' + known.lookup(address)['ssh-ed25519'].get_base64() for address in HOSTS}
        chosen = HOSTS if not args.host else (CENTRAL,) + tuple(address for address in HOSTS if address != CENTRAL and address in args.host)
        for address in chosen:
            password = getpass.getpass('rmp@' + address + ' SSH/sudo password (hidden): ')
            client = paramiko.SSHClient();client.load_host_keys(str(Path.home() / '.ssh/known_hosts'));client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(address, username='rmp', password=password, timeout=8, auth_timeout=8,
                           banner_timeout=8, allow_agent=False, look_for_keys=False)
            clients[address] = client;passwords[address] = password
            pins[address] = 'ssh-ed25519 ' + client.get_host_keys().lookup(address)['ssh-ed25519'].get_base64()
            # /data/rmp is not provisioned on every node. A new private temp
            # directory does not depend on a member workspace or source tree.
            stage = '/var/tmp/rdc-monitor-candidate-' + uuid.uuid4().hex
            bootstrap(client, password, stage)
            print(json.dumps({'server': address, 'bootstrap_verified': True}), flush=True)
            if address == CENTRAL:
                key = command(client, 'import sys,json;sys.path.insert(0,%r);from tools.install_monitor_access import prepare_key;print(json.dumps(prepare_key(True)))' % BOOTSTRAP,
                              python=PYTHON)['public_key']
            code = ('import sys,json;sys.path.insert(0,%r);from tools.install_monitor_access import authorize;'
                    'print(json.dumps(authorize(%r,%r,%r,True)))') % (BOOTSTRAP, key, address, pins[address])
            result = command(client, code, password)
            receipts.append(result)
            print(json.dumps({'server': address, 'authorized': result['authorized'], 'existing_keys_preserved': result['existing_keys_preserved']}), flush=True)
        central = clients[CENTRAL]
        known = ''.join(address + ' ' + pins[address] + '\n' for address in HOSTS)
        code = ('import os,json;from pathlib import Path;p=Path(%r);'
                'assert not p.is_symlink();p.write_text(%r);os.chmod(p,0o600);print(json.dumps({"known_hosts_written":True}))') % (KEYDIR + '/known_hosts', known)
        command(central, code)
        code = '''import json,os,subprocess
from pathlib import Path
for name,text in %r.items():
 p=Path('/etc/systemd/system')/name
 assert not p.is_symlink()
 if p.exists():assert p.read_text()==text
 else:p.write_text(text)
 os.chmod(p,0o644)
subprocess.check_call(['systemctl','daemon-reload'])
subprocess.check_call(['systemctl','enable','--now','research-server-monitor.timer'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.check_call(['systemctl','start','research-server-monitor.service'])
print(json.dumps({'monitor_started':True}))
''' % units()
        command(central, code, passwords[CENTRAL], timeout=60)
        sftp = central.open_sftp()
        try:
            with sftp.file(WORKSPACE + '/data/server-resources.json', 'rb') as stream:
                snapshot = json.loads(stream.read())
        finally:
            sftp.close()
        from platform_data import public_server, SERVERS
        rows = {row['id']: row for row in snapshot['servers']}
        snapshot['servers'] = [public_server(rows.get(server['id']), server) for server in SERVERS]
        from tools.collect_server_resources import save_snapshot
        save_snapshot(ROOT / 'data/server-resources.json', snapshot)
        result = {'installed_at': snapshot['generated_at'], 'central': CENTRAL, 'receipts': receipts,
                  'key_private_material_exported': False, 'units': list(units()),
                  'statuses': [{'id': row['id'], 'status': row['status'], 'error_code': row['error_code']} for row in snapshot['servers']]}
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        passwords.clear()
        for client in clients.values():client.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': type(exc).__name__ + (':' + str(exc) if isinstance(exc, RuntimeError) else '')}))
        raise SystemExit(2)
