"""Build local owner-review copies only. No application writes or send calls."""
import collections
import html
import json
import pathlib
import re
from email.utils import getaddresses

P = pathlib.Path(__file__).resolve().parent
live = json.loads((P / 'reprocessed-live-threads.json').read_text(encoding='utf-8'))
support = json.loads((P / 'reprocessed-support-threads.json').read_text(encoding='utf-8'))
booked = json.loads((P / 'booked-review.json').read_text(encoding='utf-8'))
old = json.loads((P / 'inbox-check-2026-11-03.json').read_text(encoding='utf-8'))
states = {f"{s['campaign_id']}/{s['lead_id']}": s for s in live['states']}
keys = list(live['threads'])
PHYS = 'https://onebodyldn.connect.tm3app.com/book/partnerships/physiotherapy_1/physiotherapy_assessment_treatment_45_min'
M45 = 'https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_45_min'
PDF = 'https://onebody.mindaptive.ai/f/one-body-ldn-partnership-brochure.pdf'
rows = []

def add(n, name, company, context, text, *, action='Predlažem jedan osobni follow-up', offer='physio', clinic='', pdf=False, manual=False, to=None, cc=None):
    key = keys[n-1]
    state = states[key]
    thread = live['threads'][key]
    sender = next(m['sender'] for m in reversed(thread) if m['kind'] == 'sent')
    persona = 'Kurt' if 'kurt' in sender.lower() else 'Rebecca'
    if to is None:
        replies = [m for m in thread if m['kind'] == 'reply' and '@' in m['sender']]
        to = getaddresses([replies[-1]['sender']])[0][1] if replies else state['email']
    body = f'Hi {name},\n\n{text}'
    if offer:
        label, link = ('45-minute physio assessment and treatment', PHYS) if offer == 'physio' else ('45-minute sports massage', M45)
        body += f'\n\nHere\'s the current link for the {label}:\n{link}\n\nUse **VIP8401** when you book.'
        if clinic:
            body += ' ' + clinic
        body += f"\n\nThere's a small £4.99 booking fee that holds your time slot.\n\nFeel free to share the link and code with colleagues too, each person at {company} gets one free session."
    if pdf:
        body += "\n\nI've included the offer PDF if that's easier to pass on."
    body += '\n\n' + persona
    existing = [d['id'] for d in old['drafts'] if f"{d['campaign_id']}/{d['lead_id']}" == key and d['status'] == 'pending']
    rows.append(dict(key=key, name=name, company=company, to=to, cc=cc or '', sender=sender, persona=persona,
                     context=context, action=action, manual=manual, body=body, attachment=PDF if pdf else None,
                     last_message_at=thread[-1]['time'], last_message_id=thread[-1]['message_id'], existing_pending_ids=existing,
                     category=state['category'], kind='reply' if n in (18,29,30) else 'followup',
                     status='local_review_only'))

add(29, 'Josh', 'Transficc', 'Pita je li ponuda za ozljede ili prevenciju; Transficc je remote. Na pitanje još nema odgovora.',
    "Sorry I left your question unanswered. It's a physio appointment with an assessment and treatment, rather than a general wellness session. You don't need a recent injury to ask about an ongoing ache or movement problem.\n\nBeing remote is fine. You can choose a clinic that suits you, rather than one near an office. The current free appointment is 45 minutes.", action='Odgovoriti na konkretno pitanje')
add(30, 'Chloe', 'BBH', 'Odgovor je potpisala Chloe iz Alexove niti. Već je proslijedila HR-u; ne tražimo Alexov osobni booking.',
    "Thanks for passing this to your HR team, and sorry for the slow reply. I've put the current offer details below so they don't have to work back through the old emails. There's nothing for BBH to set up; colleagues book their own appointments.",
    action='Odgovoriti Chloe u postojećoj niti', pdf=True, manual=True,
    to='alex.grieve@bartleboglehegarty.com')
add(18, 'Martyn', 'The Mix Global', 'Ispravio je ured na Farringdon i pita izvor stare adrese. Izvor nije potvrđen. Predložio je Firefish/Vanessu; bez novog kontakta.',
    "Sorry I left this unanswered. We had the wrong location for you. I don't have the original source to hand, so I can't point you to a listing that needs changing. I don't want to guess.\n\nThanks for suggesting Firefish and Vanessa, too. I appreciate you taking the time to help.",
    action='Ručni pregled izvora adrese prije odgovora', offer=None, manual=True)

