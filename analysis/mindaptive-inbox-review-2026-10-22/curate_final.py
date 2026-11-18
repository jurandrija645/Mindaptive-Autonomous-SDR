import json
import pathlib
import re
import hashlib

OUT=pathlib.Path(__file__).resolve().parent
records={x['key']:x for x in json.loads((OUT/'records.json').read_text(encoding='utf-8'))}
review=json.loads((OUT/'reviewed-decisions.json').read_text(encoding='utf-8'))
decisions={x['key']:x for x in review}
quality={x['key']:x for x in json.loads((OUT/'quality-drafts.json').read_text(encoding='utf-8'))}
saved={x['key']:x for x in json.loads((OUT/'drafts-saved.json').read_text()) if x.get('status')=='pending'}
initial=json.loads((OUT/'drafts-curated.json').read_text(encoding='utf-8'))
if not (OUT/'drafts-round1.json').exists():
    (OUT/'drafts-round1.json').write_text(json.dumps(initial,ensure_ascii=False,indent=2),encoding='utf-8')

# Avoid cosmetic relabeling, empty labels and obsolete future dates.
for d in review:
    if not d['recommended_label']:
        d['recommended_label']=d['current_label']
    if d['current_label'] in ['Auto-Reply','Out Of Office'] and d['recommended_label'] in ['Auto-Reply','Out Of Office']:
        d['recommended_label']=d['current_label']
    if d['recommended_label'] in ['Meeting Request','Information Request']:
        d['recommended_label']='Interested'
    if d['recommended_label']=='Lead Opted Out' and d['current_label']!='Lead Opted Out':
        d['recommended_label']='Do Not Contact'
    if d['recommended_label']=='Contact later':
        d['recommended_label']='Interested'
    if not d.get('human_interest') and d['next_action']=='WAIT' and d.get('next_action_at','') and d['next_action_at'][:10]<'2026-10-22':
        d['next_action']='NO_ACTION';d['next_action_at']=None

