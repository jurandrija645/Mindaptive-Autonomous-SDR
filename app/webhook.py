import hashlib
import hmac
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app import (
    db, events, interested_sheet, lead_language, lead_temperature, pipeline, reply_classifier, scheduler,
    smartlead,
)
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

_CALENDLY_SIGNATURE_TOLERANCE_SECONDS = 180

_BOOKING_FIELD_PATTERNS = {
    "name": re.compile(r"(?im)^\s*Client\s+Name\s*:\s*(.+?)\s*$"),
    "email": re.compile(r"(?im)^\s*Email\s*:\s*([^\s<>]+@[^\s<>]+)\s*$"),
    "code": re.compile(r"(?im)^\s*Discount\s+Code\s*:\s*([A-Z0-9_-]+)\s*$"),
    "location": re.compile(r"(?im)^\s*Location\s*:\s*(.+?)\s*$"),
    "date": re.compile(r"(?im)^\s*Date\s*:\s*(.+?)\s*$"),
    "time": re.compile(r"(?im)^\s*Time\s*:\s*(.+?)\s*$"),
}


def _booking_fields(payload: dict) -> tuple[str, str, str]:
    """Accept parsed fields or extract them from the booking email text."""
    raw = payload.get("text") or payload.get("body") or payload.get("message") or ""
    if isinstance(raw, dict):
        raw = raw.get("text") or raw.get("body") or ""
    raw = str(raw)

    def value(keys: tuple[str, ...], pattern: re.Pattern) -> str:
        for key in keys:
            found = payload.get(key)
            if found:
                return str(found).strip()
        match = pattern.search(raw)
        return match.group(1).strip() if match else ""

    return (
        value(("email", "client_email"), _BOOKING_FIELD_PATTERNS["email"]).lower(),
        value(("name", "client_name"), _BOOKING_FIELD_PATTERNS["name"]),
        value(("discount_code", "code"), _BOOKING_FIELD_PATTERNS["code"]).upper(),
    )


def _booking_metadata(payload: dict) -> dict[str, str]:
    """Extra attribution fields forwarded by the OneBody booking workflow."""
    raw = payload.get("text") or payload.get("body") or payload.get("message") or ""
    if isinstance(raw, dict):
        raw = raw.get("text") or raw.get("body") or ""
    raw = str(raw)

    def value(keys: tuple[str, ...], pattern: re.Pattern | None = None) -> str:
        for key in keys:
            found = payload.get(key)
            if found:
                return str(found).strip()
        match = pattern.search(raw) if pattern else None
        return match.group(1).strip() if match else ""

    return {
        "booking_id": value(("booking_id", "event_id", "message_id")),
        "location": value(("location",), _BOOKING_FIELD_PATTERNS["location"]),
        "appointment_date": value(("appointment_date", "date"), _BOOKING_FIELD_PATTERNS["date"]),
        "appointment_time": value(("appointment_time", "time"), _BOOKING_FIELD_PATTERNS["time"]),
    }


def _booking_matches(conn, email: str, name: str, code: str):
    matches = db.find_lead_by_email(conn, email) if email else []
    if matches:
        return matches, "email"
    if not name or code not in settings.booking_match_codes:
        return [], "none"
    matches = db.find_leads_by_name(conn, name)
    return (matches, "name") if matches else ([], "none")


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


def _event_key(payload: dict, campaign_id: int, lead_id: int) -> str:
    """Stable key across direct Smartlead delivery and an n8n forward."""
    for key in ("event_id", "webhook_id", "id"):
        value = payload.get(key)
        if value:
            return f"smartlead:{value}"
    timestamp = next(
        (
            payload.get(key)
            for key in ("time_replied", "event_timestamp", "reply_time")
            if payload.get(key)
        ),
        (payload.get("reply_message") or {}).get("time") or "",
    )
    material = f"{campaign_id}\n{lead_id}\n{timestamp}\n{_reply_text(payload).strip()}"
    return "reply:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


