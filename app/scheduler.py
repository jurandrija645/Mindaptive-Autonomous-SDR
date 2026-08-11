import json
import logging
import re
import threading
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import batch_gen, db, detector, lead_language, pipeline, signatures, smartlead
from app.config import settings
from app.email_clean import to_plain_text
from app.thread_utils import guess_timezone

log = logging.getLogger("scheduler")

_CATEGORY = {
    detector.Action.REPLY: "reply",
    detector.Action.FOLLOWUP: "followup",
    detector.Action.NONE: "waiting",
}


def _category_id_fuzzy(categories: dict[str, int], name: str) -> int | None:
    """Resolve a Smartlead category id by name, ignoring case and punctuation —
    the account's real category is "Meeting-Booked" but config/humans write
    "Meeting booked"; both should resolve to the same id."""
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    want = norm(name)
    for cat_name, cat_id in categories.items():
        if norm(cat_name) == want:
            return cat_id
    return None


def _lead_language(lead: dict, thread) -> str | None:
    """The lead's language, by the one ranking in app/lead_language.py:
    Smartlead's own per-lead field, then the thread (their replies before our
    sends), then whatever is already stored.

    The scan is the writer of `leads_state.language`, so it deliberately does
    not read the stored value back in — `lead_row` is left out and a scan that
    can't tell writes nothing rather than a guess (see `_summary_for`).
    `DETECT_LANGUAGE=false` turns the thread half off for clients that mail in
    one language only."""
    code, _source = lead_language.resolve(
        thread=thread, lead=lead, use_detection=settings.detect_language
    )
    return code


def _summary_for(lead: dict, thread, category: str, last_msg) -> dict:
    """The inbox summary the scan writes onto leads_state.

    `language` is included ONLY when it was actually determined, because
    upsert_lead_state writes every field it is handed — a None would overwrite
    a known language with NULL. Detection needs 20+ characters of the lead's
    own writing and the scan re-runs it on every pass, so a thread whose
    replies are all short ("Ok, thanks") used to wipe a correct value, and the
    next quick template then went out in English instead of the lead's
    language, with nothing anywhere saying why."""
    summary = dict(
        category=category,
        last_message_preview=to_plain_text(last_msg.body)[:200] if last_msg else None,
        last_message_at=last_msg.timestamp.isoformat() if last_msg else None,
        last_message_kind=last_msg.kind if last_msg else None,
    )
    lang = _lead_language(lead, thread)
    if lang:
        summary["language"] = lang
    return summary


def draft_attachments(draft) -> list[dict]:
    """The files this draft ships with, decoded from drafts.attachments.

    Fail-soft on purpose: an unreadable column returns "no attachments" rather
    than raising, because the alternative is a send that aborts over a garbled
    JSON blob when the message itself is perfectly fine. The dashboard shows
    what's attached before the click, so a silently missing file is visible
    there rather than being a surprise on the far end.
    """
    raw = None
    try:
        raw = draft["attachments"]
    except (KeyError, IndexError):
        return []  # pre-migration row
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("draft %s has unreadable attachments column", draft["id"])
        return []
    if not isinstance(data, list):
        return []
    return [a for a in data if isinstance(a, dict) and a.get("file_url") and a.get("file_name")]


def compose_send_body(draft: dict, fallback_signature_html: str | None = None) -> str:
    """The actual email body to send: the message body (body_html) plus the
    persona's signature (signature_html), appended once here.

    signature_html is captured once, at draft-creation time, and never
    recomputed — so a draft whose creation couldn't resolve the persona (an
    empty sender address, or Smartlead's email-account list not answering that
    second) keeps an empty column for good and would ship unsigned. That's what
    `fallback_signature_html` is for: the caller re-derives it from the thread
    it has just fetched. This guard existed before, was dropped when the
    signature moved out of body_html, and is restored here.

    body_html now holds the message body ONLY — the signature is never baked
    into it and is never part of the translate/localize round trip (that used
    to translate the signature and append a second, mangled copy). Appending
    here is the single, deterministic place the signature is added, so what
    ships is exactly "edited body + untouched signature".

    The append is guarded by a substring check purely to protect any legacy
    draft created before this change (whose body_html may still have the
    signature baked in): new drafts never contain it, so the check is reliably
    True and appends once."""
    body = draft["body_html"] or ""
    sig = draft["signature_html"] or fallback_signature_html or ""
    if sig and sig not in body:
        body = f"{body}<br><br>{sig}" if body else sig
    log.info(
        "[SIG-DEBUG] compose_send_body: draft_id=%s body_len=%d has_sig=%s contains_table_tag=%s",
        draft.get("id"), len(body), bool(sig), "<table" in body,
    )
    return body

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


