import logging
import threading

import httpx
from fastapi import APIRouter, HTTPException, Request

from app import db, pipeline, smartlead
from app.config import settings

log = logging.getLogger("webhook")
router = APIRouter()

# Leads currently being drafted by a webhook worker. Smartlead can fire the
# same reply event more than once (retries, or the n8n forward racing the
# daily scan); has_open_draft only guards against an *already saved* draft, so
# this covers the minutes-long window while Claude is still writing one.
_in_flight: set[tuple[int, int]] = set()
_in_flight_lock = threading.Lock()


def _extract_ids(payload: dict) -> tuple[int | None, int | None]:
    # Real Smartlead "reply" webhook payload shape, confirmed from the existing
    # n8n workflow (n8nNotificationSystem.json): campaign_id and sl_email_lead_id
    # at the top level, reply text under reply_message.text.
    campaign_id = payload.get("campaign_id") or payload.get("campaignId")
    lead_id = (
        payload.get("sl_email_lead_id")
        or payload.get("lead_id")
        or payload.get("leadId")
    )
    return campaign_id, lead_id


@router.post("/webhooks/smartlead")
async def smartlead_webhook(request: Request):
    if settings.smartlead_webhook_secret:
        provided = request.headers.get("x-webhook-secret") or request.query_params.get("secret")
        if provided != settings.smartlead_webhook_secret:
            raise HTTPException(status_code=401, detail="invalid webhook secret")

    payload = await request.json()
    log.info("smartlead webhook received: %s", payload)

    if not (payload.get("reply_message") or {}).get("text"):
        return {"status": "ignored", "reason": "not a reply event"}

    campaign_id, lead_id = _extract_ids(payload)
    if not campaign_id or not lead_id:
        log.warning("webhook payload missing campaign_id/sl_email_lead_id: %s", payload)
        return {"status": "ignored", "reason": "missing ids"}

    # pipeline.create_draft calls Claude synchronously (web search/fetch tools,
    # can take minutes) — far longer than the caller will wait: n8n's HTTP node
    # and the Cloudflare tunnel (~100s) both time out well before it finishes.
    # So ack straight away and draft in a background thread, same as bulk
    # generate. The dashboard picks the draft up on its next poll.
    key = (campaign_id, lead_id)
    with _in_flight_lock:
        if key in _in_flight:
            return {"status": "ignored", "reason": "already drafting for this lead"}
        _in_flight.add(key)

    def _worker() -> None:
        try:
            result = _process_reply(campaign_id, lead_id, payload)
            log.info("webhook draft for lead %s: %s", lead_id, result)
        except Exception:
            log.exception("webhook draft failed for lead %s", lead_id)
        finally:
            with _in_flight_lock:
                _in_flight.discard(key)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "accepted", "lead_id": lead_id}


def _process_reply(campaign_id: int, lead_id: int, payload: dict) -> dict:
    to_name = (payload.get("to_name") or "").strip()
    with db.db_session() as conn:
        # Smartlead's own name for the lead's inbox — not always present, but
        # when it is, worth keeping around so a wrong imported first_name is
        # easy to spot in the dashboard (see api_set_lead_name in main.py).
        if to_name:
            db.upsert_lead_state(conn, lead_id, campaign_id, email_display_name=to_name)

        pending = conn.execute(
            "SELECT id FROM drafts WHERE lead_id = ? AND campaign_id = ? AND status IN ('pending','scheduled')",
            (lead_id, campaign_id),
        ).fetchall()
        for row in pending:
            db.update_draft(conn, row["id"], status="stale")

        if db.has_open_draft(conn, lead_id, campaign_id):
            return {"status": "ok", "note": "draft already exists after clearing stale ones"}

        raw_lead = smartlead.normalize_lead({"id": lead_id}, campaign_id)
        raw_lead["email"] = raw_lead["email"] or payload.get("to_email")
        raw_lead["first_name"] = raw_lead["first_name"] or payload.get("to_name")
        lead_row = conn.execute(
            "SELECT * FROM leads_state WHERE lead_id = ? AND campaign_id = ?",
            (lead_id, campaign_id),
        ).fetchone()
        if lead_row:
            raw_lead.update(
                {
                    "email": lead_row["email"] or raw_lead["email"],
                    "first_name": lead_row["name"] or raw_lead["first_name"],
                    "company_name": lead_row["company"],
                    "website": lead_row["website"],
                }
            )

        thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
        if not thread or thread[-1].kind != "reply":
            return {"status": "ignored", "reason": "no unanswered lead reply in thread"}

        # Anything reaching this webhook has already been judged RELEVANT by the
        # n8n classifier, so treat it as interested regardless of what Smartlead's
        # own categoriser decided. Without interested=1 the lead is invisible in
        # the dashboard — list_inbox_leads filters on it — so a reply from a lead
        # sitting in "Uncategorizable by Ai" or "Not Interested" would silently
        # produce a draft nobody could see.
        db.upsert_lead_state(conn, lead_id, campaign_id, interested=1)
        _promote_category_to_interested(campaign_id, lead_id, lead_row)

        campaign_name = payload.get("campaign_name", "")
        draft_id = pipeline.create_draft(conn, raw_lead, campaign_name, "reply", thread)
        db.upsert_lead_state(conn, lead_id, campaign_id, status="awaiting_reply")

        draft = db.get_draft(conn, draft_id)

    _notify_n8n(dict(draft))
    return {"status": "ok", "draft_id": draft_id}


def _promote_category_to_interested(campaign_id: int, lead_id: int, lead_row) -> None:
    """Write "Interested" back to Smartlead so the daily scan picks this lead up
    for follow-ups too — the scan filters on the Smartlead category, and would
    otherwise keep skipping a lead we already know replied.

    Never touches a lead we've recorded as booked: that category is the success
    outcome and mark_lead_booked freezes outreach on it, so downgrading it to
    Interested here would quietly un-book a won lead when they reply again.
    Best-effort — a failure must not cost us the draft, which is the point of
    the request.
    """
    if lead_row is not None and lead_row["status"] == "booked":
        return
    try:
        interested_id = smartlead.fetch_categories().get(settings.interested_category_name)
        if interested_id is None:
            log.warning(
                "could not resolve '%s' category id; leaving lead %s category as-is",
                settings.interested_category_name,
                lead_id,
            )
            return
        smartlead.update_lead_category(campaign_id, lead_id, interested_id)
        log.info("lead %s promoted to '%s'", lead_id, settings.interested_category_name)
    except Exception:
        log.exception("failed to set Interested category on lead %s", lead_id)


def _notify_n8n(draft: dict) -> None:
    if not settings.n8n_webhook_url:
        return
    payload = {
        "lead_name": draft.get("lead_name"),
        "lead_company": draft.get("lead_company"),
        "lead_email": draft.get("lead_email"),
        "triage_summary": draft.get("triage_summary"),
        "dashboard_url": f"{settings.public_base_url}/dashboard?draft={draft['id']}",
    }
    try:
        httpx.post(settings.n8n_webhook_url, json=payload, timeout=10.0)
    except httpx.HTTPError as exc:
        log.warning("failed to notify n8n: %s", exc)
