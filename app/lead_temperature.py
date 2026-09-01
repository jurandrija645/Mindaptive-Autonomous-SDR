"""How hot a lead is — ❄️ cold / 🌤 warm / 🔥 very hot — and why.

This is a **different question** from the two statuses the app already carries,
which is the whole reason it exists as its own column:

- `leads_state.category` (reply / followup / waiting / booked, or a Smartlead
  category mirrored 1:1 — auto_reply, not_interested, do_not_contact, a
  custom one, whatever) says what the *thread* needs next, or that Smartlead
  itself has already answered that question. It is recomputed from the
  message history — or from Smartlead's own category — on every scan.
- `leads_state.smartlead_category` is Smartlead's own raw category name
  (Interested, Not Interested, Meeting-Booked…), kept for display even where
  `category` above shows an app-only sub-state Smartlead has no concept of.

Neither answers the question Andrew actually asks of the inbox each morning:
**who wants to talk to us.** A lead who wrote "can we jump on a call Thursday?"
and a lead who wrote "please send more info" are both `reply` + `Interested`,
and they are not remotely the same lead.

    🔥 hot   — they asked to meet, call, get a demo, or to be contacted. The
               strongest signal there is.
    🌤 warm  — a real person engaging, but not asking to talk yet: questions,
               "send me more info", an objection, "check back in Q3".
    ❄️ cold  — no reply at all, or nothing but an autoresponder / rejection.

Two things follow from a hot rating, and they are the point of it:

1. The lead sorts **above every other tier** in the inbox (`db.list_inbox`),
   including a due snooze and an unanswered reply.
2. Their follow-up cadence collapses to `HOT_FOLLOWUP_WAIT_HOURS` (24h) instead
   of the `FOLLOWUP_WAIT_DAYS` list — see `detector.decide`. Somebody who asked
   for a call on Monday is not a lead you chase again on Thursday.

Three rules this keeps:

- **Never cools a lead down on its own.** The rating only ever moves up.
  An out-of-office from someone who asked for a call last week does not undo
  last week, and a lead who has gone quiet is exactly the one worth keeping in
  sight. Andrew can always cool one by hand, which locks it (see `record` /
  `temperature_locked`).
- **One model call per inbound message, at most.** The message the rating was
  drawn from is stored (`temperature_message_id`), so the 5-minute reply-catch
  pass and the nightly scan re-read the same thread for free. A lead already
  rated hot is never re-classified at all.
- **It never gates visibility**, exactly like `reply_classifier`. It decides
  ordering and cadence. Being wrong costs a lead sitting one tier lower than
  they deserve, never a lead you can't see.
"""

import logging
import re
from dataclasses import dataclass

from app import db, llm, models_registry
from app.email_clean import to_plain_text

log = logging.getLogger("lead_temperature")

COLD = "cold"
WARM = "warm"
HOT = "hot"
VALUES = (COLD, WARM, HOT)

# Rank, for the "never cool down on its own" comparison below.
ORDER = {COLD: 0, WARM: 1, HOT: 2}

LABEL = {COLD: "❄️ Cold", WARM: "🌤 Warm", HOT: "🔥 Very hot"}

# The lead's own words are the whole input; a quoted history is noise and tokens
# (to_plain_text already drops the quoted part).
_MAX_CHARS = 4000

# How many of the lead's own messages to rate at once. Not one, because the ask
# to talk is often not the newest thing they said: "can we jump on a call?" then
# "any time Thursday works" then "thanks!" would rate the thank-you and call the
# lead warm. Reading their last few messages together and taking the strongest
# signal in them is what makes the first rating of an existing conversation
# right, which matters most on the leads already in the inbox today.
_MAX_MESSAGES = 3

_SYSTEM = (
    "You are a sales-signal classifier. You read one email that a prospect sent "
    "us and answer with exactly one word."
)

_USER = """Below are the last few messages one person sent us, oldest first. \
Rate the STRONGEST buying signal anywhere in them. Answer with ONE word: HOT, \
WARM or COLD.

**HOT** — the strongest signal there is. The person:
- asks to meet, talk, call, or see a demo ("let's set up a call", "can we talk \
next week", "send me some times", "when are you free?", "give me a ring")
- accepts a meeting, or answers with their availability
- asks us to contact them, or gives a phone number so we can
- names the person who books such calls AND asks us to talk to them

**WARM** — a real person engaging, but not asking to talk yet:
- questions about the product, the price, how it works
- "send me more information", "email me a proposal", asks for a document
- an objection, a "not right now", "check back in Q3"
- passes us to a colleague with no ask to talk

**COLD** — no human intent at all:
- out-of-office / autoresponder / "we will get back to you within X days"
- unsubscribe, "remove me", a flat rejection
- wrong person with no redirect, or a bounce notice

An ask to talk counts even if it wasn't the last thing they said — someone who \
asked for a call and then wrote "thanks" is still HOT.

The messages may be in any language — rate what they mean, not what language \
they are in. Wanting a meeting is HOT in every language.

**MANDATORY:** your output must be only one word: HOT, WARM or COLD. No \
explanation, no punctuation.

**MESSAGES:**
{text}"""

