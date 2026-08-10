"""Exports leads that have gone quiet after 3+ of our follow-ups since their
own last message into per-persona CSVs for manual LinkedIn outreach.

This is a one-off worklist generator, separate from the automated
reply/follow-up pipeline (app/pipeline.py, app/scheduler.py) — it doesn't touch
leads_state/drafts/candidates. Client-agnostic: takes its own Smartlead
api_key, category names, and persona map (Smartlead from_name -> persona
label) so it can run against Mindaptive's own account or a client's (e.g.
Aerodefense), each with its own set of sending personas.
"""
import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from app import smartlead
from app.config import settings
from app.detector import NormalizedMessage, normalize_thread
from app.email_clean import to_plain_text

log = logging.getLogger("lead_export")

# "3+ follow-ups since they last wrote" = we replied to their last message and
# then followed up at least 2 more times (3 of our messages total after their
# last reply), and they haven't answered since.
MIN_SENT_AFTER_LAST_REPLY = 3

SUMMARY_SYSTEM = (
    "You summarize a cold-outreach email thread for a salesperson who is about "
    "to follow up on LinkedIn. In 50-100 words, plain prose, describe what was "
    "discussed: what we offered, what the lead said or asked, and where things "
    "stalled. No headers, no bullet points, no commentary about the summary "
    "itself — just the description."
)


@dataclass
class ExportConfig:
    label: str  # e.g. "aerodefense" — used only in logging
    api_key: str
    category_names: list[str]
    persona_from_names: dict[str, str]  # Smartlead from_name -> persona label (CSV file name)
    output_dir: Path
    # alias -> canonical display name, for senders from *retired* mailboxes
    # (old_inboxes rows) — not discoverable from the current /email-accounts
    # list since those mailboxes are long gone, so this is supplied by whoever
    # knows the account's history. Local-part conventions vary per old
    # campaign/domain ("anna@...", "anna.sabryan@...", "sabryan.anna@...",
    # "l.ziemba@..." all seen for the same two people), so both first name and
    # surname are mapped to the same canonical label rather than relying on
    # one substring match per person.
    known_prior_senders: dict[str, str] = field(default_factory=dict)


@dataclass
class ExportRow:
    full_name: str
    company_name: str
    company_website: str
    linkedin: str
    phone: str
    secondary_email: str
    email: str
    sender_name: str
    thread_summary: str
    last_message_sent_at: str


_CSV_FIELDS = [
    "full_name", "company_name", "company_website", "linkedin", "phone",
    "secondary_email", "email", "sender_name", "thread_summary", "last_message_sent_at",
]


def _first_nonempty(*values: str | None) -> str:
    for v in values:
        if v:
            return v
    return ""


# Smartlead's own `website` field (populated by whichever scraping/enrichment
# tool built the campaign, long before this export runs) has been observed
# holding garbage on real Aerodefense leads: a generic directory-listing page,
# and — worse — a link to a news article about a BBB complaint against the
# company ("You cannot trust him: consumers tell BBB that ... failed to
# properly install cameras"). That's not this company's site and would be
# actively embarrassing to hand to the client as "company website", so any
# candidate URL is checked against this blocklist before being used.
_BAD_WEBSITE_PATTERNS = (
    "bbb.org", "cannot-trust", "cannot trust", "ripoffreport", "consumeraffairs",
    "complaint", "lawsuit", "scam", "muddyrivernews", "home-security.com/near-me",
    "yelp.com", "angi.com", "angieslist", "thumbtack.com", "yellowpages.com",
    "manta.com", "houzz.com",
)


