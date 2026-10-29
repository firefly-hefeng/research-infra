"""One central bounded SSH collection; credentials stay in process memory.

Default transport is strict-known-host OpenSSH key authentication. Optional
passwords are read from hidden prompts or JSON stdin, using local Paramiko only.
Only bounded GPU process metadata is collected. Full command lines, working
paths, environment variables, training logs and dataset contents are never returned.
"""
import argparse
import concurrent.futures
import datetime as dt
import getpass
import json
import multiprocessing
import os
from pathlib import Path
import queue
import shlex
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_data import SERVERS, metrics, public_server, stamp

REMOTE_PROBE = r'''
import csv, datetime, json, os, subprocess, time
from io import StringIO
try:import pwd
except ImportError:pwd=None
errors=[]
def fail(component, code): errors.append({'component':component,'code':code})
def cpu_ticks():
    with open('/proc/stat') as f: ticks=[int(x) for x in f.readline().split()[1:]]
    return sum(ticks[:8]), ticks[3]+ticks[4]
def numeric(value,scale=1):
    try:return round(float(value.strip())*scale,2)
    except ValueError:return None
def basename(value):
    if not isinstance(value,str) or '\x00' in value:return None
    value=value.replace('\\','/').rstrip('/')
    result=value.rsplit('/',1)[-1].strip()
    return result[:120] if result and not any(ord(c)<32 for c in result) else None
def gpu_job_label(pid,process):
    argv=[]
    try:
        with open(f'/proc/{pid}/cmdline','rb') as stream: raw=stream.read(16385)
        if len(raw)<=16384:argv=[part.decode('utf-8','replace') for part in raw.split(b'\x00') if part]
    except (OSError,PermissionError):pass
    for flag in ('--name','--output-dir'):
        if flag in argv:
            index=argv.index(flag)
            if index+1<len(argv):
                candidate=basename(argv[index+1])
                if candidate and all(c.isalnum() or c in '_.-' for c in candidate):return candidate
    scripts=[basename(arg) for arg in argv if arg.endswith('.py')]
    scripts=[name for name in scripts if name]
    return scripts[0] if scripts else basename(process)
def gpu_processes():
    result=[]
    output=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,process_name,used_memory','--format=csv,noheader,nounits'],universal_newlines=True,stderr=subprocess.DEVNULL,timeout=5)
    for row in list(csv.reader(StringIO(output)))[:64]:
        if len(row)!=4:continue
        try:
            uuid=row[0].strip();pid=int(row[1]);process=basename(row[2]);memory=numeric(row[3],1048576)
            uid=os.stat(f'/proc/{pid}',follow_symlinks=False).st_uid
            try:user=pwd.getpwuid(uid).pw_name if pwd else str(uid)
            except KeyError:user=str(uid)
        except (OSError,ValueError,PermissionError):continue
        result.append({'uuid':uuid,'pid':pid,'user':user,'job':gpu_job_label(pid,process),'process':process,'used_memory_bytes':memory})
    return result
cpu={'logical_cores':os.cpu_count(),'model':None,'load_1m':os.getloadavg()[0],'usage_percent':None}
try:
    with open('/proc/cpuinfo') as f:
        for line in f:
            if line.startswith('model name'):
                cpu['model']=line.split(':',1)[1].strip();break
    a=cpu_ticks();time.sleep(.25);b=cpu_ticks()
    cpu['usage_percent']=round(100*(1-(b[1]-a[1])/(b[0]-a[0])),2) if b[0]>a[0] else None
except Exception: fail('cpu','unavailable')
memory={}
try:
    with open('/proc/meminfo') as f: data={line.split(':',1)[0]:int(line.split()[1])*1024 for line in f}
    total=data['MemTotal'];available=data.get('MemAvailable')
    memory={'total_bytes':total,'available_bytes':available,'used_percent':round(100*(1-available/total),2) if available is not None else None}
except Exception: fail('memory','unavailable')
gpus=None
try:
    output=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],universal_newlines=True,stderr=subprocess.DEVNULL,timeout=5)
    process_rows=gpu_processes()
    process_map={}
    for process in process_rows:process_map.setdefault(process.pop('uuid'),[]).append(process)
    gpus=[]
    for row in csv.reader(StringIO(output)):
        if len(row)!=7:raise ValueError()
        uuid=row[1].strip()
        gpus.append({'index':int(row[0]),'uuid':uuid,'name':row[2].strip(),'memory_total_bytes':numeric(row[3],1048576),'memory_used_bytes':numeric(row[4],1048576),'utilization_percent':numeric(row[5]),'temperature_c':numeric(row[6]),'processes':process_map.get(uuid,[])})
except Exception: fail('gpu','unavailable')
disks=[]
try:
    with open('/proc/self/mountinfo') as f:
        mounted={line.split()[4]:line.split(' - ',1)[1].split()[0] for line in f}
    for path in ('/','/data','/data/share','/data/share_cold'):
        if path not in mounted:continue
        try:
            info=os.statvfs(path);total=info.f_blocks*info.f_frsize;available=info.f_bavail*info.f_frsize
            disks.append({'mount':path,'filesystem':mounted[path],'total_bytes':total,'available_bytes':available,'used_percent':round(100*(1-available/total),2) if total else None})
        except Exception:fail('disk','unavailable')
except Exception:fail('disk','unavailable')
print(json.dumps({'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cpu':cpu,'memory':memory,'gpus':gpus,'disks':disks,'errors':errors}))
'''


