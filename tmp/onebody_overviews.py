import json
from app import smartlead
out=[]
for c in smartlead.list_campaigns():
    if c.get('parent_campaign_id') and c['status']=='ACTIVE':
        for r in smartlead.list_campaign_leads(c['id']):
            l=r['lead']
            out.append({'campaign_id':c['id'],'name':l['first_name'],'lead_id':l['id'],
                        'overview':smartlead._request('GET',f"/leads/{l['id']}/campaign-overview")})
print(json.dumps(out,default=str))