add(3, 'Matthew', 'Angel Investment Network', 'Radi u Fulhamu, ne Twickenhamu. Rekao je da će ovaj tjedan rezervirati i podijeliti timu.',
    "You mentioned booking this week. Did you find a time that works around your Fulham office days? If you haven't booked yet, the current link is below.", clinic='Fulham is an option for physio; choose it on the booking page.')
add(5, 'Zsolt', 'Birchgrove', 'Upit je za stanovnike 65+, moguća poslovna suradnja. Prethodni odgovor prerano je pretpostavio prikladnost besplatne ponude.',
    "I've been thinking about your note on Birchgrove's residents. You asked about working together, and my last reply didn't really answer that.\n\nWould you be open to a short conversation about what your residents need? We'd need to check which services are suitable before suggesting anything.",
    action='Zaseban poslovni razgovor; potvrditi tko ga vodi', offer=None, manual=True)
add(6, 'Caitlin', 'BETALENT', 'Spomenula je polumaraton; dobila je 45-min massage ponudu 30.10. Stvarna adresa je caitlin.cooper@betalent.com iz odgovora, ne stari Zircon zapis.',
    "Did you find a massage appointment that works around your half-marathon plans? If choosing a clinic or using the booking page is holding things up, let me know.",
    offer=None, action='Kratki follow-up samo ako native niz već ne šalje isto', manual=True)
add(7, 'Angie', 'Goldfinch Agency', 'Odbila Wimbledon kao predalek; ured Wharf Road. Prethodna tvrdnja o par minuta hoda nije provjerena.',
    "Would Moorgate or Clerkenwell work better for your physio appointment? I know Wimbledon wasn't practical for you.\n\nThe session takes place at the clinic, rather than in your office. You can see the addresses and available times on the booking page.",
    action='Jedan osobni follow-up uz poštivanje odbijene lokacije')
add(9, 'Sophie', 'Rights & Brands', 'Tim od četiri u SE1; izričito želi masažu. Prethodni email pogrešno je rekao 45-min masaža u bilo kojoj klinici.',
    "Did the rest of your team fancy trying the massage too? One detail to make clear: the 45-minute massage is at our nine priority clinics, including Waterloo, rather than every location.",
    offer='massage', clinic='Choose Waterloo if that suits your SE1 team.', pdf=True)
add(10, 'Darius', 'Ivalua', 'Dobio je aktualni physio link 28.10. Nema potrebe ponavljati cijeli pitch.',
    "Did the booking link work for you? If you couldn't find a clinic or a time that suits, tell me which area you're looking at.", offer=None,
    action='Kratko provjeriti treba li pomoć; provjeriti native niz prije slanja', manual=True)
add(12, 'Chris', 'DatacenterDynamics', 'Pokazao interes; raspored uredskih dana bio je problem. OOO do 27.10. je prošao. Već je dobio više podsjetnika.',
    "You mentioned your office days were a bit up in the air. If you'd still like to come in, here's the current booking link so you can pick a time that fits. The physio offer is now 45 minutes.",
    clinic='Shoreditch is an option if that still suits you.', action='Samo jedan koristan update, bez novog automatskog niza')
add(17, 'Alistair', 'MVS', 'Stari OOO iz rujna nije razlog za novi odgovor. Prije toga pitao u čemu je catch.',
    "You asked about the catch when we first spoke. It's one free physio appointment, with the booking fee below and no commitment to book more. The current appointment is 45 minutes, and this is the updated booking link.",
    clinic='You can choose City of London if that location still works for you.', action='Jedan update nakon starog OOO-a')
add(20, 'Sarah', 'Flourish', 'Pozitivan odgovor; stari body potpisao Rebecca, stvarni mailbox/persona Kurt. Novi potpis usklađen s mailboxom.',
    "You said you'd like to try a session. If you haven't booked one yet, here's the updated link. The current physio appointment is 45 minutes.",
    clinic='Victoria is an option if it suits you.')
add(21, 'Joyce', 'EC1 Partners', 'Radi od kuće i ponudila kontakte; ne tražimo njen booking. Stvarna adresa joycemccarthy umjesto joycelai.',
    "You kindly offered to introduce me to a few people who might find this useful. Would you still be happy to make an introduction? No need to book anything yourself.\n\nI can send a short note for you to pass on if that helps.", offer=None)
add(22, 'Hannah', 'Thames & Hudson', 'Ured Britannia St, Kings Cross; ne vraćati je na stari Holborn pitch.',
    "You mentioned your office is on Britannia Street. If you'd still like a physio appointment, King's Cross is an option at HQ King's Cross, 344–354 Grays Inn Road, WC1X 8BP.\n\nThe current session is 45 minutes, and the booking details have changed since my last email.",
    clinic="Choose King's Cross on the booking page.")
