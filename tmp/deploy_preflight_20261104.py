import hashlib
import json
import subprocess
from pathlib import Path

roots = ['app', 'prompts', 'knowledge', 'signatures', 'clients', 'scripts']
files = [p for root in roots for p in Path(root).rglob('*')
         if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
files += [Path('Dockerfile'), Path('docker-compose.yml'), Path('requirements.txt')]
def digest(data):
 if b'\0' not in data:
  data=data.replace(b'\r\n',b'\n')
 return hashlib.sha256(data).hexdigest()
manifest = {p.as_posix(): digest(p.read_bytes()) for p in files}
remote = '''import hashlib,json,subprocess
from pathlib import Path
root=Path('/root/mindaptive-responder')
manifest=json.loads(INPUT)
out={}
for name in manifest:
 p=root/name
 if p.is_file():
  data=p.read_bytes()
  if b'\\0' not in data: data=data.replace(b'\\r\\n',b'\\n')
  out[name]=hashlib.sha256(data).hexdigest()
 else: out[name]=None
print(json.dumps(out))
'''.replace('INPUT', repr(json.dumps(manifest)))
r = subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes',
                    '-o','ConnectTimeout=10','root@167.71.63.154','python3 -'],
                   input=remote,text=True,capture_output=True,check=True)
server = json.loads(r.stdout)
changes=[]
conflicts=[]
for name, local_hash in manifest.items():
 if server[name] == local_hash: continue
 base = subprocess.run(['git','show','HEAD:'+name],capture_output=True)
 base_hash=digest(base.stdout) if base.returncode == 0 else None
 changes.append(name)
 if server[name] not in (None,base_hash): conflicts.append(name)
print(json.dumps({'changes':changes,'conflicts':conflicts},indent=2))
