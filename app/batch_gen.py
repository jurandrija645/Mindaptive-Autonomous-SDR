"""Overnight follow-up pre-generation via the Anthropic Batch API.

The daily scan (scheduler.run_daily_scan) only surfaces follow-up candidates;
generating each one interactively costs a click plus a 1-3 minute wait, which
is exactly where due follow-ups slip. This module submits every eligible open
candidate as ONE Batch API job right after the scan (AUTO_GENERATE_FOLLOWUPS)
— 50% off all token costs, results typically within the hour — so the morning
dashboard opens as a ready review queue. Sending is untouched: drafts land as
ordinary 'pending' rows that still need Andrew's click (unless
AUTO_SEND_FOLLOWUPS additionally schedules them).

Eligibility: only candidates whose lead already has research_summary. Batch
requests can't continue a pause_turn web-research loop, so leads with no prior
research keep their candidate open for the normal interactive Generate (which
has the web tools). That's the same research-reuse rule as pipeline.create_draft.

Batch results are handled by poll_gen_batches (a 5-minute APScheduler job in
scheduler.start_scheduler): each result is race-checked against a FRESH thread
(the lead may have replied overnight) before the draft is stored via the same
pipeline.store_draft_result used by interactive generation.
"""
import logging

import anthropic

from app import db, detector, drafter, pipeline
from app.config import settings
from app.thread_utils import next_morning_send_utc, render_thread_text

log = logging.getLogger("batch_gen")


def _candidate_lead(cand: dict, lead_row) -> dict:
    """Same lead shape candidates.generate_one builds for pipeline calls."""
    return {
        "id": cand["lead_id"],
        "campaign_id": cand["campaign_id"],
        "email": cand["lead_email"],
        "first_name": cand["lead_name"],
        "company_name": cand["lead_company"],
        "website": lead_row["website"] if lead_row else "",
        "custom_fields": None,
    }


def _followup_stage(followup_count: int) -> str | None:
    """Mirror of pipeline.create_draft's stage rule (final touch vs revival)."""
    if followup_count >= settings.max_followups:
        return "revive"
    if followup_count == settings.max_followups - 1:
        return "final"
    return None


def _build_candidate_request(cand: dict) -> dict | None:
    """One Batch API request for an open follow-up candidate, or None if it
    isn't batch-eligible (no prior research / no longer due) — those stay
    'open' for the interactive path."""
    with db.db_session() as conn:
        lead_row = db.get_lead_state(conn, cand["lead_id"], cand["campaign_id"])
    if lead_row is None or not lead_row["research_summary"]:
        return None

    thread = pipeline.fetch_normalized_thread(cand["campaign_id"], cand["lead_id"])
    followup_count = lead_row["followup_count"] or 0
    decision = detector.decide(thread, followup_count, lead_row["status"])
    if decision.action != detector.Action.FOLLOWUP:
        return None

    lead = _candidate_lead(cand, lead_row)
    lead_payload = {
        "name": lead["first_name"] or "",
        "company": lead["company_name"] or "",
        "email": lead["email"],
        "website": lead["website"] or "",
        "campaign_name": cand["campaign_name"] or "",
        "custom_fields": None,
    }
    params = drafter.build_batch_request_params(
        "followup",
        lead_payload,
        render_thread_text(thread),
        prior_research=lead_row["research_summary"],
        followup_stage=_followup_stage(followup_count),
    )
    return {"custom_id": f"cand-{cand['id']}", "params": params}


def submit_followup_batch() -> str | None:
    """Submit one batch covering every eligible open follow-up candidate.
    Returns the batch id, or None when there was nothing to submit."""
    with db.db_session() as conn:
        cands = [dict(r) for r in db.list_candidates(conn, status="open", kind="followup")]

    requests = []
    for cand in cands:
        try:
            req = _build_candidate_request(cand)
        except Exception:
            log.exception("batch: failed to build request for candidate %s", cand["id"])
            continue
        if req is not None:
            requests.append(req)

    if not requests:
        log.info("batch: no batch-eligible follow-up candidates (out of %d open)", len(cands))
        return None

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    batch = client.messages.batches.create(requests=requests)

    with db.db_session() as conn:
        db.create_gen_batch(conn, batch.id)
        for req in requests:
            cand_id = int(req["custom_id"].split("-", 1)[1])
            db.update_candidate(conn, cand_id, status="generating")

    log.info(
        "batch %s submitted: %d follow-up generations (of %d open candidates)",
        batch.id, len(requests), len(cands),
    )
    return batch.id


