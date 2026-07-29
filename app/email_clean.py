"""Turn Smartlead's raw email bodies into clean, safe text for the dashboard.

Message bodies from Smartlead's `email_body` field are raw email HTML — full
`<div>`/`<table>` markup, inline styles, and long quoted-reply history. The old
dashboard printed them with Jinja auto-escaping, so the user literally saw
escaped HTML source. Everything here reduces a body to plain text (tags removed,
quoted history dropped), and `clean_email_html` re-wraps that plain text into a
*safe* minimal HTML fragment (our own `<p>`/`<br>`, with the text escaped) so the
thread view can render it without ever emitting untrusted email markup.

Images are the one exception, and they are reconstructed rather than passed
through. `_TAG_RE` deletes every tag, and an `<img>` has no text content, so an
image used to vanish from the thread without leaving so much as a gap — a
screenshot pasted into a draft was invisible the moment it became a sent
message, and an image a lead sent us was never visible at all. So
`clean_email_html` swaps each `<img>` for an opaque token *before* the
text reduction, then rebuilds it afterwards from an allowlist: `src` (http(s) or
a data: image only), `alt`, and nothing else. Dropping every other attribute is
what keeps this safe — `onerror=`/`onload=` never survive the round trip. The
token has to be alphanumeric so the reduction can't mangle it: `unescape` skips
it (no `&`), the whitespace collapse skips it (no spaces), and `escape` leaves it
alone when the paragraph is escaped.
"""
import re
import uuid
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
    # Non-English equivalents of "On … wrote:". Outreach goes out in German,
    # Dutch, French and Spanish, and without these the lead's two-line reply
    # arrives with our entire previous email quoted underneath it — which
    # inflates token cost and invites a model reading the thread to treat our
    # own copy as something the lead wrote.
    # The date can follow the verb ("Mia schrieb am Mi. 22. Juli 2026 um 13:42:"),
    # so allow text between the verb and the trailing colon.
    re.compile(
        r"^.{0,200}?\b(schrieb|schreef|a écrit|ha escrito|escribió|ha scritto)\b.{0,200}?:\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    # German/Dutch date-first form: "Am 22.07.2026 um 13:42 schrieb X:"
    re.compile(r"^\s*(Am|Op)\b.{0,300}?\b(schrieb|schreef)\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*_{5,}\s*$", re.MULTILINE),  # Outlook "________" divider
    re.compile(r"^\s*From:\s.+$", re.IGNORECASE | re.MULTILINE),  # forwarded header block
    re.compile(r"^\s*>.*$", re.MULTILINE),  # a quoted (">") line
]


_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)

# What we're willing to point an <img> at. Remote http(s) images are allowed on
# purpose: a lead who sends us a screenshot is sending it from their own server,
# and Andrew's decision is that seeing it beats hiding it. The cost is that a
# tracking pixel in a lead's signature will report the thread as read, which is
# accepted — we're the ones chasing them. `data:` images are inlined and safe;
# svg+xml is excluded because it's a script carrier and no mail client sends it.
_SAFE_SRC_RE = re.compile(
    r"^(?:https?://|data:image/(?:png|jpeg|jpg|gif|webp|bmp);base64,)", re.IGNORECASE
)


def _attr(tag: str, name: str) -> str:
    """One attribute out of a raw tag, entity-decoded. '' when absent."""
    for pattern in (
        rf'{name}\s*=\s*"([^"]*)"',
        rf"{name}\s*=\s*'([^']*)'",
        rf'{name}\s*=\s*([^\s>"\']+)',
    ):
        m = re.search(pattern, tag, re.IGNORECASE)
        if m:
            return unescape(m.group(1)).strip()
    return ""


# The width the sender meant the image to have, in px, from either the `width`
# attribute or an inline `width: Npx`. `max-`/`min-width` must not match, and a
# percentage is not a pixel size — both are left to the stylesheet.
_STYLE_WIDTH_RE = re.compile(r"(?:^|;)\s*width\s*:\s*(\d+(?:\.\d+)?)\s*px", re.IGNORECASE)
_ATTR_WIDTH_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:px)?$", re.IGNORECASE)