_reply_catch_lock = threading.Lock()


# Smartlead categories that mean "don't put this in the inbox". Everything else
# — including a lead with NO category at all — is adopted by
# _adopt_unknown_repliers. Deliberately a small denylist rather than the
# allowlist the daily scan uses: see that function for why.
_SKIP_ADOPT_CATEGORIES = {
    "not interested",
    "do not contact",
    "wrong person",
    "out of office",
    "auto-reply",
    "auto reply",
    "sender originated bounce",
    "we opted out",
    "lead opted out",
    "lead done",
}


_new_reply_lock = threading.Lock()


def run_new_reply_poll() -> None:
    """`_adopt_unknown_repliers` on its own, frequent schedule.

    Two Smartlead calls and no per-lead work, against the reply-catch pass's
    one bulk thread fetch per campaign — three orders of magnitude apart in
    cost, so there is no reason for the cheap one to wait on the expensive
    one's cadence. This is the job that decides how long a lead's first reply
    stays invisible, which is the number that actually matters here
    (NEW_REPLY_POLL_SECONDS). The reply-catch pass still calls it inline first,
    so a lead adopted here is drafted for on the same pass rather than the
    next one."""
    if _new_reply_lock.locked():
        return
    with _new_reply_lock:
        try:
            _adopt_unknown_repliers()
        except Exception:
            log.exception("new-reply poll failed")


def _adopt_unknown_repliers() -> None:
    """Pull in leads who have replied but that we don't track yet.

    This is the fix for the app's worst failure: **a lead's first reply was
    invisible.** Three things had to line up for that, and they all did.

    The daily scan (and "Rescan now") only records leads whose Smartlead
    category is `Interested`. But Smartlead assigns that category with its own
    AI, minutes to hours after the reply lands — so at the moment a lead first
    answers they typically have *no category at all*. The scan skips them. The
    reply-catch pass below can't help either: it reads leads_state, and there
    is no row yet. And the webhook only fires for replies n8n classified as
    relevant. Net effect, measured against production on 2026-08-11: of the 20
    most recent replies in the Smartlead inbox, 16 had no row in the database
    at all — 7 of those purely because Smartlead hadn't categorised them yet,
    one of them a reply from that same morning. Clicking "Rescan now" appeared
    to fix it only because by then Smartlead had usually caught up and stamped
    `Interested`, which is the real five minutes people were waiting on.

    So this asks the opposite question: not "which leads are Interested?" but
    **"who has written to us lately?"** — one call to Smartlead's unified inbox
    across every campaign (smartlead.list_recent_replies). A reply is a reply;
    waiting for someone else's classifier before showing it to a human is the
    bug. Only the explicitly negative categories are skipped
    (_SKIP_ADOPT_CATEGORIES), and *no category* is emphatically not one of
    them.

    It writes the summary only, never a draft: the row plus the timestamp is
    enough to make the lead visible and to hand them to the loop below, which
    fetches the real thread anyway. Best-effort — this is a safety net, and a
    Smartlead hiccup here must not stop the pass that follows it."""
    try:
        recent = smartlead.list_recent_replies(limit=20)
        categories = {cid: name for name, cid in smartlead.fetch_categories().items()}
    except Exception:
        log.exception("reply-catch: could not list recent replies")
        return

    adopted = 0
    for row in recent:
        category = categories.get(row.get("lead_category_id")) or ""
        if category.strip().lower() in _SKIP_ADOPT_CATEGORIES:
            continue
        try:
            lead_id = int(row.get("email_lead_id") or 0)
            campaign_id = int(row.get("email_campaign_id") or 0)
        except (TypeError, ValueError):
            continue
        if not lead_id or not campaign_id:
            continue
        replied_at = row.get("last_reply_time")
        if not isinstance(replied_at, str) or not replied_at.strip():
            continue

        with db.db_session() as conn:
            existing = db.get_lead_state(conn, lead_id, campaign_id)
            # Only ever *adds* leads. One already on file is the normal case and
            # the main loop below re-derives their state from the real thread —
            # stamping a category on a lead we've stopped, booked or archived
            # off this summary alone would fight it.
            if existing:
                continue
            name = " ".join(
                part for part in (row.get("lead_first_name"), row.get("lead_last_name")) if part
            ).strip()
            db.mark_lead_replied(
                conn, lead_id, campaign_id,
                preview=None,  # this endpoint carries no body; the thread fetch fills it in
                received_at=_to_utc_iso(replied_at),
                email=row.get("lead_email"),
                name=name or None,
                campaign_name=row.get("email_campaign_name"),
                timezone_guess=guess_timezone(row.get("email_campaign_name") or ""),
            )
            adopted += 1

    if adopted:
        log.info("reply-catch: adopted %d lead(s) who replied but weren't tracked", adopted)


