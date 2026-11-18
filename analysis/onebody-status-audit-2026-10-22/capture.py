import pathlib,subprocess,sys
out=pathlib.Path(__file__).resolve().parent
script=(out/'remote_snapshot.py').read_text(encoding='utf-8-sig')
p=subprocess.Popen(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app-onebodyldn python -'],stdin=subprocess.PIPE,stdout=(out/'snapshot.json').open('w',encoding='utf-8'),stderr=None,text=True,encoding='utf-8')
p.communicate(script,timeout=600)
if p.returncode: raise RuntimeError('Snapshot failed')
print('Snapshot saved')
