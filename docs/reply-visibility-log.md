# Reply visibility — running log

**Why this file exists.** "A lead replied and it isn't in the dashboard" has come
back more than once, each time looking like a different bug and each time
costing an afternoon to re-derive. This is the log: what was actually wrong,
what was measured, and what was changed. **Append a new dated section every time
this class of problem is worked on** — including the times the conclusion is
"nothing was wrong". A negative result is worth writing down; it's the theory
nobody has to test again.

There is a standing diagnostic at the bottom (`Re-checking it`) that answers
"are replies visible right now?" in one command. Run that first.

---

## 2026-08-11 — A lead's **first** reply was invisible until Smartlead categorised them

**Reported as:** first reply from an interested lead doesn't appear in
`sdr.mindaptive.ai` or `aero.mindaptive.ai`. Had to click "Rescan now" and wait
about five minutes. Killing response time and conversion.

### What was measured

Against production (`/root/mindaptive-responder/data/responder.db`) and the live
Smartlead API, on the day:

- Of the **20 most recent replies** in the Smartlead inbox, **16 had no row in
  the database at all** and 4 had a row carrying a stale category. **Zero** were
  correctly showing as a reply.
- Of those 16: **7 had no Smartlead category at all**, 6 were Do Not Contact, 3
  were Not Interested. The 7 uncategorised ones are the actual bug — one of them
  had replied that same morning at 07:44.
- App log, 16 hours of uptime: **zero** `smartlead webhook received` lines. The
  endpoint itself was fine (probed locally and through the public URL, both
  200) — nothing was calling it.
- n8n (`Smartlead notification`, workflow `KkpOaRhwq7dLW63s`) was firing
  normally — 245 stored executions — but **216 of 242 dead-ended at "No
  Operation"**, the NOT_RELEVANT branch. Only 26 ever reached the app.
- Two leads (Mirjam `4126837299`, Anthony `4263805695`) had a `pending` reply
  draft written that morning while their inbox rows still read
  `category=followup` / `category=waiting`, with a preview showing **our own
  outbound message**. Nine leads were in that state in total.

### Root cause — three independent failures, all pointing the same way

1. **The app could only see a lead whose Smartlead category was `Interested`.**
   `scheduler.run_daily_scan` (and therefore "Rescan now") filters on it. But
   Smartlead assigns that category with its own AI, minutes to hours *after* the
   reply lands, so at the moment a lead first answers they usually have no
   category. The scan skipped them. **This is the one that made a first reply
   invisible**, and it's why "Rescan now" seemed to work: the wait was not the
   scan, it was Smartlead's classifier catching up.
2. **`run_reply_catch_scan` couldn't cover for it** — it reads `leads_state`, and
   a first-time replier has no row there yet. For the leads it *did* find, it
   went straight from spotting the reply to generating a draft and **never wrote
   the columns the inbox list reads** (`category`, `last_message_preview`,
   `last_message_at`). The answer existed and the screen said nothing had
   happened.
3. **The webhook path made its lead visible only after the draft finished.** The
   whole of `webhook._process_reply` ran inside one `db.db_session()`, which
   commits at exit — so the `interested=1` write landed minutes later, after a
   Claude call with web search. It also never wrote `category`, `name` or
   `email`, so a brand-new lead arrived at the *bottom* of the inbox as an
   anonymous grey "Lead" with no preview and no date. And that open transaction
   is an exclusive SQLite writer lock (WAL allows one writer), which is what made
   a concurrent "Rescan now" or send crawl.

Not a cause, checked and cleared: n8n's classification. It drops NOT_RELEVANT
replies and that is correct behaviour — the app is supposed to have its own
safety net, and the safety net was what was broken.

### What changed

- **`scheduler.run_new_reply_poll` / `_adopt_unknown_repliers`** (new) — asks
  Smartlead the opposite question: not "who is Interested?" but **"who has
  written to us lately?"**, via `smartlead.list_recent_replies`
  (`POST /master-inbox/inbox-replies`, all campaigns in one call). Runs every
  `NEW_REPLY_POLL_SECONDS` (default 60) because it is two API calls with no
  per-lead work. Only explicitly negative categories are skipped
  (`_SKIP_ADOPT_CATEGORIES`); **"no category" is deliberately not one of them.**
