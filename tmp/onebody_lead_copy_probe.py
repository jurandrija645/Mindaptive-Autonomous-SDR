import json
from app import smartlead

result={}
for cid in [4235673,4235670,4235352,4235340]:
    result[cid]=smartlead._request('GET',f'/campaigns/{cid}/statistics',params={'offset':0,'limit':1000})
print(json.dumps(result,default=str))
