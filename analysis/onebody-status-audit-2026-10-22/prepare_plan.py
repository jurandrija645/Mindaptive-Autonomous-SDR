import json,pathlib,sys,collections
ROOT=pathlib.Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from app import detector
from app.config import settings
from datetime import datetime,timezone
OUT=pathlib.Path(__file__).resolve().parent
s=json.loads((OUT/'snapshot.json').read_text())
for k in ['followup_wait_days','hot_followup_wait_hours','max_followups','revive_after_days','followup_business_days']:setattr(settings,k,s['config'][k])
rs={r['key']:r for r in json.loads((OUT/'records.json').read_text(encoding='utf-8'))}
first={r['key']:r for r in json.loads((OUT/'decisions.json').read_text(encoding='utf-8'))}
verified={r['key']:r for r in json.loads((OUT/'verified-decisions.json').read_text(encoding='utf-8'))}
for k,v in json.loads((OUT/'review-overrides.json').read_text(encoding='utf-8')).items():verified[k].update(v)
protected={'donotcontact','leadoptedout','weoptedout','unsubscribed','meetingbooked'}
norm=lambda v:''.join(c for c in (v or '').lower() if c.isalnum())
items=[]
for key,r in rs.items():
 d=verified.get(key);st=r.get('state') or {};provider=r['export'].get('category') or st.get('smartlead_category') or ''
 item={'key':key,'lead_id':r['lead_id'],'campaign_id':r['campaign_id'],'name':r['name'],'email':r['email'],'campaign_name':r['campaign_name'],'before':st,'provider_before':provider,'first':first[key],'verified':d,'apply':False,'reason':'not_actionable'}
 if d and d['genuine_engagement']:
  if st.get('status') in ['booked','stopped','blacklisted'] or norm(provider) in protected or str(r['export'].get('is_unsubscribed')).lower()=='true':
   item['reason']='protected_status'
  elif d.get('confirmed_booking'):
   item.update(apply=True,target='booked',reason='explicit_booking_confirmation')
  elif d['verdict'] in ['awaiting_us','waiting_on_lead','later','temporarily_away'] and d['evidence_verified']:
   thread=[detector.NormalizedMessage(m['kind'],detector._parse_timestamp(m['time']),m['message_id'],m['text'],m['from']) for m in r['messages']]
   dec=detector.decide(thread,st.get('followup_count',0),'active',hot=st.get('temperature')=='hot')
   target={detector.Action.REPLY:'reply',detector.Action.FOLLOWUP:'followup',detector.Action.NONE:'waiting'}[dec.action]
   if d.get('snooze_review_date'):target='waiting'
   # Existing future snoozes remain unless this audit explicitly reviews the date.
   if st.get('snooze_until') and detector._parse_timestamp(st['snooze_until'])>datetime.now(timezone.utc) and not d.get('snooze_review_date'):
    item['reason']='existing_future_snooze'
   else:
    item.update(apply=True,target=target,reason=dec.reason)
 item['audited_messages']=r['messages']
 items.append(item)
(OUT/'plan.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
print('Plan',collections.Counter(i.get('target') or i['reason'] for i in items))
for i in items:
 if i['apply']:print(json.dumps({'key':i['key'],'name':i['name'],'before':i['before'].get('category'),'provider':i['provider_before'],'target':i['target'],'reason':i['reason']},ensure_ascii=True))
