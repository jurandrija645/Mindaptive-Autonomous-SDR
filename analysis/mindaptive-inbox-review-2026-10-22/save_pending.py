"""Save explicitly curated bodies as PENDING drafts. Never sends or changes labels."""
import json
import subprocess
import live

payload_file = live.OUT / 'drafts-curated.json'
payload = json.loads(payload_file.read_text(encoding='utf-8'))
assert isinstance(payload, list)
script = '''import json,logging,hashlib
from app import db,pipeline,drafter,smartlead
from app.config import settings
assert not settings.client_dir if hasattr(settings,'client_dir') else True
for name in ['httpx','httpcore','smartlead','signatures']:
 logging.getLogger(name).setLevel(logging.CRITICAL)
payload=PAYLOAD
results=[]
categories=smartlead.fetch_categories()
blocked={v for k,v in categories.items() if k.lower().replace('-',' ').strip() in ['do not contact','lead opted out','we opted out','meeting booked']}
for item in payload:
 try:
  cid,lid=item['campaign_id'],item['lead_id']
  with db.db_session() as c:
   row=db.get_lead_state(c,lid,cid)
   existing=db.get_open_draft(c,lid,cid)
   existing=dict(existing) if existing else None
  if row is None: raise ValueError('lead_missing')
  if existing and existing['status'] in ['scheduled','sending']: raise ValueError('scheduled_or_sending')
  if existing and existing['id']!=item.get('expected_draft_id'): raise ValueError('draft_changed')
  if existing and item.get('expected_draft_hash') and hashlib.sha256((existing.get('body_html') or '').encode()).hexdigest()!=item['expected_draft_hash']:raise ValueError('draft_body_changed')
  if not existing and item.get('expected_draft_id'): raise ValueError('draft_changed')
  current=smartlead.get_lead_by_email(row['email'])
  campaign=next((x for x in current.get('lead_campaign_data',[]) if x['campaign_id']==cid),None)
  if not campaign: raise ValueError('campaign_not_confirmed')
  if current.get('is_unsubscribed'): raise ValueError('unsubscribed')
  if campaign.get('lead_category_id') in blocked: raise ValueError('booked_or_opted_out')
  thread=pipeline.fetch_normalized_thread(cid,lid)
  if not thread or str(thread[-1].message_id)!=str(item['expected_last_message_id']): raise ValueError('thread_changed')
  trailing=0
  for m in reversed(thread):
   if m.kind!='sent':break
   trailing+=1
  if trailing>=5:raise ValueError('five_consecutive_outbound')
  assert item['body'].strip()
  lead={'id':lid,'campaign_id':cid,'email':row['email'],'first_name':row['name'] or '', 'company_name':row['company'] or ''}
  result=drafter.DraftResult(item['triage'],item['body'],item.get('english') or '',item['body'])
  kind='reply' if thread[-1].kind=='reply' else 'followup'
  with db.db_session() as c:
   # Recheck the draft ID immediately before writing, preserving hand edits/races.
   now=db.get_open_draft(c,lid,cid)
   if (now['id'] if now else None)!=(existing['id'] if existing else None):raise ValueError('draft_changed_before_write')
   did=pipeline.store_draft_result(c,lead,kind,thread,result,model='deepseek/deepseek-v4-flash')
   if existing:db.retire_other_open_drafts(c,lid,cid,keep_draft_id=did)
   stored=db.get_draft(c,did)
   assert stored['status']=='pending' and stored['body_html'].strip()
  results.append({'key':str(cid)+'/'+str(lid),'name':row['name'],'draft_id':did,'status':'pending','replaced_draft_id':existing['id'] if existing else None})
 except Exception as e:
  results.append({'key':str(item['campaign_id'])+'/'+str(item['lead_id']),'error_type':type(e).__name__,'reason':str(e)[:120] if isinstance(e,ValueError) else 'provider_or_storage_error'})
print(json.dumps(results))
'''.replace('PAYLOAD', repr(payload))
command = 'cd /root/mindaptive-responder && docker compose exec -T app python -'
response = subprocess.run(['ssh', '-i', 'C:/Users/AndRo/.ssh/leadaptive_droplet', '-o', 'BatchMode=yes', 'root@167.71.63.154', command], input=script, capture_output=True, text=True, encoding='utf-8', timeout=300)
if response.returncode:
    raise RuntimeError('Remote draft save failed: ' + response.stderr[-300:])
results = json.loads(response.stdout)
log_file = live.OUT / 'drafts-saved.json'
old = json.loads(log_file.read_text()) if log_file.exists() else []
old.extend(results)
log_file.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(results, ensure_ascii=True, indent=2))
