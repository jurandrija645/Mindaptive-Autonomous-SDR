"""Build the owner's review document. Reads snapshots; writes artifacts only."""
import json,pathlib,re,collections
from email.utils import parseaddr
from datetime import datetime
from zoneinfo import ZoneInfo
P=pathlib.Path(__file__).resolve().parent
doc=P/'prijedlog-akcija-za-odobrenje.md'
backup=P/'prijedlog-akcija-prije-klinika-2026-10-22.md'
if not backup.exists():backup.write_text(doc.read_text(encoding='utf-8'),encoding='utf-8')
old=backup.read_text(encoding='utf-8')
J=json.loads((P/'prijedlog-akcija-za-odobrenje.json').read_text(encoding='utf-8'))
E=json.loads((P/'clinic-review-evidence.json').read_text(encoding='utf-8'))
F=json.loads((P/'clinic-review-refresh-2026-10-23.json').read_text(encoding='utf-8'))
R={r['key']:r for r in json.loads((P/'records.json').read_text(encoding='utf-8'))}
G=json.loads((P/'clinic-postcode-coordinates.json').read_text())
sets={
 'P':{6,8,9,11,12,17,18,19,20,23,24,27,31,33,34,37,39,45,46},
 'K':{14,15,38},
 'U':{2,3,5,16,40,41,43},
 'O':{21,22,25,30,36,47,48},
 'N':{1,7,10,13,26,28,29,32,35,42},
 'L':{4,44,49},
}
labels={'P':'Ponuditi prioritetnu kao dodatnu opciju','K':'Zadržati već spomenutu prioritetnu','U':'Prvo potvrditi lokaciju ili okolnosti','O':'Samo ako prihvaća dodatni put','N':'Zadržati praktičniju postojeću lokaciju','L':'Pitati koji dio Londona odgovara'}
assert set.union(*sets.values())==set(range(1,50)) and sum(map(len,sets.values()))==49
overrides={
 4:'Prvo odgovoriti što fizioterapijska ponuda uključuje; zatim pitati koji dio Londona mu odgovara. Ne ponavljati Moorgate kao navodno blizu ureda.',
 5:'Ispraviti staru lokaciju bez izmišljanja izvora podataka. Tek zatim ponuditi Moorgate uz Farringdon. Martyn radi ponedjeljak–četvrtak, zato ovu poruku planirati za ponedjeljak.',
 8:'Aldgate East je dobra londonska alternativa; u rečenici uvjetovati dolazak iz londonskog ureda jer tvrtka ima i Epping.',
 11:'Ponuditi Aldgate East prema sadašnjem službenom sjedištu, uz pitanje odgovara li mu. Ne ponavljati staru priču o Shoreditchu. Bez individualnih vježbi u prodajnom emailu.',
 12:'Prvo pomoći s kodom i rezervacijom. City of London je znatno bliže; Moorgate dodati samo kao izbor za 45-minutnu sportsku masažu, bez prisilne promjene.',
 13:'Zadržati Victoriju. Prema adresama ured i klinika su na 25 Wilton Road; dodatni put do Waterlooa ne bih prodavao kao prednost.',
 14:'Zadržati Moorgate i traženu fizioterapijsku procjenu. Sportska masaža može biti izbor ako je želi; ne zamijeniti procjenu masažom.',
 15:'Moorgate je već u razgovoru. Zadržati fizioterapiju koju je tražio; ne tvrditi da je Moorgate najbliži kad je Clerkenwell bliži po izračunu.',
 16:'Prvo pitati je li se vratila u London i koji joj dio grada odgovara. Moorgate navesti samo uvjetno, ako koristi ured u Scrutton Streetu.',
 17:'Bank je gotovo uz ured; prvo razjasniti booking fee. Moorgate ponuditi samo zbog dodatnog izbora sportske masaže od 45 minuta, nikako kao bližu kliniku.',
 24:'Aktualna tvrtka i ured su Indicium, ne stari Mesh-AI. Moorgate je razumna alternativa Liverpool Streetu. Zadržati fizioterapiju kao prvi izbor za njegov upit o stopalu/Ahilovoj tetivi.',
 27:'Waterloo na Lower Marshu ponuditi kao dodatnu opciju, uz Blackfriars. Prvo zadržati njegov interes za fizioterapiju nakon planinarenja; ne pretvoriti poruku u generički massage pitch.',
 29:'Uvažiti novu Britannia Street lokaciju i zadržati Kings Cross. Ne ponavljati Holborn iz prvog cold emaila niti gurati Moorgate udaljen oko 2 km zračno.',
 30:'Lucie sama navodi Victoriju i bolove. Zadržati Victoriju kao prvi izbor; Waterloo samo ako joj ruta ili želja za 45-minutnom sportskom masažom to čini praktičnim.',
 31:'Moorgate navesti samo ako joj/njemu odgovara dodatni put; konkretno Harryju prvo ponuditi fizioterapiju za oporavak gležnja. Ne predstavljati sportsku masažu kao zamjenu za rehabilitaciju.',
 32:'Zadržati razgovor o Blackfriarsu i poslovnoj ponudi. Ne obećavati novi postotni popust. Waterloo se može razmotriti tek nakon potvrde polazne lokacije i interesa; nema dovoljno dokaza za preciznu udaljenost.',
 34:'Dobar kandidat za prvi test: ponuditi Moorgate kao dodatnu opciju prema uredu na Featherstone Streetu; ta je prioritetna klinika i najbliža među izračunatima.',
 35:'Zadržati Victoriju. Prije bilo kakvog testa provjeriti stvarnu personu i HTML potpis zbog povijesne neusklađenosti u niti.',
 40:'Najprije potvrditi dolazi li iz Saffron Hilla, jer službeni kontakt više ne navodi stari ured u Shoreditchu. Ako da, Moorgate ponuditi kao alternativu Farringdonu, bez tvrdnje da je bliži.',
 41:'107 Cheapside je samo registered office. Ne pisati da smo blizu njegova ureda. Pitati koji dio Londona koristi; tek ako potvrdi Cheapside, ponuditi Moorgate uz Bank.',
 43:'High Street Kensington oko 2,4 km i West Kensington oko 2,7 km zračno od potvrđenog ureda. To nije dokaz praktične pješačke blizine. Ponuditi oba samo ako mu odgovaraju ruta ili osobna preferencija; inače pitati za područje.',
 44:'Razgovor voditi s predstavljenim Tomom uz postojeći To/Cc, ne Dagu slati osobni booking. Tom treba potvrditi dio Londona; Primrose Hill iz starog maila nije dokaz njegove lokacije.',
 45:'Ponuditi kratku informaciju za people tim: Moorgate kao dodatna opcija za kolege, Aldgate East kao drugi izbor samo ako im odgovara. Ne pitati Digbyja da osobno rezervira.',
 46:'Za londonski Slack predložiti Moorgate kao dodatni izbor uz Shoreditch. Pitati je li bilo odaziva; ne prodavati osobni tretman Alexu koji je rekao da ga ne treba.',
 47:'Holborn je bliže. Kolegi ponuditi Moorgate samo ako mu dodatni put odgovara; potvrditi njegovu praktičnu lokaciju preko Nadije, bez dodavanja novog kontakta.',
 48:'Za tim zadržati Blackfriars/Bank kao praktične opcije. Moorgate može biti dodatna mogućnost za 45-minutnu sportsku masažu, uz jasno pitanje odgovara li kolegama.',
 49:'Pitati želi li još predstaviti kontakte i koji dio Londona njima odgovara. Ne koristiti EC1 ured kao dokaz njezine osobne blizine i ne tražiti kućnu adresu.',
}
overrides[31]=overrides[31].replace('joj/njemu','mu')
team={x['key'] for x in J['groups']['B_team_followups']}
replies={x['key'] for x in J['groups']['A_replies']}
def km(x):return f"{x:.1f}".replace('.',',')
def names(ids):return ', '.join(r['name'] for r in E['rows'] if r['ordinal'] in ids)
def emit(s=''):lines.append(s)
lines=[]
emit('# OneBodyLDN: 49 leadova, preporuke klinika i plan za pregled')
emit('\n**Verzija 23.10.2026.** Svježe pročitana 72 relevantna razgovora u **09:42 po Zagrebu / 08:42 u Londonu**. Ovaj dokument zadržava istih 49 leadova iz prethodnog plana: **5 odgovora + 44 follow-upa**, među njima 6 za timove/preporuke. Svih 49 niti nema nove poruke u odnosu na prethodni pregled. Lokacije ureda istražene su 23.10.; to ne potvrđuje osobnu prisutnost u uredu.')
emit('\n**Za pregled, bez izvršenja.** Nisam slao, zakazivao ni stvarao bulk draftove, mijenjao statuse ili kontakte. Automatsko slanje je u svježoj provjeri isključeno, a zakazanih poruka je nula. Nakon tvog pregleda prvo slijedi zasebno odobrenje za test 1–2 poruke, zatim tvoja provjera i tek onda zasebno odobrenje za ostatak.')
emit('\n## Što bih odabrao')
emit('\n**22 dobra lokacijska kandidata**: 19 leadova kojima bih ponudio prioritetnu kliniku kao novu opciju i 3 kojima bih zadržao već spomenuti Moorgate. To nisu 22 potvrđene rezervacije niti 22 osobe kojima je ta klinika najbliža. Često je postojeća klinika bliže; dodatna vrijednost je izbor 45-minutne sportske masaže.')
emit('\n| Odluka za pregled | Broj | Imena |\n|---|---:|---|')
for g in sets:emit(f"| {labels[g]} | {len(sets[g])} | {names(sets[g])} |")
emit('\nNajbolji prvi izbori za punjenje prioritetnih klinika: **Dan Moore, Garrett Dearey i Dylan Wanigasekera za Moorgate; Nasir Jan za Aldgate East.** U sva četiri slučaja ta je prioritetna klinika i najbliža među izračunatim klinikama. Andrew Macharg je dobar kandidat za dodatnu opciju Waterloo. Nitko iz ovog skupa nema dovoljno potvrđen dokaz blizine za automatsko usmjeravanje u Wimbledon, Hendon, Mill Hill, Southfields ili Twickenham. Za Kensington je Rory uvjetni kandidat, ne potvrđena blizina.')
emit('\n## Što zapravo nudimo')
emit('\n| Usluga | Gdje vrijedi | Kako je predstaviti |\n|---|---|---|\n| Fizioterapijska procjena i tretman, 45 min | Svih 43 lokacije | Prvi izbor za postojeće physio upite; £4.99 booking fee. |\n| Sportska masaža, 20 min | Svih 43 lokacije | Kraća opcija ako to osoba želi. Naknada za booking nije potvrđena. |\n| Sportska masaža, 45 min | Samo 10 prioritetnih klinika | Dodatni izbor zbog kojeg može imati smisla druga lokacija. Naknada za booking nije potvrđena. |')
emit('\nDeset prioritetnih klinika su **Wimbledon, Aldgate East, Hendon, High Street Kensington, Mill Hill, Moorgate, Southfields, Twickenham, Waterloo i West Kensington**. Ne bih ih zvao klinikama s više slobodnih termina jer raspoloživost nije provjerena. Ne bih uvodio naziv „fizioterapeutska masaža”: potvrđena ponuda razlikuje fizioterapiju i sportsku masažu. Kod Harryja, Louise, Stevea i drugih s konkretnim tegobama ne mijenjamo traženu fizioterapiju masažom radi kampanje.')
emit('\n| Prioritetna klinika | Potvrđena adresa u internom popisu |\n|---|---|')
for c in E['clinics']:
 if c['priority']:emit(f"| {c['name']} | {c['address']} |")
