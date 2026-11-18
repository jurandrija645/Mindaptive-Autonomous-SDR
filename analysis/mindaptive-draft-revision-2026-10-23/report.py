import html
import json
import pathlib
import re
import subprocess

OUT=pathlib.Path(__file__).resolve().parent
OLD=OUT.parent/'mindaptive-inbox-review-2026-10-22'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
def plain(t):
    return html.unescape(re.sub('<[^>]+>','',re.sub(r'</p>|<br\s*/?>','\n\n',t or '',flags=re.I))).strip()
results=read(OUT/'save-results.json')
saved=[r for r in results if r.get('status')=='pending']
errors=[r for r in results if r.get('status')!='pending']
records={r['key']:r for r in read(OLD/'records.json')}
payload={p['key']:p for p in read(OUT/'approved-payload.json')}
ids=[r['draft_id'] for r in saved]
code='''import json
from app import db
with db.db_session() as c:
 rows=[dict(db.get_draft(c,i)) for i in IDS]
print(json.dumps([{k:r.get(k) for k in ['id','lead_id','campaign_id','status','kind','body_html','body_translation','signature_html','sender_email','scheduled_at']} for r in rows]))
'''.replace('IDS',repr(ids))
response=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','-o','ConnectTimeout=10','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app python -'],input=code,capture_output=True,text=True,encoding='utf-8',timeout=60)
assert response.returncode==0,'Remote verification failed; no writes from reporting.'
verified=json.loads(response.stdout)
by_id={v['id']:v for v in verified}
norm=lambda t:re.sub(r'\s+',' ',plain(t)).strip()
for s in saved:
    v=by_id[s['draft_id']];p=payload[s['key']]
    assert v['status']=='pending' and not v['scheduled_at']
    assert norm(v['body_html'])==norm(p['body'])
    assert norm(v['body_translation'])==norm(p['english'])
(OUT/'verified.json').write_text(json.dumps(verified,ensure_ascii=False,indent=2),encoding='utf-8')
cost=sum(read(f).get('usage',{}).get('cost',0) for f in list(OUT.glob('batch-*.json'))+list(OUT.glob('translation-*.json')))
age_counts={label:sum((payload[s['key']]['age_days']>=180 if label=='180+' else 60<=payload[s['key']]['age_days']<180 if label=='60–179' else payload[s['key']]['age_days']<60) for s in saved) for label in ['180+','60–179','<60']}
lines=['# Mindaptive: revidirani draftovi, 23. 10. 2026.','',f"Spremljeno i provjereno {len(saved)} novih verzija draftova. Svi su **pending**, bez slanja, zakazivanja i promjene statusa. Prethodne verzije zadržane su u povijesti.",'',f"Starost razgovora: {age_counts['180+']} više od šest mjeseci; {age_counts['60–179']} od dva do šest mjeseci; {age_counts['<60']} kraće od dva mjeseca.",'','Kod dugih pauza poruka sada priznaje proteklo vrijeme, vraća konkretan kontekst, po potrebi uključuje odgovarajući Loom i predlaže kratak razgovor. Ako je lead tražio komunikaciju emailom, to poštujemo. Poboljšanje sustava navodi se općenito, prema Andrewovoj potvrdi; bez izmišljenih rezultata ili novih osobnih videa. Noviji website razgovori ostaju vezani uz demo, cijenu ili otvoreno pitanje.','',f"Model: DeepSeek V4 Flash; zabilježeni dodatni trošak revizije i prijevoda ${cost:.4f}.",'','## Izdvojeno prije slanja','','- William: zadnja poruka poslana je prije dva dana. Postojeći draft o problemu pristupa ostavljen je bez izmjene; provjeriti radi li demo prije dodatnog podsjetnika.','- Jean-Pierre: prije slanja provjeriti aktivan Lukin mailbox i potpis. Nedostajući potpis nije nadomješten izmišljenim.','- Ranije izdvojeni slučajevi bez dovoljne ponude ili obećanog videa ostaju na provjeri. Njih nismo uključili u ovu reviziju.','']
if errors:
    lines += ['## Preskočeno zbog promjene u međuvremenu','']
    for e in errors:lines.append(f"- {records[e['key']]['email']}: {e.get('reason',e.get('error_type'))}. Nije pregazena ručna izmjena ili noviji razgovor.")
lines += ['## Spremljene poruke','']
for s in saved:
    r=records[s['key']];p=payload[s['key']];v=by_id[s['draft_id']]
    sent=[m for m in r['messages'] if m['kind']=='sent']
    inbound=[m for m in r['messages'] if m['kind']=='reply']
    lines += [f"### {r['name'] or r['email']} — draft {s['draft_id']}",'',f"{r['email']} · {r['campaign_name']}",'',f"Zadnja naša poruka: {sent[-1]['time'][:10] if sent else '—'}. Zadnja primljena: {inbound[-1]['time'][:10] if inbound else '—'}. Od zadnje poruke u razgovoru: {p['age_days']} dana.",'',plain(v['body_html']),'']
    if v['body_translation']:lines += ['**English for review:**','',v['body_translation'],'']
(OUT/'draftovi-za-pregled.md').write_text('\n'.join(lines),encoding='utf-8')
manifest=read(OLD/'bulk-review-manifest.json')
replacements={s['key']:s for s in saved}
for entry in manifest['pending_drafts']:
    if entry['key'] in replacements:
        s=replacements[entry['key']]
        entry.update(draft_id=s['draft_id'],replaced_draft_id=s['replaced_draft_id'],status='pending')
manifest['approval_status']='awaiting_user_approval'
manifest['draft_revision_date']='2026-10-23'
manifest['draft_revision_report']=str(OUT/'draftovi-za-pregled.md')
manifest['draft_send_blockers']=[{'draft_id':s['draft_id'],'key':s['key'],'reason':'Missing sender signature; verify active mailbox and signature.'} for s in saved if not by_id[s['draft_id']]['signature_html']]
manifest['revision_errors']=errors
(OLD/'bulk-review-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
decisions=read(OLD/'reviewed-decisions.json')
for d in decisions:
    if d['key'] in replacements:
        s=replacements[d['key']];v=by_id[s['draft_id']]
        d.update(saved_draft_id=s['draft_id'],draft_original=plain(v['body_html']),draft_english=v['body_translation'],draft_revision_date='2026-10-23')
(OLD/'reviewed-decisions.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2),encoding='utf-8')
for filename in ['draftovi-za-pregled.md','sazetak-i-prijedlog.md']:
    f=OLD/filename;t=f.read_text(encoding='utf-8')
    notice='> Novije verzije draftova: [Revizija prema starosti razgovora, 23. 10. 2026.](../mindaptive-draft-revision-2026-10-23/draftovi-za-pregled.md). Ovaj dokument prikazuje prethodni pregled.\n\n'
    if not t.startswith('> Novije verzije'):f.write_text(notice+t,encoding='utf-8')
print(json.dumps({'saved_and_verified':len(saved),'skipped':len(errors),'age_groups':age_counts,'cost_usd':cost,'missing_signature':sum(not bool(v['signature_html']) for v in verified)}))
