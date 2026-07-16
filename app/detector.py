"""Pure decision logic for what to do with a lead, given their message thread.

Kept free of network/DB calls so it can be reasoned about and tested in isolation.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from app.config import settings

SENT_TYPES = {"SENT", "SENT_EMAIL", "EMAIL_SENT", "SEQUENCE_SENT"}
REPLY_TYPES = {"REPLY", "EMAIL_REPLY", "REPLY_EMAIL"}


class Action(str, Enum):
    FOLLOWUP = "followup"
    REPLY = "reply"
    NONE = "none"


@dataclass
class NormalizedMessage:
    kind: str  # "sent" | "reply" | "unknown"
    timestamp: datetime
    message_id: str  # RFC822 Message-ID header value, e.g. "<abc@domain.com>"
    body: str
    from_email: str = ""
    stats_id: str = ""  # Smartlead's own internal id — required by reply-email-thread as email_stats_id


@dataclass
class Decision:
    action: Action
    reason: str


def _parse_timestamp(raw: str | None) -> datetime:
    if not raw:
        # A message Smartlead hasn't finished processing yet (e.g. one we
        # just sent) can briefly come back with no time field at all —
        # treat it as having just happened rather than crashing.
        return datetime.now(timezone.utc)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_message(msg: dict) -> NormalizedMessage:
    raw_type = (
        msg.get("type") or msg.get("message_type") or msg.get("event_type") or ""
    ).upper()
    if raw_type in SENT_TYPES or "SENT" in raw_type:
        kind = "sent"
    elif raw_type in REPLY_TYPES or "REPLY" in raw_type:
        kind = "reply"
    else:
        kind = "unknown"

    timestamp_raw = (
        msg.get("time")
        or msg.get("sent_time")
        or msg.get("created_at")
        or msg.get("timestamp")
    )
    message_id = str(
        msg.get("message_id") or msg.get("stats_id") or msg.get("id") or ""
    )
    stats_id = str(msg.get("stats_id") or "")
    body = msg.get("email_body") or msg.get("body") or msg.get("message") or ""
    from_email = msg.get("from") or msg.get("from_email") or ""

    return NormalizedMessage(
        kind=kind,
        timestamp=_parse_timestamp(timestamp_raw),
        message_id=message_id,
        body=body,
        from_email=from_email,
        stats_id=stats_id,
    )


def last_sender_email(thread: list[NormalizedMessage]) -> str:
    """The mailbox that owns this conversation — the from-address of our most
    recent SENT message, used to pick which persona's signature to append."""
    for msg in reversed(thread):
        if msg.kind == "sent" and msg.from_email:
            return msg.from_email
    return ""


def normalize_thread(raw_thread: list[dict]) -> list[NormalizedMessage]:
    messages = [normalize_message(m) for m in raw_thread]
    return sorted(messages, key=lambda m: m.timestamp)


def category_matches(lead: dict, category_id: int | None) -> bool:
    return category_id is not None and lead.get("lead_category_id") == category_id


def is_interested(lead: dict, interested_category_id: int) -> bool:
    return category_matches(lead, interested_category_id)


def decide(
    thread: list[NormalizedMessage],
    followup_count: int,
    lead_status: str,
    now: datetime | None = None,
) -> Decision:
    now = now or datetime.now(timezone.utc)

    if lead_status in ("stopped", "blacklisted"):
        return Decision(Action.NONE, f"lead status is {lead_status}")

    if not thread:
        return Decision(Action.NONE, "no message history yet")

    last = thread[-1]

    if last.kind == "reply":
        return Decision(Action.REPLY, "lead's message is the most recent — needs a response")

    if last.kind != "sent":
        return Decision(Action.NONE, "last message type is unrecognized, skipping to be safe")

    if followup_count >= settings.max_followups:
        return Decision(Action.NONE, f"already sent {followup_count} follow-ups, capped")

    age = now - last.timestamp
    wait = timedelta(days=settings.followup_wait_days)
    if age < wait:
        return Decision(
            Action.NONE,
            f"only {age.days}d since our last message, waiting for {settings.followup_wait_days}d",
        )

    return Decision(
        Action.FOLLOWUP,
        f"{age.days}d since our last message with no reply, follow-up #{followup_count + 1}",
    )