add(24, 'Layla', 'emap', 'Pitala za širi tim i popust poput 10% kod Octopusa. Nemamo potvrđenu stopu popusta.',
    "I didn't properly come back to your question about an offer for the wider business. I don't have an ongoing staff discount confirmed, so I can't promise a percentage.\n\nWhat I can share is the free first physio appointment below, which your colleagues can each book for themselves.", pdf=True)
add(25, 'João', 'Currensea', 'Pitao točnu adresu. U niti potvrđena Victoria, Spaces 25 Wilton Rd.',
    "If you'd still like to try the physio session, Victoria is at Spaces, 25 Wilton Road, SW1V 1LW. Here's the current booking link; the appointment is now 45 minutes.", clinic='Choose Victoria on the booking page.')
add(26, 'Zoe', 'Thinkbox', 'Brinula je zbog Bupa excessa; ne obećavati da ga možemo ukinuti.',
    "I remember your point about the Bupa excess making treatment less worthwhile. You can use this first-session offer without making a Bupa claim. It's a 45-minute physio appointment, with the booking fee below.\n\nAny later insurance-funded treatment would still depend on your policy.")
add(27, 'Dimitri', 'Monex Europe', 'Već dobio nove opcije 26.10.; ne ponavljati tri različita linka niti gurati masažu umjesto fizija.',
    "Would Aldgate East or City of London suit you better for physio? If you haven't booked yet, here's the current 45-minute physio link in one place.", clinic='Choose whichever of those clinics works for you.')
add(28, 'Alex', 'Crowdcube', 'Već podijelio u Slacku s oko 30 kolega; osobno nema problem. Zadnji email već pitao za odaziv.',
    "Thanks again for sharing the offer in your London Slack channel. I've included a one-page PDF in case anyone wants the details without scrolling through the thread.\n\nIf any colleagues have had trouble booking, they're welcome to reply here.",
    offer=None, pdf=True, action='Opcionalan koristan PDF, ne ponavljati pitanje od 26.10.')
add(31, 'Tom', 'SiteAssist', 'Dag nije u Londonu; u niti je uključio Toma. Zadržati reply-all s potvrđenom tom.johnson-watts adresom.',
    "Dag mentioned you might want a physio appointment for your back. If you're still looking, here's the current link for a 45-minute assessment and treatment. You can choose the clinic that works for you.",
    to='tom.johnson-watts@siteassist.co', cc='dag@siteassist.co.uk', manual=True,
    action='Pregledati reply-all; poruka Tomu, Dag ostaje u Cc')
add(32, 'Jonathan', 'Blackwood Group', 'Pitanje o izvoru podataka već je dobilo odgovor u niti. Novi draft ga ne izmišlja ni ponavlja.',
    "You mentioned being interested when we first spoke. If you'd still like to try physio, here's the current booking link. It's a 45-minute appointment now, and the earlier booking details have changed.", clinic='Charing Cross is an option if that still suits you.')
add(33, 'Nadia', 'Cornerstone Barristers', 'Ponudu želi dati kolegi s bolovima u leđima, ne rezervirati nužno sebi.',
    "Did your colleague manage to arrange a physio appointment for his back? If he hasn't booked yet, you're welcome to pass him the current details below. The appointment is now 45 minutes.", pdf=True)
add(34, 'Laura', 'Intent HQ', 'Pitala zašto je besplatno; odgovor već postoji, više kasnijih generičkih follow-upova.',
    "You asked why we offer a free first session. It's a way for people to try the clinic, with no commitment to book more. If you'd still like to give it a go, here's the current 45-minute physio offer.",
    clinic='Charing Cross is an option if it still works for you.', action='Jedan ažurirani handover, bez novog niza')
add(35, 'Rebecca', 'Harrington Starr', 'Pitala može li podijeliti timu; pisati za kolege, ne za njen osobni termin.',
    "You asked about sharing this with your team. Absolutely. The booking details have changed since we spoke, so here are the current details for colleagues who haven't used their free session yet.", pdf=True)
add(36, 'Annie', 'Transficc', 'U rujnu tražila vrijeme do sljedećeg mjeseca; sada je studeni. Jedan blag kontakt s novim detaljima.',
    "You mentioned taking a look once things were less busy. If now's a better time, here's the current booking link for a 45-minute physio appointment. If you're still tied up, that's fine too.", action='Jedan miran follow-up nakon tražene odgode')
