# Mindaptive Responder

A self-hosted dashboard that helps Andrew (Mindaptive.ai) follow up with Smartlead leads: it surfaces leads with no contact in 3+ days, drafts a follow-up with Claude on click (single or bulk), and lets him review/edit/send from a browser. Lead replies still auto-draft immediately so hot leads get a fast response.

## Where to make changes for better messages (start here)

These are plain markdown files, not code — edit them directly, no Python knowledge needed:

- **`prompts/system.md`** — the SDR system prompt. Role, tone rules (Hormozi-style: brief, peer-to-peer, no pricing over email), the website-diagnostic framework, objection handling, output format, and the follow-up examples (section 12). This is the first place to change *how* the AI writes.
- **`knowledge/solutions-catalog.md`** — every product/solution Mindaptive sells, organized by the RACE framework, with per-niche packages. Add or update offerings here.
- **`knowledge/vsl-transcript.md`** — the AI-secretary VSL transcript; referenced when deciding whether to send the video link.
- **`knowledge/hormozi-communication-style.md`** — sales philosophy/scripts reference (objection handling, follow-up cadence patterns).

`app/drafter.py` concatenates `prompts/system.md` + all of `knowledge/*.md` + a short "output contract" addendum (instructs the model to wrap its triage/draft/translation in `<triage>`/`<draft_original>`/`<draft_english>` tags so the app can parse them) into the system prompt sent to Claude. Adding a new `.md` file to `knowledge/` automatically includes it — no code change needed.

## How a message actually gets generated

1. **Daily scan** (`app/scheduler.py: run_daily_scan`) — cron job, Smartlead API only, no Claude. For every "Interested" lead it checks the thread and decides: due for a follow-up (3+ days since our last message, under the follow-up cap) → adds a row to the `candidates` table; lead's message unanswered → auto-drafts a reply immediately (fast response to hot leads); otherwise → nothing.
2. **Dashboard "Follow-ups due" tab** — lists open candidates as checkboxes, nothing drafted yet.
3. **Generate / Bulk generate** (`app/candidates.py`) — user-triggered. Re-fetches the thread fresh (race-check: skip if the lead already replied), then calls `app/pipeline.py: create_draft` → `app/drafter.py: generate_draft`, which calls Claude with web search/fetch tools enabled so it can research the lead's website. Bulk generate runs in a background thread so it doesn't block on Cloudflare's ~100s tunnel timeout.
4. **Review** — draft appears as an editable card (triage summary, English translation, edit body, thread history). Actions: Send now, Schedule, Regenerate (with an optional steering note), Skip, Stop following up this lead.
5. **Send** — `app/smartlead.py: reply_to_thread`. Re-checks the thread once more immediately before sending (abort if the lead replied in the meantime).

## Key config (`.env`, see `.env.example`)

- `FOLLOWUP_WAIT_DAYS` / `MAX_FOLLOWUPS` — cadence and cap (currently 3 days / 4 follow-ups).
- `DRY_RUN=true` — pipeline runs fully but the actual Smartlead send is skipped and logged instead. Keep this on for any testing.
- `AUTO_SEND_FOLLOWUPS` — future autonomous mode; not wired to auto-generate yet (generation is always click-triggered per Andrew's preference), only affects scheduled-send behavior.
- `ANTHROPIC_MODEL` — currently `claude-sonnet-5`.

## Local dev

```
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # Scripts/ on Windows, bin/ on Linux/Mac
cp .env.example .env   # fill in SMARTLEAD_API_KEY, ANTHROPIC_API_KEY, APP_PASSWORD
./.venv/Scripts/python -m uvicorn app.main:app --reload --port 8080
```

Dashboard at `http://localhost:8080` (password = `APP_PASSWORD`). Keep `DRY_RUN=true` while testing — the daily scan and generate/bulk-generate flows call real Smartlead + Anthropic APIs and will incur real Claude token cost per draft generated.

## Things not to change without a reason

- `app/db.py` schema (`leads_state`, `drafts`, `candidates`) — other modules assume these exact columns.
- `app/smartlead.py` field-name guesses in `normalize_lead`/`normalize_message` — verified against the real Smartlead API response shape (nested `lead{}` object, `lead_category_id` at the top level, message-history fields `type`/`time`/`message_id`/`email_body`).
- The webhook payload shape in `app/webhook.py` (`campaign_id`, `sl_email_lead_id`, `reply_message.text`, `to_name`, `to_email`) — confirmed from the existing n8n workflow, not guessed.