manual={
'3950427/4542616635':('en',"Hi William,\n\nWere you able to open the site after that region error?\n\nHere's the link again: https://williams-works.vercel.app\n\nIf it still won't open, could you send me a screenshot of the message?",''),
'3562710/4080236189':('en',"Hi Ronny,\n\nYou asked about a German AI call example when we last spoke. Is a German-speaking AI receptionist still something you'd like to explore?\n\nIf it is, I can check which live example we can share.",''),
'2732401/3016173350':('en',"Hi Anna,\n\nDid your team get a chance to look at the outreach approach we shared?\n\nIf someone else handles this, could you point me to the right person?",''),
'2538823/2758495592':('it',"Ciao Francesco,\n\necco una breve panoramica di come troviamo le aziende in linea con il cliente ideale e avviamo le conversazioni:\nhttps://www.loom.com/share/66b3d9799bf6409fb25f45ef88dec54c\n\nQuale settore di Mallei avrebbe più senso considerare per primo?","Hi Francesco,\n\nHere's a short overview of how we find companies matching the ideal customer and start conversations:\nhttps://www.loom.com/share/66b3d9799bf6409fb25f45ef88dec54c\n\nWhich Mallei sector would make the most sense to consider first?"),
'2538823/2758494599':('it',"Ciao Aleardo,\n\nti lascio una breve spiegazione del processo, così puoi guardarla quando hai tempo senza fissare una call:\nhttps://www.loom.com/share/66b3d9799bf6409fb25f45ef88dec54c\n\nC'è una parte che potrebbe essere utile al team di Innova, oltre ai tool che usate già?","Hi Aleardo,\n\nHere's a short explanation of the process so you can watch it when you have time without arranging a call:\nhttps://www.loom.com/share/66b3d9799bf6409fb25f45ef88dec54c\n\nIs there a part that could be useful to the Innova team alongside the tools you already use?"),
'2738671/3025252894':('en',"Hi Marijus,\n\nDid my answers about the Lithuanian market and our performance-based approach make sense?\n\nIf there's still a question holding this up, happy to answer it.",''),
'2738671/3025253762':('en',"Hi Albert,\n\nWe'd talked about finding a time to speak. Is that still useful for you and the Laurel team?\n\nIf so, which day would suit you?",''),
'2738607/3025136155':('it',"Ciao Roberto,\n\nle risposte che ti ho inviato sul nostro approccio hanno chiarito i tuoi dubbi?\n\nSe c'è un punto che vuoi approfondire, dimmi quale.","Hi Roberto,\n\nDid the answers I sent about our approach clear up your doubts?\n\nIf there's a point you'd like to explore further, tell me which one."),
'2738607/3025134089':('de',"Hey Alina,\n\nwir hatten vor einiger Zeit über einen kurzen Austausch gesprochen. Ist das noch interessant für dich?\n\nWenn ja, welcher Tag würde dir nächste Woche passen?","Hi Alina,\n\nWe spoke a while ago about a short chat. Is that still of interest to you?\n\nIf so, which day would suit you next week?"),
'2538823/2758495835':('fr',"Bonjour Jean-Pierre,\n\nLe sujet de trouver les bons experts pour vos projets de recherche est-il toujours d'actualité ?\n\nSi oui, quel jour vous conviendrait pour un bref échange ?","Hi Jean-Pierre,\n\nIs finding the right experts for your research projects still relevant?\n\nIf so, which day would suit you for a short chat?"),
'3960583/3822375070':('en',"Hi Sid,\n\nDoes the $750 price I sent work for you, or is something else holding this up?\n\nIf it works, reply GO and I'll send the next steps.",''),
'3562710/4080234417':('en',"Hi Ben,\n\nYou'd mentioned collecting property details, energy bills and postcodes before enquiries reach your CRM.\n\nIs that still something you want to sort out, or is it covered now?",''),
'2738607/3025134830':('en',"Hi Dan,\n\nWe'd left this until January. Would it be worth revisiting the outbound approach for ExtraBrain, or is it still the wrong time?",''),
'2538823/2758496826':('en',"Hi Michel,\n\nIs the outbound approach we discussed still relevant for Cybermatic, or are you covered for now?\n\nA quick yes or no is fine.",''),
'2538823/2758495355':('en',"Hi Damian,\n\nYou mentioned revisiting client acquisition once you'd reviewed the studio's plans.\n\nIs it worth picking this back up for Introkreatik, or have your priorities changed?",''),
'2538823/2758495791':('en',"Hi Jari,\n\nWhen we last spoke, you wanted to get clearer on your ICP and messaging before trying outreach again.\n\nHave you got that to a point where it's worth revisiting, or is it still on hold?",''),
'2538823/2758495403':('es',"Hola Denis,\n\nMe comentaste que compartirías el vídeo con Growth para valorar si podía aportar algo a las herramientas que ya usáis.\n\n¿Tiene sentido retomarlo, o preferís seguir con el sistema actual?","Hi Denis,\n\nYou mentioned sharing the video with Growth to assess whether it could add anything to the tools you already use.\n\nDoes it make sense to revisit this, or would you prefer to keep the current setup?")
}

for key,(language,body,english) in manual.items():
    assert key in records
    quality[key]={'key':key,'ready':True,'language':language,'body':body,'english':english,'reason_hr':'Ručno provjeren nastavak stvarnog razgovora, bez izmišljenih cijena, termina, asseta ili obavljenog rada.'}
    if key in {'3562710/4080234417','2738607/3025134830','2538823/2758496826','2538823/2758495355','2538823/2758495791','2538823/2758495403'}:
        d=decisions[key]
        d.update(next_action='FOLLOWUP_DUE',next_action_at=None,recommended_label='Interested',reason_hr='Raniji timing iz razgovora već je prošao. Pripremljen je kratak nastavak bez pretvaranja da se razgovor dogodio nedavno.')

# No invented EVgo demo handover: recipient and actual demo asset need confirmation.
quality['3960583/3729675040'].update(ready=False,body='',reason_hr='Stvarna ljudska preporuka na businessdev@evgo.com; treba potvrditi demo asset i recipient prije dovršenog drafta. Ne slati na opći support.')

translations={
'2538823/2758495382':"Hi Diego,\n\nHere's the video as promised: https://www.loom.com/share/66b3d9799bf6409fb25f45ef88dec54c\n\nIt shows how the agent finds and contacts founders and tech decision-makers, your target clients. It works on performance, so you only pay if it delivers results.\n\nWatch it when you have time and tell me what you think. If useful, we can have a short call to adapt it to your situation.",
'2738671/3025253783':"Hi Jedrzej,\n\nDid you have a chance to watch the video? Let me know if you have any questions.\n\nIf this isn't a priority now, let me know and I'll leave it there.",
'2738607/3025133653':"Hi David,\n\nI wanted to check whether you had a chance to watch the video I sent.\n\nIf the approach fits, we can have that 10-minute chat to define your target and put together a tailored proposal.",
'2738607/3025135047':"Hi Matthias,\n\nJust checking, did you have time to watch the video?\n\nIf so, I'd be interested to hear whether the approach could suit you.\n\nIf not, just let me know and I'll leave it there.",
'2738671/3025251911':"Hi Francisco,\n\nDid you have time to watch the video?\n\nI was wondering whether the approach for reaching CFOs makes sense for Saima, or whether you'd like to adjust something.\n\nIf you prefer, we can skip the emails and have a direct five-minute chat."
}
for key,text in translations.items():
    if key in quality:quality[key]['english']=text