@router.post("/webhooks/smartlead")
async def smartlead_webhook(request: Request):
    if settings.smartlead_webhook_secret:
        provided = request.headers.get("x-webhook-secret") or request.query_params.get("secret")
        if provided != settings.smartlead_webhook_secret:
            raise HTTPException(status_code=401, detail="invalid webhook secret")

    payload = await request.json()
    if not _reply_text(payload):
        return {"status": "ignored", "reason": "not a reply event"}

    campaign_id, lead_id = _extract_ids(payload)
    if not campaign_id or not lead_id:
        log.warning("webhook payload missing campaign_id/sl_email_lead_id: %s", payload)
        return {"status": "ignored", "reason": "missing ids"}
    campaign_id, lead_id = int(campaign_id), int(lead_id)

    event_key = _event_key(payload, campaign_id, lead_id)
    with db.db_session() as conn:
        claimed = db.claim_webhook_event(conn, event_key, campaign_id, lead_id)
    if not claimed:
        return JSONResponse(
            {"status": "accepted", "duplicate": True, "lead_id": lead_id},
            status_code=202,
        )

    # Visibility is committed before the acknowledgement. It contains no
    # Smartlead or model call, and guarantees that a deploy immediately after
    # the 202 cannot lose the reply the caller was told we accepted.
    try:
        lead_row = _record_incoming(campaign_id, lead_id, payload)
    except Exception as exc:
        with db.db_session() as conn:
            db.finish_webhook_event(conn, event_key, "failed", str(exc)[:500])
        raise
    events.publish(
        {
            "type": "reply_received",
            "campaign_id": campaign_id,
            "lead_id": lead_id,
        }
    )

    # Everything slower than the visibility write stays in the background:
    # classification, Smartlead reconciliation, thread propagation retries,
    # lead-temperature analysis and draft generation.
    key = (campaign_id, lead_id)
    with _in_flight_lock:
        if key in _in_flight:
            with db.db_session() as conn:
                db.finish_webhook_event(conn, event_key, "coalesced")
            return JSONResponse(
                {"status": "accepted", "reason": "already drafting for this lead"},
                status_code=202,
            )
        _in_flight.add(key)

    def _worker() -> None:
        try:
            result = _process_reply(campaign_id, lead_id, payload, lead_row=lead_row)
            with db.db_session() as conn:
                db.finish_webhook_event(conn, event_key)
            log.info("webhook draft for lead %s: %s", lead_id, result)
        except Exception as exc:
            with db.db_session() as conn:
                db.finish_webhook_event(conn, event_key, "failed", str(exc)[:500])
            log.exception("webhook draft failed for lead %s", lead_id)
        finally:
            with _in_flight_lock:
                _in_flight.discard(key)

    threading.Thread(target=_worker, daemon=True).start()
    return JSONResponse(
        {"status": "accepted", "lead_id": lead_id}, status_code=202
    )


def _verify_calendly_signature(raw_body: bytes, signature_header: str) -> None:
    """Verify Calendly's t=<unix>,v1=<HMAC-SHA256> signature and reject replays."""
    signing_key = settings.calendly_webhook_signing_key
    if not signing_key:
        raise HTTPException(status_code=503, detail="Calendly webhook is not configured")
    try:
        parts = dict(part.split("=", 1) for part in signature_header.split(","))
        timestamp = int(parts["t"])
        supplied = parts["v1"]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="invalid Calendly signature")
    if abs(int(time.time()) - timestamp) > _CALENDLY_SIGNATURE_TOLERANCE_SECONDS:
        raise HTTPException(status_code=401, detail="expired Calendly signature")
    signed_payload = str(timestamp).encode() + b"." + raw_body
    expected = hmac.new(
        signing_key.encode(), signed_payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="invalid Calendly signature")


