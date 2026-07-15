import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import candidates as candidates_module
from app import db, pipeline, scheduler, webhook
from app.auth import install_session_middleware, is_authed, require_auth
from app.config import settings

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Mindaptive Responder")
install_session_middleware(app)
app.include_router(webhook.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []


@app.on_event("startup")
def on_startup():
    db.init_db()
    scheduler.start_scheduler()


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
def dashboard(request: Request, tab: str = "pending"):
    redirect = require_auth(request)
    if redirect:
        return redirect

    due_candidates: list[dict] = []
    generating_candidates: list[dict] = []

    with db.db_session() as conn:
        if tab == "inbox":
            rows = db.list_drafts(conn, status="pending", kind="reply")
        elif tab == "scheduled":
            rows = db.list_drafts(conn, status="scheduled")
        elif tab == "sent":
            rows = db.list_drafts(conn, status="sent")
        else:
            tab = "pending"
            rows = db.list_drafts(conn, status="pending", kind="followup")
            due_candidates = [dict(r) for r in db.list_candidates(conn, status="open", kind="followup")]
            generating_candidates = [dict(r) for r in db.list_candidates(conn, status="generating", kind="followup")]
        drafts = [dict(r) for r in rows]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "tab": tab,
            "drafts": drafts,
            "due_candidates": due_candidates,
            "generating_candidates": generating_candidates,
            "scan_running": scheduler.is_scan_running(),
            "dry_run": settings.dry_run,
            "auto_send": settings.auto_send_followups,
        },
    )


@app.post("/scan/trigger")
def trigger_scan(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect

    scheduler.trigger_scan_in_background()
    return RedirectResponse(url="/dashboard?tab=pending", status_code=303)


@app.post("/candidates/{candidate_id}/generate")
def generate_candidate(request: Request, candidate_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect

    candidates_module.generate_one(candidate_id)
    return RedirectResponse(url="/dashboard?tab=pending", status_code=303)


@app.post("/candidates/bulk-generate")
async def bulk_generate_candidates(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect

    form = await request.form()
    candidate_ids = [int(v) for v in form.getlist("candidate_ids")]
    if candidate_ids:
        candidates_module.generate_many_in_background(candidate_ids)
    return RedirectResponse(url="/dashboard?tab=pending", status_code=303)


@app.post("/candidates/{candidate_id}/dismiss")
def dismiss_candidate(request: Request, candidate_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect

    with db.db_session() as conn:
        db.update_candidate(conn, candidate_id, status="dismissed")
    return RedirectResponse(url="/dashboard?tab=pending", status_code=303)


@app.post("/drafts/{draft_id}/send")
def send_draft(request: Request, draft_id: int, body_html: str = Form(...)):
    redirect = require_auth(request)
    if redirect:
        return redirect

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None or draft["status"] not in ("pending", "scheduled"):
            return RedirectResponse(url="/dashboard", status_code=303)
        db.update_draft(conn, draft_id, body_html=body_html)

    scheduler._send_due_draft(dict(db_get_draft_dict(draft_id)))
    return RedirectResponse(url=f"/dashboard?tab={_tab_for(draft)}", status_code=303)


@app.post("/drafts/{draft_id}/schedule")
def schedule_draft(
    request: Request,
    draft_id: int,
    body_html: str = Form(...),
    scheduled_at: str = Form(...),
):
    redirect = require_auth(request)
    if redirect:
        return redirect

    try:
        dt = datetime.fromisoformat(scheduled_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc) + timedelta(hours=1)

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return RedirectResponse(url="/dashboard", status_code=303)
        db.update_draft(
            conn,
            draft_id,
            body_html=body_html,
            status="scheduled",
            scheduled_at=dt.isoformat(),
        )
        tab = _tab_for(draft)

    return RedirectResponse(url=f"/dashboard?tab={tab}", status_code=303)


@app.post("/drafts/{draft_id}/regenerate")
def regenerate_draft(request: Request, draft_id: int, steering_note: str = Form("")):
    redirect = require_auth(request)
    if redirect:
        return redirect

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return RedirectResponse(url="/dashboard", status_code=303)
        lead_row = db.get_lead_state(conn, draft["lead_id"], draft["campaign_id"])
        lead = {
            "id": draft["lead_id"],
            "campaign_id": draft["campaign_id"],
            "email": draft["lead_email"],
            "first_name": draft["lead_name"],
            "company_name": draft["lead_company"],
            "website": lead_row["website"] if lead_row else "",
            "custom_fields": None,
        }
        tab = _tab_for(draft)
        db.update_draft(conn, draft_id, status="skipped")

    thread = pipeline.fetch_normalized_thread(draft["campaign_id"], draft["lead_id"])
    with db.db_session() as conn:
        pipeline.create_draft(conn, lead, "", draft["kind"], thread, steering_note or None)

    return RedirectResponse(url=f"/dashboard?tab={tab}", status_code=303)


@app.post("/drafts/{draft_id}/skip")
def skip_draft(request: Request, draft_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return RedirectResponse(url="/dashboard", status_code=303)
        db.update_draft(conn, draft_id, status="skipped")
        tab = _tab_for(draft)

    return RedirectResponse(url=f"/dashboard?tab={tab}", status_code=303)


@app.post("/drafts/{draft_id}/stop")
def stop_lead(request: Request, draft_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect

    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        if draft is None:
            return RedirectResponse(url="/dashboard", status_code=303)
        db.update_draft(conn, draft_id, status="skipped")
        db.upsert_lead_state(conn, draft["lead_id"], draft["campaign_id"], status="stopped")
        tab = _tab_for(draft)

    return RedirectResponse(url=f"/dashboard?tab={tab}", status_code=303)


def _tab_for(draft) -> str:
    return "inbox" if draft["kind"] == "reply" else "pending"


def db_get_draft_dict(draft_id: int) -> dict:
    with db.db_session() as conn:
        return dict(db.get_draft(conn, draft_id))