add(37, 'Jeremy', 'Housing Hand', 'Tražio da se javimo u listopadu; zadnji podsjetnik 20.10. nije dao aktualnu ponudu.',
    "You asked me to come back with the details once your diary was a little clearer. Here's the current offer: a free 45-minute physio assessment and treatment, with the booking fee below.\n\nYou can choose a clinic and time on the booking page.")
add(38, 'James', 'Ninety One', 'Izričit interes potvrđen, nije samo OOO. Tražio booking, bio prezaposlen; već više follow-upova.',
    "You mentioned work had kept you tied to your desk. If you'd still like that physio appointment, here's the current link so you can book without another email back and forth. The session is now 45 minutes.",
    clinic='Moorgate is an option if that suits your office days.', action='Jedan jasan update; potvrđen interes u ranijim odgovorima')
add(39, 'Lawrence', 'UNIT', 'Iz Tanjine povezane niti znamo da nije stigao preuzeti njen termin. Ima i vlastiti interes; ne duplicirati njih dvoje.',
    "You said you'd like to try a session. If you haven't arranged one since then, here's the current link for a 45-minute physio appointment. You can choose a time and clinic on the page.",
    action='Uskladiti s Tanjinim servisnim slučajem prije slanja', manual=True)
add(40, 'Faye', 'Dawbell', 'Spomenula gornja leđa i vrat od laptopa; zadnji email koristio istekli kod i lažnu hitnost.',
    "If you're still looking to get your upper back and neck checked, here's the current physio booking link. The appointment is 45 minutes, and the booking details have changed since my last note.", clinic='Mayfair is an option if that suits you.')
add(41, 'Steve', 'Indicium', 'Aktualna adresa indicium.ai. Izričito Achilles/stopalo; physio, bez preusmjeravanja na masažu.',
    "Would Moorgate or Liverpool Street work for the physio appointment you mentioned? I've kept the link below to physio for the Achilles and foot issue you told me about.", to='steve.bryen@indicium.ai')
add(42, 'Andy', 'HELLO!', 'Pozitivan interes nakon Ben Nevisa; već dobio Waterloo alternativu 26.10.',
    "Did you find a physio time that works for you? Waterloo and Blackfriars are both options if either suits. Here's the 45-minute physio link again so you don't have to look back through the thread.")
add(43, 'Harry', 'DixonBaxi', 'Tražio nastavak fizija nakon slomljenog gležnja; ne prodavati masažu kao zamjenu.',
    "Are you still looking for the extra physio support you mentioned for your ankle? Moorgate and Clerkenwell are options if either works for you. Here's the current link for a 45-minute physio appointment.")
add(44, 'Luxman', 'GLAS', 'Pitao cijenu i website. Zadnji email već dao lokacije; ovaj jasno daje aktualnu ponudu, ne cijene nastavka.',
    "You asked about the cost when we first spoke. The current first physio appointment is free, with the £4.99 booking fee below. It's 45 minutes.\n\nYou can book directly on the partnership page, rather than through the usual website booking page.",
    clinic='Moorgate and Blackfriars are options if either suits you.')
add(45, 'Dan', 'DixonBaxi', 'Rekao želi probati, dobio opcije 26.10. Ne tražimo ponovnu potvrdu interesa.',
    "Were you able to choose a time for the session you wanted to try? If not, here's the current physio link. Moorgate and Clerkenwell are options, so pick whichever works better for you.")
add(46, 'Digby', 'Mother', 'Rekao da procjenjuje people team, ne on. Nova poruka treba pomoći prosljeđivanju, ne tražiti osobni booking.',
    "You mentioned this was one for your people team. Would a short offer PDF help them review it? I've included it here so you don't have to pull the details out of our email chain.\n\nNo need to make a booking yourself.",
    offer=None, pdf=True, action='Opcionalan PDF za people team; ne novi isti pitch')
add(47, 'Jody', 'Propeller Group', 'Tražio link 21.10.; poslije samo generička provjera, vrijeme za koristan handover.',
    "Here's the current booking link in case the earlier one held things up. It's for a 45-minute physio assessment and treatment. You can pick your clinic and time on the page.")
add(48, 'Claire', 'Enders Analysis', '13.10. rekla za tjedan-dva; zadnja naša poruka 26.10. Ponuditi jasno bez obećanja ručnog bookinga.',
    "You mentioned hoping to find time to book once work eased off. If you're ready to take a look, here's the current link for a 45-minute physio appointment. You can choose the time that works for you directly.")
