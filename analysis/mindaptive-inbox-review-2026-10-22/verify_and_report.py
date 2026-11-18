import collections
import html
import json
import re
import pathlib
import subprocess

OUT = pathlib.Path(__file__).resolve().parent
def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))
def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
def plain(value):
    value = re.sub(r'<br\s*/?>', '\n', value or '', flags=re.I)
    value = re.sub(r'</(?:p|div)>', '\n\n', value, flags=re.I)
    return html.unescape(re.sub('<[^>]+>', '', value)).strip()
def cell(value):
    return str(value or '—').replace('|', '/').replace('\n', ' ')

saved = read('drafts-saved.json')
assert len(saved) == 56 and all(x.get('status') == 'pending' for x in saved)
ids = [x['draft_id'] for x in saved]
code = '''import json
from app import db
ids=IDS
with db.db_session() as c:
 rows=[dict(db.get_draft(c,x)) for x in ids]
print(json.dumps([{k:r.get(k) for k in ['id','lead_id','campaign_id','status','kind','body_html','body_translation','signature_html','model','created_at','scheduled_at']} for r in rows]))
'''.replace('IDS', repr(ids))
command = 'cd /root/mindaptive-responder && docker compose exec -T app python -'
response = subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','-o','ConnectTimeout=10','root@167.71.63.154',command],input=code,capture_output=True,text=True,encoding='utf-8',timeout=60)
assert response.returncode == 0, 'Remote readback failed; no changes made by verification.'
verified = json.loads(response.stdout)
assert len(verified) == 56
assert all(x['status'] == 'pending' and plain(x['body_html']) and not x['scheduled_at'] for x in verified)
payloads = {x['key']: x for x in read('drafts-round1.json') + read('drafts-curated.json')}
by_id = {x['id']: x for x in verified}
for s in saved:
    v = by_id[s['draft_id']]
    v['key'] = s['key']
    p = payloads[s['key']]
    # Rendering may wrap paragraphs and links but must retain the message text.
    normalized = lambda t: re.sub(r'\s+', ' ', plain(t).replace('**', '')).strip()
    assert normalized(v['body_html']) == normalized(p['body']), (s['key'], 'body differs')
write('drafts-verified.json', verified)

records = {x['key']: x for x in read('records.json')}
decisions = read('reviewed-decisions.json')
decision_map = {x['key']: x for x in decisions}
held = read('drafts-held.json')
for h in held:
    if h['key'] in {'3950427/4542617478', '3950427/4542617094'}:
        h['reason'] = 'Četiri odlazne poruke bez odgovora; još ne ispunjava Lead Done kriterij. Zadnjom porukom najavljeno je zatvaranje/uklanjanje dema, pa prije dodatnog kontakta treba odlučiti želimo li nastaviti.'
    if h['key'] == '2538823/2758494711':
        h['reason'] = 'U razgovoru iz 2025. već je ponuđeno 200–400 € po kvalificiranom sastanku. Prije nove ponude potvrditi vrijede li te cijene i uvjeti i danas; ne izmišljati nove.'
    if h['key'] == '3950427/4542617719':
        h['reason'] = 'Rachel je demo ponovno poslan 20. listopada, prije dva dana. Pričekati povratnu informaciju; prije eventualnog slanja cijene treba potvrditi stvarnu ponudu.'
write('drafts-held.json', held)
for s in saved:
    d = decision_map[s['key']]
    d.update(draft_action='SAVED_PENDING', saved_draft_id=s['draft_id'])
    d['draft_original'] = plain(by_id[s['draft_id']]['body_html'])
    d['draft_english'] = plain(by_id[s['draft_id']]['body_translation'])
    if d['key'] in {'3562710/4080234417','2738607/3025134830','2538823/2758496826','2538823/2758495355','2538823/2758495791','2538823/2758495403'}:
        d['next_step_hr'] = 'Ranije traženi datum već je prošao; pregledati spremljeni kratki draft za nastavak razgovora i odlučiti o slanju.'