- **`db.mark_lead_replied`** (new) — the single place that records "a lead wrote
  to us": category, preview, timestamp, plus un-archiving/un-snoozing on the
  same timestamp rule `db.mark_lead_booked` uses. Called by the webhook and by
  the catch-scan, and by the catch-scan **before** any has-draft check, because a
  message the webhook already drafted for still has to be visible as a message.
- **No model call holds a database transaction any more** — webhook, reply-catch
  and the daily scan all commit the summary first and open a fresh session for
  the draft.
- **`webhook._process_reply`** split into visibility-first / slow-half, plus
  `_fetch_thread_with_reply` (message-history lags the webhook by seconds; a
  single early fetch used to abandon the event) and `_reply_text` (accepts
  `reply_message.text`, `reply_body` and `preview_text` — the real Smartlead
  payload carries all three).
- **`app/reply_classifier.py`** (new) — n8n's RELEVANT/NOT_RELEVANT gate, in the
  app, on DeepSeek V4 Flash (`ROLE_CLASSIFY`, visible in the Models panel as
  "Sorting incoming replies"). Two rules it must keep: it **gates drafting, never
  visibility**, and it **fails open**. It exists so the catch-scan stops spending
  a draft on every out-of-office, and so Smartlead's webhook could point straight
  at the app if n8n is ever removed.
- **Frontend** — inbox poll 60s → 15s, plus an immediate refresh on tab focus.

Result: a first reply is visible within about a minute, with no clicks.

### Things worth not re-learning

- `GET /webhooks` does not exist on the Smartlead API (404). Webhooks can only
  be listed **per campaign** (`GET /campaigns/{id}/webhooks`), so an empty result
  across every campaign does **not** prove nothing is registered — a user-level
  webhook is invisible to that endpoint. This was briefly mistaken for "Smartlead
  isn't calling n8n"; it was.
- `POST /master-inbox/inbox-replies` returns `{"ok", "data", "offset", "limit"}` —
  a `data` key, not the documented `messages`, and no `total_count`. `limit` is
  capped at 20.
- Smartlead's API rejects a plain `python-urllib` user agent with 403. Send a
  normal `User-Agent` when probing by hand.
- n8n execution data lives in `execution_data.data` in
  `/var/lib/docker/volumes/n8n_data/_data/database.sqlite` as a flat array with
  string-index references — resolve `"92"` by indexing back into the array. That
  database was 11 GB; open it `mode=ro&immutable=1` and never write to it.
- The production database is `data/responder.db`, not `app.db`.

### Re-checking it

Answers "are replies visible right now?" — compares Smartlead's own inbox
against `leads_state`. Run on the droplet:

```bash
python3 - <<'PY'
import json, sqlite3, urllib.request
env = dict(l.strip().split("=", 1) for l in open("/root/mindaptive-responder/.env")
           if "=" in l and not l.strip().startswith("#"))
H = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
req = urllib.request.Request(
    "https://server.smartlead.ai/api/v1/master-inbox/inbox-replies?api_key=%s" % env["SMARTLEAD_API_KEY"],
    data=json.dumps({"offset": 0, "limit": 20, "filters": {"emailStatus": "Replied"},
                     "sortBy": "REPLY_TIME_DESC"}).encode(), headers=H, method="POST")
rows = json.loads(urllib.request.urlopen(req, timeout=60).read())["data"]
c = sqlite3.connect("file:/root/mindaptive-responder/data/responder.db?mode=ro", uri=True)
for r in rows:
    st = c.execute("SELECT category FROM leads_state WHERE lead_id=? AND campaign_id=?",
                   (int(r["email_lead_id"]), int(r["email_campaign_id"]))).fetchone()
    print("%-20s %-34s %s" % (str(r["last_reply_time"])[:16], (r["lead_email"] or "")[:34],
                              "MISSING" if st is None else st[0]))
PY
```

Healthy output: every recent reply has a row, and the recent ones read `reply`.
`MISSING` means the new-reply poll is not running — check
`docker compose logs app | grep "new-reply\|reply-catch"`.
