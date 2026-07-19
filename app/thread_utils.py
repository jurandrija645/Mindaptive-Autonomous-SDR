from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from app.detector import NormalizedMessage
from app.email_clean import to_plain_text


def render_thread_text(thread: list[NormalizedMessage]) -> str:
    """Quote-stripped, tag-free thread text for the Claude prompt — msg.body
    is the raw email HTML including every prior message quoted below each
    reply, so building this from the raw bodies directly makes the prompt
    grow roughly quadratically with thread length. Confirmed on a real
    31-message thread: raw bodies -> ~44k tokens of thread text alone vs
    ~9k tokens quote-stripped, on top of the ~12.5k-token system prompt sent
    on every turn of every generate/regenerate call."""
    parts = []
    for msg in thread:
        speaker = "US (Mindaptive)" if msg.kind == "sent" else "LEAD"
        parts.append(f"[{msg.timestamp.isoformat()}] {speaker}:\n{to_plain_text(msg.body)}\n")
    return "\n".join(parts)


def text_to_html(body: str) -> str:
    paragraphs = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    return "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)


US_KEYWORDS = ("usa", "us -", "us-", "united states", "america")


def guess_timezone(campaign_name: str) -> str:
    name = (campaign_name or "").lower()
    if any(kw in name for kw in US_KEYWORDS):
        return "America/New_York"
    return "Europe/Zagreb"


def next_morning_send_utc(tz_name: str, now: datetime | None = None) -> datetime:
    """Next weekday 09:00 in the lead's timezone (leads_state.timezone_guess),
    returned as UTC — the default send time for follow-ups, so they land at
    the top of the lead's morning inbox instead of 3am. Replies are exempt:
    those go out immediately (speed-to-lead). Weekends roll to Monday."""
    try:
        tz = ZoneInfo(tz_name or "Europe/Zagreb")
    except Exception:
        tz = ZoneInfo("Europe/Zagreb")
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    target = local.replace(hour=9, minute=0, second=0, microsecond=0)
    if local >= target:
        target += timedelta(days=1)
    while target.weekday() >= 5:  # Sat/Sun → Monday
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)
