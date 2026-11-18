"""Owner-authorized scheduling of the exact 19 reviewed messages.

Default is read-only preflight. --apply stores approved copy and calls the
dashboard schedule endpoint. No send endpoint is called.
"""
import pathlib,json,subprocess,sys
P=pathlib.Path(__file__).resolve().parent
plan=json.loads((P/'19-prioritetnih-poruka-za-pregled.json').read_text(encoding='utf-8'))
payload={'apply':'--apply' in sys.argv,'drafts':plan['drafts'],'marker':'mia-approved-priority19-20261026'}
remote=r'''
import json,logging,re,html,collections,hashlib
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from app import db,smartlead,detector,signatures,pipeline,drafter,scheduler
from app.config import settings
logging.disable(logging.CRITICAL)
assert str(settings.client_dir).endswith('onebodyldn') if hasattr(settings,'client_dir') else True
assert len(PAYLOAD['drafts'])==19
assert not settings.dry_run, 'DRY_RUN is enabled; cannot confirm actual sending scheduled.'
cats={v:k for k,v in smartlead.fetch_categories().items()}
accounts=smartlead.list_email_accounts()
accountmap={(a.get('from_email') or '').lower():a for a in accounts}
groups=collections.defaultdict(list)
for r in PAYLOAD['drafts']:
 cid,lid=map(int,r['key'].split('/'));groups[cid].append(lid)
threads={}
for cid,lids in groups.items():
 result=smartlead.get_message_history_bulk(cid,lids)
 for lid in lids:threads[f'{cid}/{lid}']=detector.normalize_thread((result.get(str(lid)) or {}).get('history') or [])
def render(md):
 # Preserve approved labels and destinations, rather than passing Markdown
 # links into the application's bare-URL renderer.
 def inline(s):
  s=html.escape(s)
  s=re.sub(r'\[([^\]]+)\]\((https://[^\s)]+)\)',r'<a href="\2" target="_blank" rel="noopener">\1</a>',s)
  return re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',s)
 parts=[]
 for paragraph in md.split('\n\n'):
  ls=paragraph.splitlines()
  if all(x.startswith('- ') for x in ls):parts.append('<ul>'+''.join('<li>'+inline(x[2:])+'</li>' for x in ls)+'</ul>')
  else:parts.append('<p>'+'<br>'.join(inline(x) for x in ls)+'</p>')
 return ''.join(parts)
rows=[]
for n,r in enumerate(PAYLOAD['drafts']):
 cid,lid=map(int,r['key'].split('/'));t=threads[r['key']];assert t and t[-1].kind=='sent',(r['name'],'new reply')
 assert t[-1].message_id==r['last_message_id'],(r['name'],'thread changed')
 sender=detector.last_sender_email(t);to=detector.next_reply_to(t,r['to_suggested']);cc=detector.next_reply_cc(t,sender)
 assert to.lower()==r['to_suggested'].lower(),(r['name'],'recipient changed')
 assert sender.lower()==r['from_previous'].lower(),(r['name'],'sender changed')
 assert sender.lower() in accountmap,(r['name'],'mailbox no longer listed')
 account=accountmap[sender.lower()]
 assert account.get('is_smtp_success',True) and account.get('is_imap_success',True),(r['name'],'mailbox connection unhealthy')
 assert account.get('from_name','').split()[0]==r['persona'],(r['name'],'persona mismatch')
 sig=signatures.get_signature_html(sender);assert sig and '<table' in sig.lower(),(r['name'],'missing HTML signature')
 assert r['persona'] in sig and ('Bossick' if r['persona']=='Rebecca' else 'Johnson') in sig
 remotelead=smartlead.get_lead_by_email(r.get('to_suggested'))
 # Some replies use an alias; find their campaign through the imported email.
 campaigndata=remotelead.get('lead_campaign_data') or []
 entry=next((x for x in campaigndata if str(x.get('campaign_id'))==str(cid)),None)
 if entry is None:
  with db.db_session() as c:state=dict(c.execute('SELECT * FROM leads_state WHERE campaign_id=? AND lead_id=?',(cid,lid)).fetchone())
  remotelead=smartlead.get_lead_by_email(state['email']);campaigndata=remotelead.get('lead_campaign_data') or []
  entry=next((x for x in campaigndata if str(x.get('campaign_id'))==str(cid)),None)
 assert entry is not None,(r['name'],'could not verify current campaign category')
 category=cats.get(entry.get('lead_category_id'),'')
 assert scheduler.norm_category_name(category)=='interested',(r['name'],'current category',category)
 with db.db_session() as c:
  state=dict(c.execute('SELECT * FROM leads_state WHERE campaign_id=? AND lead_id=?',(cid,lid)).fetchone())
  existing=[dict(x) for x in c.execute("SELECT * FROM drafts WHERE campaign_id=? AND lead_id=? AND status IN ('pending','scheduled','sending')",(cid,lid))]
 assert state['status']=='active' and state['category']=='followup',(r['name'],'local state changed',state['status'],state['category'])
 assert not state.get('snooze_until') and not state.get('archived_at'),(r['name'],'hidden/deferred')
 owned=[d for d in existing if d.get('model')==PAYLOAD['marker']]
 assert all(d.get('model')==PAYLOAD['marker'] or (d['status']=='pending' and d['kind']=='followup') for d in existing),(r['name'],'existing scheduled/sending draft')
 assert len(existing)<=1
 body=render(r['body_markdown']);assert '<strong>' in body and len(re.findall('<a href=',body))==3
 assert '/book/services/' not in body and '_45_minSports' not in body
 composed=scheduler.compose_send_body({'body_html':body,'signature_html':sig})
 assert composed.count(sig)==1
 at=datetime(2026,10,26,9,0,tzinfo=ZoneInfo('Europe/London'))+timedelta(minutes=n*6)
 utc=at.astimezone(timezone.utc);assert utc>datetime.now(timezone.utc) and at.hour in (9,10)
 rows.append(dict(key=r['key'],name=r['name'],cid=cid,lid=lid,persona=r['persona'],sender=sender,to=to,cc=cc,remote_category=category,
  scheduled_at=utc.isoformat(),uk_time=at.isoformat(),zagreb_time=utc.astimezone(ZoneInfo('Europe/Zagreb')).isoformat(),body_html=body,signature_html=sig,
  body_sha256=hashlib.sha256(body.encode()).hexdigest(),existing_draft_id=existing[0]['id'] if existing else None,previous_drafts=existing,previous_state=state,
  signature_bytes=len(sig.encode()),last_message_id=t[-1].message_id,reply_stats_id=t[-1].stats_id,
  mailbox_flags={k:account.get(k) for k in ['id','from_name','is_smtp_success','is_imap_success','smtp_success','imap_success'] if k in account}))
if PAYLOAD['apply']:
 with httpx.Client(base_url='http://127.0.0.1:8080',timeout=60) as client:
  auth=client.post('/login',data={'password':settings.app_password});assert auth.status_code==303
  for r in rows:
   approved=next(x for x in PAYLOAD['drafts'] if x['key']==r['key']);t=threads[r['key']]
   # Refresh before staging to avoid superseding an intervening message.
   fresh=detector.normalize_thread(smartlead.get_message_history(r['cid'],r['lid']))
   assert fresh and fresh[-1].message_id==r['last_message_id'] and fresh[-1].kind=='sent',(r['name'],'changed while scheduling')
   with db.db_session() as c:
    cur=db.get_open_draft(c,r['lid'],r['cid'])
    if cur is not None:
     assert cur['id']==r['existing_draft_id'] and (cur['model']==PAYLOAD['marker'] or (cur['status']=='pending' and cur['kind']=='followup')),(r['name'],'concurrent draft')
     assert cur['body_html']==r['previous_drafts'][0]['body_html'],(r['name'],'concurrent edit')
     did=cur['id']
     db.update_draft(c,did,body_html=r['body_html'],signature_html=r['signature_html'],sender_email=r['sender'],model=PAYLOAD['marker'],
       triage_summary='Exact 19-message text approved by Mia; priority clinic alternative; scheduled for 26 Oct 2026 09–11 Europe/London.',
       thread_snapshot=json.dumps([m.__dict__ for m in t],default=str),reply_message_id=t[-1].message_id,reply_email_time=t[-1].timestamp.isoformat(),reply_stats_id=t[-1].stats_id,send_error=None)
    else:
     lead=dict(r['previous_state']);lead.update(id=r['lid'],campaign_id=r['cid'])
     result=drafter.DraftResult('Mia approved exact reviewed text; priority clinic alternative; scheduled for 26 Oct 2026 09–11 Europe/London.',approved['body_markdown'],'',approved['body_markdown'])
     did=pipeline.store_draft_result(c,lead,'followup',t,result,model=PAYLOAD['marker'])
     db.update_draft(c,did,body_html=r['body_html'])
   response=client.post(f'/api/drafts/{did}/schedule',json={'scheduled_at':r['scheduled_at'],'body_html':r['body_html'],'to':r['to'],'cc':r['cc']})
   assert response.status_code==200 and response.json().get('ok'),(r['name'],'schedule failed',response.status_code)
   with db.db_session() as c:
    d=dict(db.get_draft(c,did));assert d['status']=='scheduled' and d['scheduled_at']==r['scheduled_at']
    assert d['body_html']==r['body_html'] and d['signature_html']==r['signature_html']
    assert d['to_override']==r['to'] and (d['cc_override'] or '')==r['cc']
    assert d['sent_at'] is None
   r['draft_id']=did;r['status']='scheduled'
 with db.db_session() as c:
  ids=[r['draft_id'] for r in rows];q=','.join('?' for _ in ids)
  verify=[dict(x) for x in c.execute(f'SELECT id,status,scheduled_at,to_override,cc_override,sent_at FROM drafts WHERE id IN ({q})',ids)]
  assert len(verify)==19 and all(x['status']=='scheduled' and not x['sent_at'] for x in verify)
else:verify=[]
print(json.dumps({'captured_at':datetime.now(timezone.utc).isoformat(),'applied':PAYLOAD['apply'],'count':len(rows),'rows':rows,'readback':verify},ensure_ascii=False))
'''
# httpx is only used for the authenticated local dashboard endpoint.
script='PAYLOAD='+repr(payload)+'\nimport httpx\n'+remote
r=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app-onebodyldn python -'],input=script,capture_output=True,text=True,encoding='utf-8',timeout=240)
if r.returncode:
 raise RuntimeError(r.stderr[-2500:])
data=json.loads(r.stdout)
name='nineteen-scheduled-readback.json' if payload['apply'] else 'nineteen-schedule-preflight.json'
(P/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'applied':data['applied'],'count':data['count'],'rows':[{k:r.get(k) for k in ['name','draft_id','sender','to','cc','uk_time','signature_bytes','existing_draft_id','mailbox_flags']} for r in data['rows']]},ensure_ascii=False))