signoffs={'andrew','mia','andrija','cheers','cheers,','thanks','thanks,','best','best,','best regards','best regards,','kind regards','kind regards,','a presto','a presto,','groet','groet,','veel groeten','viele grüße','viele grüße,','andrew juran','mia malcic'}
def clean(body):
    body=re.sub(r'\[link:\s*(https?://[^\]]+)\]',r'\1',body)
    body=re.sub(r'(https?://\S+)\s+\1',r'\1',body)
    body=body.replace(' — ', ', ').replace(' – ', ', ')
    lines=body.strip().splitlines()
    while lines and (not lines[-1].strip() or lines[-1].strip().casefold() in signoffs):lines.pop()
    return '\n'.join(lines).strip()

new=[];held=[]
for key,q in quality.items():
    r=records[key];d=decisions[key]
    if key in saved:continue
    if not q.get('ready'):
        held.append({'key':key,'reason':q.get('reason_hr') or 'Potrebna ručna provjera.'});continue
    body=clean(q.get('body') or '')
    english=clean(q.get('english') or '')
    if not body or re.search(r'\{\{|\[insert|\[link\]|loom\.com/\.\.\.|setup_price|demo_url',body,re.I):
        held.append({'key':key,'reason':'Nedovršen tekst ili placeholder.'});continue
    if d['consecutive_sent']>=5 or d['is_unsubscribed'] or not d['current_status_confirmed'] or d['current_label']=='Meeting-Booked':
        held.append({'key':key,'reason':'Cap, odjava, booking ili nepotvrđena kampanja.'});continue
    if q.get('language') not in ['en',''] and not english:
        held.append({'key':key,'reason':'Nedostaje provjerena engleska verzija.'});continue
    old=r['metadata'].get('draft')
    if old and old['status']!='pending':
        held.append({'key':key,'reason':'Postoji zakazan draft ili slanje u tijeku.'});continue
    source='\n'.join(m['text'] for m in r['messages'])+json.dumps(r['metadata'],ensure_ascii=False)
    known_urls=set(re.findall(r'https?://[^\s\]<>"\)]+',source))|{'https://www.loom.com/share/66b3d9799bf6409fb25f45ef88dec54c','https://www.loom.com/share/456990f4664d4d44b310f0b98d38ed8c'}
    unknown=[u for u in re.findall(r'https?://[^\s\]<>"\)]+',body) if u not in known_urls]
    money=re.findall(r'[$€£]\s?\d+(?:[.,]\d+)?',body)
    if unknown or any(m not in source for m in money):
        held.append({'key':key,'reason':'Nepotvrđen URL ili iznos.'});continue
    item={'key':key,'campaign_id':r['campaign_id'],'lead_id':r['lead_id'],'expected_last_message_id':r['messages'][-1]['message_id'],'expected_draft_id':old['id'] if old else None,'expected_draft_hash':hashlib.sha256((old.get('body_html') or '').encode()).hexdigest() if old else None,'body':body,'english':english,'language':q.get('language'),'triage':'[Mindaptive inbox audit 2026-10-22] '+d['reason_hr']+' Draft only; pending Andrew review. No sending, scheduling or category changes authorized now.'}
    new.append(item)
    d.update(draft_action='CURATED_PENDING_SAVE',draft_language=q.get('language'),draft_reason_hr=q.get('reason_hr') or 'Provjeren draft za pregled.')

for d in review:d['change_proposed']=d['recommended_label']!=d['current_label']
(OUT/'reviewed-decisions.json').write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'drafts-curated.json').write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'drafts-held.json').write_text(json.dumps(held,ensure_ascii=False,indent=2),encoding='utf-8')
print('Curated pending draft payload:',len(new),'Held:',len(held),'Already saved:',len(saved))
