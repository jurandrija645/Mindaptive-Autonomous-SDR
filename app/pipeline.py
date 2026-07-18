import json
import logging

from app import autoreply_templates, db, drafter, signatures, smartlead, translator
from app.detector import last_sender_email, normalize_thread
from app.thread_utils import render_thread_text, text_to_html

log = logging.getLogger("pipeline")


def fetch_normalized_thread(campaign_id: int, lead_id: int):
    raw = smartlead.get_message_history(campaign_id, lead_id)
    return normalize_thread(raw)


def create_quick_draft(
    conn,
    lead: dict,
    campaign_name: str,
    thread,
    english_text: str,
) -> int:
    """Builds a follow-up draft straight from one of the canned quick-pick
    snippets (dashboard "quick follow-up" buttons) — skips drafter.generate_draft
    entirely (no system prompt, no knowledge base, no tools, no Sonnet/Opus
    call) and only spends tokens on a single cheap translation call, since the
    wording itself is already fixed and pre-approved. campaign_name is accepted
    for signature symmetry with create_draft but unused here."""
    del campaign_name
    lead_state = db.get_lead_state(conn, lead["id"], lead["campaign_id"])
    target_lang = lead_state["language"] if lead_state else None
    native_text = translator.localize_quick_text(english_text, target_lang)

    last_message = thread[-1]
    sender_email = last_sender_email(thread)
    signature_html = signatures.get_signature_html(sender_email)
    log.info(
        "[SIG-DEBUG] draft creation: lead_id=%s campaign_id=%s sender=%s signature_len=%d",
        lead["id"], lead["campaign_id"], sender_email, len(signature_html or ""),
    )
    # body_html is the message body only; the signature is stored separately and
    # appended unchanged at send time (scheduler.compose_send_body).
    body_html = text_to_html(native_text)

    draft_id = db.create_draft(
        conn,
        lead_id=lead["id"],
        campaign_id=lead["campaign_id"],
        kind="followup",
        triage_summary="Quick-pick follow-up (canned template, no draft generation).",
        body_html=body_html,
        body_translation=english_text,
        thread_snapshot=json.dumps([m.__dict__ for m in thread], default=str),
        reply_message_id=last_message.message_id,
        reply_email_time=last_message.timestamp.isoformat(),
        reply_stats_id=last_message.stats_id,
        status="pending",
        lead_name=lead.get("first_name") or lead.get("name") or "",
        lead_company=lead.get("company_name") or lead.get("company") or "",
        lead_email=lead.get("email"),
        sender_email=sender_email,
        signature_html=signature_html or None,
    )
    return draft_id


def create_manual_draft(conn, lead: dict, thread) -> int:
    """Blank draft for Andrew to write from scratch — no drafter.generate_draft
    call, no translation, nothing: just the same reply-threading metadata
    (reply_message_id/time/stats_id, signature, thread_snapshot) every other
    draft gets, so Send/Schedule work identically once he's typed something in."""
    last_message = thread[-1]
    sender_email = last_sender_email(thread)
    signature_html = signatures.get_signature_html(sender_email)
    log.info(
        "[SIG-DEBUG] draft creation: lead_id=%s campaign_id=%s sender=%s signature_len=%d",
        lead["id"], lead["campaign_id"], sender_email, len(signature_html or ""),
    )

    # Blank body; the signature is stored separately and appended unchanged at
    # send time (scheduler.compose_send_body).
    body_html = ""

    draft_id = db.create_draft(
        conn,
        lead_id=lead["id"],
        campaign_id=lead["campaign_id"],
        kind="manual",
        triage_summary="Written directly — no AI generation.",
        body_html=body_html,
        body_translation=None,
        thread_snapshot=json.dumps([m.__dict__ for m in thread], default=str),
        reply_message_id=last_message.message_id,
        reply_email_time=last_message.timestamp.isoformat(),
        reply_stats_id=last_message.stats_id,
        status="pending",
        lead_name=lead.get("first_name") or lead.get("name") or "",
        lead_company=lead.get("company_name") or lead.get("company") or "",
        lead_email=lead.get("email"),
        sender_email=sender_email,
        signature_html=signature_html or None,
    )
    return draft_id


