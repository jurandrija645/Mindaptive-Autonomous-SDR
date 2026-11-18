import collections
import json
import pathlib
import re
import unicodedata

OUT = pathlib.Path(__file__).resolve().parent
records = json.loads((OUT / 'records-with-links.json').read_text(encoding='utf-8'))
live = json.loads((OUT / 'live-categories.json').read_text())
decisions = {x['key']: x for x in json.loads((OUT / 'model-decisions.json').read_text(encoding='utf-8'))}
critical = {x['key']: x for x in json.loads((OUT / 'critical-decisions.json').read_text(encoding='utf-8'))}
assert len(decisions) == len(records) == 674
decisions.update(critical)
by_key = {r['key']: r for r in records}
overrides = {}


def override(key, label, reason, review=False, next_step=None):
    item = decisions[key]
    item.update(recommended_label=label, reason_hr=reason, manual_review=review, confidence='high' if not review else 'medium', reviewed_by='Codex')
    if next_step:
        item['next_step_hr'] = next_step
    overrides[key] = dict(item)


# Manually inspected complete threads. A booking is not required for Lead Done.
done_names = {'Louise', 'Rory', 'Ashil', 'James', 'Jody', 'Caroline', 'Charlie', 'Edu', 'Beth', 'Nadia', 'Faye', 'Lawrence', 'Jeremy', 'Cassian', 'Fred', 'Mav'}
done_keys = {r['key'] for r in records if r['smartlead_category'] == 'Interested' and r['name'] in done_names}
done_keys.update({'3930675/4520621755', '3930675/4520618811', '3930675/4520615628', '3930675/4520613376', '3876232/4446317432'})
assert len(done_keys) == 21
done_reasons = {
    'Louise': 'Poslani su link, kod i odgovor o fokusu tretmana za nogu i leđa; zadnji je mail naš, bez preostalog pitanja.',
    'Rory': 'Na ponovljeni upit kako rezervirati poslani su link, kod, klinika i objašnjenje £4.99; zadnji mail je naš.',
    'Ashil': 'Na pitanje o ispravnom linku poslani su aktualni partnership link, VIP8401 i detalji 45-minutne ponude; zadnji mail je naš.',
    'James': 'Booking link i kod poslani su više puta; nakon odgode i kasnijeg OOO-a zadnji podsjetnik je naš, bez otvorenog zadatka.',
    'Jody': 'Zatražen booking link je poslan zajedno s kodom, naknadom i uputom za kolege; zadnji mail je naš.',
    'Caroline': 'Link i kod su poslani, a na zadnje Vanijino pitanje o £4.99 izričito je odgovoreno; nema novog pitanja nakon našeg odgovora.',
    'Charlie': 'Poslani su link, kod i uputa kako odabrati željeni datum, zatim završni follow-up; nema otvorenog pitanja.',
    'Edu': 'Nakon najave da će rezervirati poslani su link, kod i naknada te naš zadnji podsjetnik; nema obećane preostale radnje.',
    'Beth': 'Nakon ranijeg problema s magic linkom stigla je do naplate; na zadnje pitanje o £4.99 odgovoreno je, a link i kod ponovljeni.',
    'Nadia': 'Odgovoreno je o Bupi i dijeljenju ponude kolegi; link i kod su ranije poslani, a zadnji mail je naš odgovor.',
    'Faye': 'Nakon stvarnog interesa poslani su link, kod i objašnjenje £4.99, zatim naš zadnji podsjetnik; nema pitanja na čekanju.',
    'Lawrence': 'Nakon OOO-a osobno je prihvatio ponudu; poslani su link, kod i naknada, a zadnji mail je naš.',
    'Jeremy': 'Poslani su link i kod te ispunjen traženi follow-up u listopadu; zadnji mail 20. listopada zatvara praćenje.',
    'Cassian': 'Nakon prihvaćanja poslani su link i kod te završni follow-up; nema otvorenog pitanja ni obećane radnje.',
    'Fred': 'Odgovoreno je što nudimo u odnosu na sportsku pripremu; poslani su link i kod te završni follow-up.',
    'Mav': 'Nakon interesa poslani su link, kod i završni follow-up; nema novog pitanja ili obećane radnje.',
    'Harry Ead': 'Na stvarni interes nakon ozljede poslani su link, kod i upute za rezervaciju po povratku; zadnji mail je naš.',
    'Andrew Macharg': 'Nakon prihvaćanja ponude poslani su link, kod i objašnjenje £4.99; zadnji mail je naš, bez otvorenog pitanja.',
    'Digby Lewis': 'Na prijedlog prosljeđivanja people timu poslani su uvjeti, link, kod i dopuštenje dijeljenja; zadnji mail je naš.',
    'Lux Jega': 'Odgovoreno je na pitanja o cijeni i webu te poslani link i kod; zadnji mail je naš.',
    'Sarah Skelton': 'Pozitivno je odgovorila, a zatim dobila booking link i kod; zadnji mail je naš, bez preostalog pitanja.'
}
for key in done_keys:
    r = by_key[key]
    assert r['messages'][-1]['kind'] == 'sent'
    fulfillment = [m for m in r['messages'] if m['kind'] == 'sent' and ('OBLACCESS55' in m['text'] or 'VIP8401' in m['text']) and 'onebodyldn.connect.tm3app.com/' in m['text']]
    assert fulfillment, key
    override(key, 'Lead Done', done_reasons[r['name']], next_step='Nakon odobrenja označiti Lead Done; ne slati novu poruku.')
    decisions[key]['handover_complete'] = True
    text = fulfillment[-1]['text']
    code = 'VIP8401' if 'VIP8401' in text else 'OBLACCESS55'
    pos = max(0, text.index(code) - 22)
    decisions[key]['evidence'] = [text[pos:pos+125]]
    overrides[key] = dict(decisions[key])

