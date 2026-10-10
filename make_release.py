#!/usr/bin/env python3
"""Build only allowlisted program files; never collect runtime data recursively."""
import hashlib
import json
from pathlib import Path
import zipfile
import updater
ROOT=Path(__file__).resolve().parent

def build(destination=None):
    destination=Path(destination or ROOT.parent/f'minecraft-pi-monitor-{(ROOT/"VERSION").read_text().strip()}.zip')
    names=updater.REQUIRED | {'release_channel.json','update_pubkey.pem'}
    payload={name:(ROOT/name).read_bytes() for name in names}
    manifest=dict(format=1,version=payload['VERSION'].decode().strip(),python_min=[3,9],schema_min=4,schema_max=4,migration_policy='additive',files={name:hashlib.sha256(data).hexdigest() for name,data in payload.items()})
    extras=['launcher.py','install.sh','config.example.json','README.md','RECOVERY.md','LICENSE','CHANGELOG.md','chat-relay.py']
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(payload.items()):z.writestr('Uitgeteld-Pi/'+name,data)
        z.writestr('Uitgeteld-Pi/release.json',json.dumps(manifest,indent=2))
        for name in extras:z.write(ROOT/name,'Uitgeteld-Pi/'+name)
    updater.inspect_release(destination.read_bytes())
    destination.with_suffix('.zip.sha256').write_text(hashlib.sha256(destination.read_bytes()).hexdigest()+'  '+destination.name+'\n')
    print('Release ready:',destination)
    return destination

if __name__=='__main__':build()
