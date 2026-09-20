# Campaign analysis — 2026-09-19

Deep analysis of two accounts, run on 2026-09-19 against live Smartlead data.

- **`onebodyldn-2026-09-19.md`** — client report (2 campaigns). The source for the Loom.
  Shareable page: https://claude.ai/artifact/5jvt949q7NrWpaG9ZCmYLz
- **`mindaptive-website-offer-2026-09-19.md`** — our own report (6 "Website offer" campaigns).
  Shareable page: https://claude.ai/artifact/88UKgWvehRL4G3bNNb4Bo2

## Headline findings

**OneBodyLDN** — Microsoft (57% of the list) started junk-foldering us around
4 Sep; Google was unaffected the whole time, so it is not the copy. Subject line
"you walk past us every day" more than doubled replies against an identical body.
48 of 64 yeses never booked, and at least 8 of those hit a broken booking code,
a broken payment page or a surprise £4.99.

**Mindaptive** — the cold email is not the bottleneck. 40 demo sites were built,
26 leads then went silent, and **14 of those 26 actually visited the site**, some
of them three times. `site_visits` already records this and nothing acts on it.

## A note on what is in here

`analysis/data/` holds real lead names, email addresses and full conversation
text. It is **already excluded from git** by the existing `data/` rule in
`.gitignore` (verified with `git check-ignore`), so only the two reports and this
README are committable. Keep it that way — don't add a negation for it.

## What's in `data/`

| file | what it is |
|---|---|
| `mindaptive.db` / `onebody.db` | SQLite mirrors of every send, variant, lead variable, recipient MX and conversation. Rebuildable — see below. |
| `*_analysis.json` | Per-campaign funnel, variants, slots, provider splits, segment breakdowns, replied-lead lists. |
| `*_conversations.txt` | Every human conversation, flattened to readable text. |
| `ob_positive.txt` / `ob_negative.txt` / `mind_all.txt` | The same, filtered by Smartlead category. |
| `ob_themes.txt` | Objection themes, counted by unique lead. |
| `site_visits.json` | Who actually opened the demo site we built for them (Mindaptive only). |
| `sync_*.log` | Sync run logs. |

## How to rebuild

The app's own analytics modules do the work, so the counting rules can't drift
from the dashboard's:

```python
os.environ['DB_PATH'] = 'analysis/data/<account>.db'
os.environ['SMARTLEAD_API_KEY'] = <that account's key>
from app import db, campaign_analytics, campaign_conversations
db.init_db()
campaign_analytics.sync_campaign(campaign_id, full=True)   # sends, variants, lead vars, MX
campaign_conversations.sync_conversations(campaign_id)      # threads
```

Then `campaign_analytics.lead_outcomes()` / `lead_metrics()` / `variant_metrics()`
/ `reply_step_metrics()` and `campaign_deliverability.report()` give every number
in both reports. Segment breakdowns come from `campaign_lead_vars.custom_fields_json`.

## Counting rules (so numbers match the dashboard)

- A **reply** is a human reply only — Auto-Reply / Out Of Office / bounces excluded (`is_robot`).
- **Delivered = sent − bounced**; a bounced lead leaves the denominator entirely.
- **Positive** = any `Interested*` category or a booked meeting; `Not Interested` /
  `Do Not Contact` / `Wrong Person` explicitly excluded.
- **Attribution is sequence-wide** — a reply at step 2 belongs to the step-1 variant
  that opened the thread.
- **Open rate does not exist** — tracking is off account-wide, so `open_count` is 0
  on every row. Replies are the only signal.
- Every rate carries a **Wilson 95% interval** where it is used to rank anything.
