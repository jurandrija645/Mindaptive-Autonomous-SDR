import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path('/root/mindaptive-responder')
stage = Path('/root/responder-release-20261104-subsequences')
services = ['app', 'app-aerodefense', 'app-onebodyldn']
image = 'responder-release-20261104-subsequences'
backup = Path('/root/responder-backup-20261104-' + datetime.now(timezone.utc).strftime('%H%M%S') + '.zip')
bundle = Path('/tmp/responder-deploy-20261104.zip')

def run(args, **kw):
 return subprocess.run(args, cwd=root, check=True, text=True, **kw)

# Avoid restarting in the middle of a scheduled delivery. This also lets the
# existing scheduler drain any mail already due before the brief restart.
check = '''from app import db
from datetime import datetime,timezone,timedelta
import json
with db.db_session() as c:
 rows=c.execute("select status,scheduled_at from drafts where status in ('sending','scheduled')").fetchall()
 now=datetime.now(timezone.utc); sending=0; due=0
 for r in rows:
  if r['status']=='sending': sending+=1; continue
  try:
   t=datetime.fromisoformat(r['scheduled_at'].replace('Z','+00:00'))
   if t.tzinfo is None: t=t.replace(tzinfo=timezone.utc)
   if now-timedelta(seconds=90) <= t <= now+timedelta(seconds=90): due+=1
  except Exception: pass
 print(json.dumps({'sending':sending,'due_soon':due}))'''
for attempt in range(36):
 active=[]
 for service in services:
  result=run(['docker','compose','exec','-T',service,'python','-c',check],capture_output=True)
  state=json.loads(result.stdout.strip().splitlines()[-1])
  if state['sending'] or state['due_soon']: active.append((service,state))
 if not active: break
 print('Waiting for current scheduled deliveries:',active,flush=True)
 time.sleep(5)
else:
 raise RuntimeError('Scheduled deliveries are still in progress; no deployment was started.')

with ZipFile(bundle) as z:
 names=z.namelist()
 changed=[n for n in names if not (root/n).is_file() or (root/n).read_bytes()!=z.read(n)]
 with ZipFile(backup,'w',ZIP_DEFLATED) as saved:
  absent=[]
  for name in changed:
   path=root/name
   if path.is_file(): saved.write(path,name)
   else: absent.append(name)
  saved.writestr('_new_files.json',json.dumps(absent))
 for name in changed:
  path=root/name
  path.parent.mkdir(parents=True,exist_ok=True)
  temp=path.with_name(path.name+'.deploy-tmp')
  temp.write_bytes(z.read(name))
  temp.replace(path)

old={}
for service in services:
 cid=run(['docker','compose','ps','-q',service],capture_output=True).stdout.strip()
 old[service]=run(['docker','inspect','--format','{{.Image}}',cid],capture_output=True).stdout.strip()
print('Backup:',backup, 'files updated:',len(changed),flush=True)
print('Previous image IDs:',json.dumps(old),flush=True)
for service in services:
 run(['docker','tag',image,'mindaptive-responder-'+service])
run(['docker','compose','up','-d','--no-build','--no-deps','--force-recreate',*services])
for service,port in zip(services,[8080,8081,8082]):
 ok=False
 for _ in range(30):
  try:
   with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/login',timeout=3) as response:
    if response.status==200: ok=True; break
  except Exception: time.sleep(1)
 if not ok: raise RuntimeError(service+' did not become available')
 cid=run(['docker','compose','ps','-q',service],capture_output=True).stdout.strip()
 actual=run(['docker','inspect','--format','{{.Image}}',cid],capture_output=True).stdout.strip()
 expected=run(['docker','image','inspect','--format','{{.Id}}',image],capture_output=True).stdout.strip()
 if actual!=expected: raise RuntimeError(service+' is running an unexpected image')
 print(service,'HTTP 200, new image verified',flush=True)
print('Deployment complete.',flush=True)
