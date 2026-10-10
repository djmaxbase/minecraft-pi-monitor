import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,observe,updater,github_update
from settings import Preferences,Notifier
from insights import Insights
from test_extensions import release

class Correctness(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=app.Store(self.root/'monitor.sqlite');self.insights=Insights(self.store)
        self.prefs=Preferences(self.root);self.notify=Notifier(self.prefs,self.insights,threading.Event())
    def tearDown(self):self.temp.cleanup()
    def rec(self,second,names,query=True,count=None):
        r=dict(timestamp=(datetime(2099,1,1,tzinfo=timezone.utc)+timedelta(seconds=second)).isoformat(),reachable=True,online=len(names) if count is None else count,names=names,query_available=query)
        if query:r['query']={'names':names,'metadata':{'numplayers':str(r['online'])}}
        return observe.classify(r)
    def test_equal_length_sample_is_never_complete(self):
        old=self.rec(0,['A'],False);new=self.rec(30,['B'],False)
        self.assertEqual(new['observation'],'partial')
        self.assertEqual([x[0] for x in observe.player_events(old,new)],['sample_appeared'])
    def test_conflicting_empty_sample(self):
        self.assertEqual(self.rec(0,['A'],False,0)['observation'],'conflicting')
    def test_gap_does_not_count_sample_time(self):
        prior=None
        for second,names,query in [(0,['A'],True),(30,['A'],True),(60,['A'],False),(90,['A'],False),(120,['A'],True)]:
            current=self.rec(second,names,query);self.store.add(current,prior);prior=current
        with self.store.connect() as db:
            rows=db.execute('SELECT seconds,end_reason FROM sessions ORDER BY id').fetchall()
        self.assertEqual(rows[0]['seconds'],30);self.assertEqual(rows[0]['end_reason'],'observation_gap');self.assertIsNone(rows[1]['seconds'])
    def test_long_gap_not_a_join(self):
        old=self.rec(0,['A']);new=self.rec(300,['B']);observe.mark_stale(new,old,30)
        self.assertNotIn('join_observed',[x[0] for x in observe.player_events(old,new)])
    def test_server_read_isolation(self):
        a=self.rec(0,['A']);self.store.add(a,None);self.insights.observe(a,None)
        self.store.server_id=2;b=self.rec(30,['B']);b['server_id']=2;self.store.add(b,None);self.insights.observe(b,None)
        self.assertEqual([p['name'] for p in self.store.dashboard(24)['players']],['B'])
        self.assertIsNone(self.insights.player('A'))
        self.assertEqual(self.insights.dashboard(24)['analytics']['coverage']['total'],1)
    def test_queue_survives_restart_and_provider_failure(self):
        self.prefs.update({'enabled':True});nid=self.notify.emit('join','A','sample',player='A')
        restarted=Notifier(self.prefs,self.insights,threading.Event())
        with patch('settings.deliver',side_effect=HTTPError('https://provider',429,'limit',{'Retry-After':'120'},io.BytesIO(b''))):
            self.assertTrue(restarted.process_one())
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM delivery_queue').fetchone();self.assertEqual(row['status'],'retry');self.assertEqual(row['attempts'],1)
            db.execute("UPDATE delivery_queue SET next_attempt='2000-01-01T00:00:00+00:00'")
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self,n):return b'{}'
        with patch('settings.deliver',return_value=Response()):restarted.process_one()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT status FROM delivery_queue').fetchone()[0],'accepted')
    def test_queue_expiry_never_delivers(self):
        self.notify.emit('test','Test','Test',test=True)
        with self.store.connect() as db:db.execute("UPDATE delivery_queue SET expire='2000-01-01T00:00:00+00:00'")
        with patch('settings.deliver') as send:self.notify.process_one();send.assert_not_called()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT status FROM delivery_queue').fetchone()[0],'expired')
    def test_setup_token_takes_precedence_over_generated_admin(self):
        app.setup_token(self.root,create=True);self.assertFalse(app.setup_is_complete(self.root))
        (self.root/'setup-token.txt').unlink();self.assertTrue(app.setup_is_complete(self.root))
    def test_pending_update_cannot_be_overwritten(self):
        root=self.root/'update';(root/'data').mkdir(parents=True)
        updater.install(root,release())
        with self.assertRaises(ValueError):updater.install(root,release())
        updater.rollback(root);updater.install(root,release());updater.rollback(root)
    def test_symlink_archive_rejected(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            link=zipfile.ZipInfo('app.py');link.create_system=3;link.external_attr=(0o120777<<16);z.writestr(link,'/etc/passwd')
        with self.assertRaises(ValueError):updater.inspect_release(out.getvalue())
    def test_semver(self):
        self.assertTrue(github_update.newer('v2.1.0-rc.10','2.1.0-rc.2'))
        self.assertTrue(github_update.newer('2.1.0','2.1.0-rc.10'))
        self.assertFalse(github_update.newer('2.1.0+build2','2.1.0+build1'))
        self.assertIsNone(github_update.parse_semver('2.1.0-01'))
    def test_redirect_blocked_before_request(self):
        with self.assertRaises(ValueError):github_update.validate_url('http://github.com/owner/repo')
        with self.assertRaises(ValueError):github_update.validate_url('https://evil.example/asset.zip')

if __name__=='__main__':unittest.main()
