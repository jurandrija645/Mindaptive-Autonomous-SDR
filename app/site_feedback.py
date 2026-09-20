"""What a prospect said in the popup on the demo site we built for them.

The popup (WebsiteGenerator/templates/shared/site-feedback) asks "Do you like
the new site?" with three answers:

  like    "I like it, send the pricing"  -> hot: reply with pricing within 5 minutes
  change  "I'd change something"         -> detail = the one thing they'd change
  no      "Not for us"                   -> detail = the reason they picked

The site's own server function posts here (the token never reaches the browser).
Rows are keyed by the demo site's host, because that is all the browser knows;
prospect_contacts.demo_url is what ties the host back to a company and its lead.
"""
import json
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db, prospect_contacts
from app.config import settings

router = APIRouter()

ANSWERS = {"like", "change", "no"}
NO_REASONS = {"Too expensive", "Prefer current website", "Timing", "Not different enough", "Other"}
# A "like" answer is a buying signal that goes cold fast.
REPLY_WITHIN_MINUTES = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host TEXT NOT NULL,              -- demo site host, e.g. acme-hvac.vercel.app
    domain TEXT,                     -- prospect's own domain, when the host is known
    answer TEXT NOT NULL,            -- like | change | no
    detail TEXT,                     -- what they'd change, or why not
    page TEXT,                       -- path they were on
    trigger TEXT,                    -- time | scroll | navigation
    created_at TEXT NOT NULL,
    handled_at TEXT                  -- set when Andrew has replied
);
CREATE INDEX IF NOT EXISTS idx_site_feedback_host ON site_feedback (host, created_at);
"""


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


def _host(value: str | None) -> str:
    value = (value or "").strip().lower()
    return (urlparse(value if "//" in value else f"//{value}").hostname or "").removeprefix("www.")


def _clip(value, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None


def save(conn, payload: dict) -> dict:
    host = _host(payload.get("host"))
    if not host:
        raise ValueError("host is required")
    answer = payload.get("answer")
    if answer not in ANSWERS:
        raise ValueError("answer must be like, change or no")
    detail = _clip(payload.get("detail"), 2000)
    if answer == "no" and detail not in NO_REASONS:
        detail = f"Other: {detail}" if detail else "Other"
    if answer == "like":
        detail = None
    demo = conn.execute(
        "SELECT domain FROM prospect_contacts WHERE demo_url LIKE ? OR demo_url LIKE ? LIMIT 1",
        (f"%//{host}%", f"%//www.{host}%"),
    ).fetchone()
    row = {
        "host": host,
        "domain": demo["domain"] if demo else None,
        "answer": answer,
        "detail": detail,
        "page": _clip(payload.get("page"), 300),
        "trigger": _clip(payload.get("trigger"), 20),
        "created_at": db.now_iso(),
    }
    cur = conn.execute(
        f"INSERT INTO site_feedback ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
        list(row.values()),
    )
    row["id"] = cur.lastrowid
    return row


def _domains_for(lead, contacts_row) -> list[str]:
    domains = [contacts_row["domain"]] if contacts_row is not None else []
    if lead is not None:
        site = prospect_contacts.normalize_domain(lead["website"] if "website" in lead.keys() else "")
        if site:
            domains.append(site)
        email_domain = prospect_contacts.normalize_domain(lead["email"] or "")
        if email_domain and email_domain not in db._FREEMAIL_DOMAINS:
            domains.append(email_domain)
    return domains


def for_lead(conn, lead, contacts_row) -> list:
    domains = _domains_for(lead, contacts_row)
    if not domains:
        return []
    return conn.execute(
        f"SELECT * FROM site_feedback WHERE domain IN ({','.join('?' for _ in domains)}) "
        "ORDER BY created_at DESC LIMIT 20",
        domains,
    ).fetchall()


def payload(rows) -> list[dict]:
    return [
        {
            "id": r["id"],
            "answer": r["answer"],
            "detail": r["detail"],
            "page": r["page"],
            "created_at": r["created_at"],
            "handled_at": r["handled_at"],
            "reply_within_minutes": REPLY_WITHIN_MINUTES if r["answer"] == "like" else None,
        }
        for r in rows
    ]


@router.post("/api/site-feedback")
async def api_save_site_feedback(request: Request):
    """Called by a demo site's server function, with the shared ingest token."""
    if not settings.contact_ingest_token:
        return JSONResponse({"error": "CONTACT_INGEST_TOKEN is not set on this server"}, status_code=503)
    if not prospect_contacts.authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    try:
        with db.db_session() as conn:
            row = save(conn, body)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"saved": True, "id": row["id"], "matched_domain": row["domain"]})