emit('\nLinkovi koje bih koristio u odobrenim porukama: [fizioterapija 45 min](https://onebodyldn.connect.tm3app.com/book/partnerships/physiotherapy_1/physiotherapy_assessment_treatment_45_min), [sportska masaža 20 min](https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_20_min), [sportska masaža 45 min u prioritetnim klinikama](https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_45_min). To su aktualni linkovi iz uputa; u ovom pregledu nisam testirao checkout ni stvarao rezervaciju. Ne dodavati sva tri linka svima: izbor prilagoditi pitanju osobe.')
emit('\n**VIP8401** vrijedi za sva tri izbora, uz jednu besplatnu sesiju po osobi ukupno. Novi mailovi koriste aktualne partnership linkove, ne stari OBLACCESS55 ni 55-minutnu ponudu. Pri predaji linka/koda uključiti: “Feel free to share the link and code with colleagues too, each person gets one free session.” Ne dodavati upozorenja o naplati ponovnih rezervacija.')
emit('\nIzvori ponude i adresa: [booking-options.md](../../clients/onebodyldn/knowledge/booking-options.md) i [locations.md](../../clients/onebodyldn/knowledge/locations.md). Postojeća lokacija ostaje izbor; prema tvojoj novoj uputi predlažemo dodatnu prioritetnu kliniku kad to ima smisla.')
emit('\n## Kako čitati procjenu blizine')
emit('\nAdresa iz odgovora osobe ima prednost pred starim cold emailom i automatskim research sažetkom. Aktualni službeni kontakt tvrtke pokazuje ured tvrtke, ali ne dokazuje gdje osoba radi svaki dan. Registered office sam po sebi nije dokaz radnog ureda. Druge poslovnice navodim samo gdje postoji dokaz; nisam pretpostavljao privatne adrese ni putovanja na posao.')
emit('\nUdaljenosti su **zaokružene zračne udaljenosti između centara poštanskih brojeva**, izračunate pomoću [Postcodes.io / ONSPD](https://postcodes.io/docs/api/lookup-postcode/). Nisu pješačke rute ni minute hoda, i ne smiju se prepisivati u email kao takve. Prag oko 1,2 km služi samo za početni odabir; osobna praktičnost i izričita preferencija imaju prednost. Za Romelijin EC2M 4PL i Holborn WC1X 8WB API vraća povijesne koordinate ugašenih poštanskih brojeva putem [terminated lookup](https://postcodes.io/docs/api/lookup-terminated-postcode/); to je označeno kao orijentacijska procjena. Za četiri osobe bez radne lokacije i Laylu bez primarno potvrđenog postcodesa nema brojčane procjene.')
emit('\n## Pregled svakog od 49 leadova')
emit('\nStatusi ispod su iz čitanja 23.10.2026. Sadržaj „sljedeći korak” je preporuka, nije poslana poruka. Adresa za odgovor mora doći iz svježe niti, a ne samo iz uvoznog emaila prikazanog uz ime.')
for r in E['rows']:
 i=r['ordinal'];k=r['key'];g=next(g for g,ids in sets.items() if i in ids)
 company=R[k]['export'].get('company_name') or R[k]['state'].get('company') or ''
 status='Awaiting your reply' if k in replies else 'Follow-up due'
 original=[]
 for c in E['clinics']:
  if any(re.search(r'\b'+re.escape(c['name'])+r'\b',m['text'],re.I) for m in R[k]['messages'] if m['kind']=='sent'):original.append(c['name'])
 r['review_group']=g;r['review_action']=labels[g];r['thread_clinics']=original
 r['specific_clinic_recommendation']=overrides.get(i,'')
 emit(f"\n### {i:02d}. {r['name']} · {company}")
 emit(f"\n**{status} · {labels[g]}**"+(' · tim/preporuke' if k in team else ''))
 inbound=[m for m in F['threads'][k] if m['kind']=='reply']
 actual=parseaddr(inbound[-1].get('sender') or '')[1] if inbound else ''
 emit(f"\n**Kontakt:** {r['email']}"+(f"; stvarni odgovor dolazi s {actual}" if actual and actual.lower()!=r['email'].lower() else '')+'.')
 source=f"[službeni izvor]({r['source_url']})" if r['source_url'] else ('odgovor/potpis u niti' if r['postcode'] or i==32 else 'izričita poruka leada')
 emit(f"\n**Lokacija i dokaz:** {r['address']}"+(f", {r['postcode']}" if r['postcode'] else '')+f". {source}. {r['evidence_note']}")
 confidence=('Niska za osobnu lokaciju; nema potvrđenog polazišta.' if i in {4,16,32,41,42,44,49} else 'Srednja: postoji poslovna adresa, ali treba potvrditi odgovarajući ured/aktualne okolnosti.' if i in {2,3,5,8,36,40} else 'Visoka za navedenu poslovnu adresu; osobni dolazak iz tog ureda nije potvrđen.')
 r['location_confidence']=confidence
 emit(f'\n**Pouzdanost:** {confidence}')
 if r.get('nearest_priority'):
  n=r['nearest_priority'][0];a=r['nearest_any'][0]
  emit(f"\n**Usporedba:** prioritetna **{n['name']} ≈ {km(n['km'])} km**; najbliža među izračunatima **{a['name']} ≈ {km(a['km'])} km**. U niti: {', '.join(original) or 'nije pouzdano imenovana klinika'}."+(' Poštanski broj ureda ima povijesne koordinate; bez tvrdnje o minutama hoda.' if G[r['postcode']].get('coordinate_source') else ''))
 else:emit(f"\n**Usporedba:** nema pouzdane brojčane procjene. U niti: {', '.join(original) or 'nije pouzdano imenovana klinika'}; to nije dokaz aktualne blizine.")
 emit(f"\n**Sljedeći korak:** {r['recommendation']}")
 if i in overrides:emit(f"\n**Prijedlog klinike:** {overrides[i]}")
 elif g in {'P','K'}:
  n=r['nearest_priority'][0]['name'];emit(f"\n**Prijedlog klinike:** {'Zadržati' if g=='K' else 'Ponuditi'} {n} ako mu/joj odgovara dolazak. Spomenuti izbor između fizioterapije i sportske masaže od 45 minuta, uz postojeću lokaciju kao alternativu. Bez tvrdnje da je nova klinika bliža ili da ima slobodnih termina.")
 elif g=='U':emit('\n**Prijedlog klinike:** Moorgate navesti tek uvjetno nakon potvrde polazne lokacije. Za sada ne koristiti tvrdnju „blizu vašeg ureda”.')
 elif g=='O':emit(f"\n**Prijedlog klinike:** {r['nearest_priority'][0]['name']} ponuditi samo ako mu/joj dodatni put odgovara zbog izbora 45-minutne sportske masaže. Ne zamijeniti praktičniju kliniku automatski.")
 elif g=='N':emit('\n**Prijedlog klinike:** Zadržati praktičniju lokaciju iz razgovora. Nema dovoljno razloga za usmjeravanje u prioritetnu kliniku; ako samostalno traži 45-minutnu masažu, pitati koje mu/joj područje odgovara.')
 emit('\n**Tvoja odluka:** ☐ pripremi prema preporuci ☐ ostavi postojeću kliniku ☐ odgovorit ću ja ☐ preskoči')