add(49, 'Lucie', 'Edelman', 'Ispravno Lucie, Victoria i stalna bol. Bez nove lokacije samo zbog prioriteta.',
    "You mentioned looking for somewhere around Victoria. Our Victoria clinic is at Spaces, 25 Wilton Road, SW1V 1LW. If you'd still like a physio appointment, here's the current 45-minute offer.", clinic='Choose Victoria on the booking page.')
add(50, 'Rory', 'Fospha', 'Ranije pitao kako bookirati; potvrđena Hammersmith opcija, ne pretpostaviti drugu kliniku.',
    "You asked how to book, so here's the current link with the steps in one place: choose Hammersmith if that still suits you, pick a time, then enter the code below. The physio appointment is 45 minutes.")
add(51, 'Michal', 'Astorg', 'Pitao AXA/cijenu. Prethodni odgovor previše obećao nula troška; novi to ispravlja bez jamstva pokrića.',
    "One point to clear up from my last email: we work with AXA, but cover for any later treatment depends on your policy, authorisation and excess. I shouldn't have made it sound automatic.\n\nYou can still use the first-session offer below without making an insurance claim.",
    action='Osobni odgovor s ispravkom preširokog obećanja')
add(52, 'Sam', 'Prodco', 'Pitao lokaciju i dobio Shoreditch. Zadržati, bez neprovjerenog vremena hoda.',
    "Would Shoreditch work for your physio appointment? It's at 75 Great Eastern Street, EC2A 3HN. If you'd like to come in, here's the current link for the 45-minute session.", clinic='Choose Shoreditch on the booking page.')
add(53, 'Sam', 'The Talent Business', 'Pitao dostupnost; ne izmišljati slobodne slotove niti nuditi rezerviranje umjesto njega.',
    "You asked about available appointments. The booking page shows the times for each clinic, so you can choose one that fits your diary. Here's the current link for the 45-minute physio session.")

service_text = {
12: ("Alexander", "Sorry your account and cancellation requests were left without an answer here. Did anyone confirm that the Shoreditch appointments were cancelled?\n\nIf this is still unresolved, I'd like to get the original booking checked rather than send you back to the same login loop.", "Provjeriti stvarna otkazivanja i eventualna terećenja; nema tvrdnje da su termini otkazani."),
17: ("Ashil", "I'm sorry we missed your message when you were outside Moorgate. Were you able to get in and have your appointment?\n\nIf it didn't go ahead, let me know so we can check what happened with the original booking.", "Prvo utvrditi je li uspio ući i je li sesija održana; bez novog prodajnog pitcha."),
19: ("Ginny", "Sorry we left your rescheduling question unanswered. Did you manage to arrange a new date at Hampstead?\n\nIf not, we need to check the cancelled booking before confirming how to keep the introductory offer. I don't want to send you through another booking attempt that might not work.", "Odgovor Ginny/Virginiji, Joel u Cc. Provjeriti otkazani termin i iskorištenost ponude prije novog koda."),
20: ("Ed", "I'm sorry you had to chase the cancellation. I can see you asked on 23 October and followed up before the Liverpool Street appointment on the 27th.\n\nDid you get a clear confirmation that it was cancelled? If not, we need to check the booking under your personal email before arranging another date.", "Ručna provjera otkazivanja i naknade, To Ed; zadržati osobni email i EA, ne odgovoriti samo info adresi."),
22: ("Emily", "Sorry your message about moving the appointment was left unanswered here. Were you able to get it moved, or is it still missing from your account?\n\nIf it still needs sorting, which email address was the appointment booked under? Please don't cancel and make a new booking just to get around the account problem.", "Riješiti originalnu rezervaciju/račun; ne slati još jedan besplatni booking link."),
25: ("Tania", "Sorry we didn't come back to your request for another Thursday after neither you nor Lawrence could make the original appointment. Did you manage to arrange another date?\n\nIf not, let me know whether you're still looking for a Thursday and we can check the original booking first.", "Potvrditi što se stvarno dogodilo; koordinirati s Lawrenceovim follow-upom, ne duplicirati."),
26: ("Danny", "Sorry for the slow reply. I don't want to tell you to cancel and then leave you unable to use the offer. We need to check your existing appointment before confirming how to move it.\n\nHave you already cancelled it, or is the original booking still in your account?", "Najprije provjeriti postojeći termin i allowance. Novi kod nije automatsko pravo na drugu besplatnu sesiju."),
32: ("Franek", "Sorry I never came back with a confirmed booking count. I don't have a verified total to give you, and I don't want to repeat the estimate as though it were confirmed. Thank you again for sharing the offer around RFB.\n\nOne useful update for the team: from 9 November, the Holborn clinic will be at The Gym Group London Bloomsbury, Coram Street, WC1N 1HB. The clinic name on the booking page stays the same.", "Prije slanja pribaviti potvrđen broj iz booking podataka; common code nije pouzdana atribucija. Holborn se seli 9.11.; ne govoriti da je preko ceste.")
}
for r in booked['records']:
    if r['number'] not in service_text:
        continue
    name, text, note = service_text[r['number']]
    t = support[r['key']]
    to, cc = r['to'], ''
    if r['number'] == 19:
        to, cc = 'Virginia@alrmusic.com', 'joel.holmes@bark.com'
    if r['number'] == 20:
        cc = 'edleonklinger@gmail.com,ea@flockcover.com,info@onebodyldn.com'
    rows.append(dict(key=r['key'], name=name, company=r['company'], to=to, cc=cc, sender=r['sender'], persona=r['persona'],
        context=note, action='Ručni servisni odgovor; izvan bulk follow-upa' if r['number'] !=32 else 'Ručni odgovor nakon provjere brojki',
        manual=True, body=f"Hi {name},\n\n{text}\n\n{r['persona']}", attachment=None,
        last_message_at=t[-1]['time'], last_message_id=t[-1]['message_id'], existing_pending_ids=[],
        category='booked', kind='service' if r['number'] !=32 else 'manual', status='local_review_only'))

