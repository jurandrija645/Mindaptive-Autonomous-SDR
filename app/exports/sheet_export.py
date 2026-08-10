"""The dashboard's "Export for LinkedIn" button: one lead -> one row in the
client's Google Sheet, in the tab belonging to whichever persona's mailbox
carried the thread.

The whole-account CSV sweep (lead_export.run_export) already knew how to turn a
Smartlead lead into an outreach row; what it couldn't do was run on the droplet
(scripts/ isn't in the Docker image) or answer "this lead, now, while I'm
looking at it". So the field-picking rules are shared verbatim via
lead_export.build_row and only the plumbing is new.

Two rules the sheets themselves impose:

- **Columns are matched by the header row, never by position.** Andrew keeps
  notes in an un-headered column and colours rows by hand; writing by index
  would eventually push data into one of those. An unrecognised header gets a
  blank, so a column added to the sheet is simply left alone.
- **Never write twice.** The lead's email is looked up in the target tab first
  and a hit stops the export. A duplicate row is worse than no row: the sheet is
  a manual worklist, so a second copy means someone messages the lead twice.
"""

import logging
import re
import threading

import anthropic

from app import client_assets, models_registry, sheets, signatures, smartlead
from app.config import settings
from app.detector import last_sender_email, normalize_thread
from app.exports.lead_export import (
    _extract_custom,
    _normalize_lead_full,
    _sender_display_name,
    build_row,
)

log = logging.getLogger("sheet_export")

# The header row Andrew's two sheets already use, written onto a tab this module
# has to create. Same order and spelling as the existing tabs so a created tab
# is indistinguishable from a hand-made one — note "persona" where the CSV
# export says "sender_name".
SHEET_HEADER = [
    "full_name", "company_name", "company_website", "linkedin", "phone",
    "secondary_email", "email", "persona", "thread_summary", "last_message_sent_at",
]

# Only "persona" differs from the ExportRow field names, which is what lets the
# sheet's own header row drive the mapping instead of a hardcoded column order.
_HEADER_ALIASES = {"persona": "sender_name"}


def _field_for(header_cell: str) -> str:
    """ExportRow attribute a header cell names. Tolerant of the spacing and
    casing a human editing the sheet might introduce ("Company Website")."""
    key = header_cell.strip().lower().replace(" ", "_")
    return _HEADER_ALIASES.get(key, key)

_LINKEDIN_SYSTEM = (
    "You find one person's personal LinkedIn profile URL. Search the web, then "
    "reply with the profile URL on its own and nothing else — no explanation, no "
    "markdown. The URL must be the person's own profile (linkedin.com/in/...), "
    "never a company page (linkedin.com/company/...). If you cannot find a "
    "profile you are confident belongs to this exact person at this exact "
    "company, reply with the single word NONE."
)

# Personal profiles only. A company page in the `linkedin` column sends the SDR
# to the wrong place, and a wrong URL is worse than the blank cell it replaces —
# a blank one is visibly missing, a wrong one gets messaged.
_LINKEDIN_URL_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^\s\"'<>]+", re.I)


class ExportError(RuntimeError):
    pass


# ---------------------------------------------------------------- persona/tab

def _resolve_tab(sender_email: str, tabs: list[str]) -> tuple[str, str]:
    """(tab title, persona label) for the mailbox that carried this thread.

    The tab is matched case-insensitively against the spreadsheet's real titles
    so a tab named "max" or "Max " still resolves. An unmatched or unresolvable
    persona goes to the fallback tab, and the persona *label* then names the
    actual sender instead — AeroDefense's retired anna@/linda@/lexi.r@ mailboxes
    are real threads with a real author, they just have no tab of their own.
    """
    by_lower = {t.strip().lower(): t for t in tabs}
    persona = signatures.persona_tab(sender_email)
    if persona:
        match = by_lower.get(persona.lower())
        if match:
            return match, persona
        log.info("sheet_export: persona %r has no tab in the sheet, using fallback", persona)

    fallback = settings.linkedin_sheet_fallback_tab
    label = _sender_display_name(sender_email, client_assets.prior_senders())
    return by_lower.get(fallback.lower(), fallback), (persona or label)


def _ensure_tab(sheet_id: str, tab: str, tabs: list[str]) -> None:
    if any(t.strip().lower() == tab.strip().lower() for t in tabs):
        return
    sheets.create_tab(sheet_id, tab)
    sheets.write_header(sheet_id, tab, list(SHEET_HEADER))
    log.info("sheet_export: created tab %r with a header row", tab)


# ------------------------------------------------------------ LinkedIn lookup