def ssh_collect(server, password, options):
    command = 'python3 -c ' + shlex.quote(REMOTE_PROBE)
    if password is None:
        arguments = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                     '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=3', '-o', 'ServerAliveCountMax=1',
                     '-o', 'UserKnownHostsFile=' + options['known_hosts']]
        if options.get('identity_file'):
            arguments += ['-i', options['identity_file'], '-o', 'IdentitiesOnly=yes']
        result = subprocess.run(arguments + ['rmp@' + server['address'], command], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=options['timeout'])
        if result.returncode:
            return {'error_code': 'connection_failed'}
        raw = result.stdout
    else:
        try:
            import paramiko
        except ImportError:
            return {'error_code': 'transport_unavailable'}
        client = paramiko.SSHClient()
        try:
            client.load_host_keys(options['known_hosts'])
            if not client.get_host_keys().lookup(server['address']):
                return {'error_code': 'host_key_unknown'}
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(server['address'], username='rmp', password=password, timeout=5, auth_timeout=5,
                           banner_timeout=5, allow_agent=False, look_for_keys=False)
            stdin, stdout, stderr = client.exec_command(command, timeout=options['timeout'])
            stdin.close()
            raw = stdout.read(131073)
            if stdout.channel.recv_exit_status() != 0:
                return {'error_code': 'probe_failed'}
        except paramiko.AuthenticationException:
            return {'error_code': 'authentication_failed'}
        except paramiko.BadHostKeyException:
            return {'error_code': 'host_key_mismatch'}
        except Exception:
            return {'error_code': 'connection_failed'}
        finally:
            client.close()
    if len(raw) > 131072:
        return {'error_code': 'invalid_probe'}
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or not stamp(value.get('observed_at')):
            raise ValueError()
        return {'status': 'partial' if value.get('errors') else 'online',
                'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'remote_observed_at': value['observed_at'], **metrics(value)}
    except (ValueError, UnicodeError):
        return {'error_code': 'invalid_probe'}


def child_collect(output, server, password, options):
    try:
        output.put(ssh_collect(server, password, options))
    except Exception:
        output.put({'error_code': 'connection_failed'})


def bounded_collect(server, password, options):
    # The child can be terminated even if an SSH library or hard NFS stat hangs.
    context = multiprocessing.get_context('spawn')
    output = context.Queue(maxsize=1)
    process = context.Process(target=child_collect, args=(output, server, password, options))
    process.start()
    try:
        try:
            result = output.get(timeout=options['timeout'])
        except queue.Empty:
            return {'error_code': 'timeout'}
        return result
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill();process.join(timeout=2)
        output.close()


def collect(previous, passwords, options, selected=None, collector=bounded_collect):
    at = dt.datetime.now(dt.timezone.utc)
    previous = {row.get('id'): row for row in (previous or {}).get('servers', []) if isinstance(row, dict)}
    definitions = [server for server in SERVERS if selected is None or server['address'] in selected]
    outcomes = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        pending = {executor.submit(collector, server, passwords.get(server['address']), options): server for server in definitions}
        for future in concurrent.futures.as_completed(pending):
            server = pending[future]
            try:
                raw = future.result()
            except Exception:
                raw = {'error_code': 'connection_failed'}
            if raw.get('error_code'):
                raw = {**previous.get(server['id'], {}), 'status': 'unreachable', 'error_code': raw['error_code']}
            raw['attempted_at'] = at.isoformat()
            outcomes[server['id']] = raw
    return {'schema_version': '1.0', 'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'collection': {'method': 'central_readonly_ssh_system_metrics', 'timeout_seconds': options['timeout'],
                           'gpu_process_metadata_collected': True, 'command_lines_collected': False, 'gpu_work_started': False},
            'servers': [public_server(outcomes.get(server['id'], previous.get(server['id'])), server) for server in SERVERS]}


