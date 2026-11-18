import json,pathlib,subprocess
OUT=pathlib.Path(__file__).resolve().parent
plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
items=[x for x in plan if x['apply']]
script='BUNDLE = '+repr(items)+'\n'+(OUT/'remote_apply.py').read_text(encoding='utf-8')
(OUT/'execution-bundle.json').write_text(json.dumps(items,ensure_ascii=False),encoding='utf-8')
with (OUT/'applied.json').open('w',encoding='utf-8') as output:
 p=subprocess.Popen(['ssh','-i','C:/Users/AndRo/.ssh/leadaptive_droplet','-o','BatchMode=yes','root@167.71.63.154','cd /root/mindaptive-responder && docker compose exec -T app-onebodyldn python -'],stdin=subprocess.PIPE,stdout=output,text=True,encoding='utf-8')
 p.communicate(script,timeout=900)
 if p.returncode:raise RuntimeError('Remote apply failed')
print('Applied result saved')
