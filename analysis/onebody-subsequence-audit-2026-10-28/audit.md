# OneBody response and subsequence audit — 28 October 2026

Four active native Smartlead subsequences contain 16 leads. All 14 leads in
the two parents' current Interested in 45 Physio/Sports categories are enrolled
exactly once in the corresponding child campaign. Two additional child
members, Sean and Lila, have Meeting Booked in their parent and were explicitly
paused in the child during this audit. Four campaigns remain ACTIVE.

## Changes applied

- Deployed OneBody system prompt, booking rules, business overview and response
  templates to the production source and running OneBody container; restarted
  OneBody to invalidate its cached system prompt. File hashes match local files.
- All three booking offers require the £4.99 fee that holds the time slot and
  the company-personalized sharing line. No old massage-fee prohibition remains.
- Updated all 16 email steps in the four Smartlead subsequences in place. All
  include the fee, VIP8401 and `each person at {{company_name}} gets one free
  session`. Removed `{{nearestClinic}}` in favor of letting the lead choose.
  Existing step IDs, cadence, memberships and scheduled timestamps were checked.
- Production model probe (claude-haiku-4-5) returned the correct 45-minute sports
  massage link, £4.99 slot fee and `each person at TPXimpact gets one free
  session`. This was a generation-only probe; no message was sent or stored.

## Schedule verification

First message waits 48 hours from child enrollment (the step itself shows zero
days because the initial wait is stored elsewhere). Seven first messages are
eligible today, 28 October: Anzar, Dom, Issy, Ben, Faz, Harry and Jonathan.
Their scheduled window is 11:48–13:57 London / 12:48–14:57 Zagreb. These are
Smartlead's scheduled eligibility times, not confirmations of actual delivery.
Weekday campaign window is 08:00–18:00 London; mailbox pacing can add delay.

| Lead | Company in Smartlead | State | Next eligibility, London | Zagreb | Notes |
| --- | --- | --- | --- | --- | --- |
| Sam | Rogers, Coleridge & White Limited | STARTED | 29 Oct 13:57 | 29 Oct 14:57 |  |
| Anzar | Seedlegals | STARTED | 28 Oct 11:48 | 28 Oct 12:48 |  |
| Dom | Cavell | STARTED | 28 Oct 11:49 | 28 Oct 12:49 |  |
| Sean | Rg Jones Sound Engineering Ltd | PAUSED | — | — | Already Meeting Booked in parent; child explicitly paused. |
| Harry | Alicorn Digital | STARTED | 28 Oct 13:56 | 28 Oct 14:56 |  |
| Marios | Ravelin Technology | STARTED | 29 Oct 10:37 | 29 Oct 11:37 |  |
| Emre | Redcloud | STARTED | 29 Oct 13:56 | 29 Oct 14:56 |  |
| Devon | Somebody Digital | STARTED | 29 Oct 20:42 | 29 Oct 21:42 | 48-hour timestamp is outside 08:00–18:00 London; earliest next permitted window is Friday 30 Oct. |
| Natalia | Tpximpact | B Corp™ | STARTED | 30 Oct 09:09 | 30 Oct 10:09 |  |
| Issy | Impero | STARTED | 28 Oct 11:51 | 28 Oct 12:51 |  |
| Ben | Hawes & Co | INPROGRESS | 28 Oct 13:55 | 28 Oct 14:55 | Thank-you preceded manual enrollment. Active, step 0, original first-send time restored and read back. |
| Faz | Pink Squid | STARTED | 28 Oct 13:55 | 28 Oct 14:55 |  |
| Angie | Goldfinch | STARTED | 29 Oct 10:37 | 29 Oct 11:37 | Latest reply offered Clerkenwell/Moorgate. Old Wimbledon custom field is no longer used by subsequence copy. |
| Lucia | Muza Lab | STARTED | 29 Oct 17:15 | 29 Oct 18:15 |  |
| Lila | Signal Ai | PAUSED | — | — | Already Meeting Booked in parent; child explicitly paused. |
| Jonathan | Beamery | STARTED | 28 Oct 13:57 | 28 Oct 14:57 |  |

## Verified limits

All assigned sending accounts still exist in the live account. All 16 steps
read back with the new wording. The two old drafted native 55-minute children
and the old local responder sequence were left as they were.

Smartlead did not propagate a parent's Meeting Booked pause to its child.
This audit repaired Sean and Lila; it did not add an ongoing cross-campaign
stop mechanism. Future parent bookings still require checking/pausing the
native child. Local `app/sequences.py` hooks protect only local sequences.

Angie's imported data associates her with Goldfinch finance/Wimbledon, while
her signature identifies Goldfinch Agency at Wharf Road. Automated clinic
personalization is removed globally; AI drafts must follow her latest thread.
No new clinic choice was invented or written over her imported custom fields.

Production source backups: `/root/onebody-booking-fix-2026-10-28/`.
Evidence JSON files are stored next to this report. Unrelated workspace edits
were preserved. Source changes have not been committed or pushed.
