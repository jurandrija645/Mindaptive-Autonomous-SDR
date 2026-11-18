import json,shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

out=Path('analysis/onebody-subsequence-audit-2026-10-28')
out.mkdir(exist_ok=True)
for src,dst in [('onebody-native-before.json','native-before.json'),
                ('onebody-native-after.json','native-after.json'),
                ('onebody-native-details.json','thread-audit.json'),
                ('onebody-native-patch-result.json','changes.json'),
                ('onebody-final.json','final-verification.json'),
                ('onebody-generation-probe.json','generation-probe.json')]:
    shutil.copyfile(Path('tmp')/src,out/dst)
d=json.loads((out/'final-verification.json').read_text(encoding='utf8'))
for name,digest in d['assets'].items():
    import hashlib
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest,name
active=[r for r in d['leads'] if r['mapping']['status'] in ('STARTED','INPROGRESS')]
paused=[r for r in d['leads'] if r['mapping']['status']=='PAUSED']
assert len(d['leads'])==16 and len(active)==14 and len(paused)==2
assert {r['name'] for r in paused}=={'Sean','Lila'}
rows=[]
today=[]
for r in d['leads']:
    m=r['mapping']
    ts=m['next_timestamp_to_reach']
    if ts:
        dt=datetime.fromisoformat(ts).astimezone(ZoneInfo('Europe/London'))
        london=dt.strftime('%d Oct %H:%M')
        zagreb=dt.astimezone(ZoneInfo('Europe/Zagreb')).strftime('%d Oct %H:%M')
        if dt.date().isoformat()=='2026-10-28': today.append(r['name'])
    else: london=zagreb='—'
    note='Already Meeting Booked in parent; child explicitly paused.' if r['name'] in ('Sean','Lila') else ''
    if r['name']=='Devon': note='48-hour timestamp is outside 08:00–18:00 London; earliest next permitted window is Friday 30 Oct.'
    if r['name']=='Angie': note='Latest reply offered Clerkenwell/Moorgate. Old Wimbledon custom field is no longer used by subsequence copy.'
    if r['name']=='Ben': note='Thank-you preceded manual enrollment. Active, step 0, original first-send time restored and read back.'
    rows.append(f"| {r['name']} | {r['company']} | {m['status']} | {london} | {zagreb} | {note} |")
assert set(today)=={'Anzar','Dom','Issy','Ben','Faz','Harry','Jonathan'}
report='''# OneBody response and subsequence audit — 28 October 2026

Four active native Smartlead subsequences contain 16 leads. All 14 leads in
the two parents' current Interested in 45 Physio/Sports categories are enrolled
exactly once in the corresponding child campaign. Two additional child
members, Sean and Lila, have Meeting Booked in their parent and were explicitly
paused in the child during this audit. Four campaigns remain ACTIVE.

## Changes applied

- Deployed OneBody system prompt, booking rules, business overview and response
  templates to the production source and running OneBody container; restarted
  OneBody to invalidate its cached system prompt. File hashes match local files.
- All three booking offers require the £4.99 fee that holds the time slot and
  the company-personalized sharing line. No old massage-fee prohibition remains.
- Updated all 16 email steps in the four Smartlead subsequences in place. All
  include the fee, VIP8401 and `each person at {{company_name}} gets one free
  session`. Removed `{{nearestClinic}}` in favor of letting the lead choose.
  Existing step IDs, cadence, memberships and scheduled timestamps were checked.
- Production model probe (claude-haiku-4-5) returned the correct 45-minute sports
  massage link, £4.99 slot fee and `each person at TPXimpact gets one free
  session`. This was a generation-only probe; no message was sent or stored.

## Schedule verification

First message waits 48 hours from child enrollment (the step itself shows zero
days because the initial wait is stored elsewhere). Seven first messages are
eligible today, 28 October: Anzar, Dom, Issy, Ben, Faz, Harry and Jonathan.
Their scheduled window is 11:48–13:57 London / 12:48–14:57 Zagreb. These are
Smartlead's scheduled eligibility times, not confirmations of actual delivery.
Weekday campaign window is 08:00–18:00 London; mailbox pacing can add delay.

| Lead | Company in Smartlead | State | Next eligibility, London | Zagreb | Notes |
| --- | --- | --- | --- | --- | --- |
'''+ '\n'.join(rows)+'''

## Verified limits

All assigned sending accounts still exist in the live account. All 16 steps
read back with the new wording. The two old drafted native 55-minute children
and the old local responder sequence were left as they were.

Smartlead did not propagate a parent's Meeting Booked pause to its child.
This audit repaired Sean and Lila; it did not add an ongoing cross-campaign
stop mechanism. Future parent bookings still require checking/pausing the
native child. Local `app/sequences.py` hooks protect only local sequences.

Angie's imported data associates her with Goldfinch finance/Wimbledon, while
her signature identifies Goldfinch Agency at Wharf Road. Automated clinic
personalization is removed globally; AI drafts must follow her latest thread.
No new clinic choice was invented or written over her imported custom fields.

Production source backups: `/root/onebody-booking-fix-2026-10-28/`.
Evidence JSON files are stored next to this report. Unrelated workspace edits
were preserved. Source changes have not been committed or pushed.
'''
(out/'audit.md').write_text(report,encoding='utf8')
print(out/'audit.md')
