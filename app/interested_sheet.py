"""Auto-sync of leads Smartlead has told us are Interested into a plain
worklist Google Sheet — separate from the LinkedIn export sheet
(app/exports/sheet_export.py), which is per-lead and manual, click-triggered
from the dashboard. This one is automatic: the moment app/reply_classifier.py
clears a reply as INTERESTED, a row lands here with no click required, from
both places that classify a reply (app/webhook.py: _process_reply and
app/scheduler.py: run_reply_catch_scan). Deduplicated on email, so a lead
re-confirmed INTERESTED on a later reply doesn't produce a second row.

Optional and client-agnostic — gated entirely by INTERESTED_SHEET_ID. Blank
(the default for every client) means every function here is a no-op, so
adding this for a client that wants it is just the env var, no code change.
Built for OneBodyLDN (see clients/onebodyldn/), which needed a live worklist
an external automation could read against to match booking confirmations —
but nothing here is OneBodyLDN-specific.

This sheet is a best-effort human-readable record, never the source of truth.
The booking-confirmed webhook (app/webhook.py: POST /webhooks/booking-confirmed)
matches a booked email against leads_state directly, not this sheet — a
hand-edited or stale row here must never be able to block a real booking from
being recorded. Every function fails soft: a Sheets outage must never block
drafting or the booking webhook's response.
"""

import logging

from app import sheets
from app.config import settings

log = logging.getLogger("interested_sheet")

TAB = "Interested"
# Column order fixes which letter each field lives in (email = C, booked = G)
# for _find_row and mark_booked below — keep those in sync if this changes.
HEADER = ["full_name", "company", "email", "campaign_id", "lead_id", "first_seen_at", "booked"]

_EMAIL_COLUMN = "C"
_BOOKED_COLUMN = "G"


def _ensure_tab(sheet_id: str) -> None:
    tabs = sheets.list_tabs(sheet_id)
    if any(t.strip().lower() == TAB.lower() for t in tabs):
        return
    sheets.create_tab(sheet_id, TAB)
    sheets.write_header(sheet_id, TAB, list(HEADER))
    log.info("interested_sheet: created tab %r with a header row", TAB)


def _find_row(sheet_id: str, email: str) -> int | None:
    email = email.strip().lower()
    if not email:
        return None
    for offset, cell in enumerate(sheets.read_column(sheet_id, TAB, _EMAIL_COLUMN)):
        if cell.strip().lower() == email:
            return offset + 1
    return None


def sync_interested(
    campaign_id: int, lead_id: int, email: str, name: str, company: str, first_seen_at: str
) -> None:
    """Append a row the first time this lead is seen as Interested.

    Deduplicated on email (same reasoning as sheet_export._find_duplicate): a
    lead re-classified INTERESTED on a later reply must not produce a second
    row."""
    sheet_id = settings.interested_sheet_id
    if not sheet_id or not email:
        return
    try:
        _ensure_tab(sheet_id)
        if _find_row(sheet_id, email) is not None:
            return
        sheets.append_row(
            sheet_id,
            TAB,
            [name or "", company or "", email, str(campaign_id), str(lead_id), first_seen_at, ""],
        )
        log.info("interested_sheet: added %s", email)
    except Exception:
        log.exception("interested_sheet: failed to sync %s", email)


def mark_booked(email: str) -> None:
    """Best-effort: write TRUE into the 'booked' column for this email's row.

    Purely cosmetic upkeep so the sheet stays honest for anyone reading it by
    eye — the booking webhook's actual state change (Smartlead category +
    db.mark_lead_booked) does not depend on this succeeding, or on the row
    existing at all (a lead who booked without ever showing up as Interested
    here — e.g. booked straight off the cold email with no reply — has no row
    to update, and that's fine)."""
    sheet_id = settings.interested_sheet_id
    if not sheet_id or not email:
        return
    try:
        _ensure_tab(sheet_id)
        row = _find_row(sheet_id, email)
        if row is None:
            return
        sheets.write_range(sheet_id, TAB, f"{_BOOKED_COLUMN}{row}", ["TRUE"])
        log.info("interested_sheet: marked %s booked (row %s)", email, row)
    except Exception:
        log.exception("interested_sheet: failed to mark %s booked", email)
