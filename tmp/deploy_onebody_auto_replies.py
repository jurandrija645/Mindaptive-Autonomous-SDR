import base64
import hashlib
import json
import subprocess
from pathlib import Path

names = ['app/reply_classifier.py']
def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()
payload = {}
for name in names:
    previous = Path('tmp/onebody-remote-before') / name
    payload[name] = {
        'expected': digest(previous.read_bytes()) if previous.exists() else None,
        'content': base64.b64encode(Path(name).read_bytes()).decode(),
    }
remote = '''import base64,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
root=Path('/root/mindaptive-responder')
backup=Path('/root/onebody-optout-classifier-backup-20261104')
payload=json.loads(PAYLOAD)
def digest(data): return hashlib.sha256(data.replace(b'\\r\\n',b'\\n')).hexdigest()
for name, item in payload.items():
 p=root/name
 actual=digest(p.read_bytes()) if p.exists() else None
 if actual != item['expected']: raise RuntimeError('Remote file changed since preflight: '+name)
subprocess.run(['docker','compose','ps','-q','app-onebodyldn'],cwd=root,check=True,capture_output=True)
backup.mkdir(parents=True,exist_ok=True)
for name, item in payload.items():
 p=root/name
 old=backup/name
 if p.exists():
  old.parent.mkdir(parents=True,exist_ok=True)
  if not old.exists(): shutil.copy2(p,old)
 tmp=p.with_name(p.name+'.codex-deploy-tmp')
 tmp.write_bytes(base64.b64decode(item['content']))
 os.replace(tmp,p)
for name in payload:
 subprocess.run(['docker','compose','cp',name,'app-onebodyldn:/srv/'+name],cwd=root,check=True,capture_output=True)
subprocess.run(['docker','compose','restart','app-onebodyldn'],cwd=root,check=True,capture_output=True,timeout=90)
print('Updated files and restarted OneBody service; backup:',backup)
'''.replace('PAYLOAD', repr(json.dumps(payload)))
proc = subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes',
                       'root@167.71.63.154','python3 -'], input=remote, text=True,
                      encoding='utf-8',capture_output=True,timeout=180)
print(proc.stdout)
if proc.returncode:
    print(proc.stderr)
    raise SystemExit(proc.returncode)
