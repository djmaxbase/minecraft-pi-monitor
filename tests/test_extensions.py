import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from insights import Insights
from settings import Preferences,Notifier
from chatlogs import ChatLog,parse_chat
from telemetry import PiSampler,cpu_percent,throttle_flags
import updater


def release(bad=False):
    root=Path(__file__).resolve().parents[1]
    files={name:(root/name).read_bytes() for name in updater.REQUIRED}
    if bad:files['app.py']=b'def invalid(\n'
    manifest=dict(format=1,version=files['VERSION'].decode().strip(),files={k:hashlib.sha256(v).hexdigest() for k,v in files.items()})
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,data in files.items():z.writestr('Uitgeteld-Pi/'+name,data)
        z.writestr('Uitgeteld-Pi/release.json',json.dumps(manifest))
        z.writestr('Uitgeteld-Pi/config.json','DO NOT INSTALL THIS')
    return out.getvalue()


class ExtendedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=app.Store(self.root/'db.sqlite')
        self.insights=Insights(self.store);self.prefs=Preferences(self.root);self.stop=threading.Event();self.notify=Notifier(self.prefs,self.insights,self.stop);self.chat=ChatLog(self.store,self.notify,self.prefs)
    def tearDown(self):self.tmp.cleanup()
    def test_auth_and_preferences_persist(self):
        password=(self.root/'first-login.txt').read_text().split('Wachtwoord: ')[1].strip()
        self.assertTrue(self.prefs.authenticate(password));self.assertFalse(self.prefs.authenticate('bad'))
        self.prefs.update({'enabled':True,'pi_interval':15})
        self.assertTrue(Preferences(self.root).get()['enabled'])
        self.assertNotIn('ntfy_token',self.prefs.public())
        with self.assertRaises(ValueError):self.prefs.update({'chat_token':'attack'})
        with self.assertRaises(ValueError):self.prefs.update({'pi_interval':0})
    def test_chat_off_dedup_and_search(self):
        line='[14:50:02] [Server thread/INFO]: <PlayerA> hello <script>alert(1)</script>'
        items=[dict(id='a',line=line)]
        with self.assertRaises(ValueError):self.chat.ingest(items,'server',app.now())
        self.prefs.update({'chat_enabled':True})
        self.assertEqual(self.chat.ingest(items,'server',app.now()),1)
        self.assertEqual(self.chat.ingest(items,'server',app.now()),0)
        self.assertEqual(self.chat.search('hello')['total'],1)
        self.assertEqual(self.chat.search('hello')['rows'][0]['player'],'PlayerA')
        self.assertIsNone(parse_chat('[Server/INFO] Saving chunks'))
    def test_sample_profile_and_incidents(self):
        a=dict(timestamp=app.now(),reachable=True,names=['Sample'],name_source='sample',sample=[{'name':'Sample','id':'uuid'}],names_complete=False,server='test')
        self.insights.observe(a,None)
        self.assertEqual(self.insights.player('Sample')['summary']['confirmed_observations'],0)
        b=dict(timestamp=app.now(),reachable=False,names=[],error='DNS');self.insights.observe(b,a);self.insights.observe(a,b)
        self.assertIsNotNone(self.insights.dashboard(24)['incidents'][0]['end'])
    def test_cpu_and_throttle(self):
        self.assertIsNone(cpu_percent(None,(100,50)))
        self.assertEqual(cpu_percent((100,50),(200,100)),50)
        self.assertIn('Onderspanning actief',throttle_flags(1))
        sampler=PiSampler(self.store.path);a=sampler.sample();self.assertIn('memory',a)
        self.insights.add_pi(a);self.assertIsNotNone(self.insights.dashboard(1)['pi'])
    def test_notification_filters_and_thresholds(self):
        self.notify.emit('join','Join','PlayerA',player='PlayerA');self.assertTrue(self.notify.queue.empty())
        self.prefs.update({'enabled':True,'watch_players':'PlayerA'})
        self.notify.emit('join','Join','PlayerB',player='PlayerB');self.assertTrue(self.notify.queue.empty())
        self.notify.emit('join','Join','PlayerA',player='PlayerA');self.assertEqual(self.notify.queue.qsize(),1)
        self.notify.queue.get_nowait()
        self.prefs.update({'watch_players':'','server_failures':2})
        down=dict(reachable=False,error='Test');self.notify.server(down,None);self.assertTrue(self.notify.queue.empty())
        self.notify.server(down,down);self.assertEqual(self.notify.queue.qsize(),1)
    def test_backup_is_valid(self):
        path=self.insights.backup()
        import sqlite3
        with sqlite3.connect(path) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    def test_update_preserves_data_and_rolls_back(self):
        root=self.root/'app';(root/'data').mkdir(parents=True);(root/'app.py').write_text('old=True\n');(root/'config.json').write_text('{"custom":true}')
        (root/'data/history').write_text('KEEP')
        version=updater.install(root,release());self.assertEqual(version,app.VERSION)
        self.assertEqual((root/'config.json').read_text(),'{"custom":true}');self.assertEqual((root/'data/history').read_text(),'KEEP')
        updater.rollback(root);self.assertEqual((root/'app.py').read_text(),'old=True\n');self.assertFalse((root/'telemetry.py').exists())
    def test_bad_update_rejected(self):
        with self.assertRaises(SyntaxError):updater.inspect_release(release(bad=True))
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('../app.py','bad')
        with self.assertRaises(ValueError):updater.inspect_release(buf.getvalue())
    def test_http_admin_csrf_and_chat_scope(self):
        services=dict(prefs=self.prefs,insights=self.insights,notifier=self.notify,chat=self.chat,csrf='csrf-token',config_path=self.root/'config.json')
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.make_handler(self.store,app.DEFAULTS,services));thread=threading.Thread(target=server.serve_forever);thread.start()
        url=f'http://127.0.0.1:{server.server_port}';password=(self.root/'first-login.txt').read_text().split('Wachtwoord: ')[1].strip();auth='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
        def request(path,data=None,headers=None):
            return urlopen(Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers=headers or {}))
        try:
            with self.assertRaises(HTTPError) as e:request('/api/settings')
            self.assertEqual(e.exception.code,401)
            with request('/api/settings',headers={'Authorization':auth}) as r:self.assertEqual(json.load(r)['csrf'],'csrf-token')
            with self.assertRaises(HTTPError) as e:request('/api/settings',{'enabled':True},{'Authorization':auth})
            self.assertEqual(e.exception.code,403)
            with request('/api/settings',{'chat_enabled':True},{'Authorization':auth,'X-CSRF-Token':'csrf-token'}) as r:self.assertEqual(r.status,200)
            bearer='Bearer '+self.prefs.get()['chat_token']
            with request('/api/chat/ingest',{'source':'fixture','lines':[dict(id='id',line='<PlayerA> hello')]},{'Authorization':bearer}) as r:self.assertEqual(json.load(r)['imported'],1)
            with self.assertRaises(HTTPError) as e:request('/api/settings',{'enabled':True},{'Authorization':bearer,'X-CSRF-Token':'csrf-token'})
            self.assertEqual(e.exception.code,401)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
