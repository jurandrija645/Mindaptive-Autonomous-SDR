"""Mark the Slack notification for a lead's reply once it has been dealt with.

n8n posts every relevant reply to the client's Slack channel (the "Ekipica
dosla je poruka od ..." message) and then calls POST /webhooks/slack-posted
with the message's channel and ts plus the lead it belongs to. This module
keeps that link and closes the loop on the same message:

  ✅  a reply went out, from the dashboard, automatically, or straight from
      Smartlead's inbox (found by re-reading the thread)
  📅  the lead booked
  ⚠️  the bot held its draft for a person (refund, complaint, clinical
      question, anything the One Body review would not approve)

Each mark also leaves one line in the message's thread saying what happened.

The send path and the draft generator only write a row here. Every Slack call
happens in run_sync, on the scheduler, so a Slack outage can never block or
fail a send. Without SLACK_BOT_TOKEN nothing is posted, but links and states
are still recorded and go out once a token is set.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from zoneinfo import ZoneInfo

import httpx

from app import db
from app.config import settings

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS slack_posts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    channel          TEXT NOT NULL,
    ts               TEXT NOT NULL,
    campaign_id      INTEGER,
    lead_id          INTEGER,
    email            TEXT,
    posted_at        TEXT NOT NULL,
    answered_at      TEXT,
    answered_note    TEXT,
    answered_pushed  INTEGER NOT NULL DEFAULT 0,
    held_note        TEXT,
    held_pushed      INTEGER NOT NULL DEFAULT 0,
    booked_pushed    INTEGER NOT NULL DEFAULT 0,
    last_checked_at  TEXT,
    UNIQUE (channel, ts)
);
CREATE INDEX IF NOT EXISTS idx_slack_posts_lead ON slack_posts (lead_id);
CREATE INDEX IF NOT EXISTS idx_slack_posts_email ON slack_posts (email);
"""

LONDON = ZoneInfo("Europe/London")
# How long after the Slack post we keep checking Smartlead for a reply sent
# outside the dashboard. Past that a conversation is either answered or dead.
WATCH_DAYS = 14
RECHECK_MINUTES = 10
_EMOJI = {"answered": "white_check_mark", "booked": "date", "held": "warning"}


def ensure_table(conn) -> None:
    conn.executescript(SCHEMA)


def enabled() -> bool:
    return bool(settings.slack_bot_token)


# ---- writes (no network) ----