def _looks_like_real_company_site(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return not any(p in lowered for p in _BAD_WEBSITE_PATTERNS)


def _extract_custom(custom_fields: dict, *exact_keys: str) -> str:
    """Look up a value by trying known custom_fields key spellings
    (case/underscore/space-insensitive) — key names vary across campaigns
    since each was populated by a different scraping/enrichment source (e.g.
    "LinkedIn_URL" vs "profileUrl" vs "Company_LinkedIn_URL"). Matches on
    normalized equality rather than substring — a loose substring match on
    "domain" would wrongly hit "Email_Domain_Catchall" (a true/false
    deliverability flag, not a website), and "linkedin" would hit
    "icebreakerLinkedIn" (personalization prose, not a URL) — both observed in
    real Aerodefense campaign data across ~90 sampled leads."""
    normalized = {
        key.lower().replace("_", "").replace(" ", ""): value
        for key, value in (custom_fields or {}).items()
        if value
    }
    for k in exact_keys:
        if k in normalized:
            return str(normalized[k])
    return ""


def _normalize_lead_full(raw: dict, campaign_id: int) -> dict:
    """Like smartlead.normalize_lead, plus the extra fields this export needs
    (phone/LinkedIn/website/last name) that the main drafting pipeline doesn't."""
    inner = raw.get("lead") if isinstance(raw.get("lead"), dict) else raw
    custom_fields = inner.get("custom_fields") or raw.get("custom_fields") or {}
    return {
        "id": inner.get("id") or raw.get("lead_id") or raw.get("id"),
        "campaign_id": campaign_id,
        "email": inner.get("email") or raw.get("email") or "",
        "first_name": inner.get("first_name") or raw.get("first_name") or "",
        "last_name": inner.get("last_name") or raw.get("last_name") or "",
        "company_name": inner.get("company_name") or raw.get("company_name") or "",
        "website": inner.get("website") or raw.get("website") or "",
        "company_url": inner.get("company_url") or raw.get("company_url") or "",
        "phone_number": inner.get("phone_number") or raw.get("phone_number") or "",
        "linkedin_profile": inner.get("linkedin_profile") or raw.get("linkedin_profile") or "",
        "custom_fields": custom_fields,
        "lead_category_id": raw.get("lead_category_id") or inner.get("lead_category_id"),
    }


def _qualifies(thread: list[NormalizedMessage]) -> bool:
    last_reply_idx = None
    for i, msg in enumerate(thread):
        if msg.kind == "reply":
            last_reply_idx = i
    if last_reply_idx is None:
        return False
    after = thread[last_reply_idx + 1:]
    sent_after = [m for m in after if m.kind == "sent"]
    reply_after = [m for m in after if m.kind == "reply"]
    return len(sent_after) >= MIN_SENT_AFTER_LAST_REPLY and not reply_after


def _summarize_thread(thread: list[NormalizedMessage]) -> str:
    lines = []
    for msg in thread:
        speaker = "US" if msg.kind == "sent" else "LEAD"
        text = to_plain_text(msg.body)
        if text:
            lines.append(f"[{msg.timestamp.date().isoformat()}] {speaker}: {text}")
    transcript = "\n\n".join(lines)
    if not transcript:
        return ""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        resp = client.messages.create(
            model=settings.anthropic_translate_model,
            max_tokens=300,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": transcript}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception:
        log.exception("thread summary failed")
        return ""


def _load_persona_map(config: ExportConfig) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Exact from_email -> persona map from Smartlead's current email-accounts
    list, plus name-hint tuples per persona (derived from the persona label
    itself) for the fallback below."""
    mapping: dict[str, str] = {}
    for account in smartlead.list_email_accounts(api_key=config.api_key):
        persona = config.persona_from_names.get(account.get("from_name", ""))
        email = (account.get("from_email") or "").lower()
        if persona and email:
            mapping[email] = persona
    hints = {persona: (persona.lower(),) for persona in set(config.persona_from_names.values())}
    return mapping, hints


FALLBACK_PERSONA = "old_inboxes"


def _sender_display_name(email: str, known_prior_senders: dict[str, str] | None = None) -> str:
    """Readable identifier for whichever mailbox actually sent the thread —
    used on old_inboxes rows where the sender isn't one of the current three
    personas, so the SDR team can still see who it was. Checks known prior
    senders' name aliases (first name and surname) as a substring match first,
    since the same person's local part varies wildly across old
    campaigns/domains ("anna@...", "anna.sabryan@...", "sabryan.anna@...",
    "l.ziemba@..." were all observed for just two people on real Aerodefense
    data) — splitting/title-casing each address individually produced a
    different mangled label per format ("Anna", "Anna S", "Annasabryan",
    "L Ziemba") for what should be one consistent name per person. Falls back
    to title-casing the whole local part for a sender not in that known list."""
    local = (email or "").split("@", 1)[0]
    if not local:
        return ""
    lowered = local.lower()
    for alias, canonical in (known_prior_senders or {}).items():
        if alias.lower() in lowered:
            return canonical
    parts = [p for p in re.split(r"[._+-]+", local) if p]
    return " ".join(p.capitalize() for p in parts) if parts else local.capitalize()


def _guess_persona(email: str, hints: dict[str, tuple[str, ...]]) -> str:
    """Fallback for a sending mailbox that's since been paused/retired and no
    longer shows up in the current email-accounts list — mirrors
    app/signatures.py's _guess_persona_file, matching the persona's first name
    against the mailbox's local part. If that fails too, the mailbox isn't one
    of the current personas at all (e.g. old campaigns sent by
    anna@/linda@/lexi.r@ from before the current Andrew/Amy/Max setup) — those
    still land in a CSV (FALLBACK_PERSONA) rather than being silently dropped."""
    local = email.split("@", 1)[0].lower()
    for persona, needles in hints.items():
        if any(needle in local for needle in needles):
            return persona
    return FALLBACK_PERSONA


def build_row(lead: dict, thread: list[NormalizedMessage], sender_name: str) -> ExportRow:
    """One export row from a `_normalize_lead_full` lead plus its thread.

    Shared by the whole-account CSV sweep (`run_export`) and the per-lead
    dashboard button (app/exports/sheet_export.py), so the field-picking rules
    below — which custom_fields alias wins, which websites are rejected — hold
    the same in both. `thread_summary` costs one Haiku call per row.
    """
    custom_fields = lead["custom_fields"]
    full_name = _first_nonempty(
        " ".join(p for p in (lead["first_name"], lead["last_name"]) if p).strip(),
        _extract_custom(custom_fields, "fullname", "name"),
    )
    # companyNickname (when present) is a cleaned-up name meant for
    # outreach personalization — preferred over the raw company_name,
    # which on some leads carries AI-research citation artifacts
    # baked in by the enrichment tool, e.g. "Security Camera Guru -
    # Camera Installer[1][2][3]".
    company_name = _first_nonempty(
        _extract_custom(custom_fields, "companynickname"),
        lead["company_name"],
        _extract_custom(custom_fields, "companyname"),
    )
    # Personal LinkedIn (for outreach), not the company page — keys
    # prefixed "Company_" (e.g. Company_LinkedIn_URL) are excluded by
    # only matching the bare aliases below.
    linkedin = _first_nonempty(
        lead["linkedin_profile"],
        _extract_custom(custom_fields, "linkedinurl", "profileurl"),
    )
    phone = _first_nonempty(
        lead["phone_number"], _extract_custom(custom_fields, "phone", "mobilenumber"),
    )
    website_candidates = (
        lead["website"], lead["company_url"],
        _extract_custom(custom_fields, "companydomain", "url"),
    )
    website = _first_nonempty(
        *(c for c in website_candidates if _looks_like_real_company_site(c))
    )
    secondary_email = _extract_custom(custom_fields, "personalemail")

    sent_messages = [m for m in thread if m.kind == "sent"]
    last_sent = sent_messages[-1] if sent_messages else None

    return ExportRow(
        full_name=full_name,
        company_name=company_name,
        company_website=website,
        linkedin=linkedin,
        phone=phone,
        secondary_email=secondary_email,
        email=lead["email"],
        sender_name=sender_name,
        thread_summary=_summarize_thread(thread),
        last_message_sent_at=last_sent.timestamp.isoformat() if last_sent else "",
    )


def run_export(config: ExportConfig) -> dict[str, list[ExportRow]]:
    categories = smartlead.fetch_categories(api_key=config.api_key)
    target_cat_ids = {categories[name] for name in config.category_names if name in categories}
    missing = [name for name in config.category_names if name not in categories]
    if missing:
        log.warning("categories not found in Smartlead account: %s", missing)

    persona_map, persona_hints = _load_persona_map(config)
    rows_by_persona: dict[str, list[ExportRow]] = {
        p: [] for p in set(config.persona_from_names.values())
    }

    for campaign in smartlead.list_campaigns(api_key=config.api_key):
        campaign_id = campaign.get("id")
        if campaign_id is None:
            continue
        for raw_lead in smartlead.list_campaign_leads(campaign_id, api_key=config.api_key):
            lead = _normalize_lead_full(raw_lead, campaign_id)
            if lead["id"] is None or lead["lead_category_id"] not in target_cat_ids:
                continue

            raw_history = smartlead.get_message_history(
                campaign_id, lead["id"], api_key=config.api_key
            )
            thread = normalize_thread(raw_history)
            if not _qualifies(thread):
                continue

            sent_messages = [m for m in thread if m.kind == "sent"]
            last_sent = sent_messages[-1] if sent_messages else None
            sender_email = (last_sent.from_email if last_sent else "").lower()
            persona = persona_map.get(sender_email) or _guess_persona(sender_email, persona_hints)
            # For a current persona's own mailbox, the sender IS the persona.
            # For the old_inboxes fallback, the persona label says nothing
            # about who actually wrote these — surface that separately so the
            # SDR team knows it was e.g. Anna/Lexi/Linda, not one of the three.
            sender_name = (
                persona if persona != FALLBACK_PERSONA
                else _sender_display_name(sender_email, config.known_prior_senders)
            )
            rows_by_persona.setdefault(persona, [])
            rows_by_persona[persona].append(build_row(lead, thread, sender_name))
            log.info(
                "export[%s]: qualifying lead %s (%s) -> persona=%s",
                config.label, lead["id"], lead["email"], persona,
            )

    _write_csvs(rows_by_persona, config.output_dir)
    return rows_by_persona


def _write_csvs(rows_by_persona: dict[str, list[ExportRow]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for persona, rows in rows_by_persona.items():
        path = output_dir / f"{persona}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: getattr(row, field) for field in _CSV_FIELDS})
        log.info("wrote %d rows to %s", len(rows), path)
