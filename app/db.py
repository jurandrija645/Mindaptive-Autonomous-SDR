import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads_state (
    lead_id INTEGER NOT NULL,
    campaign_id INTEGER NOT NULL,
    email TEXT,
    name TEXT,
    company TEXT,
    website TEXT,
    timezone_guess TEXT,
    followup_count INTEGER NOT NULL DEFAULT 0,
    last_followup_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',  -- active|stopped|awaiting_reply|blacklisted
    updated_at TEXT NOT NULL,
    -- inbox summary, recorded by the daily/on-demand scan (see scheduler._process_lead)
    interested INTEGER NOT NULL DEFAULT 0,
    campaign_name TEXT,
    category TEXT,              -- reply|followup|waiting  (drives the row colour)
    language TEXT,              -- 2-letter code of the lead's last message
    last_message_preview TEXT,
    last_message_at TEXT,
    last_message_kind TEXT,     -- sent|reply  (who spoke last)
    -- archive / snooze — both hide a lead from list_inbox; see list_archived/list_snoozed
    archived_at TEXT,           -- set => archived (manually, or via "not interested")
    archive_reason TEXT,        -- manual|not_interested
    snooze_until TEXT,          -- 'YYYY-MM-DD'; hidden until this date, then top priority
    -- captured once during drafting (see drafter.py's <lead_research> tag),
    -- reused on later drafts instead of re-researching the lead's website
    research_summary TEXT,
    researched_at TEXT,
    PRIMARY KEY (lead_id, campaign_id)
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    campaign_id INTEGER NOT NULL,
    kind TEXT NOT NULL,  -- followup|reply
    triage_summary TEXT,
    body_html TEXT NOT NULL,
    body_translation TEXT,
    thread_snapshot TEXT,
    reply_message_id TEXT,
    reply_email_time TEXT,
    reply_stats_id TEXT,  -- Smartlead's internal stats_id; required as email_stats_id when actually sending
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|scheduled|sent|skipped|stale|aborted
    scheduled_at TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    lead_name TEXT,
    lead_company TEXT,
    lead_email TEXT,
    sender_email TEXT,
    -- stored separately from body_html so contenteditable edits and the
    -- English translate/localize round-trip (app/translator.py) can never
    -- touch it; re-attached only at actual send time (scheduler.compose_send_body)
    signature_html TEXT
);

CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts (status);
CREATE INDEX IF NOT EXISTS idx_drafts_lead ON drafts (lead_id, campaign_id);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    campaign_id INTEGER NOT NULL,
    kind TEXT NOT NULL,  -- followup|reply
    lead_name TEXT,
    lead_company TEXT,
    lead_email TEXT,
    campaign_name TEXT,
    reason TEXT,
    last_message_preview TEXT,
    last_message_at TEXT,
    status TEXT NOT NULL DEFAULT 'open',  -- open|generating|drafted|dismissed
    draft_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (lead_id, campaign_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates (status);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db_session() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn) -> None:
    """Additive column migrations for databases created before a schema change.
    CREATE TABLE IF NOT EXISTS above doesn't add columns to an existing table."""
    draft_cols = {row["name"] for row in conn.execute("PRAGMA table_info(drafts)")}
    if "sender_email" not in draft_cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN sender_email TEXT")
    if "signature_html" not in draft_cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN signature_html TEXT")
    if "reply_stats_id" not in draft_cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN reply_stats_id TEXT")

    lead_cols = {row["name"] for row in conn.execute("PRAGMA table_info(leads_state)")}
    inbox_columns = {
        "interested": "INTEGER NOT NULL DEFAULT 0",
        "campaign_name": "TEXT",
        "category": "TEXT",
        "language": "TEXT",
        "last_message_preview": "TEXT",
        "last_message_at": "TEXT",
        "last_message_kind": "TEXT",
        "archived_at": "TEXT",
        "archive_reason": "TEXT",
        "snooze_until": "TEXT",
        "research_summary": "TEXT",
        "researched_at": "TEXT",
    }
    for name, decl in inbox_columns.items():
        if name not in lead_cols:
            conn.execute(f"ALTER TABLE leads_state ADD COLUMN {name} {decl}")


# ---- leads_state helpers ----

def get_lead_state(conn, lead_id: int, campaign_id: int):
    return conn.execute(
        "SELECT * FROM leads_state WHERE lead_id = ? AND campaign_id = ?",
        (lead_id, campaign_id),
    ).fetchone()


def upsert_lead_state(conn, lead_id: int, campaign_id: int, **fields) -> None:
    existing = get_lead_state(conn, lead_id, campaign_id)
    fields["updated_at"] = now_iso()
    if existing is None:
        fields.setdefault("followup_count", 0)
        fields.setdefault("status", "active")
        cols = ["lead_id", "campaign_id"] + list(fields.keys())
        vals = [lead_id, campaign_id] + list(fields.values())
        placeholders = ",".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO leads_state ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
    else:
        set_clause = ",".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE leads_state SET {set_clause} WHERE lead_id = ? AND campaign_id = ?",
            list(fields.values()) + [lead_id, campaign_id],
        )


