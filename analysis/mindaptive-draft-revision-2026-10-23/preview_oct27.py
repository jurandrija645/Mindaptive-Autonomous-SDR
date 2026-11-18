import collections,html,json,pathlib,re
OUT=pathlib.Path(__file__).resolve().parent.parent/'mindaptive-preview-2026-10-27'
OLD=OUT.parent/'mindaptive-inbox-review-2026-10-22'
rows=json.loads((OUT/'fresh-review.json').read_text(encoding='utf-8'))
records={r['key']:r for r in json.loads((OLD/'records.json').read_text(encoding='utf-8'))}
def plain(t):
    t=re.sub(r'<br\s*/?>|</(?:p|div)>','\n\n',t or '',flags=re.I)
    return html.unescape(re.sub('<[^>]+>','',t)).strip()
labels={'no_open_draft':'Nema otvorenog drafta','draft_replaced_since_review':'Draft je u međuvremenu zamijenjen','not_pending':'Draft više nije pending','campaign_not_confirmed':'Nije potvrđena trenutna kampanja','unsubscribed':'Lead je odjavljen','no_contact_or_booked_or_done':'Status zabranjuje nastavak ili je sastanak rezerviran','new_thread_activity':'Razgovor se promijenio nakon izrade drafta','five_outgoing_without_reply':'Već pet naših poruka zaredom bez odgovora','sender_not_active':'Pošiljateljev mailbox nije među aktivnima','missing_signature':'Nedostaje potpis pošiljatelja','verification_error':'Provjera nije uspjela','demo_access_review':'Prvo provjeriti problem pristupa demu'}
for r in rows:
    if r['key']=='3950427/4542616635':
        r['eligible']=False
        if 'demo_access_review' not in r['blockers']:r['blockers'].append('demo_access_review')
ready=[r for r in rows if r['eligible']]
held=[r for r in rows if not r['eligible']]
lines=['# Mindaptive: poruke za tvoj pregled prije 27. listopada 2026.','',f"Ponovno je provjereno {len(rows)} razgovora. **{len(ready)} draftova za pregled**, {len(held)} izdvojeno za dodatnu provjeru.",'','**Nijedna poruka nije zakazana ni poslana ovom pripremom.** Prvo Andrewov pregled i odobrenje, zatim zakazivanje za utorak, 27. listopada. Statusi leadova nisu mijenjani. Ovo je vremenski presjek; neposredno prije zakazivanja treba ponoviti provjeru novih odgovora i odjava.','',f"U pripremljenoj skupini: {dict(collections.Counter(r.get('kind') for r in ready))}.",'','## Izdvojeno iz predloženog slanja','','| Lead | Draft/status | Razlog |','|---|---|---|']
for r in held:
    old=records[r['key']]
    lines.append(f"| {old['name'] or old['email']} / {old['email']} | {r.get('draft_id',r.get('expected_draft_id','—'))} / {r.get('draft_status',r.get('original_status','—'))} | {'; '.join(labels.get(b,b) for b in r['blockers'])} |")
lines+=['','## Draftovi koji čekaju tvoj pregled','']
for i,r in enumerate(ready,1):
    old=records[r['key']]
    recipients=r.get('recipients') or {}
    lines += [f"### {i}. {r['name'] or old['name'] or r['email']} — draft {r['draft_id']}",'',f"Lead: {r['email']} · Kampanja: {old['campaign_name']} · Vrsta: {r['kind']}",'',f"Pošiljatelj: {r.get('sender_name') or ''} <{r['sender_email']}>. Status: {r['category']}. Naših poruka zaredom bez odgovora: {r['consecutive_sent']}.",'',f"**To:** {recipients.get('to','provjeriti u aplikaciji')} · **Cc:** {recipients.get('cc') or '—'}",'',f"Zadnja naša poruka: {(r.get('last_outbound_at') or '—')[:10]}. Zadnja primljena: {(r.get('last_inbound_at') or '—')[:10]}.",'',plain(r['body_html']),'']
    if r.get('english'):lines+=['**Engleski prijevod za pregled:**','',r['english'],'']
    lines+=['**Potpis:**','',plain(r['signature_html']), '']
lines+=['## Kako odobriti','','Možeš odobriti sve draftove iz ove skupine ili navesti imena/brojeve za izmjenu ili izostavljanje. Zakazivanje slijedi tek nakon tog odobrenja. To i Cc prije slanja potvrđuju se u aplikaciji prema aktualnom razgovoru.']
(OUT/'pregled-poruka.md').write_text('\n'.join(lines),encoding='utf-8')
manifest={'client':'Mindaptive','target_date':'2026-10-27','approval_status':'awaiting_user_review_and_approval','scheduled':False,'sent':False,'lead_status_changes':False,'ready_for_review':ready,'held':held}
(OUT/'approval-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'review_count':len(ready),'held':len(held),'kinds':dict(collections.Counter(r.get('kind') for r in ready))}))
