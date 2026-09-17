# Subsequences — build plan

Status: **built 2026-09-16** (backend, stop pipeline, builder, leads view, lead badge). Not yet run on a real send; see §8 phase 5. Where the build differs from this plan, CLAUDE.md §22 describes what shipped.

## Why this exists

Smartlead has subsequences, but a Smartlead signature belongs to the **mailbox**,
not the campaign. Putting the rich HTML signature on Kurt's mailbox would also put
it on every cold first-touch email that mailbox sends, which is exactly what we
don't want: first touches carry a plain-text signature, follow-ups carry the full
HTML one (photo, address, phone, socials, website) because that is where the
credibility comes from.

This app already sends follow-ups as threaded replies with the persona's HTML
signature appended at send time (`scheduler.compose_send_body`). So subsequences
are built here, on top of that send path. Smartlead's one extra — open rates — is
not available anyway: tracking is off account-wide for deliverability.

## What Andrew wants (the spec)

1. Andrew writes and sends the first message himself, from the dashboard.
2. He changes the lead's status to a trigger category, e.g. **"Interested 55"**.
3. That enrolls the lead in the subsequence bound to that category.
4. The subsequence is **fixed copy Andrew writes** in an editor — formatting,
   bold, links, everything. No AI. N steps (typically 4), each with a delay
   Andrew sets: "2 days after the previous one", "3 days after that".
5. Each step is sent at a **random time between 07:00 and 09:00 in the lead's
   local time**, weekdays only.
6. Any reply **or** a booked meeting stops the subsequence **immediately**. A
   replying lead goes back to "Interested" and back into the inbox.
7. A lead who replied is **not** re-enrolled automatically.
8. A screen showing every subsequence, who is in it, which step they're on, and
   when the next email goes.

---

## 1. Data model (`app/db.py`, new tables in `SCHEMA`)

```sql
CREATE TABLE IF NOT EXISTS sequences (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    trigger_category TEXT NOT NULL,          -- Smartlead category name, e.g. "Interested 55"
    active           INTEGER NOT NULL DEFAULT 1,  -- 0 = no new enrollments, no sends
    window_start     TEXT NOT NULL DEFAULT '07:00',  -- lead-local
    window_end       TEXT NOT NULL DEFAULT '09:00',
    weekdays_only    INTEGER NOT NULL DEFAULT 1,
    timezone_mode    TEXT NOT NULL DEFAULT 'auto',   -- 'auto' | an IANA zone, e.g. 'Europe/London'
    finish_category  TEXT,                   -- optional Smartlead category after the last step
    created_at TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS sequence_steps (
    id          INTEGER PRIMARY KEY,
    sequence_id INTEGER NOT NULL REFERENCES sequences(id),
    position    INTEGER NOT NULL,            -- 1..N
    delay_days  INTEGER NOT NULL,            -- days after the previous send (step 1: after Andrew's message)
    body_html   TEXT NOT NULL,               -- body only, never a signature
    attachments TEXT,                        -- JSON, same shape as drafts.attachments
    created_at TEXT, updated_at TEXT
);

CREATE TABLE IF NOT EXISTS sequence_enrollments (
    id            INTEGER PRIMARY KEY,
    sequence_id   INTEGER NOT NULL,
    lead_id       INTEGER NOT NULL,
    campaign_id   INTEGER NOT NULL,
    state         TEXT NOT NULL,   -- active | paused | completed | stopped | error
    steps_sent    INTEGER NOT NULL DEFAULT 0,
    anchor_at     TEXT NOT NULL,   -- time of the outbound message the next delay counts from
    next_send_at  TEXT,            -- UTC; NULL unless active
    draft_id      INTEGER,         -- the one scheduled draft for the next step
    stop_reason   TEXT,            -- replied | auto_reply | booked | status_changed | dnc | mailbox_dead | manual | send_failed
    stop_message_id TEXT,          -- the inbound message that stopped it (ties the classifier verdict back)
    suggested_resume_at TEXT,      -- out-of-office return date read from the autoresponder
    enrolled_at TEXT, stopped_at TEXT, completed_at TEXT,
    UNIQUE (sequence_id, lead_id, campaign_id)   -- no silent re-enrollment (spec 7)
);
CREATE INDEX IF NOT EXISTS idx_enroll_lead ON sequence_enrollments(lead_id, campaign_id, state);
```

