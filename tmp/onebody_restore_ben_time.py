import json
from datetime import datetime,timezone
from app import smartlead
cid,lid=4235352,4816228662
smartlead._request('POST',f'/campaigns/{cid}/leads/{lid}/pause')
target=datetime(2026,10,28,13,55,13,tzinfo=timezone.utc)
# Smartlead applies this delay to its existing sequence anchor, not to now.
# The no-delay read-back returned this exact anchor.
anchor=datetime.fromisoformat('2026-10-26T09:42:53.467+00:00')
delay=(target-anchor).total_seconds()/86400
assert 2 < delay < 3
result=smartlead._request('POST',f'/campaigns/{cid}/leads/{lid}/resume',json={'resume_lead_with_delay_days':delay})
overview=smartlead._request('GET',f'/leads/{lid}/campaign-overview')
mapping=next(m for m in overview['data']['email_campaign_leads_mappings'] if m['email_campaign_id']==str(cid))
actual=datetime.fromisoformat(mapping['next_timestamp_to_reach'])
assert abs((actual-target).total_seconds()) < 2, mapping
print(json.dumps({'delay_days':delay,'result':result,'overview':overview},default=str))
