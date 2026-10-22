#!/usr/bin/env python3
"""Uitgeteld Pi: read-only Minecraft telemetry with a local web dashboard."""
from contextlib import contextmanager
import argparse
import secrets
import shutil
import zipfile
import tempfile
import sys
import base64
import csv
import hmac
import io
import json
import os
import re
import signal
import socket
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from radar_feed import RadarFeed
from protocol import status, full_query, ping
from telemetry import PiSampler
from insights import Insights
from settings import Preferences, Notifier
from chatlogs import ChatLog
from observe import classify, mark_stale, player_events, should_close_sessions
from schema import migrate
import updater
import github_update
import hashlib

ROOT = Path(__file__).resolve().parent
DEFAULTS = dict(host='', port=25565, query_port=25565,
                interval=30, query_interval=300, bind='0.0.0.0', web_port=8080,
                retention_days=365, database='data/monitor.sqlite', resolve_srv=True,
                edition='java')
PRODUCT = 'Minecraft Pi Monitor'
STOP = threading.Event()
RESTART = threading.Event()
VERSION = (ROOT/"VERSION").read_text().strip() if (ROOT/"VERSION").exists() else "2.0.0"


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def plain(component):
    if isinstance(component, str):
        return re.sub('§.', '', component)
    if isinstance(component, list):
        return ''.join(plain(x) for x in component)
    if isinstance(component, dict):
        return plain(component.get('text', component.get('translate', ''))) + plain(component.get('extra', []))
    return ''


class ScopedRead:
    """Explicit read adapter used by per-server views only; never used for migrations."""
    tables = ('checks','players','sessions','events','sightings','incidents','chat','notices')
    def __init__(self, db, server_id):
        self.db,self.server_id=db,int(server_id)
    def execute(self, sql, args=()):
        for table in self.tables:
            sql=re.sub(r'(?i)\b(FROM|JOIN)\s+'+table+r'\b',
                       lambda m:m[1]+f' (SELECT * FROM main.{table} WHERE server_id={self.server_id})',sql)
        return self.db.execute(sql,args)


