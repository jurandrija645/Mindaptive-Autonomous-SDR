import collections
import concurrent.futures
import csv
import io
import json
import urllib.parse
import urllib.request
import live

records = json.loads((live.OUT / 'records.json').read_text(encoding='utf-8'))
groups = collections.defaultdict(set)
for r in records:
    groups[r['campaign_id']].add(str(r['lead_id']))
path = live.OUT / 'live-categories.json'
results = json.loads(path.read_text()) if path.exists() else {}


def fetch(cid):
    url = f'https://server.smartlead.ai/api/v1/campaigns/{cid}/leads-export?' + urllib.parse.urlencode({'api_key': live.cfg['SMARTLEAD_API_KEY']})
    selected = {}
    with urllib.request.urlopen(url, timeout=120) as response:
        # Labels, IDs and email are ASCII; replace undecodable unrelated content.
        text = io.TextIOWrapper(response, encoding='utf-8-sig', errors='replace', newline='')
        for row in csv.DictReader(text):
            if row.get('id') in groups[cid]:
                selected[row['id']] = {k: row.get(k) for k in ['id', 'email', 'category', 'status', 'is_unsubscribed']}
    return str(cid), selected


with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures = [pool.submit(fetch, cid) for cid in groups if str(cid) not in results]
    for f in concurrent.futures.as_completed(futures):
        cid, rows = f.result()
        results[cid] = rows
        path.write_text(json.dumps(results, indent=2))
        print('Verified categories for', len(results), '/', len(groups), 'campaigns', flush=True)
missing = [r['key'] for r in records if str(r['lead_id']) not in results.get(str(r['campaign_id']), {})]
changed = [r['key'] for r in records if str(r['lead_id']) in results.get(str(r['campaign_id']), {}) and results[str(r['campaign_id'])][str(r['lead_id'])]['category'] != r['smartlead_category']]
print('Live categories complete. Missing:', len(missing), 'different from app:', len(changed), flush=True)
