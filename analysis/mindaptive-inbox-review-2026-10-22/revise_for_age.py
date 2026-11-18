"""Revise previously reviewed draft bodies for elapsed time. Never sends."""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import html
import json
import pathlib
import re
import urllib.request
import time

import live
import quality_drafts

OUT = live.OUT.parent/'mindaptive-draft-revision-2026-10-23'
OUT.mkdir(exist_ok=True)
records={x['key']:x for x in json.loads((live.OUT/'records.json').read_text(encoding='utf-8'))}
drafts=json.loads((live.OUT/'drafts-verified.json').read_text(encoding='utf-8'))
NOW=datetime(2026,10,23,tzinfo=timezone.utc)
SYSTEM=quality_drafts.SYSTEM.replace('Current date 2026-10-22','Current date 2026-10-23')+'''

LATEST USER EDITORIAL INSTRUCTION, applies over the earlier permissive timing guidance:
Rewrite each provided draft to fit the ACTUAL age and content of the exchange. The operator has reviewed this inbox and explicitly requests a natural acknowledgement when returning after many months. For 180+ day gaps, you MUST briefly acknowledge the long silence, recall the specific topic, and write a reactivation, never an ordinary recent follow-up like "did you get to watch?". For a genuinely unanswered old request, a short apology for the very late reply fits. If we already answered and followed up, say it has been a while since we spoke; do not pretend their request was unanswered or we lost the email. A truthful framing is reviewing our older emails/conversation. Do not invent illness, spam folders, broken systems or other excuses. Don't dwell on the delay.
The USER confirms our system has improved a lot since those old conversations. You may state that broad improvement; do not invent specific new features, new results, case studies, guarantees or exact improvements. Where suitable for an old B2B outreach-engine prospect, give the verified B2B process Loom (https://www.loom.com/share/66b3d9799bf6409fb25f45ef88dec54c) as a current overview of what we do. Don't claim it is a newly recorded personal video. Briefly explain the relevance: finding suitable companies, researching them and starting relevant conversations, only when useful to their question.
End with a gentle invitation to a short call IF that fits their request. If they explicitly preferred email or said they cannot do calls, honor that and ask one simple reply question instead. Don't force a call in place of a direct answer, quote or still-missing promised custom asset.
For gaps 60–179 days, acknowledge the pause naturally, use the correctly matched video only if relevant. For 14–59 days, a short bridge back to the actual conversation/topic is enough; no apology for a year-long delay. Under 14 days, don't invent a long silence.
Website-offer drafts keep the website offer and actual commercial stage; don't insert AI-outbound Loom, upgrades to an unrelated system, or a forced call. A one-line bridge to the website shared a few weeks ago makes A/B follow-ups feel natural instead of abrupt.
Keep the language of the actual person, correct name, existing verified prices, working offer context and safety restrictions. 60–120 words for an old reactivation is fine; no repeated full sales pitch. No sign-off or signature, no placeholders. Output one draft for EVERY key, including ready=false if needed.
'''

def run(i, batch):
    path=OUT/f'batch-{i:03d}.json'
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    inputs=[]
    for d in batch:
        r=records[d['key']]
        last=r['messages'][-1]
        inbound=[m for m in r['messages'] if m['kind']=='reply']
        sent=[m for m in r['messages'] if m['kind']=='sent']
        inputs.append({'key':d['key'],'name':r['name'],'company':r['company'],'campaign':r['campaign_name'],'website_offer':r['website_offer'],'messages':r['messages'],'existing_draft_html':d['body_html'],'consecutive_sent':r['consecutive_sent'],'days_since_last_message':(NOW-datetime.fromisoformat(last['time'].replace('Z','+00:00'))).days,'last_outbound_at':sent[-1]['time'] if sent else None,'last_inbound_at':inbound[-1]['time'] if inbound else None})
    payload={'model':'deepseek/deepseek-v4-flash','reasoning':{'effort':'none'},'response_format':{'type':'json_object'},'max_tokens':14000,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps({'leads':inputs},ensure_ascii=False)}]}
    for attempt in range(3):
        try:
            req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+live.cfg['OPENROUTER_API_KEY'],'X-Title':'Mindaptive age-aware pending draft revision'})
            with urllib.request.urlopen(req,timeout=180) as response:result=json.load(response)
            rows=json.loads(result['choices'][0]['message']['content'])['drafts']
            assert {x['key'] for x in rows}=={x['key'] for x in batch}
            answer={'model':'deepseek/deepseek-v4-flash','usage':result.get('usage'),'drafts':rows}
            path.write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
            return answer
        except Exception:
            if attempt==2:raise RuntimeError(f'Revision batch {i} failed') from None
            time.sleep(3)

batches=[(i//5,drafts[i:i+5]) for i in range(0,len(drafts),5)]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(run,i,b) for i,b in batches]
    for n,f in enumerate(concurrent.futures.as_completed(futures),1):
        f.result();print(f'Revised batches {n}/{len(batches)}',flush=True)
rows=[d for i,_ in batches for d in json.loads((OUT/f'batch-{i:03d}.json').read_text(encoding='utf-8'))['drafts']]
(OUT/'revised-proposals.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('Draft revisions ready for review:',len(rows),flush=True)
