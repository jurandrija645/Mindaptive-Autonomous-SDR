import json
import logging
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import (
    accounts,
    campaign_analytics,
    campaign_conversations,
    campaign_copy,
    campaign_deliverability,
    campaign_report,
)
from app import candidates as candidates_module
from app import db, drafter, google_oauth, lead_temperature, library, message_templates, models_registry
from app import pipeline, scheduler, signatures, smartlead
from app import translator, uploads, webhook
from app.exports import sheet_export
from app.auth import install_session_middleware, is_authed, require_auth
from app.config import settings
from app.detector import (
    NormalizedMessage,
    last_sender_email,
    next_reply_cc,
    next_reply_to,
)
from app.email_clean import clean_email_html, to_plain_text
from app.thread_utils import (
    html_to_marked_text,
    next_morning_send_utc,
    render_emphasis,
    text_to_html,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")

app = FastAPI(title="Mindaptive Responder")
install_session_middleware(app)
app.include_router(webhook.router)


class NoCacheStaticFiles(StaticFiles):
    """Static assets change with every deploy but are served from the same URL
    (/static/style.css, /static/app.js) — without this, a browser or the
    Cloudflare tunnel in front of prod can keep serving a pre-redesign file
    that no longer matches the current HTML's class names, silently
    "unstyling" the whole page after a deploy. Force revalidation instead."""

    def is_not_modified(self, *args, **kwargs) -> bool:
        return False

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/static", NoCacheStaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
# Cache-busts /static/style.css and /static/app.js URLs on every process
# restart, so a deploy can never leave a stale asset paired with new HTML.
templates.env.globals["static_version"] = str(int(time.time()))


@app.on_event("startup")
def on_startup():
    db.init_db()
    scheduler.start_scheduler()
    # Warm the campaigns lists once at boot (background, doesn't delay startup)
    # so the first time the tab is opened after a deploy it's already instant.
    _warm_campaign_caches()


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Browsers auto-request /favicon.ico; point it at the SVG we ship so this
    # doesn't 404 (the <link> tags in base.html already cover modern browsers).
    return RedirectResponse(url="/static/favicon.svg", status_code=307)


# ---- auth pages ----

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if is_authed(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login_submit(request: Request, password: str = Form(...)):
    if settings.app_password and password == settings.app_password:
        request.session["authed"] = True
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Wrong password"}, status_code=401
    )


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "dry_run": settings.dry_run,
            "auto_send": settings.auto_send_followups,
        },
    )


# ---- shared helpers ----

def _fmt_time(ts) -> str:
    if not ts:
        return ""
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            return ts
    else:
        dt = ts
    return dt.strftime("%b %d, %Y · %H:%M")


def _parse_ts(raw) -> datetime | None:
    """Timestamps reach us in two shapes: isoformat's "2026-07-21T09:21:00+00:00"
    and, from a thread snapshot (dumped with `default=str`), the same instant
    with a space instead of the T. fromisoformat reads both."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _snapshot_outdated(snapshot: list[dict], lead) -> bool:
    """True when the thread has moved on since this draft was generated — in
    practice Andrew replying straight from Smartlead's own inbox, which a
    snapshot frozen at generation time can never learn about on its own.

    leads_state.last_message_at is rewritten by every scan *before* it checks
    for an open draft (scheduler._process_lead), so this is a DB read rather
    than a Smartlead call: opening a lead whose thread hasn't moved still costs
    no API request. Only a strictly newer row counts — the webhook reply path
    drafts without touching last_message_at, so a snapshot that's ahead of the
    row is normal and must not force a re-fetch on every open."""
    db_last = _parse_ts(lead["last_message_at"]) if lead is not None else None
    if db_last is None:
        return False
    stamps = [ts for ts in (_parse_ts(m.get("timestamp")) for m in snapshot) if ts]
    return not stamps or db_last > max(stamps)


def _draft_thread_outdated(draft, lead) -> bool:
    """Same question, asked about a draft row — its *text* was written against
    that stale thread, which the UI has to warn about even though the send path
    re-derives the threading identifiers from a fresh fetch."""
    if draft is None or not draft["thread_snapshot"]:
        return False
    return _snapshot_outdated(json.loads(draft["thread_snapshot"]), lead)


def _draft_signature_html(draft, raw: list[dict]) -> str:
    """The signature this draft will actually ship with.

    Resolved in the same order the send path uses (scheduler._send_due_draft):
    the live thread's last sender first, the address stored on the draft as the
    fallback — so the preview and the outgoing email can't disagree. The stored
    signature_html wins when it has one, which is the normal case; recomputing
    only matters for a draft created while the persona couldn't be resolved.

    Returns "" when no persona resolves at all, which the UI has to say out
    loud: an unsigned email is not something to discover after sending."""
    stored = draft["signature_html"] or ""
    if stored:
        return stored
    sender = last_sender_email(_thread_as_messages(raw)) or (draft["sender_email"] or "").strip()
    if not sender:
        log.warning("draft %s has no resolvable sender — no signature", draft["id"])
        return ""
    return signatures.get_signature_html(sender)


def _load_thread_raw(campaign_id: int, lead_id: int) -> list[dict]:
    """Thread as a list of NormalizedMessage-shaped dicts — from the open
    draft's snapshot while that snapshot is still current, otherwise a live
    Smartlead fetch.

    Both branches carry the full field set (the snapshot is dumped from
    `m.__dict__`), so _thread_as_messages can rebuild real NormalizedMessages
    from either one and the recipients preview needs no extra API call.

    The snapshot is frozen at generation time and never rewritten, so it is
    only trustworthy until the thread moves. Without the _snapshot_outdated
    check a message sent from Smartlead's own inbox stayed invisible here for
    as long as the draft sat open, while the inbox list — reading
    leads_state — showed it correctly."""
    with db.db_session() as conn:
        draft = db.get_open_draft(conn, lead_id, campaign_id)
        lead = db.get_lead_state(conn, lead_id, campaign_id)
    if draft and draft["thread_snapshot"]:
        snapshot = json.loads(draft["thread_snapshot"])
        if not _snapshot_outdated(snapshot, lead):
            return snapshot
    thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
    return [{**m.__dict__, "timestamp": m.timestamp.isoformat()} for m in thread]


def _thread_as_messages(raw: list[dict]) -> list[NormalizedMessage]:
    """Rebuild NormalizedMessage objects from the raw thread dicts so the very
    same detector helpers that decide To/Cc at send time can be previewed in
    the UI. Timestamps only need to survive round-tripping here (ordering is
    already fixed by normalize_thread), not be re-derived."""
    out = []
    for m in raw:
        out.append(
            NormalizedMessage(
                kind=m.get("kind") or "unknown",
                timestamp=datetime.now(timezone.utc),
                message_id=str(m.get("message_id") or ""),
                body=m.get("body") or "",
                from_email=m.get("from_email") or "",
                to_email=m.get("to_email") or "",
                stats_id=str(m.get("stats_id") or ""),
                cc=m.get("cc") or "",
            )
        )
    return out


_EMAIL_RE = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")


def _clean_cc(raw) -> str:
    """Normalize the Cc box into what Smartlead's reply-email-thread expects: a
    comma-separated list of bare addresses. Anything that isn't an address is
    dropped rather than passed through — a malformed Cc fails the whole send,
    and this is free-text Andrew types by hand. Returns "" for "no Cc", which
    is stored as a real override (see drafts.cc_override)."""
    if not isinstance(raw, str):
        return ""
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[,;\s]+", raw):
        addr = part.strip().strip("<>")
        key = addr.lower()
        if addr and key not in seen and _EMAIL_RE.match(addr):
            seen.add(key)
            out.append(addr)
    return ",".join(out)


def _recipient_updates(body: dict) -> dict:
    """Draft columns to write from a send/schedule request's recipient fields.
    A missing key means "leave the override alone"; an empty To is ignored
    rather than stored, since sending to nobody is never what's meant."""
    updates: dict = {}
    if "cc" in body:
        updates["cc_override"] = _clean_cc(body.get("cc"))
    if "to" in body:
        to = _clean_cc(body.get("to")).split(",")[0]
        if to:
            updates["to_override"] = to
    return updates


