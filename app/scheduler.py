import logging
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import db, detector, pipeline, signatures, smartlead
from app.config import settings
from app.email_clean import to_plain_text
from app.thread_utils import guess_timezone
from app.translator import detect_language

log = logging.getLogger("scheduler")

_CATEGORY = {
    detector.Action.REPLY: "reply",
    detector.Action.FOLLOWUP: "followup",
    detector.Action.NONE: "waiting",
}


def _lead_language(lead: dict, thread) -> str | None:
    """Smartlead's own per-lead "Language Code" custom field when present —
    authoritative, and doesn't depend on guessing from a short message. Falls
    back to detecting from the lead's most recent message otherwise."""
    code = (lead.get("language_code") or "").strip().lower()[:2]
    if code:
        return code
    for msg in reversed(thread):
        if msg.kind == "reply":
            lang = detect_language(to_plain_text(msg.body))
            if lang:
                return lang
    return None


def compose_send_body(draft: dict, fallback_signature_html: str | None = None) -> str:
    """The actual email body to send: the (possibly edited) message plus the
    persona signature. Stored separately from body_html so contenteditable
    edits and the English translate/localize round-trip never touch it.
    Falls back to `fallback_signature_html` when the draft has none stored —
    older drafts created before the persona-fallback logic existed were
    saved with signature_html permanently NULL, since it's captured once at
    draft-creation time and never recomputed."""
    body = draft["body_html"] or ""
    sig = draft.get("signature_html") or fallback_signature_html
    log.info(
        "[SIG-DEBUG] compose_send_body: draft_id=%s body_len=%d stored_sig_len=%d used_fallback=%s final_sig_len=%d",
        draft.get("id"), len(body), len(draft.get("signature_html") or ""),
        not draft.get("signature_html") and bool(fallback_signature_html), len(sig or ""),
    )
    return f"{body}<br><br>{sig}" if sig else body

_scan_lock = threading.Lock()


def is_scan_running() -> bool:
    return _scan_lock.locked()


def _run_scan_locked() -> None:
    if _scan_lock.locked():
        log.info("scan already running, skipping this trigger")
        return
    with _scan_lock:
        try:
            run_daily_scan()
        except Exception:
            log.exception("scan failed")


def trigger_scan_in_background() -> bool:
    """Starts a scan in a background thread. Returns False (no-op) if one is
    already running, so a second click can't stack scans on top of each other."""
    if _scan_lock.locked():
        return False
    threading.Thread(target=_run_scan_locked, daemon=True).start()
    return True


def run_daily_scan() -> None:
    """Cheap pass: no Claude calls. Follow-ups are surfaced as candidates for
    Andrew to generate on demand (single or bulk) from the dashboard. Replies
    (a lead's message sitting unanswered) still auto-draft immediately, since
    that's the "respond fast to a live lead" path — see webhook.py for the
    primary trigger; this is the safety net for any missed webhook. Leads
    Smartlead's own classifier tagged Auto-Reply (out-of-office / autoresponder
    bounces) get pulled in too, with a lightweight "please forward this" nudge
    instead of the normal reply/follow-up pipeline."""
    log.info("daily scan starting")
    categories = smartlead.fetch_categories()
    interested_id = categories.get(settings.interested_category_name)
    autoreply_id = categories.get(settings.autoreply_category_name)
    if interested_id is None:
        log.warning("could not resolve '%s' category id, skipping scan", settings.interested_category_name)
        return
    if autoreply_id is None:
        log.warning(
            "could not resolve '%s' category id — auto-reply leads won't be pulled in this scan",
            settings.autoreply_category_name,
        )

    still_due_followups: set[tuple[int, int]] = set()

    for campaign in smartlead.list_campaigns():
        campaign_id = campaign.get("id")
        campaign_name = campaign.get("name", "")
        if campaign_id is None:
            continue
        for raw_lead in smartlead.list_campaign_leads(campaign_id):
            lead = smartlead.normalize_lead(raw_lead, campaign_id)
            if lead["id"] is None:
                continue
            is_autoreply = detector.category_matches(lead, autoreply_id)
            if not detector.is_interested(lead, interested_id) and not is_autoreply:
                continue
            if _process_lead(lead, campaign_name, is_autoreply):
                still_due_followups.add((lead["id"], lead["campaign_id"]))

    with db.db_session() as conn:
        db.clear_stale_open_candidates(conn, "followup", still_due_followups)

    log.info("daily scan done: %d leads still due for a follow-up", len(still_due_followups))


