
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