def _attachment_updates(body: dict) -> dict:
    """The drafts.attachments column to write from a send/schedule/save request.

    The client sends **slugs only** and the file_url is resolved here, against
    the library's own listing. That direction matters: Smartlead fetches
    file_url from its own servers, so a client-supplied URL would be an open
    invitation to make Smartlead retrieve anything at all and mail it out under
    Andrew's name. A slug that doesn't resolve is dropped rather than failing
    the send — the draft card lists what's attached, so it was seen before the
    click, and losing a PDF is better than losing the email.

    A missing "attachments" key means "leave it alone"; an empty list is a real
    value meaning Andrew removed them.
    """
    if "attachments" not in body:
        return {}
    slugs = body.get("attachments") or []
    if not isinstance(slugs, list):
        return {}
    available = {entry["slug"]: entry for entry in library.listing()}
    chosen = []
    for slug in slugs:
        entry = available.get(slug) if isinstance(slug, str) else None
        if not entry:
            log.warning("attachment slug %r is not in the library — dropped", slug)
            continue
        chosen.append(
            {
                "slug": entry["slug"],
                "file_name": entry["file_name"],
                "file_url": entry["url"],
                "file_type": entry["file_type"],
                "file_size": entry["file_size"],
            }
        )
    return {"attachments": json.dumps(chosen) if chosen else None}


def _recipients_payload(raw: list[dict], lead_email: str, draft) -> dict:
    """What the next send will go to, shown above Send/Schedule so a message is
    never fired at an address Andrew hasn't seen. `cc` is the draft's explicit
    override when one exists (including a deliberately emptied one), otherwise
    the auto-derived list _send_due_draft would use."""
    messages = _thread_as_messages(raw)
    own_email = last_sender_email(messages)
    auto_cc = next_reply_cc(messages, own_email=own_email)
    auto_to = next_reply_to(messages, lead_email=lead_email)
    cc_override = draft["cc_override"] if draft is not None else None
    to_override = draft["to_override"] if draft is not None else None
    return {
        "to": to_override or auto_to,
        "cc": auto_cc if cc_override is None else cc_override,
        "auto_cc": auto_cc,
        "cc_is_override": cc_override is not None,
        # The address the lead was imported under, shown only when the reply
        # came from somewhere else — that mismatch is the whole point.
        "lead_email": lead_email,
        "from": own_email,
    }


def _thread_payload(raw: list[dict], lead_name: str) -> list[dict]:
    # Attach a cached English translation per message when one already exists
    # (from a prior translate), so the client can default that message to
    # English. This is a lookup only — no message is translated on load, so
    # opening a lead never spends tokens; English is the default solely for
    # messages already in the cache. Keyed identically to the translate
    # endpoints (hash of the plain-text body).
    plains = [to_plain_text(m.get("body")) for m in raw]
    hashes = [translator.source_hash(p) if p.strip() else None for p in plains]
    with db.db_session() as conn:
        cached = db.get_cached_translations(conn, [h for h in hashes if h])

    out = []
    for m, h in zip(raw, hashes):
        is_us = m.get("kind") == "sent"
        english = clean_email_html(cached[h]) if (h and h in cached) else None
        out.append(
            {
                "who": "us" if is_us else "lead",
                "name": "You" if is_us else (lead_name or "Lead"),
                "time": _fmt_time(m.get("timestamp")),
                # Which mailbox this actually came from — for a lead's reply
                # that's often a real person (marko@company.com) answering a
                # cold email sent to a generic info@ address, so it's the only
                # place the true counterpart is visible.
                "from_email": (m.get("from_email") or "").strip(),
                "html": clean_email_html(m.get("body")),
                "english": english,
            }
        )
    return out


def _open_draft_set(conn) -> set[tuple[int, int]]:
    """Leads with a draft waiting for review — 'pending' only, deliberately not
    'scheduled'. This backs the inbox's green ready-dot, and a scheduled draft
    needs nothing from Andrew; it also no longer appears in the inbox at all
    (db.list_inbox), so counting it here would only light a dot on the one case
    that still shows through: a lead who replied while a follow-up was queued."""
    rows = conn.execute(
        "SELECT DISTINCT lead_id, campaign_id FROM drafts WHERE status = 'pending'"
    ).fetchall()
    return {(r["lead_id"], r["campaign_id"]) for r in rows}


def _row_payload(l: dict, open_set: set) -> dict:
    return {
        "campaign_id": l["campaign_id"],
        "lead_id": l["lead_id"],
        "name": l["name"] or l["email"] or "Lead",
        "company": l["company"] or "",
        "email": l["email"] or "",
        "campaign_name": l["campaign_name"] or "",
        "category": l["category"] or "waiting",
        # Smartlead's own category name for this lead, as of the last time the
        # scan or the 60s reply poll looked (see db.py's schema comment) —
        # shown next to "Change status" so a manual change isn't a guess.
        "smartlead_category": l["smartlead_category"] or "",
        # How hot the lead is — a separate axis from `category` above, and the
        # thing db.list_inbox sorts on first (app/lead_temperature.py).
        "temperature": lead_temperature.current(l),
        "temperature_reason": l["temperature_reason"] or "",
        "temperature_locked": bool(l["temperature_locked"]),
        "language": (l["language"] or "").upper(),
        "preview": l["last_message_preview"] or "",
        "last_message_at": _fmt_time(l["last_message_at"]),
        "last_message_kind": l["last_message_kind"],
        "has_draft": (l["lead_id"], l["campaign_id"]) in open_set,
        "archive_reason": l["archive_reason"],
        "snooze_until": l["snooze_until"],
    }


def _inbox_payload() -> list[dict]:
    with db.db_session() as conn:
        leads = [dict(r) for r in db.list_inbox(conn)]
        open_set = _open_draft_set(conn)
    return [_row_payload(l, open_set) for l in leads]


def _archive_payload() -> dict:
    with db.db_session() as conn:
        archived = [dict(r) for r in db.list_archived(conn)]
        snoozed = [dict(r) for r in db.list_snoozed(conn)]
        open_set = _open_draft_set(conn)
    return {
        "archived": [_row_payload(l, open_set) for l in archived],
        "snoozed": [_row_payload(l, open_set) for l in snoozed],
    }


def _draft_payload(draft) -> dict | None:
    if draft is None:
        return None
    return {
        "id": draft["id"],
        "kind": draft["kind"],
        "status": draft["status"],
        "body_html": draft["body_html"],
        "body_translation": draft["body_translation"],
        "signature_html": draft["signature_html"],
        "scheduled_at": _fmt_time(draft["scheduled_at"]) if draft["scheduled_at"] else None,
        "attachments": scheduler.draft_attachments(draft),
    }


def _scheduled_payload() -> list[dict]:
    with db.db_session() as conn:
        drafts = [dict(r) for r in db.list_scheduled(conn)]
    out = []
    for d in drafts:
        out.append(
            {
                "draft_id": d["id"],
                "campaign_id": d["campaign_id"],
                "lead_id": d["lead_id"],
                "name": d["lead_name"] or d["lead_email"] or "Lead",
                "company": d["lead_company"] or "",
                "email": d["lead_email"] or "",
                "campaign_name": d["campaign_name"] or "",
                "preview": to_plain_text(d["body_html"])[:200],
                "scheduled_at": _fmt_time(d["scheduled_at"]),
            }
        )
    return out


# ---- inbox API ----