class Store:
    def __init__(self, path, host='unknown', port=25565, query_port=25565):
        self.path = str(path)
        self.server_id = 1
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY, ts TEXT, reachable INTEGER, online INTEGER, latency REAL, data TEXT);
                CREATE INDEX IF NOT EXISTS checks_ts ON checks(ts);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, player TEXT, detail TEXT);
                CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
                CREATE TABLE IF NOT EXISTS players(name TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, observations INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, player TEXT, start TEXT, end TEXT, seconds REAL, end_reason TEXT, start_kind TEXT);
                CREATE INDEX IF NOT EXISTS sessions_player ON sessions(player);
            ''')
            migrate(db, host=host, port=port, query_port=query_port)
            row = db.execute('SELECT id FROM servers WHERE host=? AND port=? ORDER BY id LIMIT 1',(host,port)).fetchone()
            self.server_id = row['id'] if row else 1
            # Never bridge a monitoring restart as if it were uninterrupted.
            for row in db.execute('SELECT id,start,player,server_id,last_seen FROM sessions WHERE end IS NULL').fetchall():
                last = db.execute('SELECT last_seen FROM players WHERE name=? AND server_id=?', (row['player'], row['server_id'])).fetchone()
                if last is None:
                    last = db.execute('SELECT last_seen FROM players WHERE name=?', (row['player'],)).fetchone()
                end = row['last_seen'] or (last['last_seen'] if last else row['start'])
                db.execute('UPDATE sessions SET end=?,seconds=?,end_reason=? WHERE id=?',
                           (end, max(0, (datetime.fromisoformat(end)-datetime.fromisoformat(row['start'])).total_seconds()), 'monitor_restart', row['id']))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put_artifact(self, db, kind, text):
        digest = hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()
        db.execute('INSERT OR IGNORE INTO artifacts(sha256,kind,nbytes,data,first_seen) VALUES(?,?,?,?,?)',
                   (digest, kind, len(text), text, now()))
        return digest

    def slim(self, db, current):
        payload = json.loads(json.dumps(current))
        raw = payload.get('raw_status')
        if isinstance(raw, dict):
            raw = dict(raw)
            fav = raw.get('favicon')
            if isinstance(fav, str) and len(fav) > 80:
                raw['favicon'] = 'artifact:' + self.put_artifact(db, 'favicon', fav)
            forge = raw.get('forgeData')
            if forge is not None:
                blob = json.dumps(forge, separators=(',', ':'))
                if len(blob) > 400:
                    raw['forgeData'] = {'artifact': self.put_artifact(db, 'forgeData', blob)}
            payload['raw_status'] = raw
        return payload

    def add(self, current, previous):
        classify(current)
        mark_stale(current, previous, current.get('interval') or 30)
        ts = current['timestamp']
        sid = int(current.get('server_id') or self.server_id)
        current['server_id'] = sid
        events = []
        if previous is None or previous['reachable'] != current['reachable']:
            events.append(('reachable' if current['reachable'] else 'unreachable', '', current.get('error', 'Server bereikbaar'), 'confirmed'))
        if current['reachable'] and previous and previous['reachable']:
            for key in ('version', 'motd', 'maximum'):
                if previous.get(key) != current.get(key):
                    events.append(('metadata_changed', '', f'{key}: {previous.get(key)} → {current.get(key)}', 'confirmed'))
            if previous.get('online') != current.get('online'):
                events.append(('count_changed', '', f"{previous.get('online')} → {current.get('online')}", 'confirmed'))
        events.extend(player_events(previous, current))
        close_reason = should_close_sessions(previous, current)
        confirmed_names = set(current.get('names') or []) if current.get('names_complete') else set()
        sample_names = set(current.get('names') or []) if current.get('reachable') else set()
        with self.connect() as db:
            stored = self.slim(db, current)
            db.execute('INSERT INTO checks(ts,reachable,online,latency,data,server_id) VALUES(?,?,?,?,?,?)',
                       (ts, int(current['reachable']), current.get('online'), current.get('latency_ms'), json.dumps(stored), sid))
            if close_reason:
                for session in db.execute('SELECT id,player,start,last_seen FROM sessions WHERE end IS NULL AND server_id=?', (sid,)).fetchall():
                    last_row = db.execute('SELECT last_seen FROM players WHERE name=? AND server_id=?', (session['player'], sid)).fetchone()
                    last = session['last_seen'] or session['start']
                    seconds = max(0, (datetime.fromisoformat(last)-datetime.fromisoformat(session['start'])).total_seconds())
                    db.execute('UPDATE sessions SET end=?,seconds=?,end_reason=? WHERE id=?',
                               (last, seconds, close_reason, session['id']))
            for name in sample_names:
                confirmed = 1 if name in confirmed_names else 0
                db.execute(
                    'INSERT INTO players(server_id,name,first_seen,last_seen,observations,confirmed_observations) VALUES(?,?,?,?,1,?) '
                    'ON CONFLICT(server_id,name) DO UPDATE SET last_seen=excluded.last_seen,observations=observations+1,'
                    'confirmed_observations=confirmed_observations+excluded.confirmed_observations',
                    (sid, name, ts, ts, confirmed))
            for name in confirmed_names:
                db.execute('UPDATE sessions SET last_seen=? WHERE server_id=? AND player=? AND end IS NULL', (ts,sid,name))
            for kind, player, detail, confidence in events:
                if kind in ('join_observed', 'online_observed') and confidence == 'confirmed':
                    db.execute('INSERT INTO sessions(player,start,start_kind,server_id,confidence,last_seen) VALUES(?,?,?,?,?,?)',
                               (player, ts, kind, sid, confidence, ts))
                if kind == 'leave_observed' and player:
                    session = db.execute('SELECT id,start FROM sessions WHERE player=? AND end IS NULL AND server_id=?', (player, sid)).fetchone()
                    if session:
                        seconds = max(0, (datetime.fromisoformat(ts)-datetime.fromisoformat(session['start'])).total_seconds())
                        db.execute('UPDATE sessions SET end=?,seconds=?,end_reason=? WHERE id=?',
                                   (ts, seconds, 'leave_observed', session['id']))
                db.execute('INSERT INTO events(ts,kind,player,detail,server_id) VALUES(?,?,?,?,?)', (ts, kind, player, detail, sid))

    def prune(self, days):
        cutoff = datetime.fromtimestamp(time.time()-days*86400, timezone.utc).isoformat(timespec='seconds')
        with self.connect() as db:
            db.execute('DELETE FROM checks WHERE ts < ?', (cutoff,))
            db.execute('DELETE FROM events WHERE ts < ?', (cutoff,))
            db.execute('DELETE FROM sessions WHERE end IS NOT NULL AND end < ?', (cutoff,))
            db.execute('DELETE FROM players WHERE last_seen < ?', (cutoff,))
            for row in db.execute('SELECT id,end,last_seen FROM sessions WHERE start<? AND (end IS NULL OR end>=?)',(cutoff,cutoff)).fetchall():
                end=row['end'] or row['last_seen']
                seconds=max(0,(datetime.fromisoformat(end)-datetime.fromisoformat(cutoff)).total_seconds()) if end else 0
                db.execute('UPDATE sessions SET start=?,seconds=CASE WHEN end IS NULL THEN NULL ELSE ? END,start_kind=? WHERE id=?',(cutoff,seconds,'retention_boundary',row['id']))

    def dashboard(self, hours):
        cutoff = datetime.fromtimestamp(time.time()-hours*3600, timezone.utc).isoformat(timespec='seconds')
        with self.connect() as db:
            db = ScopedRead(db, self.server_id)
            latest = db.execute('SELECT data FROM checks ORDER BY id DESC LIMIT 1').fetchone()
            totals = dict(db.execute('SELECT COUNT(*) checks,SUM(reachable) successes,MAX(online) peak,AVG(CASE WHEN reachable=1 THEN online END) avg_online,AVG(latency) avg_latency FROM checks WHERE ts>=?', (cutoff,)).fetchone())
            totals['availability'] = round(100*(totals['successes'] or 0)/totals['checks'], 2) if totals['checks'] else None
            # Bound payload; retain outages and extrema via per-bucket values.
            bucket = max(30, int(hours*3600/600))
            series = [dict(r) for r in db.execute("SELECT MIN(ts) ts,AVG(online) online,MAX(online) peak,AVG(latency) latency,MIN(reachable) reachable FROM checks WHERE ts>=? GROUP BY CAST(strftime('%s',ts) AS INTEGER)/? ORDER BY ts", (cutoff,bucket))]
            events = [dict(r) for r in db.execute('SELECT * FROM events WHERE ts>=? ORDER BY id DESC LIMIT 200', (cutoff,))]
            players = [dict(r) for r in db.execute('SELECT p.*,COALESCE((SELECT SUM(seconds) FROM sessions s WHERE s.player=p.name AND s.server_id=p.server_id),0) observed_seconds,(SELECT COUNT(*) FROM sessions s WHERE s.player=p.name AND s.server_id=p.server_id) sessions FROM players p ORDER BY last_seen DESC LIMIT 500')]
            sessions = [dict(r) for r in db.execute('SELECT * FROM sessions ORDER BY id DESC LIMIT 100')]
            size = Path(self.path).stat().st_size
            return dict(latest=json.loads(latest['data']) if latest else None, stats=totals, series=series, events=events, players=players, sessions=sessions, hours=hours, bucket_seconds=bucket, database_bytes=size)


class Collector:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.previous = None
        self.query_due = 0
        self.query_enabled = False
        self.endpoint = None
        self.endpoint_due = 0
        self.observer = None
        self.dns_info = {}

    def resolve(self):
        cfg = self.config
        host, port = cfg['host'], cfg['port']
        if cfg['resolve_srv'] and port == 25565:
            # Raspberry Pi OS dnsutils supplies dig; no Python dependencies.
            try:
                result = subprocess.run(['dig', '+short', '+time=2', '+tries=1', 'SRV', '_minecraft._tcp.'+host], capture_output=True, text=True, timeout=3, check=True)
                candidates = []
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts)==4 and parts[0].isdigit() and parts[2].isdigit():
                        candidates.append((int(parts[0]), -int(parts[1]), parts[3].rstrip('.'), int(parts[2])))
                if candidates:
                    _,_,host,port = sorted(candidates)[0]
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        try:
            began=time.monotonic()
            addresses=sorted(set(r[4][0] for r in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)))
            self.dns_info=dict(addresses=addresses,lookup_ms=round((time.monotonic()-began)*1000,2),resolved_at=now())
        except OSError as exc:
            self.dns_info=dict(error=str(exc),resolved_at=now())
        self.endpoint = (host,port)
        self.endpoint_due = time.monotonic()+300
        return host,port

    def check(self, persist=True):
        cfg = self.config
        if not self.endpoint or time.monotonic() >= self.endpoint_due:
            self.resolve()
        host, port = self.endpoint
        record = dict(timestamp=now(), server=cfg['host'], endpoint=f'{host}:{port}', reachable=False,
                      names=[], names_complete=False, interval=cfg['interval'], dns=self.dns_info,
                      server_id=getattr(self.store, 'server_id', 1), edition='java')
        started = time.monotonic()
        timeouts = dict(status=cfg.get('status_timeout', 5), query=cfg.get('query_timeout', 3), ping=cfg.get('ping_timeout', 5))
        try:
            raw = status(cfg['host'], cfg['port'], host, port, timeout=timeouts['status'])
            response_ms = round((time.monotonic()-started)*1000,2)
            if not isinstance(raw, dict):
                raise ValueError('Invalid status response')
            players = raw.get('players', {})
            count = players.get('online')
            sample = players.get('sample') or []
            names = sorted(set(p['name'] for p in sample if isinstance(p,dict) and isinstance(p.get('name'),str)))
            extra_keys = sorted(set(raw) - {'description', 'players', 'version', 'favicon', 'enforcesSecureChat', 'forgeData', 'modinfo', 'modpackData'})
            record.update(reachable=True, online=count, maximum=players.get('max'), version=raw.get('version',{}).get('name'),
                          protocol=raw.get('version',{}).get('protocol'), motd=plain(raw.get('description')),
                          response_ms=response_ms, names=names, names_complete=False,
                          name_source='status sample (onbevestigd)', sample=sample,
                          enforces_secure_chat=raw.get('enforcesSecureChat'), raw_status=raw,
                          unknown_status_fields=extra_keys)
            try:
                record['latency_ms'] = ping(host, port, timeout=timeouts['ping'])
            except (OSError, ValueError) as exc:
                record['ping_error'] = str(exc)
            if self.query_enabled or time.monotonic() >= self.query_due:
                try:
                    q = full_query(host, cfg['query_port'], timeout=timeouts['query'])
                    self.query_enabled = True
                    record.update(query=q, query_available=True, query_error=None)
                except (OSError,ValueError) as exc:
                    self.query_enabled = False
                    self.query_due = time.monotonic()+cfg['query_interval']
                    record.update(query_available=False, query_error=str(exc))
            else:
                record.update(query_available=False, query_retry_seconds=max(0,round(self.query_due-time.monotonic())))
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            record['error'] = str(exc)
        classify(record)
        mark_stale(record, self.previous if persist else None, cfg['interval'])
        if persist:
            self.store.add(record, self.previous)
            if self.observer:
                self.observer(record, self.previous)
            self.previous = record
        return record

    def run(self):
        cleanup_due = 0
        while not STOP.is_set():
            started = time.monotonic()
            try:
                if not self.config.get('host'):
                    STOP.wait(1)
                    continue
                r = self.check()
                print(f"{r['timestamp']} reachable={r['reachable']} players={r.get('online','?')}", flush=True)
                if started >= cleanup_due:
                    self.store.prune(self.config['retention_days'])
                    cleanup_due = started+3600
            except Exception as exc:
                print(f'Collector error: {exc}', flush=True)
            STOP.wait(max(1,self.config['interval']-(time.monotonic()-started)))


def make_handler(store, cfg, services=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, mime):
            self.send_response(code)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            if self.path.startswith('/export/'):
                filename = urlparse(self.path).path.rsplit('/', 1)[-1]
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def send_file(self,path,mime):
            self.send_response(200)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(path.stat().st_size))
            self.send_header('Content-Disposition','attachment; filename="monitor-backup.sqlite"')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            try:
                with path.open('rb') as stream:shutil.copyfileobj(stream,self.wfile,65536)
            except (BrokenPipeError,ConnectionResetError):pass

        def export_rows(self, path, hours):
            table=path.rsplit('/',1)[-1].split('.')[0]
            specs={'checks':('ts','reachable','online','latency'),'events':('ts','kind','player','detail'),
                   'players':('name','first_seen','last_seen','observations','confirmed_observations'),
                   'sessions':('player','start','end','seconds','end_reason','start_kind'),
                   'pi':('ts','cpu','temperature','memory','rx','tx'),
                   'chat':('received','source','player','message','original_ts','tz_confidence')}
            raw=table=='raw'
            if raw:table='checks';cols=('data',)
            else:cols=specs[table]
            actual='pi_metrics' if table=='pi' else table
            col={'sessions':'start','chat':'received','players':'last_seen'}.get(table,'ts')
            cutoff=datetime.fromtimestamp(time.time()-hours*3600,timezone.utc).isoformat(timespec='seconds')
            self.send_response(200);self.send_header('Content-Type','application/x-ndjson' if raw else 'text/csv; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers()
            self.close_connection=True
            def csvline(values):
                output=io.StringIO();writer=csv.writer(output)
                writer.writerow(["'"+x if isinstance(x,str) and x.lstrip().startswith(('=','+','-','@')) else x for x in values])
                return output.getvalue().encode()
            try:
                if not raw:self.wfile.write(b'\xef\xbb\xbf'+csvline(cols))
                with store.connect() as db:
                    reader=ScopedRead(db,store.server_id)
                    for row in reader.execute(f"SELECT {','.join(cols)} FROM {actual} WHERE {col}>=? ORDER BY {col}",(cutoff,)):
                        self.wfile.write((row[0]+'\n').encode() if raw else csvline(row))
            except (BrokenPipeError,ConnectionResetError):pass

        def authorized(self):
            if not services:
                return True
            auth=self.headers.get('Authorization','')
            try:
                user,password=base64.b64decode(auth[6:],validate=True).decode().split(':',1) if auth.startswith('Basic ') else ('','')
                valid=user==services['prefs'].username() and services['prefs'].authenticate(password)
            except (ValueError,UnicodeError):valid=False
            if not valid:
                self.send_response(401);self.send_header('WWW-Authenticate','Basic realm="Uitgeteld Monitor"');self.send_header('Content-Length','0');self.end_headers()
            return valid

        def json_response(self,data,code=200):
            return self.send(code,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8')

        def do_POST(self):
            if not services:return self.send(404,b'Not found','text/plain')
            route=urlparse(self.path).path
            if route == '/api/radar/ingest':
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 256 * 1024:
                        return self.json_response({'error':'Invalid payload size'}, 413)
                    self.connection.settimeout(10)
                    payload = json.loads(self.rfile.read(size))
                    header = self.headers.get('Authorization', '')
                    key = header[7:] if header.startswith('Bearer ') else ''
                    success, result = services['radar'].accept(key, payload)
                    if not success:
                        return self.json_response({'error':result}, 403)
                    return self.json_response({'ok':True,'contacts':len(result['tracks'])})
                except (ValueError, TypeError, OSError, json.JSONDecodeError):
                    return self.json_response({'error':'Invalid radar request'}, 400)
            if route in ('/api/setup','/api/setup/test'):
                return self.handle_setup(route)
            relay=route=='/api/chat/ingest' and self.headers.get('Authorization','').startswith('Bearer ')
            if relay:
                if not hmac.compare_digest(self.headers.get('Authorization','')[7:],services['prefs'].get()['chat_token']):
                    return self.json_response({'error':'Ongeldige chatsleutel'},403)
            else:
                if not self.authorized():return
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),services['csrf']):
                    return self.json_response({'error':'Ververs de pagina en probeer opnieuw'},403)
                origin=self.headers.get('Origin')
                if origin and urlparse(origin).netloc!=self.headers.get('Host'):
                    return self.json_response({'error':'Ongeldige oorsprong'},403)
            try:
                limit=15*1024*1024 if route=='/api/update' else 2*1024*1024
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=limit:raise ValueError('Aanvraag leeg of te groot')
                self.connection.settimeout(20)
                body=self.rfile.read(size)
                if len(body)!=size:raise ValueError('Upload onvolledig')
                if route=='/api/update':
                    if not os.environ.get('MONITOR_SUPERVISED'):raise ValueError('Start via launcher.py of voer de nieuwe install.sh één keer uit')
                    version,_=updater.inspect_release(body)
                    services['insights'].backup()
                    version=updater.install(ROOT,body)
                    self.json_response({'ok':True,'version':version,'message':'Update gecontroleerd. De app herstart.'})
                    services['insights'].notice('update','Update gestart',version)
                    RESTART.set()
                    threading.Timer(1,lambda: os.kill(os.getpid(),signal.SIGTERM)).start()
                    return
                data=json.loads(body)
                if route=='/api/settings':
                    result=services['prefs'].update(data)
                    cfg.update(interval=result['monitor_interval'],retention_days=result['server_retention_days'])
                    for key in ('status_timeout','query_timeout','ping_timeout'):cfg[key]=result[key]
                    save_servers(services.get('config_path',ROOT/'config.json'),[cfg],extra={'interval':cfg['interval'],'retention_days':cfg['retention_days']})
                    return self.json_response(result)
                if route=='/api/servers':
                    return self.json_response(self.save_server_profiles(data))
                if route=='/api/updates/check':
                    include=services['prefs'].get().get('include_prereleases', False)
                    info=github_update.cached_releases(Path(store.path).parent,force=True,include_prerelease=include)
                    latest=(info.get('releases') or [None])[0]
                    info['newer']=bool(latest and github_update.newer(latest['tag'],VERSION))
                    return self.json_response(info)
                if route=='/api/updates/install':
                    if not os.environ.get('MONITOR_SUPERVISED'):raise ValueError('Start via launcher.py')
                    tag=data.get('tag')
                    include=services['prefs'].get().get('include_prereleases', False)
                    info=github_update.cached_releases(Path(store.path).parent, include_prerelease=include)
                    release=next((r for r in info.get('releases') or [] if r.get('tag')==tag), None)
                    if not release:raise ValueError('Release niet gevonden')
                    if not github_update.newer(release['tag'],VERSION):raise ValueError('Deze release is niet nieuwer')
                    blob=github_update.download_release(release, Path(store.path).parent/'update-downloads')
                    version,_=updater.inspect_release(blob)
                    services['insights'].backup()
                    version=updater.install(ROOT,blob)
                    self.json_response({'ok':True,'version':version,'message':'GitHub-update gecontroleerd. De app herstart.'})
                    services['insights'].notice('update','Update gestart',version)
                    RESTART.set()
                    threading.Timer(1,lambda: os.kill(os.getpid(),signal.SIGTERM)).start()
                    return
                if route=='/api/test-notification':
                    services['notifier'].emit('test','Uitgeteld testmelding','Testmelding van de monitor. Controleer zelf de ontvangst op je telefoon.',test=True)
                    return self.json_response({'ok':True,'message':'Test in wachtrij; controleer het meldingenlog.'})
                if route=='/api/chat/ingest':
                    count=services['chat'].ingest(data.get('lines'),data.get('source'),now())
                    return self.json_response({'ok':True,'imported':count})
                if route=='/api/password':
                    if os.environ.get('MONITOR_PASSWORD'):raise ValueError('Wachtwoord staat in monitor.env; wijzig het daar')
                    password=data.get('password','')
                    if not isinstance(password,str) or not 12<=len(password)<=200:raise ValueError('Gebruik 12–200 tekens')
                    services['prefs'].set_password(password)
                    (ROOT/'data/first-login.txt').unlink(missing_ok=True)
                    return self.json_response({'ok':True,'message':'Nieuw wachtwoord ingesteld. Log opnieuw in.'})
                return self.json_response({'error':'Onbekende actie'},404)
            except (ValueError,TypeError,KeyError,OSError,SyntaxError,zipfile.BadZipFile) as exc:
                return self.json_response({'error':str(exc)},400)

        def handle_setup(self, route):
            try:
              with services.setdefault('setup_lock',threading.Lock()):
                return self._handle_setup(route)
            except (ValueError,TypeError,KeyError,OSError) as exc:
                return self.json_response({'error':str(exc)},400)

        def _handle_setup(self, route):
            data_dir=Path(store.path).parent
            if setup_is_complete(data_dir):
                return self.json_response({'error':'Installatie is al voltooid'},400)
            self.connection.settimeout(20)
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=65536:raise ValueError('Aanvraag leeg of te groot')
            data=json.loads(self.rfile.read(size))
            token=setup_token(data_dir)
            if not token or not hmac.compare_digest(str(data.get('setup_token','')), token):
                return self.json_response({'error':'Ongeldige setup-sleutel. Staat in data/setup-token.txt op de Pi.'},403)
            if route=='/api/setup/test':
                host=str(data.get('host','')).strip()
                port=int(data.get('port') or 25565)
                query_port=int(data.get('query_port') or port)
                return self.json_response(self.probe_server(host, port, query_port, bool(data.get('resolve_srv', True))))
            username=str(data.get('username') or 'admin')
            password=str(data.get('password') or '')
            if not re.fullmatch(r'[A-Za-z0-9._-]{3,32}', username):raise ValueError('Gebruikersnaam: 3–32 letters/cijfers')
            if not 12<=len(password)<=200:raise ValueError('Wachtwoord: 12–200 tekens')
            host=str(data.get('host','')).strip()
            if not host or host.startswith('-'):raise ValueError('Vul een Minecraft Java-host in')
            port=int(data.get('port') or 25565)
            query_port=int(data.get('query_port') or port)
            if not 1<=port<=65535 or not 1<=query_port<=65535:raise ValueError('Ongeldige poort')
            services['prefs'].set_password(password, username=username)
            with store.connect() as db:
                db.execute('INSERT OR REPLACE INTO servers(id,slug,display_name,host,port,query_port,resolve_srv,created) VALUES(1,?,?,?,?,?,1,?)',
                           ('default', host, host, port, query_port, now()))
                db.execute("INSERT OR REPLACE INTO setup_state(k,v) VALUES('complete','1')")
            save_servers(services.get('config_path',ROOT/'config.json'), [dict(host=host,port=port,query_port=query_port,resolve_srv=True)])
            cfg.update(host=host,port=port,query_port=query_port)
            if services.get('collector'):
                services['collector'].endpoint=None;services['collector'].previous=None
            ntfy=data.get('notifications') or {}
            if ntfy.get('enabled'):
                patch={k:ntfy[k] for k in ('enabled','ntfy_url','topic','ntfy_token') if k in ntfy}
                services['prefs'].update(patch)
            (data_dir/'setup-token.txt').unlink(missing_ok=True)
            (data_dir/'first-login.txt').unlink(missing_ok=True)
            return self.json_response({'ok':True,'message':'Installatie voltooid. Log in en open het dashboard.','restart_needed':True})

        def probe_server(self, host, port, query_port, resolve_srv):
            from observe import classify as classify_obs
            collector=Collector(dict(DEFAULTS, host=host, port=port, query_port=query_port, resolve_srv=resolve_srv), store)
            record=collector.check(persist=False)
            classify_obs(record)
            return dict(
                reachable=record.get('reachable'), error=record.get('error'),
                version=record.get('version'), motd=record.get('motd'),
                online=record.get('online'), maximum=record.get('maximum'),
                query_available=record.get('query_available'), query_error=record.get('query_error'),
                observation=record.get('observation'), names=record.get('names'),
                names_complete=record.get('names_complete'), list_confidence=record.get('list_confidence'),
                name_source=record.get('name_source'), latency_ms=record.get('latency_ms'),
                edition='Java Edition (status/query). Bedrock wordt niet ondersteund.',
                limitation='Zonder Query is de spelerslijst vaak onvolledig. Joins/vertrekken vereisen twee opeenvolgende volledige lijsten (consistente Query-lijsten; statussamples blijven onbevestigd).',
            )

        def save_server_profiles(self, data):
            host=str(data.get('host','')).strip()
            if not host or host.startswith('-'):raise ValueError('Ongeldige host')
            port=int(data.get('port') or 25565)
            query_port=int(data.get('query_port') or port)
            display=str(data.get('display_name') or host)[:80]
            replace=True
            if not 1<=port<=65535 or not 1<=query_port<=65535:raise ValueError('Ongeldige poort')
            with store.connect() as db:
                if replace:
                    current=db.execute('SELECT host,port FROM servers WHERE id=?', (store.server_id,)).fetchone()
                    if current and (current['host']!=host or current['port']!=port):
                        db.execute('INSERT INTO servers(slug,display_name,host,port,query_port,resolve_srv,created) VALUES(?,?,?,?,?,1,?)',
                                   ('srv-'+secrets.token_hex(4), display, host, port, query_port, now()))
                        new_id=db.execute('SELECT last_insert_rowid()').fetchone()[0]
                        pass  # New profile activates with the restarted collector.
                    else:
                        db.execute('UPDATE servers SET display_name=?,host=?,port=?,query_port=? WHERE id=?',
                                   (display, host, port, query_port, store.server_id))
                else:
                    db.execute('INSERT INTO servers(slug,display_name,host,port,query_port,resolve_srv,created) VALUES(?,?,?,?,?,1,?)',
                               ('srv-'+secrets.token_hex(4), display, host, port, query_port, now()))
                rows=[dict(r) for r in db.execute('SELECT * FROM servers ORDER BY id')]
            save_servers(services.get('config_path',ROOT/'config.json'), [dict(host=host,port=port,query_port=query_port)])
            if os.environ.get('MONITOR_SUPERVISED'):
                RESTART.set()
                threading.Timer(1,lambda: os.kill(os.getpid(),signal.SIGTERM)).start()
            return dict(ok=True, servers=rows, message='Nieuw profiel opgeslagen; de monitor herstart. Oude historie blijft in het oorspronkelijke profiel.')

        def do_GET(self):
            parsed_early=urlparse(self.path)
            if parsed_early.path=='/api/bootstrap':
                data_dir=Path(store.path).parent if store else ROOT/'data'
                return self.json_response(dict(setup_required=not setup_is_complete(data_dir), version=VERSION, product=PRODUCT, edition='java'))
            data_dir=Path(store.path).parent if store else ROOT/'data'
            static_ok=parsed_early.path in ('/','/app.js','/style.css','/extended.js','/extended.css','/setup.js')
            if services and not setup_is_complete(data_dir) and static_ok:
                pass
            elif services and not self.authorized():
                return
            password = os.environ.get('MONITOR_PASSWORD') if not services else None
            if password:
                expected = 'Basic '+base64.b64encode((os.environ.get('MONITOR_USERNAME','admin')+':'+password).encode()).decode()
                if not hmac.compare_digest(self.headers.get('Authorization',''),expected):
                    self.send_response(401)
                    self.send_header('WWW-Authenticate','Basic realm="Uitgeteld Monitor"')
                    self.send_header('Content-Length','0')
                    self.end_headers()
                    return
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            try:
                hours = int(params.get('hours',['24'])[0])
                if hours not in (1,6,24,168,720):
                    raise ValueError()
            except ValueError:
                return self.send(400,b'Invalid hours', 'text/plain')
            if parsed.path in ('/export/checks.csv','/export/events.csv','/export/players.csv','/export/sessions.csv','/export/pi.csv','/export/chat.csv','/export/raw.jsonl'):
                return self.export_rows(parsed.path,hours)
            if parsed.path=='/api/health':
                with store.connect() as db:db.execute('SELECT 1').fetchone()
                return self.json_response(dict(ok=True,version=VERSION,setup_complete=setup_is_complete(Path(store.path).parent)))
            if parsed.path=='/api/history':
                table=params.get('table',['events'])[0]
                if table not in ('events','sessions','players','notices'):return self.json_response({'error':'Onbekende tabel'},400)
                try:offset=max(0,int(params.get('offset',['0'])[0]))
                except ValueError:return self.json_response({'error':'Ongeldige positie'},400)
                field='name' if table=='players' else 'player' if table in ('events','sessions') else 'title'
                search=params.get('q',[''])[0][:100]
                with store.connect() as db:
                    reader=ScopedRead(db,store.server_id)
                    count=reader.execute(f'SELECT COUNT(*) FROM {table} WHERE instr(lower({field}),lower(?))>0',(search,)).fetchone()[0]
                    order='last_seen DESC,name' if table=='players' else 'id DESC'
                    rows=[dict(r) for r in reader.execute(f'SELECT * FROM {table} WHERE instr(lower({field}),lower(?))>0 ORDER BY {order} LIMIT 100 OFFSET ?',(search,offset))]
                return self.json_response(dict(rows=rows,total=count,offset=offset,next_offset=offset+100 if offset+100<count else None))
            if services:
                if parsed.path=='/api/settings':
                    result=services['prefs'].public();result['csrf']=services['csrf'];result['version']=VERSION
                    result['supervised']=bool(os.environ.get('MONITOR_SUPERVISED'))
                    result['local_timezone']=str(datetime.now().astimezone().tzinfo)
                    result['username']=services['prefs'].username()
                    result['product']=PRODUCT
                    result['github']=github_update.load_channel()
                    outcome=ROOT/'data/update-result.json'
                    result['update_result']=json.loads(outcome.read_text()) if outcome.exists() else None
                    with store.connect() as db:
                        result['servers']=[dict(r) for r in db.execute('SELECT id,slug,display_name,host,port,query_port FROM servers ORDER BY id')]
                    return self.json_response(result)
                if parsed.path=='/api/updates':
                    include=services['prefs'].get().get('include_prereleases', False)
                    info=github_update.cached_releases(Path(store.path).parent, include_prerelease=include)
                    info['current']=VERSION
                    latest=(info.get('releases') or [None])[0]
                    info['newer']=bool(latest and github_update.newer(latest.get('tag'), VERSION))
                    info['latest']=latest
                    return self.json_response(info)
                if parsed.path=='/api/insights':return self.json_response(services['insights'].dashboard(hours))
                if parsed.path=='/api/player':
                    result=services['insights'].player(params.get('name',[''])[0])
                    return self.json_response(result if result else {'error':'Speler niet gevonden'},200 if result else 404)
                if parsed.path=='/api/chat':
                    try:before=int(params['before'][0]) if 'before' in params else None
                    except ValueError:return self.json_response({'error':'Ongeldige cursor'},400)
                    return self.json_response(services['chat'].search(params.get('q',[''])[0],params.get('player',[''])[0],before))
                if parsed.path=='/api/live':
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-cache');self.end_headers()
                    try:
                        for _ in range(60):
                            if STOP.is_set():break
                            self.wfile.write(b'data: refresh\n\n');self.wfile.flush();STOP.wait(3)
                    except (BrokenPipeError,ConnectionResetError,OSError):pass
                    return
                if parsed.path=='/export/backup.sqlite':
                    path=services['insights'].backup()
                    return self.send_file(path,'application/vnd.sqlite3')
                if parsed.path in ('/export/players.csv','/export/sessions.csv','/export/pi.csv','/export/chat.csv'):
                    columns={
                      '/export/players.csv':('players',('name','first_seen','last_seen','observations')),
                      '/export/sessions.csv':('sessions',('player','start','end','seconds','end_reason','start_kind')),
                      '/export/pi.csv':('pi_metrics',('ts','cpu','temperature','memory','rx','tx')),
                      '/export/chat.csv':('chat',('received','source','player','message'))}
                    table,cols=columns[parsed.path];output=io.StringIO();writer=csv.writer(output);writer.writerow(cols)
                    with store.connect() as db:
                        cutoff=datetime.fromtimestamp(time.time()-hours*3600,timezone.utc).isoformat(timespec='seconds')
                        timecol={'pi_metrics':'ts','chat':'received','sessions':'start'}.get(table)
                        where=f' WHERE {timecol}>=?' if timecol else ''
                        for row in db.execute(f'SELECT {",".join(cols)} FROM {table}'+where,(cutoff,) if timecol else ()):
                            writer.writerow(["'"+x if isinstance(x,str) and x.startswith(('=','+','-','@')) else x for x in row])
                    return self.send(200,output.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8')
            if services and parsed.path == '/api/radar/live':
                return self.json_response(services['radar'].current())
            if parsed.path=='/api/dashboard':
                data=store.dashboard(hours)
                data['config']={k:cfg[k] for k in ('host','port','query_port','interval','retention_days')}
                return self.send(200,json.dumps(data,ensure_ascii=False).encode(),'application/json; charset=utf-8')
            if parsed.path in ('/export/checks.csv','/export/events.csv','/export/raw.jsonl'):
                cutoff=datetime.fromtimestamp(time.time()-hours*3600,timezone.utc).isoformat(timespec='seconds')
                with store.connect() as db:
                    if parsed.path.endswith('raw.jsonl'):
                        body='\n'.join(r['data'] for r in db.execute('SELECT data FROM checks WHERE ts>=? ORDER BY id',(cutoff,)))+'\n'
                        return self.send(200,body.encode(),'application/x-ndjson')
                    output=io.StringIO(); writer=csv.writer(output)
                    table='events' if 'events' in parsed.path else 'checks'
                    columns=('ts','kind','player','detail') if table=='events' else ('ts','reachable','online','latency')
                    writer.writerow(columns)
                    for row in db.execute(f'SELECT {",".join(columns)} FROM {table} WHERE ts>=? ORDER BY id',(cutoff,)):
                        # Neutralize spreadsheet formula injection from server/player text.
                        writer.writerow(["'"+x if isinstance(x,str) and x.startswith(('=','+','-','@')) else x for x in row])
                    return self.send(200,output.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8')
            files={'/radar':('radar.html','text/html; charset=utf-8'),'/radar.js':('radar.js','text/javascript; charset=utf-8'),'/radar.css':('radar.css','text/css; charset=utf-8'),'/setup.js':('setup.js','text/javascript; charset=utf-8'),'/':('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8'), '/extended.js':('extended.js','text/javascript; charset=utf-8'), '/extended.css':('extended.css','text/css; charset=utf-8')}
            if parsed.path in files:
                filename,mime=files[parsed.path]
                return self.send(200,(ROOT/'web'/filename).read_bytes(),mime)
            self.send(404,b'Not found','text/plain')
    return Handler


def load_config(path):
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    for key in ('port','query_port','web_port'):
        if not isinstance(cfg[key],int) or not 1<=cfg[key]<=65535:
            raise ValueError(f'{key} must be a port')
    if not isinstance(cfg['interval'],(int,float)) or cfg['interval']<10:
        raise ValueError('interval must be at least 10')
    if cfg['query_interval']<30 or cfg['retention_days']<1:
        raise ValueError('Invalid query interval or retention')
    if not isinstance(cfg['host'],str) or cfg['host'].startswith('-'):
        raise ValueError('Invalid host')
    return cfg


def setup_is_complete(data_dir):
    data_dir = Path(data_dir)
    if (data_dir / 'setup-token.txt').exists():
        return False
    if (data_dir / 'admin.json').exists():
        return True
    try:
        db=sqlite3.connect(str(data_dir/'monitor.sqlite'))
        try:
            row=db.execute("SELECT v FROM setup_state WHERE k='complete'").fetchone()
            return bool(row and row[0]=='1')
        finally:db.close()
    except sqlite3.Error:
        return False


def setup_token(data_dir, create=False):
    path = Path(data_dir) / 'setup-token.txt'
    if path.exists():
        return path.read_text().strip()
    if not create:
        return ''
    token = secrets.token_urlsafe(24)
    path.write_text(token + '\n')
    os.chmod(path, 0o600)
    return token


def save_servers(cfg_path, servers, extra=None):
    cfg = load_config(Path(cfg_path)) if Path(cfg_path).exists() else dict(DEFAULTS)
    primary = servers[0]
    cfg['host'] = primary['host']
    cfg['port'] = int(primary['port'])
    cfg['query_port'] = int(primary.get('query_port') or primary['port'])
    cfg['resolve_srv'] = bool(primary.get('resolve_srv', True))
    if extra:
        cfg.update(extra)
    target=Path(cfg_path);temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(cfg,indent=2));temp.chmod(0o600);os.replace(temp,target)
    return cfg


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,default=ROOT/'config.json')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--setup',action='store_true')
    args=parser.parse_args()
    cfg=load_config(args.config)
    path=Path(cfg['database'])
    db_path=path if path.is_absolute() else ROOT/path
    db_path.parent.mkdir(parents=True,exist_ok=True)
    if not (db_path.parent/'admin.json').exists() and not os.environ.get('MONITOR_PASSWORD'):
        setup_token(db_path.parent, create=True)
    store=Store(db_path, host=cfg.get('host') or 'pending', port=cfg['port'], query_port=cfg['query_port'])
    if args.setup:
        Preferences(Path(store.path).parent)
        if not setup_is_complete(Path(store.path).parent):
            token=setup_token(Path(store.path).parent, create=True)
            print('Eerste installatie: lees de lokale sleutel uit data/setup-token.txt.')
            print('Bewaar data/setup-token.txt; willekeurige bezoekers kunnen zonder deze sleutel geen beheerder maken.')
        print('Instellingen en login zijn voorbereid.');return
    collector=Collector(cfg,store)
    if args.once:
        if not cfg.get('host'):
            print('Geen serverhost geconfigureerd.'); return
        print(json.dumps(collector.check(),indent=2)); return
    pref_path=Path(store.path).parent/'settings.json'
    old_preferences=json.loads(pref_path.read_text()) if pref_path.exists() else {}
    prefs=Preferences(Path(store.path).parent)
    for key,value in (('monitor_interval',cfg['interval']),('server_retention_days',cfg['retention_days'])):
        if key not in old_preferences:prefs.values[key]=value
    prefs.save()
    insights=Insights(store);notifier=Notifier(prefs,insights,STOP)
    cfg.update(interval=prefs.get()['monitor_interval'],retention_days=prefs.get()['server_retention_days'])
    for key in ('status_timeout','query_timeout','ping_timeout'):cfg[key]=prefs.get()[key]
    chat=ChatLog(store,notifier,prefs)
    services=dict(prefs=prefs,insights=insights,notifier=notifier,chat=chat,radar=RadarFeed(Path(store.path).parent),csrf=secrets.token_urlsafe(32),collector=collector,config_path=args.config)
    def observe(current,previous):
        insights.observe(current,previous);notifier.server(current,previous)
    collector.observer=observe
    sampler=PiSampler(store.path)
    def pi_loop():
        backup_due=0;prune_due=0
        while not STOP.is_set():
            try:
                values=sampler.sample();insights.add_pi(values);notifier.pi(values)
                settings=prefs.get()
                if settings['backups_enabled'] and time.monotonic()>backup_due:
                    insights.backup();backup_due=time.monotonic()+86400
                if time.monotonic()>prune_due:
                    insights.prune(cfg['retention_days'],settings['pi_retention_days'])
                    with store.connect() as db:db.execute('DELETE FROM chat WHERE received<?',(datetime.fromtimestamp(time.time()-cfg['retention_days']*86400,timezone.utc).isoformat(timespec='seconds'),))
                    prune_due=time.monotonic()+3600
            except Exception as exc:print(f'Pi telemetry: {exc}',flush=True)
            STOP.wait(prefs.get()['pi_interval'])
    def update_loop():
        while not STOP.is_set():
            try:
                settings=prefs.get()
                info=github_update.cached_releases(Path(store.path).parent,include_prerelease=settings['include_prereleases'])
                latest=(info.get('releases') or [None])[0]
                if settings['auto_install_updates'] and os.environ.get('MONITOR_SUPERVISED') and latest and github_update.newer(latest['tag'],VERSION):
                    blob=github_update.download_release(latest,Path(store.path).parent/'update-downloads')
                    updater.install(ROOT,blob);RESTART.set();os.kill(os.getpid(),signal.SIGTERM);return
            except Exception:
                print('Updatecontrole mislukt; zie Instellingen voor handmatige controle.',flush=True)
            STOP.wait(prefs.get()['github_check_hours']*3600)
    server=ThreadingHTTPServer((cfg['bind'],cfg['web_port']),make_handler(store,cfg,services))
    server.daemon_threads=True
    def stop(signum,frame):
        STOP.set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    worker=threading.Thread(target=collector.run,daemon=True); worker.start()
    threading.Thread(target=pi_loop,daemon=True).start()
    threading.Thread(target=notifier.run,daemon=True).start()
    threading.Thread(target=update_loop,daemon=True).start()
    # Startup health marker is written only after database queries and HTTP bind succeed.
    store.dashboard(1);insights.dashboard(1)
    (ROOT/'data/app-ready.json').write_text(json.dumps(dict(version=VERSION,timestamp=now())))
    if not setup_is_complete(Path(store.path).parent):
        token=setup_token(Path(store.path).parent, create=True)
        print(f'Setup vereist. Open http://<pi-ip>:{cfg["web_port"]} en gebruik sleutel uit data/setup-token.txt', flush=True)
        print('Setup-sleutel staat in data/setup-token.txt (alleen lokaal leesbaar).', flush=True)
    print(f"Dashboard: http://<host>:{cfg['web_port']}",flush=True)
    try:
        server.serve_forever(poll_interval=.3)
    finally:
        STOP.set(); server.server_close(); worker.join(timeout=20)
    if RESTART.is_set():sys.exit(42)


if __name__=='__main__':
    main()
