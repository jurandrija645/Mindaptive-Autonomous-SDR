"""Fill booking priority from recorded clinic locations, without replaying bookings."""
import json
from datetime import datetime, timezone
from pathlib import Path

from app import client_assets, interested_sheet, sheets
from app.config import settings


def main():
    sid = settings.interested_sheet_id
    if not sid or not client_assets.priority_clinics():
        raise SystemExit("Run in the connected OneBody container with its clinic priority list")
    # Save existing cells before the additive migration.
    before = sheets.read_range(sid, interested_sheet.BOOKINGS_TAB, "A1:M")
    folder = Path(settings.db_path).parent / "booking-priority-backfill"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (folder / f"{stamp}.json").write_text(json.dumps(before), encoding="utf-8")
    interested_sheet._ensure_booking_tabs(sid)
    rows = interested_sheet._booking_rows(sid)
    data = []
    counts = dict(Yes=0, No=0, Unknown=0)
    for number, row in rows:
        if not row[0]:
            continue
        priority = client_assets.booking_location_priority(row[6])
        counts[priority] += 1
        data.append(dict(range=f"'Bookings'!M{number}", values=[[priority]]))
    if data:
        sheets._request("POST", f"/{sid}/values:batchUpdate",
                        json=dict(valueInputOption="RAW", data=data))
    actual = interested_sheet._booking_rows(sid)
    assert all(row[12] == client_assets.booking_location_priority(row[6])
               for _, row in actual if row[0]), "Priority verification failed"
    print(json.dumps(dict(updated=len(data), **counts)), flush=True)


if __name__ == "__main__":
    main()