hold = {
1: 'Amie je 3.11. u 13:46 UTC već dobila konkretan odgovor s aktualnim linkom/kodom. Nema novog drafta da se ne duplicira.',
2: 'Daria: prazan izdvojeni odgovor. Prvo ručno otvoriti originalni email i moguće privitke; bez izmišljanja poruke.',
4: 'Kevin više ne radi u AMR Consultu. Ne slati dalje njemu. Novi kontakt nije automatski odobren.',
8: 'Pedro će se sam javiti kad bude u UK-u; poštovati to. Aktualni sender je pedro.fernandes@smith-system.com.',
11: 'Erika je na rodiljnom; auto-poruka kaže da je već proslijeđeno Cillianu. Ne tražiti od nje ponovno prosljeđivanje.',
13: 'Lasitha je napustio GuarantCo, a adresa odbija dostavu. Bez prodajnog follow-upa.',
14: 'Kiri: greška dostave. Prvo provjeriti adresu/uzrok, ne ponavljati slanje.',
15: 'Simon: greška dostave. Prvo provjeriti adresu/uzrok, ne ponavljati slanje.',
16: 'Arran: odbijanje zbog spam/security pravila. Ne ponavljati isti mail niti slati PDF na tu grešku.',
19: 'Ian je rekao da će se javiti kad bude spreman. Ne pretpostaviti oporavak niti slati medicinske savjete.',
23: 'Yasmin nije u Londonu i rekla je da će se sama javiti. Za sada bez follow-upa.'
}
excluded = [dict(key=keys[n-1], name=states[keys[n-1]]['name'], email=states[keys[n-1]]['email'], reason=reason) for n,reason in hold.items()]
assert len(rows) == 50 and len(excluded) == 11
assert len({r['key'] for r in rows}) == len(rows)
assert len(set(keys) - {r['key'] for r in rows} - {r['key'] for r in excluded}) == 0
for r in rows:
    assert not re.search(r'OBLAC+ESS55|/book/services/|55.minute|\{\{', r['body'], re.I), r['name']
    if 'VIP8401' in r['body']:
        assert '£4.99 booking fee' in r['body'] and 'Feel free to share the link and code with colleagues too, each person at ' in r['body']
    assert r['body'].endswith(r['persona'])

out = dict(status='owner_review_only_no_send_no_schedule', captured_at=live['captured_at'],
           scope='53 inbox conversations plus 8 unresolved booked/support cases; excludes 28 scheduled PDF feedback messages',
           counts=dict(conversations_reviewed=61,proposed_messages=50,no_message=11),records=rows,no_message=excluded)
