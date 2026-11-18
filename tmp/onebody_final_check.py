import hashlib,json
from pathlib import Path
from app import client_assets,smartlead
from app.config import settings
ids={4235673,4235670,4235352,4235340}
result={'client':str(client_assets.CLIENT_DIR),'dry_run':settings.dry_run,'campaigns':[], 'leads':[]}
for c in smartlead.list_campaigns():
    if c['id'] not in ids: continue
    steps=smartlead.get_campaign_sequences(c['id'])
    assert c['status']=='ACTIVE' and len(steps)==4
    for s in steps:
        body=s['email_body']
        assert '{{nearestClinic}}' not in body and '£4.99' in body and 'each person at {{company_name}} gets one free session' in body
    result['campaigns'].append({'id':c['id'],'name':c['name'],'status':c['status'],'verified_steps':len(steps)})
    for r in smartlead.list_campaign_leads(c['id']):
        l=r['lead']
        data=smartlead._request('GET',f"/leads/{l['id']}/campaign-overview")['data']
        mapping=next(m for m in data['email_campaign_leads_mappings'] if str(m['email_campaign_id'])==str(c['id']))
        result['leads'].append({'name':l['first_name'],'company':l['company_name'],'email':l['email'],
            'campaign_id':c['id'],'enrolled_at':r['created_at'],'mapping':mapping})
needed={int(r['mapping']['email_account_id']) for r in result['leads'] if r['mapping']['email_account_id']}
accounts={int(a['id']):a for a in smartlead.list_email_accounts()}
result['senders']=[{k:accounts[i].get(k) for k in ('id','from_name','from_email','is_smtp_success','is_imap_success','is_email_sending_blocked','message_per_day')} for i in sorted(needed) if i in accounts]
assert needed.issubset(accounts.keys()),needed-accounts.keys()
result['assets']={str(p.relative_to(client_assets.REPO_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
    for p in [client_assets.PROMPTS_DIR/'system.md',*[client_assets.KNOWLEDGE_DIR/n for n in ['booking-options.md','response-templates.md','onebody-overview.md']]]}
print(json.dumps(result,default=str))
