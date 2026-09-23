# Mindaptive Responder

Follow-up dashboard for Smartlead. Surfaces leads with no contact in 3+ days, drafts a follow-up with Claude when you click Generate (single or bulk), and lets you review/edit before sending. Lead replies auto-draft immediately so hot leads get a fast response. See `CLAUDE.md` for where to edit the AI's prompts/knowledge and how the drafting pipeline works internally.

## 1. Local development

```
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt      # Scripts/ on Windows, bin/ on Linux/Mac
cp .env.example .env
```

Fill in `.env`:
- `SMARTLEAD_API_KEY` — Smartlead → Settings → API.
- `ANTHROPIC_API_KEY` — console.anthropic.com.
- `APP_PASSWORD` — the password you'll use to log into the dashboard.
- `SECRET_KEY` — any random string (signs the login session cookie).
- Leave `DRY_RUN=true` while testing — the pipeline runs for real (real Smartlead reads, real Claude drafts) but the final send step is logged instead of actually delivered.

Run it:

```
./.venv/Scripts/python -m uvicorn app.main:app --reload --port 8080
```

Open `http://localhost:8080`, log in with `APP_PASSWORD`. The scheduler starts automatically (daily scan at `DAILY_SCAN_HOUR_UTC`, plus a 1-minute loop that sends anything you've scheduled). To trigger a scan immediately instead of waiting for the cron:

```
./.venv/Scripts/python -c "
import sys; sys.path.insert(0, '.')
from app import scheduler, db
db.init_db()
scheduler.run_daily_scan()
"
```

## 2. Deploying to the droplet

Prerequisites:
- SSH access to the DigitalOcean droplet (Docker already installed, runs n8n alongside this).
- A Cloudflare Tunnel token for the subdomain you want (e.g. `sdr.mindaptive.ai`).

**Create the tunnel** (Cloudflare dashboard → Zero Trust → Networks → Tunnels → Create a tunnel):
1. Name it (e.g. `mindaptive-responder`), choose Docker as the connector — Cloudflare gives you a token, copy it.
2. Add a **Public Hostname**: subdomain `sdr` (or whatever), domain your Cloudflare-managed zone, service type `HTTP`, URL `app:8080` (the docker-compose service name + port — cloudflared and the app share a network via compose, so use the service name, not `localhost`).

**Deploy:**
```
# on the droplet
git clone <this repo> mindaptive-responder && cd mindaptive-responder
cp .env.example .env
# fill in .env: SMARTLEAD_API_KEY, ANTHROPIC_API_KEY, APP_PASSWORD, SECRET_KEY,
# PUBLIC_BASE_URL=https://sdr.yourdomain.com, CLOUDFLARE_TUNNEL_TOKEN, DRY_RUN=true
docker compose up -d --build
```

Visit `https://sdr.yourdomain.com`, confirm login works. Leave `DRY_RUN=true` for the first few days of real usage before flipping it off.

**Register the Smartlead webhook** (for instant reply drafting — separate from your existing n8n webhook, both can coexist):
- Smartlead → Settings → Webhooks → add one for the "Reply" event, URL `https://sdr.yourdomain.com/webhooks/smartlead`. If you set `SMARTLEAD_WEBHOOK_SECRET` in `.env`, configure Smartlead to send it as a header or query param matching what `app/webhook.py` checks.

For OneBodyLDN, import `n8n-workflows/onebody-notifier.json` and follow
`docs/performance-and-reply-delivery.md`. The old pasted workflow points its
responder request at AeroDefense, references the wrong trigger-node name, and
doesn't authenticate to OneBody. The replacement records every reply before
classification while preserving the AI gate on Slack notifications. That gate
calls `deepseek/deepseek-v4-flash` through OpenRouter; configure
`OPENROUTER_API_KEY` in both n8n and `.env.onebodyldn` before activation.

For the most reliable setup, register Smartlead directly against the responder
and keep n8n as a parallel Slack notifier. Smartlead cannot attach a custom
header when creating its webhook, so put the secret in the supported query
parameter: `<PUBLIC_BASE_URL>/webhooks/smartlead?secret=<secret>`. The responder
deduplicates direct and n8n delivery durably.

**Redeploying after code changes (manual):**
```
git pull && docker compose up -d --build
```

**Auto-deploy on push:** `deploy/auto-deploy.sh` pulls new commits from `origin/main` and runs `docker compose up -d --build`. It records the last successfully built SHA in `.deployed-sha`, so if a build fails (common under cron when `docker` isn't on PATH), the next run retries the build even when git is already up to date.

Set it up once via cron so every push to `main` goes live within a couple minutes:

```
chmod +x deploy/auto-deploy.sh
(crontab -l 2>/dev/null; echo "*/2 * * * * $(pwd)/deploy/auto-deploy.sh >> $(pwd)/deploy/deploy.log 2>&1") | crontab -
```

Check `deploy/deploy.log` on the droplet to see deploy history. You want lines like `building/redeploying …` then `deploy complete` — if you only ever see a pull and no complete line, the build failed and the next cron tick should retry. This polls rather than reacts instantly (up to a 2-minute delay) — deliberately chosen over a GitHub Actions + SSH webhook setup since the droplet's firewall only allows outbound connections plus inbound SSH, so nothing needs to reach in to trigger it.

## 3. Day-to-day usage

**Health tab** monitors every sending mailbox and domain belonging to this
client's Smartlead account. Mailbox reputation below 90% enters rehab (5 cold,
35–45 warm); five distinct days at 100% advances to comeback (15 cold, 25–30
warm), and another five advances to full (25 cold, 18–25 warm). Monitoring is
on by default. Smartlead settings are changed only when the switch at the top
of the Health tab is on (and `DRY_RUN=false`). The same panel edits each
stage's cold and warmup numbers, the rehab threshold and how many 100% days
move a mailbox up a stage; it's saved per client, and "Reset numbers to
defaults" restores the numbers above. `DELIVERABILITY_AUTO_APPLY` only sets
where the switch starts before anyone has touched it. DNS MX/SPF/DMARC and
APIVoid blacklist checks run daily. A missing `APIVOID_API_KEY` is shown as
unknown/not configured instead of a false clean result. See
`docs/deliverability-health-research.md` for evidence, limitations
and the safe rollout procedure.

**Follow-up timing** in the top bar sets a fixed interval (every X days) for
the current client. Saving replaces the configured progressive cadence and
refreshes due statuses from cached conversations immediately; the frequent
reply scan checks fresh threads. Set the very-hot interval to 0 to use the
same day interval for every temperature. Settings survive restarts in each
client's database. The panel also shows the existing follow-up cap and revival
wait; those limits and already-scheduled emails are not changed by this setting.

Booking confirmations sent to `/webhooks/booking-confirmed` match by email
first. If the person books with another email, a code listed in
`BOOKING_MATCH_CODES` enables exact normalized-name matching against the local
lead record and the Interested sheet. Once booked, the lead remains booked
across later emails and Smartlead category changes. Only a manual dashboard
category change unlocks it.

When `INTERESTED_SHEET_ID` is configured, the same spreadsheet also receives
every approved-code confirmation in a **Bookings** tab. A booking that cannot
be matched to a Smartlead lead is kept as **Shared code / not contacted**
instead of being discarded. **Booking Summary** shows total bookings,
bookings from contacted leads, and additional bookings produced by people
sharing the offer. The OneBody n8n workflow forwards the confirmation's
booking id, clinic, date and time so retries are deduplicated and the rows are
useful by eye.

- **Follow-ups due tab** — leads with no reply for 3+ days (and under the 4-follow-up cap). Nothing is drafted yet. Click **Generate** on one, or check several + **Generate selected** to draft a batch in the background (refresh after a bit — it doesn't block the page). Click **Rescan now** any time to refresh this list immediately instead of waiting for the next cron run (takes a couple minutes; the button shows "Scan running…" while it works, and won't let you stack a second one).
- **Inbox tab** — replies from leads, auto-drafted the moment they come in (via the webhook) or caught by the next daily scan if the webhook was missed. Review and send same as follow-ups.
- Every draft card: edit the body directly (the correct Andrew/Mia signature is already baked into the text, based on which mailbox sent the original outreach — edit it like part of the email, since that's exactly what gets sent), see the English translation (if the thread's in another language), view the full thread, then **Send now**, **Schedule** (pick a time — useful for a USA lead's morning), **Regenerate** (optionally with a steering note, e.g. "shorter" or "mention the review system instead"), **Skip** (dismiss just this draft), or **Stop following up this lead** (removes them from future automated follow-ups entirely).
- **Scheduled tab** — anything you scheduled for later; the background loop sends it automatically at the chosen time (with a race-check: if the lead replies before then, the send is aborted and flagged instead).
- **Sent log** — history of everything actually sent.

## 4. Config reference (`.env`)

| Var | Purpose |
|---|---|
| `FOLLOWUP_WAIT_DAYS` | Days of silence before a lead counts as "due" (default 3) |
| `MAX_FOLLOWUPS` | Cap on automated follow-ups per lead (default 4) |
| `DAILY_SCAN_HOUR_UTC` | When the daily candidate scan runs |
| `DRY_RUN` | `true` = pipeline runs fully, send step is logged not delivered |
| `AUTO_SEND_FOLLOWUPS` | Reserved for a future fully-autonomous mode — not wired up yet; generation is always click-triggered by design |
| `INTERESTED_CATEGORY_NAME` | Smartlead lead category this app watches (default `Interested`) |
| `N8N_WEBHOOK_URL` | Optional — only used if you want this app to also ping your n8n instance on a new drafted reply. Leave blank to just rely on your existing n8n Smartlead-reply notification, which runs independently. |
| `DELIVERABILITY_AUTO_APPLY` | Apply mailbox phase limits in Smartlead; default `false` (monitor only) |
| `MAILBOX_HEALTH_CHECK_HOURS` | Smartlead mailbox + DNS check interval; default 24 |
| `DOMAIN_BLACKLIST_CHECK_HOURS` | External blacklist refresh interval; default 24 (daily) |
| `APIVOID_API_KEY` | Optional APIVoid Domain Reputation API key; blank is shown as unknown/not configured |
| `DELIVERABILITY_ALERT_WEBHOOK_URL` | Optional transition-only webhook for rehab, connection, DNS and blacklist alerts |
