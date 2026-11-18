"""Schedule only the 54 explicitly approved draft IDs, with fresh safeguards."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import collections,json,pathlib,re,subprocess

OUT=pathlib.Path(__file__).resolve().parent
manifest=json.loads((OUT/'approval-manifest.json').read_text(encoding='utf-8'))
rows=manifest['ready_for_review']
assert len(rows)==54
records={r['key']:r for r in json.loads((OUT.parent/'mindaptive-inbox-review-2026-10-22/records.json').read_text(encoding='utf-8'))}
guesses={r['key']:r['timezone'] for r in json.loads((OUT/'schedule-timezones.json').read_text(encoding='utf-8'))['leads']}
groups={'Europe':[],'America_campaign':[]}
for r in rows:
    source=records[r['key']]
    r=dict(r)
    group='America_campaign' if re.search(r'USA|EST&CST',source['campaign_name']) else 'Europe'
    r['schedule_group']=group
    r['campaign_name']=source['campaign_name']
    tz=guesses.get(r['key']) or 'Europe/Zagreb'
    basis='saved app timezone'
    if group=='America_campaign':tz='Europe/Zagreb';basis='user requested US campaigns 16:00–17:30 Zagreb'
    else:
        email=source['email'].lower()
        inbound='\n'.join(m['text'] for m in source['messages'] if m['kind']=='reply')
        if email.endswith('.uk') or re.search(r'\+44\s?\(?0?\)?',inbound) or r['key']=='3950427/4542617778':tz='Europe/London';basis='UK address/domain/telephone in thread'
        else:
            for suffix,z in {'.it':'Europe/Rome','.de':'Europe/Berlin','.lt':'Europe/Vilnius','.pl':'Europe/Warsaw','.hu':'Europe/Budapest','.sk':'Europe/Bratislava','.ro':'Europe/Bucharest','.nl':'Europe/Amsterdam'}.items():
                if email.endswith(suffix):tz=z;basis='country email domain';break
    r['schedule_timezone']=tz;r['timezone_basis']=basis
    groups[group].append(r)
plan=[]
for group,items in groups.items():
    for i,r in enumerate(items):
        start=16 if group=='America_campaign' else 9
        span=90 if group=='America_campaign' else 120
        minute=round(span*i/max(1,len(items)-1))
        local=datetime(2026,10,27,start,tzinfo=ZoneInfo(r['schedule_timezone']))+timedelta(minutes=minute)
        r['scheduled_local']=local.isoformat()
        r['scheduled_at']=local.astimezone(timezone.utc).isoformat()
        plan.append(r)
(OUT/'approved-schedule-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
payload=[{k:r[k] for k in ['key','campaign_id','lead_id','draft_id','body_hash','last_message_id','signature_html','recipients','scheduled_at']} for r in plan]
code='''import json,re,hashlib,logging,os
from datetime import datetime,timezone
from app import db,pipeline,smartlead,main
from app.config import settings
assert not os.getenv('CLIENT_DIR',''), 'Wrong client'
assert not settings.dry_run, 'Dry run enabled; not scheduling real delivery'
logging.disable(logging.CRITICAL)
payload=PAYLOAD
categories=smartlead.fetch_categories()
blocked={v for k,v in categories.items() if re.sub('[^a-z]','',k.lower()) in {'donotcontact','leadoptedout','weoptedout','notinterested','meetingbooked','leaddone'}}
accounts={(a.get('from_email') or '').lower():a for a in smartlead.list_email_accounts()}
results=[]
for p in payload:
 try:
  cid,lid=p['campaign_id'],p['lead_id']
  with db.db_session() as c:
   d=db.get_open_draft(c,lid,cid)
   d=dict(d) if d else None
   lead=db.get_lead_state(c,lid,cid)
   lead=dict(lead) if lead else None
  if not d or d['id']!=p['draft_id']:raise ValueError('draft_replaced_or_closed')
  if d['status']=='scheduled' and d.get('scheduled_at')==p['scheduled_at']:
   results.append({'key':p['key'],'draft_id':d['id'],'status':'already_scheduled','scheduled_at':d['scheduled_at']});continue
  if d['status']!='pending':raise ValueError('draft_not_pending')
  if hashlib.sha256(d['body_html'].encode()).hexdigest()!=p['body_hash']:raise ValueError('draft_body_changed')
  if d.get('signature_html')!=p['signature_html']:raise ValueError('signature_changed')
  if not lead or lead.get('status') in {'stopped','blacklisted','booked'}:raise ValueError('lead_not_active')
  account=accounts.get((d.get('sender_email') or '').lower())
  if not account or account.get('is_smtp_success') is False or not d.get('signature_html'):raise ValueError('sender_unavailable')
  current=smartlead.get_lead_by_email(lead['email'])
  campaign=next((a for a in current.get('lead_campaign_data',[]) if a['campaign_id']==cid),None)
  if not campaign:raise ValueError('campaign_not_confirmed')
  if current.get('is_unsubscribed') or campaign.get('lead_category_id') in blocked:raise ValueError('booked_done_or_opted_out')
  thread=pipeline.fetch_normalized_thread(cid,lid)
  if not thread or str(thread[-1].message_id)!=str(p['last_message_id']):raise ValueError('new_thread_activity')
  count=0
  for m in reversed(thread):
   if m.kind!='sent':break
   count+=1
  if count>=5:raise ValueError('five_outgoing_without_reply')
  raw=[m.__dict__ for m in thread]
  recipients=main._recipients_payload(raw,lead['email'],d)
  if any(recipients[k]!=(p['recipients'].get(k) or '') for k in ['to','cc','from']):raise ValueError('recipients_changed')
  if not main._EMAIL_RE.match(recipients['to']):raise ValueError('invalid_recipient')
  if main._clean_cc(recipients['cc'])!=recipients['cc']:raise ValueError('invalid_cc')
  dt=datetime.fromisoformat(p['scheduled_at'])
  if dt<=datetime.now(timezone.utc):raise ValueError('schedule_not_in_future')
  with db.db_session() as c:
   now=db.get_open_draft(c,lid,cid)
   if not now or now['id']!=d['id'] or now['status']!='pending' or hashlib.sha256(now['body_html'].encode()).hexdigest()!=p['body_hash']:raise ValueError('draft_changed_before_schedule')
   if any(now[k]!=d[k] for k in ['to_override','cc_override','signature_html']):raise ValueError('draft_changed_before_schedule')
   db.update_draft(c,d['id'],status='scheduled',scheduled_at=dt.isoformat(),to_override=recipients['to'],cc_override=recipients['cc'])
  results.append({'key':p['key'],'draft_id':d['id'],'status':'scheduled','scheduled_at':dt.isoformat(),'to':recipients['to'],'cc':recipients['cc']})
 except Exception as e:
  results.append({'key':p['key'],'draft_id':p['draft_id'],'status':'skipped','reason':str(e)[:120] if isinstance(e,ValueError) else type(e).__name__})
print(json.dumps(results))
'''.replace('PAYLOAD',repr(payload))
response=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','-o','ConnectTimeout=10','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app python -'],input=code,capture_output=True,text=True,encoding='utf-8',timeout=360)
assert response.returncode==0,'Scheduling interrupted; inspect database before retrying.'
results=json.loads(response.stdout)
(OUT/'schedule-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'statuses':dict(collections.Counter(r['status'] for r in results)),'skipped':[r for r in results if r['status']=='skipped']}))