def _create_static_autoreply_draft(conn, lead: dict, thread, native_text: str) -> int:
    """Zero-token draft for an Auto-Reply nudge: the message is fully generic
    and pre-translated (see app/autoreply_templates.py), keyed off Smartlead's
    own `language_code` custom field — no Claude call at all."""
    last_message = thread[-1]
    sender_email = last_sender_email(thread)
    signature_html = signatures.get_signature_html(sender_email)
    log.info(
        "[SIG-DEBUG] draft creation: lead_id=%s campaign_id=%s sender=%s signature_len=%d",
        lead["id"], lead["campaign_id"], sender_email, len(signature_html or ""),
    )
    # body_html is the message body only; the signature is stored separately and
    # appended unchanged at send time (scheduler.compose_send_body).
    body_html = text_to_html(native_text)

    return db.create_draft(
        conn,
        lead_id=lead["id"],
        campaign_id=lead["campaign_id"],
        kind="autoreply",
        triage_summary="Auto-reply nudge (pre-written template, no draft generation).",
        body_html=body_html,
        body_translation=autoreply_templates.ENGLISH_TEXT,
        thread_snapshot=json.dumps([m.__dict__ for m in thread], default=str),
        reply_message_id=last_message.message_id,
        reply_email_time=last_message.timestamp.isoformat(),
        reply_stats_id=last_message.stats_id,
        status="pending",
        lead_name=lead.get("first_name") or lead.get("name") or "",
        lead_company=lead.get("company_name") or lead.get("company") or "",
        lead_email=lead.get("email"),
        sender_email=sender_email,
        signature_html=signature_html or None,
    )


def create_draft(
    conn,
    lead: dict,
    campaign_name: str,
    kind: str,
    thread,
    steering_note: str | None = None,
    model: str | None = None,
    use_web_search: bool | None = None,
) -> int:
    # A steering note means Andrew explicitly wants a customized nudge for
    # this lead — skip the generic template and go to Claude for that case.
    if kind == "autoreply" and not steering_note:
        static_text = autoreply_templates.get(lead.get("language_code"))
        if static_text:
            return _create_static_autoreply_draft(conn, lead, thread, static_text)

    thread_text = render_thread_text(thread)
    lead_payload = {
        "name": lead.get("first_name") or lead.get("name") or "",
        "company": lead.get("company_name") or lead.get("company") or "",
        "email": lead.get("email"),
        "website": lead.get("website") or lead.get("company_url") or "",
        "campaign_name": campaign_name,
        "custom_fields": lead.get("custom_fields"),
    }

    prior_research = None
    if kind != "autoreply":
        lead_state = db.get_lead_state(conn, lead["id"], lead["campaign_id"])
        if lead_state and lead_state["research_summary"]:
            prior_research = lead_state["research_summary"]

    if use_web_search is None:
        # Auto (no explicit caller choice, e.g. the daily-scan/webhook paths
        # that don't go through the dashboard's toggle): skip re-researching
        # once we already have research for this lead, rather than just
        # asking Claude nicely not to re-run the tools.
        use_web_search = not bool(prior_research)

    result = drafter.generate_draft(
        kind, lead_payload, thread_text, steering_note, prior_research,
        model=model, use_web_search=use_web_search,
    )
    last_message = thread[-1]

    if result.lead_research:
        db.upsert_lead_state(
            conn, lead["id"], lead["campaign_id"],
            research_summary=result.lead_research, researched_at=db.now_iso(),
        )

    sender_email = last_sender_email(thread)
    signature_html = signatures.get_signature_html(sender_email)
    log.info(
        "[SIG-DEBUG] draft creation: lead_id=%s campaign_id=%s sender=%s signature_len=%d",
        lead["id"], lead["campaign_id"], sender_email, len(signature_html or ""),
    )
    # body_html is the message body only; the signature is stored separately and
    # appended unchanged at send time (scheduler.compose_send_body).
    body_html = text_to_html(result.body_original)

    draft_id = db.create_draft(
        conn,
        lead_id=lead["id"],
        campaign_id=lead["campaign_id"],
        kind=kind,
        triage_summary=result.triage_summary,
        body_html=body_html,
        body_translation=result.body_translation,
        thread_snapshot=json.dumps([m.__dict__ for m in thread], default=str),
        reply_message_id=last_message.message_id,
        reply_email_time=last_message.timestamp.isoformat(),
        reply_stats_id=last_message.stats_id,
        status="pending",
        lead_name=lead_payload["name"],
        lead_company=lead_payload["company"],
        lead_email=lead_payload["email"],
        sender_email=sender_email,
        signature_html=signature_html or None,
    )
    return draft_id
