import json
from app import db, smartlead
ids={4006946,4006945,3930675,3967420,4235278,4235286,4235340,4235670,4235352,4235673}
for c in smartlead.list_campaigns():
    if int(c['id']) in ids: print(json.dumps({k:c.get(k) for k in ('id','name','status','parent_campaign_id')}),flush=True)
recent=smartlead.list_recent_replies(limit=20)
for r in recent:
    if r.get('email_lead_id') in (4878291260,4878288362): print(json.dumps({'recent_reply':r}),flush=True)
