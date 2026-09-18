"""A deliberately small CRM on top of the responder: the part of the funnel that
starts once a lead has booked a meeting.

Outreach (inbox, scheduled, sequences, campaigns, health, stats) ends at the
booking. From there a lead becomes a *deal* on a five-column board Andrew drags
through by hand, and the deal's record holds everything he needs for the next
move: to-dos, a journal, extra contacts, links, the research the drafter already
did and the cold-email thread that got them here.

Two ways in:
  * every lead Smartlead marks Meeting-Booked becomes a deal automatically, in
    the first stage (`ensure_deal_for_lead`, called from db.mark_lead_booked,
    plus `sync_booked` on every board load to backfill bookings that predate
    this module);
  * one click from any lead in the inbox ("+ Add to CRM").

Removing a deal only sets `removed_at`. The row stays, so the UNIQUE key keeps
the booking sync from quietly putting a deal Andrew threw out back on the board.
Adding the lead again by hand clears it.

Nothing here writes to Smartlead: moving a card is bookkeeping, not outreach.
"""
import re
import sqlite3
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import db
from app.auth import require_auth

router = APIRouter()

STAGES = [
    {"key": "meeting_booked", "label": "Meeting booked"},
    {"key": "negotiating", "label": "Negotiating"},
    {"key": "proposal_sent", "label": "Proposal sent · awaiting payment"},
    {"key": "won", "label": "Paid · client"},
    {"key": "lost", "label": "Lost"},
]
STAGE_KEYS = [s["key"] for s in STAGES]
STAGE_LABELS = {s["key"]: s["label"] for s in STAGES}
ITEM_KINDS = {"note", "todo", "contact", "link", "event"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS crm_deals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id          INTEGER,            -- NULL for a deal added by hand, not from a lead
    campaign_id      INTEGER,
    name             TEXT,               -- snapshot at creation; the lead row wins when it exists
    company          TEXT,
    email            TEXT,
    stage            TEXT NOT NULL DEFAULT 'meeting_booked',
    position         INTEGER NOT NULL DEFAULT 0,   -- order inside the column
    value            REAL,               -- deal value, optional
    source           TEXT,               -- booked|manual|lead
    stage_changed_at TEXT NOT NULL,
    removed_at       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (lead_id, campaign_id)
);

-- Everything on a deal's record, one table: kind decides which columns mean
-- something. note: body. todo: title, due_date, done. contact: title (name),
-- body (role), email, phone. link: title, url. event: body (written by the app
-- — stage changes, completed to-dos — so the journal is a real history).
CREATE TABLE IF NOT EXISTS crm_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id    INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    title      TEXT,
    body       TEXT,
    url        TEXT,
    email      TEXT,
    phone      TEXT,
    due_date   TEXT,                     -- YYYY-MM-DD
    done       INTEGER NOT NULL DEFAULT 0,
    done_at    TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_crm_items_deal ON crm_items (deal_id, kind);
"""


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


# ---- writes ----

def _log(conn, deal_id: int, text: str) -> None:
    now = db.now_iso()
    conn.execute(
        "INSERT INTO crm_items (deal_id, kind, body, created_at, updated_at) VALUES (?, 'event', ?, ?, ?)",
        (deal_id, text, now, now),
    )


def ensure_deal_for_lead(conn, lead_id: int, campaign_id: int, source: str = "booked") -> tuple[int | None, bool]:
    """Returns (deal_id, created). Never revives a removed deal — that is
    `add_lead`'s job, because only a click should undo a click."""
    row = conn.execute(
        "SELECT id FROM crm_deals WHERE lead_id = ? AND campaign_id = ?", (lead_id, campaign_id)
    ).fetchone()
    if row:
        return row["id"], False
    lead = db.get_lead_state(conn, lead_id, campaign_id)
    if lead is None:
        return None, False
    now = db.now_iso()
    since = (lead["booked_at"] if source == "booked" else None) or now
    cur = conn.execute(
        """INSERT INTO crm_deals (lead_id, campaign_id, name, company, email, stage, position,
                                  source, stage_changed_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'meeting_booked', 0, ?, ?, ?, ?)""",
        (lead_id, campaign_id, lead["name"], lead["company"], lead["email"], source, since, since, now),
    )
    deal_id = cur.lastrowid
    _log(conn, deal_id, "Meeting booked (from Smartlead)" if source == "booked" else "Added to CRM from the inbox")
    return deal_id, True


