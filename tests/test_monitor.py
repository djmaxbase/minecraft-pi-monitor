import base64
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import protocol


class ProtocolTests(unittest.TestCase):
    def test_status_framing(self):
        server=socket.socket();server.bind(('127.0.0.1',0));server.listen();port=server.getsockname()[1]
        errors=[]
        def fixture():
            try:
                c,_=server.accept()
                with c:
                    protocol.read_exact(c,protocol.read_varint(c))
                    self.assertEqual(protocol.read_exact(c,2),b'\x01\x00')
                    body=json.dumps({'players':{'online':2,'max':20}}).encode()
                    packet=b'\x00'+protocol.varint(len(body))+body
                    c.sendall(protocol.varint(len(packet))+packet)
            except Exception as e:errors.append(e)
            finally:server.close()
        t=threading.Thread(target=fixture);t.start()
        self.assertEqual(protocol.status('127.0.0.1',port)['players']['online'],2)
        t.join(5);self.assertFalse(errors)

    def test_query_metadata_and_names(self):
        server=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);server.bind(('127.0.0.1',0));server.settimeout(5);port=server.getsockname()[1]
        errors=[]
        def fixture():
            try:
                data,addr=server.recvfrom(4096);session=data[3:7]
                server.sendto(b'\x09'+session+b'123\x00',addr)
                data,addr=server.recvfrom(4096)
                self.assertEqual(data[-8:],b'\x00\x00\x00{'+b'\x00'*4)
                server.sendto(b'\x00'+session+b'splitnum\x00\x80\x00hostname\x00Test\x00numplayers\x002\x00map\x00world\x00\x00\x01player_\x00\x00PlayerA\x00PlayerB\x00\x00',addr)
            except Exception as e:errors.append(e)
            finally:server.close()
        t=threading.Thread(target=fixture);t.start()
        result=protocol.full_query('127.0.0.1',port);t.join(5)
        self.assertFalse(errors);self.assertEqual(result['names'],['PlayerA','PlayerB']);self.assertEqual(result['metadata']['map'],'world');self.assertEqual(result['metadata']['numplayers'],'2')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=app.Store(Path(self.tmp.name)/'data.sqlite')
    def tearDown(self):self.tmp.cleanup()
    def record(self,sec,names,complete=True,reachable=True):
        return dict(query_available=complete,query={'names':names,'metadata':{'numplayers':str(len(names))}} if complete else {},timestamp=f'2099-10-08T13:00:{sec:02d}+00:00',reachable=reachable,names=names,names_complete=complete,online=len(names),latency_ms=5)
    def test_join_leave_and_gap(self):
        a=self.record(0,['PlayerA']);b=self.record(10,['PlayerA','PlayerB']);c=self.record(20,['PlayerB'])
        self.store.add(a,None);self.store.add(b,a);self.store.add(c,b)
        gap=self.record(30,[],False,False);self.store.add(gap,c)
        d=self.record(40,['PlayerB']);self.store.add(d,gap)
        data=self.store.dashboard(24)
        kinds=[(e['kind'],e['player']) for e in data['events']]
        self.assertIn(('join_observed','PlayerB'),kinds);self.assertIn(('leave_observed','PlayerA'),kinds)
        self.assertNotIn(('leave_observed','PlayerB'),kinds)
        max_session=next(s for s in data['sessions'] if s['player']=='PlayerA')
        self.assertEqual(max_session['seconds'],20)
        gaps=[s for s in data['sessions'] if s['end_reason']=='unreachable']
        self.assertEqual(gaps[0]['seconds'],10)
    def test_sample_does_not_track_names(self):
        a=self.record(0,['Ad placeholder'],False);self.store.add(a,None)
        self.assertEqual(self.store.dashboard(24)['players'][0]['confirmed_observations'],0)
        self.assertEqual(self.store.dashboard(24)['sessions'],[])
    def test_restart_closes_at_last_seen(self):
        a=self.record(0,['PlayerA']);b=self.record(10,['PlayerA'])
        self.store.add(a,None);self.store.add(b,a)
        restarted=app.Store(self.store.path)
        s=restarted.dashboard(24)['sessions'][0]
        self.assertEqual(s['end_reason'],'monitor_restart');self.assertEqual(s['seconds'],10)
    def test_query_consistency(self):
        collector=app.Collector(dict(app.DEFAULTS,resolve_srv=False),self.store)
        raw=dict(players=dict(online=2,max=20,sample=[]),version=dict(name='1.20.1'),description={'text':'§aHello','extra':[{'text':' world'}]})
        with patch('app.status',return_value=raw),patch('app.ping',return_value=3),patch('app.full_query',return_value={'names':['PlayerA'],'metadata':{'numplayers':'2'}}):
            r=collector.check();self.assertFalse(r['names_complete']);self.assertEqual(r['motd'],'Hello world')
        with patch('app.status',return_value=raw),patch('app.ping',return_value=3),patch('app.full_query',return_value={'names':['PlayerA','PlayerB'],'metadata':{'numplayers':'2'}}):
            r=collector.check();self.assertTrue(r['names_complete'])
    def test_http_and_auth(self):
        self.store.add(dict(self.record(0,[]),error='=evil'),None)
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.make_handler(self.store,app.DEFAULTS))
        t=threading.Thread(target=server.serve_forever);t.start();url=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(url+'/api/dashboard?hours=24') as res:self.assertIn('stats',json.load(res))
            with urlopen(url+'/') as res:self.assertIn(b'Minecraft Pi Monitor',res.read())
            with urlopen(url+'/export/checks.csv') as res:self.assertIn(b'reachable',res.read())
            with self.assertRaises(HTTPError) as e:urlopen(url+'/api/dashboard?hours=999')
            self.assertEqual(e.exception.code,400)
            with patch.dict(os.environ,{'MONITOR_PASSWORD':'secret'}):
                with self.assertRaises(HTTPError) as e:urlopen(url+'/')
                self.assertEqual(e.exception.code,401)
                req=Request(url+'/',headers={'Authorization':'Basic '+base64.b64encode(b'admin:secret').decode()})
                with urlopen(req) as res:self.assertEqual(res.status,200)
        finally:server.shutdown();server.server_close();t.join()


if __name__=='__main__':unittest.main()
