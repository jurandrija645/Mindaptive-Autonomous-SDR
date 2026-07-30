import re
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


_URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE)
# Punctuation that almost always belongs to the sentence, not the URL, when it
# sits at the very end of one ("...check https://calendly.com/x/30min.").
# `*` is in here for the emphasis markers below: a bolded link comes through as
# `**https://calendly.com/x**`, and without this the trailing asterisks end up
# inside the href, where render_emphasis would then rewrite the middle of the
# attribute and break the link.
_URL_TRAILING = ".,;:!?)]}'\"*"


def linkify(text: str) -> str:
    """Escape plain text and turn bare URLs into real anchors.

    Claude and the canned templates both write links as plain text
    (`-> https://calendly.com/...`); mail clients don't reliably auto-link
    those, so the lead would see unclickable text. Everything outside a URL
    is still escaped exactly as before.
    """
    out: list[str] = []
    pos = 0
    for match in _URL_RE.finditer(text):
        url = match.group(0)
        trailing = ""
        while url and url[-1] in _URL_TRAILING:
            # A closing paren that balances one inside the URL is part of it.
            if url[-1] == ")" and url.count("(") >= url.count(")"):
                break
            trailing = url[-1] + trailing
            url = url[:-1]
        if not url:
            continue
        href = url if url.lower().startswith("http") else "https://" + url
        out.append(escape(text[pos : match.start()]))
        out.append(f'<a href="{escape(href)}" target="_blank" rel="noopener">{escape(url)}</a>')
        out.append(escape(trailing))
        pos = match.end()
    out.append(escape(text[pos:]))
    return "".join(out)


# The house emphasis convention: text we generate marks its load-bearing bit
# with **double asterisks** (see prompts/human-writing.md), and it becomes real
# <strong> here. It has to work this way round — everything a model writes
# arrives as plain text and goes through `linkify`, which escapes it, so a
# literal <strong> from the model would reach the lead as visible tag source.
# Escaping is the safety property, so the marker is translated on our side and
# the only tag in the output is one we wrote.
_BOLD_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_STRAY_BOLD_RE = re.compile(r"\*\*")


def render_emphasis(html: str) -> str:
    """`**like this**` -> <strong>, and any unpaired `**` deleted.

    Deleting the leftovers is the same call `message_templates.fill` makes for a
    placeholder it doesn't know: a marker that reaches the lead as literal
    asterisks is worse than no emphasis at all. Pairing is line-bounded on
    purpose, so an opener the model forgot to close can't bold everything after
    it. Safe to run on already-escaped HTML — it only ever adds tags of its own
    around text that was between two markers.
    """
    return _STRAY_BOLD_RE.sub("", _BOLD_RE.sub(r"<strong>\1</strong>", html))


_BOLD_TAG_RE = re.compile(r"</?(?:b|strong)\b[^>]*>", re.IGNORECASE)


def html_to_marked_text(html: str | None) -> str:
    """Plain text like `to_plain_text`, but with bold kept as `**markers**`.

    For the round trips that hand a draft back to a model — the English tab's
    translation, Apply-English (localize), and a regenerate that passes the
    editor's live content as the draft being revised. `to_plain_text` drops
    <strong> along with every other tag, so those paths silently stripped the
    emphasis on the way out and handed back a draft with none.
    """
    if not html:
        return ""
    return to_plain_text(_BOLD_TAG_RE.sub("**", html))


def text_to_html(body: str) -> str:
    paragraphs = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    # Emphasis before the newline -> <br> swap, so `_BOLD_RE`'s line bound still
    # means a line and a stray marker can't pair with one on the next line.
    return "".join(
        f"<p>{render_emphasis(linkify(p)).replace(chr(10), '<br>')}</p>"
        for p in paragraphs
    )


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
