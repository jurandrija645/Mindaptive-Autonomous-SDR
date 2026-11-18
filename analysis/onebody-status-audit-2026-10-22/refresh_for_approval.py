import pathlib,json,subprocess
P=pathlib.Path('analysis/onebody-status-audit-2026-10-22')
plan=json.loads((P/'plan.json').read_text(encoding='utf-8'))
keys={x['key'] for x in plan if x.get('apply')}
keys.update(['3930675/4520622245','3876232/4446316573','4006945/4608049732'])
script='KEYS = '+repr(sorted(keys))+'''\nimport collections,json,logging,httpx
from datetime import datetime,timezone
from app import db,smartlead,detector
from app.config import settings
from app.email_clean import to_plain_text
logging.disable(logging.CRITICAL)
groups=collections.defaultdict(list)
for key in KEYS:
 cid,lid=map(int,key.split('/'));groups[cid].append(lid)
threads={}
for cid,ids in groups.items():
 result=smartlead.get_message_history_bulk(cid,ids)
 for lid in ids:
  thread=detector.normalize_thread((result.get(str(lid)) or {}).get('history') or [])
  threads[f'{cid}/{lid}']=[dict(kind=m.kind,time=m.timestamp.isoformat(),message_id=m.message_id,sender=m.from_email,to=m.to_email,cc=m.cc,text=to_plain_text(m.body)) for m in thread]
with db.db_session() as c:
 states=[dict(r) for r in c.execute('SELECT * FROM leads_state')]
 drafts=[dict(r) for r in c.execute("SELECT id,lead_id,campaign_id,kind,status,reply_message_id,created_at,sent_at,scheduled_at FROM drafts")]
with httpx.Client(base_url='http://127.0.0.1:8080',timeout=60) as client:
 response=client.post('/login',data={'password':settings.app_password});assert response.status_code==303
 response=client.get('/api/inbox');assert response.status_code==200
 inbox=response.json()
print(json.dumps({'captured_at':datetime.now(timezone.utc).isoformat(),'states':states,'drafts':drafts,'threads':threads,'inbox':inbox,'auto_send_followups':settings.auto_send_followups}))
'''
r=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app-onebodyldn python -'],input=script,capture_output=True,text=True,encoding='utf-8',timeout=180)
if r.returncode:raise RuntimeError(r.stderr[-600:])
(P/'approval-review-refresh.json').write_text(r.stdout,encoding='utf-8')
data=json.loads(r.stdout)
old=json.loads((P/'records.json').read_text(encoding='utf-8'));old={r['key']:r for r in old}
changed=[]
for key,thread in data['threads'].items():
 previous=old[key]['messages']
 if [m['message_id'] for m in thread]!=[m['message_id'] for m in previous]:changed.append((key,old[key]['name'],[(m['kind'],m['time'],m['text'][:500]) for m in thread[-2:]]))
print(json.dumps({'checked_threads':len(keys),'changed':changed,'auto_send':data['auto_send_followups'],'captured_at':data['captured_at']},ensure_ascii=True))