(P/'ponovno-obradene-poruke.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

sections = [('Odgovori na neodgovorene upite', lambda r:r['kind']=='reply'),
            ('Follow-upovi za pregled', lambda r:r['kind']=='followup'),
            ('Servisni slučajevi i poseban odgovor Franeku', lambda r:r['kind'] in ('service','manual'))]
intro = '''# OneBodyLDN: ponovno obrađene poruke za Mijin pregled

**3. studenoga 2026. — samo pregled. Ove poruke nisu poslane, zakazane ni spremljene preko postojećih draftova u aplikaciji.**

Ponovno su dohvaćena i pročitana **53 razgovora iz prethodnog inbox audita** i **8 poznatih neriješenih booked/servisnih slučajeva**. Pripremljeno je **50 prijedloga poruka**, a za **11 zapisa ne preporučujem novu poruku**. To nije 50 poruka za jedan bulk: servis, partnerstva i nejasne primatelje treba riješiti zasebno.

**Važna promjena:** Amie je u međuvremenu već dobila odgovor 3.11., pa nema novog drafta za nju. **Ranije zakazanih 28 feedback poruka s PDF-om nisu dio ovog pregleda; njihov raspored i odobrenja ovim radom nisu mijenjani.**

Svaki tekst ispod je konkretan prijedlog za postojeću email nit, bez novog subjecta. Pošiljatelj ostaje Kurt ili Rebecca prema stvarnom mailboxu. Na kraju je samo ime; postojeći HTML potpis dodaje se jednom pri stvarnom slanju. To/Cc su prijedlozi za pregled, posebno označeni gdje odgovor dolazi preko tuđe niti. PDF se predlaže samo uz poruke gdje je naveden, i ovim radom nije nikome priložen ni poslan.

Aktualni booking handoveri koriste VIP8401, partnership link i £4.99 fee. Ne nudimo uklonjene klinike ni zatvoreni Fenchurch Street. Lokacija koju je osoba ispravila u razgovoru ima prednost. Fizio ostaje fizio kad je to osoba tražila; 45-min masaža nije dostupna u svakoj klinici. Stari obećani 55-min format ne ponavljamo kao aktualnu ponudu.

Prije odobrenog slanja ponovno provjeriti najnoviju poruku i booking, stvarni To/Cc, odjave i eventualni aktivni Smartlead native niz. Pregled nije pokrenuo novi niz i nije promijenio lead statuse. Mnogi su već dobili više podsjetnika ili “last email”; predlažem najviše jedan koristan, ažurirani kontakt, pa čekanje. Za native slučajeve ne slati paralelni ručni follow-up.

Ovo obuhvaća prethodno identificirane reply/followup/custom razgovore i poznate servisne slučajeve, a ne novu klasifikaciju svih hladnih leadova ili svih 603 auto-reply zapisa.

## Kako pregledati

Uz svaku poruku piše razlog i preporuka. Možeš odobriti ili komentirati po imenu ili rednom broju. “Ručni pregled” znači da prije slanja treba riješiti navedenu provjeru; tekst nije spreman za zajednički bulk. Želiš li poslati cijelu skupinu, prvo treba izdvojiti one koje si odobrila.

'''
md = [intro, '## Popis poruka\n\n| # | Osoba | Vrsta | Preporuka |\n|---|---|---|---|\n']
for i,r in enumerate(rows,1):
    r['number']=i
    md.append(f"| {i} | [{r['name']} — {r['company']}](#poruka-{i}) | {r['kind']} | {r['action']} |\n")
for title,predicate in sections:
    md.append(f'\n## {title}\n')
    for r in rows:
        if not predicate(r):continue
        i=r['number']
        md.append(f"\n<a id=\"poruka-{i}\"></a>\n\n### {i}. {r['name']} — {r['company']}\n\n")
        md.append(f"**To:** {r['to']}  \n**Cc:** {r['cc'] or 'nema predloženog dodatnog Cc'}  \n**Šalje:** {r['persona']} — {r['sender']}  \n**Zadnja aktivnost (UTC):** {r['last_message_at']}  \n**Preporuka:** {r['action']}  \n**Kontekst i prilagodba:** {r['context']}  \n**Privitak:** {'[One Body LDN Partnership Brochure.pdf]('+PDF+')' if r['attachment'] else 'nije predložen'}\n\n")
        md.append('> '+r['body'].replace('\n','\n> ')+'\n')
md.append('\n## Za ove zapise zasad ne šaljemo poruku\n\n')
for e in excluded:
    md.append(f"- **{e['name']}** — {e['email']}: {e['reason']}\n")
md.append('\n## Što predlažem nakon tvog pregleda\n\nPrvo odobriti odgovore Joshu i Chloe, a za Martyna provjeriti izvor adrese. Odvojeno riješiti sedam korisničkih problema s rezervacijama i Franekove brojke. Nakon toga odabrati korisne follow-upove, bez onih koji čekaju povratak osobe, imaju grešku dostave ili već aktivan native niz. Zsoltov upit tretirati kao poslovni razgovor. Prije eventualnog bulka poslati jedan ili dva odobrena testa i provjeriti primatelje, potpis, linkove i predloženi PDF.\n\nOvaj dokument nije odobrenje za slanje.\n')
(P/'sve-poruke-za-pregled-2026-11-03.md').write_text(''.join(md),encoding='utf-8')

def email_html(s):
    s=html.escape(s)
    s=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',s)
    s=re.sub(r'https://[^\s<]+',lambda m:'<a href="'+m.group(0)+'">'+('Book a 45-minute physio session' if 'physiotherapy' in m.group(0) else 'Book a 45-minute sports massage')+'</a>',s)
    return ''.join('<p>'+x.replace('\n','<br>')+'</p>' for x in s.split('\n\n'))

cards=[]
for title,predicate in sections:
    cards.append('<h2>'+html.escape(title)+'</h2>')
    for r in rows:
        if not predicate(r):continue
        metadata=f"To: {r['to']}\nCc: {r['cc'] or '—'}\nŠalje: {r['persona']} <{r['sender']}>\nZadnja aktivnost UTC: {r['last_message_at']}"
        cards.append(f'<article id="poruka-{r["number"]}"><h3>{r["number"]}. {html.escape(r["name"])} <span>{html.escape(str(r["company"]))}</span></h3><p class="tag">{html.escape(r["action"])}</p><p>{html.escape(r["context"])}</p><pre>{html.escape(metadata)}</pre><div class="email">{email_html(r["body"])}</div><p class="attachment">Privitak: '+(f'<a href="{PDF}">One Body LDN Partnership Brochure.pdf</a>' if r['attachment'] else 'nije predložen')+'</p></article>')
excluded_html='<h2>Zasad bez nove poruke — 11 zapisa</h2><ul>'+''.join('<li><strong>'+html.escape(e['name'])+'</strong>: '+html.escape(e['reason'])+'</li>' for e in excluded)+'</ul>'
page='''<!doctype html><html lang="hr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OneBodyLDN — poruke za pregled</title><style>
body{margin:0;background:#f2f4f5;color:#202d35;font:16px/1.6 system-ui,sans-serif}main{max-width:900px;margin:auto;padding:36px 22px}h1{font-size:32px;line-height:1.2}h2{margin-top:46px}article{background:white;border:1px solid #d8dfe2;border-radius:12px;padding:25px;margin:20px 0;break-inside:avoid}h3{margin-top:0;font-size:22px}h3 span{font-weight:400;color:#66747c;font-size:17px}.tag{background:#e7f1ed;display:inline-block;padding:4px 10px;border-radius:5px;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 system-ui;color:#58666e}.email{border-top:1px solid #ddd;padding-top:10px;color:#182a36}.attachment{font-size:13px;color:#61717b}a{color:#08766c}.notice{background:#fff4d6;border-left:4px solid #d69d21;padding:16px}li{margin:12px 0}nav{display:flex;gap:15px;flex-wrap:wrap} @media print{body{background:white}main{max-width:none;padding:0}article{border-radius:0}nav{display:none}}
</style><main><h1>OneBodyLDN<br>Poruke za Mijin pregled</h1><p>3. studenoga 2026. · Ponovno provjeren 61 razgovor · 50 prijedloga · 11 bez nove poruke</p><div class="notice"><strong>Samo pregled.</strong> Ni jedna poruka iz ovog pregleda nije poslana ni zakazana. Postojeći draftovi u aplikaciji nisu prepisani. Ranije zakazane 28 PDF feedback poruke ostaju izvan ovog pregleda.</div><p>Svaka poruka je za postojeću email nit. Ispod su kontekst, To/Cc, stvarni pošiljatelj i predloženi tekst. HTML potpis dodaje se jednom pri stvarnom slanju. Oznaka “ručno” traži zasebnu provjeru prije slanja.</p><p>Aktualni handoveri koriste <strong>VIP8401</strong>, partnership link i £4.99 booking fee. Sedam booked servisnih slučajeva i Franekove brojke nisu za bulk. Prije odobrenog slanja ponovno provjeriti booking, odjave i native nizove. Brojevi poruka isti su u Markdown dokumentu.</p><nav>'''+''.join(f'<a href="#poruka-{r["number"]}">{r["number"]}. {html.escape(r["name"])}</a>' for r in rows)+'</nav>'+''.join(cards)+excluded_html+'<p><strong>Sljedeći korak:</strong> tvoj pregled i odabir poruka. Zatim provjera živog stanja i jedan ili dva odobrena testa prije eventualnog bulka.</p></main></html>'
(P/'sve-poruke-za-pregled-2026-11-03.html').write_text(page,encoding='utf-8')
# Persist the numbering used by both review formats.
(P/'ponovno-obradene-poruke.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out['counts']))
print('Review files created locally. No production changes.')