def increment_followup_count(conn, lead_id: int, campaign_id: int) -> None:
    conn.execute(
        """UPDATE leads_state
           SET followup_count = followup_count + 1, last_followup_at = ?, updated_at = ?
           WHERE lead_id = ? AND campaign_id = ?""",
        (now_iso(), now_iso(), lead_id, campaign_id),
    )


def list_inbox(conn):
    """Every interested, non-stopped, non-archived, non-snoozed(-future) lead for
    the unified inbox. Ordering: a snooze whose date has arrived jumps to the
    very top (that's the point of snoozing — surface it prominently once due),
    then awaiting-our-reply (red), then follow-up-due (amber), then the rest;
    within a tier, most recent activity first."""
    now = now_iso()
    return conn.execute(
        """SELECT * FROM leads_state
           WHERE interested = 1 AND status != 'stopped'
             AND archived_at IS NULL
             AND (snooze_until IS NULL OR snooze_until <= ?)
           ORDER BY
             CASE
               WHEN snooze_until IS NOT NULL AND snooze_until <= ? THEN 0
               WHEN category IN ('reply', 'auto_reply') THEN 1
               WHEN category = 'followup' THEN 2
               ELSE 3
             END,
             last_message_at DESC""",
        (now, now),
    ).fetchall()


def list_archived(conn):
    """Leads hidden via Archive or Not Interested, most recently archived first."""
    return conn.execute(
        """SELECT * FROM leads_state WHERE archived_at IS NOT NULL
           ORDER BY archived_at DESC"""
    ).fetchall()


def list_snoozed(conn):
    """Leads snoozed to a future date — hidden from the inbox until then."""
    return conn.execute(
        """SELECT * FROM leads_state
           WHERE archived_at IS NULL AND snooze_until IS NOT NULL AND snooze_until > ?
           ORDER BY snooze_until ASC""",
        (now_iso(),),
    ).fetchall()


# ---- drafts helpers ----

def create_draft(conn, **fields) -> int:
    fields["created_at"] = now_iso()
    fields.setdefault("status", "pending")
    cols = list(fields.keys())
    vals = list(fields.values())
    placeholders = ",".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO drafts ({','.join(cols)}) VALUES ({placeholders})", vals
    )
    return cur.lastrowid


def get_draft(conn, draft_id: int):
    return conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()


def list_drafts(conn, status: str | None = None, kind: str | None = None):
    query = "SELECT * FROM drafts WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if kind:
        query += " AND kind = ?"
        params.append(kind)
    query += " ORDER BY created_at DESC"
    return conn.execute(query, params).fetchall()


def list_due_scheduled(conn):
    return conn.execute(
        "SELECT * FROM drafts WHERE status = 'scheduled' AND scheduled_at <= ?",
        (now_iso(),),
    ).fetchall()


