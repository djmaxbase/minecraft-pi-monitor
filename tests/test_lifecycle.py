import base64
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app,updater
from settings import Preferences,Notifier
from insights import Insights
from chatlogs import ChatLog
from test_extensions import release

class Lifecycle(unittest.TestCase):
    def test_setup_and_different_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=app.Store(root/'monitor.sqlite');token=app.setup_token(root,create=True)
            prefs=Preferences(root);insights=Insights(store);notify=Notifier(prefs,insights,threading.Event())
            services=dict(prefs=prefs,insights=insights,notifier=notify,chat=ChatLog(store,notify,prefs),csrf='fixture',config_path=root/'config.json')
            cfg=dict(app.DEFAULTS);server=app.ThreadingHTTPServer(('127.0.0.1',0),app.make_handler(store,cfg,services));t=threading.Thread(target=server.serve_forever);t.start()
            url=f'http://127.0.0.1:{server.server_port}'
            def call(path,data=None,auth=False):
                headers={'Content-Type':'application/json'}
                if auth:headers.update(Authorization='Basic '+base64.b64encode(b'admin:fixture-long-password').decode(),**{'X-CSRF-Token':'fixture'})
                with urlopen(Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)) as res:return json.load(res)
            try:
                self.assertTrue(call('/api/bootstrap')['setup_required'])
                with self.assertRaises(HTTPError) as e:call('/api/setup',dict(setup_token='wrong'))
                e.exception.close();self.assertEqual(e.exception.code,403)
                call('/api/setup',dict(setup_token=token,username='admin',password='fixture-long-password',host='other.example',port=25565))
                self.assertFalse(call('/api/bootstrap')['setup_required']);self.assertFalse((root/'setup-token.txt').exists())
                self.assertEqual(cfg['host'],'other.example')
                with self.assertRaises(HTTPError) as e:call('/api/setup',dict(setup_token=token))
                e.exception.close();self.assertEqual(e.exception.code,400)
                call('/api/servers',dict(host='different.example',port=25566,query_port=25566),True)
                with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM servers').fetchone()[0],2)
                self.assertEqual(json.loads((root/'config.json').read_text())['host'],'different.example')
            finally:server.shutdown();server.server_close();t.join()

    def test_supervisor_consecutive_updates_and_failed_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            launcher=(Path(app.ROOT)/'launcher.py').read_text().replace('>=15','>=0.1').replace('>60','>2')
            (root/'launcher.py').write_text(launcher)
            good=b"import os,signal,time,json\nfrom pathlib import Path\nPath('data/pid').write_text(str(os.getpid()))\nPath('data/app-ready.json').write_text(json.dumps({'version':Path('VERSION').read_text().strip()}))\nsignal.signal(signal.SIGUSR1,lambda *a:exit(42))\nwhile True:time.sleep(.05)\n"
            (root/'app.py').write_bytes(good);(root/'VERSION').write_text('2.0.0')
            def package(version,code=good):
                src=zipfile.ZipFile(io.BytesIO(release()));files={i.filename:src.read(i) for i in src.infolist()};src.close()
                files['Uitgeteld-Pi/app.py']=code;files['Uitgeteld-Pi/VERSION']=version.encode()
                manifest=json.loads(files['Uitgeteld-Pi/release.json']);manifest['version']=version
                manifest['files']={k:hashlib.sha256(files['Uitgeteld-Pi/'+k]).hexdigest() for k in manifest['files']}
                files['Uitgeteld-Pi/release.json']=json.dumps(manifest).encode();out=io.BytesIO()
                with zipfile.ZipFile(out,'w') as z:
                    for k,v in files.items():z.writestr(k,v)
                return out.getvalue()
            def wait_for(predicate):
                end=time.monotonic()+8
                while time.monotonic()<end:
                    if predicate():return
                    time.sleep(.05)
                self.fail('supervisor timed out')
            with (root/'supervisor.log').open('w') as log:
                process=subprocess.Popen([sys.executable,str(root/'launcher.py')],stdout=log,stderr=log)
                try:
                    wait_for(lambda:(root/'data/pid').exists())
                    for version in ('2.1.0','2.1.1'):
                        updater.install(root,package(version));pid=int((root/'data/pid').read_text());os.kill(pid,signal.SIGUSR1)
                        wait_for(lambda:not (root/'data/update-pending.json').exists())
                        self.assertEqual(json.loads((root/'data/update-result.json').read_text())['state'],'installed')
                    updater.install(root,package('2.1.2',b"raise RuntimeError('fixture startup failure')\n"))
                    os.kill(int((root/'data/pid').read_text()),signal.SIGUSR1)
                    wait_for(lambda:not (root/'data/update-pending.json').exists())
                    self.assertEqual((root/'VERSION').read_text(),'2.1.1')
                    self.assertEqual(json.loads((root/'data/update-result.json').read_text())['state'],'rolled_back')
                finally:process.terminate();process.wait(timeout=10)

    def test_relay_replay_restart_repeated_messages(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('relay',Path(app.ROOT)/'chat-relay.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);log=root/'latest.log';log.write_text('<A> hello\n<A> hello\n');state=root/'relay.sqlite'
            relay=module.Relay(log,state,replay=True);relay.collect();batch=relay.batch();self.assertEqual(len(batch),2);self.assertNotEqual(batch[0]['id'],batch[1]['id']);relay.close()
            relay=module.Relay(log,state);relay.collect();self.assertEqual(relay.batch(),batch);relay.acknowledge(batch);self.assertEqual(relay.batch(),[])
            log.write_text('<B> hi\n');relay.collect();self.assertEqual(relay.batch()[0]['line'],'<B> hi');relay.close()

if __name__=='__main__':unittest.main()