def _process_lead(lead: dict, campaign_name: str, is_autoreply: bool = False) -> bool:
    """Record the lead's inbox summary and return True if it's an open follow-up
    candidate. Every interested (or auto-reply) lead gets a leads_state row (so
    it shows in the inbox); replies still auto-draft, follow-ups still become
    candidates, auto-replies get a one-shot nudge draft."""
    with db.db_session() as conn:
        state = db.get_lead_state(conn, lead["id"], lead["campaign_id"])
        followup_count = state["followup_count"] if state else 0
        lead_status = state["status"] if state else "active"
        has_open = db.has_open_draft(conn, lead["id"], lead["campaign_id"])
        name_locked = bool(state["name_locked"]) if state else False

    base_fields = dict(
        email=lead["email"],
        company=lead["company_name"],
        website=lead["website"],
        timezone_guess=guess_timezone(campaign_name),
        interested=1,
        campaign_name=campaign_name,
    )
    # Skip once Andrew has manually corrected the name (api_set_lead_name) —
    # otherwise this scan (daily cron or "Rescan now") reverts it right back
    # to Smartlead's own first_name on the very next run.
    if not name_locked:
        base_fields["name"] = lead["first_name"]

    # Stopped/blacklisted leads stay out of the inbox — record the flag, skip the
    # (network) thread fetch, and don't touch their status.
    if lead_status in ("stopped", "blacklisted"):
        with db.db_session() as conn:
            db.upsert_lead_state(conn, lead["id"], lead["campaign_id"], **base_fields)
        return False

    thread = pipeline.fetch_normalized_thread(lead["campaign_id"], lead["id"])
    last_msg = thread[-1] if thread else None

    if is_autoreply:
        summary = dict(
            category="auto_reply",
            language=_lead_language(lead, thread),
            last_message_preview=to_plain_text(last_msg.body)[:200] if last_msg else None,
            last_message_at=last_msg.timestamp.isoformat() if last_msg else None,
            last_message_kind=last_msg.kind if last_msg else None,
        )
        with db.db_session() as conn:
            db.upsert_lead_state(conn, lead["id"], lead["campaign_id"], **base_fields, **summary)
            if (
                not has_open
                and last_msg is not None
                and not db.has_drafted_reply_to(conn, lead["id"], lead["campaign_id"], last_msg.message_id)
            ):
                log.info("drafting auto-reply nudge for lead %s", lead["id"])
                pipeline.create_draft(conn, lead, campaign_name, "autoreply", thread)
        return False

    decision = detector.decide(thread, followup_count, lead_status)
    summary = dict(
        category=_CATEGORY.get(decision.action, "waiting"),
        language=_lead_language(lead, thread),
        last_message_preview=to_plain_text(last_msg.body)[:200] if last_msg else None,
        last_message_at=last_msg.timestamp.isoformat() if last_msg else None,
        last_message_kind=last_msg.kind if last_msg else None,
    )

    with db.db_session() as conn:
        db.upsert_lead_state(
            conn, lead["id"], lead["campaign_id"], **base_fields, **summary
        )

        if has_open:
            # Already have an editable draft for this lead — leave it be.
            return False

        if decision.action == detector.Action.REPLY:
            log.info("drafting reply for lead %s: %s", lead["id"], decision.reason)
            pipeline.create_draft(conn, lead, campaign_name, "reply", thread)
            db.upsert_lead_state(
                conn, lead["id"], lead["campaign_id"], status="awaiting_reply"
            )
            return False

        if decision.action == detector.Action.FOLLOWUP:
            db.upsert_candidate(
                conn,
                lead["id"],
                lead["campaign_id"],
                "followup",
                lead_name=lead["first_name"],
                lead_company=lead["company_name"],
                lead_email=lead["email"],
                campaign_name=campaign_name,
                reason=decision.reason,
                last_message_preview=summary["last_message_preview"],
                last_message_at=summary["last_message_at"],
            )
            return True

        return False


