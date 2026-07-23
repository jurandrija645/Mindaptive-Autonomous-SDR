import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import accounts, campaign_analytics, campaign_conversations, campaign_report
from app import candidates as candidates_module
from app import db, drafter, pipeline, scheduler, smartlead, translator, uploads, webhook
from app.auth import install_session_middleware, is_authed, require_auth
from app.config import settings
from app.detector import (
    NormalizedMessage,
    last_sender_email,
    next_reply_cc,
    next_reply_to,
)
from app.email_clean import clean_email_html, to_plain_text
from app.thread_utils import next_morning_send_utc, text_to_html

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


def _load_thread_raw(campaign_id: int, lead_id: int) -> list[dict]:
    """Thread as a list of NormalizedMessage-shaped dicts — from the open
    draft's snapshot if one exists, otherwise a live Smartlead fetch.

    Both branches carry the full field set (the snapshot is dumped from
    `m.__dict__`), so _thread_as_messages can rebuild real NormalizedMessages
    from either one and the recipients preview needs no extra API call."""
    with db.db_session() as conn:
        draft = db.get_open_draft(conn, lead_id, campaign_id)
    if draft and draft["thread_snapshot"]:
        return json.loads(draft["thread_snapshot"])
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
    rows = conn.execute(
        "SELECT DISTINCT lead_id, campaign_id FROM drafts WHERE status IN ('pending', 'scheduled')"
    ).fetchall()
    return {(r["lead_id"], r["campaign_id"]) for r in rows}


def _row_payload(l: dict, open_set: set) -> dict:
    return {
        "campaign_id": l["campaign_id"],
        "lead_id": l["lead_id"],
        "name": l["name"] or l["email"] or "Lead",
        "company": l["company"] or "",
        "email": l["email"] or "",
        "category": l["category"] or "waiting",
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
    return {
        "lead": {
            "name": lead_name,
            "company": (lead["company"] if lead else "") or "",
            "email": (lead["email"] if lead else "") or "",
            "language": ((lead["language"] if lead else "") or "").upper(),
            "language_name": translator.language_name(lead["language"]) if (lead and lead["language"]) else None,
            "category": (lead["category"] if lead else "waiting") or "waiting",
            "archive_reason": lead["archive_reason"] if lead else None,
            "archived_at": _fmt_time(lead["archived_at"]) if lead and lead["archived_at"] else None,
            "snooze_until": lead["snooze_until"] if lead else None,
            "research_summary": (lead["research_summary"] if lead else None) or None,
            "researched_at": _fmt_time(lead["researched_at"]) if lead and lead["researched_at"] else None,
            "email_display_name": (lead["email_display_name"] if lead else None) or None,
        },
        "thread": _thread_payload(raw, lead_name),
        "draft": draft_payload,
        "generating": candidates_module.is_generating(campaign_id, lead_id),
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
    if model not in drafter.ALLOWED_MODELS:
        model = None  # falls back to settings.anthropic_model
    use_web_search = body.get("use_web_search")
    if not isinstance(use_web_search, bool):
        use_web_search = None  # falls back to the prior-research auto-decide

    # Regenerate: discard any existing open draft first, then draft fresh.
    with db.db_session() as conn:
        existing = db.get_open_draft(conn, lead_id, campaign_id)
        if existing is not None:
            db.update_draft(conn, existing["id"], status="skipped")

    # generate_for_lead calls Claude synchronously (web search/fetch tools) and
    # can take minutes — long enough to hit Cloudflare's ~100s tunnel timeout
    # (confirmed via a real 524 in production) if held open as one request.
    # Kick it off in the background and let the client poll GET
    # /api/leads/{cid}/{lid} (which reports `generating`) instead.
    started = candidates_module.generate_for_lead_in_background(
        campaign_id, lead_id, steering_note, model=model, use_web_search=use_web_search
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
    draft_id = candidates_module.quick_followup(campaign_id, lead_id, text)
    if not draft_id:
        return JSONResponse({"error": "Could not create draft for this lead."}, status_code=404)
    return JSONResponse(_lead_detail_payload(campaign_id, lead_id))


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
    """Manual correction for when Smartlead's imported first_name is wrong —
    locks the name (name_locked=1) so the next scan (which otherwise
    overwrites leads_state.name from Smartlead's own first_name every run,
    see scheduler._process_lead) doesn't revert it."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required."}, status_code=400)
    with db.db_session() as conn:
        db.upsert_lead_state(conn, lead_id, campaign_id, name=name, name_locked=1)
    return JSONResponse({"ok": True})


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
    plain = to_plain_text(body.get("original_html", ""))
    if not plain.strip():
        return JSONResponse({"english_html": ""})
    with db.db_session() as conn:
        english = translator.translate_segments_cached(conn, [plain])[0]
    return JSONResponse({"english_html": clean_email_html(english)})


@app.post("/api/drafts/{draft_id}/localize")
async def api_draft_localize(request: Request, draft_id: int):
    """Applies an English edit back onto the real (native-language) draft that
    will actually be sent — runs on Sonnet, since this becomes the outgoing
    message and quality matters here, unlike the cheap /translate above."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    english_text = to_plain_text(body.get("english_html", ""))
    if not english_text.strip():
        return JSONResponse({"error": "Nothing to apply."}, status_code=400)
    model = body.get("model") or None
    if model not in drafter.ALLOWED_MODELS:
        model = None  # falls back to settings.anthropic_model

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
    reason. Picking 'Interested' instead restores it to the active inbox."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _json_body(request)
    category_name = (body.get("category_name") or "").strip()
    if not category_name:
        return JSONResponse({"error": "category_name is required."}, status_code=400)

    restoring = category_name == "Interested"
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
                conn, lead_id, campaign_id, status="active", archived_at=None, archive_reason=None
            )
        else:
            db.upsert_lead_state(
                conn, lead_id, campaign_id, archived_at=db.now_iso(), archive_reason=category_name
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
        db.update_draft(conn, draft_id, **updates)

    scheduler._send_due_draft(dict(_get_draft_dict(draft_id)))

    # Reflect "we responded" in the inbox immediately (next scan will confirm).
    with db.db_session() as conn:
        db.upsert_lead_state(
            conn,
            draft["lead_id"],
            draft["campaign_id"],
            category="waiting",
            last_message_kind="sent",
            last_message_at=db.now_iso(),
        )
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
        for entries in slots.values():
            for entry in entries:
                entry["examples"] = campaign_analytics.slot_examples(
                    conn, campaign_id, entry["slot"], limit=3
                )
        payload = {
            "campaign_id": campaign_id,
            "synced": True,
            "synced_at": _fmt_time(sync["sends_synced_at"]),
            "summary": campaign_analytics.campaign_summary(conn, campaign_id, outcomes),
            "variants": campaign_analytics.variant_metrics(conn, campaign_id, outcomes),
            "slots": slots,
            "subjects": campaign_analytics.subject_metrics(conn, campaign_id, outcomes=outcomes),
            "reply_by_step": campaign_analytics.reply_step_metrics(conn, campaign_id, outcomes),
            "conversations": campaign_conversations.conversation_stats(conn, campaign_id),
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
            "report_md": row["report_md"],
            "conversation_md": row["conversation_md"],
            "error": row["error"],
        }
    )


@app.get("/api/campaigns/{campaign_id}/responders")
def api_campaign_responders(request: Request, campaign_id: int):
    """The raw conversations behind the Layer-2 report, so Andrew can read what
    leads actually wrote instead of only the AI's summary of it."""
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        rows = db.list_campaign_conversations(conn, campaign_id)
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
            }
        )
    return JSONResponse({"responders": people})


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