override('3876232/4446316604', 'Meeting Booked', 'Franek je izričito potvrdio rezervaciju; uz to smo obećali provjeriti broj rezervacija kolega i javiti se sutra.', True, 'Potvrditi Meeting Booked i zasebno provjeriti obećani izvještaj o rezervacijama kolega.')
override('4006945/4608050916', 'Interested', 'Sam želi rezervirati i pita za dostupne termine; u presjeku razgovora još nema našeg odgovora.', next_step='Odgovoriti na upit o terminima i poslati aktualne upute za booking, nakon zasebnog pregleda odgovora.')
override('3876232/4446317501', 'Interested', 'Alistair je stvarno odgovorio s interesom i pitanjem o uvjetima; kasniji automatski OOO ne poništava taj interes.', next_step='Nakon odobrenja zamijeniti Out Of Office s Interested; bez slanja poruke.')
decisions['3876232/4446317501']['evidence'] = ["Sounds ideal. What's the catch"]
override('4006945/4608050551', 'Wrong Person', 'Odgovor samo kaže da radi od kuće; to ne dokazuje ni pogrešnu osobu ni jasan interes.', True, 'Ručno odlučiti treba li pojasniti lokaciju i individualnu ponudu; zasad ne mijenjati label.')
override('3930675/4520617891', 'Interested', 'Joshua pita je li ponuda za oporavak od ozljede ili prevenciju; to je otvoreno pitanje, iako je tvrtka remote.', True, 'Ručno potvrditi promjenu Not Interested u Interested i pregledati odgovor na njegovo pitanje.')
override('3930675/4520621302', '', 'Kristian zahvaljuje i opisuje da je aktivan te rijetko u Londonu; nema izričitog odbijanja ni jasnog prihvaćanja.', True, 'Odluka operatera: neutralan odgovor ili Not Interested; ne mijenjati automatski.')
for key, reason, next_step in [
    ('3876232/4446317381', 'Chris je dobio link i kod, ali je odgodio zbog rasporeda; za završavanje tog razgovora tražim ručnu odluku.', 'Odlučiti završavamo li nakon handovera ili ostavljamo kontakt zbog odgode.'),
    ('3930675/4520621199', 'Claire je dobila upute, ali je zadnjim stvarnim odgovorom odgodila rezervaciju zbog posla.', 'Ručno odlučiti je li handover dovoljan za Lead Done ili ostaje Interested.'),
    ('3930675/4520615955', 'Poldy je prijavio odbijeno plaćanje; nema jasne potvrde da je problem s checkoutom otklonjen.', 'Provjeriti radi li booking/plaćanje prije završavanja razgovora.'),
    ('3876232/4446316731', 'Richard je dobio ispravne upute, ali jedan kasniji poslani mail sadrži doslovne placeholdere [Insert Link] i [Insert Code].', 'Pregledati razgovor i odlučiti treba li ispravak; ne slati niti završavati automatski.'),
    ('3876232/4446316050', 'Ian je zadnji pisao i najavio da će se javiti; ranije je tražio i savjet o vježbama koji nije konkretno odgovoren.', 'Ostaviti otvoreno za tim klinike; ne nuditi medicinske savjete automatski.'),
    ('3876232/4446317181', 'Mark je pohvalio email i javio da su u Paddingtonu, ali nije jasno prihvatio ponudu; link i kod su poslani.', 'Ručno odlučiti između Lead Done i zadržavanja postojećeg statusa.')
]:
    override(key, 'Interested', reason, True, next_step)

