"""On-demand draft generation for follow-up candidates.

The daily scan (scheduler.run_daily_scan) only identifies which leads are due
for a follow-up — it never calls Claude. Generation happens here, triggered by
the user clicking "Generate" (single) or "Bulk generate" (many) on the
dashboard. Both paths share this module so the single-candidate route and the
background bulk-generate thread behave identically.
"""
import logging
import threading

from app import db, detector, pipeline

log = logging.getLogger("candidates")


def generate_one(candidate_id: int) -> int | None:
    """Draft a single candidate. Returns the new draft id, or None if the
    lead is no longer due (race: they replied, or someone else drafted it)."""
    with db.db_session() as conn:
        candidate = db.get_candidate(conn, candidate_id)
        if candidate is None or candidate["status"] not in ("open", "generating"):
            return None
        db.update_candidate(conn, candidate_id, status="generating")
        lead_row = db.get_lead_state(conn, candidate["lead_id"], candidate["campaign_id"])

    lead = {
        "id": candidate["lead_id"],
        "campaign_id": candidate["campaign_id"],
        "email": candidate["lead_email"],
        "first_name": candidate["lead_name"],
        "company_name": candidate["lead_company"],
        "website": lead_row["website"] if lead_row else "",
        "custom_fields": None,
    }

    thread = pipeline.fetch_normalized_thread(candidate["campaign_id"], candidate["lead_id"])
    followup_count = lead_row["followup_count"] if lead_row else 0
    lead_status = lead_row["status"] if lead_row else "active"
    decision = detector.decide(thread, followup_count, lead_status)

    if decision.action != detector.Action.FOLLOWUP:
        with db.db_session() as conn:
            db.update_candidate(conn, candidate_id, status="dismissed", reason=f"no longer due: {decision.reason}")
        log.info("candidate %s no longer due, dismissed: %s", candidate_id, decision.reason)
        return None

    with db.db_session() as conn:
        draft_id = pipeline.create_draft(conn, lead, candidate["campaign_name"], "followup", thread)
        db.update_candidate(conn, candidate_id, status="drafted", draft_id=draft_id)

    log.info("generated draft %s for candidate %s", draft_id, candidate_id)
    return draft_id


def generate_for_lead(campaign_id: int, lead_id: int, steering_note: str | None = None) -> int | None:
    """Draft a message for any inbox lead, keyed by lead rather than candidate.

    Used by the two-pane inbox (Generate / Regenerate). Picks kind from the
    lead's category: a nudge for auto-reply leads, otherwise a reply if the
    lead spoke last or a follow-up if we did — creates the draft, and marks
    any matching open follow-up candidate as drafted so the old candidate
    bookkeeping stays consistent. Returns the new draft id."""
    with db.db_session() as conn:
        lead_row = db.get_lead_state(conn, lead_id, campaign_id)
    if lead_row is None:
        log.warning("generate_for_lead: no lead_state for %s/%s", campaign_id, lead_id)
        return None

    lead = {
        "id": lead_id,
        "campaign_id": campaign_id,
        "email": lead_row["email"],
        "first_name": lead_row["name"],
        "company_name": lead_row["company"],
        "website": lead_row["website"],
        "custom_fields": None,
    }
    campaign_name = lead_row["campaign_name"] or ""

    thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
    if not thread:
        log.info("generate_for_lead: empty thread for %s/%s", campaign_id, lead_id)
        return None

    if lead_row["category"] == "auto_reply":
        kind = "autoreply"
    else:
        kind = "reply" if thread[-1].kind == "reply" else "followup"

    with db.db_session() as conn:
        draft_id = pipeline.create_draft(conn, lead, campaign_name, kind, thread, steering_note)
        candidate = conn.execute(
            """SELECT id FROM candidates WHERE lead_id = ? AND campaign_id = ? AND kind = ?
               AND status IN ('open', 'generating')""",
            (lead_id, campaign_id, kind),
        ).fetchone()
        if candidate is not None:
            db.update_candidate(conn, candidate["id"], status="drafted", draft_id=draft_id)

    log.info("generated draft %s for lead %s/%s (%s)", draft_id, campaign_id, lead_id, kind)
    return draft_id


def generate_many_in_background(candidate_ids: list[int]) -> None:
    with db.db_session() as conn:
        for cid in candidate_ids:
            db.update_candidate(conn, cid, status="generating")

    def _worker():
        for cid in candidate_ids:
            try:
                generate_one(cid)
            except Exception:
                log.exception("bulk generate failed for candidate %s", cid)
                with db.db_session() as conn:
                    db.update_candidate(conn, cid, status="open")

    threading.Thread(target=_worker, daemon=True).start()
