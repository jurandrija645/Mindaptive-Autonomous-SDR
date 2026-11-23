"""What a prospect did on their personal offer page (www.mindaptive.ai/offer/<slug>).

The page (LeadsFinder/gtm/funnel/site) sends small events with sendBeacon to its own Vercel
function (api/offer.js), which forwards them here with the shared ingest token, so the token never
reaches the browser. LeadsFinder/scripts/analysis/offer_funnel.py reads them back and builds the
funnel per channel for the morning report: opened, reached the plans, clicked a plan, started the
form, sent it.

Each event carries the offer slug, a random id made fresh on every page load (so one visit can be
told from the next; no cookie, nothing stored on the device), the event name and a few fields
(tier, FAQ id, seconds on the page, how far down they scrolled). No IP, no email, no device id.

The table is created on first use, so this module needs no change to db.init_db().
"""
import json
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db, prospect_contacts
from app.config import settings

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS offer_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,              -- offer page slug, e.g. cityflow
    event TEXT NOT NULL,             -- page_view, plans_view, tier_click, form_start, form_submit, ...
    visit TEXT,                      -- random per page load; groups one visit's events
    device TEXT,                     -- mobile / desktop, from the user agent class only
    ts TEXT NOT NULL,                -- when the browser says it happened (ISO, UTC)
    received_at TEXT NOT NULL,
    data TEXT NOT NULL               -- JSON object, small
);
CREATE INDEX IF NOT EXISTS offer_events_slug ON offer_events (slug);
CREATE INDEX IF NOT EXISTS offer_events_received ON offer_events (received_at);
"""

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
EVENT_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
VISIT_RE = re.compile(r"^[A-Za-z0-9]{4,40}$")
MAX_DATA = 1000


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


def _iso(value) -> str:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return db.now_iso()


def clean(item: dict) -> dict:
    slug = str(item.get("slug") or "").lower()
    event = str(item.get("event") or "")
    if not SLUG_RE.match(slug):
        raise ValueError("bad slug")
    if not EVENT_RE.match(event):
        raise ValueError("bad event")
    visit = str(item.get("visit") or "")
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    data_json = json.dumps(data, ensure_ascii=False)[:MAX_DATA]
    try:
        json.loads(data_json)
    except ValueError:
        data_json = "{}"
    device = str(item.get("device") or "")
    return {
        "slug": slug,
        "event": event,
        "visit": visit if VISIT_RE.match(visit) else None,
        "device": device if device in ("mobile", "desktop") else None,
        "ts": _iso(item.get("ts")),
        "received_at": db.now_iso(),
        "data": data_json,
    }


@router.post("/api/offer-events")
async def api_save_offer_events(request: Request):
    """Called by the offer page's Vercel function. Body: one event, or {"events": [...]}."""
    if not settings.contact_ingest_token:
        return JSONResponse({"error": "CONTACT_INGEST_TOKEN is not set on this server"}, status_code=503)
    if not prospect_contacts.authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    items = body.get("events") if isinstance(body, dict) and "events" in body else [body]
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        return JSONResponse({"error": "events must be a list of 1 to 50"}, status_code=400)
    rows, errors = [], 0
    for item in items:
        try:
            rows.append(clean(item if isinstance(item, dict) else {}))
        except ValueError:
            errors += 1
    if rows:
        with db.db_session() as conn:
            ensure_table(conn)
            conn.executemany(
                "INSERT INTO offer_events (slug, event, visit, device, ts, received_at, data) "
                "VALUES (:slug, :event, :visit, :device, :ts, :received_at, :data)",
                rows,
            )
    return JSONResponse({"saved": len(rows), "rejected": errors}, status_code=200 if rows else 400)


@router.get("/api/offer-events")
async def api_list_offer_events(request: Request, since: str = "", slug: str = "", limit: int = 20000):
    """Read back for offer_funnel.py (same token). since = ISO date or time, on received_at."""
    if not settings.contact_ingest_token:
        return JSONResponse({"error": "CONTACT_INGEST_TOKEN is not set on this server"}, status_code=503)
    if not prospect_contacts.authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    where, args = [], []
    if since:
        where.append("received_at >= ?")
        args.append(since)
    if slug:
        where.append("slug = ?")
        args.append(slug.lower())
    sql = "SELECT slug, event, visit, device, ts, received_at, data FROM offer_events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id LIMIT ?"
    args.append(max(1, min(int(limit), 50000)))
    with db.db_session() as conn:
        ensure_table(conn)
        out = []
        for r in conn.execute(sql, args).fetchall():
            d = dict(r)
            try:
                d["data"] = json.loads(d["data"] or "{}")
            except ValueError:
                d["data"] = {}
            out.append(d)
    return JSONResponse({"events": out, "count": len(out)})
