import json,pathlib,subprocess
OUT=pathlib.Path(__file__).resolve().parent.parent/'mindaptive-preview-2026-10-27'
rows=json.loads((OUT/'fresh-review.json').read_text(encoding='utf-8'))
ids=[r['draft_id'] for r in rows if r.get('draft_id')]
code='''import json,logging
from app import db,smartlead,main
logging.disable(logging.CRITICAL)
accounts=list(smartlead.list_email_accounts())
addressmap={(a.get('from_email') or '').lower():a for a in accounts}
out=[]
with db.db_session() as c:
 for i in IDS:
  d=dict(db.get_draft(c,i))
  a=addressmap.get((d.get('sender_email') or '').lower())
  snapshot=json.loads(d.get('thread_snapshot') or '[]')
  out.append({'draft_id':i,'status':d['status'],'recipients':main._recipients_payload(snapshot,d.get('lead_email') or '',d),'sender_found':a is not None,'sender_name':a.get('from_name') if a else None,'smtp_ok':a.get('is_smtp_success') if a else None,'imap_ok':a.get('is_imap_success') if a else None})
print(json.dumps(out))
'''.replace('IDS',repr(ids))
r=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','-o','ConnectTimeout=10','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app python -'],input=code,capture_output=True,text=True,encoding='utf-8',timeout=60)
assert r.returncode==0,'Recipient verification failed; no writes.'
resolved={x['draft_id']:x for x in json.loads(r.stdout)}
for row in rows:
    if row.get('draft_id') not in resolved:continue
    v=resolved[row['draft_id']]
    row['blockers']=[b for b in row['blockers'] if b!='sender_not_active']
    if not v['sender_found']:row['blockers'].append('sender_not_active')
    elif v['smtp_ok'] is False:row['blockers'].append('sender_smtp_error')
    if v['status']!=row['draft_status']:row['blockers'].append('draft_status_changed')
    row.update(recipients=v['recipients'],sender_name=v['sender_name'],smtp_ok=v['smtp_ok'],imap_ok=v['imap_ok'])
    row['eligible']=not row['blockers']
(OUT/'fresh-review.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'reviewable':sum(r['eligible'] for r in rows),'held':[{k:r.get(k) for k in ['email','blockers']} for r in rows if not r['eligible']]}))
