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

This spreadsheet is also the booking attribution record. Every booking made
with an allowlisted offer code lands in a separate Bookings tab, including a
person who was never in Smartlead and received a shared code from a colleague.
A small Booking Summary tab keeps the direct-vs-shared totals visible without
requiring a manual pivot table.

The Interested tab remains a best-effort human-readable record and constrained
booking lookup fallback: only an allowlisted offer code can enable exact-name
matching, and the sheet's campaign/lead IDs must still resolve to rows already
known in leads_state.
The booking-confirmed webhook (app/webhook.py: POST /webhooks/booking-confirmed)
matches a booked email against leads_state directly, not this sheet — a
hand-edited or stale row here must never be able to block a real booking from
being recorded. Every function fails soft: a Sheets outage must never block
drafting or the booking webhook's response.
"""

import hashlib
import logging

from app import db, sheets
from app.config import settings

log = logging.getLogger("interested_sheet")

TAB = "Interested"
BOOKINGS_TAB = "Bookings"
BOOKING_SUMMARY_TAB = "Booking Summary"
# Column order fixes which letter each field lives in (email = C, booked = G)
# for _find_row and mark_booked below — keep those in sync if this changes.
HEADER = ["full_name", "company", "email", "campaign_id", "lead_id", "first_seen_at", "booked"]

_EMAIL_COLUMN = "C"
_BOOKED_COLUMN = "G"

BOOKINGS_HEADER = [
    "booking_id",
    "recorded_at",
    "appointment_date",
    "appointment_time",
    "full_name",
    "email",
    "location",
    "discount_code",
    "attribution",
    "matched_by",
    "campaign_id",
    "lead_id",
]

ATTRIBUTION_CONTACTED = "Contacted lead"
ATTRIBUTION_SHARED = "Shared code / not contacted"


def _ensure_tab(sheet_id: str) -> None:
    tabs = sheets.list_tabs(sheet_id)
    if any(t.strip().lower() == TAB.lower() for t in tabs):
        return
    sheets.create_tab(sheet_id, TAB)
    sheets.write_header(sheet_id, TAB, list(HEADER))
    log.info("interested_sheet: created tab %r with a header row", TAB)


def _ensure_booking_tabs(sheet_id: str) -> None:
    tabs = sheets.list_tabs(sheet_id)
    normalized = {title.strip().lower() for title in tabs}
    if BOOKINGS_TAB.lower() not in normalized:
        sheets.create_tab(sheet_id, BOOKINGS_TAB)
        sheets.write_header(sheet_id, BOOKINGS_TAB, list(BOOKINGS_HEADER))
        log.info("interested_sheet: created tab %r", BOOKINGS_TAB)
    if BOOKING_SUMMARY_TAB.lower() not in normalized:
        sheets.create_tab(sheet_id, BOOKING_SUMMARY_TAB)
        sheets.write_range(
            sheet_id,
            BOOKING_SUMMARY_TAB,
            "A1",
            ["Metric", "Count"],
            raw=True,
        )
        sheets.write_range(
            sheet_id,
            BOOKING_SUMMARY_TAB,
            "A2",
            ["Total bookings", f"=COUNTA('{BOOKINGS_TAB}'!A2:A)"],
        )
        sheets.write_range(
            sheet_id,
            BOOKING_SUMMARY_TAB,
            "A3",
            [
                "Bookings from contacted leads",
                f'=COUNTIF(\'{BOOKINGS_TAB}\'!I2:I,"{ATTRIBUTION_CONTACTED}")',
            ],
        )
        sheets.write_range(
            sheet_id,
            BOOKING_SUMMARY_TAB,
            "A4",
            [
                "Additional bookings from shared code",
                f'=COUNTIF(\'{BOOKINGS_TAB}\'!I2:I,"{ATTRIBUTION_SHARED}")',
            ],
        )
        log.info("interested_sheet: created tab %r", BOOKING_SUMMARY_TAB)


def _booking_key(
    booking_id: str, email: str, name: str, date: str, time: str, location: str, code: str
) -> str:
    """Provider id when available; deterministic fallback makes retries safe."""
    if booking_id.strip():
        return booking_id.strip()
    material = "\n".join(
        value.strip().lower() for value in (email, name, date, time, location, code)
    )
    return "generated:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def record_booking(
    *,
    booking_id: str = "",
    email: str = "",
    name: str = "",
    code: str = "",
    location: str = "",
    appointment_date: str = "",
    appointment_time: str = "",
    recorded_at: str,
    attribution: str,
    matched_by: str = "",
    campaign_id: int | None = None,
    lead_id: int | None = None,
) -> str:
    """Record one booking in the shared spreadsheet.

    Returns ``recorded``, ``duplicate``, ``disabled`` or ``failed`` so the
    webhook can refuse to acknowledge an otherwise-untracked shared-code
    booking. Known Smartlead leads still keep their authoritative local state
    even when this human-readable sheet is temporarily unavailable.
    """
    sheet_id = settings.interested_sheet_id
    if not sheet_id:
        return "disabled"
    key = _booking_key(booking_id, email, name, appointment_date, appointment_time, location, code)
    try:
        _ensure_booking_tabs(sheet_id)
        if any(
            str(cell).strip() == key
            for cell in sheets.read_column(sheet_id, BOOKINGS_TAB, "A")[1:]
        ):
            return "duplicate"
        sheets.append_row(
            sheet_id,
            BOOKINGS_TAB,
            [
                key,
                recorded_at,
                appointment_date,
                appointment_time,
                name,
                email,
                location,
                code,
                attribution,
                matched_by,
                str(campaign_id) if campaign_id is not None else "",
                str(lead_id) if lead_id is not None else "",
            ],
        )
        log.info("interested_sheet: recorded booking %s (%s)", key, attribution)
        return "recorded"
    except Exception:
        log.exception("interested_sheet: failed to record booking %s", key)
        return "failed"


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


def find_by_name(name: str) -> list[dict]:
    """Resolve a trusted-code booking through the internal Interested sheet."""
    sheet_id = settings.interested_sheet_id
    wanted = db.normalize_person_name(name)
    if not sheet_id or not wanted:
        return []
    try:
        _ensure_tab(sheet_id)
        matches = []
        for row_number, cells in enumerate(sheets.read_range(sheet_id, TAB, "A2:G"), start=2):
            values = list(cells) + [""] * (7 - len(cells))
            if db.normalize_person_name(str(values[0])) != wanted:
                continue
            try:
                campaign_id, lead_id = int(values[3]), int(values[4])
            except (TypeError, ValueError):
                continue
            matches.append({
                "row": row_number,
                "name": str(values[0]),
                "email": str(values[2]),
                "campaign_id": campaign_id,
                "lead_id": lead_id,
            })
        return matches
    except Exception:
        log.exception("interested_sheet: failed to find booked name %s", name)
        return []


def mark_booked_match(*, email: str = "", name: str = "", lead_id: int | None = None) -> None:
    """Mark the exact sheet row using lead id, email, then normalized name."""
    sheet_id = settings.interested_sheet_id
    if not sheet_id:
        return
    try:
        _ensure_tab(sheet_id)
        rows = sheets.read_range(sheet_id, TAB, "A2:G")
        wanted_name = db.normalize_person_name(name)
        wanted_email = email.strip().lower()
        for row_number, cells in enumerate(rows, start=2):
            values = list(cells) + [""] * (7 - len(cells))
            row_lead_id = str(values[4]).strip()
            matches = (
                (lead_id is not None and row_lead_id == str(lead_id))
                or (lead_id is None and wanted_email and str(values[2]).strip().lower() == wanted_email)
                or (lead_id is None and not wanted_email and wanted_name
                    and db.normalize_person_name(str(values[0])) == wanted_name)
            )
            if matches:
                sheets.write_range(sheet_id, TAB, f"{_BOOKED_COLUMN}{row_number}", ["TRUE"])
                log.info("interested_sheet: marked lead %s booked (row %s)", lead_id or email or name, row_number)
                return
    except Exception:
        log.exception("interested_sheet: failed to mark booking match")