def poll_gen_batches() -> None:
    """5-minute APScheduler job: consume any finished batch into drafts."""
    with db.db_session() as conn:
        pending = [dict(r) for r in db.list_open_gen_batches(conn)]
    if not pending:
        return

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    for row in pending:
        try:
            batch = client.messages.batches.retrieve(row["batch_id"])
        except Exception:
            log.exception("batch %s: retrieve failed", row["batch_id"])
            continue
        if batch.processing_status != "ended":
            continue

        ok = errs = 0
        try:
            for result in client.messages.batches.results(row["batch_id"]):
                try:
                    if _handle_result(result):
                        ok += 1
                    else:
                        errs += 1
                except Exception:
                    errs += 1
                    log.exception("batch %s: result %s failed", row["batch_id"], result.custom_id)
                    _reopen_candidate(result.custom_id)
        except Exception:
            # Couldn't stream results at all — mark failed and reopen everything
            # still stuck in 'generating' so the interactive path can pick it up.
            log.exception("batch %s: results stream failed", row["batch_id"])
            with db.db_session() as conn:
                db.close_gen_batch(conn, row["batch_id"], status="failed")
                conn.execute(
                    "UPDATE candidates SET status = 'open', updated_at = ? WHERE status = 'generating' AND kind = 'followup'",
                    (db.now_iso(),),
                )
            continue

        with db.db_session() as conn:
            db.close_gen_batch(conn, row["batch_id"])
        log.info("batch %s done: %d drafts created, %d errors/skips", row["batch_id"], ok, errs)


def _candidate_id_from(custom_id: str) -> int | None:
    try:
        prefix, num = custom_id.split("-", 1)
        return int(num) if prefix == "cand" else None
    except (ValueError, AttributeError):
        return None


def _reopen_candidate(custom_id: str) -> None:
    cand_id = _candidate_id_from(custom_id)
    if cand_id is None:
        return
    with db.db_session() as conn:
        cand = db.get_candidate(conn, cand_id)
        if cand is not None and cand["status"] == "generating":
            db.update_candidate(conn, cand_id, status="open")


def _handle_result(result) -> bool:
    """Store one batch result as a draft. Returns True on a created draft;
    False for errors/races (candidate reopened or dismissed as appropriate)."""
    cand_id = _candidate_id_from(result.custom_id)
    if cand_id is None:
        log.warning("batch result with unexpected custom_id %r ignored", result.custom_id)
        return False

    if result.result.type != "succeeded":
        log.warning("batch result %s: %s — candidate reopened", result.custom_id, result.result.type)
        _reopen_candidate(result.custom_id)
        return False

    text = "".join(b.text for b in result.result.message.content if b.type == "text")
    draft_result = drafter.parse_draft_response(text)
    if not draft_result.body_original:
        log.warning("batch result %s: no <draft_original> in output — candidate reopened", result.custom_id)
        _reopen_candidate(result.custom_id)
        return False

    with db.db_session() as conn:
        cand = db.get_candidate(conn, cand_id)
        if cand is None or cand["status"] != "generating":
            # Someone drafted/dismissed it while the batch ran — drop silently.
            return False
        cand = dict(cand)
        lead_row = db.get_lead_state(conn, cand["lead_id"], cand["campaign_id"])

    # Race-check against a FRESH thread: the lead may have replied (or been
    # booked/stopped) between submission and results. Same rule as
    # candidates.generate_one.
    thread = pipeline.fetch_normalized_thread(cand["campaign_id"], cand["lead_id"])
    followup_count = lead_row["followup_count"] if lead_row else 0
    lead_status = lead_row["status"] if lead_row else "active"
    decision = detector.decide(thread, followup_count, lead_status)
    if decision.action != detector.Action.FOLLOWUP:
        with db.db_session() as conn:
            db.update_candidate(conn, cand_id, status="dismissed", reason=f"no longer due: {decision.reason}")
        log.info("batch result %s: candidate no longer due (%s)", result.custom_id, decision.reason)
        return False

    lead = _candidate_lead(cand, lead_row)
    with db.db_session() as conn:
        draft_id = pipeline.store_draft_result(
            conn, lead, "followup", thread, draft_result, model=settings.anthropic_model
        )
        db.update_candidate(conn, cand_id, status="drafted", draft_id=draft_id)
        # Autonomous mode: with AUTO_SEND_FOLLOWUPS on, pre-generated
        # follow-ups go straight onto the scheduled queue for the lead's next
        # weekday morning; the 1-minute due_send_loop (which re-race-checks
        # right before sending, and honours DRY_RUN) does the rest. Without
        # the flag they stay 'pending' for Andrew's review — the default.
        if settings.auto_send_followups:
            send_at = next_morning_send_utc((lead_row["timezone_guess"] if lead_row else "") or "")
            db.update_draft(conn, draft_id, status="scheduled", scheduled_at=send_at.isoformat())

    log.info("batch: draft %s created for candidate %s", draft_id, cand_id)
    return True