def sync_booked(conn) -> int:
    """Backfill: every booked lead without a deal gets one. Cheap enough to run
    on each board load (one anti-join), and it is what brings in the bookings
    recorded before the CRM existed."""
    rows = conn.execute(
        """SELECT l.lead_id, l.campaign_id FROM leads_state l
           LEFT JOIN crm_deals d ON d.lead_id = l.lead_id AND d.campaign_id = l.campaign_id
           WHERE (l.booked_at IS NOT NULL OR l.status = 'booked') AND d.id IS NULL"""
    ).fetchall()
    for r in rows:
        ensure_deal_for_lead(conn, r["lead_id"], r["campaign_id"], "booked")
    return len(rows)


def add_lead(conn, lead_id: int, campaign_id: int) -> int | None:
    deal_id, created = ensure_deal_for_lead(conn, lead_id, campaign_id, "lead")
    if deal_id and not created:
        row = conn.execute("SELECT removed_at FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
        if row["removed_at"]:
            conn.execute(
                "UPDATE crm_deals SET removed_at = NULL, position = -1, updated_at = ? WHERE id = ?",
                (db.now_iso(), deal_id),
            )
            _log(conn, deal_id, "Added back to CRM")
    return deal_id


def _renumber(conn, stage: str, order: list[int]) -> None:
    for i, deal_id in enumerate(order):
        conn.execute("UPDATE crm_deals SET position = ?, stage = ? WHERE id = ?", (i, stage, deal_id))


def _column_ids(conn, stage: str, exclude: int | None = None) -> list[int]:
    rows = conn.execute(
        """SELECT id FROM crm_deals WHERE stage = ? AND removed_at IS NULL
           ORDER BY position, stage_changed_at DESC""",
        (stage,),
    ).fetchall()
    return [r["id"] for r in rows if r["id"] != exclude]


def move_deal(conn, deal_id: int, stage: str, before_id: int | None) -> None:
    deal = conn.execute("SELECT stage FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
    now = db.now_iso()
    order = _column_ids(conn, stage, exclude=deal_id)
    idx = order.index(before_id) if before_id in order else len(order)
    order.insert(idx, deal_id)
    _renumber(conn, stage, order)
    if deal["stage"] != stage:
        conn.execute(
            "UPDATE crm_deals SET stage_changed_at = ?, updated_at = ? WHERE id = ?", (now, now, deal_id)
        )
        _log(conn, deal_id, f"Stage: {STAGE_LABELS.get(deal['stage'], deal['stage'])} → {STAGE_LABELS[stage]}")
        _renumber(conn, deal["stage"], _column_ids(conn, deal["stage"], exclude=deal_id))


# ---- reads ----

def _deal_dict(row) -> dict:
    d = dict(row)
    # The lead row is live (a rename in the inbox should show here); the
    # snapshot only covers a hand-added deal or a lead row that is gone.
    for key in ("name", "company", "email"):
        live = d.pop(f"lead_{key}", None)
        if live:
            d[key] = live
    d["name"] = d.get("name") or d.get("email") or "Unnamed"
    return d


_DEAL_SELECT = """
    SELECT d.*, l.name AS lead_name, l.company AS lead_company, l.email AS lead_email,
           l.campaign_name, l.booked_at, l.temperature
    FROM crm_deals d
    LEFT JOIN leads_state l ON l.lead_id = d.lead_id AND l.campaign_id = d.campaign_id
"""


def board(conn) -> dict:
    sync_booked(conn)
    rows = conn.execute(
        _DEAL_SELECT + " WHERE d.removed_at IS NULL ORDER BY d.position, d.stage_changed_at DESC"
    ).fetchall()
    todos = conn.execute(
        """SELECT deal_id, title, due_date FROM crm_items
           WHERE kind = 'todo' AND done = 0
           ORDER BY due_date IS NULL, due_date, id"""
    ).fetchall()
    open_todos: dict[int, list] = {}
    for t in todos:
        open_todos.setdefault(t["deal_id"], []).append(t)
    deals = []
    for r in rows:
        d = _deal_dict(r)
        mine = open_todos.get(d["id"], [])
        d["open_todos"] = len(mine)
        d["next_todo"] = {"title": mine[0]["title"], "due_date": mine[0]["due_date"]} if mine else None
        deals.append(d)
    return {"stages": STAGES, "deals": deals, "today": date.today().isoformat()}


def deal_detail(conn, deal_id: int) -> dict | None:
    row = conn.execute(_DEAL_SELECT + " WHERE d.id = ?", (deal_id,)).fetchone()
    if row is None:
        return None
    items = conn.execute(
        "SELECT * FROM crm_items WHERE deal_id = ? ORDER BY created_at DESC, id DESC", (deal_id,)
    ).fetchall()
    return {"deal": _deal_dict(row), "items": [dict(i) for i in items], "stages": STAGES}


def deal_for_lead(conn, lead_id: int, campaign_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, stage FROM crm_deals WHERE lead_id = ? AND campaign_id = ? AND removed_at IS NULL",
        (lead_id, campaign_id),
    ).fetchone()
    return {"id": row["id"], "stage": row["stage"], "stage_label": STAGE_LABELS.get(row["stage"])} if row else None


# ---- API ----

async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _clean(value, limit: int = 5000) -> str | None:
    if value is None:
        return None
    text = str(value).strip()[:limit]
    return text or None


def _valid_date(value) -> str | None:
    text = _clean(value, 10)
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _valid_url(value) -> str | None:
    text = _clean(value, 2000)
    if not text:
        return None
    # A bare "docs.google.com/x" gets https://; anything already naming
    # another scheme (javascript:, data:, mailto:) is refused below.
    if not re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", text, re.I):
        text = "https://" + text
    # The record renders this as an href: anything but http(s) (javascript:,
    # data:) is refused rather than escaped.
    return text if text.lower().startswith(("http://", "https://")) else None


def _not_found():
    return JSONResponse({"error": "Deal not found."}, status_code=404)


@router.get("/api/crm/board")
def api_board(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        return JSONResponse(board(conn))


@router.post("/api/crm/deals")
async def api_create_deal(request: Request):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _body(request)
    with db.db_session() as conn:
        if body.get("lead_id") and body.get("campaign_id"):
            try:
                deal_id = add_lead(conn, int(body["lead_id"]), int(body["campaign_id"]))
            except (TypeError, ValueError):
                deal_id = None
            if not deal_id:
                return JSONResponse({"error": "That lead isn't known to the app yet."}, status_code=400)
        else:
            name = _clean(body.get("name"), 200)
            company = _clean(body.get("company"), 200)
            if not (name or company):
                return JSONResponse({"error": "A name or a company is required."}, status_code=400)
            now = db.now_iso()
            deal_id = conn.execute(
                """INSERT INTO crm_deals (name, company, email, stage, position, source,
                                          stage_changed_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, -1, 'manual', ?, ?, ?)""",
                (name, company, _clean(body.get("email"), 200),
                 body.get("stage") if body.get("stage") in STAGE_KEYS else "meeting_booked", now, now, now),
            ).lastrowid
            _log(conn, deal_id, "Deal created by hand")
        return JSONResponse({"ok": True, "id": deal_id, **(deal_detail(conn, deal_id) or {})})


@router.get("/api/crm/deals/{deal_id}")
def api_deal(request: Request, deal_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        detail = deal_detail(conn, deal_id)
    return JSONResponse(detail) if detail else _not_found()


@router.patch("/api/crm/deals/{deal_id}")
async def api_update_deal(request: Request, deal_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _body(request)
    with db.db_session() as conn:
        if not conn.execute("SELECT 1 FROM crm_deals WHERE id = ?", (deal_id,)).fetchone():
            return _not_found()
        fields = {}
        for key in ("name", "company", "email"):
            if key in body:
                fields[key] = _clean(body[key], 200)
        if "value" in body:
            try:
                fields["value"] = float(body["value"]) if body["value"] not in (None, "") else None
            except (TypeError, ValueError):
                return JSONResponse({"error": "Value must be a number."}, status_code=400)
        if fields:
            fields["updated_at"] = db.now_iso()
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE crm_deals SET {sets} WHERE id = ?", (*fields.values(), deal_id))
        if body.get("stage") in STAGE_KEYS:
            current = conn.execute("SELECT stage FROM crm_deals WHERE id = ?", (deal_id,)).fetchone()
            if current["stage"] != body["stage"]:
                move_deal(conn, deal_id, body["stage"], None)
        return JSONResponse(deal_detail(conn, deal_id))


@router.post("/api/crm/deals/{deal_id}/move")
async def api_move_deal(request: Request, deal_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _body(request)
    stage = body.get("stage")
    if stage not in STAGE_KEYS:
        return JSONResponse({"error": "Unknown stage."}, status_code=400)
    before = body.get("before_id")
    with db.db_session() as conn:
        if not conn.execute("SELECT 1 FROM crm_deals WHERE id = ?", (deal_id,)).fetchone():
            return _not_found()
        move_deal(conn, deal_id, stage, int(before) if isinstance(before, int) else None)
    return JSONResponse({"ok": True})


@router.delete("/api/crm/deals/{deal_id}")
def api_remove_deal(request: Request, deal_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        conn.execute(
            "UPDATE crm_deals SET removed_at = ?, updated_at = ? WHERE id = ?",
            (db.now_iso(), db.now_iso(), deal_id),
        )
    return JSONResponse({"ok": True})


@router.post("/api/crm/deals/{deal_id}/items")
async def api_add_item(request: Request, deal_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _body(request)
    kind = body.get("kind")
    if kind not in ITEM_KINDS - {"event"}:
        return JSONResponse({"error": "Unknown item kind."}, status_code=400)
    item = {
        "title": _clean(body.get("title"), 300),
        "body": _clean(body.get("body")),
        "url": _valid_url(body.get("url")) if kind == "link" else None,
        "email": _clean(body.get("email"), 200),
        "phone": _clean(body.get("phone"), 60),
        "due_date": _valid_date(body.get("due_date")),
    }
    if kind == "note" and not item["body"]:
        return JSONResponse({"error": "The note is empty."}, status_code=400)
    if kind == "todo" and not item["title"]:
        return JSONResponse({"error": "The to-do needs a title."}, status_code=400)
    if kind == "link" and not item["url"]:
        return JSONResponse({"error": "That doesn't look like a web link."}, status_code=400)
    if kind == "contact" and not (item["title"] or item["email"] or item["phone"]):
        return JSONResponse({"error": "Add at least a name, email or phone."}, status_code=400)
    now = db.now_iso()
    with db.db_session() as conn:
        if not conn.execute("SELECT 1 FROM crm_deals WHERE id = ?", (deal_id,)).fetchone():
            return _not_found()
        try:
            conn.execute(
                """INSERT INTO crm_items (deal_id, kind, title, body, url, email, phone, due_date, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (deal_id, kind, *item.values(), now, now),
            )
        except sqlite3.Error as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        conn.execute("UPDATE crm_deals SET updated_at = ? WHERE id = ?", (now, deal_id))
        return JSONResponse(deal_detail(conn, deal_id))


@router.patch("/api/crm/items/{item_id}")
async def api_update_item(request: Request, item_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    body = await _body(request)
    with db.db_session() as conn:
        item = conn.execute("SELECT * FROM crm_items WHERE id = ?", (item_id,)).fetchone()
        if item is None or item["kind"] == "event":
            return JSONResponse({"error": "Item not found."}, status_code=404)
        now = db.now_iso()
        fields = {}
        for key, limit in (("title", 300), ("body", 5000), ("email", 200), ("phone", 60)):
            if key in body:
                fields[key] = _clean(body[key], limit)
        if "due_date" in body:
            fields["due_date"] = _valid_date(body["due_date"])
        if "url" in body and item["kind"] == "link":
            url = _valid_url(body["url"])
            if not url:
                return JSONResponse({"error": "That doesn't look like a web link."}, status_code=400)
            fields["url"] = url
        if "done" in body and item["kind"] == "todo":
            done = 1 if body["done"] else 0
            if done != item["done"]:
                fields["done"] = done
                fields["done_at"] = now if done else None
                if done:
                    _log(conn, item["deal_id"], f"Done: {item['title']}")
        if fields:
            fields["updated_at"] = now
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE crm_items SET {sets} WHERE id = ?", (*fields.values(), item_id))
        return JSONResponse(deal_detail(conn, item["deal_id"]))


@router.delete("/api/crm/items/{item_id}")
def api_delete_item(request: Request, item_id: int):
    redirect = require_auth(request)
    if redirect:
        return redirect
    with db.db_session() as conn:
        item = conn.execute("SELECT deal_id, kind FROM crm_items WHERE id = ?", (item_id,)).fetchone()
        if item is None or item["kind"] == "event":
            return JSONResponse({"error": "Item not found."}, status_code=404)
        conn.execute("DELETE FROM crm_items WHERE id = ?", (item_id,))
        return JSONResponse(deal_detail(conn, item["deal_id"]))
