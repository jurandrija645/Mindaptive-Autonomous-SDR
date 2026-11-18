import collections,csv,hashlib,io,json,logging,os,pathlib,sqlite3,sys
from datetime import datetime,time,timezone
from zoneinfo import ZoneInfo
from app import db,detector,pipeline,scheduler,smartlead
from app.config import settings
from app.email_clean import to_plain_text
logging.disable(logging.CRITICAL)
assert not settings.auto_send_followups,'Automatic sending must remain off'
assert not settings.dry_run,'Audit must run on the live OneBody database'
assert os.getenv('CLIENT_DIR','').endswith('onebodyldn'),'Wrong client'
ROOT=pathlib.Path('/data/status-audit-2026-10-22')
ROOT.mkdir(exist_ok=True)
backup=ROOT/'before.db'
if not backup.exists():
 source=sqlite3.connect(settings.db_path);destination=sqlite3.connect(str(backup));source.backup(destination);destination.close();source.close()
items=BUNDLE
(ROOT/'authorized-plan.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')

def signature(messages):
 return [(m.kind,m.message_id,m.timestamp.astimezone(timezone.utc).isoformat(),hashlib.sha256(to_plain_text(m.body).encode()).hexdigest()) for m in messages]

def planned_signature(item):
 return [(m['kind'],m['message_id'],detector._parse_timestamp(m['time']).astimezone(timezone.utc).isoformat(),hashlib.sha256(m['text'].encode()).hexdigest()) for m in item['audited_messages']]

bycampaign=collections.defaultdict(list)
for item in items:bycampaign[item['campaign_id']].append(item)
live_exports={};fresh={}
for cid,rows in bycampaign.items():
 raw=smartlead.export_campaign_leads_csv(cid)
 live_exports[cid]={int(r['id']):r for r in csv.DictReader(io.StringIO(raw))}
 result=smartlead.get_message_history_bulk(cid,[r['lead_id'] for r in rows])
 for r in rows:
  entry=result.get(str(r['lead_id'])) or {}
  fresh[r['key']]=detector.normalize_thread(entry.get('history') or [])
 print('Fresh threads checked for campaign',cid,len(rows),file=sys.stderr,flush=True)