# Nothing in a mail body has any business rendering wider than the editor's own
# full-size preset (CLAUDE.md §11 caps 100% at 600px).
_MAX_IMG_WIDTH = 600


def _intended_width(tag: str) -> int | None:
    """Sanitized pixel width for an image, or None to let CSS decide.

    Signature logos carry their size *only* in inline style (`width: 100px` in
    `signatures/andrew.html`), and our own editor writes it to both the `width`
    attribute and the style. Dropping both is what made a 100px logo render at
    the full width of the bubble. Reading out a bare number and re-emitting it
    ourselves keeps the attribute allowlist intact — no sender CSS is passed
    through, so this can't be used to smuggle anything.
    """
    m = _STYLE_WIDTH_RE.search(_attr(tag, "style"))
    if not m:
        m = _ATTR_WIDTH_RE.match(_attr(tag, "width"))
    if not m:
        return None
    width = int(float(m.group(1)))
    if width <= 0:
        return None
    return min(width, _MAX_IMG_WIDTH)


def _rebuild_img(tag: str) -> str:
    """A sanitized <img> for a raw one, or a visible marker if it can't render.

    `cid:` sources are the reason for the marker: inline attachments reference a
    part of the MIME message that Smartlead's `email_body` doesn't carry, so
    there's nothing to point at. Showing "[image]" is the honest answer — the
    reader at least knows an image was in the message, instead of the old
    behaviour where it silently disappeared.
    """
    src = _attr(tag, "src")
    alt = _attr(tag, "alt")
    if not _SAFE_SRC_RE.match(src):
        return f'<span class="msg-img-missing">[{escape(alt or "image")}]</span>'
    width = _intended_width(tag)
    if width is None:
        # No stated size — the stylesheet caps it by height so an unsized
        # screenshot can't take over the thread.
        sizing = ' class="msg-img msg-img-unsized"'
    else:
        sizing = (
            f' class="msg-img" width="{width}"'
            f' style="width:{width}px;max-width:100%"'
        )
    img = f'<img{sizing} src="{escape(src)}" alt="{escape(alt)}" loading="lazy">'
    if src.lower().startswith("data:"):
        return img
    # A screenshot capped to the bubble's width is often too small to read, so
    # the image opens full size in a new tab. rel=noopener because the href is
    # whatever the sender put there.
    return (
        f'<a class="msg-img-link" href="{escape(src)}" target="_blank" '
        f'rel="noopener noreferrer">{img}</a>'
    )


def _tokenize_images(raw: str) -> tuple[str, dict[str, str]]:
    """Replace every <img> with a token that survives the text reduction."""
    images: dict[str, str] = {}

    def swap(m: re.Match) -> str:
        token = f"IMGTOKEN{uuid.uuid4().hex}X"
        images[token] = m.group(0)
        # Padded with spaces so an image between two words doesn't glue them
        # together into one unreadable run once the tags are gone.
        return f" {token} "

    return _IMG_TAG_RE.sub(swap, raw), images


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
    """Safe minimal HTML for the thread view: escaped text, our own <p>/<br>,
    plus any images rebuilt from an attribute allowlist.

    Never emits the original (untrusted) email markup — the only tags in the
    output are ones this function writes itself — so it stays XSS-safe to render
    with |safe in the template, or via innerHTML in the thread view.
    """
    if not raw:
        return ""
    tokenized, images = _tokenize_images(raw)
    text = to_plain_text(tokenized)
    if not text:
        return ""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    html = "".join(
        "<p>" + escape(p).replace("\n", "<br>") + "</p>" for p in paragraphs
    )
    # Only tokens that survived get rebuilt; ones inside quoted history were cut
    # with it, which is what we want — the bubble shows this message, not the
    # signature logos of every message under it.
    for token, tag in images.items():
        if token in html:
            html = html.replace(token, _rebuild_img(tag))
    return html
