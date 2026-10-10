"""Read-only Linux/Pi telemetry. Missing sensors stay null; no elevated access."""
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def read(path, default=''):
    try:
        return Path(path).read_text(errors='replace').strip().strip('\0')
    except OSError:
        return default


def number(text):
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=2, check=True)
        return p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def memory():
    values = {}
    for line in read('/proc/meminfo').splitlines():
        key, val = line.split(':', 1)
        values[key] = int(val.split()[0]) * 1024
    total, available = values.get('MemTotal'), values.get('MemAvailable')
    return dict(total_bytes=total, available_bytes=available,
                used_bytes=total-available if total and available is not None else None,
                percent=round(100*(total-available)/total,2) if total and available is not None else None,
                swap_total_bytes=values.get('SwapTotal'),
                swap_used_bytes=values.get('SwapTotal',0)-values.get('SwapFree',0),
                cached_bytes=values.get('Cached'), buffers_bytes=values.get('Buffers'))


def cpu_ticks():
    result = {}
    for line in read('/proc/stat').splitlines():
        parts=line.split()
        if parts and re.fullmatch(r'cpu\d*',parts[0]):
            v=list(map(int,parts[1:9])) # guest time is already included in user/nice
            result[parts[0]]=(sum(v),v[3]+v[4])
    return result


def cpu_percent(before, after):
    if before is None or after[0] <= before[0]:
        return None
    return round(max(0,min(100,100*(1-(after[1]-before[1])/(after[0]-before[0])))),2)


def throttle_flags(value):
    labels={0:'Onderspanning actief',1:'CPU-frequentie begrensd',2:'Throttling actief',3:'Temperatuurlimiet actief',
            16:'Onderspanning sinds boot',17:'CPU begrensd sinds boot',18:'Throttling sinds boot',19:'Temperatuurlimiet sinds boot'}
    return [label for bit,label in labels.items() if value & (1<<bit)]


