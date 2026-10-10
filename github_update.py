"""GitHub Releases client. Signature (not a checksum next to the ZIP) is the trust check."""
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
CHANNEL_PATH = ROOT / 'release_channel.json'
PUBKEY_PATH = ROOT / 'update_pubkey.pem'
ALLOWED_HOSTS = {
    'github.com', 'api.github.com', 'objects.githubusercontent.com',
    'release-assets.githubusercontent.com', 'github-releases.githubusercontent.com',
}


def load_channel():
    if CHANNEL_PATH.exists():
        return json.loads(CHANNEL_PATH.read_text())
    return dict(owner='', repo='', api='https://api.github.com')


def parse_semver(text):
    text=str(text).removeprefix('v')
    match=re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?',text)
    if not match:return None
    pre=match[4]
    parts=[]
    if pre:
        for part in pre.split('.'):
            if part.isdigit() and len(part)>1 and part[0]=='0':return None
            parts.append((0,int(part)) if part.isdigit() else (1,part))
    return tuple(map(int,match.group(1,2,3))), (1,) if not pre else (0,tuple(parts))


def newer(candidate,current):
    a,b=parse_semver(candidate),parse_semver(current)
    return bool(a and b and a>b)


def validate_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Onveilige download-URL')


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def _request(url, timeout=20, headers=None, dest=None):
    validate_url(url)
    host = urlparse(url).hostname or ''
    if host not in ALLOWED_HOSTS:
        raise ValueError('Downloadhost niet toegestaan: '+host)
    req = Request(url, headers={'User-Agent': 'minecraft-pi-monitor', 'Accept': 'application/vnd.github+json', **(headers or {})})
    with build_opener(SafeRedirect()).open(req, timeout=timeout) as res:
        final = urlparse(res.geturl()).hostname or ''
        if final not in ALLOWED_HOSTS:
            raise ValueError('Redirect naar niet-toegestane host')
        if dest:
            sha = hashlib.sha256();total=0
            with open(dest, 'wb') as out:
                while True:
                    chunk = res.read(65536)
                    if not chunk:
                        break
                    total+=len(chunk)
                    if total>15*1024*1024:raise ValueError('Download te groot')
                    sha.update(chunk)
                    out.write(chunk)
            return sha.hexdigest(), res.geturl()
        body=res.read(2*1024*1024+1)
        if len(body)>2*1024*1024:raise ValueError('GitHub-antwoord te groot')
        return json.loads(body.decode())


def cached_releases(data_dir, force=False, include_prerelease=False):
    channel = load_channel()
    cache = Path(data_dir) / 'github-releases-cache.json'
    now = time.time()
    if cache.exists():
        try:
            payload = json.loads(cache.read_text())
            if payload.get('channel')==channel and payload.get('include_prerelease')==include_prerelease and (payload.get('next_check',0)>now or (not force and now-payload.get('fetched',0)<43200)):
                return payload
        except (OSError, ValueError):
            pass
    owner, repo = channel.get('owner'), channel.get('repo')
    if not owner or not repo:
        return dict(error='Geen GitHub-repository geconfigureerd', releases=[], fetched=now, channel=channel)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',owner) or not re.fullmatch(r'[A-Za-z0-9_.-]+',repo):raise ValueError('Ongeldige repository')
    url=f'https://api.github.com/repos/{owner}/{repo}/releases?per_page=30'
    try:
        items = _request(url)
    except HTTPError as exc:
        retry = exc.headers.get('Retry-After') if exc.headers else None
        rate_limited=exc.code in (403,429)
        try:next_check=max(now+int(retry or 60),float(exc.headers.get('X-RateLimit-Reset',0)))
        except (ValueError,TypeError):next_check=now+60
        payload=dict(error=f'GitHub HTTP {exc.code}',rate_limited=rate_limited,retry_after=retry,next_check=next_check if rate_limited else now+60,releases=[],fetched=now,channel=channel,include_prerelease=include_prerelease)
        cache.write_text(json.dumps(payload));exc.close()
        return payload
    except (URLError, TimeoutError, ValueError) as exc:
        if cache.exists():
            try:payload=json.loads(cache.read_text())
            except (OSError,ValueError):payload={'releases':[]}
            if payload.get('channel')!=channel or payload.get('include_prerelease')!=include_prerelease:payload={'releases':[]}
            payload['error'] = 'Offline of GitHub onbereikbaar; cache gebruikt'
            return payload
        return dict(error=str(exc), releases=[], fetched=now, channel=channel)
    releases = []
    for item in items:
        if item.get('draft'):
            continue
        if item.get('prerelease') and not include_prerelease:
            continue
        assets = [{'name': a['name'], 'size': a['size'], 'url': a['browser_download_url']} for a in item.get('assets') or []]
        releases.append(dict(
            tag=item.get('tag_name'), name=item.get('name'), notes=item.get('body') or '',
            published=item.get('published_at'), prerelease=bool(item.get('prerelease')),
            html_url=item.get('html_url'), assets=assets,
        ))
    releases=[r for r in releases if parse_semver(r['tag'])]
    releases.sort(key=lambda r:parse_semver(r['tag']),reverse=True)
    payload = dict(include_prerelease=include_prerelease,releases=releases, fetched=now, channel=channel, error=None)
    cache.write_text(json.dumps(payload))
    return payload


def pick_assets(release):
    zip_asset = sig_asset = None
    for asset in release.get('assets') or []:
        name = asset['name']
        if name.endswith('.zip') and 'minecraft-pi-monitor' in name:
            zip_asset = asset
        if name.endswith('.zip.sig') or name.endswith('.sig'):
            sig_asset = asset
    return zip_asset, sig_asset


def verify_signature(zip_path, sig_path, pubkey=PUBKEY_PATH):
    if not Path(pubkey).exists():
        raise ValueError('Geen update_pubkey.pem aanwezig; GitHub-update geweigerd')
    result = subprocess.run(
        ['openssl', 'dgst', '-sha256', '-verify', str(pubkey), '-signature', str(sig_path), str(zip_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ValueError('Ondertekening ongeldig of bestand aangepast')
    return True


def download_release(release, dest_dir):
    zip_asset, sig_asset = pick_assets(release)
    if not zip_asset:
        raise ValueError('Release bevat geen minecraft-pi-monitor ZIP')
    if not sig_asset:
        raise ValueError('Release mist een handtekening; weigeren (checksum alleen is geen authenticiteit)')
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    channel=load_channel()
    for asset in (zip_asset,sig_asset):
        if Path(asset['name']).name!=asset['name']:raise ValueError('Ongeldige assetnaam')
        validate_url(asset['url'])
        if not asset['url'].startswith(f"https://github.com/{channel['owner']}/{channel['repo']}/releases/download/"):raise ValueError('Asset uit verkeerde repository')
    zip_path = dest_dir / zip_asset['name']
    sig_path = dest_dir / sig_asset['name']
    _request(zip_asset['url'], timeout=120, dest=zip_path)
    _request(sig_asset['url'], timeout=30, dest=sig_path)
    verify_signature(zip_path, sig_path)
    return zip_path.read_bytes()
