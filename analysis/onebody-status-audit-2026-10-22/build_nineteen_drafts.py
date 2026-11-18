"""Prepare local review copy only. Does not create dashboard drafts or send."""
import json,pathlib,re
from email.utils import parseaddr
from datetime import datetime
from zoneinfo import ZoneInfo
P=pathlib.Path(__file__).resolve().parent
E=json.loads((P/'clinic-review-evidence.json').read_text(encoding='utf-8'))
F=json.loads((P/'nineteen-draft-refresh.json').read_text(encoding='utf-8'))
previous=json.loads((P/'clinic-review-refresh-2026-10-23.json').read_text(encoding='utf-8'))
S={f"{r['campaign_id']}/{r['lead_id']}":r for r in F['states']}
PHYS='https://onebodyldn.connect.tm3app.com/book/partnerships/physiotherapy_1/physiotherapy_assessment_treatment_45_min'
M20='https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_20_min'
M45='https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_45_min'
# Each introduction references this lead's actual conversation. Shared text is
# restricted to the same offer facts and booking instructions for every person.
COPY={
6: ('German','Rebecca',"If you haven't booked yet, **Moorgate** is another option alongside Shoreditch. It gives you a choice of a 45-minute physio session or a 45-minute sports massage, if that suits you better.","Shoreditch still offers 45-minute physio and 20-minute sports massage.","Would Moorgate work for you?",'Tražio je postupak rezervacije, dobio stari link i kod te više podsjetnika. Nudimo konkretan novi izbor, bez ponavljanja „last email”.'),
8: ('Romelia','Rebecca',"If you're coming from your London office, **Aldgate East** is another option alongside Liverpool Street. You can choose a 45-minute physio session or a 45-minute sports massage there.","Liverpool Street still offers 45-minute physio and 20-minute sports massage.","Would Aldgate East suit you?",'Pokazala je interes i već dobila upute. Tvrtka ima i Epping, pa ne pretpostavljamo da dolazi iz Londona svaki dan.'),
9: ('Sat','Rebecca',"If you're still keen to try a session, **Moorgate** is another option alongside the Clerkenwell clinic I mentioned. It offers 45-minute physio and a 45-minute sports massage, so you can pick whichever you'd prefer.","Clerkenwell still offers 45-minute physio and 20-minute sports massage.","Would Moorgate work for you?",'Potpisuje se Sat; pitao je u čemu je catch i već dobio odgovor o £4.99. U potpisu navodi 1 Moorgate; ne ponavljamo netočnu tvrdnju o dvije minute do Clerkenwella.'),
11: ('Nasir','Rebecca',"You mentioned being interested in stretching. If you haven't booked a physio appointment yet, **Aldgate East** is another option alongside Shoreditch. It also offers a 45-minute sports massage if you'd prefer that instead.","Shoreditch still offers 45-minute physio and 20-minute sports massage.","Would Aldgate East work for you?",'Spomenuo je stretching i pitao za datum. Nema potvrđenog termina; dajemo kalendar bez izmišljanja dostupnosti ili propisivanja vježbi. Odgovor ide na naj@ciklum.com.'),
12: ('Amanda','Rebecca',"I'm sorry the booking process was a hassle. If you haven't managed to book, I've put the current links and code below. **Moorgate** is another option alongside City of London, with 45-minute physio or a 45-minute sports massage to choose from.","City of London still offers 45-minute physio and 20-minute sports massage.","If anything gets stuck again, let me know where and I'll help.",'Imala je neispravan kod, pitala za 23.9. i za naplatu. Taj datum je prošao; ne nudimo ga kao dogovor. City of London je bliže uredu, pa ostaje valjan izbor.'),
17: ('Tej','Rebecca',"If you haven't booked yet, there's another choice alongside Bank: **Moorgate** offers a 45-minute sports massage as well as 45-minute physio. The £4.99 booking fee we discussed still applies to the physio offer.","Bank still offers 45-minute physio and 20-minute sports massage.","Would you prefer to stick with Bank, or try Moorgate?",'Već je dobio objašnjenje booking feeja. Ne predstavljamo ga kao novo neodgovoreno pitanje i ne tvrdimo da je Moorgate bliži Banku.'),
18: ('Jodie','Kurt',"You were interested in trying a session. If you haven't booked yet, **Moorgate** is another option alongside Farringdon. It offers 45-minute physio or a 45-minute sports massage, depending on what you'd prefer.","Farringdon still offers 45-minute physio and 20-minute sports massage.","Would Moorgate work for you?",'Tražila je više informacija i već dobila stari link. Zadržavamo Kurta kao personu iz niti; ne koristimo Rebeccin potpis.'),
19: ('Michael','Kurt',"If you're still interested, you can pick a time using the current links below. Alongside Bank, **Moorgate** gives you the choice of a 45-minute physio session or a 45-minute sports massage.","Bank still offers 45-minute physio and 20-minute sports massage.","Would Moorgate suit you, or is Bank easier?",'Pitao je koje podatke trebamo i dobio link. Ne tražimo podatke o osiguranju emailom. Povijesni potpis Rebecca u Kurtovoj niti ne ponavljamo.'),
20: ('Richard','Kurt',"You mentioned looking for a time to come in. If you haven't booked yet, **Aldgate East** is another option alongside Fenchurch Street. You can choose 45-minute physio or a 45-minute sports massage there.","Fenchurch Street still offers 45-minute physio and 20-minute sports massage.","Would Aldgate East work for you?",'Već je dobio opis tvrtke i rekao da će pogledati vrijeme. Ne ponavljamo cijeli opis OneBodyja niti nudimo izmišljene slobodne termine.'),
23: ('Leigh','Rebecca',"If you haven't booked your session yet, **Moorgate** is another option alongside Liverpool Street. It offers a 45-minute sports massage as well as 45-minute physio, so there's a bit more choice.","Liverpool Street still offers 45-minute physio and 20-minute sports massage.","Would Moorgate suit you?",'Jasno je rekao yes please i dobio booking detalje. Navodi Wood Street; ne ponavljamo staru tvrdnju da je Liverpool Street „na pragu”.'),
24: ('Steve','Rebecca',"You asked which location would work for a physio appointment. **Moorgate** is another option alongside Liverpool Street, if it's convenient for you. You can book a 45-minute physio appointment for the Achilles and foot issue you mentioned; Moorgate also offers a separate 45-minute sports massage option.","Liverpool Street still offers 45-minute physio and 20-minute sports massage.","Would you prefer Moorgate or Liverpool Street?",'Tražio je lokaciju i naveo Achilles/lateral foot problem. Ne dijagnosticiramo, ne jamčimo ishod i ne predstavljamo masažu kao zamjenu za procjenu. To je aktualni Indicium email.'),
27: ('Andy','Rebecca',"Did you get a chance to book the physio appointment you mentioned after Ben Nevis? If not, **Waterloo**, on Lower Marsh, is another option alongside Blackfriars. It offers 45-minute physio and, if you'd prefer, a 45-minute sports massage.","Blackfriars still offers 45-minute physio and 20-minute sports massage.","",'Potpisuje se Andy i tražio je physio nakon Ben Nevisa. To je povijesni kontekst, ne tvrdnja da se upravo vratio. Waterloo je dodatna mogućnost, ne navodno bliža klinika.'),
31: ('Harry','Kurt',"Did you get a chance to book the physio appointment you wanted for your ankle? If not, **Moorgate** is another option alongside Clerkenwell. You can book 45-minute physio there; it also offers a separate 45-minute sports massage option.","Clerkenwell still offers 45-minute physio and 20-minute sports massage.","",'Tražio je pomoć za oporavak slomljenog gležnja nakon NHS physija. Ne nudimo masažu kao rehabilitaciju i ne pretvaramo stari „week after” u aktualan dogovor.'),
33: ('Luxman','Rebecca',"If you haven't booked yet, **Moorgate** is another option alongside Blackfriars. It gives you a choice of a 45-minute physio session or a 45-minute sports massage. The physio session is free, with the £4.99 booking fee we discussed.","Blackfriars still offers 45-minute physio and 20-minute sports massage.","Would Moorgate work for you?",'Pitao je za cijenu i web, na što je već odgovoreno. Nema potrebe za novim dugim opisom tvrtke; naknada se jasno veže samo uz physio.'),
34: ('Dan','Kurt',"If you'd still like to come in about the aches and pains you mentioned, **Moorgate** is another option alongside Shoreditch. It offers 45-minute physio or a 45-minute sports massage, whichever you'd prefer.","Shoreditch still offers 45-minute physio and 20-minute sports massage.","Would Moorgate suit you?",'Pokazao je interes nakon odmora i naveo aches & pains. Ispravan pozdrav je Dan, ne Jason iz jednog starog podsjetnika. To je dan.moore@blackkitestudios.com.'),
37: ('Dimitri','Rebecca',"If you haven't booked yet, here are the current links in one place. **Aldgate East** is another option alongside City of London, with 45-minute physio or a 45-minute sports massage to choose from.","City of London still offers 45-minute physio and 20-minute sports massage.","Would Aldgate East work for you?",'Tražio je link. Jedan stari mail poslan je s [Insert Link]/[Insert Code], a odgovor s potpisom nije nova potvrda interesa. Sada svi linkovi i kod moraju biti stvarni.'),
39: ('Dan','Rebecca',"You said you'd like to give a session a try. If you haven't booked yet, **Moorgate** is another option alongside Clerkenwell. It offers a 45-minute sports massage as well as 45-minute physio, so you can choose what you'd prefer.","Clerkenwell still offers 45-minute physio and 20-minute sports massage.","Would Moorgate work for you?",'Daniel Capstick potpisuje se Daniel, ali razgovor se već vodi s pozdravom Dan. Tražio je sljedeće korake; ne miješati ga s Danom Mooreom iz druge tvrtke.'),
45: ('Digby','Rebecca',"Here's a short update for your people team, if you'd still like to pass it on. Alongside Shoreditch, colleagues can choose **Moorgate** for either 45-minute physio or a 45-minute sports massage.","Shoreditch still offers 45-minute physio and 20-minute sports massage.","",'Rekao je da to treba proslijediti people timu. Ne pitamo njega da osobno rezervira i ne tvrdimo da je već proslijedio.'),
46: ('Alex','Rebecca',"Did anyone from the London team get a chance to book after your Slack share? If another option would help, **Moorgate** offers a 45-minute sports massage as well as 45-minute physio. Here are the current links and code for colleagues who haven't booked yet.","Shoreditch still offers 45-minute physio and 20-minute sports massage.","",'Ponudu je već podijelio s oko 30 kolega i izričito ne treba osobni tretman. Tražimo odaziv tima bez izmišljanja broja rezervacija.'),
}
rows=[];out=[]
stamp=datetime.fromisoformat(F['captured_at']).astimezone(ZoneInfo('Europe/Zagreb')).strftime('%d.%m.%Y. %H:%M')
out += ['# OneBodyLDN: 19 osobnih poruka za Mijin pregled','',f'**Niti ponovno pročitane: {stamp}, Zagreb.** To je istih 19 leadova označenih „ponuditi prioritetnu kao dodatnu opciju” u glavnom dokumentu. Nema novih poruka u tim nitima u odnosu na prethodni lokacijski pregled. Ovo su lokalni prijedlozi teksta, nisu draftovi pohranjeni u dashboard niti poslane ili zakazane poruke.','',
 'Za svaki kontakt prvo je provjeren prethodni razgovor, stvarna adresa odgovora i persona. Poruke nude dodatni izbor, zadržavaju postojeću kliniku i ne tvrde da je druga lokacija bliža ili da ima više slobodnih termina.','',
 '**Ponuda u svim porukama:** fizioterapija 45 min i sportska masaža 20 min na svim lokacijama; dodatno sportska masaža 45 min na deset prioritetnih lokacija. Za ovu grupu preporuke su Moorgate, Aldgate East i Waterloo. Kod je VIP8401. Fizioterapija ima £4.99 booking fee; naknada za masažu još nije potvrđena i u porukama joj nije izmišljena cijena.','',
 '**Linkovi:** koriste se samo tri partnership linka iz uputa. Ispravni physio link završava na `_45_min`; završetak `_45_minSports` u zalijepljenom tekstu je spoj dvaju redaka. Poveznice ispod imaju pune ispravne ciljeve.','',
 '**Potpis:** ime na kraju poruke prati personu iz postojeće niti. Stvarni HTML potpis ostaje odvojen od tijela i dodaje se jednom pri pripremi odobrenog testa. Ovaj dokument ne potvrđuje da je mailbox aktivan ni da je konačan HTML potpis provjeren u poslanom emailu.','',
 '**Što pregledati:** tekst, predloženu kliniku i želiš li poslati. Tek kad odabereš 1–2 testa pripremamo konkretne dashboard draftove, provjeravamo svježe To/Cc, mailbox i potpis. Bulk slanje i scheduling čekaju pregled testa i daljnju uputu.','',
 '| # | Lead | Predložena klinika | Persona |','|---|---|---|---|']
