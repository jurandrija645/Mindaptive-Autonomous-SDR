import pathlib,json,re
from email.utils import parseaddr
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
P=pathlib.Path(__file__).resolve().parent
F=json.loads((P/'approval-review-refresh.json').read_text(encoding='utf-8'))
TIMING=json.loads((P/'approval-timing.json').read_text())
R={r['key']:r for r in json.loads((P/'records.json').read_text(encoding='utf-8'))}
S={f"{s['campaign_id']}/{s['lead_id']}":s for s in F['states']}
V={d['key']:d for d in json.loads((P/'verified-decisions.json').read_text(encoding='utf-8'))}
for k,d in json.loads((P/'review-overrides.json').read_text(encoding='utf-8')).items():V[k].update(d)
old=json.loads((P/'bulk-proposals.json').read_text(encoding='utf-8'))['groups']
A=[x['key'] for x in old['A_odgovori']]
B=[f"{s['campaign_id']}/{s['lead_id']}" for s in F['inbox']['leads'] if s['category']=='followup']
C=[x['key'] for x in old['C_limit_potreban_odabir']]
E=[x['key'] for x in old['E_odlozeno']]
D=[x['key'] for x in old['rucna_podrska']]
covered=set(A+B+C+D+E)
RECENT=sorted(set(F['threads'])-covered)
assert len(A)==5 and len(B)==44 and len(C)==9 and len(E)==3 and len(D)==4 and len(RECENT)==7
names={'3930675/4520617891':'Joshua DiLorenzo','3930675/4520613376':'Lux Jega (Luxman Jegatheeswaran)','3930675/4520618811':'Andrew Macharg','3930675/4520615955':'Poldy / Leopold van Lynden'}
def name(k):return names.get(k,R[k]['name'])
def esc(v):return re.sub(r'\s+',' ',str(v or '')).replace('|','\\|')
def contact(k):
 imported=R[k]['email']
 inbound=[m for m in F['threads'][k] if m['kind']=='reply']
 actual=parseaddr(inbound[-1].get('sender') or '')[1] if inbound else ''
 return imported+' → odgovor: '+actual if actual and actual.lower()!=imported.lower() else imported
def stamp(k):
 t=F['threads'][k]
 return datetime.fromisoformat(t[-1]['time']).astimezone(ZoneInfo('Europe/Zagreb')).strftime('%d.%m. %H:%M')
def state(k):
 row=S[k]
 if k in E:
  date=datetime.fromisoformat(row['snooze_until']).astimezone(ZoneInfo('Europe/London')).strftime('%d.%m. %H:%M')
  return 'Odloženo do '+date+' London'
 return {'reply':'Awaiting your reply','followup':'Follow-up due','waiting':'In conversation','booked':'Meeting booked','not_interested':'Not Interested','do_not_contact':'Do Not Contact'}.get(row['category'],row.get('smartlead_category') or row['category'])
