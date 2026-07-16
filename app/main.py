import json
import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import candidates as candidates_module
from app import db, drafter, pipeline, scheduler, smartlead, translator, webhook
from app.auth import install_session_middleware, is_authed, require_auth
from app.config import settings
from app.email_clean import clean_email_html, to_plain_text
from app.thread_utils import text_to_html

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
    """Thread as a list of {kind, timestamp, body, from_email} — from the open
    draft's snapshot if one exists, otherwise a live Smartlead fetch."""
    with db.db_session() as conn:
        draft = db.get_open_draft(conn, lead_id, campaign_id)
    if draft and draft["thread_snapshot"]:
        return json.loads(draft["thread_snapshot"])
    thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
    return [
        {"kind": m.kind, "timestamp": m.timestamp.isoformat(), "body": m.body, "from_email": m.from_email}
        for m in thread
    ]


def _thread_payload(raw: list[dict], lead_name: str) -> list[dict]:
    out = []
    for m in raw:
        is_us = m.get("kind") == "sent"
        out.append(
            {
                "who": "us" if is_us else "lead",
                "name": "You" if is_us else (lead_name or "Lead"),
                "time": _fmt_time(m.get("timestamp")),
                "html": clean_email_html(m.get("body")),
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
    }


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


def _lead_detail_payload(campaign_id: int, lead_id: int) -> dict:
    with db.db_session() as conn:
        lead = db.get_lead_state(conn, lead_id, campaign_id)
        draft = db.get_open_draft(conn, lead_id, campaign_id)
    lead_name = (lead["name"] if lead else None) or "Lead"
    raw = _load_thread_raw(campaign_id, lead_id)
    return {
        "lead": {
            "name": lead_name,
            "company": (lead["company"] if lead else "") or "",
            "email": (lead["email"] if lead else "") or "",
            "language": ((lead["language"] if lead else "") or "").upper(),
            "category": (lead["category"] if lead else "waiting") or "waiting",
            "archive_reason": lead["archive_reason"] if lead else None,
            "archived_at": _fmt_time(lead["archived_at"]) if lead and lead["archived_at"] else None,
            "snooze_until": lead["snooze_until"] if lead else None,
            "research_summary": (lead["research_summary"] if lead else None) or None,
            "researched_at": _fmt_time(lead["researched_at"]) if lead and lead["researched_at"] else None,
        },
        "thread": _thread_payload(raw, lead_name),
        "draft": _draft_payload(draft),
        "generating": candidates_module.is_generating(campaign_id, lead_id),
    }


@app.get("/api/leads/{campaign_id}/{lead_id}")
def api_lead(request: Request, campaign_id: int, lead_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    return JSONResponse(_lead_detail_payload(campaign_id, lead_id))


@app.post("/api/leads/{campaign_id}/{lead_id}/translate")
def api_translate(request: Request, campaign_id: int, lead_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    raw = _load_thread_raw(campaign_id, lead_id)
    plains = [to_plain_text(m.get("body")) for m in raw]
    english = translator.translate_segments(plains)
    segments = [clean_email_html(t) for t in english]
    return JSONResponse({"segments": segments})


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
    english = translator.translate_text(plain)
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

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return JSONResponse({"error": "Draft not found."}, status_code=404)
        lead = db.get_lead_state(conn, draft["lead_id"], draft["campaign_id"])

    target_lang = (lead["language"] if lead else None) or translator.detect_language(
        to_plain_text(draft["body_html"])
    )
    localized = translator.localize_draft(english_text, target_lang)
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
        db.update_draft(conn, draft_id, body_html=body.get("body_html", draft["body_html"]))

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
        dt = datetime.fromisoformat(body.get("scheduled_at", ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc) + timedelta(hours=1)

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return JSONResponse({"error": "Draft not found."}, status_code=404)
        db.update_draft(
            conn,
            draft_id,
            body_html=body.get("body_html", draft["body_html"]),
            status="scheduled",
            scheduled_at=dt.isoformat(),
        )
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
