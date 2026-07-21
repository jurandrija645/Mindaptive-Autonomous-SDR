# Smartlead API — how to look things up, and what's actually true

## Finding the documentation

**The pages we depend on are already mirrored into `docs/smartlead/`** — read
those first, no network needed. Refresh them with
`./.venv/Scripts/python -m scripts.fetch_smartlead_docs`; a `git diff` afterwards
shows exactly what Smartlead changed under us.

To look up anything not mirrored:

1. **`https://api.smartlead.ai/sitemap.xml`** is the complete, canonical page
   list (~200 pages). Reference pages live at
   `api-reference/<group>/<slug>` — groups include `campaigns`, `leads`,
   `inbox`, `email-accounts`, `webhooks`, `analytics`, `lead-lists`,
   `lead-tags`, `smart-delivery`, `smart-prospect`, `utilities`.
2. **Append `.md` to any docs URL to get its exact MDX source**, e.g.
   `…/api-reference/campaigns/reply-email-thread.md` → 3.6 KB of
   `<ParamField body="…" type="…" required>` declarations plus the real request
   and response examples. The rendered HTML page is ~670 KB of markup for the
   same content, and summarizing it risks inventing fields that aren't there —
   always fetch the `.md`.

There is **no OpenAPI/Swagger spec and no Postman collection** published:
`openapi.json`, `docs.json` and `mint.json` all 404, and the reference pages are
hand-written MDX (no `requestBody` schema anywhere in the markup), so the field
tables are prose, not generated. The `.md` source is the most authoritative
machine-readable form that exists.

Two traps:

- **`llms.txt` is not the documentation.** `https://api.smartlead.ai/llms.txt`
  (copied into the repo root as `SmartleadApi`) is only an index of section URLs
  and bare `METHOD /path` lines — no field schemas at all. The old `SmartleadApi`
  file is kept for orientation, but never treat it as a spec.
- **`llms-full.txt` is analytics-only.** Despite the name it covers only the
  analytics/reporting endpoints — no sending, leads, or inbox.
- A wrong slug does not 404; it silently returns a different endpoint's page.
  Always confirm the fetched page names the endpoint you meant.

## Ground truth is the live API, not the docs

Verified 2026-07-21 against the real API using the Mindaptive Jones test lead
(campaign `2538823`, lead `2758494567`). **Both endpoints this app depends on
most are documented incorrectly:**

### `POST /campaigns/{id}/reply-email-thread`

| | Documented | Actually observed |
|---|---|---|
| Success response | `{"success": true, "message": "Reply sent successfully"}` | plain text `Email added to the queue, will be sent out soon!` |
| Content-Type | `application/json` | `text/html` |

This is why `smartlead._request` checks `content-type` before calling `.json()`.

Request fields (documented list, matches observed behaviour):
`email_stats_id` (**required**), `email_body` (**required**), `to_email`,
`to_first_name`, `to_last_name`, `scheduled_time`, `reply_message_id`,
`reply_email_body`, `reply_email_time`, `cc`, `bcc`, `schedule_condition`,
`add_signature`, `seq_type`, `attachments[]` (`file_url` required, plus
`file_name`, `file_type`, `file_size`).

- **`lead_id` is NOT accepted** — rejected with "lead_id is not allowed"
  (real 400 in production). It isn't in the documented list either.
- **`to_email` IS accepted** — verified with a real send 2026-07-21. Docs say To
  otherwise defaults to the *lead email*, i.e. the imported address, which is
  wrong whenever outreach went to a generic `info@` and a real person replied
  from their own mailbox. The app always passes it explicitly (see
  `scheduler._send_due_draft`).
- `bcc`, `attachments`, `scheduled_time`, `add_signature` are available but
  unused so far.

### `GET /campaigns/{id}/leads/{id}/message-history`

The documented response shape is **entirely wrong**:

| | Documented | Actually observed |
|---|---|---|
| Wrapper key | `messages` | `history` |
| Per-message fields | `id`, `subject`, `direction`, `sent_at`, `opened_at`, `received_at` | `type`, `time`, `message_id`, `stats_id`, `from`, `to`, `cc`, `bcc`, `subject`, `email_body`, `attachments`, `reply_details` |

`app/detector.py: normalize_message` is written against the observed shape.
Note `message_id` (RFC822 header) and `stats_id` (Smartlead's internal id, what
`reply-email-thread` wants as `email_stats_id`) are different values.

Documented query params, not yet used: `event_time_gt` (ISO 8601),
`show_plain_text_response` (boolean).

### Response envelopes are inconsistent per endpoint

Some endpoints wrap in `{"data": [...]}`, others return a bare list,
`message-history` wraps in `{"history": [...]}`, `reply-email-thread` returns
plain text. Always check `isinstance(data, list)` *before* falling back to
`.get("data")` — the reverse order was a real bug in the pagination helpers.

## Endpoints this app calls

| Purpose | Call | Reference page |
|---|---|---|
| List campaigns | `GET /campaigns/` | `campaigns/get-all` |
| Campaign leads (paged) | `GET /campaigns/{id}/leads` | `campaigns/get-leads` |
| Lead categories | `GET /leads/fetch-categories` | `leads/categories` |
| Sending mailboxes | `GET /email-accounts` | `email-accounts/get-all` |
| Thread history | `GET /campaigns/{id}/leads/{id}/message-history` | `campaigns/get-lead-history` |
| Recategorize a lead | `POST /campaigns/{id}/leads/{id}/category` | `campaigns/update-lead-category` |
| Send a reply | `POST /campaigns/{id}/reply-email-thread` | `campaigns/reply-email-thread` |
| Webhooks | `POST|GET /webhooks` | `webhooks/create`, `webhooks/get` |

## Available but unused (worth knowing)

- **`POST /campaigns/{cid}/leads/{lid}/`** (`campaigns/update-lead`) — updates
  `first_name`, `last_name`, `company_name`, `website`, `custom_fields`, etc.
  (`email` is required in the body). This is the endpoint that could push the
  dashboard's **✎ Rename** correction back into Smartlead itself, instead of the
  current local-only `leads_state.name` + `name_locked`. **Not verified against
  the live API yet** — probe it against the test lead before wiring it up.
- **A whole Inbox API** (`/api-reference/inbox/*`): `get-messages`, `reply`,
  `forward`, `get-unread`, `mark-read`, `set-reminder`, `create-note`,
  `update-category`, `push-to-subsequence`. Potentially a better-fitting surface
  than the campaign endpoints for parts of this app.
- `campaigns/forward-email`, `campaigns/pause-lead`, `campaigns/resume-lead`,
  `campaigns/unsubscribe-lead`, `campaigns/mark-lead-complete`.

## Before trusting any new field

1. Find the page via the sitemap; confirm it's the right endpoint.
2. Probe it against the Mindaptive Jones test lead (safe for real sends — see
   CLAUDE.md), don't infer the shape from the example payloads.
3. Record what actually happened here, especially where it contradicts the docs.