N={
'3930675/4520613046':'Zahvaliti Chloe na prosljeđivanju HR-u i ponuditi kratak sažetak za tim. Odgovoriti stvarnom pošiljatelju u postojećoj niti; ne dodavati nove kontakte.',
'3876232/4446317501':'Osobno obnoviti razgovor nakon davno završenog OOO-a i pitati treba li pomoć s rezervacijom. Pitanje o £4.99 već je odgovoreno.',
'3930675/4520616414':'Pozvati se na njegov zahtjev da se javimo nakon puta. Taj je rok prošao. Ponuditi aktualne booking detalje, bez pretvaranja da smo tek dočekali povratak.',
'3930675/4520617891':'Odgovoriti što ponuda obuhvaća prema odobrenim podacima klinike. Uvažiti da tim radi na daljinu; ne vraćati ga na netočnu priču o blizini ureda.',
'3876232/4446317376':'Odgovoriti na pitanje o izvoru lokacijskih podataka samo onim što znamo i zahvaliti na preporuci Vanesse u Firefishu. Kontaktiranje Vanesse nije dio ove akcije.',
'3876232/4446315909':'Pitati je li bilo odaziva nakon što je ponudu podijelio s oko 30 kolega. Ne pitati njega da rezervira osobnu sesiju.',
'3930675/4520616252':'Provjeriti je li kolega kojem je proslijedila ponudu uspio rezervirati. Dopuštenje za dijeljenje već je dobila.',
'3930675/4520616518':'Pitati kakav je bio odaziv tima nakon dijeljenja. Ne tretirati je kao osobu koja mora sama rezervirati.',
'3930675/4520615628':'Pratiti prosljeđivanje people timu i ponuditi sažetak koji može podijeliti. Ne ponavljati već odgovoreno pitanje o obvezama.',
'3930675/4520622428':'Obratiti se Tomu u postojećem razgovoru i provjeriti booking. Prije slanja provjeriti stvarni To/Cc da Tom ne ispadne iz niti.',
'3876232/4446317241':'Jednom pitati ima li imena kontakata koje je ponudila predstaviti. Ne slati joj generički podsjetnik za osobnu sesiju.',
'3876232/4446316027':'Pitati je li uspjela riješiti problem s kodom i rezervirati. Stari zahtjev za 23.9. je prošao; ne nuditi ga kao važeći termin.',
'3930675/4520618811':'Kratko pitati je li uspio rezervirati nakon što je dobio link i kod. Bez ponovnog predstavljanja ponude.',
'3876232/4446317381':'Uvažiti promjenjive dane u uredu i pitati želi li aktualni booking link. Ne tražiti odgovor kao da nije već pokazao interes.',
'3930675/4520621199':'Uvažiti da je bila zauzeta i pitati odgovara li joj sada pogledati termine. Ne pretpostaviti rezervaciju.',
'3930675/4520621757':'Provjeriti je li uspio napraviti sljedeći korak nakon prihvaćanja ponude. Ne ponavljati cijeli prodajni uvod.',
'3876232/4446316729':'Provjeriti je li uspio iskoristiti poslane upute za booking; ponuditi pomoć jednim jasnim pitanjem.',
'3876232/4446315693':'Odgovor vezati uz traženu dostupnost. Provjeriti treba li komunicirati s asistenticom Cascade; ne izmišljati slobodne termine.',
'3876232/4446315774':'Kratko se vratiti na njegov zahtjev za booking linkom i provjeriti je li još potreban. Potpis bez novog teksta nije nova potvrda interesa.',
'3930675/4520616471':'Provjeriti je li uspio rezervirati nakon prihvaćanja ponude. Ne slati još jedan mail koji tvrdi da je posljednji.',
'3930675/4520613855':'Osobno provjeriti je li uspio rezervirati traženu procjenu. Bez ponavljanja stare poruke o isteku ponude.',
'3930675/4520614771':'Provjeriti je li booking postupak bio jasan i je li negdje zapeo. Ne ponavljati već poslane upute bez razloga.',
'4006945/4608049691':'Pitati je li pronašla praktičnu lokaciju nakon što je rekla da će pogledati web. Ne tvrditi koja joj je klinika najbliža.',
'3876232/4446316913':'Vratiti se na njezino pitanje o lokaciji kod Kings Crossa i provjeriti je li našla praktičan termin.',
'3930675/4520621755':'Kratko provjeriti je li uspio rezervirati nakon povratka s puta. Ne pretvarati povijesno „sljedeći tjedan” u novi dogovoreni termin.',
'3930675/4520616840':'Uvažiti da je tražio kontakt u listopadu. Zadnji podsjetnik bio je 20.10.; pripremiti miran follow-up za sljedeće primjereno jutro, ne agresivan novi niz.',
'3876232/4446315434':'Provjeriti je li dobio jasnu informaciju o lokaciji i našao termin. Koristiti samo potvrđene podatke o klinikama.',
'3930675/4520619898':'Vratiti se na njegov zahtjev za više informacija i provjeriti je li još aktualno. Ne zaključiti da je nezainteresiran zbog tišine.',
'3930675/4520613005':'Pitati treba li pomoć s bookingom. Pitanje o izvoru podataka već je odgovoreno; ne izmišljati drukčije objašnjenje.',
'3930675/4520616436':'Provjeriti je li ponuda bila jasna nakon objašnjenja zašto je sesija besplatna. Bez nove priče o umjetnom isteku.',
'3876232/4446317198':'Jednim kratkim pitanjem provjeriti želi li još rezervirati prihvaćenu sesiju.',
'3930675/4520619273':'Provjeriti je li stigao pogledati termine nakon jasnog „yes please”. Ponuditi pomoć, bez cijelog ponovljenog pitcha.',
'3930675/4520614839':'Uvažiti da je najavila povratak početkom listopada i pitati odgovara li joj sada pogledati termine.',
'3930675/4520613376':'Provjeriti je li dobio sve što treba za rezervaciju. Cijena/naknada i web već su objašnjeni; ne ponavljati neodgovoreno pitanje koje zapravo ne postoji.',
'3876232/4446316648':'Provjeriti je li uspio rezervirati nakon što je tražio upute. Ako je zapeo, ponuditi aktualni link.',
'3876232/4446315522':'Nastaviti od njegova pitanja koje informacije trebamo i pitati je li potreban još neki detalj za booking.',
'3930675/4520613112':'Provjeriti je li uspio rezervirati. Ne slati individualne vježbe ili medicinske savjete u prodajnom odgovoru.',
'3930675/4520615955':'Uvažiti da je u Londonu uglavnom utorkom ili četvrtkom; pitati želi li pogledati termine tih dana, bez obećavanja dostupnosti.',
'3876232/4446317331':'Provjeriti je li pronašao vrijeme nakon što je rekao da će pogledati kalendar.',
'3930675/4520613836':'Vratiti se na njegov zahtjev da pošaljemo link i provjeriti treba li pomoć s terminom.',
'3876232/4446317384':'Provjeriti je li dobila dovoljno informacija nakon interesa za ponudu i želi li još rezervirati.',
'4006945/4608052123':'Vratiti se na njegovo „how do I book” i provjeriti je li postupak uspio. Ne tretirati ga kao novi hladni lead.',
'3876232/4446317432':'Provjeriti je li uspjela rezervirati. U prethodnom mailu pozdrav i potpis nisu usklađeni, pa prije slanja potvrditi stvarnog pošiljatelja i odgovarajući potpis.',
'3930675/4520620397':'Poslati osobni follow-up uz lokaciju o kojoj je već razgovarao. Zapeli slijed je zaustavljen; ne pokretati ga ponovno.',
'3876232/4446317574':'Provjeriti je li još zainteresiran za ranije prihvaćenu sesiju. Bez nove tvrdnje da ponuda završava ovaj mjesec.',
'3876232/4446315651':'Provjeriti je li naknada bila prepreka rezervaciji i treba li pomoć. Ne obećavati ukidanje £4.99 bez potvrde klinike.',
'3876232/4446318129':'Kratko pitati je li uspio rezervirati nakon prihvaćanja i poslanih detalja.',
'3876232/4446316752':'Provjeriti želi li još iskoristiti prihvaćenu ponudu; jedan jasan sljedeći korak.',
'3876232/4446317666':'Uvažiti pitanje o pokriću/franšizi i pitati treba li pomoć. Ne obećavati osiguravateljsko pokriće koje nije potvrđeno.',
}
team={'3876232/4446315909','3930675/4520616252','3930675/4520616518','3930675/4520615628','3930675/4520622428','3876232/4446317241'}
assert set(A+B)<=set(N),'Missing personal recommendations'
reviewtime=datetime.fromisoformat(F['captured_at']).astimezone(ZoneInfo('Europe/Zagreb')).strftime('%d.%m.%Y. u %H:%M')
lines=['# OneBodyLDN: što bih napravio i što tražim za odobrenje','',f'Provjereno **{reviewtime}**, zagrebačko vrijeme. Dokument je prijedlog za pregled; ovdje navedene poruke nisu poslane niti zakazane.','',
'## Moja preporuka','',
'Prvo bih riješio postojeće upite i obećanja. Nakon toga bih pripremio osobne follow-up draftove za dospjele leadove. Ti zatim odlučuješ koje poruke šalješ sam, koje da doradim ja i koje odobravaš za slanje. Za leadove na limitu, odložene kontakte i nejasne slučajeve ne bih pokretao novi niz.','',
'| Redoslijed | Akcija | Broj | Moj prijedlog |','|---|---|---:|---|',
'| 1 | Podrška i obećanja postojećim rezervacijama | 2 | Emily i Franek: prvo provjeriti podatke u klinici, zatim osobni odgovor. |',
'| 2 | Razgovori koji trebaju naš odgovor | 5 | Mogu ja pripremiti pojedinačne draftove; ti pregledaš prije slanja. |',
f'| 3 | Dospjeli follow-upi za pojedince | {len(set(B)-team)} | Bulk priprema personaliziranih draftova, svaki prema svojoj niti. |',
f'| 4 | Dospjeli follow-upi za timove i preporuke | {len(team)} | Zasebna grupa: pitati za odaziv tima ili predstavljanje kontakata, ne za osobni booking. |',
'| 5 | Zainteresirani na limitu četiri follow-upa | 9 | Ti odluči želiš li jedan dodatni pokušaj. Ne bih resetirao brojanje ni pokretao automatski niz. |',
'| 6 | Odloženi kontakti | 3 | Zadržati odgode i pregledati na navedeni datum. |',
'| 7 | Nejasan ili zaštićen status | 2 | Robert i Kofil: pojedinačna odluka, bez bulk kontakta. |',
'',
'## Što je već završeno','',
'Prethodni pregled obuhvatio je svih 11.160 zapisa u kampanjama i detaljno 942 razgovora pomoću DeepSeek V4 Pro. Ispravljeni su statusi, 32 zainteresirana leada vraćena su iz arhive, a popravak aplikacije je aktivan. [Detaljan audit s imenima svih pregledanih leadova](./rundown.md) i [potpuni dodatak bez odgovora](./leadovi-bez-odgovora.md) ostaju trag tog pregleda.','',
'Sada sam ponovno dohvatio i usporedio svih 72 razgovora relevantnih za odluku. Nijedan nije dobio novu poruku u odnosu na audit. U živom inboxu sada je **44 dospjela follow-upa i pet razgovora koji čekaju naš odgovor**. Jeremy Robinson sada je također dospio prema trenutno spremljenoj kadenci. Pravila u aplikaciji su **dva kalendarska dana**, **24 sata za very hot**, najviše **četiri follow-upa**, pa revival nakon **60 dana**. Postavke u ovom nastavku nisu mijenjane.','',
'Automatsko slanje je isključeno. Zakazanih poruka nema. U ovom nastavku nisam mijenjao lead statuse, pokretao bulk draftove ili slao poruke.','',
'## 1. Prvo: podrška i obećanja','',
'| Lead | Zašto je prvi | Što bih napravio | Tko treba potvrditi podatke |','|---|---|---|---|',
'| Emily Knox | Pitala je kako pomaknuti postojeći termin i nije mogla pronaći rezervaciju na računu. | Provjeriti aktualan termin i odgovoriti s točnim postupkom. Povijesni datum iz maila ne nuditi kao novi termin. Rezervaciju ostaviti zaključanu za prodajni follow-up. | Ti ili klinika; ja mogu zatim složiti odgovor. |',
'| Franek Buczkowski | Rezervirao je, podijelio ponudu s kolegama, a mi smo obećali provjeriti broj njihovih rezervacija. | Dohvatiti stvarne brojke i ispuniti obećanje. Ne pitati njega da opet rezervira niti izmišljati broj novih klijenata. | Ti ili klinika; ja mogu pripremiti poruku iz potvrđenih podataka. |',
'',
'## 2. Pet razgovora koji čekaju naš odgovor','',
'Predlažem da za ovih pet prvo pripremim draftove koje možeš pregledati. Slanje bih ostavio za tvoju zasebnu odluku.','']
def table(keys,recommendations=N):
 out=['| Lead i email | Trenutni status | Zadnja poruka u niti, Zagreb | Što bih konkretno napravio |','|---|---|---|---|']
 for k in sorted(keys,key=lambda k:name(k).lower()):out.append('| '+' | '.join(map(esc,[name(k)+' · '+contact(k),state(k),stamp(k),recommendations[k]]))+' |')
 return out
