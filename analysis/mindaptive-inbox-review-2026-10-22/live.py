import http.cookiejar
import json
import pathlib
import shlex
import subprocess
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent


def remote_python(code):
    command = 'cd /root/mindaptive-responder && docker compose exec -T app python -c ' + shlex.quote(code)
    response = subprocess.run(['ssh', '-i', 'C:/Users/AndRo/.ssh/leadaptive_droplet', '-o', 'BatchMode=yes', 'root@167.71.63.154', command], capture_output=True, text=True, timeout=90)
    if response.returncode:
        raise RuntimeError('Mindaptive remote command failed: ' + response.stderr[-500:])
    return response.stdout


cfg = json.loads(remote_python("import os,json; print(json.dumps({k:os.getenv(k,'') for k in ['SMARTLEAD_API_KEY','OPENROUTER_API_KEY','APP_PASSWORD','PUBLIC_BASE_URL','CLIENT_DIR']}))"))
assert not cfg['CLIENT_DIR'], 'Wrong client container'
assert cfg['SMARTLEAD_API_KEY'] and cfg['OPENROUTER_API_KEY']
BASE = cfg['PUBLIC_BASE_URL'].rstrip('/')
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
opener.open(BASE + '/login', urllib.parse.urlencode({'password': cfg['APP_PASSWORD']}).encode(), timeout=30)


def app_get(path):
    with opener.open(BASE + path, timeout=60) as response:
        return json.load(response)


def smartlead_get(path, params=None):
    url = 'https://server.smartlead.ai/api/v1' + path + '?' + urllib.parse.urlencode({'api_key': cfg['SMARTLEAD_API_KEY'], **(params or {})})
    try:
        with urllib.request.urlopen(url, timeout=90) as response:
            return response.read(), response.headers.get('Content-Type')
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Smartlead {exc.code}: ' + exc.read().decode()[:200].replace(cfg['SMARTLEAD_API_KEY'], '[REDACTED]')) from None


def bulk_history(cid, ids):
    assert 0 < len(ids) <= 100
    url = f'https://server.smartlead.ai/api/v1/campaigns/{cid}/message-history-for-leads/bbfbdsFGHlBr76ruhjvh6fhHL?' + urllib.parse.urlencode({'api_key': cfg['SMARTLEAD_API_KEY']})
    request = urllib.request.Request(url, data=json.dumps({'lead_ids': [str(x) for x in ids]}).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Smartlead {exc.code}: ' + exc.read().decode()[:200].replace(cfg['SMARTLEAD_API_KEY'], '[REDACTED]')) from None


if __name__ == '__main__':
    inbox = app_get('/api/inbox')
    (OUT / 'inbox-snapshot.json').write_text(json.dumps(inbox, ensure_ascii=False, indent=2), encoding='utf-8')
    categories = json.loads(smartlead_get('/leads/fetch-categories')[0])
    (OUT / 'categories.json').write_text(json.dumps(categories, indent=2))
    print('Mindaptive inbox:', len(inbox['leads']), 'leads; app:', BASE)
    from collections import Counter
    print('Campaigns:', json.dumps(dict(Counter(x['campaign_name'] for x in inbox['leads']))))
    print('Labels:', dict(Counter(x['smartlead_category'] for x in inbox['leads'])))
