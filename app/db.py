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
    -- captured once at draft-creation time and baked directly into body_html
    -- (app/pipeline.py); kept here mainly so api_draft_localize can re-embed
    -- it after the English round-trip regenerates body_html from scratch
    signature_html TEXT,
    model TEXT,  -- Claude model that generated this draft; NULL for manual/template drafts
    -- Andrew's explicit recipients for this send, set from the recipients row
    -- in the dashboard. NULL means "no override" -> the send falls back to
    -- detector.next_reply_to / next_reply_cc. An empty string is a real value
    -- for cc_override: it means he deliberately cleared the auto-derived Cc.
    cc_override TEXT,
    to_override TEXT
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

-- Persistent cache of per-message English translations (see translator.py).
-- Keyed by a hash of the message's plain text: a sent email never changes, so
-- its translation never changes — translate once, serve free forever after.
-- Content-hash keying dedupes identical boilerplate across leads and needs no
-- message_id plumbing.
-- Anthropic Batch API jobs submitted by app/batch_gen.py (overnight follow-up
-- pre-generation at 50% token cost). One row per submitted batch; the
-- 5-minute poll job closes it once results are consumed. Candidate linkage
-- rides in each request's custom_id ("cand-<candidate_id>"), not here.
CREATE TABLE IF NOT EXISTS gen_batches (
    batch_id   TEXT PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'submitted',  -- submitted|done|failed
    created_at TEXT NOT NULL,
    ended_at   TEXT
);

