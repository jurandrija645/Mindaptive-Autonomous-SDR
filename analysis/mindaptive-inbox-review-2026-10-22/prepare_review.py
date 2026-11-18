import collections
import json
import pathlib
import re
from datetime import datetime, timezone

OUT = pathlib.Path(__file__).resolve().parent
records = json.loads((OUT / 'records.json').read_text(encoding='utf-8'))
decisions = {x['key']: x for x in json.loads((OUT / 'model-decisions.json').read_text(encoding='utf-8'))}
live = json.loads((OUT / 'live-categories.json').read_text())
assert len(decisions) == len(records) == 517
saved = {x['key']:x for x in json.loads((OUT/'drafts-saved.json').read_text()) if x.get('status')=='pending'}
rows = []
quality = []
explicit_review_candidates = {'3950427/4542617478','3950427/4542616635','3950427/4542617094','3960583/3729675040','2732401/3016173350','2738607/3025135572','2738607/3025134886','2538823/2758495823','2538823/2758494883'}


def no_draft(d, reason):
    d.update(draft_action='NONE',draft_original='',draft_english='',draft_reason_hr=reason)


for r in records:
    d=dict(decisions[r['key']])
    current=live.get(str(r['campaign_id']),{}).get(str(r['lead_id']))
    current_label=current['category'] if current else r['smartlead_category']
    unsub=bool(current and str(current.get('is_unsubscribed')).lower()=='true')
    original=r['smartlead_category']
    d.update(name=r['name'],email=r['email'],company=r['company'],campaign_id=r['campaign_id'],lead_id=r['lead_id'],campaign_name=r['campaign_name'],current_label=current_label,app_cached_label=original,consecutive_sent=r['consecutive_sent'],website_offer=r['website_offer'],is_unsubscribed=unsub,current_status_confirmed=bool(current))
    protected=re.sub(r'[^a-z]','',current_label.lower())
    internal=r['email'].lower()=='mindaptive@gmail.com'
    booked=protected=='meetingbooked'
    if not current:
        d.update(next_action='HUMAN_REVIEW',manual_review=True,reason_hr='Lead nije potvrđen u trenutnoj kampanji u Smartleadu; prvo provjeriti pripadnost kampanji.')
        no_draft(d,'Nije potvrđena trenutna kampanja.')
    elif internal:
        d.update(recommended_label=current_label,next_action='NO_ACTION',manual_review=True,reason_hr='Interni Mindaptive testni lead; izuzet iz komercijalnih bulk promjena i slanja.')
        no_draft(d,'Interni testni lead.')
    elif unsub or protected in {'donotcontact','leadoptedout','weoptedout'}:
        d.update(recommended_label=current_label,next_action='NO_ACTION',reason_hr='Zadržati odjavu/zabranu kontakta; ne uključivati u slanje.',manual_review=False)
        no_draft(d,'Odjavljen lead ili zabrana kontakta.')
    elif booked:
        d['recommended_label']=current_label
        d['next_action']='POST_MEETING_REVIEW'
        no_draft(d,'Postojeća rezervacija: prvo provjeriti ishod sastanka i eventualna otvorena pitanja.')
    elif d['recommended_label'] in ['Do Not Contact','Lead Opted Out','We opted Out','Not Interested'] and not d.get('human_interest'):
        d['next_action']='NO_ACTION'
        no_draft(d,'Odbijanje ili opt-out; nema prodajnog follow-upa.')
    elif r['consecutive_sent']>=5:
        d.update(recommended_label='Lead Done',next_action='NO_ACTION',manual_review=False,confidence='high',reason_hr=f"Od zadnjeg primljenog odgovora poslali smo {r['consecutive_sent']} poruka zaredom bez odgovora; zadovoljen korisnikov kriterij za Lead Done.")
        no_draft(d,'Ne pripremati šestu poruku; predložiti Lead Done.')
    else:
        if d['recommended_label']=='Lead Done':
            d.update(recommended_label='Interested' if d.get('human_interest') else current_label,manual_review=True)
        if d.get('human_interest') and current_label in ['Auto-Reply','Out Of Office','Redirect','Wrong Person','Uncategorizable by Ai','']:
            d['recommended_label']='Interested'
        if not d.get('human_interest'):
            no_draft(d,'Nema potvrđenog stvarnog interesa; ne pripremati automatski nudge.')
        if r['key'] in explicit_review_candidates and d.get('human_interest'):
            d['draft_action']='CREATE' if not r['metadata'].get('draft') else 'REPLACE'
        if r['key']=='2515956/2722090113':
            d.update(next_action='HUMAN_REVIEW',manual_review=True,reason_hr='Ed je inline odgovorio na oba pitanja: jednokratna licenca uz malu ponavljajuću naknadu; ciljani VP Operations, VP/Manager IT i C-level. Sada mu dugujemo konkretnu cijenu, ne nova ista pitanja.',missing_information=['Andrewovo odobrenje konkretne cijene i strukture ponude.'])
            no_draft(d,'Odgovori su pronađeni u punom emailu; nedostaje odobrena ponuda/cijena.')
        if r['key']=='3562710/4080236189':
            d.update(next_action='FOLLOWUP_DUE',recommended_label='Interested',reason_hr='Ronny je tražio primjer njemačkog AI poziva; kasniji OOO ne briše interes. Povratak s godišnjeg bio je u srpnju i rok je prošao.')
            d['draft_action']='REPLACE' if r['metadata'].get('draft') else 'CREATE'
        if r['key']=='3669803/4094527641':
            pass
    if r['key'] in saved:
        d.update(draft_action='SAVED_PENDING',saved_draft_id=saved[r['key']]['draft_id'])
    d['change_proposed']=d['recommended_label']!=current_label
    if d['change_proposed'] and d['confidence']!='high':d['manual_review']=True
    if d['draft_action'] in ['CREATE','REPLACE'] and r['key'] not in saved and current and not unsub and not booked and not internal and r['consecutive_sent']<5 and d.get('human_interest'):
        if d['next_action'] in ['REPLY_NOW','FOLLOWUP_DUE'] or r['key'] in explicit_review_candidates:
            quality.append({'record':r,'decision':d})
    rows.append(d)
(OUT/'reviewed-decisions.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'quality-candidates.json').write_text(json.dumps(quality,ensure_ascii=False,indent=2),encoding='utf-8')
print('Reviewed all',len(rows),'leads. Quality candidates',len(quality))
print('Actions',dict(collections.Counter(x['next_action'] for x in rows)))
print('Proposed labels',dict(collections.Counter(x['recommended_label'] for x in rows if x['change_proposed'])))
