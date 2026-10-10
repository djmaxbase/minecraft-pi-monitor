#!/usr/bin/env python3
"""Relay authorized Minecraft logs with a durable outbox and checkpoints."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from urllib.request import Request,build_opener
from chatlogs import parse_chat
from settings import NoRedirect

class Relay:
    def __init__(self,path,state,replay=False):
        self.path=Path(path);self.state=Path(state);self.replay=replay;self.handle=None
        self.state.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.state);os.chmod(self.state,0o600)
        self.db.executescript('CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY,identity TEXT,generation TEXT,offset INTEGER); CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY,line TEXT);')
    def collect(self):
        stat=self.path.stat();identity=f'{stat.st_dev}:{stat.st_ino}'
        row=self.db.execute('SELECT identity,generation,offset FROM checkpoint WHERE id=1').fetchone()
        if row is None or row[0]!=identity or stat.st_size<row[2]:
            offset=stat.st_size if row is None and not self.replay else 0
            row=(identity,uuid.uuid4().hex,offset)
            with self.db:self.db.execute('INSERT OR REPLACE INTO checkpoint VALUES(1,?,?,?)',row)
        room=2000-self.db.execute('SELECT COUNT(*) FROM pending').fetchone()[0]
        if room<=0:return
        with self.path.open('rb') as stream:
            stream.seek(row[2]);count=0
            with self.db:
                while count<min(room,200):
                    start=stream.tell();raw=stream.readline(8194)
                    if not raw or not raw.endswith(b'\n'):break
                    line=raw.decode('utf-8',errors='replace').rstrip()
                    if parse_chat(line):
                        self.db.execute('INSERT OR IGNORE INTO pending VALUES(?,?)',(f'{row[1]}:{start}',line));count+=1
                    self.db.execute('UPDATE checkpoint SET offset=? WHERE id=1',(stream.tell(),))
    def batch(self):
        return [dict(id=r[0],line=r[1],tz_confidence='unknown') for r in self.db.execute('SELECT id,line FROM pending ORDER BY rowid LIMIT 100')]
    def acknowledge(self,batch):
        with self.db:self.db.executemany('DELETE FROM pending WHERE id=?',[(r['id'],) for r in batch])
    def close(self):self.db.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file',type=Path,required=True);parser.add_argument('--url',required=True)
    parser.add_argument('--source',default='Minecraft log');parser.add_argument('--state',type=Path,default=Path('relay-state.sqlite'))
    parser.add_argument('--replay',action='store_true',help='Read existing records on first use of this state file')
    args=parser.parse_args();token=os.environ.get('MONITOR_CHAT_TOKEN')
    if not token:parser.error('Set MONITOR_CHAT_TOKEN to the ingestion key from Settings')
    relay=Relay(args.file,args.state,args.replay)
    try:
        while True:
            try:relay.collect()
            except OSError:print('Waiting for readable log file',flush=True)
            batch=relay.batch()
            if batch:
                req=Request(args.url.rstrip('/')+'/api/chat/ingest',data=json.dumps(dict(source=args.source,lines=batch)).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                try:
                    with build_opener(NoRedirect()).open(req,timeout=10) as response:
                        result=json.loads(response.read(65536))
                        if not result.get('ok'):raise ValueError('Ingestion not acknowledged')
                    relay.acknowledge(batch)
                except Exception:
                    print('Upload unavailable; records retained on disk',flush=True);time.sleep(13)
            time.sleep(2)
    except KeyboardInterrupt:pass
    finally:relay.close()

if __name__=='__main__':main()