# These departure notices were individually checked against the full inbound text.
confirmed_departures = {'4006945/4608052346', '4006945/4608052345', '3876232/4446317756', '3876232/4446317231', '3876232/4446317073', '3876232/4446316996', '3876232/4446316056', '3876232/4446317612', '3876232/4446316401', '3876232/4446316057', '3876232/4446316104', '3876232/4446315895', '3876232/4446315631', '3876232/4446315792', '3876232/4446315896', '3876232/4446315339', '3876232/4446316723'}
for key in confirmed_departures:
    override(key, 'Wrong Person', 'Poruka izričito navodi da je osoba napustila tvrtku ili više ne radi ondje; ovo nije privremeni OOO.', next_step='Nakon odobrenja postaviti Wrong Person; ne kontaktirati predložene zamjenske osobe bez zasebne odluke.')
    inbound = next(m['text'] for m in by_key[key]['messages'] if m['kind'] == 'reply')
    decisions[key]['evidence'] = [inbound[:160]]
    overrides[key] = dict(decisions[key])
override('3930675/4520616472', 'Out Of Office', 'Jedini odgovor je automatska obavijest o godišnjem odmoru, bez kasnijeg stvarnog odgovora.', next_step='Nakon odobrenja dodati Out Of Office; bez poruke ili drugih promjena.')
override('4006945/4608049408', 'Out Of Office', 'Jedini odgovor kaže da je odsutna zbog cjelodnevnog sastanka; nema stvarnog odgovora na ponudu.', next_step='Zadržati postojeći Out Of Office.')
override('3876232/4446317374', 'Meeting Booked', 'Problem s računom od £125 riješila je administracija klinike, a Veena je zahvalila; zadržati postojeću rezervaciju.', next_step='Bez promjene labela; iz razgovora nema novog otvorenog pitanja.')
override('3876232/4446316824', 'Meeting Booked', 'Postojeći status je Meeting Booked; na pitanja o Bupi i rezervaciji već smo odgovorili.', next_step='Zadržati postojeći Meeting Booked; ne poništavati rezervaciju samo zato što potvrda nije u ovom threadu.')
override('3876232/4446317376', 'Interested', 'Martyn je nakon OOO-a osobno odgovorio da su preselili u Farringdon i pita odakle nam stara adresa; to nije dokaz pogrešne osobe.', True, 'Ručno potvrditi promjenu Wrong Person u Interested i odlučiti kako odgovoriti na pitanje o staroj adresi.')

# Never demote a known booking or relax an existing explicit opt-out in a bulk proposal.
for r in records:
    key = r['key']
    d = decisions[key]
    current = live[str(r['campaign_id'])][str(r['lead_id'])]['category']
    if current == 'Meeting Booked' and d['recommended_label'] != current:
        old_reason = d['reason_hr']
        override(key, current, 'Zadržati postojeći Meeting Booked; zasebno provjeriti otvoreno pitanje. ' + old_reason, True, 'Riješiti otvoreni booking/support upit bez poništavanja postojeće oznake rezervacije.')
    if current in {'Do Not Contact', 'Lead Opted Out', 'We Opted Out', 'We opted Out'} and d['recommended_label'] != current:
        override(key, current, 'Zadržati postojeću zabranu kontakta; sadržaj poruke ne daje dopuštenje za ponovno aktiviranje.', next_step='Bez promjene i bez daljnjeg kontakta.')


def norm(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text or '')).strip().casefold()


items = []
for r in records:
    key = r['key']
    d = dict(decisions[key])
    current = live[str(r['campaign_id'])][str(r['lead_id'])]['category']
    changed = d['recommended_label'] != current
    d.update(name=r['name'], email=r['email'], campaign_id=r['campaign_id'], lead_id=r['lead_id'], current_label=current, app_cached_label=r['smartlead_category'], change_proposed=changed, last_message_kind=r['messages'][-1]['kind'], last_message_at=r['messages'][-1]['time'])
    source = norm('\n'.join(m['text'] for m in r['messages']))
    valid = [e for e in d.get('evidence', []) if norm(e) and norm(e) in source]
    d['evidence_verified'] = bool(valid)
    d['evidence'] = valid
    if changed and not valid and d.get('reviewed_by') != 'Codex':
        d['manual_review'] = True
        d['validation_note_hr'] = 'Citat modela nije točno potvrđen u tekstu; potreban ručni pregled.'
    if changed and d['recommended_label'] == 'Wrong Person' and d.get('reviewed_by') != 'Codex':
        inbound = '\n'.join(m['text'] for m in r['messages'] if m['kind'] == 'reply')
        if not re.search(r'no longer|has left|have left|left (?:the|our|this)|not (?:being )?monitored|not in use|not.*employed|retir|departed|moved on|ceased', inbound, re.I):
            d['manual_review'] = True
            d['validation_note_hr'] = 'Nema jasne standardne potvrde da je osoba otišla ili da se sandučić ne prati; pregledati prije promjene.'
    if d['confidence'] != 'high' and changed:
        d['manual_review'] = True
    d['approval_group'] = 'manual_review' if d['manual_review'] else 'proposed_change' if changed else 'keep'
    items.append(d)

