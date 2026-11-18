import json
import pathlib
import re

out = pathlib.Path(__file__).resolve().parent
rows = json.loads((out/'reviewed-decisions.json').read_text(encoding='utf-8'))
notes = {
 '2738607/3025135905':'Joan je ljudski proslijedio ponudu prodaji. Postojeći draft je pending, nije poslan. Pregledati ga prije eventualnog odgovora na referral.',
 '2732401/3016173187':'Dan je ponudu proslijedio partnership timu koji će se javiti ako postoji fit. Postojeći draft nije poslan; poštovati taj uvjet i ručno odlučiti treba li odgovor.',
 '2538823/2758495632':'Gennaro traži partnersku mrežu u Hrvatskoj, a ne generičku akviziciju klijenata. Postojeći draft nije poslan; prvo potvrditi odgovara li taj partnerski smjer našoj ponudi.',
 '2515956/2722089471':'Molba za javljanje u prosincu potječe iz listopada 2025. To je prosinac 2025., koji je prošao. Ne postavljati izmišljeni prosinac 2026.; pregledati postojeći draft za reaktivaciju.',
 '2538823/2758494685':'Ankie nije stigla pogledati video u listopadu 2025.; to nije poruka od prošlog tjedna. Pregledati postojeći draft za kratak nastavak nakon duge pauze.',
 '3960583/3822372424':'Eddie je rekao YES i dobio cijenu $850; zadnja poruka je 30. rujna 2026., ne prije dva dana. Pregledati postojeći draft koji pita odgovara li cijena i što blokira odluku.',
 '2738607/3025135256':'Micova odgoda od 3–6 mjeseci iz prosinca 2025. završila je do lipnja 2026. Provjeriti je li rewrite završen prije eventualnog kratkog nastavka; ne čekati prošli travanj.',
 '2738607/3025135845':'Alexey je odbio infrastrukturni trošak unaprijed; razgovor je iz prosinca 2025. Prije nastavka Andrew mora odlučiti o uvjetima. Ne nuditi besplatan probni rad ili popust bez odluke.',
 '2538823/2758497658':'Radoslav je zauzetost i internu provjeru spomenuo u prosincu 2025. Nema aktualnog roka čekanja; ručno odlučiti o kratkoj reaktivaciji nakon duge pauze.',
 '2738671/3025252775':'Stvarni sugovornik je Meritxell, koju je Joan uključio; tražila je video ili sastanak. Poslan je booking link u prosincu 2025. Provjeriti je li sastanak održan izvan inboxa prije podsjetnika.',
 '2538823/2758498639':'Četiri naše poruke bez odgovora, zadnja u studenom 2025. Još nije Lead Done. Odlučiti o petoj završnoj poruci nakon duge pauze.',
 '2515956/2722095051':'Sajid ima tri naše poruke bez odgovora od studenog 2025. Prije novog kontakta pregledati pitanje budžeta i dati samo odobrene uvjete; ne čekati prošli studeni.',
 '2538823/2758495210':'Četiri naše poruke bez odgovora od studenog 2025. Još nije Lead Done. Odlučiti o petoj završnoj poruci, bez pretvaranja da je video nedavno poslan.',
 '2538823/2758495495':'Četiri naše poruke bez odgovora od studenog 2025. Još nije Lead Done. Odlučiti o petoj završnoj poruci nakon duge pauze.',
 '2538823/2758496772':'Michal je tražio razgovor prije automatskog OOO iz listopada 2025. OOO ne poništava interes. Pregledati postojeći pending draft i provjeriti aktualnost prije slanja.'
}
for d in rows:
    if d['key'] in notes:
        d.update(next_action='HUMAN_REVIEW',manual_review=True,next_action_at=None,reason_hr=notes[d['key']],next_step_hr=notes[d['key']])
    if d['key']=='3599203/4126837800':
        d.update(next_action_at=None,next_step_hr='Habbo je rekao da će se javiti nakon odluke. Poštovati čekanje; prije eventualnog podsjetnika pregledati trenutni kontekst, bez izmišljenog roka.')
    if d['key']=='2515956/2722095669':
        d.update(next_action='WAIT',manual_review=True,next_action_at=None,reason_hr='Trish je pokazala interes, ali je zbog tržišnih uvjeta rekla da će se sama javiti ako se situacija smiri. Promjena domene ne čini je pogrešnom osobom.',next_step_hr='Predložiti Interested, ali ne slati prodajni follow-up bez nove provjere; poštovati njezinu molbu da se sama javi.')
    protected = re.sub('[^a-z]','',d['current_label'].lower())
    if d['recommended_label']=='Lead Done':
        d['next_step_hr']='Nakon odobrenja promijeniti status u Lead Done; ne pripremati dodatno slanje.'
    elif d['next_action']=='POST_MEETING_REVIEW':
        d['next_step_hr']='Zadržati rezervaciju. Prvo provjeriti je li sastanak održan i njegov ishod; bez novog prodajnog bulka.'
    elif d['is_unsubscribed'] or protected in {'donotcontact','leadoptedout','weoptedout'} or d['recommended_label']=='Do Not Contact':
        d['next_step_hr']='Bez daljnjeg kontakta. Eventualni predloženi ispravak oznake provesti tek nakon odobrenja.'
    elif d['next_action']=='NO_ACTION' and not d.get('human_interest'):
        d['next_step_hr']='Bez prodajnog slanja na temelju ovog odgovora. Eventualnu preporučenu promjenu statusa prvo odobriti.'
    if d['draft_action']=='SAVED_PENDING':
        d['next_step_hr']='Pregledati spremljeni draft. Prije odobrenog slanja ponovno provjeriti thread i To/Cc; ništa nije poslano.'
    if d['key']=='3562710/4080236189':
        d['next_step_hr']='Pregledati novi engleski draft; stari srpanjski OOO više nije aktualan. Ne tvrditi da je testni njemački broj ili demo spreman bez provjere.'
    if d.get('saved_draft_id')==1103:
        d.update(manual_review=True,next_step_hr='Draft je spremljen, ali nedostaje automatski potpis pošiljatelja Luka. Prije slanja provjeriti aktivan mailbox i njegov potpis.')
(out/'reviewed-decisions.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('Corrected stale timing and draft-versus-send distinctions; no remote writes.')
