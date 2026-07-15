import json

from app import db, drafter, smartlead
from app.detector import normalize_thread
from app.thread_utils import render_thread_text, text_to_html


def fetch_normalized_thread(campaign_id: int, lead_id: int):
    raw = smartlead.get_message_history(campaign_id, lead_id)
    return normalize_thread(raw)


def create_draft(conn, lead: dict, campaign_name: str, kind: str, thread, steering_note: str | None = None) -> int:
    thread_text = render_thread_text(thread)
    lead_payload = {
        "name": lead.get("first_name") or lead.get("name") or "",
        "company": lead.get("company_name") or lead.get("company") or "",
        "email": lead.get("email"),
        "website": lead.get("website") or lead.get("company_url") or "",
        "campaign_name": campaign_name,
        "custom_fields": lead.get("custom_fields"),
    }

    result = drafter.generate_draft(kind, lead_payload, thread_text, steering_note)
    last_message = thread[-1]

    draft_id = db.create_draft(
        conn,
        lead_id=lead["id"],
        campaign_id=lead["campaign_id"],
        kind=kind,
        triage_summary=result.triage_summary,
        body_html=text_to_html(result.body_original),
        body_translation=result.body_translation,
        thread_snapshot=json.dumps([m.__dict__ for m in thread], default=str),
        reply_message_id=last_message.message_id,
        reply_email_time=last_message.timestamp.isoformat(),
        status="pending",
        lead_name=lead_payload["name"],
        lead_company=lead_payload["company"],
        lead_email=lead_payload["email"],
    )
    return draft_id
