"""Maps a sending mailbox to its HTML signature, using Smartlead's own
`from_name` on each email account (e.g. "Andrew Juran", "Mia Malcic") rather
than a hand-maintained list of addresses — Andrew has 37+ rotating sending
accounts and Mia has 50+, so keeping a static list in sync isn't realistic."""
import logging

from app import client_assets, smartlead
from app.config import settings

log = logging.getLogger("signatures")

SIGNATURES_DIR = client_assets.SIGNATURES_DIR

# Mindaptive's built-in map. A client that ships `<CLIENT_DIR>/personas.json`
# replaces both this and _NAME_HINTS below, and can additionally give each
# persona a booking link (see calendar_link_for).
PERSONA_FILES = {
    "Andrew Juran": "andrew.html",
    "Mia Malcic": "mia.html",
}

_NAME_HINTS = {
    "andrew.html": ("andrew", "juran"),
    "mia.html": ("mia",),
}

_CALENDAR_LINKS: dict[str, str] = {}
_SHEET_TABS: dict[str, str] = {}

_CONFIGURED = client_assets.personas()
if _CONFIGURED:
    PERSONA_FILES = {p["from_name"]: p["signature_file"] for p in _CONFIGURED}
    _NAME_HINTS = {
        p["signature_file"]: tuple(p.get("name_hints") or ())
        for p in _CONFIGURED
        if p.get("name_hints")
    }
    _CALENDAR_LINKS = {
        p["signature_file"]: p["calendar_link"]
        for p in _CONFIGURED
        if p.get("calendar_link")
    }
    _SHEET_TABS = {
        p["signature_file"]: p["sheet_tab"]
        for p in _CONFIGURED
        if p.get("sheet_tab")
    }
    log.info("personas loaded from %s: %s", client_assets.CLIENT_DIR, list(PERSONA_FILES))

_email_to_file: dict[str, str] | None = None


def _load_mapping() -> dict[str, str]:
    global _email_to_file
    if _email_to_file is not None:
        return _email_to_file

    mapping: dict[str, str] = {}
    try:
        for account in smartlead.list_email_accounts():
            file = PERSONA_FILES.get(account.get("from_name", ""))
            email = (account.get("from_email") or "").lower()
            if file and email:
                mapping[email] = file
    except Exception:
        log.exception("failed to load email accounts for signature mapping")
        return {}

    _email_to_file = mapping
    return mapping


def _guess_persona_file(email: str) -> str | None:
    """Fallback for when the exact sending mailbox isn't in Smartlead's
    *current* email-accounts list — with 100+ rotating accounts, a lead's
    original outreach mailbox can get paused/retired later even though the
    persona is still obvious from the address (every Andrew/Mia mailbox we've
    seen embeds their first name in the local part, e.g. andrewj@, a.juran@,
    mia.m@, m.mia@)."""
    local = email.split("@", 1)[0]
    for file, hints in _NAME_HINTS.items():
        if any(hint in local for hint in hints):
            return file
    return None


def get_signature_html(sender_email: str) -> str:
    if not sender_email:
        log.info("[SIG-DEBUG] get_signature_html: no sender_email given, returning empty")
        return ""
    email = sender_email.lower()
    mapping = _load_mapping()
    exact = mapping.get(email)
    file = exact or _guess_persona_file(email)
    log.info(
        "[SIG-DEBUG] get_signature_html: sender=%s mapping_size=%d exact_match=%s guessed=%s resolved_file=%s",
        email, len(mapping), bool(exact), file if not exact else None, file,
    )
    if not file:
        log.warning("[SIG-DEBUG] get_signature_html: no persona file resolved for sender=%s", email)
        return ""
    path = SIGNATURES_DIR / file
    if not path.exists():
        log.warning("[SIG-DEBUG] get_signature_html: resolved file %s does not exist at %s", file, path)
        return ""
    html = path.read_text(encoding="utf-8")
    log.info("[SIG-DEBUG] get_signature_html: loaded %s (%d chars) for sender=%s", file, len(html), email)
    return html


def _resolve_file(sender_email: str) -> str | None:
    email = (sender_email or "").lower()
    if not email:
        return None
    return _load_mapping().get(email) or _guess_persona_file(email)


def persona_name(sender_email: str) -> str:
    """Display name of the persona sending this thread, or "" if unresolved.

    Returns "" for clients that don't ship a personas.json, so their draft
    prompt is unchanged — this exists to feed the per-persona booking link, and
    adding an unrequested "you are writing as X" line to a prompt that has been
    tuned without one is not a free change.
    """
    if not _CONFIGURED:
        return ""
    file = _resolve_file(sender_email)
    if not file:
        return ""
    return next((name for name, f in PERSONA_FILES.items() if f == file), "")


def is_sendable(sender_email: str) -> bool:
    """False when this thread can't be replied to at all.

    AeroDefense rotated through mailboxes that Smartlead no longer returns
    (e.g. anna@aerodefensemarketing.com). A thread whose last outbound message
    came from one of those is dead: there is no live mailbox to reply from, so
    drafting one only produces an email that can never be sent. Enabled with
    REQUIRE_KNOWN_SENDER=true; off by default, so Mindaptive keeps its current
    behaviour of simply going without a signature.

    Deliberately re-derived from Smartlead's live account list on each pass
    rather than stored as a terminal lead status, so a transient API blip can't
    permanently retire a live lead.
    """
    if not settings.require_known_sender:
        return True
    return _resolve_file(sender_email) is not None


def persona_tab(sender_email: str) -> str:
    """Which tab of the client's LinkedIn export sheet this thread belongs in,
    or "" if the sending mailbox doesn't resolve to a persona at all.

    Derived from the signature file rather than configured, because both sheets
    already name their tabs after the persona's first name and the file stems
    already start with it: max-west.html -> "Max", mia.html -> "Mia",
    andrew-grasso.html -> "Andrew". A client whose tab is named something else
    can override it with "sheet_tab" in personas.json. Unlike persona_name this
    works for Mindaptive too — it doesn't go through PERSONA_FILES' display
    names, so it needs no personas.json.
    """
    file = _resolve_file(sender_email)
    if not file:
        return ""
    configured = _SHEET_TABS.get(file)
    if configured:
        return configured
    stem = file.rsplit(".", 1)[0]
    return stem.split("-", 1)[0].capitalize()


def calendar_link_for(sender_email: str) -> str:
    """Booking link of the persona sending this thread.

    Only clients whose templates put a booking link in the message body
    (AeroDefense) configure these; Mindaptive returns "" and its prompt keeps
    using the Calendly URL written into system.md.
    """
    if not _CALENDAR_LINKS:
        return ""
    file = _resolve_file(sender_email)
    return _CALENDAR_LINKS.get(file or "", "")