@app.get("/api/inbox")
def api_inbox(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse({"leads": _inbox_payload(), "scan_running": scheduler.is_scan_running()})


@app.get("/api/archive")
def api_archive(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse(_archive_payload())


@app.get("/api/scheduled")
def api_scheduled(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse({"scheduled": _scheduled_payload()})


def _lead_detail_payload(campaign_id: int, lead_id: int) -> dict:
    with db.db_session() as conn:
        lead = db.get_lead_state(conn, lead_id, campaign_id)
        draft = db.get_open_draft(conn, lead_id, campaign_id)
    lead_name = (lead["name"] if lead else None) or "Lead"
    raw = _load_thread_raw(campaign_id, lead_id)
    draft_payload = _draft_payload(draft)
    # Follow-ups default their Schedule picker to the lead's next weekday
    # morning (campaign timezone) so they land when the lead actually reads
    # email. Replies deliberately get no suggestion — those should go out now.
    if draft_payload and draft_payload["kind"] == "followup":
        tz_guess = (lead["timezone_guess"] if lead else None) or ""
        draft_payload["suggested_schedule_at"] = next_morning_send_utc(tz_guess).isoformat()
    if draft_payload:
        draft_payload["recipients"] = _recipients_payload(
            raw, (lead["email"] if lead else "") or "", draft
        )
        # The thread above is always live; this draft's *text* may not be. It
        # was written against the thread as it stood at generation time, so a
        # message sent since then (typically from Smartlead directly) means the
        # draft can be answering something that's already been said.
        draft_payload["thread_moved_on"] = _draft_thread_outdated(draft, lead)
        # Recomputed rather than read straight off the row: the column is
        # filled once at creation and a draft that missed it would otherwise
        # show no signature here and send none either.
        draft_payload["signature_html"] = _draft_signature_html(draft, raw)
    return {
        "lead": {
            "name": lead_name,
            "company": (lead["company"] if lead else "") or "",
            "email": (lead["email"] if lead else "") or "",
            "campaign_name": (lead["campaign_name"] if lead else "") or "",
            "language": ((lead["language"] if lead else "") or "").upper(),
            "language_name": translator.language_name(lead["language"]) if (lead and lead["language"]) else None,
            "category": (lead["category"] if lead else "waiting") or "waiting",
            "smartlead_category": (lead["smartlead_category"] if lead else "") or "",
            "temperature": lead_temperature.current(lead),
            "temperature_reason": (lead["temperature_reason"] if lead else "") or "",
            "temperature_locked": bool(lead["temperature_locked"]) if lead else False,
            "archive_reason": lead["archive_reason"] if lead else None,
            "archived_at": _fmt_time(lead["archived_at"]) if lead and lead["archived_at"] else None,
            "snooze_until": lead["snooze_until"] if lead else None,
            "research_summary": (lead["research_summary"] if lead else None) or None,
            "researched_at": _fmt_time(lead["researched_at"]) if lead and lead["researched_at"] else None,
            "email_display_name": (lead["email_display_name"] if lead else None) or None,
            # Template placeholder values, resolved server-side so the modal's
            # preview and the message that actually goes out are the same
            # string. The client only substitutes (app.js fillPlaceholders).
            "placeholders": message_templates.placeholders_for(
                lead["name"] if lead else None, lead["company"] if lead else None
            ),
        },
        "thread": _thread_payload(raw, lead_name),
        "draft": draft_payload,
        "generating": candidates_module.is_generating(campaign_id, lead_id),
        # Only meaningful when there's no draft to show; the client falls back
        # to its own wording when this is absent.
        "generation_error": candidates_module.last_error(campaign_id, lead_id),
    }


@app.get("/api/leads/{campaign_id}/{lead_id}")
def api_lead(request: Request, campaign_id: int, lead_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse(_lead_detail_payload(campaign_id, lead_id))


@app.post("/api/leads/{campaign_id}/{lead_id}/translate")
async def api_translate_message(request: Request, campaign_id: int, lead_id: int):
    """Translates a single thread message on demand (per-message translate
    button), not the whole thread at once — most of a thread is often
    already in a language Andrew reads fine, so translating everything on
    one click wastes calls on messages nobody asked to see in English."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    index = body.get("index")
    if not isinstance(index, int):
        return JSONResponse({"error": "index required"}, status_code=400)
    raw = _load_thread_raw(campaign_id, lead_id)
    if index < 0 or index >= len(raw):
        return JSONResponse({"error": "index out of range"}, status_code=400)
    plain = to_plain_text(raw[index].get("body"))
    with db.db_session() as conn:
        english = translator.translate_segments_cached(conn, [plain])[0]
    return JSONResponse({"html": clean_email_html(english)})


@app.post("/api/leads/{campaign_id}/{lead_id}/translate-thread")
async def api_translate_thread(request: Request, campaign_id: int, lead_id: int):
    """Batched sibling of /translate above, for the "Translate entire thread"
    button: translates every requested message in ONE Claude call instead of
    one call per message. `indices` lets the client skip messages it already
    has cached from an earlier per-message or whole-thread translate; omitted
    (or empty) means "all of them"."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    raw = _load_thread_raw(campaign_id, lead_id)
    indices = body.get("indices")
    if not isinstance(indices, list) or not indices:
        indices = list(range(len(raw)))
    indices = [i for i in indices if isinstance(i, int) and 0 <= i < len(raw)]
    plains = [to_plain_text(raw[i].get("body")) for i in indices]
    with db.db_session() as conn:
        englishes = translator.translate_segments_cached(conn, plains)
    htmls = [clean_email_html(e) for e in englishes]
    return JSONResponse({"indices": indices, "htmls": htmls})


@app.post("/api/leads/{campaign_id}/{lead_id}/generate")
async def api_generate(request: Request, campaign_id: int, lead_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    steering_note = (body.get("steering_note") or "").strip() or None
    model = body.get("model") or None
    if not models_registry.is_allowed(model):
        model = None  # falls back to the dashboard-set default model
    use_web_search = body.get("use_web_search")
    if not isinstance(use_web_search, bool):
        use_web_search = None  # falls back to the prior-research auto-decide

    # `base_draft` is what's in the editor right now, sent by the client. The
    # model gets it as the thing it is editing, which is the whole point of a
    # steering note like "make the second paragraph shorter" — before this it
    # saw only the note and wrote a brand new email, so a request to change one
    # line rewrote the message. It's the editor's content rather than the stored
    # draft so Andrew's own hand edits survive the regeneration too; the stored
    # body is the fallback for callers that don't send one.
    #
    # The old draft is NOT retired here. It used to be, before generation had
    # even started, so a regenerate that then failed left the lead with nothing
    # at all: the message was gone, the editor was replaced by an error line,
    # and a second attempt had no base_draft to revise — so the steering note
    # applied to nothing and the model wrote the same email over again, which
    # reads as "it just gives me the old one back". A generation that fails must
    # cost nothing. generate_for_lead retires the previous draft only once the
    # replacement is safely stored.
    with db.db_session() as conn:
        existing = db.get_open_draft(conn, lead_id, campaign_id)
        # Marked text: the model has to see which line is bold, or "shorten the
        # second paragraph" comes back with the emphasis quietly dropped.
        base_draft = html_to_marked_text(body.get("base_draft") or "")
        if not base_draft and existing is not None:
            base_draft = html_to_marked_text(existing["body_html"] or "")

    # generate_for_lead calls Claude synchronously (web search/fetch tools) and
    # can take minutes — long enough to hit Cloudflare's ~100s tunnel timeout
    # (confirmed via a real 524 in production) if held open as one request.
    # Kick it off in the background and let the client poll GET
    # /api/leads/{cid}/{lid} (which reports `generating`) instead.
    started = candidates_module.generate_for_lead_in_background(
        campaign_id,
        lead_id,
        steering_note,
        model=model,
        use_web_search=use_web_search,
        base_draft=base_draft or None,
    )
    return JSONResponse({"started": started})


@app.post("/api/leads/{campaign_id}/{lead_id}/quick-draft")
async def api_quick_draft(request: Request, campaign_id: int, lead_id: int):
    """Drops a canned quick-pick follow-up straight in as a draft. Unlike
    /generate, this is cheap and fast enough (one small translation call, no
    web tools) to run synchronously — no background thread, no polling."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "No text given."}, status_code=400)
    # The Generate dropdown's current pick, so choosing a model there moves
    # template localization with it. Absent/invalid falls back to the
    # "Translating templates" role (which itself defaults to the drafting model).
    model = body.get("model") or None
    if not models_registry.is_allowed(model):
        model = None
    draft_id, warning = candidates_module.quick_followup(
        campaign_id, lead_id, text, model=model
    )
    if not draft_id:
        return JSONResponse({"error": "Could not create draft for this lead."}, status_code=404)
    payload = _lead_detail_payload(campaign_id, lead_id)
    # Set only when the template is going out in English and shouldn't be —
    # this path can't fail loudly (localize_quick_text returns its English input
    # both when it has no language and when the call errors), so the one place
    # that can say so is the response to the click that caused it.
    if warning:
        payload["warning"] = warning
    return JSONResponse(payload)


# ---- message templates ----
#
# The canned follow-ups behind the "Message templates" modal. They used to be a
# hardcoded array in app.js, so changing a word meant a deploy; they now live in
# SQLite and are edited from the dashboard. Every mutating route returns the
# whole fresh list so the client never has to reconcile state by hand.

def _templates_payload() -> dict:
    with db.db_session() as conn:
        rows = db.list_message_templates(conn)
    return {
        "templates": [
            {"id": r["id"], "label": r["label"] or "", "text": r["text"], "position": r["position"]}
            for r in rows
        ]
    }


@app.get("/api/templates")
def api_templates(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse(_templates_payload())


@app.post("/api/templates")
async def api_template_create(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "Template text is required."}, status_code=400)
    with db.db_session() as conn:
        db.create_message_template(conn, (body.get("label") or "").strip(), text)
    return JSONResponse(_templates_payload())


@app.patch("/api/templates/{template_id}")
async def api_template_update(request: Request, template_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    fields: dict = {}
    if "label" in body:
        fields["label"] = (body.get("label") or "").strip()
    if "text" in body:
        text = (body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "Template text is required."}, status_code=400)
        fields["text"] = text
    with db.db_session() as conn:
        if db.get_message_template(conn, template_id) is None:
            return JSONResponse({"error": "Template not found."}, status_code=404)
        if fields:
            db.update_message_template(conn, template_id, **fields)
    return JSONResponse(_templates_payload())


@app.delete("/api/templates/{template_id}")
def api_template_delete(request: Request, template_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        if db.get_message_template(conn, template_id) is None:
            return JSONResponse({"error": "Template not found."}, status_code=404)
        db.delete_message_template(conn, template_id)
    return JSONResponse(_templates_payload())


@app.post("/api/templates/{template_id}/move")
async def api_template_move(request: Request, template_id: int):
    """Moves a template one slot up or down, then renumbers every position —
    cheaper to reason about than swapping two values, and it heals any
    duplicate positions a previous edit left behind."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    direction = body.get("direction")
    if direction not in ("up", "down"):
        return JSONResponse({"error": "direction must be 'up' or 'down'."}, status_code=400)
    with db.db_session() as conn:
        ids = [r["id"] for r in db.list_message_templates(conn)]
        if template_id not in ids:
            return JSONResponse({"error": "Template not found."}, status_code=404)
        i = ids.index(template_id)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            db.reorder_message_templates(conn, ids)
    return JSONResponse(_templates_payload())


@app.post("/api/leads/{campaign_id}/{lead_id}/name")
async def api_set_lead_name(request: Request, campaign_id: int, lead_id: int):
    """Manual correction for when Smartlead's imported first_name is wrong.

    Two things happen, in this order. Locally: the name is saved and locked
    (name_locked=1) so the next scan (which otherwise overwrites
    leads_state.name from Smartlead's own first_name every run, see
    scheduler._process_lead) doesn't revert it. Then the correction is pushed
    back to Smartlead itself (smartlead.update_lead), because the old
    dashboard-only rename left the two permanently disagreeing: every later
    Smartlead send still merged `{{first_name}}` as the wrong name, and so did
    anyone reading the lead in Smartlead's own inbox.

    The local save deliberately comes first and the push is fail-soft — a
    rejected API call must not lose the correction, and the lock is exactly what
    keeps the right name in place when the push didn't land. The caller is told
    which of the two happened (`smartlead_synced` / `warning`) instead of the
    request quietly succeeding, since "why is it still wrong in Smartlead" is
    the question that got this written in the first place."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required."}, status_code=400)
    with db.db_session() as conn:
        db.upsert_lead_state(conn, lead_id, campaign_id, name=name, name_locked=1)
        state = db.get_lead_state(conn, lead_id, campaign_id)

    email = (state["email"] if state else None) or ""
    warning = None
    if not email:
        # Smartlead won't take the update without it, and leads_state.email is
        # only filled by a scan — a lead that has never been scanned has none.
        warning = "Renamed here, but not in Smartlead: no email address on file for this lead yet."
    elif settings.dry_run:
        log.info(
            "[DRY_RUN] would set Smartlead first_name for %s/%s to %r",
            campaign_id, lead_id, name,
        )
        warning = "Renamed here only — DRY RUN, so Smartlead was not updated."
    else:
        try:
            smartlead.update_lead(campaign_id, lead_id, {"email": email, "first_name": name})
        except smartlead.SmartleadError as e:
            log.warning("Smartlead first_name update failed for %s/%s: %s", campaign_id, lead_id, e)
            warning = f"Renamed here, but Smartlead rejected the update: {e}"
    return JSONResponse({"ok": True, "smartlead_synced": warning is None, "warning": warning})


@app.post("/api/leads/{campaign_id}/{lead_id}/compose")
def api_compose(request: Request, campaign_id: int, lead_id: int):
    """Opens a blank, directly-editable draft for this lead — no Claude call
    at all. Andrew writes the message himself in the same editor/Send/Schedule
    flow every other draft uses."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    draft_id = candidates_module.manual_draft(campaign_id, lead_id)
    if not draft_id:
        return JSONResponse({"error": "Could not create draft for this lead."}, status_code=404)
    return JSONResponse(_lead_detail_payload(campaign_id, lead_id))


# ---- image uploads ----

@app.post("/api/uploads")
async def api_upload(request: Request):
    """Accepts an image pasted/dropped into the draft editor and returns the
    absolute URL to reference it by. Andrew used to round-trip these through
    imgur by hand; this keeps them on our own domain so the editor can also
    resize them."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"error": "No file uploaded."}, status_code=400)
    data = await upload.read()
    try:
        url, name = uploads.save_image(data)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"url": url, "name": name})


@app.get("/i/{name}")
def serve_upload(name: str):
    """Deliberately unauthenticated — the recipient's mail client fetches this
    with no session. The random filename is the only credential."""
    resolved = uploads.resolve(name)
    if not resolved:
        return JSONResponse({"error": "Not found"}, status_code=404)
    path, ctype = resolved
    return FileResponse(path, media_type=ctype, headers={"Cache-Control": "public, max-age=31536000"})


# ---- attachment library ----

@app.get("/f/{slug}")
def serve_library_file(slug: str):
    """The second deliberately-unauthenticated read route, and for a stronger
    reason than /i/: **Smartlead's own servers fetch this URL** to build the
    attachment (verified 2026-07-31), and they have no session. If this needed
    auth, attachments could not work at all.

    Unlike /i/, the name here is human and guessable — these are marketing PDFs
    written to be handed to strangers, and the library is the client's own
    source-docs folder. Don't put anything in it that isn't meant to leave the
    building.
    """
    resolved = library.resolve(slug)
    if not resolved:
        return JSONResponse({"error": "Not found"}, status_code=404)
    path, ctype, filename = resolved
    return FileResponse(
        path,
        media_type=ctype,
        headers={
            "Cache-Control": "public, max-age=86400",
            # inline so a click in the dashboard previews the PDF rather than
            # downloading it; the real name is what the mail client shows.
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


@app.get("/api/library")
def api_library(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse({"files": library.listing()})


@app.post("/api/library")
async def api_library_upload(request: Request):
    """Add a file to the library from the browser, so a new PDF doesn't need a
    commit and a deploy the way clients/<slug>/source-docs/ does."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"error": "No file uploaded."}, status_code=400)
    data = await upload.read()
    try:
        entry = library.save(data, getattr(upload, "filename", "") or "file")
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"file": entry, "files": library.listing()})


@app.delete("/api/library/{slug}")
def api_library_delete(request: Request, slug: str):
    redirect = require_auth(request)
    if redirect:
        return redirect
    if not library.delete(slug):
        return JSONResponse(
            {"error": "Not an uploaded file — shipped documents can't be deleted here."},
            status_code=400,
        )
    return JSONResponse({"files": library.listing()})


# ---- draft translation (English tab) ----

@app.post("/api/drafts/{draft_id}/translate")
async def api_draft_translate(request: Request, draft_id: int):
    """Cheap (Haiku), always-fresh: translates whatever is CURRENTLY in the
    Original editor, not a stale value from generation time — this is what
    keeps the English tab from ever going stale after an edit."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    # Marked text, not plain: bold survives as `**markers**` through the
    # translation and is rendered back to <strong> below, so the English tab
    # shows the same emphasis the outgoing draft has.
    plain = html_to_marked_text(body.get("original_html", ""))
    if not plain.strip():
        return JSONResponse({"english_html": ""})
    with db.db_session() as conn:
        english = translator.translate_segments_cached(conn, [plain])[0]
    return JSONResponse({"english_html": render_emphasis(clean_email_html(english))})


@app.post("/api/drafts/{draft_id}/localize")
async def api_draft_localize(request: Request, draft_id: int):
    """Applies an English edit back onto the real (native-language) draft that
    will actually be sent — runs on Sonnet, since this becomes the outgoing
    message and quality matters here, unlike the cheap /translate above."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    # Marked text so the localizer is given the emphasis too — it's instructed
    # to keep the `**markers**` where they are, and text_to_html below turns
    # them back into <strong> on the draft that actually gets sent.
    english_text = html_to_marked_text(body.get("english_html", ""))
    if not english_text.strip():
        return JSONResponse({"error": "Nothing to apply."}, status_code=400)
    model = body.get("model") or None
    if not models_registry.is_allowed(model):
        model = None  # falls back to the dashboard-set default model

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return JSONResponse({"error": "Draft not found."}, status_code=404)
        lead = db.get_lead_state(conn, draft["lead_id"], draft["campaign_id"])

    target_lang = (lead["language"] if lead else None) or translator.detect_language(
        to_plain_text(draft["body_html"])
    )
    localized = translator.localize_draft(english_text, target_lang, model=model)
    # body_html is the message body only — the signature is never part of the
    # translate/localize round trip (that used to translate it and then append a
    # second copy). It's stored separately (signature_html) and appended once,
    # unchanged, at send time (scheduler.compose_send_body).
    new_body_html = text_to_html(localized)

    with db.db_session() as conn:
        db.update_draft(conn, draft_id, body_html=new_body_html, body_translation=english_text)
        draft = db.get_draft(conn, draft_id)
    return JSONResponse({"draft": _draft_payload(draft)})


# ---- lead status actions: category change / archive / snooze ----

# Categories where recategorizing should also stop Smartlead's own automated
# sequence — the lead has told us (or a bounce/opt-out told us) to stop.
PAUSE_CATEGORIES = {"Not Interested", "Do Not Contact", "Wrong Person", "Lead Opted Out", "We opted Out"}


@app.get("/api/models")
def api_models(request: Request):
    """Everything the model picker needs: both providers' models, their live
    per-million-token prices, whether each provider's API key is actually
    configured, and which one is currently the default."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    return _models_payload()


def _models_payload() -> JSONResponse:
    return JSONResponse({
        "models": models_registry.catalog(),
        "default": models_registry.default_model(),
        "roles": models_registry.roles_payload(),
    })


@app.post("/api/models/default")
async def api_set_default_model(request: Request):
    """Set the drafting model — the one used whenever nothing is explicitly
    picked (daily-scan auto-drafts, the webhook reply path, the dropdown's
    initial selection). Same setting as the Models panel's "Writing drafts"
    row; this is the dropdown's one-click shortcut to it."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    model = (body.get("model") or "").strip()
    try:
        models_registry.set_default_model(model)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return _models_payload()


@app.post("/api/models/role")
async def api_set_role_model(request: Request):
    """Point one task at a model (Models panel). A null/empty model clears the
    choice, putting that task back on its fallback chain — "follows Writing
    drafts" rather than pinned to whatever drafts happen to use today."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    role = (body.get("role") or "").strip()
    model = (body.get("model") or "").strip() or None
    try:
        models_registry.set_model_for(role, model)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return _models_payload()


@app.get("/api/categories")
def api_categories(request: Request):
    """Live list of every category Smartlead has configured (built-in + custom),
    so the "Change status" dropdown always matches Andrew's actual account
    instead of a hardcoded guess."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    try:
        categories = smartlead.fetch_categories()
    except smartlead.SmartleadError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return JSONResponse({"categories": sorted(categories.keys())})


@app.post("/api/leads/{campaign_id}/{lead_id}/category")
async def api_set_category(request: Request, campaign_id: int, lead_id: int):
    """Generic version of the old 'Not Interested' action — recategorizes the
    lead in Smartlead to whatever category was picked (pausing its sequence
    for the ones in PAUSE_CATEGORIES) and archives it locally under that
    reason. Picking 'Interested' instead restores it to the active inbox.
    Picking the configured meeting-booked category (settings.meeting_booked_
    category_name, matched fuzzily like the daily scan does) records the
    booking via db.mark_lead_booked instead of archiving, so the lead stays
    visible in the inbox immediately rather than reappearing only once the
    next scan un-archives it."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    category_name = (body.get("category_name") or "").strip()
    if not category_name:
        return JSONResponse({"error": "category_name is required."}, status_code=400)

    restoring = category_name == "Interested"
    booking = scheduler.norm_category_name(category_name) == scheduler.norm_category_name(
        settings.meeting_booked_category_name
    )
    pause = category_name in PAUSE_CATEGORIES

    if settings.dry_run:
        log.info(
            "[DRY_RUN] would set lead %s/%s Smartlead category to %r (pause_lead=%s)",
            campaign_id, lead_id, category_name, pause,
        )
    else:
        categories = smartlead.fetch_categories()
        category_id = categories.get(category_name)
        if category_id is None:
            return JSONResponse(
                {"error": f"Smartlead has no '{category_name}' category configured."},
                status_code=502,
            )
        try:
            smartlead.update_lead_category(campaign_id, lead_id, category_id, pause_lead=pause)
        except smartlead.SmartleadError as e:
            return JSONResponse({"error": str(e)}, status_code=502)

    with db.db_session() as conn:
        if restoring:
            db.upsert_lead_state(
                conn, lead_id, campaign_id,
                status="active", archived_at=None, archive_reason=None,
                smartlead_category=category_name,
            )
        elif booking:
            # Picking the booked category by hand is the same fact the scan
            # would record from Smartlead overnight — record it now rather
            # than archiving like every other category, or the lead vanishes
            # from the inbox until the next scan un-archives it (mark_lead_booked
            # only clears an archive *older* than booked_at).
            db.mark_lead_booked(conn, lead_id, campaign_id)
            db.upsert_lead_state(conn, lead_id, campaign_id, smartlead_category=category_name)
        else:
            db.upsert_lead_state(
                conn, lead_id, campaign_id,
                archived_at=db.now_iso(), archive_reason=category_name,
                category=scheduler._local_category_slug(category_name),
                smartlead_category=category_name,
            )
    return JSONResponse({"ok": True})


@app.post("/api/leads/{campaign_id}/{lead_id}/archive")
def api_archive_lead(request: Request, campaign_id: int, lead_id: int):
    """Local-only: hides an old/stale lead from the inbox without touching
    Smartlead. Reversible via /unarchive."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        db.upsert_lead_state(
            conn, lead_id, campaign_id, archived_at=db.now_iso(), archive_reason="manual"
        )
    return JSONResponse({"ok": True})


@app.post("/api/leads/{campaign_id}/{lead_id}/unarchive")
def api_unarchive_lead(request: Request, campaign_id: int, lead_id: int):
    """Restores an archived (or not-interested) lead back into the inbox. Does
    NOT revert the Smartlead category if it was changed by /not-interested."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        db.upsert_lead_state(conn, lead_id, campaign_id, archived_at=None, archive_reason=None)
    return JSONResponse({"ok": True})


@app.post("/api/leads/{campaign_id}/{lead_id}/temperature")
async def api_set_temperature(request: Request, campaign_id: int, lead_id: int):
    """Set how hot a lead is by hand — ❄️ cold / 🌤 warm / 🔥 very hot — or hand
    it back to the classifier with `"auto"`.

    An explicit rating also **locks** it (`temperature_locked`), so the next scan
    doesn't quietly overrule Andrew the way it used to overrule a corrected name
    before `name_locked` existed. That lock is the only thing that can cool a
    lead down, since the classifier itself only ever rates upwards.

    "auto" clears the lock *and* re-rates immediately off the live thread rather
    than waiting for the next pass. Clearing alone wouldn't be enough: a rating
    of 🔥 is sticky, so the classifier would keep returning "nothing to do" and
    the lead would stay hot forever. Re-rating costs one thread fetch and one
    cheap classifier call, on an explicit click."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    wanted = (body.get("temperature") or "").strip().lower()

    if wanted in lead_temperature.VALUES:
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, lead_id, campaign_id,
                temperature=wanted,
                temperature_reason="set by hand",
                temperature_locked=1,
            )
        return JSONResponse({"ok": True, "temperature": wanted, "locked": True})

    if wanted != "auto":
        return JSONResponse(
            {"error": f"temperature must be one of {', '.join(lead_temperature.VALUES)} or 'auto'."},
            status_code=400,
        )

    try:
        thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
    except Exception as e:
        log.exception("temperature re-rate: thread fetch failed for lead %s", lead_id)
        return JSONResponse({"error": f"Couldn't read the thread: {e}"}, status_code=502)

    # A blank slate rather than the stored row, so nothing about the manual
    # rating survives to short-circuit the read: not the lock, not the sticky
    # 🔥, not the message it was last judged from.
    reading = lead_temperature.read(thread, {})
    temperature = reading.temperature if reading else lead_temperature.COLD
    # `reading.reason` is None when the verdict didn't beat the (blank) starting
    # rating, i.e. the message read as cold; the per-rating wording covers it.
    # No reading at all means the lead has never written to us.
    reason = (
        (reading.reason or lead_temperature.REASONS[temperature])
        if reading
        else "no reply from this lead yet"
    )
    with db.db_session() as conn:
        db.upsert_lead_state(
            conn, lead_id, campaign_id,
            temperature=temperature,
            temperature_reason=reason,
            temperature_message_id=reading.message_id if reading else None,
            temperature_locked=0,
        )
    return JSONResponse(
        {"ok": True, "temperature": temperature, "reason": reason, "locked": False}
    )


@app.post("/api/leads/{campaign_id}/{lead_id}/snooze")
async def api_snooze_lead(request: Request, campaign_id: int, lead_id: int):
    """Hides the lead from the inbox until the given date, at which point it
    jumps to the top (see db.list_inbox's ordering)."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    until = (body.get("until") or "").strip()
    try:
        datetime.strptime(until, "%Y-%m-%d")
    except ValueError:
        return JSONResponse({"error": "Give a valid date (YYYY-MM-DD)."}, status_code=400)
    with db.db_session() as conn:
        db.upsert_lead_state(conn, lead_id, campaign_id, snooze_until=until)
    return JSONResponse({"ok": True})


@app.post("/api/leads/{campaign_id}/{lead_id}/unsnooze")
def api_unsnooze_lead(request: Request, campaign_id: int, lead_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        db.upsert_lead_state(conn, lead_id, campaign_id, snooze_until=None)
    return JSONResponse({"ok": True})


# ---- LinkedIn export to Google Sheets ----

@app.get("/api/google/status")
def api_google_status(request: Request):
    """What the Export for LinkedIn button should render as. `configured` is the
    client-side gate: with no spreadsheet set for this client there is nowhere
    to export to, so the button isn't drawn at all."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse({
        "configured": bool(settings.linkedin_sheet_id and google_oauth.is_configured()),
        "connected": google_oauth.is_connected(),
        "connect_url": "/oauth/google/start",
    })


