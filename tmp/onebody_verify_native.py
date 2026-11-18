import json
from app import smartlead
out={'campaigns':[],'overviews':[],'categorized':[]}
for c in smartlead.list_campaigns():
    if c.get('parent_campaign_id') and c['status']=='ACTIVE':
        leads=list(smartlead.list_campaign_leads(c['id']))
        out['campaigns'].append({'id':c['id'],'status':c['status'], 'leads':leads,
            'sequences':smartlead.get_campaign_sequences(c['id'])})
        for r in leads:
            l=r['lead']
            out['overviews'].append({'name':l['first_name'],'campaign_id':c['id'],
                'data':smartlead._request('GET',f"/leads/{l['id']}/campaign-overview")})
for cid in [4235278,4235286]:
    for cat in [197614,197615]:
        data=smartlead._request('GET',f'/campaigns/{cid}/leads',params={'offset':0,'limit':100,'lead_category_id':cat})
        out['categorized'].append({'campaign_id':cid,'category_id':cat,'data':data})
print(json.dumps(out,default=str))