class PiSampler:
    def __init__(self, database):
        self.database=Path(database)
        self.last_time=None;self.last_cpu={};self.last_net={};self.last_disks={};self.last_procs={}
        self.started=time.monotonic()
        self.info=self.identity()
        self.last_info=time.monotonic()

    def identity(self):
        release={}
        for line in read('/etc/os-release').splitlines():
            if '=' in line:
                k,v=line.split('=',1);release[k]=v.strip('"')
        ips=command(['ip','-j','address','show'])
        try:
            addresses=[dict(name=x['ifname'],state=x.get('operstate'),mac=x.get('address'),
                            addresses=[a['local'] for a in x.get('addr_info',[])]) for x in json.loads(ips or '[]')]
        except (ValueError,KeyError,TypeError):
            addresses=[]
        return dict(hostname=socket.gethostname(),model=read('/proc/device-tree/model') or platform.machine(),
                    os=release.get('PRETTY_NAME',platform.system()),kernel=platform.release(),architecture=platform.machine(),
                    cores=os.cpu_count(),python=platform.python_version(),interfaces=addresses)

    def sample(self):
        tick=time.monotonic();elapsed=tick-self.last_time if self.last_time else None
        if tick-self.last_info>300:
            self.info=self.identity();self.last_info=tick
        cpus=cpu_ticks()
        percents={key:cpu_percent(self.last_cpu.get(key),value) for key,value in cpus.items()}
        mem=memory();temperatures=[]
        for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
            temp=number(read(zone/'temp'))
            if temp is not None:
                temperatures.append(dict(name=read(zone/'type'),celsius=temp/1000))
        soc=command(['vcgencmd','measure_temp'])
        match=re.search(r'=([\d.]+)',soc or '')
        temperature=float(match[1]) if match else (temperatures[0]['celsius'] if temperatures else None)
        raw_throttle=command(['vcgencmd','get_throttled']);flags=None
        match=re.search(r'0x[0-9a-fA-F]+',raw_throttle or '')
        if match:
            flags=throttle_flags(int(match[0],16))
        volts=command(['vcgencmd','measure_volts','core'])
        match=re.search(r'=([\d.]+)',volts or '')
        voltage=float(match[1]) if match else None
        fans=[]
        for sensor in Path('/sys/class/hwmon').glob('hwmon*/fan*_input'):
            fans.append(dict(name=read(sensor.parent/'name'),rpm=number(read(sensor))))
        frequency=[]
        for cpu in Path('/sys/devices/system/cpu').glob('cpu[0-9]*'):
            val=number(read(cpu/'cpufreq/scaling_cur_freq'))
            if val is not None:frequency.append(dict(core=cpu.name,mhz=val/1000,governor=read(cpu/'cpufreq/scaling_governor')))
        net={};network=[]
        for line in read('/proc/net/dev').splitlines()[2:]:
            name,tail=line.split(':',1);name=name.strip();v=list(map(int,tail.split()));net[name]=(v[0],v[8])
            old=self.last_net.get(name)
            network.append(dict(name=name,physical=(Path('/sys/class/net')/name/'device').exists(),rx_bytes=v[0],tx_bytes=v[8],rx_packets=v[1],tx_packets=v[9],rx_errors=v[2],tx_errors=v[10],rx_drops=v[3],tx_drops=v[11],
                                rx_per_second=round((v[0]-old[0])/elapsed,2) if old and elapsed and v[0]>=old[0] else None,
                                tx_per_second=round((v[8]-old[1])/elapsed,2) if old and elapsed and v[8]>=old[1] else None))
        wifi=[]
        for line in read('/proc/net/wireless').splitlines()[2:]:
            parts=line.split()
            if len(parts)>=5:wifi.append(dict(name=parts[0].rstrip(':'),quality=number(parts[2].rstrip('.')),signal_dbm=number(parts[3].rstrip('.'))))
        disks={};io=[]
        for line in read('/proc/diskstats').splitlines():
            v=line.split()
            if len(v)<14 or not (Path('/sys/block')/v[2]).exists() or v[2].startswith(('loop','ram')):continue
            name=v[2];cur=(int(v[5])*512,int(v[9])*512,int(v[12]));disks[name]=cur;old=self.last_disks.get(name)
            io.append(dict(device=name,read_bytes=cur[0],write_bytes=cur[1],reads=int(v[3]),writes=int(v[7]),
                           read_per_second=round(max(0,cur[0]-old[0])/elapsed,2) if old and elapsed and all(a>=b for a,b in zip(cur,old)) else None,
                           write_per_second=round(max(0,cur[1]-old[1])/elapsed,2) if old and elapsed and all(a>=b for a,b in zip(cur,old)) else None,
                           busy_percent=round(min(100,max(0,cur[2]-old[2])/(elapsed*10)),2) if old and elapsed and all(a>=b for a,b in zip(cur,old)) else None))
        storage=[];devices=set()
        for name,path in [('Systeem','/'),('Monitorgegevens',str(self.database.parent))]:
            try:
                device=os.stat(path).st_dev
                if device in devices:continue
                devices.add(device)
                usage=shutil.disk_usage(path);stat=os.statvfs(path)
                storage.append(dict(name=name,path=path,total_bytes=usage.total,used_bytes=usage.used,free_bytes=usage.free,percent=round(usage.used/usage.total*100,2),inodes_total=stat.f_files,inodes_free=stat.f_favail))
            except OSError:pass
        processes=[];proc_ticks={};hz=os.sysconf('SC_CLK_TCK');page_size=os.sysconf('SC_PAGE_SIZE')
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():continue
            raw=read(entry/'stat')
            try:
                close=raw.rindex(')');comm=raw[raw.index('(')+1:close];fields=raw[close+2:].split()
                used=int(fields[11])+int(fields[12]);pid=int(entry.name);start=fields[19]
                proc_ticks[(pid,start)]=used;old=self.last_procs.get((pid,start))
                processes.append(dict(pid=pid,name=comm,state=fields[0],threads=int(fields[17]),rss_bytes=int(fields[21])*page_size,
                                      cpu_percent=round(max(0,used-old)/hz/elapsed*100,2) if old is not None and elapsed else None))
            except (ValueError,IndexError):pass
        own=next((x for x in processes if x['pid']==os.getpid()),None)
        top=sorted(processes,key=lambda p:(p['cpu_percent'] or 0,p['rss_bytes']),reverse=True)[:12]
        pressure={}
        for metric in ('cpu','memory','io'):
            pressure[metric]=read('/proc/pressure/'+metric) or None
        db_bytes=sum(p.stat().st_size for p in self.database.parent.glob(self.database.name+'*') if p.is_file())
        try:load=list(os.getloadavg())
        except OSError:load=None
        uptime=number(read('/proc/uptime').split(' ')[0])
        result=dict(timestamp=datetime.now(timezone.utc).isoformat(timespec='seconds'),identity=self.info,
                    cpu_percent=percents.get('cpu'),cores=percents,load=load,frequency=frequency,
                    memory=mem,temperature=temperature,thermal_sensors=temperatures,voltage=voltage,throttle_flags=flags,throttle_raw=raw_throttle,
                    fans=fans,network=network,wifi=wifi,storage=storage,disk_io=io,processes=top,process_count=len(processes),monitor_process=own,
                    pressure=pressure,uptime_seconds=uptime,monitor_uptime_seconds=round(tick-self.started),database_bytes=db_bytes,backup_bytes=sum(p.stat().st_size for p in (self.database.parent/'backups').glob('*.sqlite')))
        self.last_time=tick;self.last_cpu=cpus;self.last_net=net;self.last_disks=disks;self.last_procs=proc_ticks
        return result