# The offline fallback, used only when the model can't be reached or answers
# something unparseable. English-only and deliberately narrow: these are
# phrasings that mean a meeting and nothing else, because the cost of a false
# 🔥 is a lead pinned to the top of the inbox that doesn't belong there.
_MEETING_ASK = re.compile(
    r"""
    \b(?:book|schedule|set\s?up|arrange|organi[sz]e)\s+(?:a\s+|the\s+)?
        (?:quick\s+|short\s+|brief\s+)?(?:call|meeting|chat|demo|zoom|time)
  | \blet'?s\s+(?:talk|chat|connect|meet|speak|jump\s+on)
  | \b(?:send|share)\s+(?:me\s+|us\s+)?(?:some\s+|a\s+few\s+|your\s+)?
        (?:times|time\s?slots|slots|availability|calendar)
  | \bwhen\s+are\s+you\s+(?:free|available)
  | \b(?:happy|glad|keen|open|available)\s+to\s+(?:talk|chat|meet|connect|speak)
  | \bcall\s+me\b | \bgive\s+me\s+a\s+call\b
  | \bcalendly\b | \bcal\.com\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class Reading:
    """A rating to store. `reason` is None when the rating didn't change and only
    the "we have judged this message" marker needs writing — that keeps the
    existing explanation rather than replacing it with a weaker one."""

    temperature: str
    reason: str | None
    message_id: str


def label(temperature: str | None) -> str:
    return LABEL.get(temperature or COLD, LABEL[COLD])


def is_hot(state) -> bool:
    """True when this lead is rated 🔥 — the short follow-up cadence and the top
    of the inbox both key off exactly this."""
    return current(state) == HOT


def current(state) -> str:
    """The stored rating of a `leads_state` row (or dict), defaulting to cold."""
    return _col(state, "temperature", COLD) or COLD


def fields(reading: Reading | None) -> dict:
    """`Reading` as leads_state columns, ready to merge into an upsert. `reason`
    is omitted when None so an unchanged rating keeps the explanation it had —
    upsert_lead_state writes every field it is handed, including None."""
    if reading is None:
        return {}
    out = {
        "temperature": reading.temperature,
        "temperature_message_id": reading.message_id,
    }
    if reading.reason is not None:
        out["temperature_reason"] = reading.reason
    return out


def read(thread, state=None) -> Reading | None:
    """Rate this lead from their own most recent message, or return None when
    there is nothing to write.

    May call a model, so it must **never** be called with a database
    transaction open (see the note in CLAUDE.md: an open SQLite write
    transaction is an exclusive writer lock for the whole process).

    Returns None — meaning "leave the row alone, and spend nothing" — when:
      * Andrew has set the rating by hand (`temperature_locked`)
      * the lead is already 🔥 (the rating is sticky upwards; nothing to re-check)
      * this exact message has already been judged (`temperature_message_id`)
      * the lead has never written to us, so there is nothing to read. Note this
        deliberately does *not* demote an already-warm lead: a thread that comes
        back short is far more likely to be a truncated fetch than an unsent
        message.
    """
    if _col(state, "temperature_locked", 0):
        return None

    rated = current(state)
    if rated == HOT:
        return None

    last_in = last_inbound(thread)
    if last_in is None:
        return None

    # Falls back to the timestamp when Smartlead gives a message no id of its
    # own: this column is only ever a cache key, and an empty one would read as
    # "never judged" and pay for the same verdict on every single pass.
    key = last_in.message_id or last_in.timestamp.isoformat()
    if _col(state, "temperature_message_id") == key:
        return None

    verdict, reason = classify(recent_inbound_text(thread))
    if ORDER[verdict] <= ORDER[rated]:
        # No promotion. Still record the message as judged, so this doesn't pay
        # to reach the same conclusion on every pass.
        return Reading(rated, None, key)
    return Reading(verdict, reason, key)


def record(lead_id: int, campaign_id: int, thread) -> Reading | None:
    """`read` plus the write, for the two paths that spot a reply and have no
    upsert of their own to fold it into (the webhook and the reply-catch pass).

    Each database session is opened and closed around the model call rather than
    across it, for the reason in `read`'s docstring."""
    with db.db_session() as conn:
        state = db.get_lead_state(conn, lead_id, campaign_id)

    try:
        reading = read(thread, state)
    except Exception:
        # A rating is a nice-to-have on top of a reply that has already been
        # recorded and shown. Never let it cost the caller its draft.
        log.exception("temperature read failed for lead %s", lead_id)
        return None
    if reading is None:
        return None

    with db.db_session() as conn:
        db.upsert_lead_state(conn, lead_id, campaign_id, **fields(reading))
    if reading.temperature == HOT and current(state) != HOT:
        # Plain text, no emoji: a Windows dev console encodes log records as
        # cp1252 and would turn this line into a logging error.
        log.info("lead %s rated VERY HOT: %s", lead_id, reading.reason)
    return reading


def recent_inbound_text(thread, limit: int = _MAX_MESSAGES) -> str:
    """The lead's own last few messages as one blob, oldest first — what gets
    rated. Trimmed from the *front* when it's too long, so the newest message is
    always the one that survives the cap."""
    inbound = [m for m in (thread or []) if m.kind == "reply"][-limit:]
    parts = []
    for i, msg in enumerate(inbound, 1):
        text = to_plain_text(msg.body or "").strip()
        if text:
            parts.append(f"--- message {i} of {len(inbound)} ---\n{text}")
    return "\n\n".join(parts)[-_MAX_CHARS:]


def classify(message: str) -> tuple[str, str]:
    """`(temperature, reason)` for a blob of the lead's own words.

    Runs on ROLE_CLASSIFY — the same cheap model as `reply_classifier`, and for
    the same reason: one word in, one word out, on every reply.

    Falls back to a narrow English keyword match when the model is unavailable
    or unparseable, and to warm otherwise. Warm is the honest failure: they did
    write to us, so cold is wrong, and pinning an unrated lead to the top of the
    inbox would make 🔥 mean nothing."""
    text = to_plain_text(message or "").strip()
    if not text:
        return WARM, "empty message — nothing to rate"

    try:
        # 512 tokens for a one-word answer, for the reason spelled out in
        # reply_classifier.classify: a reasoning model bills its thinking
        # against this same budget, so a tight cap truncates the verdict rather
        # than shortening it.
        verdict, _ = llm.complete_for(
            models_registry.ROLE_CLASSIFY,
            _SYSTEM,
            _USER.format(text=text[:_MAX_CHARS]),
            max_tokens=512,
        )
    except Exception as exc:
        log.warning("temperature classifier failed (%s) — falling back to keywords", exc)
        return _keyword_reading(text, f"classifier unavailable ({exc.__class__.__name__})")

    normalized = verdict.strip().upper()
    # Whichever word appears first wins, so a model that ignores the one-word
    # instruction and explains itself ("HOT — they asked for a call, not WARM")
    # is still read correctly.
    hits = sorted(
        (normalized.find(word), temp)
        for word, temp in (("HOT", HOT), ("WARM", WARM), ("COLD", COLD))
        if word in normalized
    )
    if hits:
        temp = hits[0][1]
        return temp, REASONS[temp]

    log.warning("temperature classifier returned %r — falling back to keywords", verdict[:100])
    return _keyword_reading(text, f"unrecognized verdict ({verdict[:40]!r})")


REASONS = {
    HOT: "asked to talk — meeting, call or demo",
    WARM: "replied and engaged, but hasn't asked to talk",
    COLD: "auto-reply, rejection or no real intent",
}


def _keyword_reading(text: str, why: str) -> tuple[str, str]:
    if _MEETING_ASK.search(text):
        return HOT, f"asked to talk (matched on wording — {why})"
    return WARM, f"replied to us ({why})"


def last_inbound(thread):
    """The lead's own most recent message, or None if they've never written."""
    for msg in reversed(thread or []):
        if msg.kind == "reply":
            return msg
    return None


def _col(state, name: str, default=None):
    """One column out of a sqlite3.Row, a dict, or None — the three shapes the
    callers have. A Row raises IndexError for a column that doesn't exist, which
    is what a database that hasn't been migrated yet looks like."""
    if state is None:
        return default
    try:
        value = state[name]
    except (KeyError, IndexError):
        return default
    return default if value is None else value
