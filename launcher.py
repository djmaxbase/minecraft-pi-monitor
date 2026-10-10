#!/usr/bin/env python3
"""Stable supervisor: validates startup after a web update and rolls back on failure."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
STOP=False
child=None

def stop(signum,frame):
    global STOP
    STOP=True
    if child and child.poll() is None:child.terminate()


def restore():
    # Self-contained recovery, never import the newly installed updater.
    import shutil
    pending=ROOT/'data/update-pending.json';state=json.loads(pending.read_text());backup=Path(state['backup'])
    for name,existed in state['files'].items():
        target=ROOT/name
        if existed:
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(backup/name,target)
        elif target.exists():target.unlink()
    pending.unlink()
    (ROOT/'data/update-result.json').write_text(json.dumps({'state':'rolled_back','message':'Automatisch teruggezet: nieuwe versie kon niet gezond starten.'}))


def main():
    global child
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    ready=ROOT/'data/app-ready.json';pending=ROOT/'data/update-pending.json'
    (ROOT/'data').mkdir(exist_ok=True)
    while not STOP:
        if pending.exists() and json.loads(pending.read_text()).get('phase')=='installing':
            restore()
        pending_this_launch=pending.exists()
        ready.unlink(missing_ok=True)
        child=subprocess.Popen([sys.executable,str(ROOT/'app.py')],cwd=ROOT,env={**os.environ,'MONITOR_SUPERVISED':'1'})
        began=time.monotonic()
        while child.poll() is None and not STOP:
            if pending_this_launch and pending.exists() and time.monotonic()-began>60 and not ready.exists():
                child.terminate()
                try:child.wait(timeout=15)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                break
            if pending_this_launch and pending.exists() and ready.exists() and time.monotonic()-began>=15:
                state=json.loads(pending.read_text());pending.unlink()
                pending_this_launch=False
                (ROOT/'data/update-result.json').write_text(json.dumps({'state':'installed','version':state['version'],'message':'Nieuwe versie gestart.'}))
            time.sleep(.5)
        if STOP:
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:child.kill();child.wait()
            break
        code=child.wait()
        if pending.exists() and code!=42:
            restore();continue
        if code==42:continue
        return code
    return 0


if __name__=='__main__':sys.exit(main())
