"""Subsequences: follow-up emails Andrew writes once, sent on his timing.

Andrew sends the first message himself, then moves the lead into a Smartlead
category such as "Interested 55". A sequence bound to that category sends its
steps as threaded replies from the same mailbox, each one carrying the
persona's HTML signature, a set number of days apart, at a random minute of
the lead's morning. Any reply or booking stops it at once. See
docs/subsequences-plan.md for the reasoning behind each rule.

Why not Smartlead's own subsequences: a Smartlead signature belongs to the
mailbox, so the HTML signature would also go out on every cold first touch.
The send path here already appends it at send time (scheduler.compose_send_body).

Shape of the thing:

- Only the NEXT step exists as a `drafts` row (kind='sequence', status
  'scheduled'). Everything that already stales open drafts on a reply or a
  booking therefore protects sequence steps too, the Scheduled tab shows the
  exact text, and sending goes through scheduler._send_due_draft unchanged
  apart from `presend_check`.
- Stopping is two layers. db.stop_sequence_enrollments is called from inside
  db.mark_lead_replied / mark_lead_booked / mark_lead_do_not_contact, so every
  path that records one of those stops the sequence. And `presend_check`
  re-reads the thread and Smartlead's live category right before each send,
  so a missed signal costs a delay, never an email.
- Smartlead category writes (Interested after a reply, the finish category,
  the trigger again on resume) are queued on the enrollment and written by
  `run_housekeeping`, never inline in a webhook or a send.
"""

import html
import json
import logging
import random
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app import db, detector, message_templates, signatures, smartlead
from app.config import settings
from app.thread_utils import FALLBACK_TIMEZONE, guess_timezone

log = logging.getLogger("sequences")

# Every US lead gets the same window, whatever the sequence says: 08:00-10:00
# Eastern is 05:00-07:00 Pacific, so it is in the inbox before the morning
# check on both coasts (Andrew's call, 2026-09-16).
US_SEND_WINDOW = ("America/New_York", "08:00", "10:00")
_US_ZONES = {
    "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "America/Detroit", "Pacific/Honolulu",
}

DEFAULT_FINISH_CATEGORY = "Sequence finished"

# How long a queued move back to Interested waits after a reply stopped the
# sequence. The webhook's classifier normally answers in seconds; if it says
# the reply was an out-of-office, the move is cancelled and the sequence is
# paused instead, so it can resume in the trigger category.
CATEGORY_PUSH_DELAY = timedelta(minutes=3)

# A Smartlead category read that disagrees with a fresh enrollment is most
# likely a listing fetched before Andrew's own category change landed.
ENROLL_GRACE = timedelta(minutes=15)

# A step claimed for sending that never resolved: the send may or may not have
# reached Smartlead, so it is surfaced for a human instead of retried.
STUCK_SENDING_AFTER = timedelta(minutes=30)

OPEN_STATES = db.OPEN_ENROLLMENT_STATES
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class SequenceError(ValueError):
    """A request that can't be honoured, with a message fit to show Andrew."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(raw) -> datetime | None:
    return db._parse_utc(raw)


def norm_category(name: str | None) -> str:
    """Same comparison as scheduler.norm_category_name (duplicated because
    scheduler imports this module): "Interested 55" == "interested-55"."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def _parse_hhmm(raw: str) -> time:
    match = _TIME_RE.match((raw or "").strip())
    if not match:
        raise SequenceError(f"'{raw}' isn't a time like 07:30.")
    return time(int(match.group(1)), int(match.group(2)))


def _valid_zone(name: str | None) -> str | None:
    if not name:
        return None
    try:
        ZoneInfo(name)
    except Exception:
        return None
    return name


def send_window(sequence, lead_row) -> tuple[str, str, str]:
    """(IANA zone, window start, window end) this lead's steps go out in.

    Order: the sequence's explicit zone, then the lead's stored guess, then a
    guess from the campaign name (which falls back to DEFAULT_LEAD_TIMEZONE).
    Any US zone is replaced by US_SEND_WINDOW."""
    zone = None
    mode = (sequence["timezone_mode"] or "auto").strip()
    if mode != "auto":
        zone = _valid_zone(mode)
    if zone is None and lead_row is not None:
        stored = _valid_zone(lead_row["timezone_guess"])
        # The stored Zagreb value is only ever the old fallback, never
        # evidence, so a client-level default outranks it.
        if stored and not (stored == FALLBACK_TIMEZONE and settings.default_lead_timezone):
            zone = stored
    if zone is None:
        zone = _valid_zone(
            guess_timezone((lead_row["campaign_name"] if lead_row is not None else "") or "")
        ) or FALLBACK_TIMEZONE
    if zone in _US_ZONES:
        return US_SEND_WINDOW
    return zone, sequence["window_start"], sequence["window_end"]


