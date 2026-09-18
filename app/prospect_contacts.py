"""Contact details scraped from a prospect's own website by WebsiteGenerator
(cli/contacts.mjs), so Andrew can chase a lead on WhatsApp, Facebook,
Instagram, LinkedIn and phone once the site he built for them is live and the
email about it went unread.

Stored per company domain, not per lead: most website prospects have not
replied yet, so they have no leads_state row when the site is built. The
contacts wait under the domain and attach to a lead's card the moment that
company shows up (matched by website domain, company email domain, or any
exact email address the site listed, which covers gmail-run businesses).
WhatsApp is the channel Andrew cares about most, so the icon row prefers a
confirmed WhatsApp link over a merely likely mobile number.
"""
import json
import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db
from app.config import settings

router = APIRouter()

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospect_contacts (
    domain TEXT PRIMARY KEY,         -- company website domain, lowercase, no www
    company TEXT,
    website TEXT,
    demo_url TEXT,                   -- the live site we built for them
    lead_email TEXT,                 -- the address the site was pitched to, when known
    emails_index TEXT,               -- " a@x.com b@y.com " for exact-address lookups
    channels TEXT NOT NULL,          -- JSON {whatsapp: [{value, confirmed, reason, sources}], phones: [...], ...}
    source TEXT,
    updated_at TEXT NOT NULL
);
"""

# Keys the dashboard's one-click icon row understands (app.js CHANNEL_DEFS),
# mapped from the list names WebsiteGenerator sends.
_ICON_KEYS = {
    "whatsapp": "whatsapp",
    "linkedin": "linkedin",
    "facebook": "facebook",
    "instagram": "instagram",
    "emails": "email",
    "phones": "phone",
}


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


def normalize_domain(value: str | None) -> str:
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "@" in value and "/" not in value:
        value = value.rpartition("@")[2]
    host = urlparse(value if "//" in value else f"//{value}").hostname or ""
    return host.removeprefix("www.")


def _merge_items(old: list, new: list) -> list:
    """Union by value; a later push never loses a hand-added or confirmed entry."""
    merged = {item["value"]: dict(item) for item in old if isinstance(item, dict) and item.get("value")}
    for item in new:
        if not isinstance(item, dict) or not item.get("value"):
            continue
        current = merged.get(item["value"])
        if current is None:
            merged[item["value"]] = dict(item)
            continue
        current["sources"] = sorted(set(current.get("sources") or []) | set(item.get("sources") or []))
        if item.get("confirmed"):
            current["confirmed"] = True
            current["reason"] = item.get("reason") or current.get("reason")
    items = list(merged.values())
    items.sort(key=lambda i: (not i.get("confirmed", False), -len(i.get("sources") or [])))
    return items


def save(conn, payload: dict) -> dict:
    domain = normalize_domain(payload.get("domain") or payload.get("website"))
    if not domain:
        raise ValueError("domain or website is required")
    incoming = payload.get("channels") or {}
    if not isinstance(incoming, dict):
        raise ValueError("channels must be an object of lists")
    existing = conn.execute("SELECT * FROM prospect_contacts WHERE domain = ?", (domain,)).fetchone()
    channels = json.loads(existing["channels"]) if existing else {}
    for key, items in incoming.items():
        if isinstance(items, list):
            channels[key] = _merge_items(channels.get(key) or [], items)
    lead_email = (payload.get("lead_email") or (existing["lead_email"] if existing else "") or "").strip().lower()
    emails = {i["value"].lower() for i in channels.get("emails", [])}
    if lead_email:
        emails.add(lead_email)

    def keep(field):
        return payload.get(field) or (existing[field] if existing else None)

    row = {
        "domain": domain,
        "company": keep("company"),
        "website": keep("website"),
        "demo_url": keep("demo_url"),
        "lead_email": lead_email or None,
        "emails_index": " " + " ".join(sorted(emails)) + " ",
        "channels": json.dumps(channels),
        "source": keep("source"),
        "updated_at": db.now_iso(),
    }
    cols = ",".join(row)
    conn.execute(
        f"INSERT OR REPLACE INTO prospect_contacts ({cols}) VALUES ({','.join('?' for _ in row)})",
        list(row.values()),
    )
    return row


def _lead_domains(lead) -> set[str]:
    domains = set()
    website = normalize_domain(lead["website"] if "website" in lead.keys() else "")
    if website:
        domains.add(website)
    email_domain = normalize_domain(lead["email"] or "")
    if email_domain and email_domain not in db._FREEMAIL_DOMAINS:
        domains.add(email_domain)
    return domains


def for_lead(conn, lead):
    """The prospect_contacts row for this lead, or None."""
    if lead is None:
        return None
    for domain in _lead_domains(lead):
        row = conn.execute("SELECT * FROM prospect_contacts WHERE domain = ?", (domain,)).fetchone()
        if row:
            return row
    email = (lead["email"] or "").strip().lower()
    if email:
        return conn.execute(
            "SELECT * FROM prospect_contacts WHERE emails_index LIKE ? ORDER BY updated_at DESC LIMIT 1",
            (f"% {email} %",),
        ).fetchone()
    return None


def leads_for(conn, row) -> list[dict]:
    """Every leads_state row this saved contact set belongs to."""
    domain = row["domain"]
    emails = [e for e in (row["emails_index"] or "").split() if e]
    clauses = ["lower(website) LIKE ?", "lower(website) LIKE ?", "lower(email) LIKE ?"]
    params = [f"%://{domain}%", f"%://www.{domain}%", f"%@{domain}"]
    if emails:
        clauses.append(f"lower(email) IN ({','.join('?' for _ in emails)})")
        params.extend(emails)
    rows = conn.execute(
        f"SELECT campaign_id, lead_id, email, name, company FROM leads_state WHERE {' OR '.join(clauses)}",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def payload(row) -> dict | None:
    """Everything WebsiteGenerator found, for the "From their website" block."""
    if row is None:
        return None
    try:
        channels = json.loads(row["channels"] or "{}")
    except ValueError:
        channels = {}
    return {
        "domain": row["domain"],
        "company": row["company"],
        "website": row["website"],
        "demo_url": row["demo_url"],
        "channels": {k: v for k, v in channels.items() if v},
        "updated_at": row["updated_at"],
    }


def merge_icon_channels(researched: dict, row) -> dict:
    """Fills the icon row's gaps from the website scrape. The manual research
    lookup wins where it found something; the website fills whatever it missed.
    WhatsApp is always filled when the site has a number, confirmed or likely."""
    site = payload(row)
    if not site:
        return researched
    merged = dict(researched)
    for list_key, icon_key in _ICON_KEYS.items():
        items = site["channels"].get(list_key) or []
        if items and not merged.get(icon_key):
            merged[icon_key] = items[0]["value"]
    return merged


def authorized(request: Request) -> bool:
    """Shared with site_visits: both pushes come from the same script."""
    token = settings.contact_ingest_token
    if not token:
        return False
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else request.headers.get("x-ingest-token", "")
    return bool(supplied) and secrets.compare_digest(supplied, token)


@router.post("/api/prospect-contacts")
async def api_save_prospect_contacts(request: Request):
    """Called by WebsiteGenerator's cli/contacts.mjs --push. Token auth, not the
    dashboard session: it's a script on Andrew's machine, not a browser."""
    if not settings.contact_ingest_token:
        return JSONResponse({"error": "CONTACT_INGEST_TOKEN is not set on this server"}, status_code=503)
    if not authorized(request):
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
            matched = leads_for(conn, row)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"saved": True, "domain": row["domain"], "matched_leads": matched})
