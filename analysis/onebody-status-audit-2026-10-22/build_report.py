import collections,json,pathlib,re
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
P=pathlib.Path(__file__).resolve().parent
S=json.loads((P/'snapshot.json').read_text(encoding='utf-8'))
A=json.loads((P/'final-audit.json').read_text(encoding='utf-8'))
LIVE=json.loads((P/'live-verification.json').read_text(encoding='utf-8'))
R={r['key']:r for r in json.loads((P/'records.json').read_text(encoding='utf-8'))}
PLAN={r['key']:r for r in json.loads((P/'plan.json').read_text(encoding='utf-8'))}
RESULT={r['key']:r for r in A['results']}
ST={f"{r['campaign_id']}/{r['lead_id']}":r for r in A['states']}
INBOX={f"{r['campaign_id']}/{r['lead_id']}":r for r in A['inbox']}
V={r['key']:r for r in json.loads((P/'verified-decisions.json').read_text(encoding='utf-8'))}
for k,d in json.loads((P/'review-overrides.json').read_text(encoding='utf-8')).items():V[k].update(d)
LABEL={'reply':'Awaiting your reply','followup':'Follow-up due','waiting':'In conversation','booked':'Meeting booked','auto_reply':'Auto-reply','not_interested':'Not Interested','wrong_person':'Wrong Person','do_not_contact':'Do Not Contact','bounced':'Bounced'}
TODAY=datetime.fromisoformat(A['completed_at'])
def esc(t):return re.sub(r'\s+',' ',str(t or '')).replace('|','\\|')
def display(key):
 r=R[key];st=ST.get(key) or r.get('state') or {}
 for n in [st.get('email_display_name'),st.get('name'),r['name']]:
  if n and ' ' in n.strip():return n.strip()
 return r['name'] or r['email']
def status(key):
 st=ST.get(key)
 if st:
  if st.get('snooze_until'):
   try:
    dt=datetime.fromisoformat(st['snooze_until']);dt=dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    if dt>TODAY:return 'Odloženo do '+dt.astimezone(ZoneInfo('Europe/London')).strftime('%d.%m.%Y. %H:%M')+' London'
   except ValueError:pass
  return LABEL.get(st.get('category'),st.get('smartlead_category') or st.get('category') or 'Bez statusa')
 return 'Smartlead: '+(R[key]['export'].get('category') or 'Bez kategorije')+'; izvan lokalnog inboxa'
def before(key):
 st=R[key].get('state') or {};name=LABEL.get(st.get('category'),st.get('category') or 'Bez zapisa u aplikaciji')
 provider=R[key]['export'].get('category') or st.get('smartlead_category')
 return name+(' / '+provider if provider and provider!=name else '')+(' / arhiva' if st.get('archived_at') else '')
def changed(key):
 if key not in RESULT:return 'Bez promjene u ovom auditu'
 x=RESULT[key];old=x.get('before_apply') or {};new=ST.get(key) or x.get('after') or {};parts=[]
 if x.get('provider_changed'):parts.append('Smartlead → '+('Meeting Booked' if x['target']=='booked' else 'Interested')+'; kampanjski niz pauziran')
 if old.get('archived_at') and not new.get('archived_at'):parts.append('vraćen iz arhive')
 if old.get('category')!=new.get('category') or old.get('status')!=new.get('status'):parts.append('ispravljen lokalni status')
 if old.get('snooze_until')!=new.get('snooze_until') and new.get('snooze_until'):parts.append('spremljena odgoda pregleda')
 if x.get('retired_drafts'):parts.append('zastarjeli draft '+','.join(map(str,x['retired_drafts']))+' → stale')
 if x.get('stopped_error_enrollments'):parts.append('zaustavljen zapeli error upis u slijed')
 return '; '.join(parts) or 'Provjeren i osvježen točan status i sažetak'
