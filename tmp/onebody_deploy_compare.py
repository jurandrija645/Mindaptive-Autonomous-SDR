import base64
import json
import subprocess
from pathlib import Path

names = ['app/reply_classifier.py']
remote = '''import base64,json
from pathlib import Path
root=Path('/root/mindaptive-responder')
names=json.loads(NAMES)
print(json.dumps({n:base64.b64encode((root/n).read_bytes()).decode() if (root/n).is_file() else None for n in names}))
'''.replace('NAMES', repr(json.dumps(names)))
result = subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes',
                         'root@167.71.63.154','python3 -'], input=remote, text=True,
                        capture_output=True, check=True, timeout=30)
for name, content in json.loads(result.stdout).items():
    if content is None:
        print('REMOTE MISSING', name)
        continue
    data = base64.b64decode(content).replace(b'\r\n', b'\n')
    path = Path('tmp/onebody-remote-before') / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    local = Path(name).read_bytes().replace(b'\r\n', b'\n')
    base = subprocess.run(['git','show','HEAD:'+name], capture_output=True).stdout.replace(b'\r\n', b'\n')
    print(('SAME' if data == local else 'REMOTE_BASE' if data == base else 'REMOTE_DIFF'), name)