def compute_send_at(
    *,
    anchor: datetime,
    delay_days: int,
    zone: str,
    window_start: str,
    window_end: str,
    weekdays_only: bool,
    seed: str,
    now: datetime | None = None,
    skip_delay: bool = False,
) -> datetime:
    """When a step goes out, in UTC.

    The day is the anchor's local date plus `delay_days` (so "2 days after" an
    email sent Monday at 4pm is Wednesday), rolled past weekends. The minute is
    random inside the window but seeded, so recomputing it after an edit gives
    the same time rather than reshuffling. If that moment has already passed —
    the app was down, or the enrollment is late — it goes in what is left of
    today's window when the window is still open, otherwise in the next valid
    day's; never "right now at 3pm"."""
    tz = ZoneInfo(zone)
    now = now or _now()
    start, end = _parse_hhmm(window_start), _parse_hhmm(window_end)
    span = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if span <= 0:
        raise SequenceError("The send window has to end after it starts.")
    rng = random.Random(seed)
    offset = rng.randrange(span)

    day = anchor.astimezone(tz).date() + timedelta(days=0 if skip_delay else max(0, delay_days))
    today = now.astimezone(tz).date()
    if day < today:
        day = today
    for _ in range(21):
        if weekdays_only and day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        opens = datetime.combine(day, start, tzinfo=tz)
        closes = datetime.combine(day, end, tzinfo=tz)
        candidate = opens + timedelta(minutes=offset)
        if candidate > now:
            return candidate.astimezone(timezone.utc)
        left = int((closes - now).total_seconds() // 60)
        if left >= 3:
            return (now + timedelta(minutes=1 + rng.randrange(min(left - 1, 15)))).astimezone(
                timezone.utc
            )
        day += timedelta(days=1)
    raise SequenceError("Couldn't find a send day in the next three weeks.")


def format_local(ts, zone: str) -> str:
    dt = _parse(ts)
    if dt is None:
        return ""
    local = dt.astimezone(ZoneInfo(zone))
    return local.strftime("%a %d %b %H:%M")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def get_sequence(conn, sequence_id: int):
    return conn.execute("SELECT * FROM sequences WHERE id = ?", (sequence_id,)).fetchone()


def get_steps(conn, sequence_id: int) -> list:
    return conn.execute(
        "SELECT * FROM sequence_steps WHERE sequence_id = ? ORDER BY position",
        (sequence_id,),
    ).fetchall()


def get_enrollment(conn, enrollment_id: int):
    return conn.execute(
        "SELECT * FROM sequence_enrollments WHERE id = ?", (enrollment_id,)
    ).fetchone()


def open_enrollment_for_lead(conn, lead_id: int, campaign_id: int):
    return conn.execute(
        f"""SELECT * FROM sequence_enrollments
            WHERE lead_id = ? AND campaign_id = ?
              AND state IN ({','.join('?' for _ in OPEN_STATES)})
            ORDER BY enrolled_at DESC LIMIT 1""",
        (lead_id, campaign_id, *OPEN_STATES),
    ).fetchone()


def sequence_for_category(conn, category_name: str | None):
    """The sequence a category starts, if any. Inactive sequences still match
    here so the caller can say "that sequence is switched off" rather than
    silently treating the category as an ordinary status."""
    want = norm_category(category_name)
    if not want:
        return None
    for row in conn.execute("SELECT * FROM sequences ORDER BY id").fetchall():
        if norm_category(row["trigger_category"]) == want:
            return row
    return None


def _cached_thread(conn, lead_id: int, campaign_id: int) -> list:
    row = db.get_lead_thread(conn, lead_id, campaign_id)
    if not row or not row["thread_json"]:
        return []
    try:
        items = json.loads(row["thread_json"])
    except ValueError:
        return []
    thread = []
    for item in items:
        try:
            item = dict(item)
            item["timestamp"] = _parse(item.get("timestamp")) or _now()
            thread.append(detector.NormalizedMessage(**item))
        except TypeError:
            continue
    return thread


def render_step(body_html: str, lead_row) -> str:
    """The step body with {name}/{company}/{companyNickname} filled for this
    lead. Values are HTML-escaped because the body is HTML; unknown
    placeholders are deleted rather than mailed with their braces."""
    values = message_templates.placeholders_for(
        lead_row["name"] if lead_row is not None else None,
        lead_row["company"] if lead_row is not None else None,
    )
    return message_templates.fill(body_html or "", {k: html.escape(v) for k, v in values.items()})


# ---------------------------------------------------------------------------
# Enrolling and scheduling
# ---------------------------------------------------------------------------

def check_enrollable(conn, sequence, lead_id: int, campaign_id: int, thread, *, re_enroll: bool = False):
    """Raise SequenceError explaining why this lead can't start `sequence`.

    Runs before the Smartlead category is changed, so a refusal leaves the
    lead exactly as it was."""
    if sequence is None:
        raise SequenceError("That sequence doesn't exist.")
    if not sequence["active"]:
        raise SequenceError(f"The '{sequence['name']}' sequence is switched off.")
    if not get_steps(conn, sequence["id"]):
        raise SequenceError(f"The '{sequence['name']}' sequence has no emails yet.")
    lead = db.get_lead_state(conn, lead_id, campaign_id)
    if lead is not None and lead["status"] in ("booked", "blacklisted", "stopped"):
        raise SequenceError(f"This lead is {lead['status']}, so they can't start a sequence.")
    if not thread:
        raise SequenceError("Couldn't load this lead's email thread from Smartlead.")
    if thread[-1].kind != "sent":
        raise SequenceError(
            "They wrote last, so they're waiting on your reply. Send your message first."
        )
    if not signatures.is_sendable(detector.last_sender_email(thread)):
        raise SequenceError("The mailbox this thread went out from is retired, so nothing can be sent.")
    current = open_enrollment_for_lead(conn, lead_id, campaign_id)
    if current is not None and current["sequence_id"] == sequence["id"]:
        raise SequenceError(f"They're already in '{sequence['name']}'.")
    prior = conn.execute(
        """SELECT * FROM sequence_enrollments
           WHERE sequence_id = ? AND lead_id = ? AND campaign_id = ?""",
        (sequence["id"], lead_id, campaign_id),
    ).fetchone()
    if prior is not None and prior["state"] not in OPEN_STATES and not re_enroll:
        raise SequenceError(
            f"They've already been through '{sequence['name']}' ({prior['state']}). "
            "Use Re-enroll if you want to start it again."
        )


def enroll(
    conn,
    sequence,
    lead_id: int,
    campaign_id: int,
    thread,
    *,
    re_enroll: bool = False,
    now: datetime | None = None,
):
    """Start `sequence` for this lead and schedule its first step.

    The anchor is our last email in the thread (the one Andrew just sent), not
    the moment the category changed, so step 1 still goes out N days after
    that email when the status is changed late. Any other open sequence for
    the lead is stopped first: one lead, one sequence."""
    check_enrollable(conn, sequence, lead_id, campaign_id, thread, re_enroll=re_enroll)
    now = now or _now()
    db.stop_sequence_enrollments(conn, lead_id, campaign_id, "status_changed")
    conn.execute(
        """DELETE FROM sequence_enrollments
           WHERE sequence_id = ? AND lead_id = ? AND campaign_id = ?""",
        (sequence["id"], lead_id, campaign_id),
    )
    anchor = next((m.timestamp for m in reversed(thread) if m.kind == "sent"), now)
    cur = conn.execute(
        """INSERT INTO sequence_enrollments
             (sequence_id, lead_id, campaign_id, state, steps_sent, anchor_at, enrolled_at)
           VALUES (?, ?, ?, 'active', 0, ?, ?)""",
        (sequence["id"], lead_id, campaign_id, _iso(anchor), _iso(now)),
    )
    # The AI follow-up cadence stands down: no follow-up candidate, and no
    # unsent AI follow-up draft alongside the sequence's own.
    conn.execute(
        """UPDATE candidates SET status = 'dismissed', reason = 'in a sequence', updated_at = ?
           WHERE lead_id = ? AND campaign_id = ? AND kind = 'followup'
             AND status IN ('open', 'generating')""",
        (db.now_iso(), lead_id, campaign_id),
    )
    conn.execute(
        """UPDATE drafts SET status = 'skipped'
           WHERE lead_id = ? AND campaign_id = ? AND kind = 'followup'
             AND status IN ('pending', 'scheduled')""",
        (lead_id, campaign_id),
    )
    enrollment = get_enrollment(conn, cur.lastrowid)
    schedule_next(conn, enrollment, thread=thread, now=now)
    log.info(
        "lead %s/%s enrolled in sequence %s (%s)",
        campaign_id, lead_id, sequence["id"], sequence["name"],
    )
    return get_enrollment(conn, enrollment["id"])


def schedule_next(
    conn,
    enrollment,
    *,
    thread=None,
    now: datetime | None = None,
    skip_delay: bool = False,
    keep_body: str | None = None,
) -> int | None:
    """Create the scheduled draft for the enrollment's next step, or complete
    the enrollment when there is none. Returns the draft id."""
    now = now or _now()
    sequence = get_sequence(conn, enrollment["sequence_id"])
    steps = get_steps(conn, enrollment["sequence_id"])
    position = enrollment["steps_sent"] + 1
    if position > len(steps):
        complete(conn, enrollment, sequence)
        return None
    step = steps[position - 1]
    lead = db.get_lead_state(conn, enrollment["lead_id"], enrollment["campaign_id"])
    zone, start, end = send_window(sequence, lead)
    send_at = compute_send_at(
        anchor=_parse(enrollment["anchor_at"]) or now,
        delay_days=step["delay_days"],
        zone=zone,
        window_start=start,
        window_end=end,
        weekdays_only=bool(sequence["weekdays_only"]),
        seed=f"{enrollment['id']}:{position}",
        now=now,
        skip_delay=skip_delay,
    )
    thread = thread or _cached_thread(conn, enrollment["lead_id"], enrollment["campaign_id"])
    last = thread[-1] if thread else None
    sender_email = detector.last_sender_email(thread) if thread else ""
    signature_html = signatures.get_signature_html(sender_email) if sender_email else ""
    draft_id = db.create_draft(
        conn,
        lead_id=enrollment["lead_id"],
        campaign_id=enrollment["campaign_id"],
        kind="sequence",
        triage_summary=f"{sequence['name']}: email {position} of {len(steps)}",
        body_html=keep_body if keep_body is not None else render_step(step["body_html"], lead),
        thread_snapshot=json.dumps([m.__dict__ for m in thread], default=str) if thread else None,
        reply_message_id=last.message_id if last else None,
        reply_email_time=last.timestamp.isoformat() if last else None,
        reply_stats_id=last.stats_id if last else None,
        status="scheduled",
        scheduled_at=_iso(send_at),
        lead_name=(lead["name"] if lead is not None else "") or "",
        lead_company=(lead["company"] if lead is not None else "") or "",
        lead_email=lead["email"] if lead is not None else None,
        sender_email=sender_email or None,
        signature_html=signature_html or None,
        attachments=step["attachments"],
        enrollment_id=enrollment["id"],
        step_position=position,
        sequence_step_id=step["id"],
    )
    conn.execute(
        """UPDATE sequence_enrollments
           SET draft_id = ?, next_send_at = ?, last_error = NULL
           WHERE id = ?""",
        (draft_id, _iso(send_at), enrollment["id"]),
    )
    return draft_id


def complete(conn, enrollment, sequence=None) -> None:
    sequence = sequence or get_sequence(conn, enrollment["sequence_id"])
    finish = ((sequence["finish_category"] if sequence is not None else "") or "").strip() or None
    conn.execute(
        """UPDATE sequence_enrollments
           SET state = 'completed', completed_at = ?, next_send_at = NULL,
               draft_id = NULL, pending_category = ?
           WHERE id = ?""",
        (db.now_iso(), finish, enrollment["id"]),
    )
    log.info(
        "sequence %s finished for lead %s/%s",
        enrollment["sequence_id"], enrollment["campaign_id"], enrollment["lead_id"],
    )


def on_step_sent(conn, draft, sent_at: str) -> None:
    """A sequence step went out: count it, re-anchor on it, queue the next."""
    enrollment_id = draft.get("enrollment_id") if isinstance(draft, dict) else draft["enrollment_id"]
    enrollment = get_enrollment(conn, enrollment_id) if enrollment_id else None
    if enrollment is None:
        return
    position = draft["step_position"] or (enrollment["steps_sent"] + 1)
    conn.execute(
        """UPDATE sequence_enrollments
           SET steps_sent = ?, anchor_at = ?, last_sent_at = ?, send_failures = 0,
               draft_id = NULL, next_send_at = NULL
           WHERE id = ?""",
        (max(position, enrollment["steps_sent"]), sent_at, sent_at, enrollment["id"]),
    )
    enrollment = get_enrollment(conn, enrollment["id"])
    if enrollment["state"] != "active":
        return
    schedule_next(conn, enrollment)


def on_send_failed(conn, draft, error: str) -> None:
    """First failure: try again in the next morning window. Second: stop and
    show it, rather than retrying an email that keeps failing forever."""
    enrollment = get_enrollment(conn, draft["enrollment_id"]) if draft["enrollment_id"] else None
    if enrollment is None:
        db.update_draft(conn, draft["id"], status="aborted", send_error=error[:500])
        return
    failures = enrollment["send_failures"] + 1
    if failures >= 2:
        db.update_draft(conn, draft["id"], status="aborted", send_error=error[:500])
        conn.execute(
            """UPDATE sequence_enrollments
               SET state = 'error', stop_reason = 'send_failed', last_error = ?,
                   send_failures = ?, next_send_at = NULL, draft_id = NULL, stopped_at = ?
               WHERE id = ?""",
            (error[:500], failures, db.now_iso(), enrollment["id"]),
        )
        return
    sequence = get_sequence(conn, enrollment["sequence_id"])
    lead = db.get_lead_state(conn, enrollment["lead_id"], enrollment["campaign_id"])
    zone, start, end = send_window(sequence, lead)
    retry_at = compute_send_at(
        anchor=_now(), delay_days=1, zone=zone, window_start=start, window_end=end,
        weekdays_only=bool(sequence["weekdays_only"]),
        seed=f"{enrollment['id']}:{draft['step_position']}:retry",
    )
    db.update_draft(
        conn, draft["id"], status="scheduled", scheduled_at=_iso(retry_at), send_error=error[:500]
    )
    conn.execute(
        """UPDATE sequence_enrollments
           SET send_failures = ?, last_error = ?, next_send_at = ?
           WHERE id = ?""",
        (failures, error[:500], _iso(retry_at), enrollment["id"]),
    )


# ---------------------------------------------------------------------------
# The pre-send check
# ---------------------------------------------------------------------------

SEND, WAIT, STOPPED = "send", "wait", "stale"


def presend_check(draft: dict, thread) -> str:
    """The last line of defence, run right before a sequence step is sent.

    Returns SEND, WAIT (leave it scheduled and look again shortly) or STOPPED
    (the draft has been staled and the enrollment stopped). Everything here is
    read fresh: the thread the caller just fetched, and the lead's live
    Smartlead category — which is what catches a booking marked in
    Smartlead's own screen that no scan has seen yet."""
    lead_id, campaign_id = draft["lead_id"], draft["campaign_id"]
    with db.db_session() as conn:
        enrollment = get_enrollment(conn, draft["enrollment_id"]) if draft.get("enrollment_id") else None
        if enrollment is None or enrollment["state"] != "active" or enrollment["draft_id"] != draft["id"]:
            db.update_draft(conn, draft["id"], status="stale")
            return STOPPED
        if enrollment["pending_category"]:
            return WAIT
        sequence = get_sequence(conn, enrollment["sequence_id"])
        lead = db.get_lead_state(conn, lead_id, campaign_id)
        if lead is not None and lead["status"] in ("booked", "blacklisted", "stopped"):
            db.stop_sequence_enrollments(
                conn, lead_id, campaign_id,
                "booked" if lead["status"] == "booked" else "status_changed",
            )
            return STOPPED
        if sequence is None or not sequence["active"]:
            return WAIT
    anchor = _parse(enrollment["anchor_at"])

    newer = [m for m in thread if m.kind == "reply" and anchor and m.timestamp > anchor]
    if newer:
        reply = newer[-1]
        with db.db_session() as conn:
            # Recording the reply is what stops the sequence (the hook inside
            # mark_lead_replied), and it also puts the lead in the inbox.
            db.mark_lead_replied(
                conn, lead_id, campaign_id,
                preview=None,
                received_at=_iso(reply.timestamp),
            )
        log.info("sequence step %s not sent: lead %s replied", draft["id"], lead_id)
        return STOPPED

    if settings.dry_run:
        # DRY_RUN never wrote the trigger category to Smartlead, so comparing
        # against it would stop every local test.
        return SEND

    email = (lead["email"] if lead is not None else None) or draft.get("lead_email") or ""
    try:
        record = smartlead.get_lead_by_email(email) if email else {}
        categories = {cid: name for name, cid in smartlead.fetch_categories().items()}
    except Exception as exc:
        log.warning("sequence step %s: couldn't read lead %s from Smartlead (%s)", draft["id"], lead_id, exc)
        return WAIT
    entry = next(
        (
            row for row in (record.get("lead_campaign_data") or [])
            if str(row.get("campaign_id")) == str(campaign_id)
        ),
        None,
    )
    if entry is None:
        with db.db_session() as conn:
            conn.execute(
                """UPDATE sequence_enrollments
                   SET state = 'error', stop_reason = 'lead_not_found',
                       last_error = ?, next_send_at = NULL, draft_id = NULL, stopped_at = ?
                   WHERE id = ?""",
                (f"Smartlead has no lead {email} in this campaign.", db.now_iso(), enrollment["id"]),
            )
            db.update_draft(conn, draft["id"], status="stale")
        return STOPPED

    last_reply = _parse(entry.get("last_reply_at"))
    if last_reply and anchor and last_reply > anchor:
        with db.db_session() as conn:
            db.mark_lead_replied(conn, lead_id, campaign_id, preview=None, received_at=_iso(last_reply))
        log.info("sequence step %s not sent: Smartlead shows a reply from lead %s", draft["id"], lead_id)
        return STOPPED

    category = categories.get(entry.get("lead_category_id")) or ""
    if norm_category(category) != norm_category(sequence["trigger_category"]):
        with db.db_session() as conn:
            if norm_category(category) == norm_category(settings.meeting_booked_category_name):
                db.mark_lead_booked(conn, lead_id, campaign_id)
            else:
                db.stop_sequence_enrollments(conn, lead_id, campaign_id, "status_changed")
            db.upsert_lead_state(conn, lead_id, campaign_id, smartlead_category=category or None)
        log.info(
            "sequence step %s not sent: lead %s is now %r in Smartlead",
            draft["id"], lead_id, category or "(no category)",
        )
        return STOPPED
    return SEND


def defer(conn, draft) -> None:
    """Put a WAIT step back in the queue: a few minutes later while its
    window is still open, otherwise the next morning's window."""
    enrollment = get_enrollment(conn, draft["enrollment_id"])
    retry = _now() + timedelta(minutes=5)
    if enrollment is not None:
        sequence = get_sequence(conn, enrollment["sequence_id"])
        lead = db.get_lead_state(conn, draft["lead_id"], draft["campaign_id"])
        zone, start, end = send_window(sequence, lead)
        local_end = datetime.combine(
            _now().astimezone(ZoneInfo(zone)).date(), _parse_hhmm(end), tzinfo=ZoneInfo(zone)
        )
        if retry > local_end:
            retry = compute_send_at(
                anchor=_now(), delay_days=1, zone=zone, window_start=start, window_end=end,
                weekdays_only=bool(sequence["weekdays_only"]),
                seed=f"{enrollment['id']}:{draft['step_position']}",
            )
        conn.execute(
            "UPDATE sequence_enrollments SET next_send_at = ? WHERE id = ?",
            (_iso(retry), enrollment["id"]),
        )
    db.update_draft(conn, draft["id"], status="scheduled", scheduled_at=_iso(retry))


# ---------------------------------------------------------------------------
# Signals from elsewhere
# ---------------------------------------------------------------------------

def on_smartlead_category(lead_id: int, campaign_id: int, category_name: str | None) -> None:
    """A scan or poll read this lead's Smartlead category. If a running
    sequence's trigger no longer matches, Andrew (or Smartlead) moved the lead,
    so the sequence stops. Paused sequences are left alone: Smartlead's AI
    files out-of-office replies under its own category, and that must not
    cost the Resume button."""
    if not category_name or settings.dry_run:
        return
    with db.db_session() as conn:
        rows = conn.execute(
            """SELECT e.*, s.trigger_category FROM sequence_enrollments e
               JOIN sequences s ON s.id = e.sequence_id
               WHERE e.lead_id = ? AND e.campaign_id = ? AND e.state IN ('active', 'error')""",
            (lead_id, campaign_id),
        ).fetchall()
        for row in rows:
            if norm_category(row["trigger_category"]) == norm_category(category_name):
                continue
            enrolled = _parse(row["enrolled_at"])
            if enrolled and _now() - enrolled < ENROLL_GRACE:
                continue
            if norm_category(category_name) == norm_category(settings.meeting_booked_category_name):
                continue  # the booking path records it and stops the sequence itself
            db.stop_sequence_enrollments(
                conn, lead_id, campaign_id, "status_changed", states=("active", "error")
            )
            log.info(
                "sequence stopped for lead %s/%s: Smartlead category is now %r",
                campaign_id, lead_id, category_name,
            )
            return


# ---------------------------------------------------------------------------
# Actions from the dashboard
# ---------------------------------------------------------------------------

def pause(conn, enrollment_id: int) -> None:
    enrollment = get_enrollment(conn, enrollment_id)
    if enrollment is None or enrollment["state"] not in ("active", "error"):
        raise SequenceError("Only a running sequence can be paused.")
    conn.execute(
        """UPDATE sequence_enrollments
           SET state = 'paused', stop_reason = 'manual_pause', stopped_at = ?,
               next_send_at = NULL, draft_id = NULL
           WHERE id = ?""",
        (db.now_iso(), enrollment_id),
    )
    conn.execute(
        "UPDATE drafts SET status = 'stale' WHERE enrollment_id = ? AND status IN ('pending', 'scheduled')",
        (enrollment_id,),
    )


def resume_date_to_anchor(conn, enrollment, resume_on: date | None, in_days: int | None) -> datetime:
    """The moment a resume counts from: midnight of the chosen local date,
    or now plus N days, or now."""
    now = _now()
    if in_days is not None:
        return now + timedelta(days=max(0, in_days))
    if resume_on is not None:
        sequence = get_sequence(conn, enrollment["sequence_id"])
        lead = db.get_lead_state(conn, enrollment["lead_id"], enrollment["campaign_id"])
        zone, _, _ = send_window(sequence, lead)
        return max(now, datetime.combine(resume_on, time(0, 0), tzinfo=ZoneInfo(zone)))
    return now


def resume(conn, enrollment_id: int, thread, *, resume_on: date | None = None, in_days: int | None = None):
    """Pick a paused or failed sequence back up.

    The next unsent step goes out in the first window on or after the resume
    date; its own delay isn't added again, because the lead has already been
    waiting. Refused if the lead has written anything real since the pause,
    so the button can't talk over a conversation. The trigger category is
    queued back onto the lead in Smartlead, since the pause may have moved it."""
    enrollment = get_enrollment(conn, enrollment_id)
    if enrollment is None or enrollment["state"] not in ("paused", "error"):
        raise SequenceError("Only a paused sequence can be resumed.")
    sequence = get_sequence(conn, enrollment["sequence_id"])
    if sequence is None or not sequence["active"]:
        raise SequenceError("That sequence is switched off.")
    lead = db.get_lead_state(conn, enrollment["lead_id"], enrollment["campaign_id"])
    if lead is not None and lead["status"] in ("booked", "blacklisted", "stopped"):
        raise SequenceError(f"This lead is {lead['status']}.")
    since = _parse(enrollment["stopped_at"]) or _parse(enrollment["anchor_at"])
    if since and any(m.kind == "reply" and m.timestamp > since for m in (thread or [])):
        raise SequenceError("They've written since this was paused. Read that first.")
    anchor = resume_date_to_anchor(conn, enrollment, resume_on, in_days)
    conn.execute(
        """UPDATE sequence_enrollments
           SET state = 'active', stop_reason = NULL, stopped_at = NULL, last_error = NULL,
               send_failures = 0, anchor_at = ?, suggested_resume_at = NULL,
               pending_category = ?
           WHERE id = ?""",
        (_iso(anchor), sequence["trigger_category"], enrollment_id),
    )
    enrollment = get_enrollment(conn, enrollment_id)
    schedule_next(conn, enrollment, thread=thread or None, now=_now(), skip_delay=True)
    return get_enrollment(conn, enrollment_id)


def remove(conn, enrollment_id: int) -> None:
    enrollment = get_enrollment(conn, enrollment_id)
    if enrollment is None:
        raise SequenceError("That enrollment doesn't exist.")
    db.stop_sequence_enrollments(
        conn, enrollment["lead_id"], enrollment["campaign_id"], "manual",
    )


def skip_step(conn, enrollment_id: int) -> None:
    """Drop the queued step and schedule the one after it, still timed from
    the last email that actually went out."""
    enrollment = get_enrollment(conn, enrollment_id)
    if enrollment is None or enrollment["state"] != "active":
        raise SequenceError("Only a running sequence can skip an email.")
    conn.execute(
        "UPDATE drafts SET status = 'skipped' WHERE enrollment_id = ? AND status IN ('pending', 'scheduled')",
        (enrollment_id,),
    )
    conn.execute(
        """UPDATE sequence_enrollments
           SET steps_sent = steps_sent + 1, draft_id = NULL, next_send_at = NULL
           WHERE id = ?""",
        (enrollment_id,),
    )
    schedule_next(conn, get_enrollment(conn, enrollment_id))


def send_now(conn, enrollment_id: int) -> None:
    """Move the queued step to now. The send loop picks it up within a minute
    and the pre-send check still runs."""
    enrollment = get_enrollment(conn, enrollment_id)
    if enrollment is None or enrollment["state"] != "active" or not enrollment["draft_id"]:
        raise SequenceError("There's no queued email to send.")
    now = db.now_iso()
    db.update_draft(conn, enrollment["draft_id"], scheduled_at=now)
    conn.execute("UPDATE sequence_enrollments SET next_send_at = ? WHERE id = ?", (now, enrollment_id))


# ---------------------------------------------------------------------------
# Editing sequences
# ---------------------------------------------------------------------------

_RESERVED_TRIGGERS = lambda: {  # noqa: E731 - read at call time, settings can change in tests
    norm_category(settings.interested_category_name),
    norm_category(settings.meeting_booked_category_name),
    norm_category(settings.do_not_contact_category_name),
    norm_category(settings.autoreply_category_name),
    norm_category(settings.not_interested_category_name),
    norm_category(settings.wrong_person_category_name),
}


def _clean_sequence_fields(conn, body: dict, sequence_id: int | None = None) -> dict:
    fields: dict = {}
    if "name" in body or sequence_id is None:
        name = (body.get("name") or "").strip()
        if not name:
            raise SequenceError("Give the sequence a name.")
        fields["name"] = name[:120]
    if "trigger_category" in body or sequence_id is None:
        trigger = (body.get("trigger_category") or "").strip()
        if not trigger:
            raise SequenceError("Pick the status that starts this sequence.")
        if norm_category(trigger) in _RESERVED_TRIGGERS():
            raise SequenceError(f"'{trigger}' already means something else in the app. Pick a status of its own.")
        clash = sequence_for_category(conn, trigger)
        if clash is not None and clash["id"] != sequence_id:
            raise SequenceError(f"'{clash['name']}' already starts on '{trigger}'.")
        fields["trigger_category"] = trigger
    for key in ("window_start", "window_end"):
        if key in body:
            _parse_hhmm(body[key])
            fields[key] = body[key].strip()
    if "timezone_mode" in body:
        mode = (body.get("timezone_mode") or "auto").strip()
        if mode != "auto" and not _valid_zone(mode):
            raise SequenceError(f"'{mode}' isn't a timezone name like Europe/London.")
        fields["timezone_mode"] = mode
    if "weekdays_only" in body:
        fields["weekdays_only"] = 1 if body["weekdays_only"] else 0
    if "active" in body:
        fields["active"] = 1 if body["active"] else 0
    if "finish_category" in body:
        fields["finish_category"] = (body.get("finish_category") or "").strip() or None
    start = fields.get("window_start")
    end = fields.get("window_end")
    if sequence_id is not None and (start or end):
        current = get_sequence(conn, sequence_id)
        start = start or current["window_start"]
        end = end or current["window_end"]
    if start and end and _parse_hhmm(end) <= _parse_hhmm(start):
        raise SequenceError("The send window has to end after it starts.")
    return fields


def create_sequence(conn, body: dict) -> int:
    fields = _clean_sequence_fields(conn, body)
    fields.setdefault("finish_category", DEFAULT_FINISH_CATEGORY)
    now = db.now_iso()
    fields.update(created_at=now, updated_at=now)
    cols = list(fields)
    cur = conn.execute(
        f"INSERT INTO sequences ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [fields[c] for c in cols],
    )
    return cur.lastrowid


def update_sequence(conn, sequence_id: int, body: dict) -> None:
    sequence = get_sequence(conn, sequence_id)
    if sequence is None:
        raise SequenceError("That sequence doesn't exist.")
    fields = _clean_sequence_fields(conn, body, sequence_id)
    if not fields:
        return
    fields["updated_at"] = db.now_iso()
    conn.execute(
        f"UPDATE sequences SET {','.join(f'{k} = ?' for k in fields)} WHERE id = ?",
        [*fields.values(), sequence_id],
    )
    timing_keys = {"window_start", "window_end", "timezone_mode", "weekdays_only"}
    active_changed = "active" in fields and fields["active"] != sequence["active"]
    if active_changed or timing_keys & fields.keys():
        # Switching off pulls every queued email; switching on or changing the
        # window re-plans them. Hand-edited queued emails keep their text.
        reschedule_open(conn, sequence_id)


def delete_sequence(conn, sequence_id: int) -> None:
    running = conn.execute(
        f"""SELECT COUNT(*) FROM sequence_enrollments
            WHERE sequence_id = ? AND state IN ({','.join('?' for _ in OPEN_STATES)})""",
        (sequence_id, *OPEN_STATES),
    ).fetchone()[0]
    if running:
        raise SequenceError(
            f"{running} lead(s) are still in this sequence. Remove them or switch the sequence off instead."
        )
    conn.execute("DELETE FROM sequence_steps WHERE sequence_id = ?", (sequence_id,))
    conn.execute("DELETE FROM sequence_enrollments WHERE sequence_id = ?", (sequence_id,))
    conn.execute("DELETE FROM sequences WHERE id = ?", (sequence_id,))


def _clean_step_fields(body: dict, creating: bool) -> dict:
    fields: dict = {}
    if "delay_days" in body or creating:
        try:
            delay = int(body.get("delay_days", 2))
        except (TypeError, ValueError):
            raise SequenceError("The wait has to be a whole number of days.")
        if not 0 <= delay <= 90:
            raise SequenceError("The wait has to be between 0 and 90 days.")
        fields["delay_days"] = delay
    if "body_html" in body or creating:
        body_html = body.get("body_html") or ""
        if not re.sub(r"<[^>]+>|&nbsp;|\s", "", body_html):
            raise SequenceError("The email is empty.")
        fields["body_html"] = body_html
    if "attachments" in body:
        fields["attachments"] = body["attachments"]
    return fields


def _old_renders(conn, sequence_id: int) -> dict[int, str]:
    return {row["id"]: row["body_html"] for row in get_steps(conn, sequence_id)}


def add_step(conn, sequence_id: int, body: dict) -> int:
    if get_sequence(conn, sequence_id) is None:
        raise SequenceError("That sequence doesn't exist.")
    fields = _clean_step_fields(body, creating=True)
    old = _old_renders(conn, sequence_id)
    position = conn.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM sequence_steps WHERE sequence_id = ?",
        (sequence_id,),
    ).fetchone()[0]
    now = db.now_iso()
    cur = conn.execute(
        """INSERT INTO sequence_steps
             (sequence_id, position, delay_days, body_html, attachments, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (sequence_id, position, fields["delay_days"], fields["body_html"],
         fields.get("attachments"), now, now),
    )
    reschedule_open(conn, sequence_id, old)
    return cur.lastrowid


def update_step(conn, sequence_id: int, step_id: int, body: dict) -> None:
    step = conn.execute(
        "SELECT * FROM sequence_steps WHERE id = ? AND sequence_id = ?", (step_id, sequence_id)
    ).fetchone()
    if step is None:
        raise SequenceError("That email doesn't exist.")
    fields = _clean_step_fields(body, creating=False)
    if not fields:
        return
    old = _old_renders(conn, sequence_id)
    fields["updated_at"] = db.now_iso()
    conn.execute(
        f"UPDATE sequence_steps SET {','.join(f'{k} = ?' for k in fields)} WHERE id = ?",
        [*fields.values(), step_id],
    )
    reschedule_open(conn, sequence_id, old)


def delete_step(conn, sequence_id: int, step_id: int) -> None:
    old = _old_renders(conn, sequence_id)
    conn.execute("DELETE FROM sequence_steps WHERE id = ? AND sequence_id = ?", (step_id, sequence_id))
    _renumber(conn, sequence_id)
    reschedule_open(conn, sequence_id, old)


def move_step(conn, sequence_id: int, step_id: int, direction: int) -> None:
    steps = list(get_steps(conn, sequence_id))
    index = next((i for i, s in enumerate(steps) if s["id"] == step_id), None)
    if index is None:
        raise SequenceError("That email doesn't exist.")
    target = index + (1 if direction > 0 else -1)
    if not 0 <= target < len(steps):
        return
    old = _old_renders(conn, sequence_id)
    steps[index], steps[target] = steps[target], steps[index]
    for position, step in enumerate(steps, start=1):
        conn.execute("UPDATE sequence_steps SET position = ? WHERE id = ?", (position, step["id"]))
    reschedule_open(conn, sequence_id, old)


def _renumber(conn, sequence_id: int) -> None:
    for position, step in enumerate(get_steps(conn, sequence_id), start=1):
        conn.execute("UPDATE sequence_steps SET position = ? WHERE id = ?", (position, step["id"]))


def reschedule_open(conn, sequence_id: int, old_bodies: dict[int, str] | None = None) -> None:
    """Re-plan every queued step after the sequence or its emails changed.

    A queued email Andrew edited by hand in the Scheduled tab keeps its text
    when it is still the same step: that is detected by comparing it with how
    the step's PREVIOUS body rendered for this lead."""
    sequence = get_sequence(conn, sequence_id)
    rows = conn.execute(
        "SELECT * FROM sequence_enrollments WHERE sequence_id = ? AND state = 'active'",
        (sequence_id,),
    ).fetchall()
    for enrollment in rows:
        draft = db.get_draft(conn, enrollment["draft_id"]) if enrollment["draft_id"] else None
        keep_body = None
        steps = get_steps(conn, sequence_id)
        position = enrollment["steps_sent"] + 1
        next_step = steps[position - 1] if position <= len(steps) else None
        if draft is not None and draft["status"] == "scheduled":
            lead = db.get_lead_state(conn, enrollment["lead_id"], enrollment["campaign_id"])
            old_body = (old_bodies or {}).get(draft["sequence_step_id"])
            same_step = next_step is not None and draft["sequence_step_id"] == next_step["id"]
            if same_step and old_body is not None and draft["body_html"] != render_step(old_body, lead):
                keep_body = draft["body_html"]
            elif same_step and old_bodies is None:
                keep_body = draft["body_html"]
            db.update_draft(conn, draft["id"], status="skipped")
        elif draft is not None:
            continue  # sending or already resolved; leave it alone
        if sequence is None or not sequence["active"]:
            conn.execute(
                "UPDATE sequence_enrollments SET draft_id = NULL, next_send_at = NULL WHERE id = ?",
                (enrollment["id"],),
            )
            continue
        conn.execute(
            "UPDATE sequence_enrollments SET draft_id = NULL, next_send_at = NULL WHERE id = ?",
            (enrollment["id"],),
        )
        schedule_next(conn, get_enrollment(conn, enrollment["id"]), keep_body=keep_body)


# ---------------------------------------------------------------------------
# Housekeeping (every minute, from scheduler.run_due_send_loop)
# ---------------------------------------------------------------------------

_OOO_SYSTEM = (
    "You read one out-of-office autoreply and report the date the person is back "
    "at work. You never guess."
)
_OOO_USER = """The autoreply below was received on {received} ({weekday}).

Reply with ONLY the first date the person is back, as YYYY-MM-DD. Resolve
relative dates ("back Monday", "until the 24th") against the received date.
If the message doesn't say when they're back, reply NONE.

Autoreply:
{text}"""


def extract_return_date(text: str, received: datetime) -> date | None:
    from app import llm, models_registry
    from app.email_clean import to_plain_text

    plain = to_plain_text(text or "").strip()
    if not plain:
        return None
    try:
        answer, _ = llm.complete_for(
            models_registry.ROLE_CLASSIFY,
            _OOO_SYSTEM,
            _OOO_USER.format(
                received=received.date().isoformat(),
                weekday=received.strftime("%A"),
                text=plain[:3000],
            ),
            # A reasoning model bills thinking against this; see reply_classifier.
            max_tokens=2048,
        )
    except Exception as exc:
        log.warning("out-of-office date read failed: %s", exc)
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", answer or "")
    if not match:
        return None
    try:
        found = date.fromisoformat(match.group(0))
    except ValueError:
        return None
    if not received.date() <= found <= received.date() + timedelta(days=365):
        return None
    return found


def _write_category(campaign_id: int, lead_id: int, name: str) -> bool | None:
    """True written (or DRY_RUN), False try again later, None give up."""
    if settings.dry_run:
        log.info("[DRY_RUN] would set lead %s/%s Smartlead category to %r", campaign_id, lead_id, name)
        return True
    try:
        categories = smartlead.fetch_categories()
    except Exception:
        log.warning("couldn't load Smartlead categories", exc_info=True)
        return False
    category_id = next(
        (cid for cname, cid in categories.items() if norm_category(cname) == norm_category(name)),
        None,
    )
    if category_id is None:
        log.warning("Smartlead has no %r category; lead %s/%s left as-is", name, campaign_id, lead_id)
        return None
    try:
        smartlead.update_lead_category(campaign_id, lead_id, category_id, pause_lead=False)
    except Exception:
        log.warning("couldn't set lead %s/%s to %r", campaign_id, lead_id, name, exc_info=True)
        return False
    return True


def run_housekeeping(now: datetime | None = None) -> None:
    now = now or _now()
    _requeue_orphans()
    _push_pending_categories(now)
    _read_return_dates()
    _flag_stuck_sends(now)


def _push_pending_categories(now: datetime) -> None:
    with db.db_session() as conn:
        rows = conn.execute(
            """SELECT e.*, s.trigger_category, ls.status AS lead_status,
                      ls.smartlead_category AS lead_smartlead_category
               FROM sequence_enrollments e
               JOIN sequences s ON s.id = e.sequence_id
               LEFT JOIN leads_state ls ON ls.lead_id = e.lead_id AND ls.campaign_id = e.campaign_id
               WHERE e.pending_category IS NOT NULL
               LIMIT 20"""
        ).fetchall()
    for row in rows:
        target = row["pending_category"]
        is_interested = norm_category(target) == norm_category(settings.interested_category_name)
        if is_interested and row["state"] == "stopped":
            stopped_at = _parse(row["stopped_at"])
            if stopped_at and now - stopped_at < CATEGORY_PUSH_DELAY:
                continue
        give_up = row["lead_status"] in ("booked", "blacklisted")
        if is_interested and row["lead_smartlead_category"] and norm_category(
            row["lead_smartlead_category"]
        ) != norm_category(row["trigger_category"]):
            # Someone (Andrew, Smartlead's AI, a booking) already moved them.
            give_up = True
        result = None if give_up else _write_category(row["campaign_id"], row["lead_id"], target)
        if result is False:
            continue
        with db.db_session() as conn:
            conn.execute(
                "UPDATE sequence_enrollments SET pending_category = NULL WHERE id = ? AND pending_category = ?",
                (row["id"], target),
            )
            if result and not settings.dry_run:
                fields = {"smartlead_category": target}
                if norm_category(target) != norm_category(row["trigger_category"]) and not is_interested:
                    fields["category"] = re.sub(r"[^a-z0-9]+", "_", target.lower()).strip("_") or "other"
                db.upsert_lead_state(conn, row["lead_id"], row["campaign_id"], **fields)


def _requeue_orphans() -> None:
    """A running sequence must always have its next email queued. Anything
    that retires open drafts without knowing about sequences (a Regenerate on
    the lead's page, a future path) would otherwise leave it running forever
    with nothing to send. Re-queue the same step; its seeded time is unchanged."""
    with db.db_session() as conn:
        rows = conn.execute(
            """SELECT e.* FROM sequence_enrollments e
               JOIN sequences s ON s.id = e.sequence_id AND s.active = 1
               LEFT JOIN drafts d ON d.id = e.draft_id
               WHERE e.state = 'active' AND e.pending_category IS NULL
                 AND (e.draft_id IS NULL OR d.status IN ('skipped', 'stale', 'aborted'))
               LIMIT 20"""
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE sequence_enrollments SET draft_id = NULL, next_send_at = NULL WHERE id = ?",
                (row["id"],),
            )
            schedule_next(conn, get_enrollment(conn, row["id"]))


def _read_return_dates() -> None:
    with db.db_session() as conn:
        rows = conn.execute(
            """SELECT id, lead_id, campaign_id FROM sequence_enrollments
               WHERE state = 'paused' AND stop_reason = 'auto_reply' AND resume_checked = 0
               LIMIT 5"""
        ).fetchall()
        work = []
        for row in rows:
            thread = _cached_thread(conn, row["lead_id"], row["campaign_id"])
            reply = next((m for m in reversed(thread) if m.kind == "reply"), None)
            work.append((row["id"], reply))
    for enrollment_id, reply in work:
        found = extract_return_date(reply.body, reply.timestamp) if reply else None
        with db.db_session() as conn:
            conn.execute(
                "UPDATE sequence_enrollments SET resume_checked = 1, suggested_resume_at = ? WHERE id = ?",
                (found.isoformat() if found else None, enrollment_id),
            )


def _flag_stuck_sends(now: datetime) -> None:
    cutoff = _iso(now - STUCK_SENDING_AFTER)
    with db.db_session() as conn:
        rows = conn.execute(
            """SELECT e.id, d.id AS draft_id FROM sequence_enrollments e
               JOIN drafts d ON d.id = e.draft_id
               WHERE e.state = 'active' AND d.status = 'sending' AND d.scheduled_at < ?""",
            (cutoff,),
        ).fetchall()
        for row in rows:
            conn.execute(
                """UPDATE sequence_enrollments
                   SET state = 'error', stop_reason = 'send_failed', stopped_at = ?,
                       last_error = 'The send never finished. Check the thread in Smartlead before resuming.'
                   WHERE id = ?""",
                (db.now_iso(), row["id"]),
            )


# ---------------------------------------------------------------------------
# Payloads for the dashboard
# ---------------------------------------------------------------------------

def _counts(conn, sequence_id: int) -> dict:
    counts = {"active": 0, "paused": 0, "completed": 0, "stopped": 0, "error": 0, "replied": 0, "booked": 0}
    for row in conn.execute(
        """SELECT state, stop_reason, COUNT(*) AS n FROM sequence_enrollments
           WHERE sequence_id = ? GROUP BY state, stop_reason""",
        (sequence_id,),
    ).fetchall():
        counts[row["state"]] = counts.get(row["state"], 0) + row["n"]
        if row["stop_reason"] in ("replied", "booked"):
            counts[row["stop_reason"]] += row["n"]
    return counts


def sequence_payload(conn, sequence, with_steps: bool = True) -> dict:
    steps = get_steps(conn, sequence["id"])
    payload = {
        "id": sequence["id"],
        "name": sequence["name"],
        "trigger_category": sequence["trigger_category"],
        "active": bool(sequence["active"]),
        "window_start": sequence["window_start"],
        "window_end": sequence["window_end"],
        "weekdays_only": bool(sequence["weekdays_only"]),
        "timezone_mode": sequence["timezone_mode"],
        "finish_category": sequence["finish_category"],
        "step_count": len(steps),
        "total_days": sum(s["delay_days"] for s in steps),
        "counts": _counts(conn, sequence["id"]),
    }
    if with_steps:
        payload["steps"] = [
            {
                "id": s["id"],
                "position": s["position"],
                "delay_days": s["delay_days"],
                "body_html": s["body_html"],
                "attachments": json.loads(s["attachments"]) if s["attachments"] else [],
            }
            for s in steps
        ]
    return payload


def list_sequences_payload(conn) -> list[dict]:
    return [
        sequence_payload(conn, row, with_steps=False)
        for row in conn.execute("SELECT * FROM sequences ORDER BY name COLLATE NOCASE").fetchall()
    ]


def enrollment_payload(conn, row, sequence=None, step_count: int | None = None) -> dict:
    sequence = sequence or get_sequence(conn, row["sequence_id"])
    if step_count is None:
        step_count = len(get_steps(conn, row["sequence_id"]))
    lead = db.get_lead_state(conn, row["lead_id"], row["campaign_id"])
    zone, _, _ = send_window(sequence, lead) if sequence is not None else (FALLBACK_TIMEZONE, "", "")
    return {
        "id": row["id"],
        "sequence_id": row["sequence_id"],
        "sequence_name": sequence["name"] if sequence is not None else "",
        "lead_id": row["lead_id"],
        "campaign_id": row["campaign_id"],
        "lead_name": (lead["name"] if lead is not None else "") or "",
        "lead_email": (lead["email"] if lead is not None else "") or "",
        "lead_company": (lead["company"] if lead is not None else "") or "",
        "campaign_name": (lead["campaign_name"] if lead is not None else "") or "",
        "state": row["state"],
        "stop_reason": row["stop_reason"],
        "last_error": row["last_error"],
        "steps_sent": row["steps_sent"],
        "step_count": step_count,
        "next_send_at": row["next_send_at"],
        "next_send_local": format_local(row["next_send_at"], zone),
        "lead_timezone": zone,
        "last_sent_at": row["last_sent_at"],
        "enrolled_at": row["enrolled_at"],
        "stopped_at": row["stopped_at"],
        "completed_at": row["completed_at"],
        "suggested_resume_at": row["suggested_resume_at"],
        "draft_id": row["draft_id"],
    }


def enrollments_payload(conn, sequence_id: int, state: str | None = None) -> list[dict]:
    sequence = get_sequence(conn, sequence_id)
    if sequence is None:
        return []
    step_count = len(get_steps(conn, sequence_id))
    query = "SELECT * FROM sequence_enrollments WHERE sequence_id = ?"
    params: list = [sequence_id]
    if state:
        query += " AND state = ?"
        params.append(state)
    query += " ORDER BY CASE state WHEN 'error' THEN 0 WHEN 'paused' THEN 1 WHEN 'active' THEN 2 ELSE 3 END, COALESCE(next_send_at, stopped_at, completed_at, enrolled_at)"
    return [enrollment_payload(conn, row, sequence, step_count) for row in conn.execute(query, params).fetchall()]


def lead_enrollment_payload(conn, lead_id: int, campaign_id: int) -> dict | None:
    """The badge on the lead's detail pane: the open enrollment, or failing
    that the most recent one, so "replied after email 2" stays visible."""
    row = open_enrollment_for_lead(conn, lead_id, campaign_id) or conn.execute(
        """SELECT * FROM sequence_enrollments WHERE lead_id = ? AND campaign_id = ?
           ORDER BY COALESCE(stopped_at, completed_at, enrolled_at) DESC LIMIT 1""",
        (lead_id, campaign_id),
    ).fetchone()
    return enrollment_payload(conn, row) if row is not None else None
