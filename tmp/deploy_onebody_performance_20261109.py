import base64
import hashlib
import json
import subprocess
from pathlib import Path

names = ['app/static/app.js', 'app/static/crm.js', 'app/static/style.css']
def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()

payload = {name: {
    'expected': digest((Path('tmp/onebody-performance-before-20261109')/name).read_bytes()),
    'content': base64.b64encode(Path(name).read_bytes()).decode(),
} for name in names}
remote = '''import base64,hashlib,json,os,shutil,subprocess
from pathlib import Path
root=Path('/root/mindaptive-responder')
backup=Path('/root/onebody-performance-backup-20261109')
payload=json.loads(PAYLOAD)
def digest(data): return hashlib.sha256(data.replace(b'\\r\\n',b'\\n')).hexdigest()
for name,item in payload.items():
 if digest((root/name).read_bytes())!=item['expected']:
  raise RuntimeError('Server source changed since preflight: '+name)
 live=subprocess.run(['docker','compose','exec','-T','app-onebodyldn','cat','/srv/'+name],cwd=root,capture_output=True,check=True)
 if digest(live.stdout)!=item['expected']:
  raise RuntimeError('Running service differs from source: '+name)
backup.mkdir(parents=True,exist_ok=True)
for name,item in payload.items():
 p=root/name; old=backup/name
 old.parent.mkdir(parents=True,exist_ok=True)
 if not old.exists(): shutil.copy2(p,old)
 tmp=p.with_name(p.name+'.codex-performance-tmp')
 tmp.write_bytes(base64.b64decode(item['content'])); os.replace(tmp,p)
for name in payload:
 subprocess.run(['docker','compose','cp',name,'app-onebodyldn:/srv/'+name],cwd=root,check=True,capture_output=True)
subprocess.run(['docker','compose','restart','app-onebodyldn'],cwd=root,check=True,capture_output=True,timeout=90)
print(json.dumps({'updated':list(payload),'backup':str(backup),'service':'app-onebodyldn','sha256':{n:digest((root/n).read_bytes()) for n in payload}}))
'''.replace('PAYLOAD',repr(json.dumps(payload)))
result=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','-o','ConnectTimeout=10',
    'root@167.71.63.154','python3 -'],input=remote,text=True,encoding='utf-8',capture_output=True,timeout=180)
if result.returncode:
    print(result.stderr)
    raise SystemExit(result.returncode)
print(result.stdout)
Path('analysis/onebody-performance-2026-11-09/deployment.json').write_text(result.stdout,encoding='utf-8')
