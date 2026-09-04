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
    category TEXT,              -- reply|followup|waiting|auto_reply|not_interested|booked  (drives the row colour)
    -- The message app/reply_classifier.py last judged to produce the CURRENT
    -- reply/auto_reply/not_interested label. Read by scheduler.run_reply_catch_
    -- scan and app/webhook.py before calling the classifier again: if the
    -- lead's newest message is still this one, the verdict already on file
    -- stands untouched — no repeat model call, and no risk of a later call
    -- flipping a label that was already applied. It only moves again once a
    -- genuinely new message arrives (a different id) or Andrew changes the
    -- status by hand.
    category_message_id TEXT,
    -- Smartlead's own category name for this lead, as of the last time we
    -- looked (the daily scan's per-campaign listing, or the 60s recent-replies
    -- poll) — e.g. "Interested", "Not Interested", "Do Not Contact", "Auto
    -- Reply", "Meeting-Booked". Purely informational: shown next to the
    -- "Change status" control so a manual change isn't a guess. Does NOT
    -- drive `category` — see app/reply_classifier.py for what does.
    smartlead_category TEXT,
    -- How hot the lead is: cold|warm|hot (app/lead_temperature.py). Deliberately
    -- NOT the same axis as `category` above or Smartlead's own lead category —
    -- those say what the thread needs next and how Smartlead filed the lead;
    -- this says whether they asked to talk. Sorts hot leads to the very top of
    -- list_inbox and shortens their follow-up cadence to HOT_FOLLOWUP_WAIT_HOURS.
    temperature TEXT NOT NULL DEFAULT 'cold',
    temperature_reason TEXT,        -- one line, why it was rated that
    temperature_message_id TEXT,    -- the lead message the rating was read from, so it's judged once
    temperature_locked INTEGER NOT NULL DEFAULT 0,  -- Andrew set it by hand; the classifier stops touching it
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
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|scheduled|sending|sent|skipped|stale|aborted
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
    to_override TEXT,
    -- JSON list of {slug, file_name, file_url, file_type, file_size} chosen from
    -- the attachment library (app/library.py). Stored on the draft rather than
    -- resolved at send time so a scheduled send ships exactly what was picked
    -- and reviewed, even if the library changes in between.
    attachments TEXT,
    -- Last synchronous send failure, shown with the draft after it is restored
    -- to a retryable status. Cleared atomically when the next send begins.
    send_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts (status);
CREATE INDEX IF NOT EXISTS idx_drafts_lead ON drafts (lead_id, campaign_id);

-- Latest complete Smartlead thread per lead. Draft snapshots remain immutable
-- evidence of what the model saw; this table is the refreshable copy used by
-- the conversation UI and every path that has already paid to fetch a thread.
CREATE TABLE IF NOT EXISTS lead_threads (
    campaign_id      INTEGER NOT NULL,
    lead_id          INTEGER NOT NULL,
    thread_json      TEXT NOT NULL,
    latest_message_id TEXT,
    latest_message_at TEXT,
    fetched_at       TEXT NOT NULL,
    PRIMARY KEY (campaign_id, lead_id)
);

