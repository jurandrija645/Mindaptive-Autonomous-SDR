"""Whether a prospect actually opened the demo site we built for them.

Pushed in by WebsiteGenerator (cli/visits.mjs --push), which reads Vercel's
request data for each deployed demo site, throws away its own traffic, bots,
crawlers and hosting/VPN networks, and sends what is left: the human visits.

Two things shape this module:

Vercel groups requests into 4-hour blocks, so there is no exact visit time. A
"visit" here is one 4-hour block in which a human hit the site, which is why
the count is stored as a set of block timestamps rather than a number — pushes
overlap (each run asks for the last 30 days), and re-counting the same block
twice would inflate the number every day.

Free Vercel observability only keeps 1 day of history. The full history
therefore has to live here, not there: every push unions into what is already
stored, so a daily run builds a record that outlives Vercel's retention and
survives turning the paid retention off.

Keyed by company domain, like prospect_contacts and for the same reason: most
of these prospects have no leads_state row when the site is built.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db, prospect_contacts
from app.config import settings

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_visits (
    domain TEXT PRIMARY KEY,         -- company website domain, lowercase, no www
    demo_url TEXT,                   -- the site we built, whose visits these are
    vercel_project TEXT,
    first_at TEXT,                   -- earliest human visit ever recorded
    last_at TEXT,                    -- most recent
    visit_count INTEGER NOT NULL DEFAULT 0,   -- distinct 4-hour blocks with human traffic
    total_requests INTEGER NOT NULL DEFAULT 0,
    buckets TEXT NOT NULL,           -- JSON {"2026-09-10T12:00:00.000Z": 33} requests per block
    visitors TEXT NOT NULL,          -- JSON [{country, isp, device, requests, first, last}]
    source TEXT,
    updated_at TEXT NOT NULL
);
"""


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


def _visitor_key(v: dict) -> str:
    return "|".join(str(v.get(k) or "") for k in ("country", "isp", "device"))


def _merge_visitors(old: list, new: list) -> list:
    merged = {_visitor_key(v): dict(v) for v in old if isinstance(v, dict)}
    for v in new:
        if not isinstance(v, dict):
            continue
        key = _visitor_key(v)
        current = merged.get(key)
        if current is None:
            merged[key] = dict(v)
            continue
        # Pushes overlap, so the same visitor arrives again with the same
        # requests already counted: keep the larger figure, never the sum.
        current["requests"] = max(current.get("requests") or 0, v.get("requests") or 0)
        for field, pick in (("first", min), ("last", max)):
            values = [t for t in (current.get(field), v.get(field)) if t]
            if values:
                current[field] = pick(values)
    return sorted(merged.values(), key=lambda v: -(v.get("requests") or 0))


def save(conn, payload: dict) -> dict:
    domain = prospect_contacts.normalize_domain(payload.get("domain") or payload.get("website"))
    if not domain:
        raise ValueError("domain or website is required")
    # Checked for type before emptiness: [] and {} are both falsy, so an
    # `or {}` default would quietly accept a list where an object belongs.
    incoming_buckets = payload.get("buckets")
    if incoming_buckets is None:
        incoming_buckets = {}
    elif not isinstance(incoming_buckets, dict):
        raise ValueError("buckets must be an object of {timestamp: requests}")
    incoming_visitors = payload.get("visitors")
    if incoming_visitors is None:
        incoming_visitors = []
    elif not isinstance(incoming_visitors, list):
        raise ValueError("visitors must be a list")

    existing = conn.execute("SELECT * FROM site_visits WHERE domain = ?", (domain,)).fetchone()
    buckets = json.loads(existing["buckets"]) if existing else {}
    visitors = json.loads(existing["visitors"]) if existing else []
    for stamp, requests in incoming_buckets.items():
        try:
            count = int(requests)
        except (TypeError, ValueError):
            continue
        buckets[stamp] = max(buckets.get(stamp, 0), count)
    visitors = _merge_visitors(visitors, incoming_visitors)

    stamps = sorted(buckets)

    def keep(field):
        return payload.get(field) or (existing[field] if existing else None)

    row = {
        "domain": domain,
        "demo_url": keep("demo_url"),
        "vercel_project": keep("vercel_project"),
        "first_at": stamps[0] if stamps else None,
        "last_at": stamps[-1] if stamps else None,
        "visit_count": len(stamps),
        "total_requests": sum(buckets.values()),
        "buckets": json.dumps(buckets),
        "visitors": json.dumps(visitors),
        "source": keep("source"),
        "updated_at": db.now_iso(),
    }
    cols = ",".join(row)
    conn.execute(
        f"INSERT OR REPLACE INTO site_visits ({cols}) VALUES ({','.join('?' for _ in row)})",
        list(row.values()),
    )
    return row


def for_lead(conn, lead, contacts_row=None):
    """The site_visits row for this lead, or None.

    Matched the same way as prospect_contacts, including the indirect route: a
    gmail-run business has no useful email domain, but its saved contacts row
    knows which company domain it belongs to.
    """
    if lead is None:
        return None
    domains = []
    if contacts_row is not None:
        domains.append(contacts_row["domain"])
    website = prospect_contacts.normalize_domain(lead["website"] if "website" in lead.keys() else "")
    if website:
        domains.append(website)
    email_domain = prospect_contacts.normalize_domain(lead["email"] or "")
    if email_domain and email_domain not in db._FREEMAIL_DOMAINS:
        domains.append(email_domain)
    for domain in domains:
        row = conn.execute("SELECT * FROM site_visits WHERE domain = ?", (domain,)).fetchone()
        if row:
            return row
    return None


def payload(row) -> dict | None:
    """The "did they look at it" line on the lead card."""
    if row is None:
        return None
    try:
        visitors = json.loads(row["visitors"] or "[]")
    except ValueError:
        visitors = []
    return {
        "domain": row["domain"],
        "demo_url": row["demo_url"],
        "first_at": row["first_at"],
        "last_at": row["last_at"],
        "visit_count": row["visit_count"],
        "total_requests": row["total_requests"],
        "visitors": visitors,
        "updated_at": row["updated_at"],
    }


@router.post("/api/site-visits")
async def api_save_site_visits(request: Request):
    """Called by WebsiteGenerator's cli/visits.mjs --push, with the same token
    as the contacts push: a script on Andrew's machine, not a browser."""
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
            matched = prospect_contacts.leads_for(
                conn,
                conn.execute("SELECT * FROM prospect_contacts WHERE domain = ?", (row["domain"],)).fetchone()
                or {"domain": row["domain"], "emails_index": ""},
            )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(
        {
            "saved": True,
            "domain": row["domain"],
            "visit_count": row["visit_count"],
            "first_at": row["first_at"],
            "last_at": row["last_at"],
            "matched_leads": matched,
        }
    )
