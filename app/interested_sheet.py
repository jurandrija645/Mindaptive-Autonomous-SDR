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

This spreadsheet is also the booking attribution record. The Bookings tab holds
every booking: each confirmation email with an allowlisted offer code, including
a person who was never in Smartlead and received a shared code from a colleague,
and every known lead marked booked any other way (their own reply, a category
change, a hand-ticked `booked` cell) — those arrive as unconfirmed rows, written
immediately for a reply and by reconcile_bookings after each daily scan.
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

# Key prefix for a booking we know happened but have no confirmation email for
# (the lead told us in a reply, the category was set by hand or in Smartlead,
# or it predates the Bookings tab). The confirmation email, if it arrives
# later, replaces this row in place rather than adding a second one.
UNCONFIRMED_PREFIX = "unconfirmed:"

_BOOKING_KEY_COL = 0
_BOOKING_EMAIL_COL = 5
_BOOKING_LEAD_ID_COL = 11


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
    values = [
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
    ]
    try:
        _ensure_booking_tabs(sheet_id)
        rows = _booking_rows(sheet_id)
        if any(row[_BOOKING_KEY_COL] == key for _, row in rows):
            return "duplicate"
        # One lead, one free session: an unconfirmed row and the confirmation
        # email for the same lead are the same booking, whichever lands first.
        existing = next(
            (
                (row_number, row) for row_number, row in rows
                if lead_id is not None and row[_BOOKING_LEAD_ID_COL] == str(lead_id)
            ),
            None,
        )
        if existing is not None:
            row_number, row = existing
            if key.startswith(UNCONFIRMED_PREFIX):
                return "duplicate"
            if row[_BOOKING_KEY_COL].startswith(UNCONFIRMED_PREFIX):
                sheets.write_range(sheet_id, BOOKINGS_TAB, f"A{row_number}", values)
                log.info("interested_sheet: confirmed booking %s (row %s)", key, row_number)
                return "recorded"
        sheets.append_row(sheet_id, BOOKINGS_TAB, values)
        log.info("interested_sheet: recorded booking %s (%s)", key, attribution)
        return "recorded"
    except Exception:
        log.exception("interested_sheet: failed to record booking %s", key)
        return "failed"


def _booking_rows(sheet_id: str) -> list[tuple[int, list[str]]]:
    """Bookings data rows as (sheet row number, 12 stripped cells)."""
    width = len(BOOKINGS_HEADER)
    return [
        (row_number, ([str(cell).strip() for cell in cells] + [""] * width)[:width])
        for row_number, cells in enumerate(
            sheets.read_range(sheet_id, BOOKINGS_TAB, "A2:L"), start=2
        )
    ]


def record_lead_booking(
    *,
    campaign_id: int | None,
    lead_id: int | None,
    email: str,
    name: str,
    booked_at: str,
    source: str,
) -> str:
    """A known lead booked, but no confirmation email is in hand to record.

    Written as an unconfirmed row so the Bookings tab holds every booking, not
    only the ones the booking webhook saw. `source` lands in matched_by so the
    row says how we know."""
    booking_id = (
        f"{UNCONFIRMED_PREFIX}{campaign_id}:{lead_id}" if lead_id is not None
        else f"{UNCONFIRMED_PREFIX}{email.strip().lower()}"
    )
    return record_booking(
        booking_id=booking_id,
        email=email,
        name=name,
        recorded_at=booked_at,
        attribution=ATTRIBUTION_CONTACTED,
        matched_by=source,
        campaign_id=campaign_id,
        lead_id=lead_id,
    )


def reconcile_bookings(booked_leads: list[dict]) -> int:
    """Make sure every booking we know of has a row in the Bookings tab.

    Two sources: leads the database has as booked (`booked_leads`, dicts with
    campaign_id/lead_id/email/name/booked_at) and rows ticked `booked` in the
    Interested tab, which includes hand edits. A booking already present by
    lead id or by email is left alone. Returns how many rows were added."""
    sheet_id = settings.interested_sheet_id
    if not sheet_id:
        return 0
    try:
        _ensure_booking_tabs(sheet_id)
        rows = [row for _, row in _booking_rows(sheet_id)]
        known_ids = {row[_BOOKING_LEAD_ID_COL] for row in rows if row[_BOOKING_LEAD_ID_COL]}
        known_emails = {row[_BOOKING_EMAIL_COL].lower() for row in rows if row[_BOOKING_EMAIL_COL]}

        wanted = [dict(lead, source="lead_status") for lead in booked_leads]
        _ensure_tab(sheet_id)
        for cells in sheets.read_range(sheet_id, TAB, "A2:G"):
            values = [str(cell).strip() for cell in cells] + [""] * (7 - len(cells))
            if values[6].upper() != "TRUE":
                continue
            wanted.append({
                "name": values[0],
                "email": values[2],
                "campaign_id": int(values[3]) if values[3].isdigit() else None,
                "lead_id": int(values[4]) if values[4].isdigit() else None,
                "booked_at": values[5],
                "source": "interested_sheet",
            })

        added = 0
        for lead in wanted:
            email = (lead.get("email") or "").strip()
            lead_id = lead.get("lead_id")
            if (lead_id is not None and str(lead_id) in known_ids) or (
                email and email.lower() in known_emails
            ):
                continue
            if lead_id is None and not email:
                continue
            status = record_lead_booking(
                campaign_id=lead.get("campaign_id"),
                lead_id=lead_id,
                email=email,
                name=lead.get("name") or "",
                booked_at=lead.get("booked_at") or "",
                source=lead["source"],
            )
            if status == "recorded":
                added += 1
            if lead_id is not None:
                known_ids.add(str(lead_id))
            if email:
                known_emails.add(email.lower())
        if added:
            log.info("interested_sheet: reconciled %d missing booking(s)", added)
        return added
    except Exception:
        log.exception("interested_sheet: failed to reconcile bookings")
        return 0


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
