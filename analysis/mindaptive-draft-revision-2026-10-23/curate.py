import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone

OUT=pathlib.Path(__file__).resolve().parent
OLD=OUT.parent/'mindaptive-inbox-review-2026-10-22'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
records={x['key']:x for x in read(OLD/'records.json')}
previous={x['key']:x for x in read(OLD/'drafts-verified.json')}
rows=read(OUT/'revised-proposals.json')
B2B='https://www.loom.com/share/66b3d9799bf6409fb25f45ef88dec54c'
CLINIC='https://www.loom.com/share/456990f4664d4d44b310f0b98d38ed8c'
overrides={
 '3562710/4080236189':('en',"Hi Ronny,\n\nIt's been a few months since you asked about a German-speaking AI receptionist. I was looking back through our conversation and wanted to pick it up again.\n\nIs that still something you'd like to explore for Erzvoltaik? If so, I can check which German call example we can share, or we can arrange a short call."),
 '3950427/4542616557':('en',"Hi,\n\nIt's been a few weeks since I shared the website for Cupa Roofing. Would you consider using it with a few changes, or does it not feel like enough of an improvement?\n\nA quick reply either way is fine."),
 '3899056/4475672680':('en',"Hey Yevhenii,\n\nWe'd left off with the type of customer you want to reach for CoSupport. Is this still something you'd like to explore?\n\nIf so, send me a few lines about who you want to sell to and I'll take a look."),
 '2738607/3025135176':('en',f"Hey Andy,\n\nIt's been a while since we spoke about outreach and pricing for Muso. I came across our old conversation while reviewing my inbox and wanted to pick it up again.\n\nWe've improved the system quite a bit since then. Here's an overview of the process:\n{B2B}\n\nIf it's still relevant, would a short call help us pin down the target customers and a current quote?"),
 '2738607/3025135572':('en',f"Hey Andrea,\n\nIt's been a while since we spoke about reaching the right clients for myMeta. I was reviewing our old emails and wanted to see if it's worth picking this back up.\n\nWe've improved the system quite a bit since then. This video walks through how we find suitable companies, research them and start relevant conversations:\n{B2B}\n\nWould a short call be useful to see if it fits what you need now?"),
 '2515956/2722089937':('en',f"Hi Diego,\n\nIt's been a while since our conversation about finding the right clients for Adapsys. I was going back through our emails and wanted to pick it up again.\n\nOur system has improved a lot since then. Here's an overview of the process:\n{B2B}\n\nIf this is still something you're looking at, would it be worth a short call?"),
 '2732401/3016172998':('en',f"Hi Jocelyn,\n\nIt's been a while since we spoke about reaching engineering and product leaders for GAP. I came across our old conversation and wanted to see if the timing is better now.\n\nWe've improved the system quite a bit since then. Here's a video of how the process works:\n{B2B}\n\nWould a short call be useful to see if this still fits what you need?"),
 '2732401/3016172379':('en',f"Hi Sali,\n\nIt's been a while since our conversation about finding the right IT leaders for Ripton. I was reviewing our earlier emails and wanted to pick it up again.\n\nWe've improved the system a lot since then. This video explains the process:\n{B2B}\n\nIf it's still relevant, would a short call make sense?"),
 '2738607/3025134089':('de',f"Hey Alina,\n\nes ist eine ganze Weile her, seit wir über einen kurzen Austausch gesprochen haben. Beim Durchsehen meiner älteren E-Mails bin ich wieder auf unser Gespräch gestoßen.\n\nWir haben unser System seitdem deutlich verbessert. Hier siehst du, wie wir passende Unternehmen finden und Gespräche mit ihnen starten:\n{B2B}\n\nFalls das Thema noch interessant ist, hättest du Lust auf einen kurzen Call?"),
 '2738607/3025135558':('nl',f"Hoi Henri,\n\nHet is een tijd geleden dat we spraken over het vinden van nieuwe klanten voor Imagine Digital. Ik kwam ons gesprek weer tegen toen ik mijn oude mails doornam.\n\nWe hebben ons systeem sindsdien flink verbeterd. Deze video laat zien hoe we geschikte bedrijven vinden, onderzoeken en benaderen:\n{B2B}\n\nZou een kort gesprek nuttig zijn om te zien of dit nog bij jullie past?"),
 '2738607/3025135360':('it',f"Ciao Marco,\n\nè passato parecchio tempo da quando abbiamo parlato di trovare nuovi clienti per Widata. Rileggendo le mie vecchie email, mi è sembrato utile riprendere il discorso.\n\nDa allora abbiamo migliorato molto il sistema. Qui trovi una panoramica di come individuiamo le aziende adatte e avviamo le conversazioni:\n{B2B}\n\nSe il tema è ancora attuale, ti andrebbe una breve call?"),
 '3810275/4360210314':('ro',f"Salut Paul,\n\nAu trecut câteva luni de când am vorbit despre sistemul pentru clinică. Am revăzut conversația noastră și am vrut să revin asupra subiectului.\n\nÎți las din nou prezentarea procesului:\n{CLINIC}\n\nDacă subiectul mai este de interes, ți-ar fi utilă o discuție scurtă?"),
 '3810275/4360210269':('lt',f"Sveiki, Julija,\n\npraėjo keli mėnesiai nuo mūsų pokalbio apie sistemą klinikai. Peržiūrėdamas senesnius laiškus radau mūsų susirašinėjimą ir norėjau grįžti prie šios temos.\n\nČia dar kartą pateikiu proceso pristatymą:\n{CLINIC}\n\nJei tai vis dar aktualu, ar būtų naudinga trumpai pasikalbėti?"),
 '3562710/4080234417':('en',"Hi Ben,\n\nYou'd asked me to get back in touch in September about collecting property details, energy bills and postcodes before enquiries reach your CRM.\n\nI wanted to pick that conversation back up. Is this still something you want to sort out for SogoSolar, or is it covered now?"),
 '2538823/2758496826':('en',f"Hi Michel,\n\nIt's been nearly a year since we spoke about finding new clients for Cybermatic. I was going back through our emails and wanted to see if it's worth picking up again.\n\nWe've improved the system quite a bit since then. Here's an overview of how we find suitable companies and start relevant conversations:\n{B2B}\n\nIf this is still relevant, would a short call be useful?"),
 '2538823/2758495791':('en',f"Hi Jari,\n\nIt's been nearly a year since we spoke about getting clear on In Parallel's target customers and messaging before trying outreach again. I came across our old conversation while reviewing my inbox.\n\nWe've improved our system a lot since then. Here's an overview of how we find suitable companies and start relevant conversations:\n{B2B}\n\nIf you've got the target and messaging clearer now, would it be worth a short call?"),
 '3960583/3822375070':('en',"Hi Sid,\n\nIt's been a few weeks since we spoke about the website for East County Solar Cleaner. You'd asked about the price, and I sent over $750.\n\nDoes that work for you, or is there something you'd need changed first?\n\nIf you're happy to move ahead, reply GO and I'll send the next steps.")
}
localized_intro={
 'en':"Here's an overview of the process:", 'it':'Qui trovi una panoramica del processo:', 'es':'Aquí tienes una visión general del proceso:',
 'de':'Hier findest du einen Überblick über den Ablauf:', 'fr':'Voici une présentation de notre méthode :', 'nl':'Hier zie je hoe het proces werkt:',
 'pl':'Tutaj znajdziesz krótkie omówienie procesu:', 'fi':'Tässä on video siitä, miten prosessi toimii:'}
