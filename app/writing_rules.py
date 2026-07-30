"""One source of truth for how anything this app generates should read.

Every prompt in the app used to carry its own scraps of style guidance — the
SDR prompt said one thing, the auto-reply prompt said another, the translator
said nothing at all and happily produced "Sehr geehrte Damen und Herren" style
English. So a change to the house voice meant editing four prompts and
remembering the fifth.

`prompts/human-writing.md` now holds the rules, in markdown, so they can be
edited without touching Python — same principle as `prompts/system.md` and
`knowledge/*.md`. Everything that calls a model pulls them from here:

- `app/drafter.py`      — outreach drafts, replies, auto-reply nudges
- `app/translator.py`   — translations and localizations
- `app/campaign_copy.py`— translating campaign fragments for the report
- `app/campaign_report.py` — the analysis Andrew reads

Read once and cached: the file does not change while the process runs, and the
draft path would otherwise re-read it on every generation.
"""

from app import client_assets

# A client can override the house voice by shipping its own
# `<CLIENT_DIR>/prompts/human-writing.md`; otherwise everyone shares the root one.
_RULES_PATH = client_assets.resolve("prompts", "human-writing.md")

_cached: str | None = None


def rules() -> str:
    """The house style guide, as markdown, ready to paste into a system prompt."""
    global _cached
    if _cached is None:
        try:
            _cached = _RULES_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            # A missing style guide must never take the drafting path down with
            # it — the rest of the prompt still produces a usable message.
            _cached = ""
    return _cached


def as_section(heading_level: int = 2) -> str:
    """The rules as a prompt section, or nothing at all if the file is missing."""
    text = rules()
    if not text:
        return ""
    return f"\n\n---\n\n{text}\n"


def short_rules() -> str:
    """A compressed version for prompts that are themselves meant to be short.

    The full guide is ~60 lines. Pasting it into the translation prompt, where
    the output is one sentence, costs more than it buys — but the tells it names
    are exactly the ones a translator reaches for, so the core of it still has
    to be there."""
    return (
        "Write like a human, not like AI: short sentences, small words, "
        "contractions ('you're', 'I'd', 'it's'), active voice, no jargon, no "
        "fluff, no em dashes, no 'Sincerely/Best regards', no 'I hope this "
        "email finds you well'. Vary sentence length — uniform rhythm reads as "
        "generated. Write to one person, and say the thing in the first sentence. "
        # The full guide explains the convention; the short version only has to
        # stop the localizers losing markers that are already there, since they
        # rewrite a text somebody else (or a model) already bolded.
        "If the text has **double asterisk** markers around a few words, keep "
        "them, around the words that carry the same emphasis in your version. "
        "They are the app's bold markers. Don't add new ones, don't drop them, "
        "and never write HTML tags."
    )
