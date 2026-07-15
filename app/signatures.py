"""Maps a sending mailbox to its HTML signature, using Smartlead's own
`from_name` on each email account (e.g. "Andrew Juran", "Mia Malcic") rather
than a hand-maintained list of addresses — Andrew has 37+ rotating sending
accounts and Mia has 50+, so keeping a static list in sync isn't realistic."""
import logging
from pathlib import Path

from app import smartlead

log = logging.getLogger("signatures")

SIGNATURES_DIR = Path(__file__).resolve().parent.parent / "signatures"

PERSONA_FILES = {
    "Andrew Juran": "andrew.html",
    "Mia Malcic": "mia.html",
}

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


_NAME_HINTS = {
    "andrew.html": ("andrew", "juran"),
    "mia.html": ("mia",),
}


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
        return ""
    email = sender_email.lower()
    file = _load_mapping().get(email) or _guess_persona_file(email)
    if not file:
        return ""
    path = SIGNATURES_DIR / file
    return path.read_text(encoding="utf-8") if path.exists() else ""
