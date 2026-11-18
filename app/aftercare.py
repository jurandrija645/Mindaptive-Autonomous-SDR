"""Explicit, expiring approval for a booked customer's individual care email.

No blanket booked-lead switch. An operator pins one exact draft, recipient,
signature and attachment to a window of at most two hours. Outreach and native
campaigns stay frozen. Editing the approved email invalidates the permission.
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from app import client_assets, db, detector, library, smartlead
from app.config import settings

PREFIX = "booked_aftercare:"
FIELDS = ("id", "lead_id", "campaign_id", "kind", "body_html", "signature_html",
          "sender_email", "to_override", "cc_override", "attachments",
          "reply_message_id", "reply_email_time", "reply_stats_id", "scheduled_at")


def utcnow():
    return datetime.now(timezone.utc)


def _dt(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("aftercare timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def fingerprint(draft):
    row = dict(draft)
    data = {k: row.get(k) for k in FIELDS}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def authorize(conn, draft_id, *, starts_at, expires_at, approved_by, attachment_sha256):
    """Operator-only helper; not invoked by generation or category changes."""
    draft = dict(db.get_draft(conn, draft_id))
    start, end = _dt(starts_at), _dt(expires_at)
    if client_assets.CLIENT_DIR.name != "onebodyldn":
        raise ValueError("OneBody aftercare approval cannot be used for another client")
    if not (0 < (end - start).total_seconds() <= 7200) or end <= utcnow():
        raise ValueError("aftercare requires a future window no longer than two hours")
    if not start <= _dt(draft["scheduled_at"]) < end:
        raise ValueError("scheduled time is outside the approved window")
    if draft["kind"] != "aftercare" or draft["status"] not in ("pending", "scheduled"):
        raise ValueError("only a new aftercare draft can be approved")
    if not approved_by or not draft.get("to_override") or not draft.get("signature_html"):
        raise ValueError("approval requires a named owner, recipient and signature")
    if not re.fullmatch(r"[a-f0-9]{64}", attachment_sha256):
        raise ValueError("attachment checksum is required")
    approval = dict(starts_at=start.isoformat(), expires_at=end.isoformat(),
                    approved_by=approved_by, approved_at=utcnow().isoformat(),
                    fingerprint=fingerprint(draft), attachment_sha256=attachment_sha256)
    db.set_setting(conn, PREFIX + str(draft_id), json.dumps(approval))


def approval_for(conn, draft, *, for_send=False, now=None):
    """None means fail closed. Before the window, only preserve the queue."""
    draft = dict(draft)
    if draft.get("kind") != "aftercare" or client_assets.CLIENT_DIR.name != "onebodyldn":
        return None
    try:
        approval = json.loads(db.get_setting(conn, PREFIX + str(draft["id"])) or "null")
        if not isinstance(approval, dict) or not approval.get("approved_by"):
            return None
        start, end = _dt(approval["starts_at"]), _dt(approval["expires_at"])
        now = now or utcnow()
        if not (0 < (end - start).total_seconds() <= 7200) or now >= end:
            return None
        if for_send and now < start:
            return None
        if not start <= _dt(draft["scheduled_at"]) < end:
            return None
        if fingerprint(draft) != approval["fingerprint"]:
            return None
        current = db.get_draft(conn, draft["id"])
        if current is None or current["status"] not in ("pending", "scheduled", "sending"):
            return None
        if fingerprint(current) != approval["fingerprint"]:
            return None
        return approval
    except (ValueError, KeyError, TypeError):
        return None


def allow_send(draft, thread):
    """Revalidate the exact approval and real contact status immediately before send."""
    with db.db_session() as conn:
        approval = approval_for(conn, draft, for_send=True)
        states = conn.execute(
            "SELECT status FROM leads_state WHERE lead_id = ? OR lower(email) = lower(?)",
            (draft["lead_id"], draft.get("lead_email") or ""),
        ).fetchall()
    if not approval or not states or any(r["status"] in ("blacklisted", "stopped") for r in states):
        return False
    if not any(r["status"] == "booked" for r in states):
        return False
    if not thread or thread[-1].message_id != draft.get("reply_message_id"):
        return False
    if detector.last_sender_email(thread).lower() != (draft.get("sender_email") or "").lower():
        return False
    attachments = json.loads(draft.get("attachments") or "[]")
    if len(attachments) != 1:
        return False
    resolved = library.resolve(attachments[0].get("slug", ""))
    if not resolved or hashlib.sha256(resolved[0].read_bytes()).hexdigest() != approval["attachment_sha256"]:
        return False
    # Read failures raise and the scheduler retries only until approval expires.
    overview = smartlead.get_lead_campaign_overview(draft["lead_id"])
    mappings = overview["email_campaign_leads_mappings"]
    if not any(str(m.get("email_campaign_id")) == str(draft["campaign_id"]) and m.get("is_active") is not False for m in mappings):
        return False
    categories = {str(v): re.sub(r"[^a-z0-9]", "", k.lower()) for k, v in smartlead.fetch_categories().items()}
    booked = re.sub(r"[^a-z0-9]", "", settings.meeting_booked_category_name.lower())
    if booked not in categories.values():
        raise smartlead.SmartleadError("Could not verify booked status for the approved aftercare email")
    mapped = [categories.get(str(m.get("lead_category_id")), "") for m in mappings]
    if booked not in mapped or any(c in {"donotcontact", "notinterested", "unsubscribed", "leadoptedout", "bounced", "wrongperson", "blacklisted"} for c in mapped):
        return False
    with db.db_session() as conn:
        return approval_for(conn, draft, for_send=True) is not None