def proposal(key):
 d=V.get(key) or {};x=RESULT.get(key) or {};target=x.get('target')
 if target=='followup':
  if d.get('bulk_group')=='owner_review':return d.get('next_action_hr') or 'Ručno provjeriti prije slanja.'
  if d.get('bulk_group') in ['followup_general','reply_referral']:return d.get('next_action_hr') or 'Osobni follow-up na ponudu ili preporuku, za odobrenje.'
  return 'Pripremiti osobni podsjetnik za booking, prema zadnjem razgovoru. Provjeriti treba li pomoć; aktualne linkove i VIP8401 dati prema potrebi, uz £4.99 za physio i pravilo jedne besplatne ponude po osobi.'
 if target=='reply':return d.get('next_action_hr') or 'Pripremiti odgovor na zadnju ljudsku poruku, za odobrenje.'
 if key in PLAN and 'capped' in PLAN[key]['reason']:return 'Bez automatskog follow-upa: već su poslana četiri. Odobriti ili odbiti jedan osobni pokušaj ponovnog kontakta; brojanje i limit nisu resetirani.'
 return d.get('next_action_hr') or 'Bez bulk slanja.'

due=sorted([k for k,x in RESULT.items() if x['target']=='followup'],key=lambda k:display(k).lower())
replies=sorted([k for k,x in RESULT.items() if x['target']=='reply'],key=lambda k:display(k).lower())
capped=sorted([k for k,x in PLAN.items() if x.get('target')=='waiting' and 'capped' in x['reason']],key=lambda k:display(k).lower())
later=[k for k,d in V.items() if d.get('snooze_review_date')]
recent=sorted([k for k,x in RESULT.items() if x['target']=='waiting' and k not in capped and k not in later],key=lambda k:display(k).lower())
assert len(due)==43 and len(replies)==5 and len(capped)==9 and len(later)==3
assert all(k in INBOX and INBOX[k]['category']=='followup' for k in due)
assert all(k in INBOX and INBOX[k]['category']=='reply' for k in replies)
assert not LIVE['scheduled']['scheduled']
restored=[k for k,x in RESULT.items() if x.get('before_apply',{}).get('archived_at') and not ST[k].get('archived_at')]
provider_changes=[k for k,x in RESULT.items() if x.get('provider_changed')]
usage={}
for pattern in ['raw-*.json','verify-*.json']:
 for file in P.glob(pattern):
  data=json.loads(file.read_text(encoding='utf-8'))
  identity=data.get('id') or file.name
  usage[identity]=(data.get('usage') or {}).get('cost') or 0
