import json
from app import smartlead
cid,lid=4235352,4816228662
before=smartlead._request('GET',f'/leads/{lid}/campaign-overview')
response=smartlead._request('POST',f'/campaigns/{cid}/leads/{lid}/resume',json={})
after=smartlead._request('GET',f'/leads/{lid}/campaign-overview')
print(json.dumps({'before':before,'response':response,'after':after},default=str))