@router.post("/webhooks/calendly")
async def calendly_booking(request: Request):
    """Record Andrew's configured Calendly event directly, without n8n.

    Calendly's signed invitee.created payload is trusted for exact normalized
    full-name fallback when the invitee booked with a different email address.
    Ambiguous names are never changed.
    """
    raw_body = await request.body()
    _verify_calendly_signature(
        raw_body, request.headers.get("calendly-webhook-signature", "")
    )
    try:
        envelope = json.loads(raw_body)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid JSON")

    event = envelope.get("event")
    if event != "invitee.created":
        return {"status": "ignored", "reason": "not an invitee.created event"}

    payload = envelope.get("payload") or envelope
    scheduled_event = payload.get("scheduled_event") or envelope.get("scheduled_event") or {}
    event_type = scheduled_event.get("event_type") or payload.get("event_type") or ""
    configured_event_type = settings.calendly_event_type_uri
    if not configured_event_type:
        raise HTTPException(status_code=503, detail="Calendly event type is not configured")
    if event_type != configured_event_type:
        return {"status": "ignored", "reason": "different Calendly event type"}

    email = str(payload.get("email") or "").strip().lower()
    name = str(payload.get("name") or "").strip()
    if not email and not name:
        return JSONResponse(
            {"status": "invalid", "reason": "invitee email or name is required"},
            status_code=400,
        )

    with db.db_session() as conn:
        matches = db.find_lead_by_email(conn, email) if email else []
        matched_by = "email" if matches else "none"
        if not matches and name:
            matches = db.find_leads_by_name(conn, name)
            matched_by = "name" if matches else "none"
        matches = [dict(row) for row in matches]

    if not matches:
        return JSONResponse(
            {"status": "not_found", "email": email, "name": name}, status_code=404
        )
    identities = {(row["email"] or "").strip().lower() for row in matches}
    if matched_by != "email" and len(identities) > 1:
        return JSONResponse(
            {
                "status": "ambiguous",
                "name": name,
                "reason": "more than one lead has this name; email match required",
            },
            status_code=409,
        )

    booked = []
    for row in matches:
        scheduler.record_explicit_booking(
            row["lead_id"],
            row["campaign_id"],
            email=row["email"] or email,
            name=row["name"] or name,
        )
        booked.append({"campaign_id": row["campaign_id"], "lead_id": row["lead_id"]})

    first_match = matches[0]
    booking_id = str(payload.get("uri") or envelope.get("id") or "")
    start_time = str(scheduled_event.get("start_time") or "")
    sheet_status = interested_sheet.record_booking(
        booking_id=booking_id,
        email=email or first_match["email"] or "",
        name=name or first_match["name"] or "",
        code="",
        recorded_at=datetime.now(timezone.utc).isoformat(),
        attribution=interested_sheet.ATTRIBUTION_CONTACTED,
        matched_by=matched_by,
        campaign_id=first_match["campaign_id"],
        lead_id=first_match["lead_id"],
        appointment_date=start_time,
    )
    log.info(
        "Calendly invitee.created marked %d lead(s) booked by %s for %s",
        len(booked), matched_by, email or name,
    )
    return {
        "status": "booked",
        "email": email,
        "name": name,
        "matched_by": matched_by,
        "sheet_status": sheet_status,
        "matches": booked,
    }