cost=sum(usage.values())
source_at=datetime.fromisoformat(S['captured_at']).astimezone(ZoneInfo('Europe/Zagreb')).strftime('%d.%m.%Y. u %H:%M')
finished=TODAY.astimezone(ZoneInfo('Europe/Zagreb')).strftime('%d.%m.%Y. u %H:%M')
lines=['# OneBodyLDN: pregled leadova i ispravak statusa','',f'Završna provjera: **{finished}**, zagrebačko vrijeme. Početni popis kampanja: {source_at}.','',
'## Rezultat','',
f'- **43 leada: Follow-up due.** Svi su provjereni i vidljivi u inboxu.',
f'- **5 razgovora: Awaiting your reply.** Imena i sljedeći koraci su odmah ispod.',
f'- **{len(restored)} zainteresirana leada vraćena iz arhive.** Samo slanje koda i linka nije zatvoren razgovor.',
f'- **{len(provider_changes)} Smartlead kategorije ažurirane i neovisno pročitane natrag.** Kod ponovnog otvaranja kampanjski niz je pauziran; novi slijed nije pokrenut.',
'- **Franek Buczkowski: Meeting Booked**, na temelju njegove izričite potvrde rezervacije.',
'- **3 leada odložena** za kasniji ručni pregled; to nisu zakazani mailovi.',
'- **9 zainteresiranih leadova ostaje na limitu od četiri follow-upa.** Limit i brojanje nisu mijenjani; zaseban prijedlog je ispod.',
'- Nijedan mail nije poslan ni zakazan u ovom postupku. Automatsko slanje ostaje isključeno.',
'',
'## Što je obuhvaćeno','',
'Provjeren je popis svih **11.160 zapisa u šest Smartlead kampanja**, uključujući arhivu i leadove izvan lokalnog inboxa. Svih **942 razgovora s odgovorom, kategorijom ili postojećim zapisom u aplikaciji**, ukupno **3.305 poruka**, pregledao je **DeepSeek V4 Pro**. Dodatnom provjerom istog modela provjereno je 360 kandidata i potencijalnih iznimaka. Pozitivni prijedlozi provjereni su prema stvarnim porukama; pogrešne atribucije i automatske preporuke kontakata odbačene su.',
'',
'Svaki od 942 pregledana razgovora ima redak s imenom u završnom registru ovog dokumenta. Preostalih **10.218 zapisa bez evidentiranog odgovora ili kategorije** navedeno je po imenu u [dodatku bez odgovora](./leadovi-bez-odgovora.md). Nisu proglašeni zainteresiranima niti uključeni u bulk slanje. Brojevi se odnose na zapise po kampanji; ista osoba može postojati u više kampanja.',
'',
'Prije svake promjene ponovno su dohvaćeni razgovor, aktualna Smartlead kategorija i lokalni status. Nijedna ciljana nit nije se promijenila između pregleda i upisa. Spremljena je sigurnosna kopija baze. Nakon upisa ponovno su pročitane Smartlead kategorije te provjeren stvarni dashboard API.',
'',f'Prijavljeni API trošak dovršenih i sačuvanih modelskih poziva: približno **${cost:.2f}**. To je zbroj API usage podataka, ne procjena prema cjeniku.',
'',
'## Prvo ručno provjeriti ove slučajeve','',
'| Lead | Stanje | Što preporučujem |','|---|---|---|',
'| Emily Knox | Rezervacija ostaje zaštićena. Na poruku od 16.10. o pomicanju termina nema kasnijeg odgovora u niti. | Provjeriti stvarno stanje termina i odgovoriti kao podrška. Ovo nije prodajni follow-up. |',
'| Franek Buczkowski | Potvrdio je da je rezervirao; sada je Meeting Booked. | U zadnjem našem mailu obećana mu je provjera broja rezervacija kolega. Provjeriti stvarne podatke i ispuniti obećanje. Ne ponavljati prodajnu ponudu za njegovu osobnu sesiju. |',
'| Kofil Ali | Lead Opted Out ostaje zaštićen. U niti postoji stvaran problem s rezervacijom. | Ručno razjasniti status i zahtjev prije bilo kakvog kontakta. Nije uključen u bulk slanje ni odblokiran. |',
'| Robert Tynan | Nije potvrđen interes. Njegov odgovor sadrži samo ime Kurt i potpis. | Ne pretpostavljati da je to prihvaćanje ponude. Ostaje za tvoju odluku, izvan bulk grupe zainteresiranih. |',
'| Steve Bryen | Vraćen u Follow-up due i iz arhive. | Slijed je bio u error stanju lead_not_found, bez poslanog koraka. Zaustavljen je samo taj zapeli upis; preporučujem osobni follow-up nakon tvoje odluke. |',
'',
'## Bulk akcije koje predlažem, ali nisu pokrenute','',
'| Oznaka | Obuhvat | Prijedlog za odobrenje |','|---|---|---|',
f'| A | {len(replies)} razgovora koji trebaju naš sljedeći odgovor | Pripremiti pojedinačne draftove ili ih odgovoriti ručno. Pitanja i preporuke ne spajati u isti generički mail. |',
f'| B | {len(due)} dospjela follow-upa | Bulk priprema osobnih draftova iz zadnje niti, zatim tvoja provjera i zasebna odluka o slanju. Za preporuke i timove koristiti drukčiji tekst od osobnog booking podsjetnika. |',
f'| C | {len(capped)} zainteresiranih leadova na limitu | Odlučiti želiš li jedan dodatni pokušaj ponovnog kontakta. Trenutno se za njih ništa ne generira niti šalje; automatski limit ostaje četiri. |',
'| D | Emily, Franek, Kofil, Robert i ostali označeni za ručni pregled | Pojedinačna odluka. Bez generičkog prodajnog bulk maila. |',
'| E | Annie Barker, Ian Timlin, Ryan Thomas | Pohranjen je samo podsjetnik za pregled, bez zakazanog slanja. Uključiti u buduću akciju tek nakon pregleda. |',
'',
'Za nove booking odgovore koristiti aktualne partnership linkove i VIP8401, 45-minutni physio i potvrđenu £4.99 naknadu za physio. Pozvati na dijeljenje s kolegama, uz jednu besplatnu ponudu po osobi ukupno. Ne tvrditi da novi kod daje drugu besplatnu sesiju. Naknade za masažu nisu potvrđene. Povijesni OBLACCESS55 u već poslanim porukama nije dokaz da je lead rezervirao niti razlog za automatsko zatvaranje.',
'',
'## A: razgovori koji trebaju naš odgovor','']

