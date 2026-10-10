"""Additional SQLite observations and bounded aggregate views."""
import json
import math
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def timestamp(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch,timezone.utc).isoformat(timespec='seconds')


class Insights:
    def __init__(self, store):
        self.store=store
        self.cache={};self.lock=threading.Lock()
        with store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sightings(id INTEGER PRIMARY KEY,ts TEXT,name TEXT,uuid TEXT,source TEXT,confirmed INTEGER);
            CREATE INDEX IF NOT EXISTS sightings_name_ts ON sightings(name,ts);
            CREATE INDEX IF NOT EXISTS sightings_ts ON sightings(ts);
            CREATE TABLE IF NOT EXISTS pi_metrics(id INTEGER PRIMARY KEY,ts TEXT,cpu REAL,temperature REAL,memory REAL,rx REAL,tx REAL,data TEXT);
            CREATE INDEX IF NOT EXISTS pi_metrics_ts ON pi_metrics(ts);
            CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY,ts TEXT,kind TEXT,title TEXT,message TEXT,delivery TEXT);
            CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY,start TEXT,last_seen TEXT,end TEXT,reason TEXT);
            ''')
            db.execute("UPDATE incidents SET end=last_seen,reason=reason || ' [meetgat/herstart]' WHERE end IS NULL")
        self.server_id = store.server_id

    def observe(self, current, previous):
        ts=current['timestamp']
        ids={x.get('name'):x.get('id') for x in current.get('sample',[]) if isinstance(x,dict)}
        with self.store.connect() as db:
            sid=int(current.get('server_id') or getattr(self,'server_id',1))
            for name in current.get('names',[]):
                db.execute('INSERT INTO sightings(ts,name,uuid,source,confirmed,server_id) VALUES(?,?,?,?,?,?)',
                           (ts,name,ids.get(name),current.get('name_source'),int(current.get('names_complete',False)),sid))
            if not current['reachable']:
                if previous and not previous['reachable']:
                    db.execute('UPDATE incidents SET last_seen=? WHERE end IS NULL AND server_id=?',(ts,sid))
                else:
                    db.execute('INSERT INTO incidents(start,last_seen,reason,server_id) VALUES(?,?,?,?)',(ts,ts,current.get('error','Onbereikbaar'),sid))
            elif previous and not previous['reachable']:
                db.execute('UPDATE incidents SET end=?,last_seen=? WHERE end IS NULL AND server_id=?',(ts,ts,sid))

    def add_pi(self, data):
        rx=sum(x['rx_per_second'] or 0 for x in data['network'] if x.get('physical'))
        tx=sum(x['tx_per_second'] or 0 for x in data['network'] if x.get('physical'))
        with self.store.connect() as db:
            db.execute('INSERT INTO pi_metrics(ts,cpu,temperature,memory,rx,tx,data) VALUES(?,?,?,?,?,?,?)',
                       (data['timestamp'],data['cpu_percent'],data['temperature'],data['memory']['percent'],rx,tx,json.dumps(data)))

    def notice(self, kind, title, message, delivery='local'):
        with self.store.connect() as db:
            cur=db.execute('INSERT INTO notices(ts,kind,title,message,delivery,server_id) VALUES(?,?,?,?,?,?)',(timestamp(),kind,title,message,delivery,self.store.server_id))
            return cur.lastrowid

    def delivery(self, notice_id, result):
        with self.store.connect() as db:
            db.execute('UPDATE notices SET delivery=?,reason=? WHERE id=?',(result,result,notice_id))
            db.execute("UPDATE delivery_queue SET status=? WHERE notice_id=? AND status IN ('queued','retry')",(result,notice_id))

    def queue_delivery(self, notice_id, title, message, created, expire):
        with self.store.connect() as db:
            db.execute(
                'INSERT INTO delivery_queue(created,expire,attempts,next_attempt,status,kind,title,message,notice_id) VALUES(?,?,0,?,?,?,?,?,?)',
                (created, expire, created, 'queued', title, title, message, notice_id),
            )

    def prune(self, server_days, pi_days):
        with self.store.connect() as db:
            db.execute('DELETE FROM pi_metrics WHERE ts<?',(timestamp(time.time()-pi_days*86400),))
            for table,col in [('sightings','ts'),('notices','ts'),('incidents','last_seen'),('delivery_queue','created')]:
                db.execute(f'DELETE FROM {table} WHERE {col}<?',(timestamp(time.time()-server_days*86400),))

    def dashboard(self, hours):
        # Heavy aggregates cache for one minute; current data always stays fresh.
        cutoff=timestamp(time.time()-hours*3600);bucket=max(30,int(hours*3600/400))
        from app import ScopedRead
        with self.store.connect() as db:
            db=ScopedRead(db,self.store.server_id)
            last=db.execute('SELECT data FROM pi_metrics ORDER BY id DESC LIMIT 1').fetchone()
            pi=json.loads(last['data']) if last else None
            pi_series=[dict(r) for r in db.execute("SELECT MIN(ts) ts,AVG(cpu) cpu,MAX(temperature) temperature,AVG(memory) memory,AVG(rx) rx,AVG(tx) tx FROM pi_metrics WHERE ts>=? GROUP BY CAST(strftime('%s',ts) AS INTEGER)/? ORDER BY ts",(cutoff,bucket))]
            notices=[dict(r) for r in db.execute('SELECT * FROM notices ORDER BY id DESC LIMIT 100')]
            incidents=[dict(r) for r in db.execute('SELECT * FROM incidents WHERE last_seen>=? ORDER BY id DESC LIMIT 100',(cutoff,))]
            with self.lock:cached=self.cache.get(hours)
            if cached and time.monotonic()-cached[0]<60:
                stats=cached[1]
            else:
                latency=[r[0] for r in db.execute('SELECT latency FROM checks WHERE ts>=? AND latency IS NOT NULL ORDER BY latency',(cutoff,))]
                def quantile(p):return latency[min(len(latency)-1,math.ceil(p*len(latency))-1)] if latency else None
                hourly=[dict(r) for r in db.execute("SELECT strftime('%H',ts) hour,AVG(online) average,MAX(online) peak,COUNT(*) checks FROM checks WHERE ts>=? AND reachable=1 GROUP BY hour ORDER BY hour",(cutoff,))]
                daily=[dict(r) for r in db.execute("SELECT substr(ts,1,10) day,COUNT(*) checks,SUM(reachable) reachable,MAX(online) peak,AVG(online) average,AVG(latency) latency FROM checks WHERE ts>=? GROUP BY day ORDER BY day",(cutoff,))]
                heat=[dict(r) for r in db.execute("SELECT strftime('%w',ts) weekday,strftime('%H',ts) hour,AVG(online) average,COUNT(*) samples FROM checks WHERE ts>=? AND reachable=1 GROUP BY weekday,hour",(cutoff,))]
                coverage=dict(db.execute('SELECT COUNT(*) total,MIN(ts) first,MAX(ts) last FROM checks').fetchone())
                quality=dict(db.execute("SELECT COUNT(*) checks,SUM(CASE WHEN json_extract(data,'$.names_complete')=1 THEN 1 ELSE 0 END) complete FROM checks WHERE ts>=?",(cutoff,)).fetchone())
                seen=[dict(r) for r in db.execute('SELECT name,MIN(ts) first_seen,MAX(ts) last_seen,COUNT(*) observations,MAX(confirmed) confirmed FROM sightings GROUP BY name ORDER BY last_seen DESC LIMIT 500')]
                stats=dict(latency_min=latency[0] if latency else None,latency_max=latency[-1] if latency else None,latency_p50=quantile(.5),latency_p95=quantile(.95),hourly=hourly,daily=daily,heatmap=heat,coverage=coverage,quality=quality,sightings=seen)
                with self.lock:self.cache[hours]=(time.monotonic(),stats)
        return dict(pi=pi,pi_series=pi_series,notices=notices,incidents=incidents,analytics=stats)

    def player(self, name):
        from app import ScopedRead
        with self.store.connect() as db:
            db=ScopedRead(db,self.store.server_id)
            summary=db.execute('SELECT name,MIN(ts) first_seen,MAX(ts) last_seen,COUNT(*) observations,SUM(confirmed) confirmed_observations FROM sightings WHERE name=?',(name,)).fetchone()
            old=db.execute('SELECT * FROM players WHERE name=?',(name,)).fetchone()
            if not summary['name'] and not old:return None
            summary=dict(summary) if summary['name'] else dict(old)
            summary['name']=name
            identities=[dict(r) for r in db.execute('SELECT uuid,source,MAX(ts) last_seen FROM sightings WHERE name=? GROUP BY uuid,source',(name,))]
            totals=dict(db.execute('SELECT COUNT(*) segments,SUM(seconds) seconds,AVG(seconds) average_seconds,MAX(seconds) longest_seconds FROM sessions WHERE player=?',(name,)).fetchone())
            sessions=[dict(r) for r in db.execute('SELECT * FROM sessions WHERE player=? ORDER BY id DESC LIMIT 200',(name,))]
            daily=[dict(r) for r in db.execute('SELECT substr(ts,1,10) day,COUNT(*) observations,SUM(confirmed) confirmed FROM sightings WHERE name=? GROUP BY day ORDER BY day DESC LIMIT 60',(name,))]
            hourly=[dict(r) for r in db.execute("SELECT strftime('%H',ts) hour,COUNT(*) observations,SUM(confirmed) confirmed FROM sightings WHERE name=? GROUP BY hour",(name,))]
            overlaps=[dict(r) for r in db.execute('''SELECT b.player,COUNT(*) overlaps FROM sessions a JOIN sessions b ON a.player!=b.player AND a.start < COALESCE(b.end,(SELECT last_seen FROM players WHERE name=b.player)) AND b.start < COALESCE(a.end,(SELECT last_seen FROM players WHERE name=a.player)) WHERE a.player=? AND a.end_reason IN ('leave_observed','observation_gap','monitor_restart') AND b.end IS NOT NULL GROUP BY b.player ORDER BY overlaps DESC LIMIT 20''',(name,))]
            return dict(summary=summary,identities=identities,totals=totals,sessions=sessions,daily=daily,hourly=hourly,overlaps=overlaps)

    def backup(self, keep=7):
        folder=Path(self.store.path).parent/'backups';folder.mkdir(exist_ok=True)
        name=datetime.now(timezone.utc).strftime('monitor-%Y%m%d-%H%M%S.sqlite')
        path=folder/name
        with self.store.connect() as source:
            target=sqlite3.connect(path)
            try:source.backup(target)
            finally:target.close()
        for old in sorted(folder.glob('monitor-*.sqlite'))[:-keep]:old.unlink()
        return path
