import json
import logging

from app import (
    autoreply_templates, db, drafter, lead_language, models_registry, signatures,
    smartlead, translator,
)
from app.config import settings
from app.detector import last_sender_email, normalize_thread
from app.thread_utils import render_thread_text, text_to_html

log = logging.getLogger("pipeline")


# The language rules live in app/lead_language.py, which is the one place that
# ranks the three sources (Smartlead's per-lead field, the thread, the cached
# column). Re-exported because the docs and callers name it here.
thread_language = lead_language.thread_language


def fetch_normalized_thread(campaign_id: int, lead_id: int):
    raw = smartlead.get_message_history(campaign_id, lead_id)
    thread = normalize_thread(raw)
    cache_normalized_thread(campaign_id, lead_id, thread)
    return thread


def cache_normalized_thread(campaign_id: int, lead_id: int, thread) -> None:
    """Persist a complete thread after any caller has paid to fetch it."""
    if not thread:
        return
    last = thread[-1]
    payload = json.dumps([m.__dict__ for m in thread], default=str)
    with db.db_session() as conn:
        db.put_lead_thread(
            conn,
            lead_id,
            campaign_id,
            payload,
            last.message_id,
            last.timestamp.isoformat(),
        )


def _quick_language_note(
    target_lang: str | None, source: str, english_text: str, native_text: str
) -> tuple[str, str | None]:
    """`(triage line, warning)` for a quick-pick draft.

    Both halves exist because this path can only fail one way — by quietly
    sending the English. `localize_quick_text` returns its input unchanged when
    it has no language to work with and again when the call fails, so a template
    mailed in English to a German lead looked exactly like one that had been
    localized properly. The triage line records what happened on the draft row;
    the warning is what the dashboard puts in front of Andrew *before* he clicks
    Send, which the triage line never did — it is stored but has never been
    rendered anywhere in the UI.
    """
    base = "Quick-pick follow-up (canned template, no draft generation)"
    if not target_lang:
        log.warning("quick draft has no language for this lead — sending English")
        return (
            f"{base}. English — nothing on this lead says which language they read.",
            "Sent as English: nothing on this lead says which language they read — "
            "no language field in Smartlead, and nothing readable in the thread. "
            "Check the message before sending.",
        )
    name = translator.language_name(target_lang) or target_lang
    if target_lang.lower() == "en":
        return f"{base}. English ({source}).", None
    if native_text.strip() == english_text.strip():
        log.warning("quick draft not localized to %s — sending English", target_lang)
        return (
            f"{base}. NOT localized — this is still English, not {name}.",
            f"This is still English: the translation into {name} didn't come back. "
            "Regenerate the template, or pick a different model above.",
        )
    return f"{base}. Written in {name} ({source}).", None


