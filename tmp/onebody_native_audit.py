import json
from app import smartlead
out=[]
for c in smartlead.list_campaigns():
    if c.get('parent_campaign_id'):
        out.append({'campaign': c, 'sequences': smartlead.get_campaign_sequences(c['id']),
                    'leads': list(smartlead.list_campaign_leads(c['id'])),
                    'analytics': smartlead.get_campaign_analytics(c['id'])})
print(json.dumps(out,default=str))