@router.post("/webhooks/booking-confirmed")
async def booking_confirmed(request: Request):
    """External automations (e.g. an n8n flow watching a booking-confirmation
    inbox) call this with the booked person's email, name and offer code to record a meeting
    booked outside Smartlead's own category flow — see the "Meeting booked"
    freeze in db.mark_lead_booked.

    Deliberately does the lookup itself rather than trusting campaign_id/lead_id
    from the caller. Email is authoritative when it matches. If the person booked
    with another address, an allowlisted offer code permits an exact normalized
    full-name lookup in leads_state and then the internal Interested sheet. Titles
    such as Mr/Ms/Mrs/Dr are ignored. Ambiguous names are rejected. A booking
    carrying an allowlisted code but matching no known lead is recorded as a
    shared-code booking in Google Sheets; it never creates or changes a Smartlead
    lead. This keeps external input from mutating an unrelated lead while retaining
    the extra bookings produced when someone shares the offer with colleagues.

    Sets the Smartlead category too (not just the local status), same as the
    dashboard's manual "mark as booked" action (main.api_set_category). Once
    recorded, the local booking is a lock: later messages and Smartlead category
    drift cannot remove it. Only a manual dashboard category change can.
    """
    if settings.booking_webhook_secret:
        provided = request.headers.get("x-webhook-secret") or request.query_params.get("secret")
        if provided != settings.booking_webhook_secret:
            raise HTTPException(status_code=401, detail="invalid webhook secret")

    payload = await request.json()
    email, name, code = _booking_fields(payload)
    metadata = _booking_metadata(payload)
    if not email and not name:
        return JSONResponse({"error": "email or client name is required"}, status_code=400)

    with db.db_session() as conn:
        matches, matched_by = _booking_matches(conn, email, name, code)
        matches = [dict(row) for row in matches]

    # Sheet fallback is allowed only after the offer code proves this is our
    # booking. Do the Google call outside a database session.
    if not matches and name and code in settings.booking_match_codes:
        sheet_matches = interested_sheet.find_by_name(name)
        with db.db_session() as conn:
            matches = [
                dict(row)
                for match in sheet_matches
                if (row := db.get_lead_state(conn, match["lead_id"], match["campaign_id"]))
                is not None
            ]
        if matches:
            matched_by = "sheet_name"

    if not matches and code in settings.booking_match_codes:
        sheet_status = interested_sheet.record_booking(
            email=email,
            name=name,
            code=code,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            attribution=interested_sheet.ATTRIBUTION_SHARED,
            **metadata,
        )
        if sheet_status not in ("recorded", "duplicate"):
            return JSONResponse({
                "status": "not_recorded",
                "email": email,
                "name": name,
                "reason": "shared-code booking could not be written to Google Sheets",
                "sheet_status": sheet_status,
            }, status_code=503)
        log.info("booking-confirmed: recorded shared-code booking for %s", email or name)
        return JSONResponse({
            "status": "booked",
            "email": email,
            "name": name,
            "attribution": "shared_code",
            "matched_by": "none",
            "sheet_status": sheet_status,
            "matches": [],
        })

    if not matches:
        return JSONResponse({
            "status": "not_found", "email": email, "name": name,
            "reason": "name fallback requires an approved discount code"
            if name and code not in settings.booking_match_codes else "no matching lead",
        }, status_code=404)

    identities = {(row["email"] or "").strip().lower() for row in matches}
    if matched_by != "email" and len(identities) > 1:
        return JSONResponse({
            "status": "ambiguous", "name": name,
            "reason": "more than one lead has this name; email match required",
        }, status_code=409)

    booked = []
    for row in matches:
        lead_id, campaign_id = row["lead_id"], row["campaign_id"]
        scheduler.record_explicit_booking(
            lead_id,
            campaign_id,
            email=row["email"] or email,
            name=row["name"] or name,
        )
        booked.append({"campaign_id": campaign_id, "lead_id": lead_id})

    first_match = matches[0]
    sheet_status = interested_sheet.record_booking(
        email=email or first_match["email"] or "",
        name=name or first_match["name"] or "",
        code=code,
        recorded_at=datetime.now(timezone.utc).isoformat(),
        attribution=interested_sheet.ATTRIBUTION_CONTACTED,
        matched_by=matched_by,
        campaign_id=first_match["campaign_id"],
        lead_id=first_match["lead_id"],
        **metadata,
    )
    log.info(
        "booking-confirmed: marked %d lead(s) booked by %s for %s",
        len(booked), matched_by, email or name,
    )
    return JSONResponse({
        "status": "booked", "email": email, "name": name,
        "attribution": "contacted_lead", "matched_by": matched_by,
        "sheet_status": sheet_status, "matches": booked,
    })


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


