"""Persistent preferences, admin authentication and optional phone notifications."""
import copy
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

EVENTS = [
    'join', 'leave', 'sample_seen', 'server_down', 'server_up', 'count', 'metadata',
    'high_ping', 'pi_hot', 'disk_low', 'pi_throttle', 'chat',
]


class Preferences:
    def __init__(self, data):
        self.path = Path(data) / 'settings.json'
        self.lock = threading.RLock()
        defaults = dict(
            enabled=False, ntfy_url='https://ntfy.sh', topic='mcmon-' + secrets.token_hex(16), ntfy_token='',
            events={name: name in ('join', 'leave', 'server_down', 'server_up', 'pi_hot', 'disk_low', 'pi_throttle') for name in EVENTS},
            watch_players='', quiet_start='', quiet_end='', quiet_timezone='Europe/Amsterdam',
            ping_threshold=200, temperature_threshold=75, disk_threshold=90,
            alert_cooldown=300, server_failures=2, pi_interval=10, pi_retention_days=30, backups_enabled=True,
            chat_enabled=False, chat_token=secrets.token_urlsafe(32), map_url='',
            include_prereleases=False, auto_install_updates=False, github_check_hours=12,
            status_timeout=5, query_timeout=3, ping_timeout=5, monitor_interval=30, server_retention_days=365,
        )
        self.values = defaults
        if self.path.exists():
            existing = json.loads(self.path.read_text())
            self.values.update(existing)
            self.values['events'] = {**defaults['events'], **existing.get('events', {})}
            if str(self.values.get('topic', '')).startswith('uitgeteld-') and not existing.get('topic_custom'):
                pass
        self.admin_path = Path(data) / 'admin.json'
        if not os.environ.get('MONITOR_PASSWORD') and not self.admin_path.exists():
            password = secrets.token_urlsafe(18)
            self.set_password(password, username='admin')
            (Path(data) / 'first-login.txt').write_text('Gebruikersnaam: admin\nWachtwoord: ' + password + '\n')
            os.chmod(Path(data) / 'first-login.txt', 0o600)
        else:
            self._ensure_username()
        self.save()

    def _ensure_username(self):
        if not self.admin_path.exists():
            return
        try:
            data = json.loads(self.admin_path.read_text())
        except (OSError, ValueError):
            return
        if 'username' not in data:
            data['username'] = 'admin'
            self.admin_path.write_text(json.dumps(data))
            os.chmod(self.admin_path, 0o600)

    def username(self):
        if os.environ.get('MONITOR_USERNAME'):
            return os.environ['MONITOR_USERNAME']
        try:
            return json.loads(self.admin_path.read_text()).get('username', 'admin')
        except (OSError, ValueError):
            return 'admin'

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.values, indent=2))
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)

    def get(self):
        with self.lock:
            return copy.deepcopy(self.values)

    def public(self):
        v = self.get()
        v['ntfy_token_set'] = bool(v.pop('ntfy_token', ''))
        v['chat_token'] = v.get('chat_token', '')
        return v

    def set_password(self, password, username=None):
        salt = secrets.token_hex(16)
        payload = dict(
            salt=salt,
            hash=hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200000).hex(),
            username=username or self.username(),
        )
        self.admin_path.write_text(json.dumps(payload))
        os.chmod(self.admin_path, 0o600)

    def authenticate(self, password):
        override = os.environ.get('MONITOR_PASSWORD')
        if override:
            return hmac.compare_digest(override, password)
        try:
            data = json.loads(self.admin_path.read_text())
            value = hashlib.pbkdf2_hmac('sha256', password.encode(), data['salt'].encode(), 200000).hex()
            return hmac.compare_digest(data['hash'], value)
        except (OSError, ValueError, KeyError):
            return False

    def update(self, changes):
        allowed = {
            'enabled', 'ntfy_url', 'topic', 'ntfy_token', 'events', 'watch_players', 'quiet_start', 'quiet_end',
            'quiet_timezone', 'ping_threshold', 'temperature_threshold', 'disk_threshold', 'alert_cooldown',
            'server_failures', 'pi_interval', 'pi_retention_days', 'backups_enabled', 'chat_enabled', 'map_url',
            'include_prereleases', 'auto_install_updates', 'github_check_hours', 'status_timeout', 'query_timeout',
            'ping_timeout', 'monitor_interval','server_retention_days',
        }
        if not isinstance(changes, dict) or set(changes) - allowed:
            raise ValueError('Onbekende instellingen')
        with self.lock:
            v = self.get()
            if 'ntfy_token' in changes and changes['ntfy_token'] == '':
                changes = dict(changes)
                changes.pop('ntfy_token')
            v.update(changes)
            for key in ('enabled', 'backups_enabled', 'chat_enabled', 'include_prereleases', 'auto_install_updates'):
                if not isinstance(v[key], bool):
                    raise ValueError('Ongeldige schakelaar')
            for key, low, high in [
                ('ping_threshold', 10, 10000), ('temperature_threshold', 30, 100), ('disk_threshold', 50, 99),
                ('alert_cooldown', 10, 86400), ('server_failures', 1, 20), ('pi_interval', 5, 300),
                ('pi_retention_days', 1, 365), ('github_check_hours', 1, 168),
                ('status_timeout', 2, 20), ('query_timeout', 1, 15), ('ping_timeout', 2, 20), ('monitor_interval',10,3600),('server_retention_days',1,3650),
            ]:
                if type(v[key]) is not int or not low <= v[key] <= high:
                    raise ValueError('Ongeldige waarde: ' + key)
            if not isinstance(v['events'], dict) or set(v['events']) - set(EVENTS) or any(type(x) is not bool for x in v['events'].values()):
                raise ValueError('Ongeldige meldingen')
            v['events'] = {name: v['events'].get(name, False) for name in EVENTS}
            url = urlparse(v['ntfy_url'])
            if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment:
                raise ValueError('Gebruik een HTTPS ntfy-serveradres')
            if not re.fullmatch(r'[A-Za-z0-9_-]{8,120}', v['topic']):
                raise ValueError('Topic: 8–120 letters/cijfers/streepjes')
            for key in ('quiet_start', 'quiet_end'):
                if v[key] and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', v[key]):
                    raise ValueError('Gebruik HH:MM voor stille uren')
            try:
                ZoneInfo(v['quiet_timezone'])
            except Exception:
                raise ValueError('Onbekende tijdzone')
            for key in ('watch_players', 'ntfy_token'):
                if not isinstance(v[key], str) or len(v[key]) > 2048:
                    raise ValueError('Tekst te lang')
            if v['map_url'] and (urlparse(v['map_url']).scheme not in ('http', 'https') or not urlparse(v['map_url']).hostname):
                raise ValueError('Ongeldige kaartlink')
            self.values = v
            self.save()
        return self.public()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirect geweigerd: provideradres moet rechtstreeks werken')


