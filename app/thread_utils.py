from html import escape

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