payload=[]; held=[]
for x in rows:
    key=x['key'];r=records[key];old=previous[key]
    if key=='3950427/4542616635':
        held.append({'key':key,'draft_id':old['id'],'reason':'Zadnja poruka poslana je prije dva dana. Postojeći draft o grešci regije ostavljen je bez izmjene; prije slanja provjeriti pristup demu.'});continue
    if key in overrides:
        x['language'],x['body']=overrides[key];x['ready']=True
    if not x['ready']:
        held.append({'key':key,'draft_id':old['id'],'reason':x['reason_hr']});continue
    body=x['body'].strip()
    body=body.replace('Loom link.',B2B).replace('Loom link',B2B)
    body=body.replace('well over a year now','about a year now')
    body=re.sub(r"\s*(?:Thanks|Grazie|Gracias|Merci|Cheers)[.!]?\s*$",'',body,flags=re.I)
    body=body.replace(' — ','. ').replace(' – ','. ').replace('—',', ').replace('–',', ')
    body=body.replace('**','')
    # A link in the historical conversation is not proof the demo is still online.
    body=re.sub(r"It's still up at (https://[^\s]+)",lambda m:"Here's the link again: "+m.group(1).rstrip('.')+'\n',body)
    age=(datetime(2026,10,23,tzinfo=timezone.utc)-datetime.fromisoformat(r['messages'][-1]['time'].replace('Z','+00:00'))).days
    if age>=180 and not r['website_offer'] and B2B not in body:
        parts=body.split('\n\n')
        parts.insert(-1,localized_intro.get(x['language'],localized_intro['en'])+'\n'+B2B)
        body='\n\n'.join(parts)
    assert 'Loom link' not in body and '—' not in body and '{{' not in body
    allowed=set(re.findall(r'https?://[^\s<>\]]+',json.dumps(r,ensure_ascii=False)))|{B2B,CLINIC}
    for u in re.findall(r'https?://[^\s<>]+',body):
        assert any(u.rstrip('.,/)')==a.rstrip('.,/)') for a in allowed),(key,'unverified URL',u)
    payload.append({'key':key,'campaign_id':r['campaign_id'],'lead_id':r['lead_id'],'expected_draft_id':old['id'],'expected_draft_hash':hashlib.sha256(old['body_html'].encode()).hexdigest(),'expected_last_message_id':r['messages'][-1]['message_id'],'body':body,'english':'','language':x['language'],'age_days':age,'triage':f"[Age-aware revision 2026-10-23] {age} days since last thread message. Acknowledge elapsed time, preserve topic and actual request. Pending human review only; no sending, scheduling or status changes."})
(OUT/'approved-payload.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'held.json').write_text(json.dumps(held,ensure_ascii=False,indent=2),encoding='utf-8')
print('Curated revisions:',len(payload),'Unchanged/held:',len(held),'Foreign translations needed:',sum(x['language']!='en' for x in payload))
