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