lines+=table(A)
lines+=['','## 3. Priprema follow-upova: 38 pojedinaca','',
'Ovdje predlažem **bulk pripremu pojedinačnih draftova**, bez automatskog slanja. Svaki draft mora uzeti u obzir što je već poslano i postaviti jedno smisleno sljedeće pitanje. Slanje linka i koda ne znači da je osoba rezervirala; tišina ne znači odbijanje. Ne bih slao još jednu identičnu poruku „this is my last email”.','']+table(set(B)-team)
lines+=['','## 4. Šest follow-upova za timove i preporuke','',
'Ovu bih grupu pripremio odvojeno. Cilj je odaziv kolega ili obećani kontakt, a ne pretvaranje svakog posrednika u osobnog pacijenta.','']+table(team)
lines+=['','## 5. Devet leadova na limitu: tražim tvoju odluku','',
'Prije bilo kakve pripreme iznad limita odlučio bih za svako ime ima li smisla još jedan osobni pokušaj. Ako ga odobriš, to bi bio izuzetak za konkretan lead, ne reset brojača ili novi niz. Revival nakon 60 dana ostaje postojeće pravilo.','']
capnotes={k:'Razmotriti jedan osobni pokušaj s aktualnom ponudom, samo ako ga posebno odobriš. Ne bih pokretao novi niz.' for k in C}
capnotes.update({
'3876232/4446315820':'Carolineina asistentica Vania pitala je za £4.99 i dobila objašnjenje. Ako odobriš izuzetak, provjeriti je li Caroline sada uspjela rezervirati; pisati stvarnoj sugovornici uz ispravan To/Cc.',
'3876232/4446317153':'Beth je već pitala je li £4.99 očekivana naknada. Ako odobriš, napraviti osobni follow-up oko te prepreke, bez obećanja besplatne rezervacije.',
'3876232/4446315515':'Prije prodajnog podsjetnika provjeriti je li spomenuti termin u kalendaru za 29.9. bio stvarna rezervacija. Ako jest, ne slati prodajni follow-up.',
'3876232/4446317001':'Ako odobriš, kratko provjeriti je li još aktualan interes. Ne davati individualne programe pripreme za sportska natjecanja.',
})
lines+=table(C,capnotes)
lines+=['','## 6. Tri odložena kontakta: ništa ne bih slao sada','']
laternotes={
'3930675/4520617893':'Pregled 26.10., nakon mjesečnog prozora koji je tražila. Tada provjeriti je li i dalje potreban follow-up; datum je odgoda pregleda, ne zakazano slanje.',
'3876232/4446316050':'Pregled 29.10., nakon najmanje osam tjedana odsutnosti koje je najavio. Rekao je da će se sam javiti; prvo procijeniti treba li poruka.',
'3930675/4520612744':'Pregled 16.11. služi kao naš podsjetnik. Točan povratak nije potvrđen. Ne pisati sada niti tvrditi da je datum povratka dogovoren.',
}
lines+=table(E,laternotes)
lines+=['','## 7. Dva slučaja koja ne bih uključio u bulk','',
'| Lead | Trenutno | Moja odluka do tvog pregleda |','|---|---|---|',
'| Kofil Ali · kofil@journeyrecruitment.co.uk | Zaštićeni Lead Opted Out. Postoji i stvaran problem s rezervacijom u niti. | Prvo razjasniti status i je li kontakt primjeren. Ne bih ga odblokirao ni slao poruku kao dio bulk grupe. Email provjeriti iz zapisa ispod. |',
'| Robert Tynan · rt@morph.fit | Nema jasne potvrde interesa; odgovor je samo ime Kurt i potpis. | Ne bih ga pribrojio zainteresiranima samo zato što smo mi poslali link. Ti odluči treba li zaseban kontakt. |',
'',
'## Ostalih sedam relevantnih leadova: još nisu za novi follow-up','',
'Njima je već poslan nedavni odgovor. Zadržao bih postojeću kadencu i ponovno provjerio razgovor prije pripreme poruke.','']
recentnotes={k:'Zadnji mail je naš i još nije dospjela nova poruka prema spremljenoj kadenci. Pričekati; ne duplicirati već poslan odgovor.' for k in RECENT}
lines+=table(RECENT,recentnotes)
lines+=['','## Pravila za draftove koje bih pripremio nakon odobrenja','',
'- Novi booking detalji moraju slijediti aktualnu OneBodyLDN ponudu: partnership linkovi, VIP8401 i potvrđena £4.99 naknada za physio. Ne kopirati staru 55-minutnu ponudu kao novu.',
'- Ne pretpostavljati da lead još ima pravo na novu besplatnu sesiju ako je već iskoristio jednu. Dijeljenje s kolegama vrijedi uz jednu besplatnu ponudu po osobi ukupno.',
'- Odgovarati stvarnom sugovorniku iz niti i sačuvati potrebni To/Cc i ispravnu personu. Posebno provjeriti Chloe, Toma, Vaniu, Cascade i razgovor sa Sarah.',
'- Ne izmišljati slobodne termine, točnu udaljenost klinike, pokriće osiguranja, broj rezervacija ili izvor podataka.',
'- Neposredno prije pripreme i ponovno prije slanja provjeriti je li lead u međuvremenu odgovorio, rezervirao ili odbio kontakt.',
'',
'## Što mi možeš odobriti','',
'Predlažem prvu odluku: **pripremiti pet osobnih odgovora i 44 follow-up drafta za pregled, bez slanja**. Unutar tih 44, šest je za timove i preporuke. Emily i Franek čekaju potvrđene podatke klinike. Devet leadova na limitu, tri odložena te Kofil i Robert ostaju izvan te pripreme.','',
'Ako želiš dio odgovoriti sam, dovoljno je navesti imena ili cijelu grupu. Slanje nije uključeno u prijedlog pripreme draftova.','',
'Adresa uz ime prikazuje uvozni zapis. Kad stvarni odgovor dolazi s druge adrese, označen je s „→ odgovor”. Za slanje bih koristio stvarnog sugovornika iz niti, uz provjeru To/Cc.','',
'## Trag pregleda','',
'[Raniji puni audit i registar 942 razgovora](./rundown.md) · [Preostali zapisi bez odgovora](./leadovi-bez-odgovora.md) · [Svježa provjera razgovora i statusa](./approval-review-refresh.json) · [Aktualna kadenca](./approval-timing.json)','']
# Include source addresses for the two support cases too.
for i,line in enumerate(lines):
 if line.startswith('| Emily Knox |'):
  lines[i]=line.replace('| Emily Knox |','| Emily Knox · '+contact('3930675/4520622245')+' |',1)
 if line.startswith('| Franek Buczkowski |'):
  lines[i]=line.replace('| Franek Buczkowski |','| Franek Buczkowski · '+contact('3876232/4446316604')+' |',1)