emit('\n## Primjeri rečenica za pregled, nisu cijeli draftovi')
emit('\nOvo su dodaci postojećem razgovoru, ne isti novi pitch za svih 49. Konačni draft mora odgovoriti na prethodno pitanje, imati aktualni link/kod kad ih predaje i ispravan potpis.')
examples=[('Dan Moore, nova opcija Moorgate','If Moorgate works for you, you can choose a 45-minute physio session or a 45-minute sports massage there. Which would you prefer?'),('Garrett / Dylan, zadržati Moorgate','Moorgate also has a 45-minute sports massage option if you’d prefer that to physio.'),('Andrew Macharg, Waterloo kao izbor','If Waterloo works for you, that’s another option alongside Blackfriars. You can choose physio or a 45-minute sports massage there.'),('Harry Ead, ostaje physio','Would Moorgate work for your physio appointment, or would you prefer Clerkenwell?'),('Alex Timmons, za tim','If Moorgate suits the team, colleagues can choose a 45-minute physio session or a 45-minute sports massage there.'),('Joshua / Tom iz Dagove niti, prvo lokacija','Which part of London would be easiest for you?')]
for title,body in examples:emit(f'\n**{title}:**\n\n> {body}')
emit('\n## Predloženi redoslijed testiranja i slanja')
emit('\n**Korak 1: sada pregled dokumenta.** Ti biraš imena, klinike i tko piše. Sam dokument ništa ne odobrava za slanje ili zakazivanje.')
emit('\n**Korak 2: test tek kad kažeš.** Predložio bih Dan Moore + Andrew Macharg: dvije različite preporuke klinika i, prema sadašnjim nitima, Kurtova i Rebeccina persona. Ako želiš samo jedan test, Dan Moore je prvi izbor. Najprije pročitati svježu nit, potvrditi To/Cc, aktivni mailbox i personu te pregledati konačni HTML s jednim izvornim potpisom. Zatim poslati samo odobreni test i stati dok ti ne provjeriš stvarno primljenu/poslanu poruku. Uspješan queue odgovor nije dokaz dostave; provjeriti nit i prikaz potpisa prije nastavka.')
emit('\n**Korak 3: tek nakon tvoje provjere testa i drugog odobrenja** pripremiti/zakazati preostale poruke. Testirani leadovi se oduzimaju od 49; ne dobivaju još jedan isti follow-up u bulku. Svaka se nit opet provjerava prije generiranja i prije slanja. Novi odgovor, rezervacija, odbijanje ili promjena dostupnosti izbacuju poruku iz redovnog slanja i vraćaju je na pregled.')
emit('\n| Grupa | Predloženi dan i ritam, London | Zagreb | Napomena |\n|---|---|---|---|\n| 1–2 odobrena testa | Petak 23.10., vrijeme nakon tvoje odluke; 10 min između testova | +1 sat | Nakon testa stati i čekati tvoju provjeru. |\n| Četiri postojeća upita: Chloe/Alex, Alistair, Craig, Joshua | Petak nakon potvrđenog testa i tvog dodatnog odobrenja; razmak oko 5 min | +1 sat | Osobni odgovori imaju prednost pred follow-upovima; samo ako još ima smisla u radnom danu. |\n| Martyn Hill | Ponedjeljak 26.10., prijedlog 09:05 | 10:05 | Navodi četverodnevni radni tjedan, pon–čet. |\n| Preostala 42 follow-upa ako odradimo oba testa | Ponedjeljak 26.10., 09:15–12:40, najviše jedna poruka svakih 5 min | 10:15–13:40 | To je globalni raspored kao gornja granica; prije toga provjeriti opterećenje i stanje stvarnih mailboxa. Ne puniti svima isti 09:00. |')
emit('\nAko odobrenje ne stigne na vrijeme u petak, propuštene stavke prebaciti na ponedjeljak u sljedeće raspoložive razmaknute slotove. Ako bude samo jedan test, ostaju 43 follow-upa; ako preskočiš leadove, broj i slotovi se smanjuju. Za odgođene kontakte i leadove na limitu ovaj raspored ne vrijedi. Poldyju možemo pisati u ponedjeljak, ali ne nudimo ponedjeljak kao njegov dogovoreni dan dolaska: naveo je utorak ili četvrtak.')
emit('\n**Promjena sata:** petak je London BST (UTC+1), Zagreb CEST (UTC+2); ponedjeljak London GMT (UTC+0), Zagreb CET (UTC+1). U aplikaciju upisivati lokalni datum uz Europe/London, a pohraniti ispravan UTC za taj dan. Ponovno korištenje petkovog UTC pomaka za ponedjeljak pomaknulo bi slanje za sat.')
emit('\n## Novi upit izvan ovih 49: Ashil Shah')
emit('\nAshil je **23.10. u 07:15 Zagreb / 06:15 London** odgovorio na već poslani email: pita može li odabrati sportsku masažu od 45 minuta i drugu kliniku blizu mjesta gdje živi. To nije novi follow-up. U zasebnom odgovoru bih potvrdio da lokacija nije ograničena na Victoriju: 45-minutna sportska masaža vrijedi u deset navedenih klinika, a 20-minutna u ostalima. Pitao bih koji mu dio Londona odgovara, bez traženja kućne adrese. Ne slati ga automatski u Victoriju jer je ona bila u staroj poruci. Ne obećavati booking fee za masažu dok nije potvrđen. Nije dodan u bulk 49 i ništa mu nije poslano u ovom pregledu.')
emit('\n## Ostali kontakti i raniji rad')
emit('\nOvaj dio ostaje kontekst za odluku, izvan 49. Prethodni audit obuhvatio je 11.160 zapisa i 942 razgovora; ranije su popravljeni statusi i vraćena 32 zainteresirana leada iz arhive. To nisu izmjene napravljene ovim lokacijskim pregledom. [Puni raniji audit](./rundown.md) ostaje sačuvan.')
support=old.split('## 1. Prvo: podrška i obećanja')[1].split('## 2.')[0]
emit('\n### Podrška i već obećane radnje'+support)
excluded=old.split('## 5. Devet leadova na limitu: tražim tvoju odluku')[1].split('## Ostalih sedam')[0]
emit('\n### Devet leadova na limitu, odgode i zaštićeni slučajevi\n\nSljedeće je sačuvan plan iz pregleda 22.10., nije uključeno u bulk 49. Prije moguće nove akcije osvježiti stanje.\n'+excluded.replace('## 6.','###').replace('## 7.','###'))
emit('\n### Drugi nedavni razgovori')
emit('\nDavid Galan, Faye Wilson, James Boal, Jody Osman, Lawrence Tatler i Sam Iddekinge ostaju izvan ove fiksne grupe 49. Njihova dospjelost može se mijenjati s vremenom; ovaj dokument nije nalog za još jedan follow-up. Ashilov novi upit opisan je odvojeno iznad.')
emit('\n## Što mi možeš vratiti nakon pregleda')
emit('\nDovoljno je navesti imena ili brojeve 01–49 i odluku: pripremiti prema preporuci, ostaviti postojeću kliniku, promijeniti tekst, odgovoriti sam ili preskočiti. Zatim, kad budeš spreman, zasebno odabireš test 1–2 poruke. Bulk slanje/scheduling čeka tvoju provjeru testova i daljnju uputu.')
emit('\n## Trag provjere')
emit('\n[Lokacije i izračuni za svih 49](./clinic-review-evidence.json) · [Svježe niti i statusi 23.10.](./clinic-review-refresh-2026-10-23.json) · [Izvorna verzija dokumenta prije ove dopune](./prijedlog-akcija-prije-klinika-2026-10-22.md) · [Raniji audit](./rundown.md). Ovo su interni dokumenti s imenima i poslovnim razgovorima; nisu materijal za slanje leadovima.')
text='\n'.join(lines)+'\n'
doc.write_text(text,encoding='utf-8')
(P/'clinic-review-evidence.json').write_text(json.dumps(E,ensure_ascii=False,indent=2),encoding='utf-8')
J['clinic_review']={'date':'2026-10-23','fixed_cohort_count':49,'no_messages_sent_or_scheduled':True,'groups':{g:{'label':labels[g],'keys':[r['key'] for r in E['rows'] if r['ordinal'] in ids]} for g,ids in sets.items()},'evidence_file':'clinic-review-evidence.json','snapshot_file':'clinic-review-refresh-2026-10-23.json','pilot_names':['Dan Moore','Andrew Macharg'],'approval_state':'owner_document_review; test_requires_explicit_instruction; bulk_requires_test_review_and_further_instruction'}
J['verified_at']=F['captured_at']
(P/'prijedlog-akcija-za-odobrenje.json').write_text(json.dumps(J,ensure_ascii=False,indent=2),encoding='utf-8')
assert len(re.findall(r'^### \d{2}\.',text,re.M))==49
for date in ['2026-10-23T09:15:00','2026-10-26T09:15:00']:
 d=datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('Europe/London'));print(d.isoformat(),'UTC',d.astimezone(ZoneInfo('UTC')).isoformat(),'Zagreb',d.astimezone(ZoneInfo('Europe/Zagreb')).isoformat())
print('Written',doc,'chars',len(text),'groups', {g:len(ids) for g,ids in sets.items()})