def find_linkedin(full_name: str, company: str, website: str, email: str) -> str:
    """Web-search for a missing personal LinkedIn URL. "" on anything unsure.

    Fail-soft like lead_export._summarize_thread: the row is worth exporting
    without this field, so no failure here may stop the export. Deliberately
    small next to drafter.generate_draft's research — two searches, no
    web_fetch, three turns — because the answer is one URL, not a diagnostic.
    """
    if not full_name or not settings.anthropic_api_key:
        return ""
    known = ", ".join(
        part for part in (
            f"name: {full_name}",
            f"company: {company}" if company else "",
            f"company website: {website}" if website else "",
            f"work email: {email}" if email else "",
        ) if part
    )
    # allowed_callers=["direct"] is required, not decorative: without it the
    # current web_search type also permits programmatic calling, which Haiku
    # (AeroDefense's model) rejects with a 400. See app/drafter.py.
    tools = [{
        "type": "web_search_20260209",
        "name": "web_search",
        "allowed_callers": ["direct"],
        "max_uses": 2,
    }]
    model = models_registry.resolve_anthropic(None)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        messages = [{"role": "user", "content": f"Find the LinkedIn profile for — {known}"}]
        response = client.messages.create(
            model=model, max_tokens=1024, system=_LINKEDIN_SYSTEM,
            tools=tools, messages=messages,
        )
        turns = 0
        while response.stop_reason == "pause_turn" and turns < 3:
            turns += 1
            response = client.messages.create(
                model=model, max_tokens=1024, system=_LINKEDIN_SYSTEM, tools=tools,
                messages=[
                    messages[0],
                    {"role": "assistant", "content": response.content},
                ],
            )
        text = "".join(b.text for b in response.content if b.type == "text")
    except Exception:
        log.exception("linkedin lookup failed for %r", full_name)
        return ""

    match = _LINKEDIN_URL_RE.search(text or "")
    if not match:
        log.info("sheet_export: no LinkedIn found for %r (model said %r)", full_name, text[:120])
        return ""
    # Trailing punctuation from a sentence the model wasn't supposed to write.
    return match.group(0).rstrip(".,);]")


# ------------------------------------------------------------------- the work

def export_lead(campaign_id: int, lead_id: int) -> dict:
    """Append this lead to its persona's tab. Returns what happened."""
    if not settings.linkedin_sheet_id:
        raise ExportError("LINKEDIN_SHEET_ID is not set — add it to .env.")

    raw = smartlead.get_lead(lead_id)
    if not raw:
        raise ExportError(f"Smartlead has no lead {lead_id}.")
    lead = _normalize_lead_full(raw, campaign_id)

    thread = normalize_thread(smartlead.get_message_history(campaign_id, lead_id))
    sender_email = last_sender_email(thread)

    sheet_id = settings.linkedin_sheet_id
    tabs = sheets.list_tabs(sheet_id)
    tab, persona = _resolve_tab(sender_email, tabs)
    _ensure_tab(sheet_id, tab, tabs)

    header = sheets.read_header(sheet_id, tab) or list(SHEET_HEADER)

    duplicate = _find_duplicate(sheet_id, tab, header, lead)
    if duplicate:
        log.info("sheet_export: %s already in tab %r at row %s", lead["email"], tab, duplicate)
        return {"status": "duplicate", "tab": tab, "row": duplicate, "persona": persona}

    row = build_row(lead, thread, persona)
    if not row.linkedin:
        row.linkedin = find_linkedin(
            row.full_name, row.company_name, row.company_website, row.email
        )

    values = [getattr(row, _field_for(h), "") or "" for h in header]
    written = sheets.append_row(sheet_id, tab, values)
    log.info(
        "sheet_export: added %s (%s) to tab %r row %s",
        lead["email"], campaign_id, tab, written,
    )
    return {
        "status": "added",
        "tab": tab,
        "row": written,
        "persona": persona,
        "linkedin_found": bool(row.linkedin),
    }


def _find_duplicate(sheet_id: str, tab: str, header: list[str], lead: dict) -> int | None:
    """Sheet row number this lead already occupies, or None.

    Keyed on email because it's the one field that is always present and never
    rewritten by hand; names in the sheet get corrected and companies get
    renamed. Both the work address and the personal one count as a hit — the
    same person under a second address is still the same person to message.
    """
    fields = [_field_for(h) for h in header]
    # "email", not "secondary_email" — _field_for normalizes, so match exactly.
    column_index = fields.index("email") if "email" in fields else -1
    if column_index < 0 or column_index >= 26:
        log.warning(
            "sheet_export: no usable email column in tab %r — skipping the duplicate check", tab
        )
        return None
    column_letter = chr(ord("A") + column_index)

    wanted = {
        value.strip().lower()
        for value in (
            lead.get("email"),
            _extract_custom(lead.get("custom_fields") or {}, "personalemail"),
        )
        if isinstance(value, str) and value.strip()
    }
    if not wanted:
        return None

    for offset, cell in enumerate(sheets.read_column(sheet_id, tab, column_letter)):
        if cell.strip().lower() in wanted:
            return offset + 1
    return None


# ------------------------------------------------------------------ threading

# Same shape as candidates.generate_for_lead_in_background: a Smartlead fetch, a
# Haiku summary and a web search add up to well past Cloudflare's ~100s tunnel
# timeout on a slow lead, so the click starts a thread and the client polls.
_lock = threading.Lock()
_running: set[tuple[int, int]] = set()
_results: dict[tuple[int, int], dict] = {}
_errors: dict[tuple[int, int], str] = {}
_MAX_ERROR_CHARS = 300


def is_running(campaign_id: int, lead_id: int) -> bool:
    return (campaign_id, lead_id) in _running


def last_result(campaign_id: int, lead_id: int) -> dict | None:
    return _results.get((campaign_id, lead_id))


def last_error(campaign_id: int, lead_id: int) -> str | None:
    return _errors.get((campaign_id, lead_id))


def export_lead_in_background(campaign_id: int, lead_id: int) -> bool:
    """False (no-op) if this lead is already exporting, so a double click can't
    race two appends of the same row past the duplicate check."""
    key = (campaign_id, lead_id)
    with _lock:
        if key in _running:
            return False
        _running.add(key)
        _results.pop(key, None)
        _errors.pop(key, None)

    def _worker():
        try:
            _results[key] = export_lead(campaign_id, lead_id)
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            _errors[key] = detail[:_MAX_ERROR_CHARS]
            log.exception("export_lead failed for %s/%s", campaign_id, lead_id)
        finally:
            with _lock:
                _running.discard(key)

    threading.Thread(target=_worker, daemon=True).start()
    return True
