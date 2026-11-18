import json

import httpx

from app import auto_replies, db, onebody_review
from app.config import settings

campaign_id, lead_id = 4235278, 4816227199
assert not auto_replies.enabled(), 'Automatic replies changed since inspection'
assert not settings.auto_send_followups, 'Automatic follow-ups changed since inspection'
with db.db_session() as conn:
    lead = db.get_lead_state(conn, lead_id, campaign_id)
    existing = db.get_open_draft(conn, lead_id, campaign_id)
    assert lead and lead['status'] not in ('booked', 'blacklisted', 'stopped')
with httpx.Client(base_url='http://127.0.0.1:8080', timeout=60, follow_redirects=True) as client:
    login = client.post('/login', data={'password': settings.app_password})
    login.raise_for_status()
    if existing is None or (existing['status'] == 'pending' and onebody_review.warning(existing['id'])):
        response = client.post(f'/api/leads/{campaign_id}/{lead_id}/generate', json={'use_web_search': False})
        response.raise_for_status()
        print(json.dumps({'generate':response.json()}))
    else:
        print(json.dumps({'existing_draft':existing['id'], 'status':existing['status']}))
