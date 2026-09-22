"""Outreach that happened somewhere other than email.

Andrew chases a lead who stopped answering email on WhatsApp, LinkedIn,
Facebook or Instagram (the same channels app/lead_research.py digs up and
app.js renders as one-click icons). Until now none of that was written down
anywhere, so the thread said "two emails, silence" when the truth was "two
emails, and I messaged him on WhatsApp yesterday".

These are notes, not messages: nothing is sent from here and nothing is
fetched. A row is one manual log entry, and it is rendered inline in the
email thread at its own timestamp so the whole history reads in one column.

Deliberately its own table rather than a column on `drafts` or a fake
`lead_threads` entry: a touch has no body, no send path and no race check,
and mixing it into the thread cache would put it in front of the drafter and
the classifier, which should keep seeing email only.
"""
import logging
from datetime import datetime, timezone

from app import db

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS lead_touches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    campaign_id INTEGER NOT NULL,
    channel TEXT NOT NULL,           -- whatsapp / linkedin / facebook / instagram / phone / sms / other
    direction TEXT NOT NULL,         -- 'out' (we contacted them) or 'in' (they answered there)
    note TEXT,                       -- what was said, in Andrew's own words
    occurred_at TEXT NOT NULL,       -- ISO-8601 UTC; what the thread sorts on
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lead_touches_lead
    ON lead_touches (campaign_id, lead_id, occurred_at);
"""

# The channels Andrew actually uses. Keys are stored, so renaming one is a
# migration; the labels live in the client (CHANNEL_DEFS in app.js), which
# already had icons and brand colours for the first four.
CHANNELS = ("whatsapp", "linkedin", "facebook", "instagram", "phone", "sms", "other")
DIRECTIONS = ("out", "in")


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_occurred_at(raw) -> str:
    """The client posts the moment as ISO-8601 (it converts the picker's local
    time to UTC itself, same as scheduleDraft). Anything unparseable becomes
    'now' rather than failing the save — a log entry with a slightly wrong
    timestamp beats losing the note."""
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            log.warning("lead touch: unparseable occurred_at %r, using now", raw)
        else:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
    return _now()


def add(conn, lead_id: int, campaign_id: int, channel: str, direction: str,
        note: str | None, occurred_at=None) -> int:
    channel = (channel or "").strip().lower()
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
    direction = (direction or "out").strip().lower()
    if direction not in DIRECTIONS:
        raise ValueError("direction must be 'out' or 'in'")
    cur = conn.execute(
        """INSERT INTO lead_touches
               (lead_id, campaign_id, channel, direction, note, occurred_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (lead_id, campaign_id, channel, direction, (note or "").strip() or None,
         _normalize_occurred_at(occurred_at), _now()),
    )
    return int(cur.lastrowid)


def delete(conn, touch_id: int, lead_id: int, campaign_id: int) -> bool:
    """Scoped to the lead on purpose — the id comes from the browser, so the
    route must not be able to delete another lead's log entry by guessing."""
    cur = conn.execute(
        "DELETE FROM lead_touches WHERE id = ? AND lead_id = ? AND campaign_id = ?",
        (touch_id, lead_id, campaign_id),
    )
    return cur.rowcount > 0


def list_for_lead(conn, lead_id: int, campaign_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM lead_touches
            WHERE lead_id = ? AND campaign_id = ?
            ORDER BY occurred_at""",
        (lead_id, campaign_id),
    ).fetchall()
    return [dict(r) for r in rows]


def for_lead(lead_id: int, campaign_id: int) -> list[dict]:
    # No ensure_table here: db.init_db creates it at startup, and a
    # CREATE TABLE on a read path would take the write lock for no reason.
    with db.db_session() as conn:
        return list_for_lead(conn, lead_id, campaign_id)