@app.get("/oauth/google/start")
def oauth_google_start(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    try:
        # CSRF: Google echoes this back on the callback, which is the only proof
        # the code arriving there was requested by this browser session.
        state = secrets.token_urlsafe(24)
        request.session["google_oauth_state"] = state
        return RedirectResponse(url=google_oauth.authorize_url(state), status_code=303)
    except google_oauth.GoogleAuthError as e:
        return HTMLResponse(f"<p>{e}</p><p><a href='/dashboard'>Back</a></p>", status_code=400)


@app.get("/oauth/google/callback")
def oauth_google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Google sends the browser back here. A top-level GET navigation, so the
    lax session cookie rides along and require_auth passes as usual."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    expected = request.session.pop("google_oauth_state", None)
    if error:
        return HTMLResponse(
            f"<p>Google returned: {error}</p><p><a href='/dashboard'>Back</a></p>", status_code=400
        )
    if not code or not expected or state != expected:
        return HTMLResponse(
            "<p>That Google sign-in didn't match this browser session — start it again "
            "from the dashboard.</p><p><a href='/dashboard'>Back</a></p>",
            status_code=400,
        )
    try:
        google_oauth.exchange_code(code)
    except google_oauth.GoogleAuthError as e:
        return HTMLResponse(f"<p>{e}</p><p><a href='/dashboard'>Back</a></p>", status_code=400)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/api/google/disconnect")
def api_google_disconnect(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    google_oauth.disconnect()
    return JSONResponse({"ok": True})


@app.post("/api/leads/{campaign_id}/{lead_id}/export-linkedin")
def api_export_linkedin(request: Request, campaign_id: int, lead_id: int):
    """Starts the export on a background thread; the client polls the GET below.
    Same reason as bulk generate — a Smartlead fetch plus a thread summary plus
    a LinkedIn web search runs past Cloudflare's ~100s tunnel timeout.

    Deliberately not gated by DRY_RUN: it writes to Andrew's own spreadsheet and
    mails nobody, and gating it would make the feature untestable locally, where
    DRY_RUN stays on."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    if not settings.linkedin_sheet_id:
        return JSONResponse({"error": "LINKEDIN_SHEET_ID is not set."}, status_code=400)
    if not google_oauth.is_connected():
        return JSONResponse(
            {"error": "Not connected to Google — click Connect Google Sheets."},
            status_code=409,
        )
    started = sheet_export.export_lead_in_background(campaign_id, lead_id)
    return JSONResponse({
        "started": started,
        "running": sheet_export.is_running(campaign_id, lead_id),
    })


@app.get("/api/leads/{campaign_id}/{lead_id}/export-linkedin")
def api_export_linkedin_status(request: Request, campaign_id: int, lead_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse({
        "running": sheet_export.is_running(campaign_id, lead_id),
        "result": sheet_export.last_result(campaign_id, lead_id),
        "error": sheet_export.last_error(campaign_id, lead_id),
    })


# ---- draft actions (JSON) ----

@app.post("/api/drafts/{draft_id}/send")
async def api_send(request: Request, draft_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None or draft["status"] not in ("pending", "scheduled"):
            return JSONResponse({"error": "Draft is no longer sendable."}, status_code=409)
        log.info(
            "[SIG-DEBUG] api_send: draft_id=%s posted_body_len=%d stored_signature_len=%d sender_email=%s",
            draft_id, len(body.get("body_html") or ""), len(draft["signature_html"] or ""),
            draft["sender_email"],
        )
        updates = {"body_html": body.get("body_html", draft["body_html"])}
        # Only touch the overrides when the client actually sent the field, so a
        # client that doesn't know about recipients can't silently wipe one.
        updates.update(_recipient_updates(body))
        updates.update(_attachment_updates(body))
        db.update_draft(conn, draft_id, **updates)

    # _send_due_draft is what actually marks the lead "waiting" on a real
    # send (scheduler._mark_lead_waiting_on_them) — not done here too, since
    # that would also fire on a race-abort (a newer reply arrived since this
    # draft was drafted), which correctly leaves the lead needing a reply and
    # must not be immediately overwritten to "waiting" right after.
    scheduler._send_due_draft(dict(_get_draft_dict(draft_id)))
    return JSONResponse({"ok": True})


@app.post("/api/drafts/{draft_id}/schedule")
async def api_schedule(request: Request, draft_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    try:
        # Client sends UTC ISO (toISOString, may carry a Z suffix); naive
        # values from any older client are treated as UTC as before.
        dt = datetime.fromisoformat((body.get("scheduled_at", "")).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc) + timedelta(hours=1)

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return JSONResponse({"error": "Draft not found."}, status_code=404)
        updates = {
            "body_html": body.get("body_html", draft["body_html"]),
            "status": "scheduled",
            "scheduled_at": dt.isoformat(),
        }
        updates.update(_recipient_updates(body))
        updates.update(_attachment_updates(body))
        db.update_draft(conn, draft_id, **updates)
    return JSONResponse({"ok": True})


@app.post("/api/drafts/{draft_id}/skip")
def api_skip(request: Request, draft_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return JSONResponse({"error": "Draft not found."}, status_code=404)
        db.update_draft(conn, draft_id, status="skipped")
    return JSONResponse({"ok": True})


@app.post("/api/drafts/{draft_id}/stop")
def api_stop(request: Request, draft_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return JSONResponse({"error": "Draft not found."}, status_code=404)
        db.update_draft(conn, draft_id, status="skipped")
        db.upsert_lead_state(conn, draft["lead_id"], draft["campaign_id"], status="stopped")
    return JSONResponse({"ok": True})


# ---- metrics ----

@app.get("/api/metrics")
def api_metrics(request: Request):
    """Backs the dashboard's Stats view. Everything is derived from data the
    app already records (drafts, leads_state, candidates) — no new tracking.
    "Follow-up got a reply" is a proxy: a reply-kind draft created after the
    follow-up was sent (every unanswered lead reply auto-drafts one), or the
    lead's latest message being a reply newer than the send."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    try:
        days = max(1, min(365, int(request.query_params.get("days", "30"))))
    except ValueError:
        days = 30
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with db.db_session() as conn:
        sent_by_kind = {
            r["kind"]: r["n"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM drafts WHERE status = 'sent' AND sent_at >= ? GROUP BY kind",
                (since,),
            )
        }
        followups_sent = sent_by_kind.get("followup", 0)
        followup_replies = conn.execute(
            """SELECT COUNT(*) AS n FROM drafts d
               WHERE d.kind = 'followup' AND d.status = 'sent' AND d.sent_at >= ?
                 AND (EXISTS (SELECT 1 FROM drafts r
                              WHERE r.lead_id = d.lead_id AND r.campaign_id = d.campaign_id
                                AND r.kind = 'reply' AND r.created_at > d.sent_at)
                      OR EXISTS (SELECT 1 FROM leads_state l
                                 WHERE l.lead_id = d.lead_id AND l.campaign_id = d.campaign_id
                                   AND l.last_message_kind = 'reply' AND l.last_message_at > d.sent_at))""",
            (since,),
        ).fetchone()["n"]
        avg_reply_hours = conn.execute(
            """SELECT AVG((julianday(sent_at) - julianday(reply_email_time)) * 24.0) AS h
               FROM drafts
               WHERE kind = 'reply' AND status = 'sent' AND sent_at >= ?
                 AND reply_email_time IS NOT NULL""",
            (since,),
        ).fetchone()["h"]
        booked_total = conn.execute(
            "SELECT COUNT(*) AS n FROM leads_state WHERE booked_at IS NOT NULL"
        ).fetchone()["n"]
        booked_recent = conn.execute(
            "SELECT COUNT(*) AS n FROM leads_state WHERE booked_at >= ?", (since,)
        ).fetchone()["n"]
        recent_booked = [
            {
                "name": r["name"] or r["email"] or "Lead",
                "company": r["company"] or "",
                "booked_at": _fmt_time(r["booked_at"]),
            }
            for r in conn.execute(
                """SELECT name, email, company, booked_at FROM leads_state
                   WHERE booked_at IS NOT NULL ORDER BY booked_at DESC LIMIT 10"""
            )
        ]
        drafts_by_model = {
            (r["model"] or "manual / template"): r["n"]
            for r in conn.execute(
                "SELECT model, COUNT(*) AS n FROM drafts WHERE created_at >= ? GROUP BY model",
                (since,),
            )
        }
        open_candidates = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates WHERE status = 'open'"
        ).fetchone()["n"]
        pending_drafts = conn.execute(
            "SELECT COUNT(*) AS n FROM drafts WHERE status = 'pending'"
        ).fetchone()["n"]
        scheduled_drafts = conn.execute(
            "SELECT COUNT(*) AS n FROM drafts WHERE status = 'scheduled'"
        ).fetchone()["n"]

    return JSONResponse(
        {
            "days": days,
            "booked_total": booked_total,
            "booked_recent": booked_recent,
            "recent_booked": recent_booked,
            "sent_by_kind": sent_by_kind,
            "sent_total": sum(sent_by_kind.values()),
            "followups_sent": followups_sent,
            "followup_replies": followup_replies,
            "avg_reply_hours": round(avg_reply_hours, 1) if avg_reply_hours is not None else None,
            "drafts_by_model": drafts_by_model,
            "open_candidates": open_candidates,
            "pending_drafts": pending_drafts,
            "scheduled_drafts": scheduled_drafts,
        }
    )


# ---- campaigns ----

# Building the list means one Smartlead call per campaign for headline totals
# (~25 calls). Two things keep the tab instant despite that:
#   1. The result is cached for 12h and served immediately on every open — the
#      user never waits on a fetch when entering the screen.
#   2. When the cache is older than 12h it is refreshed *in the background*; the
#      (slightly stale) cached data is still returned right away. Only the very
#      first load, before any cache exists, builds synchronously — and startup
#      warms it so that case rarely happens.
# The per-campaign calls are fanned out across threads so a refresh is one
# round-trip's worth of latency, not 25 in series.
# Keyed by account slug: each Smartlead account has its own campaigns and its own
# cache entry, so switching accounts in the UI is instant once each is warm.
_CAMPAIGN_LIST_TTL = 12 * 3600
_campaign_list_cache: dict[str, dict] = {}
_campaign_refresh_lock = threading.Lock()
_campaign_refreshing: set[str] = set()


def _build_campaign_list(api_key: str) -> list[dict]:
    with db.db_session() as conn:
        analyzed = {
            row["campaign_id"]: row
            for row in conn.execute(
                "SELECT campaign_id, status, generated_at FROM campaign_reports"
            )
        }

    campaigns = [c for c in smartlead.list_campaigns(api_key=api_key) if c.get("id") is not None]

    def headline(cid: int) -> dict:
        try:
            stats = smartlead.get_campaign_analytics(cid, api_key=api_key)
            sent = _as_int(stats.get("sent_count"))
            bounced = _as_int(stats.get("bounce_count"))
            lead_stats = stats.get("campaign_lead_stats") or {}
            return {
                "sent": sent,
                "replies": _as_int(stats.get("reply_count")),
                "bounced": bounced,
                "leads": _as_int(lead_stats.get("total")),
                "interested": _as_int(lead_stats.get("interested")),
                "bounce_rate": (bounced / sent) if sent else 0.0,
            }
        except Exception as exc:  # one bad campaign shouldn't blank the list
            log.warning("campaign %s: analytics fetch failed: %s", cid, exc)
            return {"error": str(exc)[:200]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        stats_by_id = dict(
            zip(
                (c["id"] for c in campaigns),
                pool.map(headline, (c["id"] for c in campaigns)),
            )
        )

    out = []
    for campaign in campaigns:
        cid = campaign["id"]
        report = analyzed.get(cid)
        out.append(
            {
                "id": cid,
                "name": campaign.get("name") or f"Campaign {cid}",
                "status": campaign.get("status"),
                "created_at": campaign.get("created_at"),
                "report_status": report["status"] if report else None,
                "report_at": _fmt_time(report["generated_at"]) if report else None,
                **stats_by_id.get(cid, {}),
            }
        )
    return out


def _refresh_campaign_list_in_background(account) -> None:
    """Rebuild one account's cache off the request path. Lock-guarded per account
    so a burst of stale reads can't start several rebuilds of the same one."""
    with _campaign_refresh_lock:
        if account.slug in _campaign_refreshing:
            return
        _campaign_refreshing.add(account.slug)

    def _worker():
        try:
            data = _build_campaign_list(account.api_key)
            _campaign_list_cache[account.slug] = {"at": time.time(), "data": data}
        except Exception:
            log.exception("campaign list refresh failed for account %s", account.slug)
        finally:
            with _campaign_refresh_lock:
                _campaign_refreshing.discard(account.slug)

    threading.Thread(target=_worker, daemon=True).start()


def _warm_campaign_caches() -> None:
    """Warm every account's list at startup so the first open after a deploy is
    instant, for whichever account is selected."""
    for account in accounts.list_accounts():
        _refresh_campaign_list_in_background(account)


@app.get("/api/accounts")
def api_accounts(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse(
        {"accounts": [{"slug": a.slug, "label": a.label} for a in accounts.list_accounts()]}
    )


@app.get("/api/campaigns")
def api_campaigns(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    account = accounts.get_account(request.query_params.get("account"))
    if account is None:
        return JSONResponse({"error": "No Smartlead account configured."}, status_code=400)
    fresh = request.query_params.get("refresh") == "1"
    now = time.time()
    entry = _campaign_list_cache.get(account.slug)

    # Nothing cached yet (first ever load) — nothing to show, so build inline.
    if entry is None:
        data = _build_campaign_list(account.api_key)
        _campaign_list_cache[account.slug] = {"at": now, "data": data}
        return JSONResponse({"account": account.slug, "campaigns": data, "cached": False})

    # Stale or force-refresh: hand back what we have instantly and rebuild in
    # the background. The user never waits on the fetch when opening the tab.
    age = now - entry["at"]
    if fresh or age >= _CAMPAIGN_LIST_TTL:
        _refresh_campaign_list_in_background(account)
    return JSONResponse(
        {"account": account.slug, "campaigns": entry["data"], "cached": True, "age_seconds": int(age)}
    )


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@app.get("/api/campaigns/{campaign_id}")
def api_campaign_detail(request: Request, campaign_id: int):
    """Overview tab: the computed numbers only, straight from the local mirror.
    Never syncs — a first sync moves tens of MB and belongs behind the explicit
    Analyze click, not a tab switch."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        sync = db.get_campaign_sync(conn, campaign_id)
        if sync is None or not sync["sends_synced_at"]:
            return JSONResponse(
                {
                    "campaign_id": campaign_id,
                    "synced": False,
                    "message": "Not analyzed yet — click Analyze to pull this campaign's data.",
                }
            )
        outcomes = campaign_analytics.lead_outcomes(conn, campaign_id)
        slots = campaign_analytics.slot_metrics(conn, campaign_id, outcomes)
        texts = campaign_copy.slot_text_map(conn, campaign_id)
        emails = campaign_copy.variant_emails(conn, campaign_id)

        # Attach what each component actually says, and which number judges it.
        # A row that reads `Icebreaker2 · 4.3%` is unusable; the whole point of
        # this tab is to show the sentence being ranked.
        for role, entries in slots.items():
            stage = campaign_analytics.stage_of(role)
            metric = campaign_analytics.STAGE_METRIC[stage]
            for entry in entries:
                text = texts.get(entry["slot"]) or {}
                entry["text"] = text.get("display") or ""
                entry["personalized"] = bool(text.get("personalized"))
                entry["examples"] = text.get("examples") or []
                entry["translated"] = bool(text.get("translated"))
                entry["stage"] = stage
                entry["judged_on"] = metric["label"]
                entry["judged_rate"] = entry.get(metric["rate"], 0.0)
                entry["judged_verdict"] = entry.get(metric["verdict"])

        variants = campaign_analytics.variant_metrics(conn, campaign_id, outcomes)
        for variant in variants:
            email = emails.get(variant["seq_variant_id"]) or {}
            variant["email"] = {
                "subject": email.get("subject") or "",
                "body": email.get("body") or "",
                "slot_breakdown": email.get("slot_breakdown") or [],
                "translated": bool(email.get("any_translated")),
            }

        payload = {
            "campaign_id": campaign_id,
            "synced": True,
            "synced_at": _fmt_time(sync["sends_synced_at"]),
            "summary": campaign_analytics.campaign_summary(conn, campaign_id, outcomes),
            "variants": variants,
            "slots": slots,
            "recommendations": campaign_analytics.recommendations(
                conn, campaign_id, outcomes, texts
            ),
            "subjects": campaign_analytics.subject_metrics(conn, campaign_id, outcomes=outcomes),
            "reply_by_step": campaign_analytics.reply_step_metrics(conn, campaign_id, outcomes),
            "conversations": campaign_conversations.conversation_stats(conn, campaign_id),
            # Who hosts the recipients, and whether that is what held the
            # campaign back. Reads the domain cache only — the DNS lookups
            # happen during Analyze, never on a tab switch.
            "deliverability": campaign_deliverability.report(conn, campaign_id, outcomes),
        }
    return JSONResponse(payload)


@app.post("/api/campaigns/{campaign_id}/analyze")
async def api_campaign_analyze(request: Request, campaign_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    layers = tuple(body.get("layers") or ("variants", "conversations"))
    account = accounts.get_account(body.get("account"))
    if account is None:
        return JSONResponse({"error": "No Smartlead account configured."}, status_code=400)
    started = campaign_report.run_analysis_in_background(
        campaign_id,
        campaign_name=body.get("name") or "",
        layers=layers,
        full_sync=bool(body.get("full_sync")),
        api_key=account.api_key,
    )
    return JSONResponse({"started": started, "running": campaign_report.is_running(campaign_id)})


@app.get("/api/campaigns/{campaign_id}/report")
def api_campaign_report(request: Request, campaign_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        row = db.get_campaign_report(conn, campaign_id)
    if row is None:
        return JSONResponse({"status": None, "running": campaign_report.is_running(campaign_id)})
    return JSONResponse(
        {
            "status": row["status"],
            "stage": row["stage"],
            "running": campaign_report.is_running(campaign_id),
            "generated_at": _fmt_time(row["generated_at"]),
            "model": row["model"],
            "directives_md": row["directives_md"],
            "conversation_md": row["conversation_md"],
            "error": row["error"],
        }
    )


@app.get("/api/campaigns/{campaign_id}/responders")
def api_campaign_responders(request: Request, campaign_id: int):
    """The Conversations tab: the win/loss analysis first, the raw threads under
    it so a quoted claim can be checked against what the lead actually wrote."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        rows = db.list_campaign_conversations(conn, campaign_id)
        insights = campaign_conversations.conversation_insights(conn, campaign_id)
        stats = campaign_conversations.conversation_stats(conn, campaign_id)
        report = db.get_campaign_report(conn, campaign_id)
    conversation_md = report["conversation_md"] if report else None
    people = []
    for row in rows:
        try:
            extract = json.loads(row["extract_json"]) if row["extract_json"] else None
        except ValueError:
            extract = None
        people.append(
            {
                "lead_id": row["lead_id"],
                "email": row["lead_email"],
                "company": row["company"],
                "category": row["category"],
                "variant": row["variant_label"],
                "replied_after_step": row["first_reply_after_step"],
                "first_reply_at": _fmt_time(row["first_reply_at"]),
                "hours_to_reply": row["hours_to_reply"],
                "magnet": campaign_conversations.magnet_for(row["category"]),
                "turns": json.loads(row["thread_json"] or "[]"),
                "extract": extract,
                "positive": campaign_analytics.is_positive(row["category"]),
            }
        )
    return JSONResponse(
        {
            "responders": people,
            "insights": insights,
            "stats": stats,
            "conversation_md": conversation_md,
        }
    )


# ---- scan ----

@app.post("/api/scan/trigger")
def api_scan(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    started = scheduler.trigger_scan_in_background()
    return JSONResponse({"started": started, "scan_running": scheduler.is_scan_running()})


# ---- helpers ----

async def _json_body(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


def _get_draft_dict(draft_id: int) -> dict:
    with db.db_session() as conn:
        return dict(db.get_draft(conn, draft_id))
