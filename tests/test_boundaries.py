from datetime import datetime,timezone
import io
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from settings import Preferences,Notifier
from insights import Insights
from telemetry import cpu_percent

class Boundaries(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=app.Store(Path(self.tmp.name)/'monitor.sqlite');self.insights=Insights(self.store)
        self.prefs=Preferences(self.tmp.name);self.notifier=Notifier(self.prefs,self.insights,threading.Event())
    def tearDown(self):self.tmp.cleanup()
    def test_quiet_hours_cover_both_repeated_dst_hours(self):
        self.prefs.update({'quiet_start':'23:00','quiet_end':'07:00','quiet_timezone':'Europe/Amsterdam'})
        for instant,expected in [('2026-10-25T00:30:00+00:00',True),('2026-10-25T01:30:00+00:00',True),('2026-10-25T12:00:00+00:00',False)]:
            fixed=datetime.fromisoformat(instant)
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None):return fixed.astimezone(tz)
            with patch('settings.datetime',Clock):self.assertEqual(self.notifier._quiet(self.prefs.get()),expected)
    def test_permanent_provider_error_not_retried(self):
        self.notifier.emit('test','Fixture','Fixture',test=True)
        with patch('settings.deliver',side_effect=HTTPError('https://provider',401,'unauthorized',{},io.BytesIO(b''))):self.notifier.process_one()
        with self.store.connect() as db:
            row=db.execute('SELECT status,attempts FROM delivery_queue').fetchone();self.assertEqual(tuple(row),('failed',1))
    def test_retention_clips_crossing_session(self):
        start='2026-10-08T12:00:00+00:00';end='2026-10-10T12:00:00+00:00'
        with self.store.connect() as db:db.execute('INSERT INTO sessions(player,start,end,seconds,server_id) VALUES(?,?,?,?,1)',('Fixture',start,end,172800))
        with patch('app.time.time',return_value=datetime.fromisoformat(end).timestamp()):self.store.prune(1)
        with self.store.connect() as db:
            row=db.execute('SELECT start,seconds,start_kind FROM sessions').fetchone();self.assertEqual(tuple(row),('2026-10-09T12:00:00+00:00',86400,'retention_boundary'))
    def test_cpu_counter_reset_is_unknown(self):
        self.assertIsNone(cpu_percent((100,50),(90,40)))

if __name__=='__main__':unittest.main()
