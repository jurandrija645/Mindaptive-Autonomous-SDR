"""Turn Smartlead's raw email bodies into clean, safe text for the dashboard.

Message bodies from Smartlead's `email_body` field are raw email HTML — full
`<div>`/`<table>` markup, inline styles, and long quoted-reply history. The old
dashboard printed them with Jinja auto-escaping, so the user literally saw
escaped HTML source. Everything here reduces a body to plain text (tags removed,
quoted history dropped), and `clean_email_html` re-wraps that plain text into a
*safe* minimal HTML fragment (our own `<p>`/`<br>`, with the text escaped) so the
thread view can render it without ever emitting untrusted email markup.
"""
import re
from html import escape, unescape

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END_RE = re.compile(
    r"</(p|div|tr|table|li|ul|ol|h[1-6]|blockquote)>", re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_INLINE_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MANY_NL_RE = re.compile(r"\n{3,}")

# Markers where a fresh reply gives way to quoted history. We truncate at the
# earliest one so the bubble shows only what the person actually wrote this time.
_QUOTE_MARKERS = [
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*On\b.{0,300}?\bwrote:\s*$", re.IGNORECASE | re.MULTILINE | re.DOTALL),
    re.compile(r"^\s*_{5,}\s*$", re.MULTILINE),  # Outlook "________" divider
    re.compile(r"^\s*From:\s.+$", re.IGNORECASE | re.MULTILINE),  # forwarded header block
    re.compile(r"^\s*>.*$", re.MULTILINE),  # a quoted (">") line
]


def _html_to_text(raw: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _INLINE_WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MANY_NL_RE.sub("\n\n", text)
    return text.strip()


def _strip_quoted_history(text: str) -> str:
    cut = len(text)
    for marker in _QUOTE_MARKERS:
        m = marker.search(text)
        if m and m.start() < cut:
            cut = m.start()
    trimmed = text[:cut].strip()
    # If stripping ate everything (e.g. a body that's only quoted text), keep the
    # original so the user still sees something rather than an empty bubble.
    return trimmed or text.strip()


def to_plain_text(raw: str | None) -> str:
    """Plain, quote-free text — for previews and language detection."""
    if not raw:
        return ""
    return _strip_quoted_history(_html_to_text(raw))


def clean_email_html(raw: str | None) -> str:
    """Safe minimal HTML for the thread view: escaped text, our own <p>/<br>.

    Never emits the original (untrusted) email markup, so it's XSS-safe to render
    with |safe in the template.
    """
    text = to_plain_text(raw)
    if not text:
        return ""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    return "".join(
        "<p>" + escape(p).replace("\n", "<br>") + "</p>" for p in paragraphs
    )