def record_post(conn, *, channel: str, ts: str, campaign_id=None, lead_id=None,
                email: str = "", posted_at: str | None = None) -> bool:
    """Link one Slack message to a lead. Repeats of the same message are ignored."""
    channel, ts = (channel or "").strip(), (ts or "").strip()
    if not channel or not ts:
        raise ValueError("channel and ts are required")
    cur = conn.execute(
        """INSERT OR IGNORE INTO slack_posts (channel, ts, campaign_id, lead_id, email, posted_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (channel, ts, _int(campaign_id), _int(lead_id), (email or "").strip().lower() or None,
         posted_at or db.now_iso()),
    )
    return cur.rowcount > 0


def _open_posts(conn, lead_id, email):
    email = (email or "").strip().lower()
    return conn.execute(
        """SELECT * FROM slack_posts
           WHERE answered_at IS NULL AND (lead_id = ? OR (? != '' AND email = ?))""",
        (_int(lead_id), email, email),
    ).fetchall()


def mark_answered(conn, draft: dict, sent_at: str, *, sender: str = "") -> int:
    """Called right after a draft was sent. Closes every open Slack post for
    this lead that went up before the send."""
    if (draft.get("kind") or "") == "sequence":
        return 0
    how = "automatski" if draft.get("kind") == "auto_response" else "iz dashboarda"
    preview = _first_words(draft.get("body_html") or "", 160)
    who = f" ({sender})" if sender else ""
    note = f"Odgovoreno {how}{who}, {_london(sent_at)}: \"{preview}\""
    n = 0
    for post in _open_posts(conn, draft.get("lead_id"), draft.get("lead_email")):
        if post["posted_at"] <= sent_at:
            conn.execute("UPDATE slack_posts SET answered_at = ?, answered_note = ? WHERE id = ?",
                         (sent_at, note, post["id"]))
            n += 1
    return n


def mark_held(conn, lead_id, email, reason: str) -> int:
    """Called when the One Body review holds a newly generated draft."""
    note = "Treba čovjek: " + (reason or "bot nije siguran u odgovor").strip()[:300]
    n = 0
    for post in _open_posts(conn, lead_id, email):
        if post["held_note"] != note:
            conn.execute("UPDATE slack_posts SET held_note = ?, held_pushed = 0 WHERE id = ?",
                         (note, post["id"]))
            n += 1
    return n


# ---- Slack ----

def _slack(method: str, payload: dict) -> dict:
    resp = httpx.post(
        f"https://slack.com/api/{method}",
        headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
        json=payload, timeout=20,
    )
    data = resp.json()
    if not data.get("ok") and data.get("error") not in ("already_reacted",):
        raise RuntimeError(f"Slack {method}: {data.get('error')}")
    return data


def _push(post, emoji_key: str, text: str) -> None:
    _slack("reactions.add", {"channel": post["channel"], "timestamp": post["ts"],
                             "name": _EMOJI[emoji_key]})
    _slack("chat.postMessage", {"channel": post["channel"], "thread_ts": post["ts"],
                                "text": text, "unfurl_links": False})


# ---- scheduler job ----

def run_sync() -> None:
    try:
        _detect_outside_replies()
    except Exception:
        log.exception("slack sync: checking Smartlead for replies failed")
    if not enabled():
        return
    with db.db_session() as conn:
        booked = conn.execute(
            """SELECT p.* FROM slack_posts p WHERE p.booked_pushed = 0 AND EXISTS (
                   SELECT 1 FROM leads_state s WHERE s.status = 'booked'
                   AND (s.lead_id = p.lead_id OR (p.email IS NOT NULL AND lower(s.email) = p.email)))"""
        ).fetchall()
        answered = conn.execute(
            "SELECT * FROM slack_posts WHERE answered_at IS NOT NULL AND answered_pushed = 0"
        ).fetchall()
        held = conn.execute(
            """SELECT * FROM slack_posts WHERE held_note IS NOT NULL AND held_pushed = 0
               AND answered_at IS NULL"""
        ).fetchall()
    for post in booked:
        _try(post, "booked", "Bukirano.", "booked_pushed")
    for post in answered:
        _try(post, "answered", post["answered_note"], "answered_pushed")
    for post in held:
        _try(post, "held", post["held_note"], "held_pushed")


def _try(post, key: str, text: str, column: str) -> None:
    try:
        _push(post, key, text)
    except Exception as exc:
        log.warning("slack sync: could not mark %s/%s as %s: %s", post["channel"], post["ts"], key, exc)
        return
    with db.db_session() as conn:
        conn.execute(f"UPDATE slack_posts SET {column} = 1 WHERE id = ?", (post["id"],))


def _detect_outside_replies() -> None:
    """A reply sent straight from Smartlead never passes through the send path,
    so re-read the thread of every open post now and then."""
    from app import pipeline  # imports db; deferred to avoid a cycle
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=WATCH_DAYS)).isoformat()
    stale = (now - timedelta(minutes=RECHECK_MINUTES)).isoformat()
    with db.db_session() as conn:
        posts = conn.execute(
            """SELECT * FROM slack_posts WHERE answered_at IS NULL AND posted_at >= ?
               AND campaign_id IS NOT NULL AND lead_id IS NOT NULL
               AND (last_checked_at IS NULL OR last_checked_at < ?) LIMIT 30""",
            (since, stale),
        ).fetchall()
    for post in posts:
        try:
            thread = pipeline.fetch_normalized_thread(post["campaign_id"], post["lead_id"])
        except Exception as exc:
            log.warning("slack sync: thread fetch failed for lead %s: %s", post["lead_id"], exc)
            thread = None
        posted = _parse(post["posted_at"])
        ours = [m for m in (thread or []) if m.kind == "sent" and posted and m.timestamp > posted]
        with db.db_session() as conn:
            conn.execute("UPDATE slack_posts SET last_checked_at = ? WHERE id = ?", (db.now_iso(), post["id"]))
            if ours:
                m = ours[-1]
                note = (f"Odgovoreno direktno iz Smartleada, {_london(m.timestamp.isoformat())}: "
                        f"\"{_first_words(m.body, 160)}\"")
                conn.execute(
                    "UPDATE slack_posts SET answered_at = ?, answered_note = ? WHERE id = ? AND answered_at IS NULL",
                    (m.timestamp.isoformat(), note, post["id"]),
                )


# ---- helpers ----

def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse(raw):
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _london(raw) -> str:
    dt = _parse(raw)
    return dt.astimezone(LONDON).strftime("%d.%m. %H:%M") if dt else ""


def _first_words(html: str, limit: int) -> str:
    text = re.sub(r"<(br|/p|/div)[^>]*>", " ", html or "", flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.split(r"On .{5,120}?wrote:", text)[0]
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"