for h in held:
    d = decision_map[h['key']]
    d.update(draft_action='HELD_FOR_REVIEW', draft_original='', draft_english='', manual_review=True, next_step_hr=h['reason'])
write('reviewed-decisions.json', decisions)
changes = [d for d in decisions if d['change_proposed']]
done = [d for d in changes if d['recommended_label'] == 'Lead Done']
interested = [d for d in changes if d['recommended_label'] == 'Interested']
assert len(done) == 16 and all(d['consecutive_sent'] >= 5 for d in done)
assert len(interested) == 6
cost = sum(read(str(p.relative_to(OUT))).get('usage', {}).get('cost', 0) for p in list(OUT.glob('batch-*.json')) + list((OUT/'quality').glob('batch-*.json')))
manifest = {'approval_status':'awaiting_user_approval', 'client':'Mindaptive', 'review_date':'2026-10-22', 'model':'deepseek/deepseek-v4-flash', 'model_cost_usd':cost, 'counts':{'leads':len(records),'messages':sum(len(r['messages']) for r in records.values()),'drafts_saved_pending':len(saved),'proposed_label_changes':len(changes),'interested':len(interested),'lead_done':len(done),'bookings_preserved':sum(d['next_action']=='POST_MEETING_REVIEW' for d in decisions)}, 'executed':{'drafts_saved':True,'categories_changed':False,'emails_sent':False,'emails_scheduled':False}, 'status_proposals':[{k:d.get(k) for k in ['key','name','email','current_label','recommended_label','consecutive_sent','reason_hr','evidence','manual_review']} for d in changes], 'pending_drafts':saved, 'held':held}
write('bulk-review-manifest.json', manifest)

lines = ['# Mindaptive: pregled svih leadova, 22. 10. 2026.', '', f"Pregledano je {len(records)} leadova i {manifest['counts']['messages']} poruka; 116 leadova pripada website ponudama. Analiza i provjera draftova: DeepSeek V4 Flash (`deepseek/deepseek-v4-flash`), zabilježeni trošak ${cost:.4f}.", '', '**Spremljeno je 56 draftova, svi pending i bez zakazanog slanja. Nismo mijenjali statuse niti slali poruke.** Postojeće draftove zamijenili smo samo kada je novi draft uspješno spremljen; stare verzije ostaju u povijesti.', '', 'Od 300 ranije otvorenih draftova, 263 su bili autoreply nudges. Njihovo postojanje samo po sebi nije razlog za slanje. Zadržano je 46 rezerviranih sastanaka i sve odjave/zabrane kontakta. U 98 razgovora zadnja je poruka iz 2025., pa stare datume treba tumačiti prema datumu poruke.', '', '## Predložene promjene statusa', '', f'Ukupno {len(changes)} prijedloga, još ništa nije primijenjeno: 6 Interested, 16 Lead Done i 18 ostalih ispravaka.', '', 'Lead Done vrijedi samo za najmanje pet uzastopnih naših poruka bez primljenog odgovora. Dostavljen link ili cijena nisu razlog za Lead Done. Rezervacije i odjave imaju prednost.', '']
for title, group in [('Propušteni Interested',interested),('Lead Done: pet ili više poruka bez odgovora',done),('Ostali ispravci', [d for d in changes if d not in interested and d not in done])]:
    lines += ['## '+title,'','| Lead | Trenutno → prijedlog | Naših poruka zaredom | Zašto |','|---|---|---:|---|']
    for d in group:
        lines.append(f"| {cell(d['name'])} ({cell(d['email'])}) | {cell(d['current_label'])} → {cell(d['recommended_label'])} | {d['consecutive_sent']} | {cell(d['reason_hr'])} |")
    lines += ['']
