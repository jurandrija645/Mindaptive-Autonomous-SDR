"""Run synthetic, unsent OneBody draft checks using the server's model key."""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["CLIENT_DIR"] = "clients/onebodyldn"
from app import client_assets, drafter, writing_rules

examples = [
    ("simple_yes", "[1] US: A free physio session for you.\n[2] LEAD: Yes please, how do I book?"),
    ("switch", "[1] US: Book physio with VIP8401. The £4.99 fee holds the slot. I've attached our brochure. Please share it with your team, each person gets one free session.\n[2] LEAD: Thanks, can I have a 20-minute sports massage instead?"),
    ("medical", "[1] US: A free physio session for you.\n[2] LEAD: I have severe new leg weakness. What is wrong and what treatment should I take?"),
]
if len(sys.argv) > 1:
    examples = [item for item in examples if item[0] == sys.argv[1]]
payload = {
    "system": drafter._load_system_prompt(),
    "review_source": Path("app/onebody_review.py").read_text(encoding="utf-8"),
    "rules": {n: client_assets.read_text("knowledge", n) for n in
              ("booking-options.md", "clinic-routing.md", "onebody-overview.md")},
    "voice": writing_rules.rules(),
    "examples": examples,
}
encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
remote = '''
import base64,json,types
import anthropic
from app import client_assets, writing_rules, drafter, models_registry
from app.config import settings
p=json.loads(base64.b64decode(PAYLOAD))
client_assets.read_text=lambda *parts, **kwargs:p["rules"].get(parts[-1], "")
writing_rules.rules=lambda:p["voice"]
mod=types.ModuleType("synthetic_review")
exec(p["review_source"], mod.__dict__)
mod.enabled=lambda: True
model=models_registry.default_model()
client=anthropic.Anthropic(api_key=settings.anthropic_api_key)
review_usage=[]
real_anthropic=anthropic.Anthropic
class CaptureMessages:
    def __init__(self, original): self.original=original
    def create(self, **kwargs):
        response=self.original.create(**kwargs)
        review_usage.append(response.usage.model_dump())
        return response
class CaptureClient:
    def __init__(self, **kwargs): self.messages=CaptureMessages(real_anthropic(**kwargs).messages)
mod.anthropic=types.SimpleNamespace(Anthropic=CaptureClient)
lead={"name":"Andy", "company":"Example Ltd", "sender_name":"Rebecca Bossick"}
for name,thread in p["examples"]:
    prompt=drafter._build_user_message("reply",lead,thread,use_web_search=False)
    response=client.messages.create(model=model,max_tokens=4096,system=p["system"],messages=[{"role":"user","content":prompt}])
    text="".join(x.text for x in response.content if x.type=="text")
    result=drafter.parse_draft_response(text)
    try:
        result=mod.review(result,thread,lead,model)
        verdict="approved"
        body=result.body_original
    except Exception as exc:
        verdict="held"
        body=type(exc).__name__ + ": " + str(exc)
    print(json.dumps({"case":name,"model":model,"review":verdict,"result":body,"generation_input_tokens":response.usage.input_tokens,"generation_output_tokens":response.usage.output_tokens,"review_usage":review_usage[-1] if review_usage else None}),flush=True)
'''.replace("PAYLOAD", repr(encoded))
result = subprocess.run(
    ["ssh", "-i", "C:/Users/AndRo/.ssh/leadaptive_droplet", "-o", "BatchMode=yes",
     "root@167.71.63.154", "cd /root/mindaptive-responder && docker compose exec -T app-onebodyldn python -"],
    input=remote, text=True, encoding="utf-8", timeout=300,
)
raise SystemExit(result.returncode)