results=[]
protected={'donotcontact','leadoptedout','weoptedout','unsubscribed','meetingbooked'}
norm=lambda v:''.join(c for c in (v or '').lower() if c.isalnum())
categories=smartlead.fetch_categories()
interested_id=categories[settings.interested_category_name]
booked_id=scheduler._category_id_fuzzy(categories,settings.meeting_booked_category_name)
for item in items:
 key=item['key'];cid=item['campaign_id'];lid=item['lead_id'];d=item['verified'];thread=fresh[key]
 result={'key':key,'name':item['name'],'applied':False,'provider_changed':False,'retired_drafts':[],'stopped_error_enrollments':0}
 try:
  with db.db_session() as c:
   row=db.get_lead_state(c,lid,cid);state=dict(row) if row else {}
  result['before_apply']=state
  live=live_exports[cid].get(lid)
  if not live:
   result['outcome']='lead_missing_from_live_campaign';results.append(result);continue
  provider=live.get('category') or ''
  result['provider_before_apply']=provider
  if state.get('status') in ['booked','stopped','blacklisted'] or norm(provider) in protected or str(live.get('is_unsubscribed')).lower()=='true':
   result['outcome']='protected_in_live_state';results.append(result);continue
  if signature(thread)!=planned_signature(item):
   result['outcome']='thread_changed_since_audit';result['fresh_messages']=[dict(kind=m.kind,time=m.timestamp.isoformat(),message_id=m.message_id,text=to_plain_text(m.body),sender=m.from_email) for m in thread];results.append(result);continue
  if not thread:
   result['outcome']='empty_live_thread';results.append(result);continue
  # A running manual sequence keeps its ownership. A failed, zero-send
  # enrollment explicitly reviewed above may be returned to the manual inbox.
  with db.db_session() as c:
   active=c.execute("SELECT * FROM sequence_enrollments WHERE lead_id=? AND campaign_id=? AND state IN ('active','paused','error')",(lid,cid)).fetchall()
  if active and not (d.get('stop_failed_sequence') and all(r['state']=='error' and r['steps_sent']==0 for r in active)):
   result['outcome']='active_sequence_preserved';results.append(result);continue
  target=item['target']
  decision=detector.decide(thread,state.get('followup_count',0),'active',hot=state.get('temperature')=='hot')
  if target!='booked':
   target={detector.Action.REPLY:'reply',detector.Action.FOLLOWUP:'followup',detector.Action.NONE:'waiting'}[decision.action]
   if d.get('snooze_review_date'):target='waiting'
  if target=='booked':
   assert d.get('confirmed_booking') and any(d['human_quote'] in to_plain_text(m.body) for m in thread if m.kind=='reply')
   if norm(provider)!=norm(settings.meeting_booked_category_name):
    smartlead.update_lead_category(cid,lid,booked_id,pause_lead=True);result['provider_changed']=True
   with db.db_session() as c:
    db.upsert_lead_state(c,lid,cid,interested=1,smartlead_category=settings.meeting_booked_category_name)
    db.mark_lead_booked(c,lid,cid)
    db.upsert_lead_state(c,lid,cid,**scheduler._summary_for({},thread,'booked',thread[-1]))
  else:
   if provider!=settings.interested_category_name:
    # Pause cold campaign automation during owner-reviewed recovery. This
    # operation never resumes a provider sequence or schedules an email.
    smartlead.update_lead_category(cid,lid,interested_id,pause_lead=True);result['provider_changed']=True
   latest=thread[-1]
   fields=scheduler._summary_for({},thread,target,latest)
   fields.update(interested=1,status='awaiting_reply' if target=='reply' else 'active',archived_at=None,archive_reason=None,smartlead_category=settings.interested_category_name,email=live['email'],campaign_name=item['campaign_name'])
   if not state.get('name_locked'):fields['name']=state.get('name') or item['name']
   if not state.get('timezone_guess'):fields['timezone_guess']='Europe/London'
   if d.get('snooze_review_date'):
    fields['snooze_until']=datetime.combine(datetime.fromisoformat(d['snooze_review_date']).date(),time(9),tzinfo=ZoneInfo('Europe/London')).astimezone(timezone.utc).isoformat()
   if latest.kind=='reply':fields['category_message_id']=latest.message_id
   if not state.get('temperature_locked') and state.get('temperature','cold')=='cold':fields.update(temperature='warm',temperature_reason='Verified personal engagement in owner-authorized DeepSeek V4 Pro audit')
   with db.db_session() as c:
    if active:
     result['stopped_error_enrollments']=db.stop_sequence_enrollments(c,lid,cid,'owner_authorized_status_audit')
    for draft in c.execute("SELECT id,kind,status,reply_message_id FROM drafts WHERE lead_id=? AND campaign_id=? AND status IN ('pending','scheduled')",(lid,cid)).fetchall():
     if draft['reply_message_id']!=latest.message_id or draft['kind']=='autoreply':
      db.update_draft(c,draft['id'],status='stale');result['retired_drafts'].append(draft['id'])
    db.upsert_lead_state(c,lid,cid,**fields)
    if target=='followup' and not db.has_open_draft(c,lid,cid):
     c.execute("UPDATE candidates SET status='open',updated_at=? WHERE lead_id=? AND campaign_id=? AND kind='followup' AND status IN ('dismissed','drafted')",(db.now_iso(),lid,cid))
     db.upsert_candidate(c,lid,cid,'followup',lead_name=fields['name'] if 'name' in fields else state.get('name'),lead_email=live['email'],lead_company=state.get('company'),campaign_name=item['campaign_name'],reason='Owner-authorized audit: '+decision.reason,last_message_preview=to_plain_text(latest.body)[:200],last_message_at=latest.timestamp.isoformat())
    elif target!='followup':
     c.execute("UPDATE candidates SET status='dismissed',reason='status audit: not due',updated_at=? WHERE lead_id=? AND campaign_id=? AND kind='followup' AND status='open'",(db.now_iso(),lid,cid))
  pipeline.cache_normalized_thread(cid,lid,thread)
  with db.db_session() as c:
   result['after']=dict(db.get_lead_state(c,lid,cid))
   result['candidate']=[dict(r) for r in c.execute('SELECT id,kind,status FROM candidates WHERE lead_id=? AND campaign_id=?',(lid,cid))]
   result['open_drafts']=[dict(r) for r in c.execute("SELECT id,kind,status,reply_message_id FROM drafts WHERE lead_id=? AND campaign_id=? AND status IN ('pending','scheduled','sending')",(lid,cid))]
  result.update(applied=True,outcome='updated',target=target,decision_reason=decision.reason)
  print('Updated',key,target,file=sys.stderr,flush=True)
 except Exception as exc:
  result.update(outcome='error',error=type(exc).__name__+': '+str(exc)[:300])
 results.append(result)
 (ROOT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
# Verify canonical labels independently after all writes.
for cid in bycampaign:
 live={int(r['id']):r for r in csv.DictReader(io.StringIO(smartlead.export_campaign_leads_csv(cid)))}
 for r in results:
  if r['applied'] and int(r['key'].split('/')[0])==cid:
   label=live.get(int(r['key'].split('/')[1]),{}).get('category')
   r['provider_after_verified']=label
   expected=settings.meeting_booked_category_name if r['target']=='booked' else settings.interested_category_name
   r['provider_verified']=norm(label)==norm(expected)
with db.db_session() as c:
 final_states=[dict(r) for r in c.execute('SELECT * FROM leads_state')]
 final_drafts=[dict(r) for r in c.execute("SELECT id,lead_id,campaign_id,kind,status,reply_message_id,created_at,sent_at,scheduled_at FROM drafts")]
 final_inbox=[dict(r) for r in db.list_inbox(c)]
final={'completed_at':datetime.now(timezone.utc).isoformat(),'results':results,'states':final_states,'drafts':final_drafts,'inbox':final_inbox,'backup_path':str(backup),'auto_send_followups':settings.auto_send_followups}
(ROOT/'final.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(final,ensure_ascii=False))
