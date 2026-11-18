import json
from pathlib import Path

import httpx

from app.config import settings

with httpx.Client(base_url='http://127.0.0.1:8080',timeout=45,follow_redirects=True) as client:
    client.post('/login',data={'password':settings.app_password}).raise_for_status()
    dashboard = client.get('/dashboard')
    dashboard.raise_for_status()
    detail = client.get('/api/leads/4414344/4907435002')
    detail.raise_for_status()
print(json.dumps({'html':dashboard.text, 'inbox':json.loads(Path('/tmp/onebody-perf-inbox.json').read_text()), 'detail':detail.json()}))