`drafts` gains two columns via `_migrate`: `enrollment_id INTEGER`, `step_position INTEGER`,
and a new `kind='sequence'`.

**Invariant:** a lead has at most **one** `active` enrollment across all sequences.
Enforced in `sequences.enroll` inside the same transaction.

### Why each step becomes a normal `drafts` row

Only the **next** step is materialized, as a `drafts` row with `status='scheduled'`.
That one choice buys most of the safety for free:

- `db.mark_lead_booked` already stales pending/scheduled drafts.
- `webhook._record_incoming` already stales pending/scheduled drafts on a reply.
- `_send_due_draft` already re-fetches the thread and aborts if the lead replied.
- The Scheduled tab already lists it, with the exact text that will go out.
- Recipients, attachments, persona signature, `DRY_RUN`, `REQUIRE_KNOWN_SENDER`
  are all already handled on that path.

The enrollment row is the source of truth for *where the lead is*; the draft is
just the next letter in the outbox.

---

## 2. New module `app/sequences.py` — the only place sequence logic lives

| Function | Does |
|---|---|
| `enroll(conn, sequence, lead_id, campaign_id, anchor_at)` | Guards, creates enrollment, schedules step 1 |
| `schedule_next(conn, enrollment)` | Computes `next_send_at`, renders step body, creates the scheduled draft |
| `on_step_sent(conn, draft)` | Called from `_send_due_draft` after a sequence draft is sent: `steps_sent += 1`, `anchor_at = sent_at`, schedule next or complete |
| `stop_for_lead(conn, lead_id, campaign_id, reason, *, event_at=None)` | **The single stop chokepoint** (§4). Stops active enrollment, stales its draft |
| `send_time_utc(sequence, lead, anchor_at, step, rng_seed)` | Timing rules (§3) |
| `sequence_for_category(name)` | Trigger lookup, normalized with `scheduler.norm_category_name` |

### Enrollment guards (all must pass, else a visible error, never a silent skip)

1. Sequence is `active` and has ≥1 step.
2. Lead has no other `active` enrollment.
3. No prior enrollment in this sequence (the UNIQUE key). Re-enrolling needs the
   explicit **"Re-enroll"** button, which deletes the old row first.
4. The thread's **last message is ours** — if the lead wrote last, they're waiting
   on Andrew, not on a sequence. Error: *"They're waiting on your reply."*
5. The mailbox that sent the last message is sendable (`signatures.is_sendable`).
6. Lead isn't booked / stopped / blacklisted / DNC.

`anchor_at` = timestamp of our last outbound message in the thread (Andrew's
manual message), **not** the moment the status changed. So a status changed a day
late, or detected late from Smartlead, still sends step 1 two days after the email.

---

## 3. Send timing

`send_time_utc`:

1. `target_date = local_date(anchor_at) + delay_days` in the lead's timezone.
2. If `weekdays_only` and target is Sat/Sun → next Monday.
3. Pick a random minute in `[window_start, window_end)` local. Seeded from
   `(enrollment_id, step_position)` so recomputing it (e.g. after a step edit)
   gives the same time instead of reshuffling.
4. Convert with `zoneinfo` (DST handled).
5. If the result is already in the past (app was down, or late enrollment), use
   the next window that is still ahead — today's if it's still open, else the
   next valid day. Never "send immediately at 3pm".

### Lead timezone — needs fixing, this is a real gap

`thread_utils.guess_timezone` today returns `America/New_York` for US campaign
names and **`Europe/Zagreb` for everything else**. For OneBodyLDN that's an hour
off: a 07:00–09:00 Zagreb window is 06:00–08:00 London.

Resolution order, in `sequences.lead_timezone(sequence, lead)`:

1. Sequence `timezone_mode` if it's an explicit zone (OneBody sequences: `Europe/London`).
2. A timezone/country/state custom field on the Smartlead lead, if one exists
   (to verify against the live API per client — nothing assumed).
3. Improved `guess_timezone`: add UK/London keywords → `Europe/London`.
4. Client default `DEFAULT_LEAD_TIMEZONE` env var (new, per container).

US leads span 4 zones, so (decided 2026-09-16) **every US lead uses a fixed
08:00–10:00 America/New_York window**. That's 05:00–07:00 Pacific, so it lands in the
inbox before the morning check on either coast. The rule overrides the sequence's
window for any lead whose timezone resolves to a US zone. It's one constant,
`US_SEND_WINDOW`, not a per-sequence setting.

### Volume

Many leads share the same 2-hour window. Smartlead pacing already exists
(`SMARTLEAD_REQUESTS_PER_MINUTE`); each send is ~2 calls (thread + reply). Randomizing
within the window also spreads the load. Log a warning if more are due in one window
than the pacing can clear before `window_end`.

---

## 4. Stopping — the part that must not fail

Principle: **every signal that a lead is no longer silent calls
`sequences.stop_for_lead`**, and the last line of defence is a fresh check right
before every single send. Two independent layers, so a missed webhook costs at most
a delay, never an email.

### Layer 1 — stop at the source (hook points)

| Signal | Latency | Where it's detected today | Hook |
|---|---|---|---|
| Lead replies (Smartlead webhook / n8n) | seconds | `webhook._record_incoming` | call `stop_for_lead(reason='replied', event_at=received_at)` |
| Lead replies (webhook missed) | ≤60 s | `scheduler._adopt_unknown_repliers` — only handles *unknown* leads today | **new:** for a known lead with an active enrollment, reply time > `anchor_at` → stop |
| Lead replies (both above missed) | ≤5 min | `run_reply_catch_scan` — selects `interested=1` only | **extend** its query to include enrolled leads; last message is a reply newer than `anchor_at` → stop |
| Calendly booking | seconds | `/webhooks/calendly` → `record_explicit_booking` → `mark_lead_booked` | hook inside `db.mark_lead_booked` |
| OneBody booking email (n8n) | seconds | `/webhooks/booking-confirmed` → same | same |
| "I've booked" reply (classifier) | seconds–1 min | `record_explicit_booking` | same |
| Andrew marks booked in the dashboard | instant | `api_set_category` → `mark_lead_booked` | same |
| Andrew changes status in dashboard to anything else | instant | `api_set_category` | `stop_for_lead(reason='status_changed')` |
| Status changed in Smartlead's own UI | ≤60 s if they replied, else daily scan | `_sync_category_from_smartlead` | category ≠ trigger → stop. **Plus** the pre-send category check below, so it's never later than the send itself |
| Unsubscribe / DNC / bounce | varies | `record_do_not_contact` | `stop_for_lead(reason='dnc')` |
| Mailbox retired | at send | `_send_due_draft` sendable check | `stop_for_lead(reason='mailbox_dead')` |

Putting the hook **inside** `db.mark_lead_booked` and `db.mark_lead_replied` (rather
than at each caller) means any future path that records a reply or booking stops
sequences without anyone remembering to. `mark_lead_replied` only stops when
`received_at > anchor_at` — the catch-scan re-marks old replies, and an old reply
from before enrollment must not kill a fresh sequence.

### Layer 2 — the pre-send gate (in `_send_due_draft`, sequence drafts only)

Right before calling `smartlead.reply_to_thread`, all fresh, none from cache:

