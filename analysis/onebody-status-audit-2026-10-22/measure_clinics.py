import pathlib,json,re,urllib.request,math
from clinic_facts import FACTS
P=pathlib.Path(__file__).resolve().parent
root=P.parents[1]
rx=r'\b[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}\b'
clinics=[]
priority={'Wimbledon','Aldgate East','Hendon','High Street Kensington','Mill Hill','Moorgate','Southfields','Twickenham','Waterloo','West Kensington'}
for line in (root/'clients/onebodyldn/knowledge/locations.md').read_text(encoding='utf-8').splitlines():
 if not line.startswith('|'):continue
 parts=[x.strip() for x in line.split('|')]
 if len(parts)<4:continue
 pc=re.findall(rx,parts[2])
 if pc:clinics.append(dict(name=parts[1],address=parts[2],postcode=pc[-1],priority=parts[1] in priority))
assert len(clinics)==43
pcs=sorted(set([c['postcode'] for c in clinics]+[v[1] for v in FACTS.values() if v[1]]))
cache=P/'clinic-postcode-coordinates.json'
if cache.exists(): geo=json.loads(cache.read_text())
else:
 req=urllib.request.Request('https://api.postcodes.io/postcodes',data=json.dumps({'postcodes':pcs}).encode(),headers={'Content-Type':'application/json','User-Agent':'OneBody-location-review/1.0'})
 with urllib.request.urlopen(req,timeout=40) as response:data=json.load(response)
 geo={r['query']:r['result'] for r in data['result']}
 cache.write_text(json.dumps(geo,indent=2),encoding='utf-8')
def dist(a,b):
 lat1,lat2=map(math.radians,[a['latitude'],b['latitude']]);dl=lat2-lat1;dn=math.radians(b['longitude']-a['longitude'])
 return 6371*2*math.asin(math.sqrt(math.sin(dl/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dn/2)**2))
j=json.loads((P/'prijedlog-akcija-za-odobrenje.json').read_text(encoding='utf-8'))
rows=sum([j['groups'][x] for x in ['A_replies','B_individual_followups','B_team_followups']],[])
out=[]
for i,r in enumerate(rows,1):
 address,pc,url,note=FACTS[i]; item=dict(**r,ordinal=i,address=address,postcode=pc,source_url=url,evidence_note=note)
 if pc and geo.get(pc):
  ds=sorted([dict(**c,km=round(dist(geo[pc],geo[c['postcode']]),3)) for c in clinics if geo.get(c['postcode'])],key=lambda d:d['km'])
  item['nearest_priority']=[d for d in ds if d['priority']][:3];item['nearest_any']=ds[:2]
  print(i,r['name'],[(d['name'],d['km']) for d in item['nearest_priority'][:2]],'closest',[(d['name'],d['km']) for d in ds[:1]])
 else:print(i,r['name'],'NO_COORDINATES')
 out.append(item)
(P/'clinic-review-evidence.json').write_text(json.dumps(dict(clinics=clinics,rows=out,method='Haversine between postcode centroids from api.postcodes.io, km, not walking routes',missing=[pc for pc in pcs if not geo.get(pc)]),ensure_ascii=False,indent=2),encoding='utf-8')
print('Missing:',[pc for pc in pcs if not geo.get(pc)])
