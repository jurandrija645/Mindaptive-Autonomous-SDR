import logging
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import db, detector, pipeline, smartlead
from app.config import settings
from app.thread_utils import guess_timezone

log = logging.getLogger("scheduler")

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
    primary trigger; this is the safety net for any missed webhook."""
    log.info("daily scan starting")
    categories = smartlead.fetch_categories()
    interested_id = categories.get(settings.interested_category_name)
    if interested_id is None:
        log.warning("could not resolve '%s' category id, skipping scan", settings.interested_category_name)
        return

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
            if not detector.is_interested(lead, interested_id):
                continue
            if _process_lead(lead, campaign_name):
                still_due_followups.add((lead["id"], lead["campaign_id"]))

    with db.db_session() as conn:
        db.clear_stale_open_candidates(conn, "followup", still_due_followups)

    log.info("daily scan done: %d leads still due for a follow-up", len(still_due_followups))


def _process_lead(lead: dict, campaign_name: str) -> bool:
    """Returns True if this lead is currently an open follow-up candidate."""
    with db.db_session() as conn:
        if db.has_open_draft(conn, lead["id"], lead["campaign_id"]):
            return False
        state = db.get_lead_state(conn, lead["id"], lead["campaign_id"])
        followup_count = state["followup_count"] if state else 0
        lead_status = state["status"] if state else "active"

        db.upsert_lead_state(
            conn,
            lead["id"],
            lead["campaign_id"],
            email=lead["email"],
            name=lead["first_name"],
            company=lead["company_name"],
            website=lead["website"],
            timezone_guess=guess_timezone(campaign_name),
        )

        if lead_status in ("stopped", "blacklisted"):
            return False

        thread = pipeline.fetch_normalized_thread(lead["campaign_id"], lead["id"])
        decision = detector.decide(thread, followup_count, lead_status)

        if decision.action == detector.Action.NONE:
            return False

        if decision.action == detector.Action.REPLY:
            existing_candidate = conn.execute(
                "SELECT id FROM candidates WHERE lead_id = ? AND campaign_id = ? AND kind = 'reply' AND status = 'open'",
                (lead["id"], lead["campaign_id"]),
            ).fetchone()
            if existing_candidate is None:
                log.info("drafting reply for lead %s: %s", lead["id"], decision.reason)
                pipeline.create_draft(conn, lead, campaign_name, "reply", thread)
                db.upsert_lead_state(conn, lead["id"], lead["campaign_id"], status="awaiting_reply")
            return False

        last_msg = thread[-1]
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
            last_message_preview=last_msg.body[:200],
            last_message_at=last_msg.timestamp.isoformat(),
        )
        return True


def run_due_send_loop() -> None:
    with db.db_session() as conn:
        due = db.list_due_scheduled(conn)

    for draft in due:
        _send_due_draft(dict(draft))


def _send_due_draft(draft: dict) -> None:
    lead_id, campaign_id = draft["lead_id"], draft["campaign_id"]

    thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
    if thread and thread[-1].kind == "reply":
        with db.db_session() as conn:
            db.update_draft(conn, draft["id"], status="stale")
            db.upsert_lead_state(conn, lead_id, campaign_id, status="awaiting_reply")
        log.info("draft %s aborted: lead replied before scheduled send", draft["id"])
        return

    if settings.dry_run:
        log.info("[DRY_RUN] would send draft %s to lead %s", draft["id"], lead_id)
        with db.db_session() as conn:
            db.update_draft(conn, draft["id"], status="sent", sent_at=db.now_iso())
        return

    smartlead.reply_to_thread(
        campaign_id,
        lead_id,
        draft["body_html"],
        draft["reply_message_id"],
        draft["reply_email_time"],
    )

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
