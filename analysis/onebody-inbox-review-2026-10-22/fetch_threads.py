import collections
import json
import pathlib
import sys
import time
import re
from html import unescape

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tmp/onebody-mailbox-audit-2026-10-22'))
import operate as api
from app.email_clean import to_plain_text

OUT = pathlib.Path(__file__).resolve().parent
roster = json.loads((OUT / 'inbox-snapshot.json').read_text())['leads']
groups = collections.defaultdict(list)
for lead in roster:
    groups[lead['campaign_id']].append(lead)
threads = {}
cache = OUT / 'threads-with-links.json'
if cache.exists():
    threads = json.loads(cache.read_text())
for cid, leads in groups.items():
    missing = [x for x in leads if f"{cid}/{x['lead_id']}" not in threads]
    for start in range(0, len(missing), 75):
        chunk = missing[start:start+75]
        result = api.call(f'/campaigns/{cid}/message-history-for-leads/bbfbdsFGHlBr76ruhjvh6fhHL', {'lead_ids': [str(x['lead_id']) for x in chunk]})
        for lead in chunk:
            entry = result.get(str(lead['lead_id']))
            if entry is None:
                continue
            history = entry.get('history', []) if isinstance(entry, dict) else entry
            clean = []
            for msg in history:
                raw_type = (msg.get('type') or '').upper()
                body = msg.get('email_body') or ''
                def preserve_booking_link(match):
                    url = unescape(match.group(1))
                    return f' [booking link: {url}] ' if 'onebodyldn.connect.tm3app.com/' in url else match.group(0)
                body = re.sub(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>', preserve_booking_link, body, flags=re.I)
                clean.append({'kind': 'sent' if raw_type == 'SENT' else 'reply' if raw_type == 'REPLY' else raw_type.lower(), 'time': msg.get('time'), 'from': msg.get('from'), 'subject': msg.get('subject'), 'text': to_plain_text(body), 'message_id': msg.get('message_id')})
            clean.sort(key=lambda x: x.get('time') or '')
            threads[f"{cid}/{lead['lead_id']}"] = clean
        cache.write_text(json.dumps(threads, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Fetched {len(threads)}/{len(roster)} threads', flush=True)
        time.sleep(.6)
records = [{**lead, 'key': f"{lead['campaign_id']}/{lead['lead_id']}", 'messages': threads.get(f"{lead['campaign_id']}/{lead['lead_id']}", [])} for lead in roster]
(OUT / 'records-with-links.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
print('Message count:', sum(len(x['messages']) for x in records), 'Missing/empty threads:', sum(not x['messages'] for x in records), flush=True)