def update_draft(conn, draft_id: int, **fields) -> None:
    set_clause = ",".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE drafts SET {set_clause} WHERE id = ?",
        list(fields.values()) + [draft_id],
    )


def has_open_draft(conn, lead_id: int, campaign_id: int) -> bool:
    row = conn.execute(
        """SELECT 1 FROM drafts WHERE lead_id = ? AND campaign_id = ?
           AND status IN ('pending', 'scheduled') LIMIT 1""",
        (lead_id, campaign_id),
    ).fetchone()
    return row is not None


def has_drafted_reply_to(conn, lead_id: int, campaign_id: int, message_id: str) -> bool:
    """True if any draft (any status) already exists for this exact inbound
    message — used to stop the Auto-Reply nudge path from re-drafting the
    same auto-response every scan just because it was skipped rather than sent."""
    row = conn.execute(
        "SELECT 1 FROM drafts WHERE lead_id = ? AND campaign_id = ? AND reply_message_id = ? LIMIT 1",
        (lead_id, campaign_id, message_id),
    ).fetchone()
    return row is not None


def get_open_draft(conn, lead_id: int, campaign_id: int):
    """The current editable draft (pending or scheduled) for a lead, if any —
    what the detail pane shows when you open the lead."""
    return conn.execute(
        """SELECT * FROM drafts WHERE lead_id = ? AND campaign_id = ?
           AND status IN ('pending', 'scheduled')
           ORDER BY created_at DESC LIMIT 1""",
        (lead_id, campaign_id),
    ).fetchone()


# ---- candidates helpers ----

def upsert_candidate(conn, lead_id: int, campaign_id: int, kind: str, **fields) -> None:
    """Insert or refresh an 'open' candidate. No-ops if a candidate for this
    lead/kind already exists in a non-open state (generating/drafted/dismissed) —
    those are left alone so the daily scan doesn't clobber in-flight work."""
    existing = conn.execute(
        "SELECT * FROM candidates WHERE lead_id = ? AND campaign_id = ? AND kind = ?",
        (lead_id, campaign_id, kind),
    ).fetchone()
    now = now_iso()
    if existing is None:
        fields["created_at"] = now
        fields["updated_at"] = now
        fields.setdefault("status", "open")
        cols = ["lead_id", "campaign_id", "kind"] + list(fields.keys())
        vals = [lead_id, campaign_id, kind] + list(fields.values())
        placeholders = ",".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO candidates ({','.join(cols)}) VALUES ({placeholders})", vals
        )
    elif existing["status"] == "open":
        fields["updated_at"] = now
        set_clause = ",".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE candidates SET {set_clause} WHERE id = ?",
            list(fields.values()) + [existing["id"]],
        )


def clear_stale_open_candidates(conn, kind: str, still_due_lead_ids: set[tuple[int, int]]) -> None:
    """Remove 'open' candidates of this kind that are no longer due (lead
    replied, cadence not yet reached, or cap hit) since the last scan."""
    rows = conn.execute(
        "SELECT id, lead_id, campaign_id FROM candidates WHERE kind = ? AND status = 'open'",
        (kind,),
    ).fetchall()
    for row in rows:
        if (row["lead_id"], row["campaign_id"]) not in still_due_lead_ids:
            conn.execute("DELETE FROM candidates WHERE id = ?", (row["id"],))


def get_candidate(conn, candidate_id: int):
    return conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()


def list_candidates(conn, status: str = "open", kind: str | None = None):
    query = "SELECT * FROM candidates WHERE status = ?"
    params: list = [status]
    if kind:
        query += " AND kind = ?"
        params.append(kind)
    query += " ORDER BY created_at ASC"
    return conn.execute(query, params).fetchall()


def update_candidate(conn, candidate_id: int, **fields) -> None:
    fields["updated_at"] = now_iso()
    set_clause = ",".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE candidates SET {set_clause} WHERE id = ?",
        list(fields.values()) + [candidate_id],
    )
