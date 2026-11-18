"""Store reviewed replacements pending only; abort on changed draft/thread."""
import json
import pathlib
import subprocess

OUT=pathlib.Path(__file__).resolve().parent
payload=json.loads((OUT/'approved-payload.json').read_text(encoding='utf-8'))
script='''import json,logging,hashlib,re
from app import db,pipeline,drafter,smartlead
from app.config import settings
assert not settings.client_dir if hasattr(settings,'client_dir') else True
logging.disable(logging.CRITICAL)
payload=PAYLOAD
categories=smartlead.fetch_categories()
blocked={v for k,v in categories.items() if re.sub('[^a-z]','',k.lower()) in {'donotcontact','leadoptedout','weoptedout','meetingbooked','notinterested','leaddone'}}
results=[]
for p in payload:
 try:
  cid,lid=p['campaign_id'],p['lead_id']
  with db.db_session() as c:
   leadrow=db.get_lead_state(c,lid,cid)
   old=db.get_open_draft(c,lid,cid)
   old=dict(old) if old else None
  if not leadrow:raise ValueError('lead_missing')
  if not old or old['id']!=p['expected_draft_id'] or old['status']!='pending':raise ValueError('draft_changed_or_not_pending')
  if hashlib.sha256(old['body_html'].encode()).hexdigest()!=p['expected_draft_hash']:raise ValueError('draft_edited')
  current=smartlead.get_lead_by_email(leadrow['email'])
  campaign=next((x for x in current.get('lead_campaign_data',[]) if x['campaign_id']==cid),None)
  if not campaign:raise ValueError('campaign_not_confirmed')
  if current.get('is_unsubscribed') or campaign.get('lead_category_id') in blocked:raise ValueError('no_contact_or_booked')
  thread=pipeline.fetch_normalized_thread(cid,lid)
  if not thread or str(thread[-1].message_id)!=str(p['expected_last_message_id']):raise ValueError('thread_changed')
  trailing=0
  for m in reversed(thread):
   if m.kind!='sent':break
   trailing+=1
  if trailing>=5:raise ValueError('five_outgoing_without_reply')
  lead={'id':lid,'campaign_id':cid,'email':leadrow['email'],'first_name':leadrow['name'] or '', 'company_name':leadrow['company'] or ''}
  result=drafter.DraftResult(p['triage'],p['body'],p.get('english') or '',p['body'])
  with db.db_session() as c:
   now=db.get_open_draft(c,lid,cid)
   if not now or now['id']!=old['id'] or now['status']!='pending' or hashlib.sha256(now['body_html'].encode()).hexdigest()!=p['expected_draft_hash']:raise ValueError('draft_changed_before_write')
   did=pipeline.store_draft_result(c,lead,old['kind'],thread,result,model='deepseek/deepseek-v4-flash')
   db.retire_other_open_drafts(c,lid,cid,keep_draft_id=did)
   stored=dict(db.get_draft(c,did))
   assert stored['status']=='pending' and stored['body_html'].strip()
  results.append({'key':p['key'],'replaced_draft_id':old['id'],'draft_id':did,'status':'pending', 'body_html':stored['body_html'],'body_translation':stored['body_translation'],'signature_present':bool(stored.get('signature_html'))})
 except Exception as e:
  results.append({'key':p['key'],'error_type':type(e).__name__,'reason':str(e)[:100] if isinstance(e,ValueError) else 'provider_or_storage_error'})
print(json.dumps(results))
'''.replace('PAYLOAD',repr(payload))
response=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','-o','ConnectTimeout=10','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app python -'],input=script,capture_output=True,text=True,encoding='utf-8',timeout=300)
assert response.returncode==0, 'Remote revision save failed; inspect before retrying.'
results=json.loads(response.stdout)
(OUT/'save-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{k:v for k,v in r.items() if k not in ['body_html','body_translation']} for r in results]))
