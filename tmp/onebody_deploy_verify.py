import json
import httpx
from app import auto_replies, booking_guard, db, models_registry, onebody_review
from app.config import settings

with httpx.Client(base_url='http://127.0.0.1:8080', follow_redirects=True, timeout=10) as client:
    login = client.post('/login', data={'password': settings.app_password})
    page = client.get('/dashboard')
    api = client.get('/api/auto-replies')
    data = api.json()
    print(json.dumps({
        'dashboard_status': page.status_code,
        'toggle_present': 'id="auto-replies-toggle"' in page.text,
        'toggle_api_status': api.status_code,
        'auto_replies': data.get('enabled'),
        'draft_model': models_registry.default_model(),
        'review_enabled': onebody_review.enabled(),
        'review_hold_support': hasattr(onebody_review, 'held'),
        'suppression_guard': hasattr(booking_guard, 'is_locally_suppressed'),
        'dry_run': settings.dry_run,
    }))
    assert page.status_code == 200 and 'id="auto-replies-toggle"' in page.text
    assert api.status_code == 200 and data.get('enabled') is False
    assert models_registry.default_model() == 'claude-sonnet-5-5'
    assert onebody_review.enabled() and hasattr(onebody_review, 'held')
    assert hasattr(booking_guard, 'is_locally_suppressed')
