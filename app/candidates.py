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


_generating_lock = threading.Lock()
_generating: set[tuple[int, int]] = set()


def is_generating(campaign_id: int, lead_id: int) -> bool:
    return (campaign_id, lead_id) in _generating


def generate_for_lead_in_background(
    campaign_id: int,
    lead_id: int,
    steering_note: str | None = None,
    model: str | None = None,
    use_web_search: bool | None = None,
) -> bool:
    """Starts generate_for_lead in a background thread and returns
    immediately. A synchronous Claude call with web search/fetch tools can
    take minutes — long enough to hit Cloudflare's ~100s tunnel timeout
    (confirmed via a real 524) if held open as a single request/response.
    Returns False (no-op) if this lead is already generating, so a second
    click/poll can't stack calls."""
    key = (campaign_id, lead_id)
    with _generating_lock:
        if key in _generating:
            return False
        _generating.add(key)

    def _worker():
        try:
            generate_for_lead(campaign_id, lead_id, steering_note, model=model, use_web_search=use_web_search)
        except Exception:
            log.exception("generate_for_lead failed for %s/%s", campaign_id, lead_id)
        finally:
            with _generating_lock:
                _generating.discard(key)

    threading.Thread(target=_worker, daemon=True).start()
    return True


def generate_for_lead(
    campaign_id: int,
    lead_id: int,
    steering_note: str | None = None,
    model: str | None = None,
    use_web_search: bool | None = None,
) -> int | None:
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
        draft_id = pipeline.create_draft(
            conn, lead, campaign_name, kind, thread, steering_note,
            model=model, use_web_search=use_web_search,
        )
        candidate = conn.execute(
            """SELECT id FROM candidates WHERE lead_id = ? AND campaign_id = ? AND kind = ?
               AND status IN ('open', 'generating')""",
            (lead_id, campaign_id, kind),
        ).fetchone()
        if candidate is not None:
            db.update_candidate(conn, candidate["id"], status="drafted", draft_id=draft_id)

    log.info("generated draft %s for lead %s/%s (%s)", draft_id, campaign_id, lead_id, kind)
    return draft_id


def quick_followup(campaign_id: int, lead_id: int, english_text: str) -> int | None:
    """Drops one of the dashboard's canned quick-pick snippets straight in as a
    follow-up draft, bypassing drafter.generate_draft (and its Sonnet/Opus +
    web-tools cost) entirely — see pipeline.create_quick_draft. Synchronous:
    the only Claude call involved is one small, cheap translation, nothing
    like the multi-minute web-research generation this is meant to skip."""
    with db.db_session() as conn:
        lead_row = db.get_lead_state(conn, lead_id, campaign_id)
        existing = db.get_open_draft(conn, lead_id, campaign_id)
        if existing is not None:
            db.update_draft(conn, existing["id"], status="skipped")
    if lead_row is None:
        log.warning("quick_followup: no lead_state for %s/%s", campaign_id, lead_id)
        return None

    lead = {
        "id": lead_id,
        "campaign_id": campaign_id,
        "email": lead_row["email"],
        "first_name": lead_row["name"],
        "company_name": lead_row["company"],
    }
    thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
    if not thread:
        log.info("quick_followup: empty thread for %s/%s", campaign_id, lead_id)
        return None

    with db.db_session() as conn:
        draft_id = pipeline.create_quick_draft(conn, lead, lead_row["campaign_name"] or "", thread, english_text)
        candidate = conn.execute(
            """SELECT id FROM candidates WHERE lead_id = ? AND campaign_id = ? AND kind = 'followup'
               AND status IN ('open', 'generating')""",
            (lead_id, campaign_id),
        ).fetchone()
        if candidate is not None:
            db.update_candidate(conn, candidate["id"], status="drafted", draft_id=draft_id)

    log.info("quick-drafted follow-up %s for lead %s/%s", draft_id, campaign_id, lead_id)
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
