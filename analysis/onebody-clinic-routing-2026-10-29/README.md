# OneBody clinic routing update, 29 October 2026

Authority: Andrew relayed Kurt's exclusion of Twickenham, Battersea, Chiswick,
Finsbury Park and Vauxhall from free sessions because they are fully booked.
Andrew explicitly clarified that "Sessionet" does not exist.

The responder knowledge, system prompt and templates now prohibit all free
offer types at those five clinics, overriding old emails, prior research and
nearestClinic. Twickenham was removed from the priority list, leaving nine
clinics eligible for 45-minute massage. Links, code, fee and sharing terms
remain governed by booking-options.md.

`postcode-distances.json` records all 43 directory clinics, Postcodes.io
centroids and Haversine rankings after the exclusions. Holborn's terminated
postcode was resolved through the terminated-postcode endpoint and marked
as such; it is not a recommended replacement. Rankings are straight-line
clinic-to-clinic estimates, not journeys from a lead's home or office and
not live slot availability. clinic-routing.md contains the operational map
and official address-check links.

Validation: nine priority clinics, no excluded replacement, all 45-minute
massage replacements on the priority list, routing included in the assembled
drafting prompt, Twickenham classified non-priority, git diff whitespace check.

Six prompt/knowledge assets were copied to the production OneBody service
and its server checkout with backups. Only app-onebodyldn was restarted to
refresh the cached prompt. Production verification matched the local prompt
SHA-256 and returned dashboard HTTP 200. Existing booking-priority cells were
refreshed using scripts.backfill_booking_priority: 56 rows, 12 Yes, 38 No,
6 Unknown. Original sheet values are backed up by that script beside the
production database. deployment.txt and live-verification.txt record results.

This update changes future generated drafts. It does not rewrite already
stored drafts, campaign lead fields or Smartlead sequence copy.
