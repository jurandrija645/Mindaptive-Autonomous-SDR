import base64
import hashlib
import json
from pathlib import Path
import subprocess

files = [
    'clients/onebodyldn/prompts/system.md',
    'clients/onebodyldn/knowledge/booking-options.md',
    'clients/onebodyldn/knowledge/locations.md',
    'clients/onebodyldn/knowledge/response-templates.md',
    'clients/onebodyldn/knowledge/onebody-overview.md',
    'clients/onebodyldn/knowledge/clinic-routing.md',
]
payload = {}
for name in files:
    old = subprocess.run(['git', 'show', 'HEAD:' + name], capture_output=True)
    payload[name] = dict(
        content=base64.b64encode(Path(name).read_bytes()).decode(),
        expected=hashlib.sha256(old.stdout).hexdigest() if old.returncode == 0 else None,
    )
    if name.endswith('booking-options.md'):
        payload[name]['previous_text'] = Path(name).read_text(encoding='utf-8').replace(
            'If the lead wants 45-minute massage at an otherwise eligible location outside\n'
            'the priority list, offer 20-minute massage there or 45-minute massage at a listed clinic that suits',
            'If the lead wants 45-minute massage at a location outside the list, offer\n'
            '20-minute massage there or 45-minute massage at a listed clinic that suits')

script = '''import base64,hashlib,json,shutil,subprocess
from datetime import datetime,timezone
from pathlib import Path
root=Path('/root/mindaptive-responder')
payload=json.loads(PAYLOAD)
def digest(p):
 return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
# Preflight all assets before writing anything; preserve any concurrent edits.
for name,item in payload.items():
 actual=digest(root/name)
 target=hashlib.sha256(base64.b64decode(item['content'])).hexdigest()
 if actual not in (item['expected'],target) and (not item.get('previous_text') or (root/name).read_text()!=item['previous_text']):
  raise RuntimeError('Concurrent remote edit: '+name)
backup=Path('/root/onebody-clinic-routing-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir()
for name,item in payload.items():
 path=root/name
 saved=backup/name
 saved.parent.mkdir(parents=True,exist_ok=True)
 if path.exists(): shutil.copy2(path,saved)
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_bytes(base64.b64decode(item['content']))
 subprocess.run(['docker','compose','cp',name,'app-onebodyldn:/srv/'+name],cwd=root,check=True,capture_output=True)
verify="""import hashlib,json
from pathlib import Path
from app import client_assets,drafter
expected=EXPECTED
for name,sha in expected.items():
 assert hashlib.sha256(Path('/srv',name).read_bytes()).hexdigest()==sha,name
priority=client_assets.priority_clinics()
assert len(priority)==9,priority
assert client_assets.booking_location_priority('One Body LDN - Twickenham')=='No'
prompt=drafter.system_prompt()
assert '# Reference: clinic-routing' in prompt
assert '2026-10-29 exclusions' in prompt
print(json.dumps({'verified_asset_count':len(expected),'priority_clinics':priority,'routing_loaded':True,'system_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}))
""".replace('EXPECTED',repr({name:hashlib.sha256(base64.b64decode(item['content'])).hexdigest() for name,item in payload.items()}))
r=subprocess.run(['docker','compose','exec','-T','app-onebodyldn','python','-'],input=verify,cwd=root,capture_output=True,text=True)
if r.returncode:
 print(r.stderr)
 raise RuntimeError('Container asset verification failed')
print(r.stdout)
subprocess.run(['docker','compose','restart','app-onebodyldn'],cwd=root,check=True,capture_output=True)
print(json.dumps({'backup':str(backup),'restarted':'app-onebodyldn'}))
'''.replace('PAYLOAD', repr(json.dumps(payload)))
result = subprocess.run(
    ['ssh', '-i', 'C:/Users/AndRo/.ssh/leadaptive_droplet', '-o', 'BatchMode=yes',
     'root@167.71.63.154', 'python3 -'],
    input=script, capture_output=True, text=True, encoding='utf-8', timeout=120,
)
folder = Path('analysis/onebody-clinic-routing-2026-10-29')
with (folder / 'deployment.txt').open('a', encoding='utf-8') as log:
    log.write(result.stdout + result.stderr)
print(result.stdout)
if result.returncode:
    raise RuntimeError(result.stderr)
