import base64
import hashlib
import json
from pathlib import Path
import subprocess

files=['clients/onebodyldn/prompts/system.md',
       'clients/onebodyldn/knowledge/booking-options.md',
       'clients/onebodyldn/knowledge/onebody-overview.md',
       'clients/onebodyldn/knowledge/response-templates.md']
payload={f:base64.b64encode(Path(f).read_bytes()).decode() for f in files}
script='''import base64,json,hashlib,shutil,subprocess
from pathlib import Path
root=Path('/root/mindaptive-responder')
backup=Path('/root/onebody-booking-fix-2026-10-28')
backup.mkdir(exist_ok=True)
payload=json.loads(PAYLOAD)
for name,data in payload.items():
    path=root/name
    saved=backup/name
    saved.parent.mkdir(parents=True,exist_ok=True)
    if not saved.exists(): shutil.copy2(path,saved)
    path.write_bytes(base64.b64decode(data))
    print(name,hashlib.sha256(path.read_bytes()).hexdigest())
    subprocess.run(['docker','compose','cp',name,'app-onebodyldn:/srv/'+name],cwd=root,check=True,capture_output=True)
subprocess.run(['docker','compose','restart','app-onebodyldn'],cwd=root,check=True,capture_output=True)
print('OneBody assets deployed and OneBody restarted')
'''.replace('PAYLOAD',repr(json.dumps(payload)))
result=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes',
                       'root@167.71.63.154','python3 -'],input=script,
                       capture_output=True,text=True,encoding='utf8',timeout=120)
print(result.stdout)
if result.returncode: raise RuntimeError(result.stderr)
