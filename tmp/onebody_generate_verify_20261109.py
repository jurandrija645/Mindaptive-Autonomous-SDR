import json

import httpx

from app import auto_replies, db, detector, pipeline
from app.config import settings

campaign_id, lead_id = 4235278, 4816227199
with httpx.Client(base_url='http://127.0.0.1:8080', timeout=60, follow_redirects=True) as client:
    client.post('/login', data={'password':settings.app_password}).raise_for_status()
    response = client.get(f'/api/leads/{campaign_id}/{lead_id}')
    response.raise_for_status()
    data = response.json()
    draft = data.get('draft')
    if draft:
        assert draft['status'] == 'pending' and not draft['scheduled_at']
        assert draft['body_html'].strip()
        assert draft['attachments'], 'Expected partnership brochure'
    print(json.dumps({key:data.get(key) for key in ['draft','generating','generation_error','review_hold']}))
with db.db_session() as conn:
    rows = [dict(r) for r in conn.execute(
        'SELECT id,status,kind,sent_at,scheduled_at FROM drafts WHERE campaign_id=? AND lead_id=? ORDER BY id DESC LIMIT 5',
        (campaign_id,lead_id))]
print(json.dumps({'automatic_replies':auto_replies.enabled(),'auto_followups':settings.auto_send_followups,'stored':rows}))