def deliver(request):
    return build_opener(NoRedirect()).open(request, timeout=8)


class Notifier:
    def __init__(self, prefs, insights, stop):
        self.prefs = prefs
        self.insights = insights
        self.stop = stop
        self.queue = queue.Queue(maxsize=200)
        self.last = {}
        self.lock = threading.Lock()
        self.failures = 0
        self.down_notified = False
        self.sensor_active = {}
        self.sensor_counts = {}

    def _quiet(self, p):
        start, end = p['quiet_start'], p['quiet_end']
        if not start or not end or start == end:
            return False
        try:
            tz = ZoneInfo(p.get('quiet_timezone') or 'Europe/Amsterdam')
        except Exception:
            tz = datetime.now().astimezone().tzinfo
        now = datetime.now(tz).strftime('%H:%M')
        return (start <= now < end) if start < end else (now >= start or now < end)

    def emit(self, kind, title, message, player=None, test=False, extra_reason=None):
        p = self.prefs.get()
        if not test and kind in ('high_ping', 'pi_hot', 'disk_low', 'pi_throttle'):
            with self.lock:
                if time.monotonic() - self.last.get('log:' + kind, -1e20) < p['alert_cooldown']:
                    return None
                self.last['log:' + kind] = time.monotonic()
        nid = self.insights.notice(kind, title, message)
        if test:
            self._enqueue(nid, title, message, test=True, reason='testmelding')
            return nid
        if not p['enabled']:
            self.insights.delivery(nid, 'gefilterd: hoofdschakelaar uit')
            return nid
        if not p['events'].get(kind):
            self.insights.delivery(nid, 'gefilterd: deze gebeurtenis staat uit')
            return nid
        names = {x.strip().lower() for x in p['watch_players'].split(',') if x.strip()}
        if player and names and player.lower() not in names:
            self.insights.delivery(nid, 'gefilterd: niet op de volglijst')
            return nid
        if self._quiet(p):
            self.insights.delivery(nid, 'gefilterd: stille uren (' + p.get('quiet_timezone', '') + ')')
            return nid
        if kind not in ('join', 'leave', 'sample_seen'):
            with self.lock:
                if time.monotonic() - self.last.get(kind, -1e20) < p['alert_cooldown']:
                    self.insights.delivery(nid, 'gefilterd: herhaalpauze')
                    return nid
                self.last[kind] = time.monotonic()
        self._enqueue(nid, title, message, test=False, reason=extra_reason or 'wachtrij')
        return nid

    def _enqueue(self, nid, title, message, test, reason):
        created = datetime.now(timezone.utc)
        expire = (created + timedelta(hours=24)).isoformat(timespec='seconds')
        with self.insights.store.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM delivery_queue WHERE status IN ('queued','retry')").fetchone()[0]
            if count >= 200:
                db.execute("UPDATE notices SET delivery='mislukt: wachtrij vol' WHERE id=?", (nid,))
                return
            notice = db.execute('SELECT kind FROM notices WHERE id=?', (nid,)).fetchone()
            db.execute("INSERT INTO delivery_queue(created,expire,next_attempt,status,kind,title,message,notice_id,test,server_id) VALUES(?,?,?,'queued',?,?,?,?,?,?)",
                       (created.isoformat(),expire,created.isoformat(),notice['kind'],title,message,nid,int(test),self.insights.store.server_id))
            db.execute("UPDATE notices SET delivery='wachtrij',reason=? WHERE id=?", (reason,nid))
        # Compatibility and wake-up only; SQLite is the authoritative queue.
        try:self.queue.put_nowait(nid)
        except queue.Full:pass

    def process_one(self):
        stamp = datetime.now(timezone.utc)
        with self.insights.store.connect() as db:
            row = db.execute("SELECT * FROM delivery_queue WHERE status IN ('queued','retry') AND next_attempt<=? ORDER BY id LIMIT 1", (stamp.isoformat(),)).fetchone()
        if row is None:return False
        item = dict(row); nid = item['notice_id']; p = self.prefs.get()
        def finish(status, reason):
            with self.insights.store.connect() as db:
                db.execute('UPDATE delivery_queue SET status=?,reason=? WHERE id=?',(status,reason,item['id']))
                db.execute('UPDATE notices SET delivery=?,reason=? WHERE id=?',(reason,reason,nid))
        if stamp >= datetime.fromisoformat(item['expire']):
            finish('expired','verlopen in wachtrij');return True
        if not item['test'] and (not p['enabled'] or not p['events'].get(item['kind'])):
            finish('filtered','gefilterd: uitgeschakeld bij verzenden');return True
        if not item['test'] and self._quiet(p):
            with self.insights.store.connect() as db:
                db.execute("UPDATE delivery_queue SET next_attempt=?,reason='uitgesteld: stille uren' WHERE id=?",((stamp+timedelta(minutes=1)).isoformat(),item['id']))
                db.execute("UPDATE notices SET delivery='uitgesteld: stille uren' WHERE id=?",(nid,))
            return True
        payload=json.dumps(dict(topic=p['topic'],title=item['title'],message=item['message'],priority=3)).encode()
        headers={'Content-Type':'application/json'}
        if p['ntfy_token']:headers['Authorization']='Bearer '+p['ntfy_token']
        attempts=item['attempts']+1; retry=None
        try:
            with deliver(Request(p['ntfy_url'].rstrip('/')+'/',data=payload,headers=headers)) as res:
                res.read(1024);code=res.status
            finish('accepted',f'provider geaccepteerd (HTTP {code}); telefoonontvangst niet bevestigd')
        except HTTPError as exc:
            if exc.code==429 or exc.code>=500:
                retry=min(3600,15*2**min(attempts,8))
                if exc.headers:
                    try:retry=max(retry,min(86400,int(exc.headers.get('Retry-After','0'))))
                    except ValueError:pass
            else:finish('failed',f'mislukt: HTTP {exc.code}; controleer providerinstellingen')
            exc.close()
        except Exception:
            retry=min(3600,15*2**min(attempts,8))
        with self.insights.store.connect() as db:
            db.execute('UPDATE delivery_queue SET attempts=? WHERE id=?',(attempts,item['id']))
            if retry is not None:
                reason=f'opnieuw proberen na {retry}s (poging {attempts}); provider/netwerk niet beschikbaar'
                db.execute("UPDATE delivery_queue SET status='retry',next_attempt=?,reason=? WHERE id=?",((stamp+timedelta(seconds=retry)).isoformat(),reason,item['id']))
                db.execute('UPDATE notices SET delivery=?,reason=? WHERE id=?',(reason,reason,nid))
        return True

    def run(self):
        while not self.stop.is_set():
            try:
                if not self.process_one():self.stop.wait(1)
                while not self.queue.empty():self.queue.get_nowait()
            except Exception:
                self.stop.wait(5)

    def server(self, current, previous):
        from observe import player_events
        p = self.prefs.get()
        if not current['reachable']:
            self.failures += 1
            if self.failures >= p['server_failures'] and not self.down_notified:
                self.down_notified = True
                self.emit('server_down', 'Server onbereikbaar vanaf deze monitor', current.get('error', 'Geen statusantwoord'))
        else:
            if self.down_notified:
                self.emit('server_up', 'Server weer bereikbaar vanaf deze monitor', current.get('server', ''))
            self.failures = 0
            self.down_notified = False
            if previous and previous['reachable']:
                for kind, name, detail, confidence in player_events(previous, current):
                    if kind == 'join_observed':
                        self.emit('join', name + ' is online gekomen', detail, name, extra_reason='bevestigde join')
                    elif kind == 'leave_observed':
                        self.emit('leave', name + ' is weggegaan', detail, name, extra_reason='bevestigd vertrek')
                    elif kind == 'sample_appeared':
                        self.emit('sample_seen', name + ' zichtbaar in sample', 'Niet hetzelfde als een bevestigde join. ' + detail, name)
                if current.get('online') != previous.get('online'):
                    self.emit('count', 'Spelersaantal veranderd', f"{previous.get('online')} → {current.get('online')}")
                if any(current.get(k) != previous.get(k) for k in ('version', 'motd', 'maximum')):
                    self.emit('metadata', 'Serverinformatie gewijzigd', current.get('motd', ''))
            self.threshold('high_ping',current.get('latency_ms'),p['ping_threshold'],'Hoge serverping','ms')

    def threshold(self,kind,value,limit,title,unit):
        if value is None:return
        if value<limit*.9:
            self.sensor_active[kind]=False;self.sensor_counts[kind]=0
        elif value>=limit:
            self.sensor_counts[kind]=self.sensor_counts.get(kind,0)+1
            if self.sensor_counts[kind]>=2 and not self.sensor_active.get(kind):
                self.sensor_active[kind]=True
                self.emit(kind,title,f'{value} {unit}; twee opeenvolgende metingen')

    def pi(self, data):
        p=self.prefs.get()
        self.threshold('pi_hot',data.get('temperature'),p['temperature_threshold'],'Pi-temperatuur hoog','°C')
        disks=[d['percent'] for d in data.get('storage',[]) if d.get('percent') is not None]
        self.threshold('disk_low',max(disks) if disks else None,p['disk_threshold'],'Opslag bijna vol','%')
        flags=data.get('throttle_flags')
        self.threshold('pi_throttle',None if flags is None else int(any('sinds boot' not in x for x in flags)),1,'Pi-prestaties begrensd','actieve vlag')
