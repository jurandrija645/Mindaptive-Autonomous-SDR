import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

names = ['app/onebody_review.py', 'app/pipeline.py', 'app/auto_replies.py',
         'app/batch_gen.py', 'app/main.py', 'app/static/app.js']
before_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('tmp/onebody-generate-before-20261109')
backup_suffix = '-locations' if len(sys.argv) > 1 else ''

def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()

payload = {name: {
    'expected': digest((before_dir / name).read_bytes()),
    'content': base64.b64encode(Path(name).read_bytes()).decode(),
} for name in names}

remote = '''import base64,hashlib,json,os,shutil,subprocess
from pathlib import Path
root=Path('/root/mindaptive-responder')
backup=Path('/root/onebody-generation-backup-20261109SUFFIX')
payload=json.loads(PAYLOAD)
def digest(data): return hashlib.sha256(data.replace(b'\\r\\n',b'\\n')).hexdigest()
for name,item in payload.items():
 p=root/name
 if digest(p.read_bytes()) != item['expected']:
  raise RuntimeError('Remote source changed since preflight: '+name)
 r=subprocess.run(['docker','compose','exec','-T','app-onebodyldn','cat','/srv/'+name],cwd=root,check=True,capture_output=True)
 if digest(r.stdout) != item['expected']:
  raise RuntimeError('Live container differs from source: '+name)
backup.mkdir(parents=True,exist_ok=True)
for name,item in payload.items():
 p=root/name
 old=backup/name
 old.parent.mkdir(parents=True,exist_ok=True)
 if not old.exists(): shutil.copy2(p,old)
 new=base64.b64decode(item['content'])
 if name.endswith('.py'): compile(new,name,'exec')
 tmp=p.with_name(p.name+'.codex-generation-tmp')
 tmp.write_bytes(new)
 os.replace(tmp,p)
for name in payload:
 subprocess.run(['docker','compose','cp',name,'app-onebodyldn:/srv/'+name],cwd=root,check=True,capture_output=True)
subprocess.run(['docker','compose','restart','app-onebodyldn'],cwd=root,check=True,capture_output=True,timeout=90)
print(json.dumps({'updated':list(payload),'backup':str(backup),'service':'app-onebodyldn'}))
'''.replace('PAYLOAD', repr(json.dumps(payload))).replace('SUFFIX', backup_suffix)

result = subprocess.run(['ssh', '-i', 'C:/Users/AndRo/.ssh/leadaptive_droplet',
    '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@167.71.63.154', 'python3 -'],
    input=remote, text=True, encoding='utf-8', capture_output=True, timeout=180)
print(result.stdout)
if result.returncode:
    print(result.stderr)
    raise SystemExit(result.returncode)