selected=[r for r in E['rows'] if r['review_group']=='P']
assert len(selected)==len(COPY)==19
for n,r in enumerate(selected,1):out.append(f"| {n:02d} | {r['name']} | {r['nearest_priority'][0]['name']} | {COPY[r['ordinal']][1]} |")
for n,r in enumerate(selected,1):
 i=r['ordinal']; key=r['key']; greeting,persona,intro,other,close,reason=COPY[i]
 thread=F['threads'][key]
 assert [m['message_id'] for m in thread]==[m['message_id'] for m in previous['threads'][key]]
 assert S[key]['category']=='followup'
 last_sent=[m for m in thread if m['kind']=='sent'][-1]
 last_reply=[m for m in thread if m['kind']=='reply'][-1]
 sender=parseaddr(last_sent['sender'])[1];to=parseaddr(last_reply['sender'])[1]
 assert ('kurt' in sender.lower())==(persona=='Kurt'),(r['name'],sender,persona)
 body=f'Hi {greeting},\n\n{intro}\n\n{other}\n\n'
 body+=f'Use VIP8401 when you book:\n\n- [Physio, 45 minutes]({PHYS})\n- [Sports massage, 45 minutes]({M45})\n- [Sports massage, 20 minutes]({M20})\n\n'
 if i not in {17,33}:body+='The physio session is free, with a £4.99 booking fee to hold your slot.\n\n'
 body+='Feel free to share the link and code with colleagues too, each person gets one free session.\n\n'
 if close:body+=close+'\n\n'
 body+=persona
 # Pin the suggested clinic for both links without asserting any booked slot.
 body=body.replace('Use VIP8401 when you book:',f"For {r['nearest_priority'][0]['name']}, choose that location on the booking page and use VIP8401:")
 if i in {45,46}:body=body.replace('when you book','when they book')
 cc=last_sent.get('cc') or ''
 notes=[]
 if cc:notes.append('Povijesni Cc za provjeru: '+cc+'. Sačuvati potrebne primatelje i ukloniti duplikate tek pri svježoj provjeri.')
 if i==39:notes.append('Isti ured kao Harry: kasnije razmaknuti slanje njima dvojici; ne slati oba istodobno.')
 if i==31:notes.append('Isti ured kao Daniel Capstick: kasnije razmaknuti slanje njima dvojici.')
 if i==34:notes.append('Predloženi prvi test; drugi mogući test je Andy za provjeru druge persone/lokacije.')
 if i in {45,46}:notes.append('Poruka je za tim/preporuku; ne kontaktirati HR ili kolege izravno bez posebne upute.')
 out += ['',f"## {n:02d}. {r['name']} · {r['nearest_priority'][0]['name']}",'',f"**Zašto ovako:** {reason}",'',f"**Za pregled primatelja:** To `{to}` · persona **{persona}** · dosadašnji From `{sender}`.",'',f"**Zašto ta klinika:** {r['address']}; okvirno {str(round(r['nearest_priority'][0]['km'],1)).replace('.',',')} km zračno do predložene klinike. Procjena iz lokacijskog pregleda, nije vrijeme hoda niti potvrda da osoba dolazi iz ureda."]
 if notes:out+=['','**Prije slanja:** '+' '.join(notes)]
 out += ['','**Predložena poruka na engleskom:**','']+[('> '+line if line else '>') for line in body.splitlines()]+['','**Mijina odluka:** ☐ tekst je u redu ☐ promijeni kliniku/tekst ☐ ja ću odgovoriti ☐ preskoči']
 rows.append(dict(key=key,original_review_number=i,review_number=n,name=r['name'],clinic=r['nearest_priority'][0]['name'],persona=persona,to_suggested=to,from_previous=sender,cc_previous=cc,body_markdown=body,reason=reason,last_message_id=thread[-1]['message_id'],thread_read_at=F['captured_at'],status='local_review_only_not_in_dashboard',notes=notes))