def create_quick_draft(
    conn,
    lead: dict,
    campaign_name: str,
    thread,
    english_text: str,
    model: str | None = None,
) -> tuple[int, str | None]:
    """Builds a follow-up draft straight from one of the canned quick-pick
    snippets (dashboard "quick follow-up" buttons) — skips drafter.generate_draft
    entirely (no system prompt, no knowledge base, no tools, no Sonnet/Opus
    call) and only spends tokens on a single cheap translation call, since the
    wording itself is already fixed and pre-approved. campaign_name is accepted
    for signature symmetry with create_draft but unused here.

    Returns `(draft_id, warning)`; the warning is non-None only when the message
    is going out in English and shouldn't be."""
    del campaign_name
    lead_state = db.get_lead_state(conn, lead["id"], lead["campaign_id"])
    # Live evidence first, the cached column last (see app/lead_language.py).
    # This used to read leads_state.language and stop there, which is how a
    # lead whose stored code had drifted to 'en' — 11 of 203 measured against
    # the live API — got every template mailed to them in English, with the
    # Dutch thread it was a reply to sitting right there in the same request.
    target_lang, source = lead_language.resolve(
        thread=thread, lead=lead, lead_row=lead_state
    )
    stored = lead_state["language"] if lead_state else None
    if target_lang and target_lang != stored:
        # Heal the column so the rest of the app (the auto-reply nudge, the
        # drafter's language line, the next template) stops reading the stale
        # value. Only when the answer came from somewhere better than the
        # column itself, which resolve() guarantees by ordering.
        log.info(
            "lead %s/%s language %s -> %s (from %s)",
            lead["campaign_id"], lead["id"], stored, target_lang, source,
        )
        db.upsert_lead_state(
            conn, lead["id"], lead["campaign_id"], language=target_lang
        )
    native_text = translator.localize_quick_text(english_text, target_lang, model=model)
    triage, warning = _quick_language_note(
        target_lang, source, english_text, native_text
    )

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

    # The quick-pick button answers whatever's due, not only cadence
    # follow-ups — including a lead who just replied. scheduler._send_due_draft's
    # race-check unconditionally stales any "followup"-kind draft the moment the
    # thread's last message is a reply (that's how it knows a real follow-up went
    # stale), so a quick draft that's actually answering that reply must be
    # stamped "reply" or it aborts its own send every time, silently.
    kind = "reply" if last_message.kind == "reply" else "followup"

    draft_id = db.create_draft(
        conn,
        lead_id=lead["id"],
        campaign_id=lead["campaign_id"],
        kind=kind,
        triage_summary=triage,
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
    return draft_id, warning


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
    and pre-translated (see app/autoreply_templates.py), keyed off the lead's
    resolved language — no Claude call at all."""
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
    base_draft: str | None = None,
) -> int:
    lead_state = db.get_lead_state(conn, lead["id"], lead["campaign_id"])
    # One resolution for both the nudge template and the prompt below, so the
    # language a draft is written in can't disagree with the language its
    # canned variant would have used. Live evidence first — see lead_language.
    language, language_source = lead_language.resolve(
        thread=thread, lead=lead, lead_row=lead_state
    )

    # A steering note means Andrew explicitly wants a customized nudge for
    # this lead — skip the generic template and go to Claude for that case.
    if kind == "autoreply" and not steering_note:
        static_text = autoreply_templates.get(language)
        if static_text:
            return _create_static_autoreply_draft(conn, lead, thread, static_text)

    thread_text = render_thread_text(thread)
    # Resolve the sending persona before the model runs, not just at signature
    # time: clients whose approved templates end with a booking link need that
    # person's own link inside the body, and the personas have different ones.
    sender_email = last_sender_email(thread)
    lead_payload = {
        "name": lead.get("first_name") or lead.get("name") or "",
        "company": lead.get("company_name") or lead.get("company") or "",
        "email": lead.get("email"),
        "website": lead.get("website") or lead.get("company_url") or "",
        "campaign_name": campaign_name,
        "custom_fields": lead.get("custom_fields"),
        "sender_name": signatures.persona_name(sender_email),
        "calendar_link": signatures.calendar_link_for(sender_email),
        # Told to the model outright rather than left for it to infer from the
        # thread (prompts/system.md §9). It got this right most of the time and
        # wrong the rest, which is the worst version: the app knows the answer,
        # so it should say it. Blank when nothing knows — the §9 rule still
        # applies and the model reads the thread as before.
        "language": language,
        "language_name": translator.language_name(language) if language else "",
    }
    log.info(
        "drafting %s for lead %s/%s in %s (from %s)",
        kind, lead["campaign_id"], lead["id"], language or "?", language_source,
    )

    prior_research = None
    followup_stage = None
    if kind != "autoreply":
        if lead_state and lead_state["research_summary"]:
            prior_research = lead_state["research_summary"]
        # Follow-up stage steering (see drafter._build_user_message): the last
        # follow-up before the cap becomes the Section 12 "closing this file"
        # breakup; anything past the cap is a revival touch (detector only
        # surfaces those after REVIVE_AFTER_DAYS of silence).
        if kind == "followup" and lead_state:
            count = lead_state["followup_count"] or 0
            if count >= settings.max_followups:
                followup_stage = "revive"
            elif count == settings.max_followups - 1:
                followup_stage = "final"

    if use_web_search is None:
        # Auto (no explicit caller choice, e.g. the daily-scan/webhook paths
        # that don't go through the dashboard's toggle): skip re-researching
        # once we already have research for this lead, rather than just
        # asking Claude nicely not to re-run the tools.
        use_web_search = not bool(prior_research)

    result = drafter.generate_draft(
        kind, lead_payload, thread_text, steering_note, prior_research,
        model=model, use_web_search=use_web_search, followup_stage=followup_stage,
        previous_draft=base_draft,
    )
    # Record the model actually used (drafter falls back to the default for
    # anything not in the picker) — feeds the Stats view's cost proxy.
    resolved_model = models_registry.resolve(model)
    return store_draft_result(conn, lead, kind, thread, result, model=resolved_model)


def store_draft_result(conn, lead: dict, kind: str, thread, result, model: str | None = None) -> int:
    """Persist a drafter.DraftResult as a pending draft row (plus the lead's
    research summary). Shared by create_draft above and the Batch API result
    handler (app/batch_gen.py) so both paths store byte-identical drafts."""
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
        lead_name=lead.get("first_name") or lead.get("name") or "",
        lead_company=lead.get("company_name") or lead.get("company") or "",
        lead_email=lead.get("email"),
        sender_email=sender_email,
        signature_html=signature_html or None,
        model=model,
    )
    return draft_id