assert len(items) == len({x['key'] for x in items}) == 674
cost_files = list(OUT.glob('batch-*.json')) + list((OUT / 'critical-review').glob('batch-*.json'))
cost = sum((json.loads(f.read_text(encoding='utf-8')).get('usage') or {}).get('cost') or 0 for f in cost_files)
summary = {'leads': len(items), 'messages': sum(len(r['messages']) for r in records), 'model': 'deepseek/deepseek-v4-flash', 'reported_cost_usd': cost, 'groups': dict(collections.Counter(x['approval_group'] for x in items)), 'proposed_labels': dict(collections.Counter(x['recommended_label'] for x in items if x['approval_group'] == 'proposed_change')), 'manual_change_labels': dict(collections.Counter(x['recommended_label'] for x in items if x['approval_group'] == 'manual_review' and x['change_proposed'])), 'label_changes_executed': 0}
(OUT / 'reviewed-proposals.json').write_text(json.dumps({'summary': summary, 'leads': items}, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'codex-overrides.json').write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding='utf-8')


def cell(text):
    return str(text or 'Bez labela').replace('|', '\\|').replace('\n', ' ')


def table(rows):
    text = ['| Lead | Trenutno | Prijedlog | Razlog |', '|---|---|---|---|']
    for x in rows:
        text.append(f"| {cell(x['name'])}<br>{cell(x['email'])} | {cell(x['current_label'])} | {cell(x['recommended_label'])} | {cell(x['reason_hr'])} |")
    return '\n'.join(text)


proposed = [x for x in items if x['approval_group'] == 'proposed_change']
manual = [x for x in items if x['approval_group'] == 'manual_review']
lines = ['# OneBodyLDN: prijedlog razvrstavanja inboxa', '', '**Samo prijedlog. Nijedan label, lead, draft ili raspored nije promijenjen. Nije poslan nijedan email.**', '', f"Presjek 22. listopada 2026.: {len(items)} leadova i {summary['messages']} poruka. DeepSeek V4 Flash, prijavljeni trošak ${cost:.3f}. Dodatno pregledani stvarni razgovori važnih i spornih leadova. Trenutni labeli provjereni u Smartlead exportima, ne samo lokalnom cacheu.", '', '## Sažetak', '', f"- Predložene jasne izmjene: {len(proposed)}.", f"- Za ručnu odluku: {len(manual)}.", f"- Bez promjene: {sum(x['approval_group'] == 'keep' for x in items)}.", '', 'Lead Done znači da je naša predaja završena: poslali smo link, kod i tražene odgovore, zadnji je mail naš i nema otvorenog zadatka. Nije potrebna potvrda bookinga. Poznata rezervacija zadržava Meeting Booked. OOO sam po sebi nije interes i ne poništava raniji stvarni interes. Stare ponude nisu ponovno otvarane samo zbog promjene booking ponude 21. listopada.', '', 'Promjena kroz aplikaciju može i arhivirati lead ili zaustaviti njegov lokalni follow-up niz. Prije eventualne primjene ponovno provjeriti je li stigla nova poruka i je li status još isti. Ovaj popis ne odobrava slanje poruka, pokretanje novih sekvenci ni promjenu sadržaja poruka.', '']
for label in sorted({x['recommended_label'] for x in proposed}, key=lambda x: (x != 'Lead Done', x)):
    rows = [x for x in proposed if x['recommended_label'] == label]
    lines.extend([f'## Prijedlog: {label} ({len(rows)})', '', table(rows), ''])
lines.extend(['## Ručna odluka prije bilo kakve izmjene', '', table(manual), '', 'Za ove leadove nema odobrenja za bulk promjenu čak ni ako se odobre jasni prijedlozi iz prethodnog dijela.'])
(OUT / 'prijedlog-izmjena.md').write_text('\n'.join(lines), encoding='utf-8')
all_lines = ['# Svi leadovi: individualni prijedlozi', '', 'Ovo je analiza, bez izvršenih promjena. Statusi i poruke čine presjek od 22. listopada 2026.', '', '| Lead | Smartlead sada | Prijedlog | Odluka | Razlog i sljedeći korak |', '|---|---|---|---|---|']
for x in items:
    all_lines.append(f"| {cell(x['name'])}<br>{cell(x['email'])} | {cell(x['current_label'])} | {cell(x['recommended_label'])} | {cell(x['approval_group'])} | {cell(x['reason_hr'])} Sljedeće: {cell(x['next_step_hr'])} |")
(OUT / 'svi-leadovi.md').write_text('\n'.join(all_lines), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=True, indent=2))