def _to_utc_iso(raw: str) -> str:
    """Smartlead timestamp -> UTC ISO string. last_message_at is compared as
    text (list_inbox's ordering, and db.mark_lead_replied's archive check), so
    a value carrying another offset would sort against the table wrongly."""
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc).isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def run_reply_catch_scan() -> None:
    """Frequent, cheap safety-net for replies the webhook missed.

    The webhook (webhook.py) is the fast path, but it's fire-and-forget with no
    retry — a reply that lands while the app is restarting for a deploy is lost,
    and the lead only resurfaces on the next daily scan or a manual "Rescan
    now". This closes that gap without the daily scan's cost: it never walks the
    full campaign lead lists, it only re-checks the leads we already track as
    live conversations (interested, not stopped/booked) and pulls their threads
    in bulk — roughly one Smartlead call per campaign. A lead whose newest
    message is an unanswered reply, with no open draft, gets an auto-reply
    drafted, exactly as the webhook would have. Reading the thread from a bulk
    fetch minutes after the reply also sidesteps the propagation lag that can
    make the webhook's own instant re-fetch miss the reply.

    Two things this used to get wrong, both of which made a caught reply
    invisible rather than merely late:

    - It wrote no inbox summary at all — see db.mark_lead_replied. Spotting the
      reply and drafting for it are not the same as *showing* it, and only the
      daily scan wrote the columns the inbox list reads. That is why "Rescan
      now" looked like the only way to see new mail.
    - Being keyed off leads_state, it could not see a lead replying for the
      first time. _adopt_unknown_repliers covers that in one extra call.
    """
    if _reply_catch_lock.locked():
        log.info("reply-catch scan already running, skipping this trigger")
        return
    with _reply_catch_lock:
        run_new_reply_poll()

        with db.db_session() as conn:
            rows = conn.execute(
                """SELECT lead_id, campaign_id, name, email, company, website
                   FROM leads_state
                   WHERE interested = 1 AND status IN ('active', 'awaiting_reply')"""
            ).fetchall()
        if not rows:
            return

        by_campaign: dict[int, list] = {}
        for row in rows:
            by_campaign.setdefault(row["campaign_id"], []).append(row)

        drafted = 0
        for campaign_id, leads in by_campaign.items():
            try:
                bulk = smartlead.get_message_history_bulk(
                    campaign_id, [row["lead_id"] for row in leads]
                )
            except Exception:
                log.exception(
                    "reply-catch: bulk history failed for campaign %s", campaign_id
                )
                continue

            for row in leads:
                entry = bulk.get(str(row["lead_id"])) or {}
                raw = entry.get("history") if isinstance(entry, dict) else entry
                thread = detector.normalize_thread(raw or [])
                if not thread or thread[-1].kind != "reply":
                    continue
                last = thread[-1]
                try:
                    # Show the message first, unconditionally. This pass used to
                    # go straight from spotting a reply to generating a draft
                    # and never touch the inbox summary, so the lead kept the
                    # row, chip, preview and list position the last daily scan
                    # gave them: a reply could sit in the database for hours
                    # with nothing on screen saying it had arrived. Writing it
                    # before the has_draft checks matters just as much — a
                    # message the webhook already drafted for still has to be
                    # visible as a message.
                    with db.db_session() as conn:
                        db.mark_lead_replied(
                            conn, row["lead_id"], campaign_id,
                            preview=to_plain_text(last.body),
                            received_at=last.timestamp.astimezone(timezone.utc).isoformat(),
                        )

                    with db.db_session() as conn:
                        # Already have a draft for this reply (webhook or an
                        # earlier tick) — don't make a second one.
                        if db.has_open_draft(conn, row["lead_id"], campaign_id):
                            continue
                        if db.has_drafted_reply_to(
                            conn, row["lead_id"], campaign_id, last.message_id
                        ):
                            continue
                        lead = {
                            "id": row["lead_id"],
                            "campaign_id": campaign_id,
                            "first_name": row["name"],
                            "company_name": row["company"],
                            "email": row["email"],
                            "website": row["website"],
                        }
                        log.info(
                            "reply-catch: drafting missed reply for lead %s",
                            row["lead_id"],
                        )
                        pipeline.create_draft(conn, lead, "", "reply", thread)
                        db.upsert_lead_state(
                            conn, row["lead_id"], campaign_id, status="awaiting_reply"
                        )
                        drafted += 1
                except Exception:
                    log.exception(
                        "reply-catch: drafting failed for lead %s", row["lead_id"]
                    )

        if drafted:
            log.info("reply-catch scan drafted %d missed reply(ies)", drafted)


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
    booked_id = _category_id_fuzzy(categories, settings.meeting_booked_category_name)
    if interested_id is None:
        log.warning("could not resolve '%s' category id, skipping scan", settings.interested_category_name)
        return
    if autoreply_id is None:
        log.warning(
            "could not resolve '%s' category id — auto-reply leads won't be pulled in this scan",
            settings.autoreply_category_name,
        )
    if booked_id is None:
        log.warning(
            "could not resolve '%s' category id — booked leads won't be detected this scan",
            settings.meeting_booked_category_name,
        )

    still_due_followups: set[tuple[int, int]] = set()
    failed_leads = 0
    failed_campaigns = 0
    booked_seen = 0

    # Two passes over the same leads, split by what they cost.
    #
    # Pass one only *lists* leads — one paginated call per campaign, no per-lead
    # network — and records every booked lead as it goes, since a booking needs
    # no thread to decide anything. Pass two does the expensive part: a thread
    # fetch per interested/auto-reply lead, ~150 of them.
    #
    # The split exists because the two used to be interleaved, and anything that
    # threw during the expensive part of campaign 5 killed campaigns 6..28 for
    # that whole run: only _process_lead was guarded, so a Smartlead 429 or a
    # timeout raised straight out of the loop. It ran that way for two weeks —
    # every campaign older than the fifth stayed frozen at its Jul 20 state, and
    # 34 of the account's 36 Meeting-Booked leads never got a row at all, so
    # they were missing from the dashboard entirely. Bookings are the one thing
    # the scan records that has no other source, so they are now written before
    # anything costly can fail, and a campaign that fails to list no longer
    # takes the rest of the account down with it.
    pending: list[tuple[dict, str, bool]] = []

    for campaign in smartlead.list_campaigns():
        campaign_id = campaign.get("id")
        campaign_name = campaign.get("name", "")
        if campaign_id is None:
            continue
        try:
            for raw_lead in smartlead.list_campaign_leads(campaign_id):
                lead = smartlead.normalize_lead(raw_lead, campaign_id)
                if lead["id"] is None:
                    continue
                is_autoreply = detector.category_matches(lead, autoreply_id)
                is_booked = detector.category_matches(lead, booked_id)
                if (
                    not detector.is_interested(lead, interested_id)
                    and not is_autoreply
                    and not is_booked
                ):
                    continue
                if is_booked:
                    # Isolate per lead, same as pass two: one lead that can't be
                    # recorded must not cost us the rest of the campaign.
                    try:
                        _process_lead(lead, campaign_name, False, True)
                        booked_seen += 1
                    except Exception:
                        failed_leads += 1
                        log.exception("booked lead %s failed, continuing", lead["id"])
                else:
                    pending.append((lead, campaign_name, is_autoreply))
        except Exception:
            failed_campaigns += 1
            log.exception(
                "campaign %s (%r) failed while listing leads, continuing with the next",
                campaign_id,
                campaign_name,
            )

    for lead, campaign_name, is_autoreply in pending:
        # Isolate per lead. One bad lead used to abort the whole scan —
        # an Anthropic outage or an exhausted credit balance during
        # language detection took out all remaining campaigns and left
        # leads_state empty, so the inbox looked like the account had no
        # leads at all rather than showing a partial result.
        try:
            if _process_lead(lead, campaign_name, is_autoreply, False):
                still_due_followups.add((lead["id"], lead["campaign_id"]))
        except Exception:
            failed_leads += 1
            log.exception("lead %s failed during scan, continuing", lead["id"])

    # "Every follow-up still due" is only true of a complete pass. A campaign
    # that failed to list contributed no leads to still_due_followups, so
    # clearing against a partial set would dismiss its open candidates as though
    # the leads had answered.
    if failed_campaigns:
        log.warning(
            "%d campaign(s) failed to list — keeping existing follow-up candidates",
            failed_campaigns,
        )
    else:
        with db.db_session() as conn:
            db.clear_stale_open_candidates(conn, "followup", still_due_followups)

    log.info(
        "daily scan done: %d booked lead(s) recorded, %d leads still due for a "
        "follow-up, %d lead(s) failed, %d campaign(s) failed",
        booked_seen,
        len(still_due_followups),
        failed_leads,
        failed_campaigns,
    )

    # Overnight pre-generation: hand every eligible due follow-up to the Batch
    # API (50% token cost) so drafts are waiting for review by morning. The
    # 5-minute poll job (start_scheduler) consumes the results. Failures here
    # must never break the scan — candidates simply stay open for the
    # interactive Generate path.
    if settings.auto_generate_followups and still_due_followups:
        try:
            batch_gen.submit_followup_batch()
        except Exception:
            log.exception("follow-up batch submission failed")