def save_snapshot(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.server-resources-', suffix='.json', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'data/server-resources.json')
    parser.add_argument('--known-hosts', type=Path, default=Path.home() / '.ssh/known_hosts')
    parser.add_argument('--identity-file', type=Path)
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--host', action='append', choices=[server['address'] for server in SERVERS])
    secrets = parser.add_mutually_exclusive_group()
    secrets.add_argument('--prompt-passwords', action='store_true', help='Hidden getpass prompts; never written to output.')
    secrets.add_argument('--passwords-stdin', action='store_true', help='Read one JSON object {address:password} from redirected stdin; never use terminal echo.')
    args = parser.parse_args()
    if not 5 <= args.timeout <= 60:
        parser.error('timeout must be 5..60 seconds')
    passwords = {}
    if args.prompt_passwords:
        for server in SERVERS:
            if args.host is None or server['address'] in args.host:
                passwords[server['address']] = getpass.getpass('rmp@' + server['address'] + ' password (hidden): ')
    elif args.passwords_stdin:
        if sys.stdin.isatty():
            parser.error('Use redirected stdin or --prompt-passwords; terminal echo is refused.')
        passwords = json.loads(sys.stdin.read(16385))
        if (not isinstance(passwords, dict) or set(passwords) - {server['address'] for server in SERVERS}
                or any(not isinstance(value, str) or len(value) > 1024 for value in passwords.values())):
            parser.error('Invalid in-memory credentials object')
    previous = json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {}
    options = {'timeout': args.timeout, 'known_hosts': str(args.known_hosts),
               'identity_file': str(args.identity_file) if args.identity_file else None}
    result = collect(previous, passwords, options, selected=args.host)
    passwords.clear()
    # A targeted diagnostic must not erase another host's newer saved sample.
    if args.host and args.output.exists():
        latest = json.loads(args.output.read_text(encoding='utf-8'))
        latest_rows = {row['id']: row for row in latest.get('servers', []) if isinstance(row, dict) and 'id' in row}
        for index, server in enumerate(SERVERS):
            if server['address'] not in args.host and server['id'] in latest_rows:
                result['servers'][index] = public_server(latest_rows[server['id']], server)
    save_snapshot(args.output, result)
    print(json.dumps({'output': str(args.output), 'generated_at': result['generated_at'],
                      'servers': [{'id': row['id'], 'status': row['status'], 'error_code': row['error_code']} for row in result['servers']]}))
    return 0


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
