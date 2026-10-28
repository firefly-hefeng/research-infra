
import csv, datetime, json, os, subprocess, time
from io import StringIO
errors=[]
def fail(component, code): errors.append({'component':component,'code':code})
def cpu_ticks():
    with open('/proc/stat') as f: ticks=[int(x) for x in f.readline().split()[1:]]
    return sum(ticks[:8]), ticks[3]+ticks[4]
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
    output=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],universal_newlines=True,stderr=subprocess.DEVNULL,timeout=5)
    gpus=[]
    def numeric(value,scale=1):
        try:return round(float(value.strip())*scale,2)
        except ValueError:return None
    for row in csv.reader(StringIO(output)):
        if len(row)!=6:raise ValueError()
        gpus.append({'index':int(row[0]),'name':row[1].strip(),'memory_total_bytes':numeric(row[2],1048576),'memory_used_bytes':numeric(row[3],1048576),'utilization_percent':numeric(row[4]),'temperature_c':numeric(row[5])})
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
