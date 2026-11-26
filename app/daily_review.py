"""The morning review page (Pregled): every cold-email conversation after a positive reply.

Owner, 26 Nov 2026: 10-17 positive replies a day and no meeting booked, so Mia reviews every
conversation each morning and looks for the mistakes made after the first reply. The report is
built on Andrija's machine by LeadsFinder/scripts/analysis/daily_review.py (it needs the follow-up
registry that lives there) and pushed here with the shared ingest token. This module only stores
it, one JSON per day, and serves it to the dashboard (static/review.js).

The table is created on first use, so db.init_db() needs no change.
"""
import json
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db, prospect_contacts
from app.auth import is_authed
from app.config import settings

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_reviews (
    day TEXT PRIMARY KEY,            -- the day the report is about (Zagreb), YYYY-MM-DD
    generated_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    summary TEXT NOT NULL,           -- JSON, small: for the day list
    report TEXT NOT NULL             -- JSON, the whole report
);
"""

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_BYTES = 15_000_000


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


@router.post("/api/daily-review")
async def api_save_daily_review(request: Request):
    """Called by LeadsFinder's daily_review.py. Body: {"day": "YYYY-MM-DD", "report": {...}}."""
    if not settings.contact_ingest_token:
        return JSONResponse({"error": "CONTACT_INGEST_TOKEN is not set on this server"}, status_code=503)
    if not prospect_contacts.authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        return JSONResponse({"error": "report too large"}, status_code=413)
    try:
        body = json.loads(raw)
    except ValueError:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    day = str(body.get("day") or "")
    report = body.get("report")
    if not DAY_RE.match(day) or not isinstance(report, dict):
        return JSONResponse({"error": "day (YYYY-MM-DD) and report (object) are required"}, status_code=400)
    with db.db_session() as conn:
        ensure_table(conn)
        conn.execute(
            "INSERT INTO daily_reviews (day, generated_at, received_at, summary, report) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET generated_at=excluded.generated_at, received_at=excluded.received_at, "
            "summary=excluded.summary, report=excluded.report",
            (day, str(report.get("generated_at") or ""), db.now_iso(),
             json.dumps(report.get("summary") or {}, ensure_ascii=False), json.dumps(report, ensure_ascii=False)),
        )
    return JSONResponse({"saved": day})


def _allowed(request: Request) -> bool:
    return is_authed(request) or prospect_contacts.authorized(request)


@router.get("/api/daily-review/days")
def api_review_days(request: Request):
    if not _allowed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    with db.db_session() as conn:
        ensure_table(conn)
        rows = conn.execute(
            "SELECT day, generated_at, summary FROM daily_reviews ORDER BY day DESC LIMIT 60").fetchall()
    out = []
    for r in rows:
        try:
            summary = json.loads(r["summary"] or "{}")
        except ValueError:
            summary = {}
        out.append({"day": r["day"], "generated_at": r["generated_at"], "summary": summary})
    return JSONResponse({"days": out})


@router.get("/api/daily-review")
def api_review(request: Request, day: str = ""):
    if not _allowed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    with db.db_session() as conn:
        ensure_table(conn)
        if day and DAY_RE.match(day):
            row = conn.execute("SELECT report FROM daily_reviews WHERE day = ?", (day,)).fetchone()
        else:
            row = conn.execute("SELECT report FROM daily_reviews ORDER BY day DESC LIMIT 1").fetchone()
    if not row:
        return JSONResponse({"error": "no report for that day"}, status_code=404)
    return JSONResponse(json.loads(row["report"]))