def detail_table(keys):
 rows=['| Lead / email | Prije → sada | Što je napravljeno | Preporučeni korak |','|---|---|---|---|']
 for k in keys:
  rows.append('| '+esc(display(k)+' / '+R[k]['email'])+' | '+esc(before(k)+' → '+status(k))+' | '+esc(changed(k))+' | '+esc(proposal(k))+' |')
 return rows
lines+=detail_table(replies)
lines+=['','Alistairu je pitanje o naknadi već odgovoreno. Zadnja poruka je njegov stari OOO odgovor s povratkom 9.9.; crveni status ovdje znači da trebamo obnoviti razgovor, ne da je ostalo neodgovoreno pitanje o naknadi.','',
'## B: svi dospjeli follow-upi','']+detail_table(due)
lines+=['','## C: zainteresirani leadovi na postojećem limitu','',
'Za ove leadove tišina nije protumačena kao odbijanje. Već su poslana četiri follow-upa, a 60-dnevni rok za revival još nije istekao. Zato nisu lažno označeni kao automatski dospjeli. Preporučujem da odobriš ili odbiješ jedan dodatni osobni kontakt, posebno ondje gdje je ostala prepreka rezervaciji.','']+detail_table(capped)
lines+=['','## E: odloženi pregledi','']+detail_table(sorted(later,key=display))
lines+=['','Datumi su u London vremenu. Annie je rekla da će pogledati unutar mjesec dana od 24.9.; pregled je postavljen na ponedjeljak 26.10. Ian je najavio 8 do 12 tjedana odsutnosti od 3.9.; najraniji pregled je 29.10. Ryan nije dao točan datum povratka; 16.11. je naš podsjetnik za provjeru, a ne potvrđeni datum njegova povratka ili slanja.','',
'## Nedavno odgovoreni, još nisu dospjeli','',
'Ovim ljudima već je poslan odgovor. Ostaju aktivni i vidljivi; sljedeći status računa se po postojećoj kadenci, uključujući kraći rok za vrlo vruće leadove.','']+detail_table(recent)
lines+=['','## Ispravci aplikacije','',
'- Bulk dohvat razgovora sada se dijeli u grupe do 100 leadova. Prije je cijela provjera velikih kampanja padala na Smartlead limitu.',
'- Vraćanje u Interested odmah ponovno računa je li potreban odgovor, follow-up ili čekanje i osvježava sažetak razgovora.',
'- Ponovno čitanje iste stare poruke više ne poništava namjerno spremljenu odgodu. Nova poruka i dalje prekida odgodu.',
'- Ispravci su aktivni na serveru. Prošlo je 87 testova pouzdanosti i slijedova, uključujući velike grupe, status pri vraćanju i stare nasuprot novim porukama.',
'- Alistairov stari automatski draft 358 označen je kao zastario. Novi bulk draftovi nisu pokrenuti. Redovni app proces može i dalje pripremati draftove za nove odgovore; za slanje je potreban tvoj klik.',
'',
'## Registar svih 942 pregledana razgovora','',
'Jedan redak po kampanji i leadu. Stupac „Zadnji ulazni tekst” je kratak isječak stvarne poruke, a ne modelova pretpostavka. „Bez promjene” znači da u ovom auditu nije izvršena promjena tog zapisa, ne da je model preporučio slanje. Automatizirane poruke, odbijanja, blokade i rezervacije nisu u bulk grupi B.','',
'| Ime | Email | Kampanja / lead ID | Status pri završnoj provjeri | Što je napravljeno | Zadnji ulazni tekst |','|---|---|---|---|---|---|']
for key in sorted(R,key=lambda k:display(k).lower()):
 r=R[key];inbound=[m for m in r['messages'] if m['kind']=='reply'];snippet=esc(inbound[-1]['text'])[:155] if inbound else 'Nema ulazne poruke'
 lines.append('| '+' | '.join(map(esc,[display(key),r['email'],key,status(key),changed(key),snippet]))+' |')
