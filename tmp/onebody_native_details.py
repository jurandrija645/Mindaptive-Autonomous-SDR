import json
from app import smartlead
out=[]
campaigns=[c for c in smartlead.list_campaigns() if c.get('parent_campaign_id') and c['status']=='ACTIVE']
for c in campaigns:
    leads=list(smartlead.list_campaign_leads(c['id']))
    info={'campaign': smartlead.get_campaign(c['id']), 'leads': []}
    for r in leads:
        l=r['lead']
        info['leads'].append({'row':r,
            'details':smartlead._request('GET',f"/leads/{r['campaign_lead_map_id']}/sequence-details",params={'campaignId':c['id']}),
            'lookup':smartlead.get_lead_by_email(l['email']),
            'thread':smartlead.get_message_history(c['parent_campaign_id'],l['id'])})
    out.append(info)
print(json.dumps(out,default=str))