-- Durable idempotency ledger for reply webhooks. Smartlead and n8n may both
-- deliver the same event, and either may retry it; only the first delivery is
-- allowed to start classification/drafting.
CREATE TABLE IF NOT EXISTS webhook_events (
    event_key    TEXT PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    lead_id     INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    processed_at TEXT,
    status       TEXT NOT NULL DEFAULT 'received',
    last_error   TEXT
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_status
    ON webhook_events (status, received_at);

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
    -- Which client this template is for (a label from
    -- client_assets.available_clients(), e.g. "Mindaptive"/"AeroDefense"), or
    -- NULL/'' for a general template usable with any client. See app/main.py's
    -- /api/templates routes and the templates modal's client filter in app.js.
    client     TEXT,
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

-- What each {{slot}} in a campaign actually SAYS, in English.
--
-- The variant tables only ever knew a slot by its token (`Icebreaker1`), which
-- made every report unreadable: you cannot judge a CTA you have not read. The
-- text itself lives per-lead in the leads-export custom_fields, in whatever
-- language that lead was mailed in. This table caches one representative value
-- per token plus its English rendering — `text_en` is a copy of `text` when the
-- value was already English, and a Claude translation otherwise (which is why
-- it is cached: translating on every Overview load would be absurd).
--
-- `personalized` marks a slot whose value differs per lead (a per-lead
-- icebreaker) rather than a fixed block of copy. Those cannot be summarised by
-- one value, so `examples_json` carries a few and the UI says so.
CREATE TABLE IF NOT EXISTS campaign_slot_texts (
    campaign_id  INTEGER NOT NULL,
    token        TEXT NOT NULL,
    role         TEXT,
    text         TEXT,
    text_en      TEXT,
    lang         TEXT,
    personalized INTEGER NOT NULL DEFAULT 0,
    distinct_values INTEGER NOT NULL DEFAULT 0,
    examples_json TEXT,
    updated_at   TEXT,
    PRIMARY KEY (campaign_id, token)
);

-- One cached analysis per campaign. `stage` is progress text the dashboard
-- polls while the background thread works.
CREATE TABLE IF NOT EXISTS campaign_reports (
    campaign_id     INTEGER PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'running',  -- running|done|failed
    -- Only stored so the cross-campaign deliverability history can name the
    -- campaigns it is comparing; everything else here keys on the id alone.
    campaign_name   TEXT,
    stage           TEXT,
    started_at      TEXT,
    generated_at    TEXT,
    model           TEXT,
    stats_json      TEXT,
    report_md       TEXT,      -- legacy long-form variant essay, no longer written
    directives_md   TEXT,      -- the short Do / Don't / Next test brief
    conversation_md TEXT,
    error           TEXT
);

-- Who hosts a recipient's mailbox, keyed on the DOMAIN and shared by every
-- campaign, client and account — see app/mailbox_provider.py. This is the table
-- that makes the deliverability analysis nearly free after the first run: two
-- campaigns mailing German dental practices overlap heavily, and a domain
-- resolved for one is already answered for the other.
--
-- `mx_host` is the primary MX we classified from, kept so the provider table can
-- gain a name later and re-map the rows without re-querying DNS.
CREATE TABLE IF NOT EXISTS mailbox_domains (
    domain     TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    mx_host    TEXT,
    checked_at TEXT NOT NULL
);

-- One row per campaign per provider: the mix, and how that slice of the
-- audience actually performed. Written on every analysis and never deleted,
-- because the whole point is the record over time — "campaigns heavy on
-- Microsoft underperform" is a claim that can only be made across campaigns,
-- and the per-lead data it rests on is far too big to keep.
--
-- `_all` is a real provider key here, holding the campaign's own totals, so a
-- campaign's baseline travels with its slices instead of having to be
-- recomputed from a sends table that may since have been re-synced.
CREATE TABLE IF NOT EXISTS campaign_esp_stats (
    campaign_id   INTEGER NOT NULL,
    provider      TEXT NOT NULL,
    provider_group TEXT,
    leads         INTEGER NOT NULL DEFAULT 0,
    delivered     INTEGER NOT NULL DEFAULT 0,
    bounced       INTEGER NOT NULL DEFAULT 0,
    replies       INTEGER NOT NULL DEFAULT 0,
    positives     INTEGER NOT NULL DEFAULT 0,
    booked        INTEGER NOT NULL DEFAULT 0,
    unsubscribed  INTEGER NOT NULL DEFAULT 0,
    computed_at   TEXT NOT NULL,
    PRIMARY KEY (campaign_id, provider)
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

-- Small key/value store for settings Andrew changes from the dashboard rather
-- than from .env. Currently just `default_model` (see app/models_registry.py):
-- the .env ANTHROPIC_MODEL stays the fallback, this row overrides it, so
-- switching the default drafting model is a click and not a redeploy.
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_setting(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn, key: str, value: str | None) -> None:
    conn.execute(
        """INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (key, value, now_iso()),
    )


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
    if "attachments" not in draft_cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN attachments TEXT")
    if "send_error" not in draft_cols:
        conn.execute("ALTER TABLE drafts ADD COLUMN send_error TEXT")

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
        # How hot the lead is (app/lead_temperature.py). Existing rows backfill
        # to 'cold' and are re-rated the next time their thread is read, which
        # costs one cheap classifier call per lead who has actually replied.
        "temperature": "TEXT NOT NULL DEFAULT 'cold'",
        "temperature_reason": "TEXT",
        "temperature_message_id": "TEXT",
        "temperature_locked": "INTEGER NOT NULL DEFAULT 0",
        # Smartlead's own category name — see the schema comment above.
        "smartlead_category": "TEXT",
        # The message app/reply_classifier.py last judged — see the schema
        # comment above.
        "category_message_id": "TEXT",
    }
    for name, decl in inbox_columns.items():
        if name not in lead_cols:
            conn.execute(f"ALTER TABLE leads_state ADD COLUMN {name} {decl}")

    template_cols = {row["name"] for row in conn.execute("PRAGMA table_info(message_templates)")}
    if "client" not in template_cols:
        conn.execute("ALTER TABLE message_templates ADD COLUMN client TEXT")

    report_cols = {row["name"] for row in conn.execute("PRAGMA table_info(campaign_reports)")}
    if "directives_md" not in report_cols:
        conn.execute("ALTER TABLE campaign_reports ADD COLUMN directives_md TEXT")
    if "campaign_name" not in report_cols:
        conn.execute("ALTER TABLE campaign_reports ADD COLUMN campaign_name TEXT")


# ---- leads_state helpers ----

def get_lead_state(conn, lead_id: int, campaign_id: int):
    return conn.execute(
        "SELECT * FROM leads_state WHERE lead_id = ? AND campaign_id = ?",
        (lead_id, campaign_id),
    ).fetchone()


def find_lead_by_email(conn, email: str):
    """Every leads_state row for this email, case-insensitive.

    Used by the booking-confirmed webhook (app/webhook.py) to resolve a booked
    person's address back to a campaign_id/lead_id pair. This is the
    authoritative lookup — not the Interested Google Sheet
    (app/interested_sheet.py), which is a best-effort human-readable record and
    must never be what gates a real booking from being recorded."""
    email = (email or "").strip().lower()
    if not email:
        return []
    return conn.execute("SELECT * FROM leads_state WHERE lower(email) = ?", (email,)).fetchall()


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


# ---- live thread cache ----

def get_lead_thread(conn, lead_id: int, campaign_id: int):
    return conn.execute(
        "SELECT * FROM lead_threads WHERE lead_id = ? AND campaign_id = ?",
        (lead_id, campaign_id),
    ).fetchone()


def put_lead_thread(
    conn,
    lead_id: int,
    campaign_id: int,
    thread_json: str,
    latest_message_id: str | None,
    latest_message_at: str | None,
) -> None:
    conn.execute(
        """INSERT INTO lead_threads
             (campaign_id, lead_id, thread_json, latest_message_id,
              latest_message_at, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(campaign_id, lead_id) DO UPDATE SET
             thread_json = excluded.thread_json,
             latest_message_id = excluded.latest_message_id,
             latest_message_at = excluded.latest_message_at,
             fetched_at = excluded.fetched_at""",
        (
            campaign_id, lead_id, thread_json, latest_message_id,
            latest_message_at, now_iso(),
        ),
    )


# ---- reply-webhook idempotency ----

def claim_webhook_event(conn, event_key: str, campaign_id: int, lead_id: int) -> bool:
    """Return True for the first delivery, or a retry of a failed delivery."""
    cur = conn.execute(
        """INSERT INTO webhook_events
             (event_key, campaign_id, lead_id, received_at, status)
           VALUES (?, ?, ?, ?, 'received')
           ON CONFLICT(event_key) DO UPDATE SET
             status = 'received', last_error = NULL, processed_at = NULL
           WHERE webhook_events.status = 'failed'""",
        (event_key, campaign_id, lead_id, now_iso()),
    )
    return cur.rowcount == 1


def finish_webhook_event(
    conn, event_key: str, status: str = "processed", error: str | None = None
) -> None:
    conn.execute(
        """UPDATE webhook_events
           SET status = ?, processed_at = ?, last_error = ?
           WHERE event_key = ?""",
        (status, now_iso(), error, event_key),
    )


def mark_lead_booked(conn, lead_id: int, campaign_id: int) -> None:
    """Meeting booked (Smartlead's "Meeting-Booked" category seen on the lead):
    freeze all outreach for this lead — open drafts go stale, open candidates
    are dismissed, status becomes 'booked' (detector.decide treats it like
    stopped). booked_at is set once and never overwritten, so the first
    booking date survives later rescans.

    Recording the booking also **un-hides the lead**, and it has to. Archive and
    snooze are the only two things that keep a lead out of list_inbox once it is
    booked (a scheduled draft is the third, and the stale-ing above deals with
    it) — so a lead Andrew had archived or snoozed weeks ago, who then booked,
    stayed invisible under the Meeting-booked filter no matter how many times
    the scan ran. Two of the account's 36 bookings were exactly that. A booking
    is newer and better information than "not now" or "put this away".

    An archive is cleared only when it is *older than the booking*, i.e. stale
    information. Archiving a lead **after** the meeting is a deliberate act —
    cleanup once the call has happened — and clearing that on every pass would
    resurrect it every night with no way to make it stay gone. Phrasing the rule
    against the timestamps rather than "only on the transition" also repairs the
    rows that are already in this state: a lead booked before this existed keeps
    its stale archive forever under a transition-only rule, because it never
    transitions again.

    A snooze is always cleared while the lead is booked. Unlike an archive it
    says "not now" rather than "put this away", and a booking answers that; it
    also carries no timestamp of its own to age against."""
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
    existing = get_lead_state(conn, lead_id, campaign_id)
    booked_since = existing["booked_at"] if existing else None
    archived_at = existing["archived_at"] if existing else None
    fields: dict = {"status": "booked", "category": "booked"}
    # No booked_at yet => this is the booking being recorded now, and anything
    # hiding the lead predates it by definition.
    if archived_at and (not booked_since or archived_at < booked_since):
        fields.update(archived_at=None, archive_reason=None)
    if existing is None or existing["snooze_until"]:
        fields["snooze_until"] = None
    upsert_lead_state(conn, lead_id, campaign_id, **fields)
    conn.execute(
        """UPDATE leads_state SET booked_at = ?
           WHERE lead_id = ? AND campaign_id = ? AND booked_at IS NULL""",
        (now_iso(), lead_id, campaign_id),
    )


def mark_lead_replied(
    conn,
    lead_id: int,
    campaign_id: int,
    *,
    preview: str | None,
    received_at: str,
    **extra,
) -> None:
    """A lead has just written to us: make that visible in the inbox, now.

    Every path that learns about an inbound message goes through here — the
    webhook, and the reply-catch scan — because "visible" is more than one
    column and getting a subset of them right leaves the message effectively
    hidden. `category='reply'` is what puts the lead in list_inbox's red tier
    and paints the chip; `last_message_at` is what sorts it to the top of that
    tier; `last_message_preview` is what makes the row readable. The
    reply-catch scan used to write none of them — it went straight from
    spotting the reply to generating a draft — so a lead who answered kept the
    row, chip, preview and list position the last daily scan had given them.
    The message was in the database and nothing on screen said so, which is
    why "Rescan now" looked like the only way to see new mail: the scan is
    what rewrites these.

    `received_at` must be a UTC ISO string; it is compared as text, both by
    list_inbox's ordering and against archived_at below.

    Archive and snooze both hide a lead from list_inbox, and someone who has
    just written to us must not be hidden — the same call db.mark_lead_booked
    makes, for the same reason: this is newer information than either. The
    archive is cleared only when it predates the message, since archiving is a
    manual act here and archiving *after* reading a reply means "dealt with"
    and has to stick. Phrasing it against the timestamps rather than the
    transition is also what keeps it from flapping: a lead re-archived after
    the fact has archived_at > received_at on every later pass. A snooze says
    "not now", which the message itself answers.

    A booked lead keeps its category and status: those carry the green
    "Meeting booked ✅" badge and mark_lead_booked's freeze, and a reply after
    the meeting must not quietly un-book them. Their row still gets the new
    preview and timestamp."""
    existing = get_lead_state(conn, lead_id, campaign_id)

    fields: dict = dict(extra)
    fields.update(interested=1, last_message_kind="reply", last_message_at=received_at)
    if preview:
        fields["last_message_preview"] = preview[:200]

    if not (existing and existing["status"] == "booked"):
        fields["category"] = "reply"
        fields["status"] = "awaiting_reply"

    if existing and existing["archived_at"] and existing["archived_at"] < received_at:
        fields.update(archived_at=None, archive_reason=None)
    if existing and existing["snooze_until"]:
        fields["snooze_until"] = None

    upsert_lead_state(conn, lead_id, campaign_id, **fields)


def sort_replied_lead(
    conn,
    lead_id: int,
    campaign_id: int,
    label: str,
    message_id: str | None = None,
    smartlead_category: str | None = None,
) -> None:
    """Act on what app/reply_classifier.py decided an inbound reply was.

    `mark_lead_replied` puts every reply in the red "awaiting reply" tier,
    which is right until you know what the reply says — and wrong once you do.
    Left alone it filled the inbox with "Thank you for your email, we aim to
    respond within 24 hours", because a clinic's autoresponder is,
    structurally, a reply. So the classifier's verdict is applied here:

    - `interested` — leave it. It is a live conversation.
    - `auto_reply` — a machine answered. Stays visible, but as `auto_reply`,
      which drops it out of the red tier into the grey one, and `status`
      returns to 'active' so it is not counted as owing anyone a response.
      The scan's existing Auto-Reply handling then treats it normally.
    - `not_interested` — labelled and moved out of the red tier, and **that is
      all**. Not archived, not stopped, still in the inbox, one click from
      either.
    - `wrong_person` — labelled the same shallow way as not_interested (still
      in the inbox, one click away, `status` back to 'active'). What actually
      stops the follow-ups is the caller pushing this verdict to Smartlead's
      category with pause_lead=True (scheduler._push_category_to_smartlead) —
      once the lead's Smartlead category is no longer Interested/Auto-Reply/
      Meeting-Booked, run_daily_scan's own gate stops generating candidates
      for it. Deliberately not folded into not_interested's bucket: "wrong
      person" here means the mailbox itself is a dead end (nobody left to
      read it), not a verdict on the offer, so it must not share auto_reply's
      "keep chasing, they're coming back" treatment either.

    That last one is deliberately weaker than it first was. Archiving and
    stopping on this verdict was tried and reverted the same day: the cheap
    model is dependable at spotting an autoresponder — the bulk of the problem,
    136 of 177 leads in the first backfill — and unreliable exactly at the
    interested/not-interested boundary, which is the judgement a person should
    be making anyway. It filed a lead asking about minimum deal size, and one
    handing over their director's address, under "no". Prompt tuning traded
    those errors for others rather than removing them.

    So the split is by risk, not by confidence: the model does the boring,
    high-volume, harmless part, and anything that would end a conversation
    stays a human decision. Clearing the inbox is worth a lot; burying one real
    buyer costs more than the whole exercise saves.

    Passing `message_id` stamps `category_message_id`, which is what makes
    this verdict *sticky*: the caller checks that column before ever calling
    the classifier again, so the same message is judged once and this label
    then stands until either a genuinely new message arrives (a different id)
    or Andrew changes the status by hand — not until the next scan happens to
    run again on unchanged content. `smartlead_category` separately refreshes
    the informational column shown next to "Change status"; it never decides
    this label, only records what Smartlead itself currently says.

    Never touches a booked lead — that freeze outranks anything a reply says."""
    existing = get_lead_state(conn, lead_id, campaign_id)
    if existing and existing["status"] == "booked":
        return

    fields: dict = {"status": "active"}
    if message_id is not None:
        fields["category_message_id"] = message_id
    if smartlead_category is not None:
        fields["smartlead_category"] = smartlead_category
    if label == "auto_reply":
        upsert_lead_state(conn, lead_id, campaign_id, category="auto_reply", **fields)
    elif label == "not_interested":
        upsert_lead_state(conn, lead_id, campaign_id, category="not_interested", **fields)
    elif label == "wrong_person":
        upsert_lead_state(conn, lead_id, campaign_id, category="wrong_person", **fields)


def mark_category_judged(conn, lead_id: int, campaign_id: int, message_id: str) -> None:
    """Stamp `category_message_id` for a message the classifier judged
    `interested` — the counterpart to sort_replied_lead's stamping for
    auto_reply/not_interested. `category` itself is left alone: mark_lead_
    replied already has it right as 'reply', and this call exists purely so a
    later pass sees the same message id already on file and skips calling the
    classifier on it again."""
    upsert_lead_state(conn, lead_id, campaign_id, category_message_id=message_id)


def list_inbox(conn):
    """Every interested, non-stopped, non-archived, non-snoozed(-future) lead for
    the unified inbox.

    Ordering, outermost first: a 🔥 **very hot** lead — one who asked to meet or
    call (app/lead_temperature.py) — sits above everything else, because that is
    the one signal worth acting on before anything else in the list and it must
    not be buried under a dozen leads whose only claim is that they replied more
    recently. A booked lead is excluded from that promotion: the meeting is the
    outcome, so there is nothing left to chase.

    Within that, the tiers are as before: a snooze whose date has arrived jumps
    to the top (that's the point of snoozing — surface it prominently once due),
    then awaiting-our-reply (red), then follow-up-due (amber), then the rest;
    within a tier, most recent activity first.

    A lead whose draft is already *scheduled* is handled — it belongs to the
    Scheduled tab, not here. It used to sit in both, still wearing its amber
    "Follow-up due" chip: the chip is `category`, which the scan recomputes off
    the thread, and a scheduled email hasn't been sent yet, so the thread is
    unchanged and the lead is still genuinely "due" as far as the detector can
    see. The scan's `has_open` check knows about scheduled drafts but runs
    after the category is written, and only suppresses a *second* draft.

    The `category` escape hatch is deliberate: if the lead replies while a
    follow-up sits scheduled, the scan stamps 'reply' (or 'auto_reply') and the
    lead comes back into the inbox immediately, rather than staying hidden
    until the scheduled time arrives and `_send_due_draft` aborts the send. A
    lead who just answered must never be invisible.

    Only 'scheduled' hides a lead — a 'pending' draft is one waiting for
    review, which is exactly what the inbox is for."""
    now = now_iso()
    return conn.execute(
        """SELECT * FROM leads_state
           WHERE interested = 1 AND status != 'stopped'
             AND archived_at IS NULL
             AND (snooze_until IS NULL OR snooze_until <= ?)
             AND (
               category IN ('reply', 'auto_reply')
               OR NOT EXISTS (
                 SELECT 1 FROM drafts d
                 WHERE d.lead_id = leads_state.lead_id
                   AND d.campaign_id = leads_state.campaign_id
                   AND d.status = 'scheduled'
               )
             )
           ORDER BY
             CASE WHEN temperature = 'hot' AND status != 'booked' THEN 0 ELSE 1 END,
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
    first — backs the dashboard's "Scheduled" tab.

    campaign_name is joined in rather than stored on the draft: every list in
    the dashboard shows which campaign a lead belongs to, and the scan keeps
    that name current on leads_state, so reading it from there means a campaign
    renamed in Smartlead doesn't leave old drafts labelled with the old name."""
    return conn.execute(
        """SELECT d.*, ls.campaign_name
           FROM drafts d
           LEFT JOIN leads_state ls
             ON ls.lead_id = d.lead_id AND ls.campaign_id = d.campaign_id
           WHERE d.status = 'scheduled'
           ORDER BY d.scheduled_at ASC"""
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
           AND status IN ('pending', 'scheduled', 'sending') LIMIT 1""",
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


def retire_other_open_drafts(conn, lead_id: int, campaign_id: int, keep_draft_id: int) -> int:
    """Mark every other open draft for this lead 'skipped', keeping one.

    Called right after a regeneration stores its replacement, so the old draft
    survives a generation that fails instead of being discarded before the
    attempt (see main.api_generate). Returns how many were retired. 'scheduled'
    is included deliberately: a regenerate supersedes a queued send, and leaving
    both open would let get_open_draft pick either one."""
    cur = conn.execute(
        """UPDATE drafts SET status = 'skipped'
           WHERE lead_id = ? AND campaign_id = ? AND id != ?
             AND status IN ('pending', 'scheduled')""",
        (lead_id, campaign_id, keep_draft_id),
    )
    return cur.rowcount


def get_open_draft(conn, lead_id: int, campaign_id: int):
    """The current editable/in-flight draft for a lead, if any."""
    return conn.execute(
        """SELECT * FROM drafts WHERE lead_id = ? AND campaign_id = ?
           AND status IN ('pending', 'scheduled', 'sending')
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


def create_message_template(
    conn, label: str, text: str, position: int | None = None, client: str | None = None
) -> int:
    if position is None:
        row = conn.execute("SELECT MAX(position) AS m FROM message_templates").fetchone()
        position = ((row["m"] if row and row["m"] is not None else -1)) + 1
    now = now_iso()
    cur = conn.execute(
        """INSERT INTO message_templates (label, text, position, client, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (label, text, position, client or None, now, now),
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


def upsert_campaign_slot_texts(conn, campaign_id: int, rows: list[dict]) -> int:
    """Cache what each slot says. Upsert rather than replace: `text_en` may hold a
    paid translation, and a re-sync that finds the same source text must not
    throw it away — the translation step re-fills only rows where it is NULL."""
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO campaign_slot_texts (
               campaign_id, token, role, text, text_en, lang, personalized,
               distinct_values, examples_json, updated_at
           ) VALUES (
               :campaign_id, :token, :role, :text, :text_en, :lang, :personalized,
               :distinct_values, :examples_json, :updated_at
           )
           ON CONFLICT(campaign_id, token) DO UPDATE SET
               role            = excluded.role,
               text            = excluded.text,
               -- keep a cached translation unless the source text itself moved
               text_en         = CASE
                                   WHEN campaign_slot_texts.text IS excluded.text
                                     THEN COALESCE(campaign_slot_texts.text_en, excluded.text_en)
                                   ELSE excluded.text_en
                                 END,
               lang            = excluded.lang,
               personalized    = excluded.personalized,
               distinct_values = excluded.distinct_values,
               examples_json   = excluded.examples_json,
               updated_at      = excluded.updated_at""",
        rows,
    )
    return len(rows)


def list_campaign_slot_texts(conn, campaign_id: int):
    return conn.execute(
        "SELECT * FROM campaign_slot_texts WHERE campaign_id = ?", (campaign_id,)
    ).fetchall()


def set_campaign_slot_translation(conn, campaign_id: int, token: str, text_en: str) -> None:
    conn.execute(
        "UPDATE campaign_slot_texts SET text_en = ? WHERE campaign_id = ? AND token = ?",
        (text_en, campaign_id, token),
    )


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


# ---- mailbox provider helpers (see app/mailbox_provider.py) ----

def get_mailbox_domains(conn, domains: list[str]):
    """Cached provider verdicts for the domains given. Chunked because SQLite
    caps a statement at 999 parameters by default and a campaign asks about
    several thousand domains at once."""
    rows = []
    for start in range(0, len(domains), 500):
        chunk = domains[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            conn.execute(
                f"SELECT * FROM mailbox_domains WHERE domain IN ({placeholders})", chunk
            ).fetchall()
        )
    return rows


def upsert_mailbox_domains(conn, rows: list[tuple[str, str, str | None]]) -> int:
    """rows are (domain, provider, mx_host) — the shape mailbox_provider._lookup
    returns, so the caller never builds a dict just to take it apart again."""
    checked_at = now_iso()
    conn.executemany(
        """INSERT INTO mailbox_domains (domain, provider, mx_host, checked_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(domain) DO UPDATE SET
               provider = excluded.provider,
               mx_host = excluded.mx_host,
               checked_at = excluded.checked_at""",
        [(domain, provider, mx_host, checked_at) for domain, provider, mx_host in rows],
    )
    return len(rows)


def replace_campaign_esp_stats(conn, campaign_id: int, rows: list[dict]) -> int:
    """Rewrite one campaign's provider breakdown. A delete-then-insert rather
    than an upsert so a provider that no longer appears (the table gained a name
    for what used to be `other`) doesn't linger as a stale row."""
    conn.execute("DELETE FROM campaign_esp_stats WHERE campaign_id = ?", (campaign_id,))
    computed_at = now_iso()
    conn.executemany(
        """INSERT INTO campaign_esp_stats (
               campaign_id, provider, provider_group, leads, delivered, bounced,
               replies, positives, booked, unsubscribed, computed_at)
           VALUES (:campaign_id, :provider, :provider_group, :leads, :delivered,
                   :bounced, :replies, :positives, :booked, :unsubscribed, :computed_at)""",
        [{**row, "campaign_id": campaign_id, "computed_at": computed_at} for row in rows],
    )
    return len(rows)


def list_campaign_esp_stats(conn, campaign_id: int | None = None):
    """One campaign's breakdown, or every campaign's — the second form is the
    history the cross-campaign pattern is read from. The campaign name is joined
    in from campaign_reports so the history can name what it compares."""
    sql = """SELECT s.*, r.campaign_name
             FROM campaign_esp_stats s
             LEFT JOIN campaign_reports r ON r.campaign_id = s.campaign_id"""
    params: tuple = ()
    if campaign_id is not None:
        sql += " WHERE s.campaign_id = ?"
        params = (campaign_id,)
    return conn.execute(sql, params).fetchall()


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
