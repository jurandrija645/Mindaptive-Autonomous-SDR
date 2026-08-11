import logging
import threading
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request

from app import db, lead_language, pipeline, reply_classifier, smartlead
from app.config import settings
from app.email_clean import to_plain_text

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


def _reply_text(payload: dict) -> str:
    """The lead's message out of the webhook body, whichever shape it arrives in.

    `reply_message.text` is what the n8n workflow forwards and is confirmed
    against real traffic. The other keys are what Smartlead's own EMAIL_REPLY
    documents (`reply_body`, `preview_text`) and matter now that Smartlead can
    post here directly with no n8n in between — that reference has been wrong
    before, so accept every shape rather than betting on one."""
    reply = payload.get("reply_message")
    if isinstance(reply, dict):
        for key in ("text", "html", "body"):
            value = reply.get(key)
            if isinstance(value, str) and value.strip():
                return value
    for key in ("reply_body", "preview_text", "email_body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


@router.post("/webhooks/smartlead")
async def smartlead_webhook(request: Request):
    if settings.smartlead_webhook_secret:
        provided = request.headers.get("x-webhook-secret") or request.query_params.get("secret")
        if provided != settings.smartlead_webhook_secret:
            raise HTTPException(status_code=401, detail="invalid webhook secret")

    payload = await request.json()
    log.info("smartlead webhook received: %s", payload)

    if not _reply_text(payload):
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


def _reply_received_at(payload: dict) -> str:
    """When the lead's message arrived, as an ISO string for last_message_at.

    Smartlead has used more than one field name for this and the published
    payload example doesn't match what actually arrives (see
    docs/smartlead-api.md), so take whichever is present and fall back to now:
    an approximate timestamp still sorts the lead to the top of the inbox,
    which is the whole job here. The thread fetch replaces it with the exact
    value a moment later anyway."""
    candidates = [payload.get(k) for k in ("time_replied", "event_timestamp", "reply_time")]
    candidates.append((payload.get("reply_message") or {}).get("time"))
    for raw in candidates:
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        # Always store UTC. last_message_at is compared as a *string* — against
        # archived_at below, and by list_inbox's ordering — so a value carrying
        # someone else's offset, or none at all, would sort against the rest of
        # the table wrongly.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _record_incoming(campaign_id: int, lead_id: int, payload: dict):
    """Put the lead in the inbox **now**, from the webhook payload alone.

    This runs before the thread fetch and before Claude, and that ordering is
    the point. It all used to happen in one transaction that committed only
    after generate_draft returned — minutes later, with web search running —
    so a reply that had already arrived was invisible until the draft was
    finished. Worse, it was invisible in a way that looked like nothing had
    happened at all: `category` was never written by this path, so even once
    the row landed it carried no 'reply' chip, no preview and no
    last_message_at, which put a brand-new hot lead at the *bottom* of the
    inbox under db.list_inbox's ordering. Clicking "Rescan now" appeared to
    fix it only because the scan is what writes the summary. So the summary is
    written here, from what the webhook already tells us, and the thread fetch
    later refines it.

    Holding that write transaction open across the model call was also a
    SQLite writer lock held for minutes (WAL allows one writer), which is what
    made a concurrent rescan or send crawl or time out.

    Returns the lead's pre-existing leads_state row (or None)."""
    to_name = (payload.get("to_name") or "").strip()
    to_email = (payload.get("to_email") or "").strip()
    reply_text = (payload.get("reply_message") or {}).get("text") or ""

    with db.db_session() as conn:
        lead_row = db.get_lead_state(conn, lead_id, campaign_id)

        extra: dict = {}
        # Smartlead's own name for the lead's inbox — not always present, but
        # when it is, worth keeping around so a wrong imported first_name is
        # easy to spot in the dashboard (see api_set_lead_name in main.py).
        if to_name:
            extra["email_display_name"] = to_name
        if payload.get("campaign_name"):
            extra["campaign_name"] = payload["campaign_name"]
        # A row this webhook creates from scratch has no name and no email, and
        # the inbox renders `name or email or "Lead"` — so without these a lead
        # who has never been scanned shows up as an anonymous "Lead".
        if to_email and not (lead_row and lead_row["email"]):
            extra["email"] = to_email
        if to_name and not (lead_row and lead_row["name"]):
            extra["name"] = to_name

        db.mark_lead_replied(
            conn, lead_id, campaign_id,
            preview=to_plain_text(reply_text) if reply_text else None,
            received_at=_reply_received_at(payload),
            **extra,
        )

        # Retire whatever was queued for this lead: they've said something new,
        # so a draft written against the old thread is out of date.
        pending = conn.execute(
            "SELECT id FROM drafts WHERE lead_id = ? AND campaign_id = ? AND status IN ('pending','scheduled')",
            (lead_id, campaign_id),
        ).fetchall()
        for row in pending:
            db.update_draft(conn, row["id"], status="stale")

    return lead_row


def _fetch_thread_with_reply(campaign_id: int, lead_id: int, attempts: int = 3):
    """The thread, retried while its last message still isn't the lead's reply.

    message-history can lag the webhook by a few seconds — Smartlead fires the
    event as the mail is processed, not once it's queryable. A single fetch
    that came back early used to abandon the whole event, leaving the reply to
    wait for the next daily scan."""
    thread = []
    for attempt in range(attempts):
        thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
        if thread and thread[-1].kind == "reply":
            return thread
        if attempt < attempts - 1:
            time.sleep(8)
            log.info(
                "lead %s: reply not in message-history yet, refetching (%d/%d)",
                lead_id, attempt + 2, attempts,
            )
    return thread


def _process_reply(campaign_id: int, lead_id: int, payload: dict) -> dict:
    # Phase 1 — visibility. Short transaction, no network, no model. Runs before
    # the classifier on purpose: what Andrew sees must not depend on a model
    # agreeing that the message was worth seeing.
    lead_row = _record_incoming(campaign_id, lead_id, payload)

    # Phase 2 — is this a person worth answering, or an out-of-office? This is
    # the gate the n8n workflow's gpt-5-mini + Switch pair used to apply before
    # forwarding, kept here so Smartlead's webhook can point straight at the app
    # (app/reply_classifier.py). It decides whether to spend a draft and whether
    # to push the lead to Smartlead's Interested category — nothing else.
    relevant, reason = reply_classifier.is_relevant(_reply_text(payload))
    log.info("lead %s reply: %s", lead_id, reason)
    if not relevant:
        return {"status": "ok", "note": f"recorded, no draft — {reason}"}

    _promote_category_to_interested(campaign_id, lead_id, lead_row)

    raw_lead = smartlead.normalize_lead({"id": lead_id}, campaign_id)
    raw_lead["email"] = raw_lead["email"] or payload.get("to_email")
    raw_lead["first_name"] = raw_lead["first_name"] or payload.get("to_name")
    # The placeholder above carries no custom_fields, so it knows no language.
    # Fetch the real one: pipeline.create_draft ranks it above langdetect on
    # the thread, and this is a lead who just replied — an English "thanks" or
    # an out-of-office is exactly the input that reads as English when the
    # campaign has been mailing them German all along. Fail-soft (see
    # lead_language.smartlead_field), so a hiccup just falls back to the thread.
    raw_lead["language_code"] = lead_language.smartlead_field(campaign_id, lead_id)
    if lead_row:
        raw_lead.update(
            {
                "email": lead_row["email"] or raw_lead["email"],
                "first_name": lead_row["name"] or raw_lead["first_name"],
                "company_name": lead_row["company"],
                "website": lead_row["website"],
            }
        )

    thread = _fetch_thread_with_reply(campaign_id, lead_id)
    if not thread or thread[-1].kind != "reply":
        # The lead is in the inbox from phase 1 regardless, so this costs the
        # draft, not the message.
        return {"status": "ignored", "reason": "no unanswered lead reply in thread"}

    with db.db_session() as conn:
        # Refine the placeholder summary with the real thread: the exact
        # timestamp, and the message as Smartlead stored it rather than the
        # webhook's copy of it.
        last = thread[-1]
        db.upsert_lead_state(
            conn, lead_id, campaign_id,
            last_message_preview=to_plain_text(last.body)[:200],
            last_message_at=last.timestamp.astimezone(timezone.utc).isoformat(),
        )
        if db.has_open_draft(conn, lead_id, campaign_id):
            return {"status": "ok", "note": "draft already exists after clearing stale ones"}

    # generate_draft runs outside the session on purpose (see _record_incoming).
    campaign_name = payload.get("campaign_name", "")
    with db.db_session() as conn:
        draft_id = pipeline.create_draft(conn, raw_lead, campaign_name, "reply", thread)
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
