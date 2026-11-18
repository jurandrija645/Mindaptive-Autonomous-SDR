from datetime import datetime
from zoneinfo import ZoneInfo
import collections,hashlib,json,pathlib,subprocess
OUT=pathlib.Path(__file__).resolve().parent
read=lambda n:json.loads((OUT/n).read_text(encoding='utf-8'))
plan={r['draft_id']:r for r in read('approved-schedule-plan.json')}
results=read('schedule-results.json')
ids=[r['draft_id'] for r in results]
code='''import json,hashlib
from app import db
with db.db_session() as c:
 out=[]
 for i in IDS:
  d=dict(db.get_draft(c,i))
  out.append({'draft_id':i,'status':d['status'],'scheduled_at':d['scheduled_at'],'body_hash':hashlib.sha256(d['body_html'].encode()).hexdigest(),'to':d['to_override'],'cc':d['cc_override'],'sent_at':d['sent_at']})
print(json.dumps(out))
'''.replace('IDS',repr(ids))
r=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','-o','ConnectTimeout=10','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app python -'],input=code,capture_output=True,text=True,encoding='utf-8',timeout=60)
assert r.returncode==0,'Could not confirm schedule; do not claim completion.'
verified=json.loads(r.stdout)
by_id={v['draft_id']:v for v in verified}
scheduled=[];skipped=[]
for result in results:
    v=by_id[result['draft_id']];p=plan[result['draft_id']]
    if result['status'] in ['scheduled','already_scheduled']:
        assert v['status']=='scheduled' and v['scheduled_at']==p['scheduled_at'] and v['body_hash']==p['body_hash'] and not v['sent_at']
        assert v['to']==p['recipients']['to'] and (v['cc'] or '')==(p['recipients'].get('cc') or '')
        dt=datetime.fromisoformat(v['scheduled_at'])
        local=dt.astimezone(ZoneInfo(p['schedule_timezone']))
        assert local.date().isoformat()=='2026-10-27'
        assert ((16,0)<=(local.hour,local.minute)<=(17,30)) if p['schedule_group']=='America_campaign' else ((9,0)<=(local.hour,local.minute)<=(11,0))
        scheduled.append({**result,'email':p['email'],'group':p['schedule_group'],'schedule_timezone':p['schedule_timezone'],'local_time':local.isoformat(),'zagreb_time':dt.astimezone(ZoneInfo('Europe/Zagreb')).isoformat()})
    else:skipped.append(result)
report={'date':'2026-10-27','scheduled_count':len(scheduled),'scheduled':scheduled,'skipped':skipped,'verification':verified,'body_changes':False,'emails_sent_now':False,'lead_label_changes':False,'authorization':'User approved the preview batch and specified Europe mornings 09–11 and American campaigns 16–17:30 Zagreb.'}
(OUT/'schedule-confirmed.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# Zakazane Mindaptive poruke — 27. listopada 2026.','',f"Potvrđeno je {len(scheduled)} zakazanih poruka. Sadržaj odobrenih draftova nije mijenjan. Ništa nije poslano odmah; statusi/labeli leadova nisu mijenjani.",'','Europske kampanje: ravnomjerno 09:00–11:00 u odabranoj europskoj zoni. Američke kampanje: 16:00–17:30 po zagrebačkom vremenu. UK zona je London prema domeni/adresi/potpisu; europske zemlje prema domeni gdje je poznato; ostalo prema zoni spremljenoj u aplikaciji. Skupina za Ameriku utvrđena je prema kampanjama USA/EST&CST.','', '| Lead | Draft | Skupina | Lokalno | Zagreb | To | Cc |','|---|---:|---|---|---|---|---|']
for s in scheduled:
    p=plan[s['draft_id']]
    lines.append(f"| {p['name'] or p['email']} | {s['draft_id']} | {s['group']} | {s['local_time'][11:16]} {s['schedule_timezone']} | {s['zagreb_time'][11:16]} | {s['to']} | {s['cc'] or '—'} |")
if skipped:
    lines+=['','## Preskočeno','']+[f"- Draft {s['draft_id']}: {s.get('reason','provjeriti')}" for s in skipped]
lines+=['','William i Jean-Pierre nisu bili dio odobrenog batcha za zakazivanje. Standardna provjera novih odgovora ostaje aktivna neposredno prije slanja.']
(OUT/'raspored-potvrden.md').write_text('\n'.join(lines),encoding='utf-8')
manifest=read('approval-manifest.json')
manifest.update(approval_status='approved_by_user_and_scheduled',scheduled=True,scheduled_count=len(scheduled),schedule_confirmation_file=str(OUT/'schedule-confirmed.json'),skipped_during_schedule=skipped)
(OUT/'approval-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'verified_scheduled':len(scheduled),'groups':dict(collections.Counter(s['group'] for s in scheduled)),'skipped':skipped}))