# Use authoritative record values, never an inferred address for protected cases.
for i,line in enumerate(lines):
 if line.startswith('| Kofil Ali ·'):
  k='3876232/4446316573';lines[i]='| '+esc(name(k)+' · '+contact(k))+' | '+esc(S[k].get('smartlead_category') or state(k))+'. U niti postoji stvaran problem s rezervacijom. | Prvo razjasniti status i je li kontakt primjeren. Ne bih ga odblokirao ni slao poruku kao dio bulk grupe. |'
(P/'prijedlog-akcija-za-odobrenje.md').write_text('\n'.join(lines),encoding='utf-8')
manifest={'status':'for_owner_review_not_executed','verified_at':F['captured_at'],'counts':{'responses':5,'followups':44,'team_followups_included':6,'capped_excluded':9,'snoozed_excluded':3,'pending_recent':7,'special_review':4},'recommended_first_approval':'Prepare 5 replies and 44 personalized follow-up drafts for review. Do not send.','groups':{g:[{'key':k,'name':name(k),'email':R[k]['email'],'recommendation':notes[k]} for k in keys] for g,keys,notes in [('A_replies',A,N),('B_individual_followups',list(set(B)-team),N),('B_team_followups',list(team),N),('C_capped_excluded',C,capnotes),('E_deferred',E,laternotes),('recent_not_due',RECENT,recentnotes)]}}
(P/'prijedlog-akcija-za-odobrenje.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
assert set(A+B+C+D+E+RECENT)==set(F['threads'])
text=(P/'prijedlog-akcija-za-odobrenje.md').read_text(encoding='utf-8')
for key in F['threads']:assert R[key]['email'] in text,key
for target in re.findall(r'\]\(\./([^\)]+)\)',text):assert (P/target).exists()
print('Approval document complete. Every one of 72 relevant leads included; 5 replies + 44 follow-ups proposed, none executed.')
