"""Seed content for the editable message templates (db.message_templates).

These used to live as a hardcoded MESSAGE_TEMPLATES constant in app/static/app.js,
which meant changing a template's wording needed a commit and a deploy. They now
live in SQLite and are edited from the "Message templates" modal — this list is
only used to populate the table the first time it's created (see db.init_db), so
editing it here has no effect on an existing database.

Placeholders are `{name}`, `{company}` and `{companyNickname}` (see
PLACEHOLDER_KEYS). Their values are computed HERE, server-side, and shipped to
the client in the lead payload — the client only substitutes. That is deliberate:
the modal renders a preview of the same string that gets sent, so the two can
never drift, and adding a placeholder means editing one function rather than two
implementations in two languages.
"""

import re

PLACEHOLDER_KEYS = ("name", "company", "companyNickname")

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")

# Legal forms, stripped off the end of a company name to get something a person
# would actually say out loud. "Sonnenplus Energie GmbH" is not what anyone
# calls it; "your Sonnenplus Energie team" is.
_LEGAL_FORMS = {
    "gmbh", "mbh", "ug", "ag", "kg", "ohg", "gbr", "ek", "e.k", "e.k.",
    "bv", "b.v", "b.v.", "nv", "n.v", "n.v.", "vof", "cv",
    "ltd", "ltd.", "limited", "llc", "l.l.c.", "inc", "inc.", "incorporated",
    "corp", "corp.", "corporation", "plc", "llp", "pty",
    "sa", "s.a", "s.a.", "sas", "sarl", "s.a.r.l.", "sl", "s.l", "s.l.",
    "srl", "s.r.l.", "spa", "s.p.a.",
    "oy", "ab", "as", "a/s", "aps", "asa", "oyj",
    "doo", "d.o.o", "d.o.o.", "sro", "s.r.o.", "kft", "zrt", "a.s.",
    "sp", "z", "o.o", "o.o.", "zoo",
    "co", "co.", "company", "the",
}

# Where a company "name" turns into a description of it. Smartlead's company
# names carry a lot of this: "Kieferorthopädie.Ruhr - Dr. Nora Mersmann -
# Fachzahnärztin für Kieferorthopädie" is one field, and only the first part is
# a name anyone uses.
_SEPARATORS = re.compile(r"\s+[-–—|/]\s+|,|\||\bt/a\b", re.IGNORECASE)


def company_nickname(company: str | None) -> str:
    """The short, spoken form of a company name.

    Conservative on purpose: it only cuts at an explicit separator and strips
    trailing legal forms. Guessing harder (dropping "Praxis", "Dr.", the first
    word) mangles names more often than it helps, and a nickname that is merely
    the full name reads fine — a wrong one does not."""
    name = (company or "").strip()
    if not name:
        return ""
    head = _SEPARATORS.split(name)[0].strip() or name
    words = head.split()
    # Alternating, not two sequential passes: "Sonnenplus Energie GmbH & Co. KG"
    # sheds KG and Co., which exposes the "&", which exposes GmbH. Stopping after
    # one pass over each left "Sonnenplus Energie GmbH".
    changed = True
    while changed and words:
        changed = False
        if words[-1].strip(".,&").lower() in _LEGAL_FORMS:
            words.pop()
            changed = True
        elif words[-1].strip(".,").lower() in {"&", "and", "+"}:
            words.pop()
            changed = True
    return " ".join(words).strip(" ,&-") or head


def placeholders_for(name: str | None, company: str | None) -> dict[str, str]:
    """The substitution map for one lead. Fallbacks are wording that still reads
    as a sentence if the field is missing, since these go out to a real person."""
    first_name = (name or "").strip().split(" ")[0] or "there"
    company_name = (company or "").strip()
    return {
        "name": first_name,
        "company": company_name or "your business",
        # Empty rather than "your business" when the company is unknown: the
        # templates say "your {companyNickname} team", so the generic fallback
        # produced "your your business team". Empty collapses to "your team",
        # which reads like a person wrote it.
        "companyNickname": company_nickname(company_name),
    }


def fill(text: str, values: dict[str, str]) -> str:
    """Substitute known placeholders and remove unknown ones.

    Dropping the unknown ones matters more than filling the known ones: a
    template with a typo, or one written against a variable this app doesn't
    have, used to send `{companyNickname}` to the lead verbatim. Anything left
    in braces is deleted and the surrounding spacing tidied, so the worst case
    is a slightly clipped sentence rather than visible machinery."""
    def replace(match: re.Match) -> str:
        return values.get(match.group(1), "")

    filled = _PLACEHOLDER_RE.sub(replace, text or "")
    filled = re.sub(r"[ \t]{2,}", " ", filled)
    return re.sub(r" +([,.!?])", r"\1", filled).strip()


DEFAULT_TEMPLATES: list[dict] = [
    {
        "label": "Prototype offer (already-built agent)",
        "text": "Hi {name},\n\nI actually went ahead and created a prototype Ai Agent for {company}. It's trained on your website data. Wanted to provide some value upfront because I know that's how you get ahead in this industry. Would love to show you how it works over a call -> https://calendly.com/andrew-mindaptive/30min\n\nYours to keep regardless.\n\nAndrew",
    },
    {"label": "", "text": "Wanted to make sure you saw this, let me know either way"},
    {
        "label": "",
        "text": "Hey {name}, I'm locking in projects for next week, let me know if you'd like to move forward or if the timing changed",
    },
    {"label": "", "text": "{name} - just bumping this up in case it got buried. No rush at all"},
    {
        "label": "",
        "text": "Hey {name}, just checking in on this. Let me know if there's anything I can help clarify.",
    },
    {
        "label": "",
        "text": "Hi {name}, closing this file, it seems that now is not the right time. No worries though, it happens. Wishing you and your {companyNickname} team all the best.",
    },
    {"label": "", "text": "{name} - please give me your thoughts on this"},
]
