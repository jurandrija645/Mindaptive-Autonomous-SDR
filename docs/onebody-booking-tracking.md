# OneBodyLDN booking tracking

## Current configuration

As of 2026-10-22, all three partnership appointments use `VIP8401`.
Booking tracking depends on runtime configuration and the live n8n workflow;
editing the offer knowledge alone does not update either of these.

- Server `.env.onebodyldn`: `BOOKING_MATCH_CODES=VIP8401,OBLACCESS55,OBLACCESS25`.
  Retain the old codes to catch bookings from already-sent offers.
- Active n8n workflow: `Booking notification`, ID `4RX1d7HRFweHRjLH`.
- Outlook trigger polls every minute for `noreply@onebodyldn.com`, uses Raw
  output (full body), and includes both read and unread messages. Reading an
  email before the next poll must not make the booking invisible.
- The Code node runs `clients/onebodyldn/booking-extractor.js`, embedded in
  `clients/onebodyldn/n8n-booking-workflow.json`. Update both copies together.
  It processes every input item, parses HTML table cells and plain text,
  normalizes code case, and forwards only the approved codes. A blank
  `Discount Code` must not absorb the following `Discount Code Value` line.
- The HTTP node posts to OneBody's booking-confirmed webhook and retries
  failed delivery five times, five seconds apart.

No appointment-type filter is used: physio, 20-minute massage and 45-minute
massage bookings with the code follow the same path.

## Matching and accounting

The notification's actual `Location` is stored in Bookings column G (`location`).
Column M (`priority_location`) contains `Yes`, `No`, or `Unknown`, based on the
current ten priority clinics in `knowledge/booking-options.md`. The One Body LDN
prefix and punctuation/case differences are normalized. Missing or unrecognized
clinic names stay `Unknown`; the campaign or nearest-clinic field is never used
to guess where someone booked. Booking Summary includes totals for all three.
Existing sheet columns retain their positions. Notification retries can fill a
missing location and refresh priority without appending a duplicate booking.
After a priority-list change, run `python -m scripts.backfill_booking_priority`
inside the OneBody container to refresh existing rows from recorded locations.
The command saves the pre-migration sheet values beside the database.

The webhook first matches a known lead by email. With an approved code it
can also match an unambiguous normalized name when a person uses a different
address. Known matches are marked booked and their follow-ups stopped.
Bookings without a known lead are still recorded in the Google Sheets
Bookings tab as shared-code bookings; they do not create a guessed Smartlead
lead. Replaying a notification is safe because the Outlook message ID is the
booking ID used for deduplication.

Ambiguous names require manual resolution (HTTP 409). A failed shared-code
sheet write returns HTTP 503 so n8n retries. Exhausted retries remain failed
n8n executions and need reconciliation; five attempts are not a permanent
recovery queue. Changes of notification sender or format need a fresh check.
This workflow records bookings; it does not enforce the one-use offer rule
or charge repeat users.

## Production audit, 2026-10-22

Before correction, the server allowed only `OBLACCESS55` and `OBLACCESS25`.
The active workflow requested simplified previews, filtered unread messages,
and extracted just one item from a poll. Failed executions also showed an
empty code being read as `DISCOUNT CODE VALUE: 0`.

Updated the actual server environment, recreated only the OneBody responder,
and updated and activated the existing n8n workflow while preserving its
Outlook connection and webhook authentication. Confirmed the active version
matches the updated version.

Queried the connected Outlook mailbox across folders, including read mail,
for the notification sender from 1 October through the audit on 22 October:
578 messages, no `VIP8401` bookings yet, and 12 `OBLACCESS55` bookings.
Replayed all 12 approved-code notifications through the real webhook: all
returned HTTP 200 and sheet status `duplicate`, confirming they were already
recorded. Four matched known leads; eight were shared-code bookings. No
additional booking was recovered in this audit. The mailbox was read without
changing message read status.

Verified the actual JavaScript extractor against the full mailbox messages
and ran 13 focused booking and OneBody regression tests successfully.

Repository pushes alone do not activate a workflow or change server `.env`
files. Future changes must verify both deployed settings and active n8n
version, then reconcile relevant historical notifications through the
idempotent webhook. Do not send fabricated bookings to production as tests.
