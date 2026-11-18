"""Opt-in OneBody auto replies: new reviewed drafts only, never old drafts."""
import hashlib
import json

from app import client_assets, db, reply_classifier, smartlead

SETTING = "onebody_auto_replies"
APPROVAL = "onebody_auto_reply:"
KIND = "auto_response"


def available():
    return client_assets.CLIENT_DIR == client_assets.REPO_ROOT / "clients" / "onebodyldn"


def enabled(conn=None):
    if not available():
        return False
    if conn is not None:
        return db.get_setting(conn, SETTING) == "true"
    with db.db_session() as current:
        return enabled(current)


def set_enabled(value):
    if not available() or not isinstance(value, bool):
        raise ValueError("Invalid automatic reply setting")
    with db.db_session() as conn:
        db.set_setting(conn, SETTING, "true" if value else "false")
        if not value:
            # Queued but not yet claimed replies become ordinary review drafts.
            conn.execute("UPDATE drafts SET status='pending', kind='reply', scheduled_at=NULL "
                         "WHERE kind=? AND status='scheduled'", (KIND,))
    return value


def fingerprint(draft):
    fields = ("lead_id", "campaign_id", "kind", "body_html", "thread_snapshot",
              "reply_message_id", "reply_email_time", "reply_stats_id", "sender_email",
              "signature_html", "attachments", "to_override", "cc_override")
    data = json.dumps({key: draft.get(key) for key in fields}, sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()


def schedule_reviewed(draft_id, thread):
    """Called only after a newly generated reply has passed OneBody review."""
    if not enabled() or not thread or thread[-1].kind != "reply" or not thread[-1].message_id:
        return False
    label, _ = reply_classifier.classify(thread[-1].body, fail_closed=True)
    if label == reply_classifier.DO_NOT_CONTACT:
        from app import scheduler
        with db.db_session() as conn:
            draft = db.get_draft(conn, draft_id)
        if draft:
            scheduler.record_do_not_contact(draft["lead_id"], draft["campaign_id"],
                                            email=draft["lead_email"] or "",
                                            message_id=thread[-1].message_id)
        return False
    if label != reply_classifier.INTERESTED:
        return False
    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if not enabled(conn) or not draft or draft["status"] != "pending" or draft["kind"] != "reply":
            return False
        draft = dict(draft)
        states = conn.execute(
            "SELECT status FROM leads_state WHERE lead_id=? OR (? != '' AND lower(trim(email))=lower(trim(?)))",
            (draft["lead_id"], draft["lead_email"] or "", draft["lead_email"] or ""),
        ).fetchall()
        if not states or any(row["status"] in ("booked", "blacklisted", "stopped") for row in states):
            return False
        if draft["reply_message_id"] != thread[-1].message_id:
            return False
        if conn.execute(
            "SELECT 1 FROM drafts WHERE lead_id=? AND campaign_id=? AND reply_message_id=? AND id<>? "
            "AND status IN ('scheduled','sending','sent') LIMIT 1",
            (draft["lead_id"], draft["campaign_id"], draft["reply_message_id"], draft_id),
        ).fetchone():
            return False
        draft["kind"] = KIND
        db.set_setting(conn, APPROVAL + str(draft_id), fingerprint(draft))
        db.update_draft(conn, draft_id, kind=KIND, status="scheduled", scheduled_at=db.now_iso())
    return True


def presend(draft, thread):
    """Fail closed if anything approved or any live state has changed."""
    if not enabled() or not thread or thread[-1].kind != "reply" or not thread[-1].message_id:
        return False
    if "@" not in (thread[-1].from_email or "") or "@" not in (draft.get("sender_email") or ""):
        return False
    snapshot = json.dumps([m.__dict__ for m in thread], default=str)
    if snapshot != draft.get("thread_snapshot") or thread[-1].message_id != draft.get("reply_message_id"):
        return False
    with db.db_session() as conn:
        if db.get_setting(conn, APPROVAL + str(draft["id"])) != fingerprint(draft):
            return False
        rows = conn.execute(
            "SELECT status FROM leads_state WHERE lead_id=? OR (? != '' AND lower(trim(email))=lower(trim(?)))",
            (draft["lead_id"], draft.get("lead_email") or "", draft.get("lead_email") or ""),
        ).fetchall()
        if not rows or any(row["status"] in ("booked", "blacklisted", "stopped") for row in rows):
            return False
        if conn.execute(
            "SELECT 1 FROM drafts WHERE lead_id=? AND campaign_id=? AND reply_message_id=? AND id<>? "
            "AND status IN ('sending','sent') LIMIT 1",
            (draft["lead_id"], draft["campaign_id"], draft["reply_message_id"], draft["id"]),
        ).fetchone():
            return False
    overview = smartlead.get_lead_campaign_overview(draft["lead_id"])
    mappings = overview["email_campaign_leads_mappings"]
    if not any(str(m.get("email_campaign_id")) == str(draft["campaign_id"]) and m.get("is_active") is not False for m in mappings):
        return False
    categories = smartlead.fetch_categories()
    if not categories:
        return False
    def norm(value):
        return "".join(c for c in str(value or "").lower() if c.isalnum())
    blocked = {"donotcontact", "notinterested", "unsubscribed", "leadoptedout", "weoptedout", "bounced", "wrongperson", "blacklisted", "meetingbooked", "outofoffice", "autoreply"}
    category_names = {str(value): norm(name) for name, value in categories.items()}
    for mapping in mappings:
        cid = mapping.get("lead_category_id")
        if cid and (str(cid) not in category_names or category_names[str(cid)] in blocked):
            return False
    return enabled()