def _process_lead(
    lead: dict, campaign_name: str, is_autoreply: bool = False, is_booked: bool = False
) -> bool:
    """Record the lead's inbox summary and return True if it's an open follow-up
    candidate. Every interested (or auto-reply, or booked) lead gets a
    leads_state row (so it shows in the inbox); replies still auto-draft,
    follow-ups still become candidates, auto-replies get a one-shot nudge
    draft, and booked leads get frozen (db.mark_lead_booked)."""
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

    # Meeting booked — the success outcome. Freeze all outreach (open drafts
    # stale, candidates dismissed, status 'booked') but keep the lead visible
    # in the inbox with a "Booked" badge so pre-call context stays one click
    # away. Normally skip the (network) thread fetch: nothing left to decide
    # here, and replies from booked leads still auto-draft via the webhook path.
    #
    # The exception is a lead we have no summary for — booked before we ever
    # saw it as Interested, which is most of them once the scan started
    # recording every booking. With no last_message_at it sorts to the bottom
    # of the inbox as a bare name with no date and no preview. So fetch the
    # thread exactly once, the first time we record the booking; the steady
    # state is still free. A failure here must not lose the booking itself,
    # which is the whole point of recording it before anything expensive.
    if is_booked:
        summary: dict = {}
        if not (state and state["last_message_at"]):
            try:
                thread = pipeline.fetch_normalized_thread(lead["campaign_id"], lead["id"])
                summary = _summary_for(lead, thread, "booked", thread[-1] if thread else None)
            except Exception:
                log.exception(
                    "booked lead %s: thread fetch failed, recording without a preview",
                    lead["id"],
                )
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, lead["id"], lead["campaign_id"], **base_fields, **summary
            )
            db.mark_lead_booked(conn, lead["id"], lead["campaign_id"])
        if lead_status != "booked":
            log.info("lead %s marked as booked (Meeting-Booked category)", lead["id"])
        return False

    # Stopped/blacklisted leads stay out of the inbox — record the flag, skip the
    # (network) thread fetch, and don't touch their status.
    if lead_status in ("stopped", "blacklisted"):
        with db.db_session() as conn:
            db.upsert_lead_state(conn, lead["id"], lead["campaign_id"], **base_fields)
        return False

    thread = pipeline.fetch_normalized_thread(lead["campaign_id"], lead["id"])
    last_msg = thread[-1] if thread else None

    if is_autoreply:
        summary = _summary_for(lead, thread, "auto_reply", last_msg)
        # Committed on its own, before any drafting: see the note below.
        with db.db_session() as conn:
            db.upsert_lead_state(conn, lead["id"], lead["campaign_id"], **base_fields, **summary)
        with db.db_session() as conn:
            if (
                not has_open
                and last_msg is not None
                and not db.has_drafted_reply_to(conn, lead["id"], lead["campaign_id"], last_msg.message_id)
            ):
                log.info("drafting auto-reply nudge for lead %s", lead["id"])
                pipeline.create_draft(conn, lead, campaign_name, "autoreply", thread)
        return False

    # Category drives the booked state both ways: if a previously-booked lead
    # is back in the Interested category (meeting fell through / new cycle),
    # release the freeze so the normal reply/follow-up flow resumes.
    if lead_status == "booked":
        lead_status = "active"
        base_fields["status"] = "active"
        log.info("lead %s un-booked (category back to Interested)", lead["id"])

    decision = detector.decide(thread, followup_count, lead_status)
    summary = _summary_for(
        lead, thread, _CATEGORY.get(decision.action, "waiting"), last_msg
    )

    # The inbox summary commits on its own, before anything slow. Two reasons.
    # It used to share a transaction with the create_draft below, so a lead the
    # scan had already read stayed invisible until Claude finished writing to
    # them — on a pass with several replies, minutes. And an open SQLite write
    # transaction is an exclusive writer lock (WAL allows exactly one), so that
    # same wait blocked every other write in the process: the rest of the scan,
    # a send, a webhook recording a brand-new reply.
    with db.db_session() as conn:
        db.upsert_lead_state(
            conn, lead["id"], lead["campaign_id"], **base_fields, **summary
        )

    if has_open:
        # Already have an editable draft for this lead — leave it be.
        return False

    # No live mailbox to reply from (REQUIRE_KNOWN_SENDER clients only):
    # don't draft and don't queue, so a dead thread never reaches the review
    # queue as an email that could not be sent anyway.
    if decision.action != detector.Action.NONE and not signatures.is_sendable(
        detector.last_sender_email(thread)
    ):
        log.info(
            "lead %s skipped: sending mailbox %s is retired, thread is dead",
            lead["id"],
            detector.last_sender_email(thread) or "(unknown)",
        )
        return False

    if decision.action == detector.Action.REPLY:
        log.info("drafting reply for lead %s: %s", lead["id"], decision.reason)
        with db.db_session() as conn:
            pipeline.create_draft(conn, lead, campaign_name, "reply", thread)
            db.upsert_lead_state(
                conn, lead["id"], lead["campaign_id"], status="awaiting_reply"
            )
        return False

    if decision.action == detector.Action.FOLLOWUP:
        with db.db_session() as conn:
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
    # Last line of defence for REQUIRE_KNOWN_SENDER clients: the mailbox may
    # have been retired between drafting and the scheduled send.
    if not signatures.is_sendable(sender_email):
        with db.db_session() as conn:
            db.update_draft(conn, draft["id"], status="aborted")
        log.warning(
            "draft %s aborted: sending mailbox %s is retired, thread is dead",
            draft["id"], sender_email or "(unknown)",
        )
        return
    # cc_override / to_override are what Andrew put in the recipients row
    # before sending — for cc that includes an empty string, which means he
    # cleared the auto-derived Cc on purpose. Only NULL (never edited) falls
    # back to the auto-derived values.
    cc_override = draft.get("cc_override")
    cc = cc_override if cc_override is not None else detector.next_reply_cc(thread, own_email=sender_email)

    # Always send an explicit To rather than letting Smartlead default it to
    # the *imported* lead email: outreach often goes to a generic info@ and a
    # real person answers from their own mailbox, and the reply belongs to that
    # person. next_reply_to picks the address the lead last wrote from, which
    # is also exactly what the dashboard showed before the click.
    with db.db_session() as conn:
        lead_state = db.get_lead_state(conn, lead_id, campaign_id)
    lead_email = (lead_state["email"] if lead_state else "") or draft.get("lead_email") or ""
    to_email = draft.get("to_override") or detector.next_reply_to(thread, lead_email=lead_email)
    send_body = compose_send_body(draft, signatures.get_signature_html(sender_email))
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
        to_email=to_email,
        attachments=draft_attachments(draft),
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
    sched.add_job(batch_gen.poll_gen_batches, "interval", minutes=5, id="gen_batch_poll")
    # Frequent, cheap safety-net so a lead's reply surfaces on its own within a
    # few minutes even when the webhook is missed (it's fire-and-forget, and a
    # reply landing during a deploy restart is lost). Unlike the daily scan this
    # doesn't walk every lead in every campaign — it only re-checks the leads we
    # already track as live conversations, pulling their threads in bulk (~one
    # call per campaign). See run_reply_catch_scan.
    if settings.scan_interval_minutes > 0:
        sched.add_job(
            run_reply_catch_scan,
            "interval",
            minutes=settings.scan_interval_minutes,
            id="reply_catch_scan",
        )
    # How fast a lead's *first* reply shows up, which is the latency that
    # actually costs meetings. Two Smartlead calls, no per-lead work — cheap
    # enough to run far more often than the pass above. See run_new_reply_poll.
    if settings.new_reply_poll_seconds > 0:
        sched.add_job(
            run_new_reply_poll,
            "interval",
            seconds=settings.new_reply_poll_seconds,
            id="new_reply_poll",
        )
    sched.start()
    _scheduler = sched
    return sched