out+=['','## Nakon pregleda','',
 'Vrati brojeve 01–19 i izmjene koje želiš. Ovi brojevi vrijede za ovaj dokument; u JSON-u je sačuvan i originalni broj iz pregleda 49 leadova. Nakon izričite upute testiramo samo odabranu jednu ili dvije poruke i čekamo tvoju provjeru stvarnog potpisa i sadržaja. Zatim se zasebno dogovara scheduling ostatka. Nisu odobreni novi nizovi automatskih follow-upova niti resetiranje brojača.','',
 '[Povratak na pregled 49 leadova](./prijedlog-akcija-za-odobrenje.md) · [Podaci za svih 19 predloženih poruka](./19-prioritetnih-poruka-za-pregled.json) · [Svježa provjera razgovora](./nineteen-draft-refresh.json)','']
doc='\n'.join(out)
assert len(re.findall(r'^## \d{2}\.',doc,re.M))==19
for r in rows:
 b=r['body_markdown'];assert 'VIP8401' in b and all(u in b for u in [PHYS,M20,M45])
 assert '_45_minSports' not in b and '/book/services/' not in b and 'OBLACCESS55' not in b
 assert b.count('**')==2 and '{{' not in b and '[Insert' not in b
 assert b.count('£4.99')==1
 assert 'Feel free to share the link and code with colleagues too, each person gets one free session.' in b