def _process_reply(
    campaign_id: int, lead_id: int, payload: dict, lead_row=None
) -> dict:
    # Phase 1 — visibility. Short transaction, no network, no model. Runs before
    # the classifier on purpose: what Andrew sees must not depend on a model
    # agreeing that the message was worth seeing.
    if lead_row is None:
        lead_row = _record_incoming(campaign_id, lead_id, payload)

    # Refresh Smartlead's own label before making our separate workflow
    # judgement. This is informational and authoritative for the remote label;
    # the classifier below is not allowed to overwrite it. Smartlead can still
    # be uncategorized for a few minutes, so a failed/empty refresh must never
    # delay visibility or drafting.
    scheduler.refresh_smartlead_category_for_reply(campaign_id, lead_id)

    # Phase 2 — is this a person worth answering, or an out-of-office? This is
    # the gate the n8n workflow's gpt-5-mini + Switch pair used to apply before
    # forwarding, kept here so Smartlead's webhook can point straight at the app
    # (app/reply_classifier.py). It decides only whether to spend a draft and
    # how to arrange the local inbox. Smartlead owns its canonical category.
    label, reason = reply_classifier.classify(_reply_text(payload))
    log.info("lead %s reply: %s", lead_id, reason)
    if label == reply_classifier.BOOKED:
        scheduler.record_explicit_booking(
            lead_id,
            campaign_id,
            email=(lead_row["email"] if lead_row else "") or "",
            name=(lead_row["name"] if lead_row else "") or "",
        )
        return {"status": "ok", "note": "booking confirmation recorded"}
    if label == reply_classifier.DO_NOT_CONTACT:
        scheduler.record_do_not_contact(
            lead_id,
            campaign_id,
            email=(lead_row["email"] if lead_row else "") or "",
        )
        return {"status": "ok", "note": "do not contact recorded and suppressed"}
    if label != reply_classifier.INTERESTED:
        # Recorded and visible either way; db.sort_replied_lead just moves it
        # out of the red "awaiting reply" tier it doesn't belong in. No real
        # message id to stamp here — the thread isn't fetched on this branch,
        # deliberately, so a junk reply doesn't cost the retry-loop fetch below
        # — so the next reply-catch tick judges this exact message once more
        # against the real thread and stamps `category_message_id` then; every
        # tick after that is free (see run_reply_catch_scan).
        with db.db_session() as conn:
            db.sort_replied_lead(conn, lead_id, campaign_id, label)
        return {"status": "ok", "note": f"recorded, no draft — {reason}"}

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

    interested_sheet.sync_interested(
        campaign_id, lead_id, raw_lead.get("email") or "", raw_lead.get("first_name") or "",
        raw_lead.get("company_name") or "", db.now_iso(),
    )

    thread = _fetch_thread_with_reply(campaign_id, lead_id)
    if not thread or thread[-1].kind != "reply":
        # The lead is in the inbox from phase 1 regardless, so this costs the
        # draft, not the message.
        return {"status": "ignored", "reason": "no unanswered lead reply in thread"}

    # Phase 3 — how hot is this lead? Separate question from phase 2's: that one
    # asks whether a human wrote this at all, this one asks whether they asked to
    # talk. A 🔥 rating pins them to the top of the inbox and shortens their
    # follow-up cadence to 24h (app/lead_temperature.py). Runs on the real
    # thread rather than the webhook's copy of the text, and outside every
    # transaction, since it can call a model.
    lead_temperature.record(lead_id, campaign_id, thread)

    with db.db_session() as conn:
        # Refine the placeholder summary with the real thread: the exact
        # timestamp, and the message as Smartlead stored it rather than the
        # webhook's copy of it. Also stamp category_message_id now that a real
        # message id exists — this is what lets run_reply_catch_scan's next
        # tick recognise this exact message as already judged and skip
        # calling the classifier on it again.
        last = thread[-1]
        db.upsert_lead_state(
            conn, lead_id, campaign_id,
            last_message_preview=to_plain_text(last.body)[:200],
            last_message_at=last.timestamp.astimezone(timezone.utc).isoformat(),
        )
        db.mark_category_judged(conn, lead_id, campaign_id, last.message_id)
        if db.has_open_draft(conn, lead_id, campaign_id):
            return {"status": "ok", "note": "draft already exists after clearing stale ones"}

    # generate_draft runs outside the session on purpose (see _record_incoming).
    campaign_name = payload.get("campaign_name", "")
    with db.db_session() as conn:
        draft_id = pipeline.create_draft(conn, raw_lead, campaign_name, "reply", thread)
        draft = db.get_draft(conn, draft_id)

    _notify_n8n(dict(draft))
    return {"status": "ok", "draft_id": draft_id}


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
