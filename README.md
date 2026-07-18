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