CREATE TABLE IF NOT EXISTS message_translations (
    source_hash TEXT PRIMARY KEY,
    english     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Canned follow-up templates shown in the "Message templates" modal, editable
-- from the dashboard (see app/main.py's /api/templates routes). Seeded once
-- from message_templates.DEFAULT_TEMPLATES when the table is first created.
CREATE TABLE IF NOT EXISTS message_templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    label      TEXT,
    text       TEXT NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Campaign analytics (see app/campaign_analytics.py, app/campaign_report.py).
-- Local mirror of Smartlead's per-send data so the variant/slot maths runs as
-- plain SQL and a re-analysis doesn't re-download the whole campaign.
-- ---------------------------------------------------------------------------

-- One row per sent email, from GET /campaigns/{id}/statistics. `seq_variant_id`
-- is the whole point: it's the only link from an outcome back to the message
-- variant that produced it. The rendered `email_message` is deliberately NOT
-- stored (~10 KB/row, ~75 MB for one campaign) — only the rendered subject,
-- which is short and is what subject-line analysis needs.
CREATE TABLE IF NOT EXISTS campaign_sends (
    stats_id             TEXT PRIMARY KEY,
    campaign_id          INTEGER NOT NULL,
    lead_email           TEXT,
    sequence_number      INTEGER,
    email_campaign_seq_id INTEGER,
    seq_variant_id       INTEGER,
    email_subject        TEXT,
    sent_time            TEXT,
    reply_time           TEXT,
    lead_category        TEXT,
    is_bounced           INTEGER NOT NULL DEFAULT 0,
    is_unsubscribed      INTEGER NOT NULL DEFAULT 0,
    click_time           TEXT
);

CREATE INDEX IF NOT EXISTS idx_sends_campaign_step
    ON campaign_sends (campaign_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_sends_campaign_variant
    ON campaign_sends (campaign_id, seq_variant_id);
CREATE INDEX IF NOT EXISTS idx_sends_campaign_email
    ON campaign_sends (campaign_id, lead_email);

-- The message templates themselves, from GET /campaigns/{id}/sequences.
-- `slots_json` is the parsed {{variable}} recipe (see campaign_analytics.
-- parse_slots) — variants share slots, which is what makes slot-level pooling
-- possible.
CREATE TABLE IF NOT EXISTS campaign_variants (
    campaign_id      INTEGER NOT NULL,
    seq_variant_id   INTEGER NOT NULL,
    seq_number       INTEGER,
    variant_label    TEXT,
    subject_template TEXT,
    body_template    TEXT,
    slots_json       TEXT,
    PRIMARY KEY (campaign_id, seq_variant_id)
);

-- Per-lead variable values, parsed from the leads-export CSV's custom_fields
-- column — i.e. the spreadsheet the campaign was built from, recovered from
-- Smartlead. Also the only bulk email -> lead_id map, which the conversation
-- sync needs (statistics rows carry only the email).
CREATE TABLE IF NOT EXISTS campaign_lead_vars (
    campaign_id              INTEGER NOT NULL,
    lead_email               TEXT NOT NULL,
    lead_id                  TEXT,
    company_name             TEXT,
    category                 TEXT,
    reply_count              INTEGER NOT NULL DEFAULT 0,
    last_email_sequence_sent INTEGER,
    custom_fields_json       TEXT,
    PRIMARY KEY (campaign_id, lead_email)
);

CREATE INDEX IF NOT EXISTS idx_lead_vars_lead ON campaign_lead_vars (campaign_id, lead_id);

-- Full conversations with leads who actually answered like humans (never
-- Auto-Reply / Out Of Office — see campaign_conversations.REAL_RESPONSE
-- filtering). `first_reply_after_step` is what answers "how many follow-ups
-- still work". `extract_json` caches the per-conversation AI extraction so a
-- re-analysis only pays for new conversations.
CREATE TABLE IF NOT EXISTS campaign_conversations (
    campaign_id           INTEGER NOT NULL,
    lead_id               TEXT NOT NULL,
    lead_email            TEXT,
    company               TEXT,
    category              TEXT,
    variant_label         TEXT,
    seq_variant_id        INTEGER,
    thread_json           TEXT,
    our_msg_count         INTEGER NOT NULL DEFAULT 0,
    their_msg_count       INTEGER NOT NULL DEFAULT 0,
    first_reply_after_step INTEGER,
    first_reply_at        TEXT,
    hours_to_reply        REAL,
    thread_hash           TEXT,
    extract_json          TEXT,
    extracted_at          TEXT,
    synced_at             TEXT NOT NULL,
    PRIMARY KEY (campaign_id, lead_id)
);

-- One cached analysis per campaign. `stage` is progress text the dashboard
-- polls while the background thread works.
CREATE TABLE IF NOT EXISTS campaign_reports (
    campaign_id     INTEGER PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'running',  -- running|done|failed
    stage           TEXT,
    started_at      TEXT,
    generated_at    TEXT,
    model           TEXT,
    stats_json      TEXT,
    report_md       TEXT,
    conversation_md TEXT,
    error           TEXT
);

-- Sync bookkeeping: `last_sent_time` is replayed as statistics'
-- sent_time_start_date so only the first sync of a campaign is expensive.
CREATE TABLE IF NOT EXISTS campaign_sync (
    campaign_id     INTEGER PRIMARY KEY,
    last_sent_time  TEXT,
    sends_synced_at TEXT,
    vars_synced_at  TEXT,
    convos_synced_at TEXT
);
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
        # Checked *before* SCHEMA runs: the seed must happen only on a database
        # that has never had this table, not "whenever it's empty" — otherwise
        # templates Andrew deleted would come back on the next restart.
        needs_template_seed = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'message_templates'"
        ).fetchone() is None
        conn.executescript(SCHEMA)
        _migrate(conn)
        if needs_template_seed:
            _seed_message_templates(conn)


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
    if "model" not in draft_cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN model TEXT")
    if "cc_override" not in draft_cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN cc_override TEXT")
    if "to_override" not in draft_cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN to_override TEXT")

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
        # name_locked: set once Andrew manually corrects `name` (see
        # app.main.api_set_lead_name) so the scan's base_fields (scheduler.py)
        # stop overwriting it from Smartlead's own first_name every run.
        "name_locked": "INTEGER NOT NULL DEFAULT 0",
        # Smartlead's own name for the lead's inbox (webhook `to_name`), shown
        # next to `name` so a wrong imported first_name is easy to spot.
        "email_display_name": "TEXT",
        # set when the scan sees Smartlead's "Meeting-Booked" category on the
        # lead — the app's success metric. Never overwritten once set.
        "booked_at": "TEXT",
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


def mark_lead_booked(conn, lead_id: int, campaign_id: int) -> None:
    """Meeting booked (Smartlead's "Meeting-Booked" category seen on the lead):
    freeze all outreach for this lead — open drafts go stale, open candidates
    are dismissed, status becomes 'booked' (detector.decide treats it like
    stopped). booked_at is set once and never overwritten, so the first
    booking date survives later rescans."""
    conn.execute(
        """UPDATE drafts SET status = 'stale'
           WHERE lead_id = ? AND campaign_id = ? AND status IN ('pending', 'scheduled')""",
        (lead_id, campaign_id),
    )
    conn.execute(
        """UPDATE candidates SET status = 'dismissed', reason = 'meeting booked', updated_at = ?
           WHERE lead_id = ? AND campaign_id = ? AND status IN ('open', 'generating')""",
        (now_iso(), lead_id, campaign_id),
    )
    upsert_lead_state(conn, lead_id, campaign_id, status="booked", category="booked")
    conn.execute(
        """UPDATE leads_state SET booked_at = ?
           WHERE lead_id = ? AND campaign_id = ? AND booked_at IS NULL""",
        (now_iso(), lead_id, campaign_id),
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


def list_scheduled(conn):
    """All drafts waiting on the 1-minute due_send_loop (scheduler.py), soonest
    first — backs the dashboard's "Scheduled" tab."""
    return conn.execute(
        "SELECT * FROM drafts WHERE status = 'scheduled' ORDER BY scheduled_at ASC"
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


# ---- batch-generation helpers (see app/batch_gen.py) ----

def create_gen_batch(conn, batch_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO gen_batches (batch_id, status, created_at) VALUES (?, 'submitted', ?)",
        (batch_id, now_iso()),
    )


def list_open_gen_batches(conn):
    return conn.execute(
        "SELECT * FROM gen_batches WHERE status = 'submitted' ORDER BY created_at ASC"
    ).fetchall()


def close_gen_batch(conn, batch_id: str, status: str = "done") -> None:
    conn.execute(
        "UPDATE gen_batches SET status = ?, ended_at = ? WHERE batch_id = ?",
        (status, now_iso(), batch_id),
    )


# ---- translation cache helpers (see translator.translate_segments_cached) ----

def get_cached_translations(conn, hashes: list[str]) -> dict[str, str]:
    """Batch-lookup cached English translations by source hash. Returns only the
    hashes that are present, mapped to their English text."""
    if not hashes:
        return {}
    placeholders = ",".join("?" for _ in hashes)
    rows = conn.execute(
        f"SELECT source_hash, english FROM message_translations WHERE source_hash IN ({placeholders})",
        hashes,
    ).fetchall()
    return {row["source_hash"]: row["english"] for row in rows}


def put_cached_translation(conn, source_hash: str, english: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO message_translations (source_hash, english, created_at) VALUES (?, ?, ?)",
        (source_hash, english, now_iso()),
    )


# ---- message template helpers (see app/main.py's /api/templates routes) ----

def _seed_message_templates(conn) -> None:
    """First-run only (see init_db) — the shipped starter set."""
    from app.message_templates import DEFAULT_TEMPLATES

    for position, tpl in enumerate(DEFAULT_TEMPLATES):
        create_message_template(conn, tpl.get("label") or "", tpl["text"], position=position)


def list_message_templates(conn):
    return conn.execute(
        "SELECT * FROM message_templates ORDER BY position ASC, id ASC"
    ).fetchall()


def get_message_template(conn, template_id: int):
    return conn.execute(
        "SELECT * FROM message_templates WHERE id = ?", (template_id,)
    ).fetchone()


def create_message_template(conn, label: str, text: str, position: int | None = None) -> int:
    if position is None:
        row = conn.execute("SELECT MAX(position) AS m FROM message_templates").fetchone()
        position = ((row["m"] if row and row["m"] is not None else -1)) + 1
    now = now_iso()
    cur = conn.execute(
        """INSERT INTO message_templates (label, text, position, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (label, text, position, now, now),
    )
    return cur.lastrowid


def update_message_template(conn, template_id: int, **fields) -> None:
    fields["updated_at"] = now_iso()
    set_clause = ",".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE message_templates SET {set_clause} WHERE id = ?",
        list(fields.values()) + [template_id],
    )


def delete_message_template(conn, template_id: int) -> None:
    conn.execute("DELETE FROM message_templates WHERE id = ?", (template_id,))


def reorder_message_templates(conn, ordered_ids: list[int]) -> None:
    """Renumber positions to match `ordered_ids` exactly (0, 1, 2, …). Cheaper
    to reason about than swapping two rows' position values, and it also
    repairs any duplicate/gapped positions left by earlier edits."""
    now = now_iso()
    for position, template_id in enumerate(ordered_ids):
        conn.execute(
            "UPDATE message_templates SET position = ?, updated_at = ? WHERE id = ?",
            (position, now, template_id),
        )


# ---- campaign analytics helpers (see app/campaign_analytics.py) ----

def upsert_campaign_sends(conn, rows: list[dict]) -> int:
    """Bulk-upsert statistics rows. Keyed on stats_id so re-syncing an
    overlapping window updates rows (a reply can land after the send was first
    recorded) instead of duplicating them."""
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO campaign_sends (
               stats_id, campaign_id, lead_email, sequence_number,
               email_campaign_seq_id, seq_variant_id, email_subject, sent_time,
               reply_time, lead_category, is_bounced, is_unsubscribed, click_time
           ) VALUES (
               :stats_id, :campaign_id, :lead_email, :sequence_number,
               :email_campaign_seq_id, :seq_variant_id, :email_subject, :sent_time,
               :reply_time, :lead_category, :is_bounced, :is_unsubscribed, :click_time
           )
           ON CONFLICT(stats_id) DO UPDATE SET
               reply_time      = excluded.reply_time,
               lead_category   = excluded.lead_category,
               is_bounced      = excluded.is_bounced,
               is_unsubscribed = excluded.is_unsubscribed,
               click_time      = excluded.click_time""",
        rows,
    )
    return len(rows)


def replace_campaign_variants(conn, campaign_id: int, rows: list[dict]) -> None:
    """Variants are edited in Smartlead, so the local copy is a full replace
    rather than a merge — a deleted variant must disappear here too."""
    conn.execute("DELETE FROM campaign_variants WHERE campaign_id = ?", (campaign_id,))
    if rows:
        conn.executemany(
            """INSERT INTO campaign_variants (
                   campaign_id, seq_variant_id, seq_number, variant_label,
                   subject_template, body_template, slots_json
               ) VALUES (
                   :campaign_id, :seq_variant_id, :seq_number, :variant_label,
                   :subject_template, :body_template, :slots_json
               )""",
            rows,
        )


def list_campaign_variants(conn, campaign_id: int):
    return conn.execute(
        "SELECT * FROM campaign_variants WHERE campaign_id = ? ORDER BY seq_number, variant_label",
        (campaign_id,),
    ).fetchall()


def upsert_campaign_lead_vars(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO campaign_lead_vars (
               campaign_id, lead_email, lead_id, company_name, category,
               reply_count, last_email_sequence_sent, custom_fields_json
           ) VALUES (
               :campaign_id, :lead_email, :lead_id, :company_name, :category,
               :reply_count, :last_email_sequence_sent, :custom_fields_json
           )
           ON CONFLICT(campaign_id, lead_email) DO UPDATE SET
               lead_id                  = excluded.lead_id,
               company_name             = excluded.company_name,
               category                 = excluded.category,
               reply_count              = excluded.reply_count,
               last_email_sequence_sent = excluded.last_email_sequence_sent,
               custom_fields_json       = excluded.custom_fields_json""",
        rows,
    )
    return len(rows)


def get_campaign_sync(conn, campaign_id: int):
    return conn.execute(
        "SELECT * FROM campaign_sync WHERE campaign_id = ?", (campaign_id,)
    ).fetchone()


def update_campaign_sync(conn, campaign_id: int, **fields) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO campaign_sync (campaign_id) VALUES (?)", (campaign_id,)
    )
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE campaign_sync SET {assignments} WHERE campaign_id = ?",
        (*fields.values(), campaign_id),
    )


# ---- campaign conversation helpers (see app/campaign_conversations.py) ----

def upsert_campaign_conversation(conn, campaign_id: int, lead_id: str, **fields) -> None:
    """Upsert one thread. `extract_json`/`extracted_at` are left alone unless
    explicitly passed, so a re-sync that finds an unchanged thread keeps the
    cached AI extraction and costs nothing to re-analyze."""
    fields["synced_at"] = now_iso()
    columns = ", ".join(["campaign_id", "lead_id", *fields])
    placeholders = ", ".join("?" for _ in range(len(fields) + 2))
    updates = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"""INSERT INTO campaign_conversations ({columns}) VALUES ({placeholders})
            ON CONFLICT(campaign_id, lead_id) DO UPDATE SET {updates}""",
        (campaign_id, lead_id, *fields.values(), *fields.values()),
    )


def list_campaign_conversations(conn, campaign_id: int, unextracted_only: bool = False):
    sql = "SELECT * FROM campaign_conversations WHERE campaign_id = ?"
    if unextracted_only:
        sql += " AND (extract_json IS NULL OR extract_json = '')"
    sql += " ORDER BY first_reply_at DESC"
    return conn.execute(sql, (campaign_id,)).fetchall()


def clear_campaign_conversations(conn, campaign_id: int) -> None:
    conn.execute("DELETE FROM campaign_conversations WHERE campaign_id = ?", (campaign_id,))


# ---- campaign report helpers (see app/campaign_report.py) ----

def start_campaign_report(conn, campaign_id: int, stage: str = "Starting…") -> None:
    conn.execute(
        """INSERT INTO campaign_reports (campaign_id, status, stage, started_at, error)
           VALUES (?, 'running', ?, ?, NULL)
           ON CONFLICT(campaign_id) DO UPDATE SET
               status = 'running', stage = excluded.stage,
               started_at = excluded.started_at, error = NULL""",
        (campaign_id, stage, now_iso()),
    )


def update_campaign_report(conn, campaign_id: int, **fields) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(
        f"UPDATE campaign_reports SET {assignments} WHERE campaign_id = ?",
        (*fields.values(), campaign_id),
    )


def get_campaign_report(conn, campaign_id: int):
    return conn.execute(
        "SELECT * FROM campaign_reports WHERE campaign_id = ?", (campaign_id,)
    ).fetchone()
