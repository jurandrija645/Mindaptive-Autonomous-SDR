from html import escape

from app.detector import NormalizedMessage


def render_thread_text(thread: list[NormalizedMessage]) -> str:
    parts = []
    for msg in thread:
        speaker = "US (Mindaptive)" if msg.kind == "sent" else "LEAD"
        parts.append(f"[{msg.timestamp.isoformat()}] {speaker}:\n{msg.body}\n")
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
