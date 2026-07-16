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

1. **Daily scan** (`app/scheduler.py: run_daily_scan`) — cron job (`DAILY_SCAN_HOUR_UTC`), Smartlead API only, no Claude. Also triggerable on demand from the dashboard ("Rescan now" button → `scheduler.trigger_scan_in_background`, lock-protected so it can't stack). For every "Interested" lead it checks the thread and decides: due for a follow-up (3+ days since our last message, under the follow-up cap) → adds a row to the `candidates` table; lead's message unanswered → auto-drafts a reply immediately (fast response to hot leads); otherwise → nothing.
2. **Dashboard "Follow-ups due" tab** — lists open candidates as checkboxes, nothing drafted yet.
3. **Generate / Bulk generate** (`app/candidates.py`) — user-triggered. Re-fetches the thread fresh (race-check: skip if the lead already replied), then calls `app/pipeline.py: create_draft` → `app/drafter.py: generate_draft`, which calls Claude with web search/fetch tools enabled so it can research the lead's website. Bulk generate runs in a background thread so it doesn't block on Cloudflare's ~100s tunnel timeout.
4. **Signature** — `pipeline.create_draft` also looks up which mailbox sent the thread's last message (`detector.last_sender_email`) and appends that persona's HTML signature (`app/signatures.py`, files in `signatures/`) directly onto `body_html` *before* saving the draft — deliberately not at send time, so the full email (message + signature) is what's shown and editable in the dashboard, and Send ships exactly that with no hidden transformation. Persona is detected from Smartlead's own `from_name` on each of the 90+ rotating sending accounts (`GET /email-accounts`), not a hand-maintained email list — see `PERSONA_FILES` in `signatures.py` if a new persona/name is added.
5. **Lead research** — the same Claude call that drafts the message also researches the lead's website (per the Website Diagnostic Framework in `prompts/system.md`) and returns a `<lead_research>` block (parsed into `DraftResult.lead_research`). `pipeline.create_draft` saves this to `leads_state.research_summary`/`researched_at` and passes it back in as `prior_research` on every later generation for that lead (regenerate, next follow-up, etc.) — the model is instructed to reuse it and skip re-searching unless it looks stale or a steering note asks for something new (tools stay available, it's an instruction not a hard cutoff). Shown in the dashboard as the "About this lead" panel next to the thread (`app/static/app.js: renderResearchPanel`).
6. **Review** — draft appears as an editable card (triage summary, English translation, edit body incl. signature, thread history). Actions: Send now, Schedule, Regenerate (with an optional steering note), Skip, Stop following up this lead.
7. **Send** — `app/smartlead.py: reply_to_thread`. Requires `email_stats_id` (Smartlead's internal id, captured as `NormalizedMessage.stats_id`/`drafts.reply_stats_id` — distinct from `reply_message_id`, the RFC822 header value) alongside `reply_message_id`/`reply_email_time`; Smartlead's API 400s without it. Re-checks the thread once more immediately before sending — for a reply/autoreply draft this only aborts if the lead has a *newer* reply than the one the draft addresses (comparing `message_id`), not merely "last message is a reply", since that's always true for a reply-kind draft by definition.

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
- `signatures/andrew.html` / `signatures/mia.html` — real signatures pulled from Smartlead's actual sending accounts, HTML/inline-styled, not meant to be hand-edited casually. `PERSONA_FILES` in `app/signatures.py` maps a Smartlead `from_name` to one of these files.
- Smartlead API response shapes are inconsistent per endpoint (some wrap in `{"data": [...]}`, others return a bare list) — always check `isinstance(data, list)` *before* falling back to `.get("data")`, not after (a real bug fixed in `smartlead.py`'s pagination helpers).