lines += ['## Što treba tvoju odluku prije slanja', '', '- **Ed / Infocon:** u punom emailu pronađeni su odgovori na oba pitanja: jednokratna licenca uz malu ponavljajuću naknadu te VP Operations, VP/Manager IT i C-level kao donositelji odluke. Sada mu treba konkretna cijena. Ne treba mu ponavljati pitanja ili forsirati sastanak koji je odbio.', '- **Carlos:** ranije smo obećali personalizirani video; treba potvrditi da postoji i priložiti stvarni link.', '- **EVgo:** odgovor upućuje na business development. To je interes, ali prije slanja treba potvrditi adresata i raspoloživ demo.', '- **Trish:** zadržati interes uz njezinu molbu da se kontakt odgodi; promjena statusa ne znači odmah slati poruku.', '- **46 Meeting-Booked leadova:** prvo provjeriti ishod sastanka. Nisu uključeni u novi prodajni bulk.', '', '### Draftovi zadržani na provjeri', '', '| Lead | Razlog |','|---|---|']
for h in held:
    d = decision_map[h['key']]
    lines.append(f"| {cell(d['name'])} ({cell(d['email'])}) | {cell(h['reason'])} |")
lines += ['', '## Datoteke za pregled', '', '- [Sve pripremljene poruke](draftovi-za-pregled.md)', '- [Analiza svakog od 517 leadova](svi-leadovi.md)', '- [Točan popis predloženih bulk radnji](bulk-review-manifest.json)', '', 'Svaki draft prije slanja treba završni pregled. Prije eventualnog bulk izvršenja ponovno provjeriti zadnju poruku, odjave, rezervacije, adresate i eventualne ručne izmjene. Odobrenje statusa i odobrenje slanja zasebne su odluke.']
(OUT/'sazetak-i-prijedlog.md').write_text('\n'.join(lines),encoding='utf-8')

lines = ['# Mindaptive: 56 draftova za pregled', '', 'Svi su spremljeni u aplikaciji kao pending. Ništa nije poslano ni zakazano. U tekstu ispod prikazano je spremljeno tijelo poruke; aplikacija zasebno prikazuje potpis pošiljatelja. Adresate provjeriti u To/Cc retku prije slanja.', '']
for s in sorted(saved, key=lambda s:(decision_map[s['key']]['priority'],decision_map[s['key']]['name'] or decision_map[s['key']]['email'])):
    d = decision_map[s['key']]; v = by_id[s['draft_id']]
    lines += [f"## {d['name'] or d['email']} — draft {s['draft_id']}", '', f"{d['email']} · {d['campaign_name']} · {v['kind']} · {d['priority']} · {d['current_label']}", '', f"**Zašto:** {d['reason_hr']}", '', f"**Sljedeći korak:** {d['next_step_hr']}", '', plain(v['body_html']), '']
    if v['body_translation'] and plain(v['body_translation']) != plain(v['body_html']):
        lines += ['**English translation for review:**','',plain(v['body_translation']),'']
(OUT/'draftovi-za-pregled.md').write_text('\n'.join(lines),encoding='utf-8')

lines = ['# Pojedinačna analiza svih 517 leadova', '', 'Prijedlozi još nisu provedeni. SAVED_PENDING označava draft pripremljen za pregled, bez slanja.', '', '| Lead / email | Kampanja | Trenutni status → prijedlog | Naših zaredom | Akcija / draft | Razlog i sljedeći korak |', '|---|---|---|---:|---|---|']
for d in decisions:
    lines.append(f"| {cell(d['name'])} / {cell(d['email'])} | {cell(d['campaign_name'])} | {cell(d['current_label'])} → {cell(d['recommended_label'])} | {d['consecutive_sent']} | {cell(d['next_action'])}; {cell(d['draft_action'])} {d.get('saved_draft_id','')} | {cell(d['reason_hr'])} {cell(d['next_step_hr'])} |")
(OUT/'svi-leadovi.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'verified_pending_drafts':len(verified),'kinds':dict(collections.Counter(x['kind'] for x in verified)), 'signatures_present':sum(bool(x['signature_html']) for x in verified),'model_cost_usd':cost,'proposals':dict(collections.Counter(x['recommended_label'] for x in changes))}))