1. Enrollment is still `active` and `draft_id` is this draft (a stop that raced us wins).
2. Fresh thread: **any** inbound message newer than `anchor_at` → stop, don't send.
   (Stricter than today's "last message is a reply" check.)
3. Fresh lead category from Smartlead (`GET /leads/{id}`, one call): must still
   normalize to the trigger category. Booked / Interested / anything else → stop.
   This is what catches a booking marked in Smartlead's UI that no scan has seen yet.
4. Local `leads_state.status` not booked / stopped / blacklisted.
5. **Claim** the draft (`status='sending'`) in a short transaction before the API
   call, so a crash or overlapping loop can't send the same step twice. (Today's
   `_send_due_draft` has no claim — fix it for all drafts while we're in there.)

Any gate failure is recorded as `stop_reason`, visible in the Sequences tab.

### What happens to a lead who replied

1. Enrollment → `stopped`, `stop_reason='replied'`, scheduled draft → `stale`.
2. Lead goes back into the inbox (`mark_lead_replied` already un-archives, sets `category='reply'`).
3. Smartlead category → **Interested**. Note `_push_category_to_smartlead` currently
   refuses anything but DNC / Meeting-Booked (scheduler.py:360); allow Interested
   **only** for this path. If the classifier says booked / DNC / wrong person, that
   verdict wins over Interested.
4. The reply is drafted like any other reply (existing pipeline).

### Out-of-office replies (decided 2026-09-16: they stop the sequence)

Any inbound message stops the sequence at once, autoresponders included. Nothing is
sent on the classifier's say-so. What changes for an out-of-office is what happens
**after** the stop:

1. The stop happens at receipt (§4 Layer 1), before classification, with
   `stop_reason='replied'` and **no** Smartlead category push yet.
2. The classifier then runs as it does today. If it says `AUTO_REPLY` and the lead
   has a stopped enrollment from that same message, the enrollment becomes
   `state='paused'`, `stop_reason='auto_reply'`: it's resumable rather than finished.
3. **Return date extraction.** One more cheap `ROLE_CLASSIFY` call reads the
   autoresponder and returns the date they're back (`YYYY-MM-DD` or `NONE`),
   resolved against the message's own sent date ("back Monday", "until the 24th").
   Stored as `sequence_enrollments.suggested_resume_at`. Fail-soft: no date → no
   suggestion, never a guess.
4. **Smartlead category stays the trigger category** for an enrolled lead. Don't
   push Auto-Reply (§17's usual push), or the pre-send gate would refuse the
   resumed sequence. Only an `INTERESTED` verdict pushes Interested; booked, DNC
   and wrong-person verdicts behave as usual and turn the pause into a real stop.
5. The lead shows in the inbox (grey auto-reply tier) with the badge
   *"Out of office until Mon 29 Sep · sequence paused at step 2 of 4"* and three buttons:
   - **Resume on 29 Sep** (only when a date was found)
   - **Resume in [N] days**
   - **Resume on [date picker]**

Resuming sets `state='active'`, puts `anchor_at` at the resume date, and schedules the
**next unsent step in the first send window on or after that date**. The step's own
`delay_days` isn't added again, because the wait already happened. Resume also
re-runs the enrollment guards: if a real reply arrived in the meantime, the button
refuses.

A paused enrollment still counts as the lead's one open enrollment. A paused lead
can't be enrolled elsewhere until Andrew resumes or removes it.

---

## 5. Sending mechanics

- `run_due_send_loop` (every minute) already picks up `scheduled` drafts. No new job.
- `_send_due_draft` for `kind='sequence'`: pre-send gate (§4), then the existing path.
  Signature: `compose_send_body` with the persona of the mailbox that sent the last
  message — the same mailbox Andrew's manual message went out from. Threaded as a
  reply (`reply_message_id` / `stats_id` from the fresh last message).
- After success: `sequences.on_step_sent` in the same transaction as marking the
  draft sent. `followup_count` is **not** incremented (that's the AI cadence's counter).
- After the last step: enrollment `completed`, and the lead moves to **"Sequence
  finished"** in Smartlead and locally (decided 2026-09-16). That's the default
  `finish_category` for every sequence. The category must exist in each client's
  Smartlead account. The builder checks `GET /api/categories` and warns if it's missing
  rather than failing the last send. Push with `pause_lead=False` and allow it through
  `_push_category_to_smartlead`'s allowlist. A reply after "finished" goes through the
  normal reply pipeline back to Interested.
- Send failure: draft keeps `send_error`, enrollment → `error`, retried once in the
  next window, then left in `error` for Andrew. Never silently retried forever.
- `DRY_RUN`: draft marked sent without the API call, enrollment advances. Good for
  local walkthroughs.
- **Placeholders:** `{name}`, `{company}`, `{companyNickname}` via
  `message_templates.fill` at materialization time; unknown ones are deleted, never
  mailed with braces. Bold via real `<strong>` from the editor.
- **Editing a step later:** scheduled-but-unsent drafts for that step are re-rendered,
  *unless* Andrew hand-edited that specific draft in the Scheduled tab (flag
  `drafts.body_edited`). Send time is kept (seeded random).
- **Pausing a whole sequence** (`active=0`): its scheduled drafts go back to `pending`
  with `next_send_at` kept; un-pausing reschedules any that slipped into the past.

### Language

Copy is fixed and written by Andrew, so a sequence is single-language. OneBody is
English-only. For Mindaptive EU campaigns, either one sequence per language
(trigger e.g. "Interested 55 DE"), or a later per-step language variant. Not in v1.

### Existing AI follow-up cadence must stand down

The daily scan and reply-catch pass queue AI follow-up candidates for silent
leads. An enrolled lead must be **excluded** from `_queue_due_followup` /
`_process_lead` candidate creation and from overnight batch generation, or they get
both a sequence step and an AI follow-up.

---

## 6. UI

### 6a. Sequences tab (new `view-sequences-btn`, `VIEW_LOADERS.sequences`)

**Left: list of sequences** — name, trigger category chip, active toggle, counts:
`12 active · 30 completed · 9 replied · 3 booked`.

**Right, when one is selected — two sub-tabs:**

**Leads** (default)

| Lead | Company | Step | Last sent | Next send | State |
|---|---|---|---|---|---|
| Jane Doe | Acme Physio | 2 of 4 | Tue 08:12 | Fri 07:46 London (08:46 yours) | ● Active |
| John Roe | Roe Clinic | 1 of 4 | Mon 07:31 | — | ⏹ Replied Wed |

Filter chips: Active / Completed / Stopped (with reason) / Error. Row click opens the
lead in the normal detail pane. Row actions: **Pause**, **Resume**, **Send next step now**,
**Skip step**, **Remove from sequence**, **Re-enroll** (stopped/completed only).

**Builder**

- Name, trigger category (dropdown from `GET /api/categories`, so it's always a real
  Smartlead category), send window (07:00–09:00 default), weekdays only, timezone
  (Auto / explicit zone), optional finish category.
- Steps as cards, reorderable: *"Send **2** days after the previous email"* + the
  rich editor + Files row.
- Each step shows a **live preview** with a sample lead's placeholders filled and
  the signature of each persona under it (toggle Kurt / Rebecca), so what Andrew
  sees is what the lead gets.
- **"Send test to Mindaptive Jones"** per step — real send to the test lead via the
  same path, so formatting + signature are verified in a real inbox.
- Timeline strip at the top: *Your email → +2d → Step 1 → +3d → Step 2 → …* with the
  total span in days.

**Editor reuse.** The draft editor (`app.js` ~3654–3809, `editorSerialize` 4165) is
hardwired to `#draft-editor` and `state.originalHtml`. Extract it into
`createRichEditor(container, {initialHtml, onChange})` returning
`{serialize(), setHtml(), el}` — toolbar, bold, links, paste-image upload, image
resize — and use it in both places. Do this refactor as its own step and re-test the
draft card before building on it.

### 6b. Everywhere else a lead appears

- **Detail pane badge:** `🔁 Interested 55 · step 2 of 4 · next Fri 07:46 (London)`
  with Pause / Remove.
- **Status dropdown** (`api_set_category`): choosing a trigger category now **enrolls**
  and returns the scheduled time → toast *"Enrolled in Interested 55 — first
  follow-up Wed 07:42 London."* Guard failures are shown, not swallowed. Today the
  final `else` branch archives the lead locally; for a trigger category it still
  leaves the inbox (it lives in the Sequences tab now), but it must not archive
  the enrollment away.
- **Inbox chip** for an enrolled lead that comes back (reply): shows *"Replied during
  Interested 55 (after step 2)"* so Andrew knows which email worked.
- **Scheduled tab:** sequence drafts show a `Step 2/4 · Interested 55` label.

### 6c. Endpoints (`app/main.py`)

```
GET    /api/sequences                          list + counts
POST   /api/sequences                          create
GET    /api/sequences/{id}                     sequence + steps
PATCH  /api/sequences/{id}                     settings, active toggle
DELETE /api/sequences/{id}                     only if no active enrollments
POST   /api/sequences/{id}/steps               add step
PATCH  /api/sequences/{id}/steps/{step_id}     edit (re-renders unsent drafts)
DELETE /api/sequences/{id}/steps/{step_id}
POST   /api/sequences/{id}/steps/{step_id}/move
POST   /api/sequences/{id}/steps/{step_id}/test-send   → Mindaptive Jones only
GET    /api/sequences/{id}/enrollments?state=
POST   /api/enrollments/{id}/pause | resume | skip | send-now | remove | re-enroll
```

Mutating routes return the fresh object, like the template routes.

---

## 7. Stats

Per sequence and per step: sent, replied after this step (reply between step k and
k+1), booked, stopped by reason. Answers "does step 3 ever get a reply, or should
the sequence be 3 steps". No opens — tracking is off.

---

## 8. Build order

Each phase ends testable; nothing ships to a live client before phase 5.

1. **Core, no UI.** Tables + migration, `app/sequences.py` (enroll, timing,
   schedule_next, on_step_sent, stop_for_lead), `_send_due_draft` changes including
   the `sending` claim, exclusion from the AI cadence. Unit tests in
   `tests/test_sequences.py` for timing (weekend roll, DST week, window already past,
   London vs New York, seeded stability) and state transitions.
2. **Stop pipeline.** All Layer-1 hooks + the pre-send gate. Test matrix below.
3. **Builder.** Editor refactor → Sequences tab builder → test-send to Jones.
4. **Leads view + badges + status-dropdown enrollment + stats.**
5. **Live test on Mindaptive Jones** with a 4-step sequence at `delay_days=0` via
   "Send next step now": verify signature rendering in Gmail, threading, stop on
   reply, stop on booking webhook, stop on a category change made in Smartlead's UI.
   Then create OneBody's first sequence in their container (`timezone_mode=Europe/London`)
   and enable it with Andrew watching the first window.

### Stop test matrix (phase 2, each one a test)

| # | Scenario | Expect |
|---|---|---|
| 1 | Webhook reply between steps | Stopped in seconds, draft stale, lead in inbox, Smartlead → Interested |
| 2 | Webhook never arrives, reply exists | Stopped by 60 s poll |
| 3 | Webhook + poll both miss | Stopped by 5-min catch scan |
| 4 | All of the above miss, reply arrives 1 min before send | Pre-send gate aborts |
| 5 | Calendly / booking-confirmed webhook | Stopped via `mark_lead_booked` |
| 6 | Booked in Smartlead UI, no reply, no webhook | Pre-send category check aborts |
| 7 | Andrew changes status in dashboard | Stopped instantly |
| 8 | Out-of-office reply | Stopped; Resume works and reschedules from today |
| 9 | Old reply (before enrollment) re-seen by catch scan | **Not** stopped |
| 10 | Two send loops / crash mid-send | Step sent exactly once |
| 11 | Mailbox retired | Stopped, reason `mailbox_dead` |
| 12 | Lead enrolled, then re-set to trigger category after replying | Not re-enrolled without the button |

---

## Decisions (2026-09-16)

1. **Out-of-office stops the sequence.** The app reads the return date and offers
   Resume on that date, in N days, or on a picked date (§4).
2. **US leads: 08:00–10:00 Eastern**, fixed (§3).
3. **Finished leads move to "Sequence finished"** (§5).

## Notes

- **Trigger in Smartlead's UI vs dashboard:** both work, but changing status in the dashboard enrolls instantly and shows the scheduled time. Changing it in Smartlead's UI is picked up only when a scan sees it (up to the next daily scan for a silent lead) — fine for a 2-day first delay since timing counts from the email, not the status change.