def run_due_send_loop() -> None:
    with db.db_session() as conn:
        due = db.list_due_scheduled(conn)

    for draft in due:
        _send_due_draft(dict(draft))


def _send_due_draft(draft: dict) -> None:
    lead_id, campaign_id = draft["lead_id"], draft["campaign_id"]

    thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
    last = thread[-1] if thread else None

    # Race-check before sending. For a follow-up, the thread's last message is
    # normally *ours* (that's why a follow-up is due) — any reply appearing
    # since we drafted means the lead spoke up and this follow-up is now
    # stale, so abort unconditionally. For a reply/autoreply draft, the last
    # message is *always* the lead's (that's literally what we're replying
    # to) — comparing kind alone would abort every single send. Only abort
    # there if it's a *newer* reply than the one this draft actually answers
    # (draft["reply_message_id"] is the message_id it was drafted against).
    if last and last.kind == "reply":
        if draft["kind"] == "followup" or last.message_id != draft["reply_message_id"]:
            with db.db_session() as conn:
                db.update_draft(conn, draft["id"], status="stale")
                db.upsert_lead_state(conn, lead_id, campaign_id, status="awaiting_reply")
            log.info("draft %s aborted: lead has a newer reply than this draft addresses", draft["id"])
            return

    if settings.dry_run:
        log.info("[DRY_RUN] would send draft %s to lead %s", draft["id"], lead_id)
        with db.db_session() as conn:
            db.update_draft(conn, draft["id"], status="sent", sent_at=db.now_iso())
        return

    # Use the freshly-fetched thread's message identifiers rather than the
    # values stored on the draft: a draft can sit around (queued follow-up,
    # scheduled send) while the thread moves on underneath it — e.g. Andrew
    # replies directly from Smartlead's own inbox. Mixing a stale
    # reply_message_id/reply_email_time (pointing at an old message) with a
    # freshly-fetched stats_id confuses Smartlead's threading: a real send
    # went "To" the original sequence recipient instead of continuing the
    # actual thread, because only stats_id was being refreshed here. Keep
    # all three in sync off the same message, falling back to the draft's
    # stored values only if the thread fetch came back empty.
    reply_message_id = last.message_id if last else draft["reply_message_id"]
    reply_email_time = last.timestamp.isoformat() if last else draft["reply_email_time"]
    stats_id = last.stats_id if last else draft["reply_stats_id"]
    sender_email = detector.last_sender_email(thread)
    fallback_sig = signatures.get_signature_html(sender_email)
    cc = detector.next_reply_cc(thread, own_email=sender_email)
    send_body = compose_send_body(draft, fallback_sig)
    log.info(
        "[SIG-DEBUG] _send_due_draft: draft_id=%s sender=%s stats_id=%s send_body_len=%d "
        "contains_table_tag=%s send_body_tail=%r",
        draft["id"], sender_email, stats_id, len(send_body),
        "<table" in send_body, send_body[-120:],
    )
    resp = smartlead.reply_to_thread(
        campaign_id,
        send_body,
        reply_message_id,
        reply_email_time,
        stats_id,
        cc=cc,
    )
    log.info("[SIG-DEBUG] _send_due_draft: draft_id=%s smartlead response=%r", draft["id"], resp)

    with db.db_session() as conn:
        db.update_draft(conn, draft["id"], status="sent", sent_at=db.now_iso())
        if draft["kind"] == "followup":
            db.increment_followup_count(conn, lead_id, campaign_id)
    log.info("sent draft %s to lead %s", draft["id"], lead_id)


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone=timezone.utc)
    sched.add_job(
        _run_scan_locked,
        CronTrigger(hour=settings.daily_scan_hour_utc, minute=0),
        id="daily_scan",
    )
    sched.add_job(run_due_send_loop, "interval", minutes=1, id="due_send_loop")
    sched.start()
    _scheduler = sched
    return sched
