import base64,json,subprocess
from pathlib import Path
names=['app/batch_gen.py','app/onebody_review.py','app/pipeline.py','app/static/app.js',
       'clients/onebodyldn/knowledge/booking-options.md','clients/onebodyldn/knowledge/locations.md',
       'clients/onebodyldn/knowledge/onebody-overview.md','clients/onebodyldn/knowledge/response-templates.md',
       'clients/onebodyldn/prompts/system.md']
script='''import base64,json
from pathlib import Path
root=Path('/root/mindaptive-responder')
names=json.loads(NAMES)
print(json.dumps({n:base64.b64encode((root/n).read_bytes()).decode() if (root/n).is_file() else None for n in names}))
'''.replace('NAMES',repr(json.dumps(names)))
r=subprocess.run(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','root@167.71.63.154','python3 -'],input=script,text=True,capture_output=True,check=True)
for name, content in json.loads(r.stdout).items():
 if content is None:
  print('REMOTE MISSING',name)
  continue
 p=Path('tmp/deploy-remote-20261104')/name
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_bytes(base64.b64decode(content))
 d=subprocess.run(['git','diff','--no-index','--ignore-cr-at-eol','--',str(p),name],capture_output=True,text=True,encoding='utf8',errors='replace')
 if d.stdout:
  print(d.stdout)
