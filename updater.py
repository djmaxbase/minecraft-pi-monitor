"""Authenticated release ZIP installation, checksum validation and rollback."""
import hashlib
import io
import json
import os
import shutil
import threading
import zipfile
import stat
import sys
import sqlite3
import time
import fcntl
from pathlib import Path, PurePosixPath

ALLOWED={'app.py','protocol.py','telemetry.py','insights.py','settings.py','updater.py','chatlogs.py',
         'observe.py','schema.py','github_update.py','release_channel.json','update_pubkey.pem',
         'radar_feed.py','web/radar.html','web/radar.js','web/radar.css','web/setup.js','web/index.html','web/style.css','web/app.js','web/extended.js','web/extended.css','VERSION'}
REQUIRED={'app.py','protocol.py','telemetry.py','insights.py','settings.py','updater.py','chatlogs.py',
          'observe.py','schema.py','github_update.py','web/setup.js','web/index.html','web/style.css','web/app.js','web/extended.js','web/extended.css','VERSION'}
LOCK=threading.Lock()


def inspect_release(blob):
    if len(blob)>15*1024*1024:raise ValueError('Update is groter dan 15 MB')
    payload={};seen=set()
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        if len(archive.infolist())>100:raise ValueError('Te veel bestanden')
        if sum(i.file_size for i in archive.infolist())>12*1024*1024:raise ValueError('Uitgepakte update te groot')
        for info in archive.infolist():
            mode=info.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):raise ValueError('Speciaal bestand of symlink in ZIP')
            parts=PurePosixPath(info.filename).parts
            if not parts or '..' in parts or PurePosixPath(info.filename).is_absolute() or '\\' in info.filename:raise ValueError('Ongeldig pad in ZIP')
            path='/'.join(parts[1:]) if parts[0]=='Uitgeteld-Pi' else '/'.join(parts)
            if not path or info.is_dir():continue
            if path in seen:raise ValueError('Dubbel bestand in ZIP')
            seen.add(path)
            if info.file_size>3*1024*1024:raise ValueError('Bestand te groot')
            if path in ALLOWED or path=='release.json':payload[path]=archive.read(info)
        if sum(map(len,payload.values()))>10*1024*1024:raise ValueError('Uitgepakte update te groot')
    if not REQUIRED<=payload.keys() or 'release.json' not in payload:raise ValueError('Geen volledig Uitgeteld-updatepakket')
    manifest=json.loads(payload.pop('release.json'))
    if manifest.get('format')!=1:raise ValueError('Onbekend releaseformaat')
    if manifest.get('files')!={name:hashlib.sha256(data).hexdigest() for name,data in payload.items()}:raise ValueError('Bestandscontrole mislukt')
    if manifest.get('schema_max',4)<4 or manifest.get('schema_min',0)>4:raise ValueError('Incompatibel databaseschema')
    if tuple(manifest.get('python_min',[3,9]))>sys.version_info[:2]:raise ValueError('Python-versie te oud')
    if manifest.get('migration_policy','additive')!='additive':raise ValueError('Migratie vereist handmatige installatie')
    version=payload['VERSION'].decode().strip()
    if manifest.get('version')!=version:raise ValueError('Versie komt niet overeen')
    for name,data in payload.items():
        if name.endswith('.py'):compile(data,name,'exec')
    return version,payload


def rollback(root):
    root=Path(root);pending=root/'data/update-pending.json'
    state=json.loads(pending.read_text());backup=Path(state['backup'])
    for name,existed in state['files'].items():
        target=root/name
        if existed:
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(backup/name,target)
        elif target.exists():target.unlink()
    atomic_json(root/'data/update-result.json',{'state':'rolled_back','message':'Vorige code hersteld; nieuwe versie startte niet correct.'})
    pending.unlink()


def install(root,blob):
    root=Path(root)
    if not LOCK.acquire(blocking=False):raise ValueError('Er loopt al een update')
    lock_file=None
    try:
        (root/'data').mkdir(parents=True,exist_ok=True)
        lock_file=(root/'data/update.lock').open('a')
        try:fcntl.flock(lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Er loopt al een update')
        pending_path=root/'data/update-pending.json'
        if pending_path.exists():raise ValueError('Vorige update wacht nog op supervisorbevestiging of herstel')
        version,payload=inspect_release(blob)
        staging=root/'data/update-staging';backup=root/'data/update-rollback'
        for folder in (staging,backup):
            if folder.exists():shutil.rmtree(folder)
            folder.mkdir(parents=True)
        existed={}
        for name,data in payload.items():
            target=root/name;existed[name]=target.is_file()
            if target.is_symlink() or any(x.is_symlink() for x in target.parents if x!=root.parent):raise ValueError('Symlinks worden niet bijgewerkt')
            if existed[name]:
                dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,dest)
            dest=staging/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        pending=root/'data/update-pending.json'
        db_path=root/'data/monitor.sqlite'
        config=root/'config.json'
        if config.exists():
            configured=Path(json.loads(config.read_text()).get('database','data/monitor.sqlite'))
            db_path=configured if configured.is_absolute() else root/configured
        if db_path.exists():
            source=sqlite3.connect(db_path);dest=sqlite3.connect(backup/'database.sqlite')
            try:source.backup(dest)
            finally:source.close();dest.close()
        state=dict(version=version,backup=str(backup),files=existed,phase='installing',started=time.time())
        atomic_json(pending,state)
        try:
            for name in payload:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);os.replace(staging/name,target)
            state['phase']='awaiting_restart'
            atomic_json(pending,state)
        except Exception:
            rollback(root);raise
        return version
    finally:
        if lock_file:lock_file.close()
        LOCK.release()


def atomic_json(path,value):
    temp=path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)
    fd=os.open(path.parent,os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
