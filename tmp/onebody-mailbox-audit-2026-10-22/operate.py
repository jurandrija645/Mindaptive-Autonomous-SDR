import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent
cfg = {}
for line in (ROOT / '.env.onebodyldn').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        cfg[k] = v.strip().strip('\"\'')


def call(path, body=None, params=None):
    url = 'https://server.smartlead.ai/api/v1' + path + '?' + urllib.parse.urlencode({'api_key': cfg['SMARTLEAD_API_KEY'], **(params or {})})
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(str(exc.code) + ' ' + exc.read().decode()[:300].replace(cfg['SMARTLEAD_API_KEY'], '[REDACTED]')) from None
    except Exception as exc:
        raise RuntimeError(type(exc).__name__) from None


def accounts():
    result = []
    for offset in range(0, 10000, 100):
        data = call('/email-accounts', params={'offset': offset, 'limit': 100})
        batch = data if isinstance(data, list) else data['data']
        result.extend(batch)
        if len(batch) < 100:
            return result
        time.sleep(.3)
    raise RuntimeError('Pagination incomplete')


def safe(account):
    fields = ['id', 'from_email', 'created_at', 'message_per_day', 'warmup_details', 'is_smtp_success', 'is_imap_success', 'smtp_failure_error', 'imap_failure_error', 'type', 'tags']
    return {k: v for k, v in account.items() if k in fields}


if __name__ == '__main__':
    links = json.loads((OUT / 'campaign-links.json').read_text())
    old = set(i for ids in links.values() for i in ids)
    before = accounts()
    (OUT / 'before-settings.json').write_text(json.dumps([safe(a) for a in before], indent=2))
    assert len(old) == 61 and old.issubset({a['id'] for a in before})
    changes = {'messagePerDay': 15, 'maxEmailPerDay': 35, 'warmupMinCount': 25, 'warmupMaxCount': 35}
    probe = next(a for a in before if a['id'] in old and a['warmup_details']['status'] == 'ACTIVE')
    response = call('/email-accounts/bulk-update-email-account-config', {'emailAccountIds': [probe['id']], 'updateData': changes})
    print('Probe response:', json.dumps(response), flush=True)
    checked = call('/email-accounts/' + str(probe['id']))
    assert checked['message_per_day'] == 15
    assert checked['warmup_details']['warmup_min_count'] == 25
    assert checked['warmup_details']['warmup_max_count'] == 35
    print('Probe readback verified', flush=True)
    remaining = sorted(old - {probe['id']})
    response = call('/email-accounts/bulk-update-email-account-config', {'emailAccountIds': remaining, 'updateData': changes})
    print('Remaining response:', json.dumps(response), flush=True)
    after = accounts()
    (OUT / 'after-settings.json').write_text(json.dumps([safe(a) for a in after], indent=2))
    previous = {a['id']: a for a in before}
    for a in after:
        if a['id'] in old:
            assert (a['message_per_day'], a['warmup_details']['warmup_min_count'], a['warmup_details']['warmup_max_count']) == (15, 25, 35), a['id']
        else:
            for k in ['message_per_day']:
                assert a[k] == previous[a['id']][k], a['id']
            for k in ['warmup_min_count', 'warmup_max_count', 'max_email_per_day', 'reply_rate', 'status']:
                assert a['warmup_details'].get(k) == previous[a['id']]['warmup_details'].get(k), (a['id'], k)
    print('Verified all 61 old settings. All 270 new settings preserved.', flush=True)