(P/'19-prioritetnih-poruka-za-pregled.md').write_text(doc,encoding='utf-8')
(P/'19-prioritetnih-poruka-za-pregled.json').write_text(json.dumps({'status':'owner_review_only_no_sends_or_schedules','read_at':F['captured_at'],'count':19,'drafts':rows},ensure_ascii=False,indent=2),encoding='utf-8')
main=P/'prijedlog-akcija-za-odobrenje.md'
t=main.read_text(encoding='utf-8')
start='<!-- nineteen-drafts-start -->';end='<!-- nineteen-drafts-end -->'
block=f'{start}\n## Dopuna za Miju: 19 potpunih prijedloga poruka\n\nZa svih 19 leadova kojima predlažemo novu prioritetnu opciju ponovno su pročitane niti ({stamp}, Zagreb) i pripremljene konkretne poruke na engleskom. [Otvori 19 poruka za pregled](./19-prioritetnih-poruka-za-pregled.md). Uključeni su aktualni partnership linkovi, VIP8401, razlika između usluga i napomena za svaku personu/primatelja. To su lokalni prijedlozi: ništa nije poslano, zakazano niti spremljeno kao bulk draft u aplikaciji. Ova dopuna zamjenjuje ranije kratke primjere za tih 19; ostali leadovi ostaju u izvornom planu.\n{end}'
if start in t:t=t[:t.index(start)]+block+t[t.index(end)+len(end):]
else:
 first=t.index('\n');t=t[:first+1]+'\n'+block+'\n'+t[first+1:]
main.write_text(t,encoding='utf-8')
print('Prepared and verified 19 local drafts; refreshed existing review document; no live mutations.')
