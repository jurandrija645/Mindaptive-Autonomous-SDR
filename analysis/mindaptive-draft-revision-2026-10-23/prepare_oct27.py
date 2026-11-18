"""Read-only fresh eligibility and preview for the proposed Oct 27 batch."""
import json,pathlib,subprocess
OUT=pathlib.Path(__file__).resolve().parent.parent/'mindaptive-preview-2026-10-27'
OUT.mkdir(exist_ok=True)
OLD=OUT.parent/'mindaptive-inbox-review-2026-10-22'
manifest=json.loads((OLD/'bulk-review-manifest.json').read_text(encoding='utf-8'))
items=manifest['pending_drafts']
code='''import json,logging,re,hashlib
from app import db,pipeline,smartlead,detector
logging.disable(logging.CRITICAL)
items=ITEMS
categories=smartlead.fetch_categories()
catnames={v:k for k,v in categories.items()}
accounts=list(smartlead.list_email_accounts())
addresses={(a.get('from_email') or a.get('email') or a.get('email_address') or '').lower():a.get('from_name','') for a in accounts}
results=[]
for i in items:
 cid,lid=map(int,i['key'].split('/'))
 try:
  with db.db_session() as c:
   row=db.get_lead_state(c,lid,cid)
   draft=db.get_open_draft(c,lid,cid)
   original=db.get_draft(c,i['draft_id'])
   row=dict(row) if row else {}
   draft=dict(draft) if draft else None
   original=dict(original) if original else None
  base={'key':i['key'],'campaign_id':cid,'lead_id':lid,'name':row.get('name'),'email':row.get('email'),'expected_draft_id':i['draft_id'],'original_status':original.get('status') if original else None}
  if not draft:
   results.append({**base,'eligible':False,'blockers':['no_open_draft']});continue
  reasons=[]
  if draft['id']!=i['draft_id']:reasons.append('draft_replaced_since_review')
  if draft['status']!='pending':reasons.append('not_pending')
  current=smartlead.get_lead_by_email(row['email'])
  campaign=next((a for a in current.get('lead_campaign_data',[]) if a['campaign_id']==cid),None)
  category=catnames.get(campaign.get('lead_category_id')) if campaign else None
  if not campaign:reasons.append('campaign_not_confirmed')
  if current.get('is_unsubscribed'):reasons.append('unsubscribed')
  if re.sub('[^a-z]','',(category or '').lower()) in {'donotcontact','leadoptedout','weoptedout','notinterested','meetingbooked','leaddone'}:reasons.append('no_contact_or_booked_or_done')
  thread=pipeline.fetch_normalized_thread(cid,lid)
  snapshot=json.loads(draft.get('thread_snapshot') or '[]')
  if not thread or not snapshot or str(thread[-1].message_id)!=str(snapshot[-1].get('message_id')):reasons.append('new_thread_activity')
  count=0
  for m in reversed(thread):
   if m.kind!='sent':break
   count+=1
  if count>=5:reasons.append('five_outgoing_without_reply')
  sender=(draft.get('sender_email') or '').lower()
  if sender not in addresses:reasons.append('sender_not_active')
  if not draft.get('signature_html'):reasons.append('missing_signature')
  outgoing=[m for m in thread if m.kind=='sent']
  incoming=[m for m in thread if m.kind=='reply']
  results.append({**base,'eligible':not reasons,'blockers':reasons,'draft_id':draft['id'],'draft_status':draft['status'],'kind':draft['kind'],'body_html':draft['body_html'],'english':draft.get('body_translation'),'signature_html':draft.get('signature_html'),'sender_email':sender,'sender_name':addresses.get(sender),'to_override':draft.get('to_override'),'cc_override':draft.get('cc_override'),'category':category,'consecutive_sent':count,'last_outbound_at':outgoing[-1].timestamp.isoformat() if outgoing else None,'last_inbound_at':incoming[-1].timestamp.isoformat() if incoming else None,'last_message_id':thread[-1].message_id if thread else None,'body_hash':hashlib.sha256(draft['body_html'].encode()).hexdigest(),'scheduled_at':draft.get('scheduled_at')})
 except Exception as e:
  results.append({'key':i['key'],'eligible':False,'blockers':['verification_error'],'error_type':type(e).__name__})
print(json.dumps(results,default=str))
'''.replace('ITEMS',repr(items))
response=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','-o','ConnectTimeout=10','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app python -'],input=code,capture_output=True,text=True,encoding='utf-8',timeout=300)
assert response.returncode==0, 'Read-only verification failed.'
rows=json.loads(response.stdout)
(OUT/'fresh-review.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checked':len(rows),'eligible':sum(r['eligible'] for r in rows),'held':[{k:r.get(k) for k in ['key','email','original_status','blockers']} for r in rows if not r['eligible']]},ensure_ascii=False))
