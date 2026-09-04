# Performance and immediate reply delivery

## Why the dashboard became slow

The responder was not slow in SQLite or browser rendering. Production probes
on 2026-09-04 showed `/api/inbox` at roughly 0.08–0.21 seconds while a lead
detail request alternated between roughly 0.4 seconds and 8–13 seconds. The
long delays match the cumulative sleeps in the old Smartlead 429 retry loop.

Three behaviours amplified that upstream throttling:

1. Every Smartlead request created a new HTTP client and TLS connection.
2. The five-minute reply catcher sent one bulk-history request per campaign in
   a burst (21 campaigns on Mindaptive), and repeated the separate new-reply
   poll at the start of the same pass.
3. `POST /api/drafts/{id}/send` ran synchronous Smartlead reads/writes directly
   on FastAPI's async event loop. One throttled send therefore froze unrelated
   dashboard requests. The browser then fetched the thread a third time.

## What now prevents it

- `app/smartlead.py` owns a reusable connection pool per API key.
- A per-key sliding-window limiter defaults to 50 requests/minute and 8/second.
- HTTP 429 honours `Retry-After`; fallback backoff has jitter and every throttle
  is logged without exposing the API key.
- Category definitions are cached for ten minutes.
- The reply catcher runs once a minute but rotates through the oldest fifth of
  campaigns. Every campaign retains approximately five-minute coverage without
  a 20-plus-request burst.
- `api_send` runs `_send_due_draft` in a worker thread, so the event loop stays
  responsive.
- The client updates the sent card locally instead of immediately issuing a
  third Smartlead thread read.
- Every complete thread fetched by the scan, webhook, draft generator, detail
  view or send race check is saved in `lead_threads`. The detail endpoint reads
  that cache whenever it is current and heals it after a live refresh.

Do not solve this by increasing Uvicorn workers. Every process currently starts
its own APScheduler, so additional workers would duplicate scans and sends.

## Immediate replies: source-of-truth order

Receipt and drafting are deliberately separate:

1. Validate the webhook secret and extract campaign/lead IDs.
2. Claim a durable `webhook_events` fingerprint. Direct Smartlead delivery,
   n8n forwarding and retries can therefore coexist without duplicate drafts.
3. Commit `db.mark_lead_replied` and stale older drafts before acknowledging.
4. Publish a `reply_received` Server-Sent Event. An open dashboard reloads the
   SQLite inbox immediately; the existing 15-second poll remains the fallback.
5. Return to the caller.
6. Classify, reconcile Smartlead, fetch the canonical thread, rate temperature
   and generate the draft in a background worker.

A classifier, model outage, delayed Smartlead thread, or deployment can delay a
draft, but it can no longer hide the reply itself.

## OneBodyLDN n8n workflow

Import `n8n-workflows/onebody-notifier.json`. It replaces the broken workflow
whose responder branch pointed at AeroDefense, referenced a nonexistent node,
omitted OneBody's webhook secret, and only forwarded classifier-approved mail.

Before activation:

1. Set `ONEBODY_WEBHOOK_SECRET` in the n8n container environment to exactly the
   OneBody responder's `SMARTLEAD_WEBHOOK_SECRET`, then restart n8n so `$env`
   can read it. Never paste the secret into exported workflow JSON.
2. Re-select the Slack credential if the imported credential ID does not map on
   that n8n installation.
3. Confirm the webhook path is the path Smartlead currently calls.
4. Activate the workflow and send a test reply.

The webhook has two branches:

- `Record in OneBody responder` posts the unwrapped Smartlead body to
  `https://onebody.mindaptive.ai/webhooks/smartlead`, with the secret header,
  a 10-second timeout and three retries.
- The existing classifier keeps `NOT_RELEVANT` replies out of Slack. Only its
  `RELEVANT` output proceeds through cleanup/Croatian translation to the channel
  and owner notifications.

Classification must never gate the responder-ingestion branch. It deliberately
does gate Slack notifications so rejections, out-of-office mail, unsubscribes
and automated acknowledgements do not notify the team.

## Direct Smartlead webhook (recommended)

The most reliable production topology registers the OneBody responder directly
with Smartlead and keeps n8n only for Slack. Smartlead's create-webhook API does
not expose custom headers, so use the query-secret form supported by the app:

```text
https://onebody.mindaptive.ai/webhooks/smartlead?secret=<SMARTLEAD_WEBHOOK_SECRET>
```

Register a user-level `EMAIL_REPLY` webhook in the OneBody Smartlead account.
Do this only after the new responder version is deployed. The query string is a
secret: do not paste it into tickets, commit it, or log full request URLs.

It is safe to leave the n8n forward active as a fallback because
`webhook_events.event_key` deduplicates repeat delivery.

## Verification checklist

For a OneBody test lead:

1. Send a human reply and verify the responder returns `accepted`.
2. Confirm the lead appears in the dashboard immediately, before drafting ends.
3. Confirm Slack receives the original message without waiting for a model.
4. Deliver the same payload twice and verify only one event/draft exists.
5. Open the same lead twice; the second open should be served from cache.
6. During a deliberately slow mocked send, `/api/inbox` must remain responsive.
7. Confirm a newer lead reply still makes an old draft stale.
8. Watch logs for `smartlead throttled`, `smartlead completed`, and
   `slow request`; none of those lines contains a full API key.

Run the local reliability suite with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Verification performed on 2026-09-04

- Python bytecode compilation completed for `app/` and `tests/`.
- All ten reliability tests passed. They cover cache population/use, durable
  webhook claims and retries, visibility-before-background-work, numeric
  and HTTP-date `Retry-After`, campaign rotation, send claiming/failure recovery,
  duplicate send rejection, and dashboard responsiveness during a slow send.
- `node --check app/static/app.js` passed.
- The replacement n8n workflow parsed as valid JSON.
- SQLite migration completed against the local development database;
  `PRAGMA quick_check` returned `ok`, both new tables exist, and `send_error`
  exists on `drafts`.
- A real send through Smartlead's reply endpoint used the designated safe test
  lead, Mindaptive Jones. Smartlead accepted it with `Email added to the queue,
  will be sent out soon!`.
- A Docker image could not be built on this workstation because Docker is not
  installed here. The production image build remains a rollout check, not a
  skipped application test.

The repository changes do not by themselves alter the running n8n instance or
the deployed containers. Import/activate the workflow and deploy the image in
the order below; until then production continues to run the old behaviour.

## Rollout

1. Set OneBody's server-side `DRY_RUN=false` and deploy the code.
2. Import and activate the corrected n8n workflow.
3. Test one real inbound reply and a duplicate delivery.
4. Register the direct Smartlead webhook.
5. Observe one complete five-minute reply-catch sweep.
6. Deploy the same image to Mindaptive/AeroDefense; pacing and caches are
   isolated by process and API key.
