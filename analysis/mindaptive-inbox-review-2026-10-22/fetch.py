import collections
import json
import re
import sys
import time
from html import unescape
import live

sys.path.insert(0, str(live.ROOT))
from app.email_clean import to_plain_text

roster = json.loads((live.OUT / 'inbox-snapshot.json').read_text(encoding='utf-8'))['leads']
metadata_code = '''import json
from app import db,prospect_contacts,site_visits,site_feedback
result={}
with db.db_session() as c:
 for row in db.list_inbox(c):
  lead=dict(row); key=str(lead['campaign_id'])+'/'+str(lead['lead_id'])
  contact=prospect_contacts.for_lead(c,row)
  visits=site_visits.for_lead(c,row,contact)
  feedback=site_feedback.for_lead(c,row,contact)
  draft=db.get_open_draft(c,lead['lead_id'],lead['campaign_id'])
  result[key]={'lead':{k:lead.get(k) for k in ['website','research_summary','followup_count','timezone_guess','language','status','snooze_until','booked_at']},'contacts':prospect_contacts.payload(contact),'visits':site_visits.payload(visits),'feedback':site_feedback.payload(feedback),'draft':{k:dict(draft).get(k) for k in ['id','status','kind','created_at','body_html','body_translation','triage_summary','model','scheduled_at','thread_snapshot']} if draft else None}
print(json.dumps(result))
'''
metadata = json.loads(live.remote_python(metadata_code))
(live.OUT / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
groups = collections.defaultdict(list)
for lead in roster:
    groups[lead['campaign_id']].append(lead)
path = live.OUT / 'threads.json'
threads = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
for cid, leads in groups.items():
    missing = [x for x in leads if f"{cid}/{x['lead_id']}" not in threads]
    for start in range(0, len(missing), 75):
        chunk = missing[start:start+75]
        data = live.bulk_history(cid, [x['lead_id'] for x in chunk])
        for x in chunk:
            raw = data.get(str(x['lead_id']))
            if raw is None:
                continue
            history = raw.get('history', []) if isinstance(raw, dict) else raw
            clean = []
            for m in history:
                def preserve_url(match):
                    url = unescape(match.group(1))
                    return f' [link: {url}] ' if url.startswith(('https://', 'http://')) else match.group(0)
                body = re.sub(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>', preserve_url, m.get('email_body') or '', flags=re.I)
                kind = (m.get('type') or '').upper()
                clean.append({'kind': 'sent' if kind == 'SENT' else 'reply' if kind == 'REPLY' else kind.lower(), 'time': m.get('time'), 'from': m.get('from'), 'to': m.get('to'), 'cc': m.get('cc'), 'subject': m.get('subject'), 'message_id': m.get('message_id'), 'text': to_plain_text(body)})
            clean.sort(key=lambda m: m.get('time') or '')
            threads[f"{cid}/{x['lead_id']}"] = clean
        path.write_text(json.dumps(threads, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Fetched', len(threads), '/', len(roster), 'threads', flush=True)
        time.sleep(.8)
records = []
for x in roster:
    key = f"{x['campaign_id']}/{x['lead_id']}"
    messages = threads.get(key, [])
    trailing = 0
    for m in reversed(messages):
        if m['kind'] != 'sent':
            break
        trailing += 1
    records.append({**x, 'key': key, 'website_offer': bool(re.search(r'website|redesign', x['campaign_name'], re.I)), 'consecutive_sent': trailing, 'messages': messages, 'metadata': metadata.get(key, {})})
(live.OUT / 'records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
print('Messages', sum(len(x['messages']) for x in records), 'empty', sum(not x['messages'] for x in records), 'website offer', sum(x['website_offer'] for x in records), 'existing drafts', sum(bool(x['metadata'].get('draft')) for x in records), flush=True)
