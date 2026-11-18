import json,hashlib
from pathlib import Path
from app import drafter,models_registry,client_assets

lead={'name':'Natalia','company':'TPXimpact','email':'natalia.riley@tpximpact.com',
      'sender_name':'Rebecca Bossick','campaign_name':'Priority Clinics - Walk 15min or less - Physio vs Massage',
      'custom_fields':{'offer':'massage','nearestClinic':'Aldgate East','companyNickname':'TPXimpact'}}
result=drafter.generate_draft('reply',lead,
    'Rebecca: I want to give you a free 45-minute sports massage at Aldgate East.\nNatalia: Yes please, can you send me the booking link?',
    use_web_search=False)
body=result.body_original
assert '4.99' in body and 'holds' in body and 'TPXimpact' in body
assert 'each person at TPXimpact gets one free session' in body
assert 'sports_massage_45_min' in body and 'VIP8401' in body
print(json.dumps({'model':models_registry.resolve(None),'draft':body,
    'assets':{str(p.relative_to(client_assets.REPO_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [client_assets.PROMPTS_DIR/'system.md',*client_assets.KNOWLEDGE_DIR.glob('*.md')]}},default=str))