lines+=['','## Trag provjere','',
'[Svi zapisi bez odgovora](./leadovi-bez-odgovora.md) · [Prijedlozi bulk grupa s ID-jevima](./bulk-proposals.json) · [Završni zapis primijenjenih promjena](./final-audit.json) · [Upute modelu](./model-instructions.txt) · [Dodatna provjera](./verification-instructions.txt) · [Ručno provjerene korekcije modela](./review-overrides.json)','',
'Sigurnosna kopija prije promjena na serveru: `/data/status-audit-2026-10-22/before.db`. Osobni podaci audita spremljeni su lokalno i nisu dodani u Git commit. Promjene aplikacije su commitovi dc44538 i 8281a3c.','']
(P/'rundown.md').write_text('\n'.join(lines),encoding='utf-8')

cold=['# OneBodyLDN: potpuni popis zapisa bez odgovora','',f'Izvoz: {source_at}. Ovaj dodatak pokriva preostalih 10.218 zapisa koji u početnom pregledu nisu imali evidentiran odgovor, kategoriju ni postojeći zapis u responderu. Njihov status nije mijenjan, nisu proglašeni zainteresiranima i nisu dodani u bulk akcije. Glavni dokument s pregledanim razgovorima: [rundown](./rundown.md).','',
'| Ime | Email | Kampanja / lead ID | Što je napravljeno |','|---|---|---|---|']
count=0
for cid,rows in S['exports'].items():
 for r in rows:
  key=f"{cid}/{r['id']}"
  if key in R:continue
  name=(' '.join([r.get('first_name') or '',r.get('last_name') or ''])).strip() or r['email']
  cold.append('| '+' | '.join(map(esc,[name,r['email'],key,'Bez promjene; nema evidentiranog odgovora']))+' |');count+=1
assert count==10218
(P/'leadovi-bez-odgovora.md').write_text('\n'.join(cold)+'\n',encoding='utf-8')
groups={'A_odgovori':replies,'B_followup_due':due,'C_limit_potreban_odabir':capped,'E_odlozeno':later,'rucna_podrska':['3930675/4520622245','3876232/4446316604','3876232/4446316573','4006945/4608049732']}
(P/'bulk-proposals.json').write_text(json.dumps({'executed':False,'requires_owner_approval_before_drafting_or_sending':True,'groups':{g:[{'key':k,'name':display(k),'email':R[k]['email'],'recommendation_hr':proposal(k)} for k in keys] for g,keys in groups.items()}},ensure_ascii=False,indent=2),encoding='utf-8')
(P/'report-metrics.json').write_text(json.dumps({'audited_threads':942,'all_campaign_records':11160,'cold_records':count,'followups_due':len(due),'awaiting_reply':len(replies),'restored_from_archive':len(restored),'provider_changes':len(provider_changes),'capped':len(capped),'snoozed':len(later),'processed_leads':len(RESULT),'model_reported_cost_usd':cost,'completed_at':A['completed_at']},indent=2),encoding='utf-8')
print('Report generated',len(lines),'lines; audited 942 + appendix',count,'API cost',round(cost,2))
