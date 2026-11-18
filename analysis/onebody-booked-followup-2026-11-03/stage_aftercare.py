"""Schedule only the 28 reviewed A/B messages under Mia's expiring approval."""
import pathlib,json,subprocess
P=pathlib.Path(__file__).resolve().parent
review=json.loads((P/'booked-review.json').read_text(encoding='utf-8'))
snapshot=json.loads((P/'booked-snapshot.json').read_text(encoding='utf-8'))
rows=[r for r in review['records'] if r['group'] in ('A','B')]
payload={'rows':rows,'expected':{r['key']:[m['message_id'] for m in snapshot['threads'][r['key']]] for r in rows},'sha':'33a60240198c0dbeee04328b91a4150d70bc20e4fde1f406724e16eddc2dc7b9'}
remote=r'''
import json,logging,collections,hashlib,httpx
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from email.utils import getaddresses
from app import db,aftercare,smartlead,detector,signatures,library,client_assets,scheduler
from app.config import settings
from app.thread_utils import text_to_html
logging.disable(logging.CRITICAL)
assert client_assets.CLIENT_DIR.name=='onebodyldn' and not settings.dry_run
assert len(PAYLOAD['rows'])==28
entry=next(e for e in library.listing() if e['slug']=='one-body-ldn-partnership-brochure.pdf')
resolved=library.resolve(entry['slug']);assert resolved and hashlib.sha256(resolved[0].read_bytes()).hexdigest()==PAYLOAD['sha']
attachment={k:entry[v] for k,v in [('slug','slug'),('file_name','file_name'),('file_url','url'),('file_type','file_type'),('file_size','file_size')]}
with httpx.Client(timeout=45,follow_redirects=True) as client:
 response=client.head(entry['url']);assert response.status_code==200 and 'pdf' in response.headers.get('content-type','')
accounts={a['from_email'].lower():a for a in smartlead.list_email_accounts() if a.get('from_email')}
groups=collections.defaultdict(list)
for r in PAYLOAD['rows']:
 cid,lid=map(int,r['key'].split('/'));groups[cid].append(lid)
threads={}
for cid,ids in groups.items():
 result=smartlead.get_message_history_bulk(cid,ids)
 for lid in ids:threads[f'{cid}/{lid}']=detector.normalize_thread((result.get(str(lid)) or {}).get('history') or [])
categories={str(v):''.join(c for c in k.lower() if c.isalnum()) for k,v in smartlead.fetch_categories().items()}
plans=[]
for index,r in enumerate(PAYLOAD['rows']):
 cid,lid=map(int,r['key'].split('/'));thread=threads[r['key']]
 assert [m.message_id for m in thread]==PAYLOAD['expected'][r['key']],(r['name'],'new conversation activity')
 sender=detector.last_sender_email(thread);assert sender.lower()==r['sender'].lower()
 account=accounts[sender.lower()];assert account.get('is_smtp_success',True) and account.get('is_imap_success',True)
 assert account['from_name'].split()[0]==r['persona']
 sig=signatures.get_signature_html(sender);assert sig and '<table' in sig.lower() and r['persona'] in sig
 # Booked status is verified live, without unpausing or changing any mapping.
 overview=smartlead.get_lead_campaign_overview(lid);maps=overview['email_campaign_leads_mappings']
 cs=[categories.get(str(m.get('lead_category_id')),'') for m in maps]
 assert 'meetingbooked' in cs and not any(x in {'leadoptedout','donotcontact','unsubscribed','blacklisted','notinterested','bounced'} for x in cs),(r['name'],'live contact suppression')
 with db.db_session() as c:
  state=dict(db.get_lead_state(c,lid,cid));assert state['status']=='booked'
  previous=[dict(x) for x in c.execute("SELECT * FROM drafts WHERE lead_id=? AND campaign_id=? AND status IN ('pending','scheduled','sending')",(lid,cid))]
 assert not previous or all(x['kind']=='aftercare' and x.get('model')=='mia-approved-booked-feedback-20261104' for x in previous),(r['name'],'another draft exists')
 # Keep relevant recipients from the latest thread; omit our own/clinic mailboxes.
 last=thread[-1];cc_raw=last.cc or ''
 if last.kind=='reply':cc_raw+=','+(last.to_email or '')
 cc=[]
 for _,email in getaddresses([cc_raw]):
  email=email.strip();lower=email.lower()
  if lower and lower not in accounts and not lower.endswith('@onebodyldn.com') and lower!=r['to'].lower() and lower not in [x.lower() for x in cc]:cc.append(email)
 if r['number']==14:cc=[e for e in cc if not e.lower().endswith('@emergecapital.vc')]
 at=datetime(2026,11,4,9,0,tzinfo=ZoneInfo('Europe/London'))+timedelta(minutes=4*index)
 body=text_to_html(r['body']);assert r['persona'] in body and '{{' not in body
 plans.append(dict(record=r,cid=cid,lid=lid,sender=sender,to=r['to'],cc=','.join(cc),body_html=body,signature_html=sig,
   at=at.astimezone(timezone.utc).isoformat(),uk=at.isoformat(),zagreb=at.astimezone(ZoneInfo('Europe/Zagreb')).isoformat(),previous_state=state,previous_drafts=previous))
# Atomic insertion + approval: the booking sweep never sees an unapproved row.
with db.db_session() as c:
 for p in plans:
  r=p['record'];cid,lid=p['cid'],p['lid'];thread=threads[r['key']];last=thread[-1]
  state=db.get_lead_state(c,lid,cid);assert state['status']=='booked'
  existing=c.execute("SELECT * FROM drafts WHERE lead_id=? AND campaign_id=? AND kind='aftercare' AND model=? AND status IN ('scheduled','sending','sent')",(lid,cid,'mia-approved-booked-feedback-20261104')).fetchall()
  if existing:
   assert len(existing)==1;draft=dict(existing[0]);assert draft['body_html']==p['body_html'] and draft['scheduled_at']==p['at'];did=draft['id']
  else:
   did=db.create_draft(c,lead_id=lid,campaign_id=cid,kind='aftercare',status='scheduled',scheduled_at=p['at'],
    triage_summary='Mia explicitly approved this customer feedback message and PDF for 4 Nov 2026, 09–11 UK. Booked status and outreach stop remain.',
    body_html=p['body_html'],body_translation='',signature_html=p['signature_html'],sender_email=p['sender'],to_override=p['to'],cc_override=p['cc'],
    attachments=json.dumps([attachment]),thread_snapshot=json.dumps([m.__dict__ for m in thread],default=str),
    reply_message_id=last.message_id,reply_email_time=last.timestamp.isoformat(),reply_stats_id=last.stats_id,
    lead_name=r['name'],lead_company=r['company'],lead_email=state['email'],model='mia-approved-booked-feedback-20261104')
   aftercare.authorize(c,did,starts_at='2026-11-04T09:00:00+00:00',expires_at='2026-11-04T11:00:00+00:00',
    approved_by='Mia: 3 Nov explicit instruction to allow these 28 booked-customer feedback/PDF messages in the 09–11 UK window',attachment_sha256=PAYLOAD['sha'])
  p['draft_id']=did
for p in plans:
 # Exercise the real periodic freeze: approved care stays queued; outreach stops.
 with db.db_session() as c:
  db.mark_lead_booked(c,p['lid'],p['cid'])
  draft=dict(db.get_draft(c,p['draft_id']));state=db.get_lead_state(c,p['lid'],p['cid'])
  assert draft['status']=='scheduled' and state['status']=='booked'
  assert aftercare.approval_for(c,draft) is not None and aftercare.approval_for(c,draft,for_send=True) is None
  assert scheduler.compose_send_body(draft).count(p['signature_html'])==1
  assert scheduler.draft_attachments(draft)==[attachment]
  assert draft['sent_at'] is None and draft['to_override']==p['to'] and draft['body_html']==p['body_html']
  assert state['followup_count']==p['previous_state']['followup_count']
  p['verified_status']='scheduled';p['fingerprint']=aftercare.fingerprint(draft)
with httpx.Client(base_url='http://127.0.0.1:8080',timeout=60) as client:
 assert client.post('/login',data={'password':settings.app_password}).status_code==303
 response=client.get('/api/scheduled');assert response.status_code==200
 ids={x.get('draft_id',x.get('id')) for x in response.json()['scheduled']};assert {p['draft_id'] for p in plans}<=ids
print(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'count':28,'status':'scheduled','attachment':attachment,'plans':plans},ensure_ascii=False))
'''
script='PAYLOAD='+repr(payload)+'\n'+remote
r=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app-onebodyldn python -'],input=script,capture_output=True,text=True,encoding='utf-8',timeout=240)
if r.returncode:raise RuntimeError(r.stderr[-1800:])
result=json.loads(r.stdout)
(P/'aftercare-scheduled-readback.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'count':result['count'],'status':result['status'],'first':result['plans'][0]['uk'],'last':result['plans'][-1]['uk'],'ids':[p['draft_id'] for p in result['plans']]},ensure_ascii=False))
