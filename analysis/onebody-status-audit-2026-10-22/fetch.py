import collections,json,pathlib,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'tmp/onebody-mailbox-audit-2026-10-22'))
sys.path.insert(0,str(ROOT))
import operate as api
from app.email_clean import to_plain_text
s=json.loads((OUT/'snapshot.json').read_text())
states={f"{r['campaign_id']}/{r['lead_id']}":r for r in s['states']}
cps={str(r['id']):r['name'] for r in s['campaigns']}
roster={}
for cid,rs in s['exports'].items():
 for r in rs:
  key=f"{cid}/{r['id']}"
  if r.get('category') or int(r.get('reply_count') or 0)>0 or key in states:
   roster[key]={'key':key,'lead_id':int(r['id']),'campaign_id':int(cid),'name':(' '.join([r.get('first_name') or '',r.get('last_name') or ''])).strip(),'email':r['email'],'campaign_name':cps[cid],'export':r,'state':states.get(key)}
for key,r in states.items():
 if key not in roster: roster[key]={'key':key,'lead_id':r['lead_id'],'campaign_id':r['campaign_id'],'name':r['name'] or r['email'],'email':r['email'],'campaign_name':r['campaign_name'],'export':{},'state':r}
(OUT/'roster.json').write_text(json.dumps(list(roster.values()),ensure_ascii=False,indent=2),encoding='utf-8')
cache=OUT/'threads-raw.json'
threads=json.loads(cache.read_text()) if cache.exists() else {}
groups=collections.defaultdict(list)
for r in roster.values():
 if r['key'] not in threads: groups[r['campaign_id']].append(r)
for cid,rs in groups.items():
 for start in range(0,len(rs),75):
  chunk=rs[start:start+75]
  for attempt in range(5):
   try:
    result=api.call(f'/campaigns/{cid}/message-history-for-leads/bbfbdsFGHlBr76ruhjvh6fhHL',{'lead_ids':[str(r['lead_id']) for r in chunk]})
    break
   except Exception:
    if attempt==4: raise
    time.sleep(5*(attempt+1))
  for r in chunk:
   entry=result.get(str(r['lead_id']))
   if entry is not None: threads[r['key']]=entry.get('history',[]) if isinstance(entry,dict) else entry
  cache.write_text(json.dumps(threads,ensure_ascii=False),encoding='utf-8')
  print('Threads fetched',len(threads),'/',len(roster),flush=True)
  time.sleep(1.3)
records=[]
for key,r in roster.items():
 msgs=[]
 for m in threads.get(key,[]):
  msgs.append({'kind':'sent' if m.get('type')=='SENT' else 'reply' if m.get('type')=='REPLY' else m.get('type'),'time':m.get('time'),'from':m.get('from'),'message_id':m.get('message_id'),'text':to_plain_text(m.get('email_body') or '')})
 msgs.sort(key=lambda m:m['time'] or '')
 records.append({**r,'messages':msgs})
(OUT/'records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print('Complete',len(records),'empty',sum(not r['messages'] for r in records),flush=True)
