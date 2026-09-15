"""On-demand deep contact research for a single lead — the "Research this
lead" button in the About-this-lead panel (app/static/app.js:
renderResearchPanel). Andrew's ask: not just "what does this company do" (the
website-diagnostic <lead_research> block drafter.py already captures during
drafting, see leads_state.research_summary) but "who do I actually email or
call there" — a named person, their direct email/phone, their LinkedIn.

Deliberately a separate column (leads_state.contact_research) rather than
overwriting research_summary: that one is a drafting aid the model keeps
current turn by turn and is fed back into every later draft's prompt as
"reuse this instead of re-researching" (app/pipeline.py, app/drafter.py). A
contact lookup answers a different question and must never silently become
the website research a draft relies on.

Modeled on app/exports/sheet_export.py's find_linkedin (same web_search-only
shape, small and fail-soft) and app/candidates.py's background-generation
pattern (a synchronous "do the work" function plus an in-memory
running/last-error tracker, since a multi-tool-call research pass can take
long enough to hit Cloudflare's ~100s tunnel timeout if awaited inline)."""
import logging
import threading

import anthropic

from app import db, models_registry, pipeline
from app.config import settings
from app.thread_utils import render_thread_text

log = logging.getLogger("lead_research")

_SYSTEM = """You are researching a single B2B lead so a salesperson can reach the \
actual human being at that company, not just the address already on file.

Use the web_search and web_fetch tools to find:
- What the company does, roughly how big it is, and who it serves (2-4 bullets).
- The real point of contact: full name and title. Prefer whoever is already \
writing on the email thread if one is given; if the thread only shows a \
generic address (info@, contact@, sales@), find a named owner, founder, \
marketing lead or ops lead at the company instead.
- Direct contact info for that person, if it's publicly findable: their \
personal LinkedIn profile URL, a direct/personal email if different from the \
one on file, and a phone number (personal or the company's main line) if it \
appears anywhere public — the company site, LinkedIn, a press mention.
- Any other public contact point worth having: company phone number, \
physical address, other social profiles.

Never invent anything. If something can't be found, say so plainly rather \
than guessing — a wrong phone number is worse than none.

Reply in exactly this structure, plain text, no preamble and no markdown \
headers other than these three labels:

COMPANY:
(2-4 bullet points)

CONTACT:
- Name:
- Title:
- LinkedIn:
- Direct email:
- Phone:

OTHER:
(other contact points or notes, or "None found")
"""

# Same tool budget as drafter.generate_draft's Website Diagnostic research —
# this is the same kind of multi-page lookup (company site, LinkedIn, a press
# mention), just aimed at a person instead of a pitch angle.
_TOOLS = [
    {
        "type": "web_search_20260209",
        "name": "web_search",
        "allowed_callers": ["direct"],
        "max_uses": 5,
    },
    {
        "type": "web_fetch_20260209",
        "name": "web_fetch",
        "allowed_callers": ["direct"],
        "max_uses": 5,
        "max_content_tokens": 10000,
    },
]


def _build_prompt(lead: dict, thread_text: str) -> str:
    lines = [
        "Research this lead:",
        f"- Name on file: {lead.get('name', '')}",
        f"- Company: {lead.get('company', '')}",
        f"- Email on file: {lead.get('email', '')}",
        f"- Website: {lead.get('website', '')}",
    ]
    if thread_text:
        lines += ["", "Email thread so far (oldest to newest):", thread_text]
    return "\n".join(lines)


def research_contact(lead: dict, thread_text: str = "") -> str:
    """One Claude call (web_search + web_fetch, pause_turn loop like
    drafter.generate_draft). Raises on failure — the background wrapper below
    is what turns that into a stored, pollable error, same split as
    candidates.generate_for_lead / candidates._record_error."""
    if not settings.anthropic_api_key:
        raise RuntimeError("No ANTHROPIC_API_KEY configured.")
    model = models_registry.resolve_anthropic(None)
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    user_message = _build_prompt(lead, thread_text)
    messages = [{"role": "user", "content": user_message}]
    response = client.messages.create(
        model=model, max_tokens=2048, system=_SYSTEM, tools=_TOOLS, messages=messages,
    )
    # Capped like the drafting loop, for the same reason: stop a stuck
    # research pass from running away with tool calls indefinitely.
    turns = 0
    while response.stop_reason == "pause_turn" and turns < 6:
        turns += 1
        messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response.content},
        ]
        response = client.messages.create(
            model=model, max_tokens=2048, system=_SYSTEM, tools=_TOOLS, messages=messages,
        )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("Model returned no research.")
    return text


_researching_lock = threading.Lock()
_researching: set[tuple[int, int]] = set()

# Same in-memory, per-lead, single-attempt bookkeeping as
# candidates._last_error, for the same reason: this runs in a background
# thread so the HTTP response is sent long before anything can succeed or
# fail, and the dashboard learns the outcome by polling.
_last_error: dict[tuple[int, int], str] = {}
_MAX_ERROR_CHARS = 300


def is_researching(campaign_id: int, lead_id: int) -> bool:
    return (campaign_id, lead_id) in _researching


def last_error(campaign_id: int, lead_id: int) -> str | None:
    return _last_error.get((campaign_id, lead_id))


def research_contact_in_background(campaign_id: int, lead_id: int) -> bool:
    """Starts the lookup in a background thread and returns immediately.
    Returns False (no-op) if this lead is already being researched, so a
    double-click/poll can't stack calls."""
    key = (campaign_id, lead_id)
    with _researching_lock:
        if key in _researching:
            return False
        _researching.add(key)
        _last_error.pop(key, None)  # this attempt's outcome, not the last one's

    def _worker():
        try:
            with db.db_session() as conn:
                lead_row = db.get_lead_state(conn, lead_id, campaign_id)
            if lead_row is None:
                _last_error[key] = "No lead found."
                return
            lead = {
                "name": lead_row["name"],
                "company": lead_row["company"],
                "email": lead_row["email"],
                "website": lead_row["website"],
            }
            thread_text = ""
            try:
                thread = pipeline.fetch_normalized_thread(campaign_id, lead_id)
                if thread:
                    thread_text = render_thread_text(thread)
            except Exception:
                # Fail-soft: a thread fetch hiccup shouldn't block researching
                # the company itself from the lead/company data alone.
                log.exception(
                    "lead_research: thread fetch failed for %s/%s", campaign_id, lead_id
                )

            summary = research_contact(lead, thread_text)
            with db.db_session() as conn:
                db.upsert_lead_state(
                    conn, lead_id, campaign_id,
                    contact_research=summary, contact_researched_at=db.now_iso(),
                )
            log.info("contact research stored for lead %s/%s", campaign_id, lead_id)
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            _last_error[key] = detail[:_MAX_ERROR_CHARS]
            log.exception("contact research failed for %s/%s", campaign_id, lead_id)
        finally:
            with _researching_lock:
                _researching.discard(key)

    threading.Thread(target=_worker, daemon=True).start()
    return True
