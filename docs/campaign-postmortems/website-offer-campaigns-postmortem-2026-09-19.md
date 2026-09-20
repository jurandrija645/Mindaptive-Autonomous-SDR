# Website-offer cold email campaigns — RAW postmortem

**Prepared:** 2026-09-19
**Source:** Smartlead API (live), account `SMARTLEAD_API_KEY` (Mindaptive default account)
**Scope:** the 5 most recent "Website offer" campaigns
**Purpose:** documentation, not strategy. No recommendations are given anywhere in this document (see §16).

---

## ⚠ READ THIS BEFORE USING ANY NUMBER BELOW

**All five campaigns are ACTIVE and between 2 and 17 days old.** This is the single most important fact about this dataset and it limits nearly every conclusion.

| Campaign | Created | Age at 2026-09-19 | Status | Send progress |
|---|---|---|---|---|
| 3960583 Solar USA Recycled | 2026-09-15 | 4 days | ACTIVE | **Mid-send.** 1,600 of 2,479 leads have received email 1; 879 not started; step 3 has never fired. |
| 3960357 HVAC USA Recycled | 2026-09-15 | 4 days | ACTIVE | **Mid-send.** 1,561 of 1,781 leads contacted; 220 not started; step 3 has never fired. |
| 3950427 mixedICP EU | 2026-09-13 | 6 days | ACTIVE | Sequence nearly complete (1,622 of 1,957 leads finished all 3 steps). |
| 3912149 HVAC Europe Eng | 2026-09-07 | 12 days | ACTIVE | Sequence essentially complete (1,193 of 1,256 finished). |
| 3892258 HVAC USA | 2026-09-02 | 17 days | ACTIVE | Sequence largely complete (1,437 of 2,409 finished; 904 "blocked"). |

Consequences, all of which recur as caveats throughout:

1. **The two "Recycled" campaigns (3960583, 3960357) have effectively no follow-up data.** Step 3 has never sent. Roughly 35% and 12% of their lists have never been emailed at all. Their reply rates are computed on a partial denominator against a partial sequence and **cannot** be compared with the three older campaigns.
2. **Later-funnel stages are near-empty by construction, not by failure.** 3 meetings booked, 7 price conversations, 0 closed deals, $0 revenue across 8,403 delivered emails. The oldest campaign is 17 days old and the typical observed positive-reply → demo → price cycle in this data runs 5–14 days. It is genuinely too early to read demo→sale or price→sale conversion, and those rates are reported as "not measurable yet", not as zero performance.
3. **Several leads are mid-conversation right now.** Marking them "ghosted" would be wrong; they are labelled `live` and dated.

---

## Data sources used, and what Smartlead does NOT expose

| Needed for | Source used | Notes |
|---|---|---|
| Campaign settings, timezone, tracking | `GET /campaigns/{id}` | Confirms `track_settings: ['DONT_EMAIL_OPEN','DONT_LINK_CLICK']` on **all five** |
| Headline totals incl. bounce count | `GET /campaigns/{id}/analytics` | `bounce_count` IS exposed here (contrary to the brief's suspicion). But its `reply_count` is per-lead and disagrees with per-send rows — see below |
| Exact templates & A/B variants | `GET /campaigns/{id}/sequences` | Verbatim in §3 |
| Per-send attribution (variant, step, bounce, reply) | `GET /campaigns/{id}/statistics` | 19,597 rows pulled. Used for every rate in this document |
| Lead list + personalization tokens | `GET /campaigns/{id}/leads-export` | The source spreadsheet, recovered |
| Full raw threads | `POST /campaigns/{id}/message-history-for-leads/...` | All 114 replying leads |
| **Whether the prospect actually opened the demo site** | **`site_visits` table, production DB** (`/root/mindaptive-responder/data/responder.db`), joined per lead in `analysis/data/demo_visits_by_lead.json` and `analysis/data/demo_visitors_silent_HOT.csv` | **Not a Smartlead source.** See §D below |

### D. Demo-site visit tracking — a second, non-Smartlead source of truth

Smartlead cannot answer "did they look at the demo?" — tracking is off account-wide and the Vercel links carry nothing Smartlead sees. **A separate production table answers it.**

`app/site_visits.py` documents the semantics, and three points govern how it is reported throughout this document:

1. **`visit_count` is NOT page views.** Vercel groups requests into **4-hour blocks**, so there is no exact visit time. **One "visit" = one 4-hour block in which a human hit the site.** The raw request count is a separate column, **`total_requests`**. Both are reported side by side everywhere below; neither is ever called a "page view".
2. **The join is keyed by company email domain, not lead id** — most of these prospects have no `leads_state` row when the demo is built, because site generation happens outside the normal pipeline. The fallback match is the demo URL. **Consequence: a demo recipient showing zero visits is NOT proof they never looked.** A missed domain match or a missing Vercel push is indistinguishable from a genuine non-visit. This ambiguity is restated at every point where a "0 visits" figure appears, and in §14.
3. **This table is the only long-term record.** It is populated by `WebsiteGenerator`'s `cli/visits.mjs --push`, which strips bots, crawlers, hosting/VPN networks and Mindaptive's own traffic before pushing. Free Vercel observability retains **1 day**, so these visits **cannot be re-derived from Vercel later**.

**Scope of the visit data against this postmortem:** the join file carries **40 demo recipients**. **3 of them belong to campaign 3886379 ("Website offer - Electric", launched 2026-09-01), which is outside this document's 5-campaign scope and is excluded from every number below.** The remaining **37 are an exact one-to-one match with the 37 demos this document independently identified from the threads** — no demo recipient is missing from the join and none is extra.

⚠ **One join hazard found and corrected.** Domain-keyed matching falsely linked `jlhheating@gmail.com` (a lead who received no demo and only replied "Stop sending email to this address we're not interested") to another prospect's visit record, because `gmail.com` is a shared public domain. **Four of the five campaigns' lists contain gmail.com leads.** The match was corrected to exact-email-first, with domain fallback only for company domains. Anyone re-running this join must handle freemail domains explicitly.

**Remaining data Smartlead does not hold, and which is absent here:**

- **Open rate and click rate.** Deliberately off account-wide (`DONT_EMAIL_OPEN` / `DONT_LINK_CLICK`); `open_count` and `click_count` are 0 on all 19,597 rows. **Whether an email was opened remains unanswerable** — only demo-site visits are tracked, and only after a demo was sent.
- **Revenue, deal value, CRM stage.** Smartlead has a `revenue` field in `campaign_lead_stats`; it is `0` on all five and is not wired to anything. Payment status for the one live deal (Diamond Heating, $1,600 proposal + Stripe link sent) is **not knowable from Smartlead**.
- **Job titles.** Not present in any of the five lists. All targeting was company-level.
- **Pre-filter list sizes, verification vendor, filter criteria.** Smartlead only holds the post-import list. §4 reports what the `custom_fields` blob implies and flags the rest as missing.
- **Meeting outcome.** "Meeting-Booked" is a Smartlead category. Whether the call happened is only knowable from the thread text (and in one of the three cases, it demonstrably did not).

**One reconciliation note:** `analytics.reply_count` (per-lead) and the count of `/statistics` rows carrying a `reply_time` disagree slightly (e.g. campaign 3960583: 8 vs 9). **Every rate in this document is computed from the `/statistics` rows**, so one denominator is used throughout. Lead-level de-duplication is applied (a lead who replies twice counts once).

---

# 1. Executive summary

## 1.1 Campaign 3960583 — "Website offer - Solar - USA- Recycled"

| Field | Value |
|---|---|
| Campaign id | 3960583 |
| Date range | 2026-09-15 → ongoing (first send 2026-09-15 13:22 UTC, last 2026-09-18) |
| Vertical / niche | Solar, renewables, battery storage, EV charging (US) — **see §4 for a serious ICP-drift finding** |
| Geography | USA (heavily CA, TX, FL). Sending window America/New_York 09:00–18:00 Mon–Fri |
| Lead source | Google Maps (`ICP_Source: "Google Maps"` on 1,564 of 2,479) + a web-scrape layer. "Recycled" = re-used from prior campaigns |
| Total leads in campaign | 2,479 |
| Leads emailed so far | 1,600 (879 not started) |
| Emails sent | 2,464 (step 1: 1,600; step 2: 864; **step 3: 0**) |
| Delivered (unique leads) | 1,505 |
| Bounced | 95 |
| Total replies (all, incl. machine) | 9 leads |
| Unique replies | 9 |
| **Real human replies** | **5** |
| Positive / interested | 3 |
| Neutral | 1 |
| Negative | 1 |
| Unsubscribe / not-interested replies | 1 (a formal CAN-SPAM cease-and-desist) |
| Meetings booked | **0** |
| Prospects who asked to see the website | 3 |
| Websites/demos generated | 3 |
| Prospects who received a demo | 3 |
| **Prospects with a recorded demo-site visit** | **2 of 3** (East County Solar Cleaner, StackRack) |
| Demo recipients with no recorded visit | 1 (Clear Efficiency — see §D caveat, absence is not proof) |
| Prospects who continued conversation after demo | 1 |
| Prospects who discussed price | 1 |
| Prospects who expressed buying intent | 1 |
| Closed deals | **0** |
| Revenue | **$0** (and not trackable in Smartlead — see above) |

Calculated:

| Metric | Value | Basis |
|---|---|---|
| Delivery rate | 94.06% | 1,505 / 1,600 |
| Bounce rate | 5.94% | 95 / 1,600 |
| Overall reply rate | 0.60% | 9 / 1,505 |
| Human reply rate | 0.33% | 5 / 1,505 |
| Positive reply rate (of delivered) | 0.20% | 3 / 1,505 |
| Positive as % of all replies | 33.3% | 3 / 9 |
| Positive as % of human replies | 60.0% | 3 / 5 |
| Meeting booking rate | 0.00% | 0 / 1,505 |
| Demo request rate | 0.20% | 3 / 1,505 |
| Demo → continued conversation | 33.3% | 1 / 3 |
| Demo → buying intent | 33.3% | 1 / 3 |
| Demo → sale | **not measurable yet** | 0 / 3, campaign is 4 days old |
| Positive reply → meeting | 0.0% | 0 / 3 |
| Positive reply → demo | 100.0% | 3 / 3 |
| Positive reply → buying intent | 33.3% | 1 / 3 |
| Positive reply → sale | **not measurable yet** | 0 / 3 |

⚠ **Caveat:** 4 days old, 35% of the list never contacted, step 3 never fired. These rates will move.

## 1.2 Campaign 3960357 — "Website offer - HVAC - USA - Recycled"

| Field | Value |
|---|---|
| Campaign id | 3960357 |
| Date range | 2026-09-15 → ongoing |
| Vertical / niche | HVAC contractors (US) |
| Geography | USA (TX, CA, FL heavy). America/New_York 09:00–18:00 |
| Lead source | Google Maps (1,087 of 1,781) + web-found homepage scrape; "Recycled" list |
| Total leads | 1,781 |
| Leads emailed so far | 1,561 (220 not started) |
| Emails sent | 2,403 (step 1: 1,561; step 2: 842; **step 3: 0**) |
| Delivered | 1,523 |
| Bounced | 38 |
| Total replies | 3 leads |
| Unique replies | 3 |
| **Real human replies** | **2** |
| Positive / interested | 2 |
| Neutral | 0 |
| Negative | 0 |
| Unsubscribe / not interested | 0 |
| Meetings booked | **0** |
| Asked to see the website | 2 |
| Demos generated / received | 2 |
| **Prospects with a recorded demo-site visit** | **0 of 2** ⚠ see §D — both demos were sent 2026-09-15/17 and neither has a visit row; absence is not proof |
| Continued after demo | 0 |
| Discussed price | 0 |
| Buying intent | 0 |
| Closed deals | **0** |
| Revenue | **$0** |

| Metric | Value | Basis |
|---|---|---|
| Delivery rate | 97.57% | 1,523 / 1,561 |
| Bounce rate | 2.43% | 38 / 1,561 |
| Overall reply rate | 0.20% | 3 / 1,523 |
| Human reply rate | 0.13% | 2 / 1,523 |
| Positive reply rate (of delivered) | 0.13% | 2 / 1,523 |
| Positive as % of all replies | 66.7% | 2 / 3 |
| Meeting booking rate | 0.00% | 0 / 1,523 |
| Demo request rate | 0.13% | 2 / 1,523 |
| Demo → continued / intent / sale | 0% / 0% / **not measurable yet** | one demo was sent 2026-09-17, i.e. 2 days ago |
| Positive → demo | 100.0% | 2 / 2 |

⚠ **Caveat: this campaign has 2 real human replies. Nothing in it is statistically meaningful.** It is 4 days old with step 3 unfired. Do not rank it against the others.

## 1.3 Campaign 3950427 — "Website offer - mixedICP - EU (roofers, medspas, home remodelers)"

| Field | Value |
|---|---|
| Campaign id | 3950427 |
| Date range | 2026-09-13 → ongoing (sends 2026-09-14 → 2026-09-18) |
| Vertical / niche | **Four** sub-verticals in one campaign (see §4.3, §9): Roofing companies, Building contractors, Med spas, Home renovators |
| Geography | **United Kingdom** (London 208, Glasgow 115, Birmingham 114, Manchester 108, Leeds 90…). Note: campaign named "EU", list is UK. Send window Europe/Zagreb 08:00–18:00 |
| Lead source | Google Maps — `ICP_Source: "Google Maps"` on **1,957 / 1,957 (100%)** |
| Total leads | 1,957 |
| Emails sent | 5,357 (step 1: 1,956; step 2: 1,813; step 3: 1,588) |
| Delivered | 1,827 |
| Bounced | 130 |
| Total replies | 39 leads |
| Unique replies | 39 |
| **Real human replies** | **21** |
| Positive / interested | 16 |
| Neutral | 1 |
| Negative | 4 |
| Unsubscribe / not interested | 4 (3 "not interested"/"stop", 1 confused-hostile) |
| Meetings booked | **0** |
| Asked to see the website | 16 |
| Demos generated / received | 17 (16 positive + 1 neutral challenge) |
| **Prospects with a recorded demo-site visit** | **9 of 17** |
| Demo recipients with no recorded visit | 8 (see §D caveat) |
| Continued after demo | 4 |
| Discussed price | 2 |
| Buying intent | 2 |
| Closed deals | **0** |
| Revenue | **$0** |

| Metric | Value | Basis |
|---|---|---|
| Delivery rate | 93.36% | 1,827 / 1,957 |
| Bounce rate | 6.64% | 130 / 1,957 |
| Overall reply rate | 2.13% | 39 / 1,827 |
| Human reply rate | 1.15% | 21 / 1,827 |
| **Positive reply rate (of delivered)** | **0.88%** | 16 / 1,827 — **the best of the five** |
| Positive as % of all replies | 41.0% | 16 / 39 |
| Positive as % of human replies | 76.2% | 16 / 21 — **the best of the five** |
| Meeting booking rate | 0.00% | 0 / 1,827 |
| Demo request rate | 0.88% | 16 / 1,827 |
| Demo → continued conversation | 23.5% | 4 / 17 |
| Demo → buying intent | 11.8% | 2 / 17 |
| Demo → sale | **not measurable yet** | 0 / 17, campaign is 6 days old |
| Positive → meeting | 0.0% | 0 / 16 |
| Positive → demo | 100.0% | 16 / 16 |
| Positive → buying intent | 12.5% | 2 / 16 |
| Positive → sale | **not measurable yet** | 0 / 16 |

## 1.4 Campaign 3912149 — "Website offer - HVAC - Europe - Eng"

| Field | Value |
|---|---|
| Campaign id | 3912149 |
| Date range | 2026-09-07 → ongoing |
| Vertical / niche | HVAC / plumbing & heating / renewables — **plus substantial off-ICP drift** (§4.4) |
| Geography | **United Kingdom** (campaign named "Europe"; every lead read was UK). Europe/Zagreb 08:00–18:00 |
| Lead source | **Recycled from a prior AI-secretary campaign.** `custom_fields` carries `campaign_id: "3278845"` plus that campaign's copy variables (`cta1`, `offer1`, `painPoint`, `ctaVideo`, `giftCTA`, `socialProof`) on all 1,256 leads |
| Total leads | 1,256 |
| Emails sent | 3,607 (step 1: 1,256; step 2: 1,183; step 3: 1,168) |
| Delivered | 1,181 |
| Bounced | 75 |
| Total replies | 30 leads |
| Unique replies | 30 |
| **Real human replies** | **9** — the other 21 were out-of-office / autoresponders |
| Positive / interested | 4 |
| Neutral | 1 |
| Negative | 4 |
| Unsubscribe / not interested | 4 |
| Meetings booked | **0** |
| Asked to see the website | 4 |
| Demos generated / received | 4 |
| **Prospects with a recorded demo-site visit** | **4 of 4 (100%)** — the only campaign where every demo recipient is recorded as having looked |
| Continued after demo | 3 |
| Discussed price | 2 |
| Buying intent | 2 |
| Closed deals | **0** |
| Revenue | **$0** |

| Metric | Value | Basis |
|---|---|---|
| Delivery rate | 94.03% | 1,181 / 1,256 |
| Bounce rate | 5.97% | 75 / 1,256 |
| Overall reply rate | 2.54% | 30 / 1,181 — **highest raw reply rate, but see next row** |
| Human reply rate | 0.76% | 9 / 1,181 |
| **Positive reply rate (of delivered)** | **0.34%** | 4 / 1,181 |
| Positive as % of all replies | 13.3% | 4 / 30 — **the worst of the five** |
| Positive as % of human replies | 44.4% | 4 / 9 |
| Meeting booking rate | 0.00% | 0 / 1,181 |
| Demo request rate | 0.34% | 4 / 1,181 |
| Demo → continued conversation | 75.0% | 3 / 4 |
| Demo → buying intent | 50.0% | 2 / 4 |
| Demo → sale | **0 of 4, and both price conversations closed as explicit losses** (not ghosts) |
| Positive → demo | 100.0% | 4 / 4 |
| Positive → buying intent | 50.0% | 2 / 4 |

⚠ **This campaign is the clearest example of why raw reply rate must not be the ranking metric.** It has the highest reply rate (2.54%) and the lowest positive share of replies (13.3%). **70% of its replies (21/30) were machines.**

## 1.5 Campaign 3892258 — "Website offer - HVAC - USA"

| Field | Value |
|---|---|
| Campaign id | 3892258 |
| Date range | 2026-09-02 → ongoing. **The oldest and therefore the only campaign with any late-funnel data at all.** |
| Vertical / niche | HVAC contractors (US) |
| Geography | USA, broad (Springfield, Aurora, NYC, Bridgeport, Peoria, Grand Rapids, Portland, Albuquerque…). America/New_York 09:00–18:00 |
| Lead source | Google Maps — `ICP_Source: "Google Maps"` on **2,409 / 2,409 (100%)**, with a `Selection_Tier` field ("A - site-confirmed email") |
| Total leads | 2,409 |
| Emails sent | 5,766 (step 1: 2,409; step 2: 1,950; step 3: 1,407) |
| Delivered | 2,367 |
| Bounced | 42 |
| Total replies | 33 leads |
| Unique replies | 33 |
| **Real human replies** | **21** |
| Positive / interested | 11 |
| Neutral | 1 |
| Negative | **9 — the highest negative count and share of any campaign** |
| Unsubscribe / not interested | 9 |
| **Meetings booked** | **3** (the only meetings in the whole dataset) |
| Asked to see the website | 11 |
| Demos generated / received | 11 |
| **Prospects with a recorded demo-site visit** | **9 of 11** |
| Demo recipients with no recorded visit | 2 (Airmark, Climate HVAC — see §D caveat) |
| Continued after demo | 4 |
| Discussed price | 2 (plus 1 more who asked for pricing and never received numbers) |
| Buying intent | 4 |
| Closed deals | **0** |
| Revenue | **$0** (one $1,600 proposal + Stripe deposit link outstanding since 2026-09-16) |

| Metric | Value | Basis |
|---|---|---|
| Delivery rate | 98.26% | 2,367 / 2,409 — **best deliverability of the five** |
| Bounce rate | 1.74% | 42 / 2,409 |
| Overall reply rate | 1.39% | 33 / 2,367 |
| Human reply rate | 0.89% | 21 / 2,367 |
| Positive reply rate (of delivered) | 0.46% | 11 / 2,367 |
| Positive as % of all replies | 33.3% | 11 / 33 |
| Positive as % of human replies | 52.4% | 11 / 21 |
| **Meeting booking rate** | **0.13%** | 3 / 2,367 |
| Demo request rate | 0.46% | 11 / 2,367 |
| Demo → continued conversation | 36.4% | 4 / 11 |
| Demo → buying intent | 36.4% | 4 / 11 |
| Demo → sale | **not measurable yet** | 0 / 11, 2 deals live as of 2026-09-17 |
| Positive reply → meeting | 27.3% | 3 / 11 |
| Positive reply → demo | 100.0% | 11 / 11 |
| Positive reply → buying intent | 36.4% | 4 / 11 |
| Positive reply → sale | **not measurable yet** | 0 / 11 |

⚠ Of the 3 "meetings booked": **one call actually happened** (Mid-City Heating, 2026-09-14), **one prospect no-showed twice and has since gone quiet** (HVAC Doctors), and **one is a Smartlead category set during an active proposal exchange** (Diamond Heating) where no call is evidenced in the thread. Section 6 has all three verbatim.

## 1.6 All five combined (reported only where combining does not destroy information)

| | Total |
|---|---|
| Leads in campaigns | 9,882 |
| Leads emailed (unique) | 8,783 |
| Emails sent | 19,597 |
| Delivered | 8,403 |
| Bounced | 380 (4.33%) |
| Replying leads (all) | 114 (1.36% of delivered) |
| **Real human replies** | **58 (0.69% of delivered)** |
| Automated / machine replies excluded | 56 (49.1% of all replies) |
| Positive | 36 (0.43% of delivered; 62.1% of human replies) |
| Neutral | 4 |
| Negative | 18 |
| Demos sent | 37 |
| **Demo recipients with a recorded site visit** | **24 (64.9% of demos)** |
| **Demo recipients with no recorded visit** | **13 (35.1%)** — ⚠ absence is not proof they didn't look; see §D |
| **Demo visited but prospect never replied ("silent but visited")** | **14** — see §7B2 |
| Continued after demo | 12 |
| Meetings booked | 3 |
| Price conversations | 7 |
| Buying intent | 9 |
| **Closed deals** | **0** |
| **Revenue** | **$0** |

---

# 2. Campaign comparison table

Raw numbers preserved. **Do not rank on `reply rate` alone** — column `pos % of replies` shows why (3912149 is top on reply rate and bottom on positive share).

| campaign | id | vertical | lead count | emailed | delivered | bounce rate | reply rate (all) | human reply rate | positive reply rate | positive replies | pos % of all replies | meetings | demos sent | **demos visited** | **silent-but-visited** | price convos | buying intent | closed deals | revenue | best-performing step-1 variant | worst-performing step-1 variant |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Solar USA Recycled | 3960583 | Solar/renewables US | 2,479 | 1,600 | 1,505 | 5.94% | 0.60% | 0.33% | 0.20% | 3 | 33.3% | 0 | 3 | **2 of 3** | **2** | 1 | 1 | 0 | $0 | **C** "I built {{co}} a fresh website this week" — 4 replies / 3 positive on 321 sent | **A** "my weird hobby" — 0 replies on 320 sent |
| HVAC USA Recycled | 3960357 | HVAC US | 1,781 | 1,561 | 1,523 | 2.43% | 0.20% | 0.13% | 0.13% | 2 | 66.7% | 0 | 2 | **0 of 2** ⚠ | **0** | 0 | 0 | 0 | $0 | **A / C** tied, 1 positive each — *sample far too small to call* | **B / D** 0 replies each — *sample far too small to call* |
| mixedICP EU | 3950427 | Roofing / building contractors / med spas / home renovators (UK) | 1,957 | 1,957 | 1,827 | 6.64% | 2.13% | 1.15% | **0.88%** | 16 | 41.0% | 0 | 17 | **9 of 17** | **6** | 2 | 2 | 0 | $0 | **D** "{{co}}'s fresh website is live" — 12 replies / 5 positive on 490 | **C** "your redesigned website is live" — 8 replies / 4 positive on 486 (*all four variants overlap; no real separation*) |
| HVAC Europe Eng | 3912149 | HVAC/plumbing UK | 1,256 | 1,256 | 1,181 | 5.97% | **2.54%** | 0.76% | 0.34% | 4 | **13.3%** | 0 | 4 | **4 of 4 (100%)** | **1** | 2 | 2 | 0 | $0 | **C** "your redesigned website is live" — 9 replies / 2 positive on 314 | **A** "my weird hobby" — 9 replies / **0 positive** on 314 |
| HVAC USA | 3892258 | HVAC US | 2,409 | 2,409 | 2,367 | **1.74%** | 1.39% | 0.89% | 0.46% | 11 | 33.3% | **3** | 11 | **9 of 11** | **5** | 2 | 4 | 0 | $0 | **D** "{{co}}'s fresh website is live" — 9 replies / 4 positive on 604 | **C** "your redesigned website is live" — 8 replies / 2 positive on 595 (*overlapping; see §13*) |

**New column definitions:** *demos visited* = demo recipients with at least one recorded human visit to their demo site (a "visit" is one 4-hour Vercel request block, not a page view — see §D). *silent-but-visited* = prospects who received a demo, are recorded as having visited it, and **never replied after the demo** (§7B2). A demo recipient with no recorded visit may simply be a domain-match miss; absence is not proof.

**Sample-size warning attached to every "best/worst variant" cell above:** with 2–5 positive replies per arm, no variant difference in any campaign clears statistical significance. See §13 for the full breakdown and the explicit statement of which comparisons are and are not valid.

---

# 3. Exact outreach messages

Pulled verbatim from `GET /campaigns/{id}/sequences` (templates) and from the actual `SENT` message bodies in the threads (rendered examples, demo-delivery and pricing emails, which are hand-written and exist only in the threads).

**Structural facts true of all five campaigns:**
- Three steps. Step 1 has 4–5 A/B variants, step 2 has 2 variants, step 3 has **no** variants (single template).
- `seq_delay_details` is `{delayInDays: 1}` before step 1, then `{delayInDays: 2}` before step 2 and step 3 — i.e. a roughly 2-day-apart, 3-touch sequence (observed real gaps ran 2–7 days).
- `send_as_plain_text: true` on all five.
- Step 2 and step 3 carry **empty subject lines**, so they thread as `RE: <step 1 subject>`.
- `%signature%` and `%sender-firstname%` are Smartlead spintax/merge tokens; `{{companyNickname}}`, `{{icebreaker}}`, `{{subjectLine}}`, `{{vertical}}` are lead custom fields.

## 3.1 Campaign 3960583 — Solar USA Recycled

**STEP 1 — variant A** (id 7691680) · subject: `my weird hobby`
```
Some people gather stamps. I build websites for Solar companies who have no idea I exist.
This week it was {{companyNickname}}'s turn. Website is finished and sitting on a server.
Want to see how it looks? Just give me a quick 'yes' and I'll send you the link.
PS: If you think it's garbage, tell me it's garbage. That's genuinely useful to me. If you like it we can talk.
Thanks
%signature%
```
Sent 320 · delivered (est.) 301 · replies 0 · reply rate **0.00%** · positive 0 · positive rate 0.00% · meetings/demos/sales 0

**STEP 1 — variant B** (id 7691681) · subject: `built you a website, no charge to look`
```
I built {{companyNickname}} a fresh website this week. You didn't ask, I know. I did it anyway.
What I did:
Rebuilt the whole thing with modern design. Loads instantly on mobile and pc with improved SEO. I even included a live Ai Agent on the site.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll leave you alone. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 319 · replies 2 · reply rate 0.63% · **positive 0** (both were autoresponders) · meetings/demos/sales 0

**STEP 1 — variant C** (id 7691682) · subject: `I built {{companyNickname}} a fresh website this week`
```
Hi, You didn't ask, I know. I did it anyway. I'm %sender-fir
Hi,
You didn't ask, I know. I did it anyway. I'm %sender-firstname%, Co-Founder of Mindaptive. This isn't a standard cold pitch, I actually built something from scratch for {{companyNickname}}.
What I did:
Rebuilt the whole site with modern design. Loads instantly on mobile and pc with improved SEO. I even included a live Ai Agent on the site.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll step back. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 321 · replies 4 · reply rate 1.25% · **positive 3** · positive rate 0.93% · demos 3 · price convos 1 · meetings 0 · sales 0

> 🐞 **COPY DEFECT, PRESERVED VERBATIM AND VERIFIED IN DELIVERED MAIL.** The first line `Hi, You didn't ask, I know. I did it anyway. I'm %sender-fir` is a truncated duplicate of the opening, with the merge token cut off mid-word. It is in the stored template **and it was delivered to real prospects** — confirmed in the actual `SENT` bodies to `info@koolkoncepts.com` (campaign 3960357), `info@evgo.com`, `sid@eastcountysolarcleaner.com`, `sales@stackrackbattery.com` and `admin@clearefficiency.com`. The same defect exists in variant C of campaign 3960357. Notably, **this is nonetheless the best-performing variant in this campaign.**

**STEP 1 — variant D** (id 7691683) · subject: `{{companyNickname}}'s fresh website is live`
```
{Hey|Hi}, {{icebreaker}}
While looking around I got motived and wanted to make your website better
Here is what I did:
Rebuilt the whole thing with modern design. Loads instantly on mobile and pc with improved SEO. I even included a live Ai Agent on the site.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll step back. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 320 · replies 2 · reply rate 0.63% · positive 0 · (typo preserved: "motived")

**STEP 1 — variant E** (id 7691939) · subject: `{{subjectLine}}` (per-lead custom subject)
```
{Hey|Hi}, {{icebreaker}}
While looking around I got motived and wanted to make your website better
Here's what I did:
Rebuilt the whole thing with modern design. Loads instantly on mobile and pc with improved SEO. I even included a live Ai Agent on the site.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll leave you alone. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 320 · replies 1 · reply rate 0.31% · positive 0
*(E differs from D only in: subject source, "Here's" vs "Here is", and "leave you alone" vs "step back".)*

**STEP 2 — variant A** (id 7691684) · subject: *(empty → `RE:` step 1)*
```
I'll keep your site live on the server for another 48hrs. It takes 10 secs to take look.

Let me know,
Thanks
```
**STEP 2 — variant B** (id 7691685) · subject: *(empty)*
```
This might sound a bit odd...

but it is not scam. I'm real person and literally did this for {{companyNickname}}. All I want is if you could take a look and judge it yourself.

Appreciate it,
%signature%
```
Step 2 combined: 864 sent · 1 reply attributable to step 2.

**STEP 3** (no variants) · subject: *(empty)*
```
This is my last email. I'll take the {{companyNickname}}'s redesigned website down in a few hours to free up some space for new projects.

Last chance to take a look. Thanks for your time.

%signature%
```
**Sent: 0. This step has never fired in this campaign.** (Grammatical artefact preserved: "the {{companyNickname}}'s".)

## 3.2 Campaign 3960357 — HVAC USA Recycled

**STEP 1 — variant A** (7691281) · subject: `my weird hobby` — identical to 3960583/A but "HVAC companies" instead of "Solar companies".
Sent 391 · replies 2 · reply rate 0.51% · positive 1 · positive rate 0.26% · demos 1

**STEP 1 — variant B** (7691282) · subject: `built you a website, no charge to look` — identical to 3960583/B.
Sent 392 · replies 0 · positive 0

**STEP 1 — variant C** (7691283) · subject: `I built {{companyNickname}} a fresh website this week` — identical to 3960583/C **including the `%sender-fir` truncation defect**, except "Co-Founder @ Mindaptive" rather than "Co-Founder of Mindaptive".
Sent 390 · replies 1 · reply rate 0.26% · positive 1 · positive rate 0.26% · demos 1

**STEP 1 — variant D** (7691284) · subject: `{{companyNickname}}'s fresh website is live`
```
I redesigned {{companyNickname}}'s website this week. You didn't ask, I know. I did it anyway.
What I did:
Rebuilt the whole thing. Loads instantly on mobile and pc. Dial button that follows users down the page. Your services laid out so someone can find in two seconds instead of scrolling through a wall of text. Your Google reviews pulled in and showing.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll leave you alone. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 388 · replies 0 · positive 0

**STEP 2 A** (7691285) / **STEP 2 B** (7691286): identical to 3960583's step 2 A/B except "the site" vs "your site". 842 sent, 1 reply.
**STEP 3** (single): identical text to 3960583 step 3. **Sent: 0 — never fired.**

## 3.3 Campaign 3950427 — mixedICP EU

This campaign's step-1 variants A and B use a `{{vertical}}` token, so the same template rendered as "Roofing companies", "Building contractors", "Med spas" or "Home renovators" per lead.

**STEP 1 — variant A** (7669221) · subject: `my weird hobby`
```
Some people gather stamps. I build websites for {{vertical}} who have no idea I exist.
This week it was {{companyNickname}}'s turn. Website is finished and sitting on a server.
Want to see how it looks? Just give me a quick 'yes' and I'll send you the link.
PS: If you think it's garbage, tell me it's garbage. That's genuinely useful to me. If you like it we can talk.
Thanks
%signature%
```
Sent 489 · replies 9 · reply rate 1.84% · positive 4 · positive rate 0.82% · demos 4 · meetings 0 · sales 0

**STEP 1 — variant B** (7669222) · subject: `built you a website, no charge to look`
```
I built {{companyNickname}} a fresh website this week. You didn't ask, I know. I did it anyway.
What I did:
Rebuilt the whole thing with modern design. Loads instantly on mobile and pc. I even included a live Ai Agent on the site.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll step back. If it is, we can talk.
I usually work with {{vertical}} and I built hundreds of projects over the years. Reply and I'll send the link to your website.
Thanks
%signature%
```
Sent 491 · replies 10 · reply rate 2.04% · positive 3 · positive rate 0.61% · demos 3

**STEP 1 — variant C** (7669223) · subject: `your redesigned website is live`
```
I built {{companyNickname}} a fresh website this week. You didn't ask, I know. I did it anyway.
What I did:
Rebuilt the whole thing with modern design. Loads instantly on mobile and pc. Better SEO and I even included a live Ai Agent on the site.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll step back. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 486 · replies 8 · reply rate 1.65% · positive 4 · positive rate 0.82% · demos 4

**STEP 1 — variant D** (7669224) · subject: `{{companyNickname}}'s fresh website is live`
```
I redesigned {{companyNickname}}'s website this week. You didn't ask, I know. I did it anyway.
What I did:
Rebuilt the whole thing. Loads instantly on mobile and pc. Dial button that follows users down the page. Your services laid out so someone can find in two seconds instead of scrolling through a wall of text. Your Google reviews pulled in and showing.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll step back. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 490 · replies 12 · reply rate **2.45%** · positive 5 · positive rate **1.02%** · demos 5 · price convos 1

**STEP 2 A** (7669225) / **B** (7669226): same text as §3.1's step 2. 1,813 sent · 6 replies attributed to step 2.
**STEP 3** (single, 1,588 sent · 3 replies):
```
This is my last email. I'll take the {{companyNickname}}'s redesigned website down in a few hours to add some space for fresh projects.

Last chance to take a look. Thanks for your time.

%signature%
```

## 3.4 Campaign 3912149 — HVAC Europe Eng

**STEP 1 — variant A** (7552003) · subject: `my weird hobby` — identical to 3960357/A ("HVAC companies").
Sent 314 · replies 9 · reply rate 2.87% · **positive 0** · positive rate **0.00%** · demos 0

**STEP 1 — variant B** (7552004) · subject: `built you a website, no charge to look` — as 3960357/B.
Sent 315 · replies 5 · reply rate 1.59% · **positive 0** · demos 0

**STEP 1 — variant C** (7552005) · subject: `your redesigned website is live`
```
I built {{companyNickname}} a fresh website this week. You didn't ask, I know. I did it anyway.
What I did:
Rebuilt the whole thing with modern design. Loads instantly on mobile and pc. I even included a live Ai Agent on the site.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll leave you alone. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 314 · replies 9 · reply rate 2.87% · positive 2 · positive rate 0.64% · demos 2 · price convos 1

**STEP 1 — variant D** (7552006) · subject: `{{companyNickname}}'s fresh website is live` — as 3960357/D ("Dial button…Google reviews").
Sent 313 · replies 7 · reply rate 2.24% · positive 2 · positive rate 0.64% · demos 2 · price convos 1

**STEP 2 A** (7552007) / **B** (7552008): standard. 1,183 sent · 4 replies.
**STEP 3** (single): standard "This is my last email…free up some space for new projects." 1,168 sent · 4 replies.

## 3.5 Campaign 3892258 — HVAC USA

**STEP 1 — variant A** (7510142) · subject: `my weird hobby` — standard HVAC wording.
Sent 599 · replies 9 · reply rate 1.50% · positive 2 · positive rate 0.33% · demos 2 · **meetings 1** (Mid-City Heating)

**STEP 1 — variant B** (7510143) · subject: `built you a website, no charge to look`
Sent 611 · replies 7 · reply rate 1.15% · positive 3 · positive rate 0.49% · demos 3

**STEP 1 — variant C** (7510144) · subject: `your redesigned website is live`
```
Hi,
I built {{companyNickname}} a fresh website this week. You didn't ask, I know. I did it anyway.
What I did:
Rebuilt the whole thing with modern design. Loads instantly on mobile and pc. I even included a live Ai Agent on the site.
What I want:
Just to have you take a look. That's it. If it's not better than what you have, say so and I'll leave you alone. If it is, we can talk.
Reply and I'll send the link.
Thanks
%signature%
```
Sent 595 · replies 8 · reply rate 1.34% · positive 2 · positive rate 0.34% · demos 2 · **price convo 1** (United Heating, live)

**STEP 1 — variant D** (7510145) · subject: `{{companyNickname}}'s fresh website is live` — the "Dial button / Google reviews" body.
Sent 604 · replies 9 · reply rate 1.49% · positive 4 · positive rate 0.66% · demos 4 · **meetings 2** (Diamond Heating, HVAC Doctors) · **price convo 1** (Diamond, the $1,600 proposal)

**STEP 2 A** (7510178) / **B** (7510179): standard. 1,950 sent · 8 replies.
**STEP 3** (single): standard. 1,407 sent · 4 replies.

## 3.6 The "send it" reply message — i.e. the demo-delivery email

**This is hand-written per lead, not a template.** It does not exist in the Smartlead sequence at all; it lives only in the threads. There are 37 distinct versions. The recurring structure is: link → 3–4 bullets naming the AI assistant, per-service SEO pages and the qualifying quote form → "connects to whatever you run dispatch on" → "this is only the first version, I usually do at least 3 rounds of revisions" → a CTA.

Four verbatim examples spanning the range:

**(a) Kool Koncepts (3960357), 2026-09-15 — the "reply if you like it and I'll send pricing" CTA**
```
Here is your new website -> https://kool-koncepts.vercel.app

What I added.
Fresh design with a modern approach
An AI assistant on every page. Ask at 10pm whether you work on Trane units or what a service call costs and it answers from your own services and pricing.
Air conditioning, heating and furnaces, heat pumps and commercial HVAC each get a page Google SEO can rank.
A quote form that asks what needs service, how urgent it is, the property type and the ZIP, so leads arrive sorted.
And many more functionalities that make sure your cusomters have the best experience

Quotes land in your sales board, CRM system or email inbox. I can connect this website to basically anything.
Please note that this is only the initial version of the website. There is still work to be done to adjust the design, visuals and content. I usually do at least 3 rounds of revisions.
Just reply if you like the site and I'll send over the pricing and next steps.

Thanks,
Andrew
```

**(b) HVAC Doctors (3892258), 2026-09-09 — the "three things it does that your current one can't" CTA**
```
Here is your new website, Michael -> https://hvac-doctors-sc.vercel.app

Three things it does that your current one can't:

• An AI agent on every page, answering at 11pm while you're on a job. It knows your prices, your hours and your service area.
• Seven real service pages on your own domain, each one something Google can rank.
• An estimate form that asks what's broken and how urgent, so leads reach you already qualified.

It connects to whatever you run dispatch on, so requests land in your board instead of an inbox someone has to retype.

Let me know what you think

Thanks,
Andrew
```

**(c) Dr Band Clinic (3950427), 2026-09-15 — med-spa version, note the apology for the 1-day delay**
```
Hi Dr Band, here is your new website -> https://drband-clinic.vercel.app
What I added:
• An AI assistant that answers price and treatment questions at midnight, when men are actually researching this.
• Your before-and-afters sit right under the hero now. Move the mouse across a face to see the change, then scroll all 30 cases.
• Every treatment has its own page, so Google SEO can rank you for "jawline filler London" and "Endolift London" separately.

Enquiries can go straight into your booking system instead of an inbox. This is only the first version of the website, I usually do at least 3 rounds of revisions.
P.S: Sorry for answering the next day. I was locked in on a project yesterday and the day got away from me.
Let me know your thoughts.
Best,
Mia
```

**(d) BDS Services (3912149), 2026-09-10 — the rebuttal after the prospect said the demo looked the same as their existing site**
```
Thanks for taking a look, and that's fair on the homepage.

The words and photos are deliberately yours. I wasn't going to invent services or reviews you don't have. That's why it reads familiar. The layout itself I can change however you want, that part is open.

The new bits aren't on the homepage. Three things, about 30 seconds each:

Chat bubble, bottom right. Ask it "how much for a 4m x 5m bedroom?" It's a real AI assistant, not a contact form, and it answers from your own prices.
bds-services.vercel.app/systems - type in a room size and it gives you the kW you'd fit plus the price straight off your own list.
bds-services.vercel.app/service-areas/birmingham - one of 12 town pages. Right now you have one page trying to rank for every town. This gives each one its own.

If you've tried those and still think it's the same as what you have, say so and I'll leave it there.

If not, what would you change first? It's a first draft and two rounds of changes are included. Tell me what you would want to improve and I'll see what I can do.

Thanks,
Mia
```

## 3.7 The post-demo nudge sequence (also hand-written, not in Smartlead)

Sent to prospects who received a demo and went quiet. Observed in this order:

**Nudge 1 — "what do you think" (≈2–4 days after demo)**
```
What do you think about your new website, {name}?
Did you try the new Ai Agent feature?
I would appreciate your feedback.
Thanks
Andrew
```
> 🐞 **COPY DEFECT, DELIVERED TO REAL PROSPECTS.** The `{name}` merge failed on at least 6 sends, producing the literal line **`What do you think about your new website,?`** — verbatim to Airmark AC, Cosmo's, Free State Cooling, DC Air and Heating, PROFLO, Climate HVAC Solutions (all 3892258), HSB Renewables (3912149), MTF Roofing (3950427), and East County Solar Cleaner + Clear Efficiency (3960583). Where the merge worked it reads "…new website, Christina?".

**Nudge 2 — takedown threat (≈7 days after demo)**
```
Hi {name},
your new website comes down in about 48 hours. I need some space on the server for other projects.
Whatever you decide, I'd appreciate a sentence on what you made of it. Even a blunt one helps me build the next one better.
But if you'd rather keep it up while you think it through, just say so before then.
Best,
Andrew
```

**Nudge 3 — final heads-up**
```
Hi {name},
This is my final email. I'll be taking the website down this evening to free up the server.
Just wanted to give you a final heads-up. If you want me to hold off, just hit reply and let me know.
Best,
Andrew
```

**Nudge 4 — post-takedown re-open offer**
```
Hi {name}, this is my last email. Your website is no longer available. If you would like me to upload it again for your review let me know and I'll put it live again.
Thank you for your time.
Andrew
```

**Short bump variant** (used mid-thread, often the same day the price was sent +1–2 days):
```
Wanted to make sure you saw this, {name}. Let me know either way.
Thanks,
Andrew
```

> **Note for the analysing agent:** every one of these nudges appears in a thread that ultimately produced no reply. **Zero replies in this dataset were generated by nudges 2, 3 or 4.** Nudge 1 produced 2 replies (Elevation Roofing "Yh I like it, how much…", MTF Roofing "Ive not seen the link to It??"). The "Wanted to make sure you saw this" bump produced 1 (Cosytoes' decline).

## 3.8 The pricing / closing emails

**Every price in this dataset was quoted only after the prospect explicitly asked.** There are 7 such emails and they are **not consistent with each other** — the same offer was priced at $580, $650 (£650), $850, £850, $950, $1,200 and $1,600 across seven prospects within 16 days. All seven are reproduced verbatim because the inconsistency is itself a finding for the analysing agent.

**(a) Clear Efficiency (3960583), 2026-09-15 — $850 one-time + $49/$79 monthly, pay-on-launch, Calendly**
```
Sure, take your time.
That entire website is yours for $850, one time. That's the whole thing.
How it works:
You send me what you want to change or add (photos, branding, etc..), and anything you want worded differently. That's the only thing I need from you. We can do that on a call or over email.
I finish it and send it back. Three rounds of changes. Anything you don't like, I will fix it. Any design change you want, it's covered.
When you approve it, it's live in 5 days. Your current site stays up, untouched, until that moment.
You pay the $850 on launch day, not before. If we go through the changes and you still don't want it, you don't pay me anything.

After launch:
Website Care — $49/month. Hosting, security, and content changes whenever you need them.
Website + AI — $79/month. Same, plus the AI assistant answering customers and taking enquiries.

Cancel either one whenever you want. No locking contract.
Let me know your thoughts. If you'd like to meet and go over more info feel free to select a time on my calendar here -> https://calendly.com/andrew-mindaptive/website-redesign
Thanks,
Andrew
```

**(b) AC Comfort (3912149), 2026-09-07 — $580 one-time + $49/$79 monthly**
```
Glad that landed, Mary.
That site is yours for $580, one time. That's the whole thing. The site you just looked at, finished with your branding and photos, SEO set up so people find you when they search for Air conditioning in your area, and live on your domain.
How it works:
You send me what you want to change or add (photos, branding, etc..), and anything you want worded differently. That's the only thing I need from you. No calls, no forms, no chasing.
I finish it and send it back. Three rounds of changes. Anything you don't like, I will fix it.
When you approve it, it's live in 5 days. Your current site stays up, untouched, until that moment.
You pay the $580 on launch day, not before. If we go through the changes and you still don't want it, you don't pay and we shake hands. I'd rather lose the work than have you pay for something you're not happy with.
After launch:
Website Care — $49/month. Hosting, security, and small changes whenever you need them.
Website + AI — $79/month. Same, plus the AI assistant answering customers and taking enquiries.
Cancel either one whenever you want. No contract.
If you'd like to handle this over the phone you can call or message me anytime on whatsapp: +385 97766 9883
Thanks,
Andrew
```

**(c) Elevation Roofing (3950427), 2026-09-16 — £650 one-time + £35/£65 monthly, sent to a prospect who had just said money was tight**
```
If now is a quite time for you, that is exactly what a new website with better SEO could help solve. Its yours for £650, one time. That's the whole thing. The site you just looked at, finished with your branding and photos.
How it works:
You send me what you want to change or add (photos, branding, etc..), and anything you want worded differently. That's the only thing I need from you.
I finish it and send it back. Three rounds of changes. Anything you don't like, I will fix it.
When you approve it, it's live in 5 days. Your current site stays up, untouched, until that moment.
After launch you have two options to choose from:
Website Care — £35/month. Hosting, security, and small changes whenever you need them.

OR
Website + AI — £65/month. Same, plus the AI assistant answering customers and taking enquiries.

Cancel either one whenever you want. No contract.
Let me know what you think.
Thanks,
Andrew
```

**(d) Omry Building Contractors (3950427), 2026-09-15 — three tiers, £850 / £1,250 / £1,450, Calendly close**
```
Hi,

Glad the idea landed. 30% is enough to start. What you saw is a first version, not the finished site. I usually do 3 rounds of revisions before anything goes live, so your wording, photos, design and details replace whatever I guessed. That way we can get it to 100%

Each option is a one-off build plus a monthly plan that keeps it running. No annual lock-in.

Website. £850, £45 a month
The site you clicked through, live on your own domain. Service pages, quotation form, works on a phone.

Website + assistant. £1,250, £75 a month
Same as the first option but it includes an Ai Assistant that answers questions on your website 24/7

Website + assistant + job routing. £1,450, £95 a month
Same as above, with enquiries landing in the board/CRM system you already use instead of an inbox.

The monthly covers hosting, SSL, backups, security, and unlimited text and price changes. Whenever you want to change something on the website you just text/email me the details, and the change is usually live inside 24 hours.

To get this live we usually jump on a call, you tell me what to change and how you would want to improve the site. 4-5 days after that your new website is live.
If one the options works for you or you want to get more info on the available options, select a time slot that works for you here -> https://calendly.com/andrew-mindaptive/website-redesign

Best,
Mia
```

**(e) Cosytoes (3912149), 2026-09-09 — £850 / £1,250, the most detailed version, written to be forwarded internally**
```
Hi Mike,
Glad it landed well. Here are the numbers, set out so you can forward this straight to your colleagues.
One thing up front. What you've seen is a starting point, not a finished site. I built it from your brochure and your current pages, so some of it will be wrong. Two rounds of revisions are included in every option below, before anything goes live. Your wording, your photos, your product detail, your call.

THE TWO OPTIONS
Each one is a one-off build fee plus a monthly plan that keeps it running.
1. Website. £850 to build, £45 a month
Everything you've clicked through, live on cosytoes.co. Every mat, cable and control unit, working properly on a phone.
The enquiry form asks what floor finish and what stage the project is at, so what reaches your inbox is already sorted.

2. Website + AI Assistant. £1,250 to build, £75 a month
The assistant you tried on the demo is a prototype. When fully trained it answers sizing and technical questions day and night, off your own brochure and spec sheets, and hands over to you when it should.
It also adds a sizing calculator: the customer types in their room size and floor finish, and gets back the exact mat and the control that goes with it.

WHAT THE MONTHLY COVERS
£45 buys hosting, SSL, daily backups, monitoring, support and security, so nobody at your end has to think about it.
£75 adds the assistant running day and night. Its running costs are included.

ONGOING CHANGES
You asked about this specifically, so to be clear, the monthly plan covers:
Pricelist alterations. Across the whole list, at no charge. Send me the new list and it is live within one working day.
Brochure and PDF swaps, product photos, text and spec corrections. Same.
Anything larger, a whole new product range or a new section of the site, is worth twenty minutes on a call once I know how often that actually comes up for you. I would rather price it against how you really work than guess at it now.

Nothing is locked in for a year, you can stop any month. Let me know what you think.

Thanks,
Andrew
```

**(f) United Heating (3892258), 2026-09-17 — $950, "own it" vs "I run it", answering 8 ownership/SEO/lock-in questions**
```
Hi Ed,

Everything you asked for is a yes. The one thing that decides a few of the answers is whether you want to run the site or whether you want me to run it, so let me lay that out first.

Option A. It is all yours.
One-off fee, $950. I build it, do the revisions, change everything you want on the page including adding pages and removing them. Then hand over the full source code, put everything in your name, and help you get the hosting set up.
After that you own the lot and you pay me nothing, monthly or otherwise. You or your team make the changes.

Option B. I run it for you.
$950 to build, then $45 a month. I host it, I make every change you ask for, I fix anything that breaks, I handle backups, SSL and security.
You email me what you want changed and it is done the same day. You still own the domain, the content and the code, and you can take it and leave whenever you want. This is the no-thinking-about-it option.

Now your questions:
Built in React on TanStack Start, same family as Next.js. The pages are rendered on the server, so Google gets the finished page instantly and it loads faster than WordPress. No plugins to break.
Yes. Under Option A it is handed straight over. Under Option B it is still yours and I hand it over any time you ask.
and 4. Under Option A, yes, everything: pages, text, images, service areas, blog, SEO titles and meta descriptions. One question there, do you want a visual editor where you click and save, or will your team edit the code directly? Both work, I just need to know which to build. Under Option B you do not edit anything, you just tell me and I do it, at no extra charge.
Yes, both included.
Yes. Every service and every town gets its own page with its own title, meta description, H1 and content. One page listing all your towns ranks for none of them. A page per town is what shows up for "AC repair Cary".
No licences, no plugin fees, no maintenance fees, ever. Under Option A hosting is the only cost and it is small, paid by you directly. Under Option B the $45 covers it all.
You do, either way. Domain, code, images, content, hosting account, all in your name. Nothing is registered under me. If you decide to cancel the monthly parthership you keep everything.

Let me know if that makes sense.

Thanks,
Andrew
```

**(g) Diamond Heating (3892258) — the furthest-progressed commercial exchange in the dataset. TWO emails.**

*g1 — 2026-09-16, the proposal + Stripe deposit link:*
```
Hi Derien,
As promised, we looked further into WEX Field Service Management. We confirmed that it can be connected to the new website through Zapier, allowing enquiries to be added to your existing CRM workflow
We will handle that connection during the final launch stage, together with connecting the completed website to your domain. We will complete both connections with you during a short screen-sharing call once the website changes are approved and ready to launch.
I have attached the proposal outlining everything included in the $1,600 project and the ongoing $120 monthly service.
The next steps are:
Pay the $800 project deposit -> https://buy.stripe.com/7sY6oH9syf4V1tngN49IQ04
Complete the onboarding form and upload any current photos, company documents and information we should use -> https://yourlaunchcheck.vercel.app/c/diamond-heating-cooling-hh0n3h - It good to have your demo site on hand while going through that -> https://diamond-heat-cool.vercel.app/
We will complete the requested website changes, build the enquiry flow, prepare the AI assistant and send everything back for your review.
Once everything is approved, the remaining $800 project balance is due. We will then schedule the final connection call, connect WEX FSM and the domain, perform the final checks and launch the website. The $120 monthly service begins after launch.

The onboarding form saves automatically, so you can stop at any time and return to the same link later. When everything is complete, click "I am done — send it over."
If anything is unclear while completing it, just reply and we'll help.
Thank you,
Mia
```

*g2 — 2026-09-17, the 4-tier breakdown the prospect asked for after receiving g1:*
```
Hi Derien,

Here is the full breakdown, with or without the AI assistant. Each option is attached as its own one-page proposal.

1. Website -> $950 one-time, $49/month
The full website live on your domain: all services, the commercial HVAC page, a local SEO page for each area you cover, the enquiry and quote form, three revision rounds. Enquiries are emailed to the office. No AI assistant, no CRM connection.

2. Website + AI assistant -> $1,200 one-time, $89/month
Everything above, plus the AI assistant you saw on the demo, trained on your own documents and answering customers day and night. It collects the customer's details in conversation and sends them to the office.

3. Website + WEX FSM connection -> $1,200 one-time, $79/month
Everything in option 1, plus the enquiry and quote system wired directly into WEX FSM. This is the option if you want the CRM side but not the AI assistant.

4. Everything -> $1,600 one-time, $120/month
Website, AI assistant and the WEX FSM connection together. This is the proposal I sent earlier.

The same terms apply to all of them: up to 7 days to launch once we have your feedback, 50% to start and 50% at launch via Stripe, month-to-month with no lock-in contract, and text, price or photo changes sent to us by email or WhatsApp go live within 24-48 hours.

Thank you,
Mia
```

**Price summary table (raw, for the analysing agent to compare):**

| Prospect | Campaign | Vertical | Currency | One-time | Monthly options | Payment terms | Outcome |
|---|---|---|---|---|---|---|---|
| AC Comfort | 3912149 | HVAC UK | USD | $580 | $49 / $79 | pay on launch | Lost — stock/market uncertainty |
| Elevation Roofing | 3950427 | Roofing UK | GBP | £650 | £35 / £65 | (not stated) | Ghosted after price |
| Clear Efficiency | 3960583 | Solar/HVAC US | USD | $850 | $49 / $79 | pay on launch | Ghosted after price |
| Omry Building | 3950427 | Building contractor UK | GBP | £850 / £1,250 / £1,450 | £45 / £75 / £95 | (not stated) | Ghosted after price |
| Cosytoes | 3912149 | Underfloor heating UK | GBP | £850 / £1,250 | £45 / £75 | (not stated) | Lost — budget freeze |
| United Heating | 3892258 | HVAC US | USD | $950 / $950 | $0 (own it) / $45 | (not stated) | **LIVE** as of 2026-09-17 |
| Diamond Heating | 3892258 | HVAC US | USD | $950 / $1,200 / $1,200 / $1,600 | $49 / $89 / $79 / $120 | 50% deposit via Stripe | **LIVE** as of 2026-09-17 |

---

# 4. Lead / list information

Everything below is recovered from the `leads-export` CSV's `custom_fields` JSON blob, which is the source spreadsheet as imported. **What Smartlead cannot tell us is stated explicitly per campaign.**

**Missing for all five campaigns, with no way to derive it from Smartlead:**
- Number of leads **before** filtering (Smartlead only holds what was imported).
- The exact filter criteria used in the scrape (review count thresholds, rating floors, employee count, radius).
- The email-verification **vendor**. Fields named `Verification_Status` / `Verify_Status` / `Email_Status` exist with values like `Valid`, `Web-found (homepage)` — so verification clearly happened, but which tool is not recorded.
- **Job titles — absent from all five lists.** All targeting is company-level, to generic mailboxes (`info@`, `service@`, `office@`, `sales@`, `enquiries@`). Among the 114 replying leads, a meaningful number of replies came from a *different* personal address than the one emailed (e.g. `strongholdroof@icloud.com` replying to mail sent to `info@stronghold-roofing.uk`; `mike@nationalenergyinstallers.com` replying to `info@`; `gary@londonbuildingsolutions.com` replying to `info@`; `Whiteside@tdirefrigeration.com` replying to `getcold@`).
- Business size / revenue / employee count. Proxies only: Google review count (`Reviews`) and rating (`Maps_Rating` / `Rating`).

## 4.1 Campaign 3960583 — Solar USA Recycled

| | |
|---|---|
| Vertical (intended) | Solar installers, US |
| Sub-vertical | none declared; the list has **no `vertical` field at all** (`vertical` = null on all 2,479) |
| Geography | USA. `location` is blank on 577 of 2,479 (23%). Present values skew CA/TX/FL. **At least one lead has a Spanish address ("C/ Gabriel Campillo, s/n, Pol. Ind. La S…") — a Spanish company inside a "USA" list.** |
| Business size | Not captured. `Reviews` present on only 111 of 2,479; `Maps_Rating` on 100 |
| Job titles | **None** |
| Source | `ICP_Source: "Google Maps"` on 1,564 / 2,479 (63%). The remaining 915 carry no source field |
| Company vs person | **Company**, generic mailboxes |
| Website requirement | **NOT enforced.** The `website` column is populated on only **1,007 of 2,479 (40.6%)** — i.e. ~59% of this list was sent "I rebuilt your website" with no website recorded |
| Verification | `Verification_Status: "Valid"` and `Email_Status` values like `"Web-found (homepage)"`. Vendor unknown |
| Enrichment / personalization | `icebreaker` (2,479/2,479, AI-written, 1–2 sentences), `subjectLine` (2,479), `companyNickname` (2,479), `Perplexity` (2,479, long AI company research), `Quick_Description` (1,005), `MX_Provider` (2,479 — Google Workspace / Microsoft 365 etc.), `Has_ESG`, `Intent_Signal` (1,530) |
| Leads before / after filtering | **Unknown — not in Smartlead** |
| Segments inside the campaign | None declared. **Cannot be split.** |

🔴 **ICP-drift finding.** The list is labelled "Solar" but the replying companies include: **Walters Wholesale Electric** (an electrical *distributor*, 25+ branches), **EVgo** (a national EV-charging network), **Solar Atmospheres** (a **vacuum heat-treating** company — "solar" in the name only; their reply is signed "Quality Manager - AS9100 CQM" and carries an ITAR export-control notice), **StackRack Battery Systems** (a battery manufacturer, not an installer), **Axia by Qcells**, **Clear Efficiency** (an HVAC/insulation/windows/solar contractor), **Turnkey Energy**. Roughly 5 of the 9 replying companies are not local solar installers. Variant A hard-codes *"I build websites for Solar companies"*, and it was mailed to a heat-treating firm and an EV-charging network. ⚠ **This is a qualitative observation on 9 replies from a 4-day-old campaign, not a measured rate.**

## 4.2 Campaign 3960357 — HVAC USA Recycled

| | |
|---|---|
| Vertical | HVAC contractors, US |
| Sub-vertical | none declared (`vertical` null on all 1,781) |
| Geography | USA. `location` blank on 840 / 1,781 (47%); present values are bare city names (Plano, Riverside, San Jose, Dallas, Anaheim, Sacramento, Fort Worth…) |
| Business size | `Reviews` on 1,081/1,781, `Maps_Rating` on 1,003. `Selection_Tier` on only 156 |
| Job titles | **None** |
| Source | `ICP_Source: "Google Maps"` on 1,087 / 1,781 (61%) |
| Company vs person | **Company**, generic mailboxes |
| Website requirement | **Enforced. `website` populated on 1,781 / 1,781 (100%)** |
| Verification | `Verification_Status` on 1,011; `Verify_Status` on 160; `Email_Status` on all 1,781 |
| Enrichment | `icebreaker` (present on all — but **an empty string on a large share**; both Kool Koncepts and Richmond Heating had `icebreaker: ''`), `subjectLine`, `companyNickname`, `Perplexity` (long-form, all 1,781), `Quick_Description` (all), `MX_Provider` (1,015) |
| Segments inside the campaign | None declared. **Cannot be split.** |
| Leads before / after filtering | **Unknown** |

This list is materially cleaner than 3960583 (100% website coverage, 2.43% bounce vs 5.94%) but produced only 2 human replies in 4 days.

## 4.3 Campaign 3950427 — mixedICP EU — **THE ONLY CAMPAIGN WITH A MACHINE-READABLE SEGMENT SPLIT**

| | |
|---|---|
| Vertical | Four sub-verticals, declared per lead in `custom_fields.vertical` |
| Sub-vertical breakdown | **Roofing companies 897 (45.8%) · Building contractors 616 (31.5%) · Med spas 247 (12.6%) · Home renovators 197 (10.1%)** |
| ⚠ Naming mismatch | The campaign name says "roofers, medspas, home remodelers" — **three**. The data has **four**; "Building contractors" (616 leads, the second-largest segment) is not named in the campaign title |
| Geography | **United Kingdom** (campaign is named "EU"). London 208, Glasgow 115, Birmingham 114, Manchester 108, Leeds 90, Bristol 88, Brent 77, Sheffield 71, Edinburgh 67, Liverpool 65, Leicester 64, Southampton 62, plus Cardiff, Belfast, Hull, Preston, Derby, Nottingham, Stoke |
| Business size | `Rating` and `Reviews` on **all 1,957**. A second field `ICP` carries a human-readable descriptor, e.g. `"krovovi — roofing contractors (UK)"` — the Croatian word for "roofs" survives in the field, indicating the list was built from a Croatian-language brief |
| Job titles | **None** |
| Source | `ICP_Source: "Google Maps"` on **1,957 / 1,957 (100%)**; `Intent_Signal: "Google Maps lead"` on all; `Scraped_At` timestamps cluster on 2026-09-08 |
| Company vs person | **Company**, generic mailboxes |
| Website requirement | **Enforced. `website` on 1,957 / 1,957 (100%)** |
| Verification | `Email_Status: "Web-found (homepage)"` on all. No separate verification-status field on this campaign |
| Enrichment | `Company_Profile` (a long AI-written company summary, all 1,957), `companyNickname`, `vertical`, `ICP`, `Rating`, `Reviews`, `Address`. **No `icebreaker` and no per-lead `subjectLine` on this campaign** — the only personalization in the copy is the `{{vertical}}` token (variants A and B) and `{{companyNickname}}` |
| Leads before / after filtering | **Unknown** |

**Per-segment results** (§9 has the qualitative read). Leads are used as the denominator because per-segment bounce counts are not separable — the `/statistics` rows carry `lead_email`, not `vertical`:

| Sub-vertical | Leads | Replies (all) | Human replies | Positive | Positive % of leads | Demos | Price convos | Meetings |
|---|---|---|---|---|---|---|---|---|
| Roofing companies | 897 | 19 (2.12%) | 10 (1.11%) | 7 | **0.78%** | 8 | 1 | 0 |
| Building contractors | 616 | 13 (2.11%) | 9 (1.46%) | 8 | **1.30%** | 8 | 1 | 0 |
| Med spas | 247 | 5 (2.02%) | 1 (0.40%) | 1 | **0.40%** | 1 | 0 | 0 |
| Home renovators | 197 | 2 (1.02%) | 1 (0.51%) | 0 | **0.00%** | 0 | 0 | 0 |

⚠ Med spas: 4 of its 5 replies were clinic autoresponders. Home renovators: 197 leads, 2 replies, 1 human ("No thanks"). **Both segments are far too small in reply volume for any rate to be meaningful.** The roofing-vs-building-contractor comparison (7/897 vs 8/616) is the only one with enough volume to be worth looking at, and even there the difference is 1 positive reply wide.

## 4.4 Campaign 3912149 — HVAC Europe Eng — **A RECYCLED LIST BUILT FOR A DIFFERENT OFFER**

| | |
|---|---|
| Vertical | HVAC / plumbing & heating / renewables, UK |
| Sub-vertical | none declared |
| Geography | **United Kingdom**, despite "Europe" in the name. `location` blank on 170/1,256; every present value observed was UK (Wigan, Swindon, London, Runcorn, Ipswich, Nottingham, Coventry, Northampton, Plymouth, Glasgow…). 🐞 **The address strings are in mixed languages** — the same field carries `Osoite:` (Finnish), `Adresse:` (German/French), `Adres:` (Dutch), `Adress:` + `Storbritannien` (Swedish), `Мекенжай:` + `Ұлыбритания` (Kazakh) as prefixes to UK addresses. A scraping artefact from a multi-locale Google Maps pull |
| Business size | `Reviews` / `Maps_Rating` on only 74 / 1,256 (6%) |
| Job titles | **None** |
| Source | `ICP_Source` on only 74 / 1,256. **The dominant signal is `campaign_id: "3278845"` + `campaign_name` on all 1,256 — this list is recycled from an earlier campaign** |
| Company vs person | **Company**, generic mailboxes |
| Website requirement | **Enforced. `website` on 1,256 / 1,256 (100%)** |
| Verification | `Verification_Status` AND `verification_status` (duplicated, differently cased) on all 1,256 |
| Enrichment | The richest of the five — **but most of it belongs to a different offer.** All 1,256 leads carry `cta1`, `cta2`, `ctaVideo`, `giftCTA`, `offer1`, `offer2`, `painPoint`, `reframe`, `socialProof`, `socialproof3`, `followup1`, `followup2`, and **their content is the AI-secretary pitch, not the website pitch**. Verbatim from lead 3734012398's blob: `offer1: "I would like to build an AI secretary for Aalberts HFC, completely no charge. It answers calls, chat…"`; `ctaVideo: "Reply 'yes' and I will send a 4-min video demo showing how the secretary takes calls for HVAC and pl…"`; `painPoint: "Quick question: how many jobs do you lose each week because no one was available to answer the custo…"`. **None of these tokens are referenced by the website-offer templates in §3.4** — they are dead weight carried over from campaign 3278845. Live tokens actually used: `companyNickname`, `icebreaker`, `subjectLine` |
| Also present on 74 leads | A full `*_translated` token set (`SubjectLine1_translated`, `Offer1_translated`, `followUp1_translated`…) plus `targetLanguage` — leftovers from a multi-language EU campaign. Unused here |
| Leads before / after filtering | **Unknown** |
| Segments | None declared. **Cannot be split.** |

🔴 **ICP-drift finding — larger than 3960583's.** Companies in this "HVAC" list that replied include: **The National Trust** (a UK heritage *charity*, mailed at `giving@nationaltrust.org.uk`, their **fundraising** inbox — the AI icebreaker discusses a 1612 Roman bath cistern), **Bob Richardson Tools & Fasteners** (a tool merchant, est. 1983), **The Radiator Centre** (a retail showroom chain), **Cosytoes Underfloor Heating** (a B2B manufacturer/wholesaler who told us explicitly *"we do not sell to the general public, relying on both our Cosytoes and 'own brand' dealers to generate sales"*), **H2 Clubs Soho** (a **gym** — icebreaker: *"Love the feel of H2 Clubs Soho… proper London energy for busy people who want a solid session and a nice place to train"*), **UK Energy Management Group**, **Insight Energy Systems**, **Wheeldon Brothers** (a housebuilder). This campaign's 21-of-30 autoresponder rate and its **0 positives on variants A and B** should be read against this list composition.

## 4.5 Campaign 3892258 — HVAC USA

| | |
|---|---|
| Vertical | HVAC contractors, US |
| Sub-vertical | none declared |
| Geography | USA, broad and evenly spread — no single city over 37 leads (Springfield 37, Aurora 32, New York city 29, Bridgeport 26, Peoria 26, Grand Rapids 25, Portland 25, Albuquerque 24, Charleston 24, Tucson 24, Fayetteville 23, Myrtle Beach 22, Port St. Lucie 22, Mesa 21) |
| Business size | `Rating` and `Reviews` on **all 2,409**. Sample values as low as 3 reviews — **no evident review floor in the filter** |
| Job titles | **None** |
| Source | `ICP_Source: "Google Maps"` on **2,409 / 2,409 (100%)**; `Intent_Signal: "Google Maps lead"` on all; `Scraped_At` clusters on 2026-08-05 |
| Company vs person | **Company.** Note 4 of the 33 repliers used a personal Gmail as the business mailbox (`miketbeam2012@gmail.com`, `cosmosaclv@gmail.com`, `margie.proflo@gmail.com`, `jlhheating@gmail.com`) — and **two of those four became the deepest-engaged leads in the campaign** |
| Website requirement | **Enforced. `website` on 2,409 / 2,409 (100%)** |
| Verification | `Verify_Status: "Valid"` on all; **`Selection_Tier: "A - site-confirmed email"` on all 2,409** — the only campaign with a uniform declared selection tier |
| Enrichment | `Company_Profile` (long AI summary, all), `companyNickname`, `Rating`, `Reviews`, `Address`, `Email_Status`. **No `icebreaker` and no per-lead `subjectLine`** — confirmed `icebreaker=None` on every replying lead in this campaign |
| Leads before / after filtering | **Unknown** |
| Segments | None declared. **Cannot be split.** |

Minor ICP drift, much smaller than the other two: **Johnstone Supply** and **Air Equipment Company** are HVAC *wholesalers*, not contractors; **Bill Trombly Plumbing** had been acquired ("now part of Sanford Temperature Control") with its mailbox retired; **Mr. Cool** is a national equipment brand. 4 of 33 repliers. **This is the cleanest list of the five (100% website, 100% selection tier, 1.74% bounce) and it is the only one that produced meetings.**

---

# 5. Reply classification

All 114 replying leads were read by hand and classified against the taxonomy in the brief. **Excluded as automated: 56 leads (49.1% of all replies)** — out-of-office autoresponders, helpdesk/Zendesk ticket acknowledgements, challenge-response spam filters, spam-filter rejection notices, "this mailbox is no longer monitored" notices, and one marketing drip sequence that auto-subscribed us and sent three roofing-advice newsletters.

**58 real human replies remain.**

## 5.1 Summary across all five campaigns

| Class | Count | % of human replies | % of all 114 replies |
|---|---|---|---|
| **POSITIVE** | **36** | **62.1%** | 31.6% |
| NEUTRAL | 4 | 6.9% | 3.5% |
| NEGATIVE | 18 | 31.0% | 15.8% |
| *(automated, excluded)* | *56* | — | *49.1%* |

## 5.2 POSITIVE — 36 replies (62.1% of human replies)

| Subclass | Count | % of positives |
|---|---|---|
| wants to see website / asks for link | **31** | 86.1% |
| interested but asks question | 4 | 11.1% |
| asks for revisions / details | 1 | 2.8% |
| asks price *(as the FIRST reply)* | **0** | 0.0% |
| wants a call *(as the FIRST reply)* | **0** | 0.0% |
| wants to buy / move forward *(as the FIRST reply)* | **0** | 0.0% |

🔴 **The most uniform finding in the dataset: 86% of positive replies are a bare request for the link, and they are extremely short.** Of the 36 positive first replies, **20 are five words or fewer**. **Not one positive first reply asked a price, asked for a call, or expressed purchase intent.** Every price and call conversation in this dataset began only *after* the demo was delivered. This follows directly from the CTA — all step-1 variants ask for exactly one thing ("Reply and I'll send the link" / "give me a quick 'yes'").

Verbatim, all 31 link requests:

- `"Send it"` — Kool Koncepts (3960357) **and** DC Air and Heating (3892258), identically
- `"ok"` — East County Solar Cleaner (3960583)
- `"Worth a look"` — StackRack Battery Systems (3960583)
- `"Hi Andrew / Please send the link"` — Clear Efficiency (3960583)
- `"Sure"` — Genesis Air Mechanical (3960357)
- `"Yes"` — Mid-City Heating (3892258) ← *became the only completed meeting*
- `"Yes."` — Azteca HVAC Pros (3892258); `"Yes."` — Horan Construction (3950427)
- `"Send me the link to judge"` — Diamond Heating (3892258) ← *the furthest-progressed deal*
- `"i would like to see the website"` — HVAC Doctors (3892258)
- `"Hey Andrew , I would like to take a look and see what the site looks like"` — United Heating (3892258)
- `"OK send link, I'll at least look at it"` — Airmark Air Conditioning (3892258)
- `"Send the link. I'll take a look. Thanks."` — Cosmo's Heating & Air (3892258)
- `"Please send it over!"` — Free State Cooling and Heating (3892258)
- `"Hi Mia, Let's see what you come up with."` — PROFLO HVAC (3892258)
- `"Link please"` — Leaking Roof (3950427)
- `"Send me the link to look at the site"` — Stronghold Roofing (3950427)
- `"Go on then , show me your work"` — MTF Roofing (3950427)
- `"Yes send it over thanks"` — Dr Band Clinic (3950427)
- `"okay Mia / let us have a look sweet"` — Omry Building Contractors (3950427)
- `"send the link"` — Sky House Construction (3950427)
- `"Ok send the link let me have a look"` — Elevation Roofing (3950427)
- `"Ok Miac let's take a look and see what youve got"` — Williams Works (3950427)
- `"Ok where is it?"` — J Taylor Build (3950427)
- `"Yes send"` — Perfect Building Contractor (3950427)
- `"I just want to see what you did then we can talk"` — West London Building Group (3950427)
- `"Send it over"` — A1 Bespoke (3950427)
- `"I dont see the website?"` — Golden Oak All Trades (3950427) *(replied to step 3)*
- `"Let's see the website 😉"` — AC Comfort (3912149)
- `"We will have a look please."` — Cosytoes (3912149)
- `"Ok show us the link of redesigned website"` — BDS Services (3912149)

*interested but asks question (4) — **all four are variations of "prove you actually did this":***
- `"Well that is the best cold email I've received in a long time. If you truly rebuilt my website and not created your own from scratch I'd be interested in check it out"` — Climate HVAC Solutions (3892258)
- `"Hi Mia, Not sure how you could possibly have done that please show me."` — London Building Solutions (3950427)
- `"Thank you for your email, but I can't see anything that you've done for my company on website?"` — Unique Roofing (3950427)
- `"Seems odd, But ok send me the link"` — HSB Renewable Energy (3912149)

*asks for revisions / details (1):*
- `"You when looks great, but can you develop something that works with my CRM which is field edge. And do you guys have a partner int the states. I love it. 😂"` — Mid-City Heating (3892258). *(This is his second reply, after "Yes" and the demo.)*

## 5.3 NEUTRAL — 4 replies (6.9% of human replies)

| Subclass | Count | Verbatim | Campaign |
|---|---|---|---|
| forward to another person | 1 | `"We appreciate your interest in our business and are glad to hear about your expertise. For inquiries related to business development, please feel free to reach out directly to our team at businessdev@evgo.com. Please understand that this line is mainly for driver support and charger issues."` — EVgo. **The referral address was never emailed.** | 3960583 |
| already working with someone | 1 | `"Hi Mia / Apologies if I have missed your emails but I am contracted to another company. / Andy"` — Insight Energy Systems | 3912149 |
| asks who we are / why contacted | 1 | `"Got a web site what the problem what makes your any different"` — Franklin Roofing. **A demo was sent in response; he never replied again.** | 3950427 |
| unclear response | 1 | `"Let me deejeffrey yeck"` — Yeck Heating and Cooling. Apparently truncated/garbled. **Never followed up by us.** | 3892258 |
| not now / later | **0** | *No lead asked us to come back later at first reply. Two said it only after seeing the price — see §7G.* | — |

## 5.4 NEGATIVE — 18 replies (31.0% of human replies)

| Subclass | Count | % of negatives |
|---|---|---|
| dislikes unsolicited outreach | **8** | 44.4% |
| not interested (bare) | 4 | 22.2% |
| happy with current site / site doesn't need work | 3 | 16.7% |
| thinks it is spam | 1 | 5.6% |
| distrusts / confused by the offer | 1 | 5.6% |
| unsubscribe | 1 | 5.6% |
| no budget *(as first reply)* | **0** | 0.0% |
| already have internal/agency support *(as first reply)* | **0** | 0.0% |

All 18, verbatim:

*dislikes unsolicited outreach (8):*
- `"FORMAL CEASE AND DESIST NOTICE / CAN-SPAM OPT-OUT DEMAND / NOTICE OF DOCUMENTATION AND POTENTIAL CIVIL LIABILITY … FEDERAL CAN-SPAM VIOLATIONS CAN SUBJECT RESPONSIBLE PARTIES TO CIVIL PENALTIES OF UP TO $53,088 FOR EACH SEPARATE VIOLATING EMAIL. … This notice is directed not only to the business or organization being represented but also to the individual sender…"` — **National Energy Installers** (3960583). *The most severe reply in the dataset: a full legal notice naming individual liability, sent 2 minutes after our email.*
- `"Please stop."` — Trusted Heating & Cooling Solutions (3892258)
- `"stop"` — Doggone Good Heating & Cooling (3892258)
- `"Looking forward for you to f off"` — Reidy Heating & Cooling (3892258)
- `"Remove us from your list."` — New York Heating Corporation (3892258)
- `"No thanks / Stop embarrassing yourself"` — G & N Plumbing (3912149)
- `"Please accept this as an official request to stop emailing this mailbox ."` — H2 Clubs Soho, *a gym* (3912149)
- `"stop plese"` — Sussex Roofer (3950427)

*not interested, bare (4):*
- `"Thank you but we are not interested."` — Comfort Heroes of Texas (3892258)
- `"Thank you not interested"` — Aircon Heating & Cooling (3892258)
- `"No thanks"` — A&J Kitchen Fitters (3950427)
- `"Stop sending email to this address we're not interested"` — JLH Heating and Air (3892258)

*happy with current site / doesn't need work (3):*
- `"not intersted I have good webside"` — Smart Builder London (3950427)
- `"If you did your research you'll see I have a website. Please stop the emails."` — We Heat London (3912149)
- `"I guess you havent seen mine Andrew 😅"` — JJK Gas Services (3912149)

*thinks it is spam (1):*
- `"Please make this your last email. We dont need anymore spam."` — TDI Refrigeration (3892258)

*distrusts / confused by the offer (1):*
- `"I've never asked you to do anything for me mate what are you on about mate"` — Kinnane Roofing & Guttering (3950427)

*unsubscribe (1):*
- `"unsubscribe"` — Greens Heating & Air Conditioning (3892258)

## 5.5 Per-campaign classification

| Campaign | All replies | Automated | Human | Positive | Neutral | Negative | Negatives as % of human |
|---|---|---|---|---|---|---|---|
| 3960583 Solar USA Recycled | 9 | 4 | 5 | 3 | 1 | 1 | 20.0% |
| 3960357 HVAC USA Recycled | 3 | 1 | 2 | 2 | 0 | 0 | 0.0% |
| 3950427 mixedICP EU | 39 | 18 | 21 | 16 | 1 | 4 | 19.0% |
| 3912149 HVAC Europe Eng | 30 | **21 (70%)** | 9 | 4 | 1 | 4 | 44.4% |
| 3892258 HVAC USA | 33 | 12 | 21 | 11 | 1 | **9** | **42.9%** |

---

# 6. Positive reply dataset

**This is the core of the document.** Every positive and potentially-positive thread, chronologically, with the prospect's exact words preserved. Complete message bodies for all 114 threads are in the companion JSON (`all_thread_messages`); this section is the human-readable reconstruction.

**Outcome labels used** (per the brief): `positive reply only` · `requested demo` · `demo sent` · `conversation continued` · `meeting booked` · `price discussion` · `buying intent` · `won` · `lost` · `ghosted after initial interest` · `ghosted after demo` · `ghosted after price`.

⚠ **"Whether they clicked/viewed the demo" is unknowable.** Click tracking is off account-wide and the Vercel demo links carry no tracking Smartlead can see. Where a prospect is recorded as having viewed the demo, it is **because they said so in an email**.

## 6.1 THE LIVE DEALS — 3 threads, all in campaign 3892258 (HVAC USA)

### 6.1.1 Diamond Heating & Cooling Services, Inc — Winston-Salem, NC — **FURTHEST-PROGRESSED DEAL IN THE DATASET**
- **Campaign:** 3892258 · **Lead id:** 4466858791 · **Vertical:** HVAC US
- **Step-1 variant received:** **D** (7510145), subject **`"Diamond's fresh website is live"`**
- **Smartlead category:** Meeting-Booked · **Outcome label: `price discussion` + `buying intent` — LIVE, not closed**

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-02 14:03 | us (step 1, var D) | `I redesigned Diamond's website this week. You didn't ask, I know. I did it anyway. / What I did: Rebuilt the whole thing. Loads instantly on mobile and pc. Dial button that follows users down the page. Your services laid out so someone can find in two seconds instead of scrolling through a wall of text. Your Google reviews pulled in and showing. / What I want: Just to have you take a look. That's it. …` |
| 2 | 2026-09-11 22:03 (**+9 days**) | us (step 2, var B) | `This might sound a bit odd... / but it is not scam. I'm real person and literally did this for Diamond. All I want is if you could take a look and judge it yourself.` |
| 3 | 2026-09-12 15:36 (+17.5h) | **PROSPECT** | **`"Send me the link to judge"`** — Derien Gee, President |
| 4 | 2026-09-13 20:46 (**+29.2h — the slowest demo delivery in the dataset**) | us | demo → `https://diamond-heat-cool.vercel.app` — *"I expanded the redesign using more of Diamond's real content and branding. The 'Ask Diamond AI' assistant is in the bottom-right corner and answers service, coverage and equipment questions. The payment estimator is under 'Estimator' in the main menu and is also interactive directly on the homepage. Each core service and service-area city now has its own search-focused page… This is the first version, so any content or functionality can still be added, changed, or removed based on your feedback."* |
| 5 | 2026-09-14 13:20 (+16.6h) | **PROSPECT** | **`"Thank you for sending the link. I will take a look at the site and get back to you with my thoughts."`** |
| 6 | 2026-09-14 13:46 (+26 min) | us | `Thanks, Derien. If anything on there doesn't feel right or there's something you'd change, just reply here. I built it so everything is easy to tweak.` |
| 7 | 2026-09-14 17:51 (+4h) | **PROSPECT** | **`"I like the flow and easy navigating, the pictures need to be updated, and correction on some features. So what is the cost of website as is and when would be a good time to discuss further and get more info"`** ← *praise + revision request + price question + meeting request, in one sentence* |
| 8 | 2026-09-14 17:58 (**+7 minutes**) | us | **Price withheld, pushed to a call:** `On cost: We have different pricing options so it would be better to go over this on a call. We can go through exactly what you'd like updated and can give you a precise number right then. When are you free this week? Here's our calendar, just pick a slot that works: https://calendly.com/andrew-mindaptive/website-redesign` |
| 9 | 2026-09-16 17:14 (**+47h, no prospect reply in between**) | us | The **$1,600 proposal + $800 Stripe deposit link + onboarding form** (full text §3.8 g1). **No completed call is evidenced anywhere in the thread.** |
| 10 | 2026-09-17 19:42 (+26.5h) | **PROSPECT** | **`"I don't believe I received the breakdown on the different pricing tiers with or without the AI feature. Could you please send over those details?"`** |
| 11 | 2026-09-17 20:22 (+40 min) | us | The 4-tier breakdown: $950/$49 · $1,200/$89 · $1,200/$79 · $1,600/$120 (full text §3.8 g2) |

- **Website generated:** yes (`https://diamond-heat-cool.vercel.app`) · **Meeting:** Smartlead says Meeting-Booked; **no completed call is evidenced in the thread** · **Price discussed:** yes, twice · **Payment:** Stripe link sent, **payment status not knowable from Smartlead**
- 🔍 **DEMO-SITE VISITS (confirmed, not inferred): `visit_count` 2 · `total_requests` 98 · first visit 2026-09-14 12:00 · last visit 2026-09-17 16:00.** He visited the day after the demo landed — which is also when he wrote *"I like the flow and easy navigating"* — and **again on 2026-09-17, the day he asked for the pricing-tier breakdown.** 98 requests across 2 four-hour blocks is the second-highest request count among the live deals.
- **Status at 2026-09-19:** awaiting his response to the tier breakdown, sent 2 days ago. **OPEN.**
- **Diagnostic detail:** the prospect asked for cost at msg 7; the reply withheld the number and asked for a call; the call did not happen; 2 days later a full proposal with a deposit link was sent anyway; the prospect's next message was that he still did not have a price comparison. **The price question took 3 days and 2 emails to be answered in the form asked.**

### 6.1.2 United Heating and Cooling — Raleigh, NC
- **Campaign:** 3892258 · **Lead id:** 4466861837 · **Step-1 variant:** **C** (7510144), subject `"your redesigned website is live"`
- **Outcome label: `price discussion` + `buying intent` — LIVE**
- **Notable: the only lead in the entire dataset who replied to STEP 3, the breakup email.**

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-02 18:23 | us (step 1 var C) | "I built United Heating a fresh website this week…" |
| 2 | 2026-09-08 20:03 | us (step 2 var A) | "I'll keep the site live on the server for another 48hrs. It takes 10 secs to take look." |
| 3 | 2026-09-10 20:43 | us (**step 3, breakup**) | `This is my last email. I'll take the United Heating's redesigned website down in a few hours to free up some space for new projects. / Last chance to take a look. Thanks for your time.` |
| 4 | 2026-09-11 02:14 (+5.5h) | **PROSPECT** | **`"Hey Andrew , I would like to take a look and see what the site looks like"`** — Ed Kamhawy, Project Manager |
| 5 | 2026-09-11 08:19 (+6h) | us | demo → `https://united-heating-cooling.vercel.app` — *"The AI assistant answers service and coverage questions while you're on a job or after hours… The new inquiry flow collects the service needed and urgency, then directs customers into your Jobber booking process. Each service now has its own optimized page, with local coverage and clearer page titles, giving Google better pages to show for searches like AC repair in Cary."* |
| 6 | 2026-09-14 13:47 (+3 days) | us | takedown nudge: *"your new website comes down in about 48 hours. I need some space on the server for other projects…"* |
| 7 | 2026-09-16 13:32 | us | final heads-up: *"This is my final email. I'll be taking the website down this evening to free up the server."* |
| 8 | 2026-09-17 18:52 (**+6 days after the demo**) | **PROSPECT** | **Eight numbered procurement questions, verbatim:** `"1. What platform/framework was the website built with? (Next.js, React, WordPress, Webflow, etc.) 2. Do I receive full ownership of the source code? 3. Can I edit the website myself without paying you for every content change? 4. Can I change pages, text, images, service areas, blog posts, SEO titles and meta descriptions myself? 5. Does the website include an XML sitemap and robots.txt? 6. Does every service and location page have its own unique SEO title, meta description, H1 and content? 7. Are there any monthly hosting, software, licensing or maintenance fees required to keep the website running? 8. Who owns the domain, website code, images, content and hosting account?"` |
| 9 | 2026-09-17 19:26 (+34 min) | us | The $950 Option A / Option B answer (full text §3.8 f) |

- **Meeting booked:** no · **Price discussed:** yes ($950) · **Status:** awaiting reply, 2 days. **OPEN.**
- 🔍 **DEMO-SITE VISITS: `visit_count` 2 · `total_requests` 54 · first visit 2026-09-14 20:00 · last visit 2026-09-15 12:00.** **He did not open the demo until 3 days after it was sent — and the first visit falls on 2026-09-14, the same day we sent him the "your new website comes down in about 48 hours" takedown message.** He then visited again the next day, stayed silent for two more days, and on 2026-09-17 sent the 8 procurement questions. **The visit data shows an actively-evaluating prospect throughout a period the email thread showed as dead silence.**
- ⚠ Note the takedown threat (msgs 6 and 7) fired **while the prospect was silently evaluating**; he came back anyway, 6 days later, with the most commercially serious message in the dataset. **This is direct evidence that "silent for N days" ≠ "gone" in this dataset.**

### 6.1.3 Mid-City Heating, Ventilation & Air Conditioning Inc. — Chicago, IL — **THE ONLY CALL THAT DEMONSTRABLY HAPPENED**
- **Campaign:** 3892258 · **Lead id:** 4466858253 · **Step-1 variant:** **A** (7510142), subject `"my weird hobby"`
- **Outcome label: `meeting booked` (completed) + `buying intent`**

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-02 13:08 | us (step 1 var A) | "Some people gather stamps. I build websites for HVAC companies who have no idea I exist. This week it was Mid-City Heating's turn…" |
| 2 | 2026-09-04 15:25 | us (step 2 A) | 48hrs nudge |
| 3 | 2026-09-08 18:26 | us (step 3) | breakup email |
| 4 | 2026-09-08 19:54 (+1.5h) | **PROSPECT** | **`"Yes"`** |
| 5 | 2026-09-08 21:58 (+2h) | us | demo → `https://mid-city-hvac.vercel.app` — *"An AI assistant answering customer questions anytime, including after hours. Dedicated service pages that give each HVAC service a better chance to rank locally. A guided estimate flow that qualifies leads by service, urgency and property type."* |
| 6 | 2026-09-08 23:09 (**+1.2h**) | **PROSPECT** | **`"You when looks great, but can you develop something that works with my CRM which is field edge. And do you guys have a partner int the states. I love it. 😂"`** ← *feature request + a geography/trust question + unambiguous enthusiasm* |
| 7 | 2026-09-09 13:25 (+14h) | us | `FieldEdge integration is definitely doable. We'd need to get into the specifics on a call, but yes, we can connect the system to your existing setup. / On the partner question, we're based in Croatia and work directly with US businesses. No middle man. It keeps things simple. / Let's jump on a call go through the specifics. You can select a slot here -> https://calendly.com/andrew-mindaptive/30min / Or you can call or message us directly on Whatsapp here -> +385 977669883` |
| 8 | 2026-09-09 13:47 (**+22 minutes**) | **PROSPECT** | **`"HI Mia, / Ive already scheduled a call talk soon."`** |
| 9 | 2026-09-11 16:21 | us | `We're in the call, Russell. Let me know if we should wait for you a while longer…` ← **prospect no-showed the first booking** |
| 10 | 2026-09-11 22:56 | **PROSPECT** | **`"Mia I am so sorry I had an emergency come up and I couldn't get to you guys. I tried to call but the number you placed on the WhatsApp has too many digits. Do you have a different number?"`** |
| 11 | 2026-09-12 00:49 | us | `No worries at all, Russell. Emergencies happen. Sorry about the number confusion. The WhatsApp number is +385 97 766 9883. Sometimes dialing from the US adds an extra digit if the + gets dropped or replaced with 011. I just saw you booked another slot for Monday so you are all set.` |
| 12 | 2026-09-14 13:53 | us | `Hi Russell, just wanted to send a quick reminder for our call today at 12:30 EST. This is the link to join the call --> https://meet.google.com/gjr-yjxq-wps` |
| 13 | 2026-09-14 15:17 | **PROSPECT** | **`"Received Thanks,"`** — Russell Graham, Mid-City Heating |

- **Website generated:** yes · **Meeting:** booked, no-showed once, rebooked, **call scheduled and join link acknowledged for 2026-09-14 12:30 EST** · **Price discussed: NO — no price has ever been quoted to this lead** · **Last email contact 2026-09-14; email-silent 5 days.**
- 🔍 **DEMO-SITE VISITS: `visit_count` 5 · `total_requests` 114 · first visit 2026-09-08 20:00 · last visit 2026-09-19 04:00.** **The highest visit count and highest request count of any lead in the 5-campaign scope.** He visited within 2 hours of receiving the demo, and **his most recent recorded visit is 2026-09-19 — the day this data was pulled, and five days after the call.** The email thread has been silent since 2026-09-14; the visit record has not been. ⚠ This directly contradicts reading his thread as "went quiet", and it is why §7D labels him provisional.
- **Outcome label: `meeting booked`, then silent.** Whether the call happened is not recorded in Smartlead; the thread ends at the join-link acknowledgement and **nothing was sent afterwards.**

## 6.2 PRICE-STAGE THREADS THAT ENDED (4 threads)

### 6.2.1 Cosytoes Underfloor Heating — Leeds, UK — **`lost` (explicit, with the fullest stated reason in the dataset)**
- **Campaign:** 3912149 · **Lead id:** 3734009775 · **Step-1 variant:** **D** (7552006), subject `"Cosytoes's fresh website is live"`

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-07 09:06 | us (var D) | "I redesigned Cosytoes's website this week…" |
| 2 | 2026-09-09 09:27 | us (step 2 B) | "This might sound a bit odd... but it is not scam…" |
| 3 | 2026-09-09 09:57 (+30 min) | **PROSPECT** | **`"Hi Andrew, / We will have a look please. / Kind Regards, Mike Bentley"`** |
| 4 | 2026-09-09 10:26 (+29 min) | us | demo → `https://cosytoes-underfloor-heating.vercel.app` — *"An AI agent guide answering customer questions at any time. (Bottom right corner) / A guided enquiry that qualifies leads by product, floor type and project stage. / Dedicated pages for each heating system, giving Google more useful content to rank."* |
| 5 | 2026-09-09 12:36 (**+2.2h**) | **PROSPECT** | **`"Hi Andrew, / The wonders of AI! How the world is changing. / Seriously, what sort of money are we looking at – and itemise new product inclusions from time to time and pricelist alterations etc. / I need to show some of my colleagues back next week, and we can then take a view."`** |
| 6 | 2026-09-09 13:43 (+1.1h) | us | The forwardable £850 / £1,250 proposal (full text §3.8 e) — explicitly written *"so you can forward this straight to your colleagues"* |
| 7 | 2026-09-15 09:23 (+6 days) | us | bump: `Wanted to make sure you saw this, Mike. Let me know either way.` |
| 8 | 2026-09-15 10:07 (+44 min) | **PROSPECT** | **`"Hi Andrew, I have had a chat with colleagues and we are of the opinion that we should stay where we are. Thank you for your time and effort and I will keep you in mind for the future."`** |
| 9 | 2026-09-15 14:49 | us | `Thanks for being direct, Mike. Would you mind me asking what led to that decision? Any feedback so that I can improve my acquisiton process would be much appreciated.` |
| 10 | 2026-09-15 15:25 (+36 min) | **PROSPECT — the most informative loss reason in the dataset** | **`"Hi Andrew, / There is nothing wrong with your innovative acquisition process! / We have resolved to 'batten down the hatches' until businesses generally see an uplift. / Even though we are currently holding last year's level of business, we are aware that some of our customers are struggling. / We have been here before, and keeping everything tight is the best solution, meaning no new expenditure. / Your prices are much more than our current outgoings. / Our current website is for information only, and we do not sell to the general public, relying on both our Cosytoes and 'own brand' dealers to generate sales. / Should we have need of your services in the future then I will contact you. / Good luck."`** |
| 11 | 2026-09-16 06:55 | us | gracious close, door left open |

- **Three distinct loss reasons, in his own words:** (a) macro caution / budget freeze; (b) **"Your prices are much more than our current outgoings"**; (c) **"Our current website is for information only, and we do not sell to the general public"** — an ICP mismatch: a B2B wholesaler selling through dealers has no lead-generation problem for this offer to solve.
- **Outcome label: `lost`.**
- 🔍 **DEMO-SITE VISITS: `visit_count` 5 · `total_requests` 101 · first visit 2026-09-09 08:00 · last visit 2026-09-17 16:00.** Tied for the highest visit count in scope. He first hit the site *before* replying, consistent with *"We will have a look please."* → demo → a price question 2.2h later. **Critically, the last recorded visit is 2026-09-17 — two days AFTER he formally declined on 2026-09-15** (*"we should stay where we are"*). The 5 blocks span 8 days, matching his stated intent to *"show some of my colleagues back next week"*.

### 6.2.2 AC Comfort Air Conditioning Ltd. — Market Drayton, UK — **`lost` (timing), with the strongest product signal in the dataset**
- **Campaign:** 3912149 · **Lead id:** 3734010683 · **Step-1 variant:** **D** (7552006)

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-07 11:03 | us (var D) | "I redesigned AC Comfort's website this week…" |
| 2 | 2026-09-07 11:12 (**+9 minutes**) | **PROSPECT** | **`"Hi Andrew, / Let's see the website 😉"`** |
| 3 | 2026-09-07 12:45 (+1.5h) | us | demo → `https://ac-comfort.vercel.app` — plus an honest admission: *"I left the Google review feed off because I couldn't verify the correct listing. Send me the Google profile link and I'll add it."* |
| 4 | 2026-09-07 15:07 (+2.4h) | **PROSPECT** | **`"Hi Andrew, / Thanks for sending this over. I've had a look and it does look really impressive, especially the AI assistant and the enquiry flow. / Could you let me know what your pricing would be for something like this, including setup and any ongoing monthly costs?"`** ← *the clearest feature-level praise received* |
| 5 | 2026-09-07 18:26 (+3.3h) | us | $580 + $49/$79 (full text §3.8 b) |
| 6 | 2026-09-09 12:17 (+2 days) | us | bump: "Wanted to make sure you saw this, Mary." |
| 7 | 2026-09-14 16:11 (+5 days) | us | bump 2: "Mary - please give me your thoughts on this." |
| 8 | 2026-09-15 11:55 (**+8 days after the price**) | **PROSPECT** | **`"Hi Andrew, / Apologies for a late reply. Due to the current air conditioning stock issues across the UK, we really don't know how the next few months are going to look for our business. Because of that uncertainty, we're not in a position at the moment to commit to purchasing the website. / We really love the website so I'll get back in touch once the stock situation has settled down and things are a bit more predictable for us. / Thanks for understanding."`** |
| 9 | 2026-09-15 12:02 (+7 min) | us | `Hi Mary, No worries at all. Completely understand and hope it clears up for you soon. Glad you liked the site. Talk when the time's right.` |

- **Loss reason:** sector-specific trading uncertainty (UK air-conditioning stock shortage). **Explicitly not the product, not the price, not trust** — *"We really love the website."*
- **Outcome label: `lost`**, door left open by the prospect.
- 🔍 **DEMO-SITE VISITS: `visit_count` 3 · `total_requests` 146 · first visit 2026-09-07 12:00 · last visit 2026-09-18 08:00.** **146 requests is the highest raw request count of any lead in the 5-campaign scope** — consistent with the detailed, feature-level praise (*"especially the AI assistant and the enquiry flow"*). **The last recorded visit is 2026-09-18, three days after she declined on 2026-09-15**, and 11 days after the demo was sent.

### 6.2.3 Omry Building Contractors — Manchester, UK — **`ghosted after price`**
- **Campaign:** 3950427 · **Lead id:** 4542617566 · **Vertical: Building contractors** · **Step-1 variant:** **D** (7669224)

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-14 12:02 | us (var D) | "I redesigned omry building contractors's website this week…" |
| 2 | 2026-09-14 15:14 (+3.2h) | **PROSPECT** | **`"okay Mia / let us have a look sweet"`** |
| 3 | 2026-09-15 08:12 (**+17h**) | us | demo → `https://omry-building.vercel.app` + *"PS: Sorry for answering the next day. I had a few more inquiries yesterday than usual and the day got away from me."* |
| 4 | 2026-09-15 08:30 (**+18 minutes**) | **PROSPECT** | **`"Hi Mia / I like it 30% because i like the idea and concept. / how much for this?"`** ← *an explicit, unprompted satisfaction score* |
| 5 | 2026-09-15 08:49 (+19 min) | us | Three tiers £850 / £1,250 / £1,450 + Calendly (full text §3.8 d). Opens by addressing the 30%: *"30% is enough to start. What you saw is a first version, not the finished site."* |
| 6 | 2026-09-17 07:38 (+2 days) | us | bump: "Omar - wanted to make sure you saw this, let me know either way." |
| — | — | — | **No further reply. Silent 4 days at 2026-09-19.** |

- 🔍 **DEMO-SITE VISITS: `visit_count` 1 · `total_requests` 21 · first visit 2026-09-15 08:00 · last visit 2026-09-15 08:00.** A single 4-hour block, the same block in which the demo arrived and in which he replied *"I like it 30%... how much for this?"* 18 minutes later. **There is no recorded visit after the price was sent** — though see §D, absence is not proof.

⚠ **4 days of silence only.** That is well inside the observed reply latency elsewhere in this dataset. Label provisional.

### 6.2.4 Elevation Roofing Specialists Ltd — London, UK — **`ghosted after price`**
- **Campaign:** 3950427 · **Lead id:** 4542617094 · **Vertical: Roofing** · **Step-1 variant:** **C** (7669223)

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-14 11:04 | us (var C) | "I built elevation roofing specialists a fresh website this week…" |
| 2 | 2026-09-14 11:33 (+29 min) | **PROSPECT** | **`"Ok send the link let me have a look"`** |
| 3 | 2026-09-14 17:21 (**+5.8h**) | us | demo → `https://elevation-roofing-specialists.vercel.app/` — *"I've added an AI roofing assistant, an interactive roof issue checker and a cost estimator to help turn visitors into inspection enquiries. I also reorganised the services and location content to give the site much stronger local SEO foundations. Sorry for getting back to you so late I had a bit more inquiries than usual."* |
| 4 | 2026-09-16 06:49 (+1.6 days) | us | Nudge 1, **with the `{name}` merge broken**: `"What do you think about your new website? / Did you try the new Ai Agent feature? / I would appreciate your feedback."` |
| 5 | 2026-09-16 07:50 (+1h) | **PROSPECT** | **`"Yh I like it, how much would something like that cost , money is tight for me at the minute it's quiet for me."`** ← *a price question pre-loaded with a budget objection* |
| 6 | 2026-09-16 08:04 (+14 min) | us | £650 + £35/£65 (full text §3.8 c), opening by reframing: *"If now is a quite time for you, that is exactly what a new website with better SEO could help solve."* |
| 7 | 2026-09-17 09:32 (+1 day) | us | bump |
| — | — | — | **No further reply. Silent 3 days at 2026-09-19.** |

- 🔍 **DEMO-SITE VISITS: `visit_count` 3 · `total_requests` 30 · first visit 2026-09-14 16:00 · last visit 2026-09-16 08:00.** He visited in the block the demo was sent, and the **last visit (2026-09-16 08:00) is the same block in which he replied *"Yh I like it, how much would something like that cost"***. No recorded visit after the £650 price landed at 08:04 that day.

⚠ 3 days only. Label provisional.

## 6.3 EXPLICIT DECLINE AFTER SEEING THE WEBSITE (1 thread) — the only negative product feedback in the dataset

### 6.3.1 BDS Services Limited — Birmingham, UK
- **Campaign:** 3912149 · **Lead id:** 3734010172 · **Step-1 variant:** **C** (7552005) · Smartlead category: `Lead Opted Out`

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-07 09:45 | us (var C) | "I built BDS Services a fresh website this week…" |
| 2 | 2026-09-09 10:06 | us (step 2 A) | 48hrs nudge |
| 3 | 2026-09-09 21:45 (+11.7h) | **PROSPECT** | **`"Ok show us the link of redesigned website"`** |
| 4 | 2026-09-10 12:39 (+14.9h) | us | demo → `https://bds-services.vercel.app` — *"Built from your own site, so your prices, reviews and photos are already in it. An AI assistant on every page… A room sizer that turns 'how much for my bedroom?' into a kW size and a price from your own list. SEO optimization - a page for each of the 12 towns you cover… It's a starting point, not a finished site. Two rounds of changes are included before anything goes live."* |
| 5 | 2026-09-10 12:47 (**+8 minutes**) | **PROSPECT — the only explicit product rejection received** | **`"Not as expected, except the first section, everything seems the same as existing one"`** |
| 6 | 2026-09-10 13:31 (+44 min) | us | The rebuttal (full text §3.6 d): explains the words and photos are deliberately theirs, names three specific things to click (the chat bubble, `/systems`, `/service-areas/birmingham`), ends *"If you've tried those and still think it's the same as what you have, say so and I'll leave it there. If not, what would you change first?"* |
| — | — | — | **No further reply.** |

- **Outcome label: `lost` — explicitly declined after seeing the website.** Reason in his own words: the demo **looked like his existing site**.
- 🔍 **DEMO-SITE VISITS: `visit_count` 1 · `total_requests` 33 · first visit 2026-09-10 12:00 · last visit 2026-09-10 12:00.** **One 4-hour block only, and it is the block in which the demo was sent and rejected 8 minutes later. There is no recorded visit after the detailed rebuttal was sent**, which had asked him to click three specific things (the chat bubble, `/systems`, `/service-areas/birmingham`). 33 requests inside a single 8-minute window is consistent with a homepage-only look — i.e. **the visit record supports, but does not prove, that the judgement was made on the homepage alone and that the rebuttal's three links were never opened.**

## 6.4 GHOSTED AFTER DEMO (24 threads) — the largest single group in the dataset

All follow the same shape: short positive → demo within 2–29h → **silence**.

| Prospect | Campaign | Vertical | Var | First reply (verbatim) | Demo sent | **Visits** | **Reqs** | **First → last visit** | Post-demo msgs from us | Days silent at 2026-09-19 |
|---|---|---|---|---|---|---|---|---|---|---|
| East County Solar Cleaner | 3960583 | Solar US | C | `"ok"` | 2026-09-15 | **2** | 24 | 09-16 00:00 → 09-17 16:00 | 1 (nudge 1, merge broken) | 4 |
| StackRack Battery Systems | 3960583 | Battery mfr US | C | `"Worth a look"` | 2026-09-15 | **1** | **124** | 09-15 20:00 → 09-15 20:00 | 1 (bump) | 4 |
| Genesis Air Mechanical | 3960357 | HVAC US | A | `"Sure"` | 2026-09-17 | none rec. ⚠ | 0 | — | 0 | **2 — too new to call a ghost** |
| Kool Koncepts | 3960357 | HVAC US | C | `"Send it"` | 2026-09-15 | none rec. ⚠ | 0 | — | 1 (bump) | 4 |
| Leaking Roof | 3950427 | Roofing UK | A | `"Link please"` | 2026-09-16 | **2** | 81 | 09-16 12:00 → 09-16 16:00 | 0 | 3 |
| Stronghold Roofing | 3950427 | Roofing UK | C | `"Send me the link to look at the site"` | 2026-09-16 | **1** | 26 | 09-16 12:00 → 09-16 12:00 | 0 | 3 |
| Unique Roofing & Building | 3950427 | Roofing UK | B | `"Thank you for your email, but I can't see anything that you've done for my company on website?"` | 2026-09-17 | **2** | 42 | 09-17 04:00 → 09-17 12:00 | 0 | 2 |
| Dr Band Clinic | 3950427 | **Med spa UK** | B | `"Yes send it over thanks"` | 2026-09-15 | none rec. ⚠ | 0 | — | 1 (bump) | 4 |
| Horan Construction | 3950427 | Building contractor UK | A | `"Yes."` | 2026-09-15 | none rec. ⚠ | 0 | — | 1 (nudge 1) | 4 |
| Sky House Construction | 3950427 | Building contractor UK | D | `"send the link"` | 2026-09-15 | none rec. ⚠ | 0 | — | 1 (nudge 1) | 4 |
| J Taylor Build | 3950427 | Building contractor UK | D | `"Ok where is it?"` | 2026-09-14 | none rec. ⚠ | 0 | — | 1 (bump) | 5 |
| Perfect Building Contractor | 3950427 | Building contractor UK | D | `"Yes send"` | 2026-09-14 | **3** | 74 | 09-14 12:00 → 09-15 04:00 | 1 (bump) | 5 |
| London Building Solutions | 3950427 | Building contractor UK | B | `"Hi Mia, Not sure how you could possibly have done that please show me."` | 2026-09-14 | none rec. ⚠ | 0 | — | 1 (bump) | 5 |
| West London Building Group | 3950427 | Building contractor UK | C | `"I just want to see what you did then we can talk"` | 2026-09-14 | **1** | 31 | 09-14 16:00 → 09-14 16:00 | 1 (bump) | 5 |
| A1 Bespoke | 3950427 | Roofing UK | A | `"Send it over"` | 2026-09-15 | none rec. ⚠ | 0 | — | 1 (nudge 1) | 4 |
| Franklin Roofing *(neutral, not positive)* | 3950427 | Roofing UK | A | `"Got a web site what the problem what makes your any different"` | 2026-09-15 | none rec. ⚠ | 0 | — | 1 (bump) | 4 |
| HSB Renewable Energy | 3912149 | Renewables UK | C | `"Seems odd, But ok send me the link"` | 2026-09-09 | **1** | 47 | 09-09 12:00 → 09-09 12:00 | 2 (nudge 1 merge-broken, bump) | **10** |
| Azteca HVAC Pros | 3892258 | HVAC US | A | `"Yes."` | 2026-09-04 | **3** | 37 | 09-04 16:00 → **09-14 12:00** | 3 (nudge 1, takedown, post-takedown) | **15** |
| Airmark Air Conditioning | 3892258 | HVAC US | D | `"OK send link, I'll at least look at it"` | 2026-09-03 | none rec. ⚠ | 0 | — | 4 (nudge 1 merge-broken, takedown ×2, post-takedown) | **16** |
| Cosmo's Heating & Air | 3892258 | HVAC US | B | `"Send the link. I'll take a look. Thanks."` | 2026-09-03 | **3** | 35 | 09-03 12:00 → 09-07 00:00 | 4 (one of them signed **"Best, Mia"** under Andrew's signature — 🐞) | **16** |
| Climate HVAC Solutions | 3892258 | HVAC US | B | `"Well that is the best cold email I've received in a long time. If you truly rebuilt my website and not created your own from scratch I'd be interested in check it out"` | 2026-09-03 | none rec. ⚠ | 0 | — | 4 | **16** |
| Free State Cooling and Heating | 3892258 | HVAC US | B | `"Please send it over!"` | 2026-09-03 | **3** | 44 | 09-03 12:00 → 09-07 16:00 | 4 | **16** |
| DC Air and Heating | 3892258 | HVAC US | C | `"Send it"` | 2026-09-03 | **3** | 58 | **09-02 16:00** → 09-10 00:00 | 4 | **16** |
| PROFLO HVAC | 3892258 | HVAC US | D | `"Hi Mia, Let's see what you come up with."` | 2026-09-03 | **2** | 46 | 09-03 12:00 → 09-09 16:00 | 4 | **16** |

*(24 rows — 23 positives + Franklin Roofing, the neutral who received a demo.)*

**Visit-data read of this table.** ⚠ *"none rec." means no visit row exists for that lead — which may be a genuine non-visit OR a domain-match miss / missing Vercel push. The two cannot be distinguished (§D, §14.5).*

- **13 of these 24 have a recorded visit. They looked, and said nothing.** They form the core of §7B2.
- **11 have no recorded visit.** They form §7B1.
- **Four visited days after the demo landed, i.e. they went back:** Azteca (last visit **2026-09-14, ten days after** the 09-04 demo), DC Air (09-10, a week after), PROFLO (09-09, six days after), Free State (09-07, four days after). **None of them ever replied.**
- 🐞 **DC Air and Heating's first recorded visit (2026-09-02 16:00) PRE-DATES the demo email (2026-09-03).** Either the site was deployed and hit before the email went out, or the 4-hour bucketing/timezone handling shifts the boundary. Recorded as an unexplained anomaly rather than resolved.
- **StackRack's 124 requests in a single 4-hour block is the highest request-per-block figure in scope**, split across two devices (Windows Chrome 81, iPad Chrome 43) — consistent with more than one person at the company looking at the same time.
- 🌍 **Perfect Building Contractor's visitors span two countries** — `PK / Telenor Pakistan / Android Chrome` (30 requests, 09-14 to 09-15) and `GB / Virgin Media / Android Chrome` (21 requests). Recorded without interpretation.

## 6.5 STILL LIVE, NOT YET GHOSTED (4 threads)

| Prospect | Campaign | Vertical | Status and exact words |
|---|---|---|---|
| **Williams Works Limited** | 3950427 | Roofing UK | `"Ok Miac let's take a look and see what youve got"` (2026-09-15) → demo same day → **`"Thanks Mia, Looks good a first view, I will take a look properly over the weekend and get back to early next week.. Have a nice weekend."`** (2026-09-16) → we replied same day offering a Calendly slot. **He said he'd reply "early next week", which is now.** Outcome label: `conversation continued`. **OPEN.**<br>🔍 **Visits: 1 · 33 requests · 09-16 12:00 → 09-16 12:00.** One block — the one in which he wrote "Looks good a first view". **No recorded visit over the weekend he said he would use to look properly** (⚠ absence is not proof, §D). |
| **MTF Roofing & Fascias** | 3950427 | Roofing UK | `"Go on then , show me your work"` (2026-09-16) → demo same day → nudge 1 (2026-09-18) → **`"Ive not seen the link to It?? / Please re-send"`** (2026-09-18) → link re-sent + Calendly the same day. **The prospect lost the link.** Outcome label: `conversation continued`. **OPEN, 1 day old.** |
| **Golden Oak All Trades** | 3950427 | Building contractor UK | Replied to **step 3** with **`"I dont see the website?"`** (2026-09-18) → demo sent 2026-09-18. Outcome label: `demo sent`. **OPEN, 1 day old.**<br>🔍 **Visits: 1 · 20 requests · 09-18 12:00 → 09-18 12:00.** He visited the same day the demo was sent and has not replied since. **He therefore appears in the 14-lead silent-but-visited list (§7B2), but only because he is 1 day old** — he is not a ghost. ⚠ **His `last_visit` (2026-09-18) is one day before this data was pulled (2026-09-19), so this figure is the most likely of all 24 to already be stale by the time anyone reads this.** |
| **HVAC Doctors (formerly Palmetto)** | 3892258 | HVAC US | See §7C — meeting proposed, no-showed twice, last prospect message 2026-09-11. Arguably already a ghost at 8 days. |

## 6.6 THE NEUTRAL THAT WAS NEVER WORKED

**EVgo** (3960583) replied through their support desk: *"We appreciate your interest in our business and are glad to hear about your expertise. For inquiries related to business development, please feel free to reach out directly to our team at businessdev@evgo.com."* **A named, valid referral address was volunteered and no email was ever sent to it.** Outcome: dropped.

---

# 7. Lost-interest / ghosting analysis

Grouped exactly as the brief specifies, with the per-thread diagnostic dimensions it asks for.

## A. Interested → ghosted BEFORE demo
**Count: 0.**
**Every prospect who asked for the link received it.** There is no leak at this stage. (Slowest delivery 29.2h; median 5.9h.)

## B. Demo sent → ghosted
**Count: 23 positives (24 including the one neutral) — §6.4.**
**This is the single largest conversion leak in the dataset: 23 of 36 positive leads, 63.9%; 24 of 37 demos, 64.9%.**

### Where the demos went, before splitting the ghosts

**Demo-building is not evenly distributed across the 5 campaigns.** All 37 demos in scope, by campaign:

| Campaign | Demos built | With a recorded visit | No recorded visit ⚠ | Silent-but-visited (B2) |
|---|---|---|---|---|
| 3950427 mixedICP EU | **17** | 9 | 8 | **6** |
| 3892258 HVAC USA | **11** | 9 | 2 | **5** |
| 3912149 HVAC Europe Eng | 4 | **4 (100%)** | 0 | **1** |
| 3960583 Solar USA Recycled | 3 | 2 | 1 | **2** |
| 3960357 HVAC USA Recycled | 2 | 0 | 2 | 0 |
| **Total (this document's scope)** | **37** | **24 (64.9%)** | **13 (35.1%)** | **14** |
| *(excluded: 3886379 "Website offer - Electric")* | *3* | *1* | *2* | *0* |

⚠ The join file contains 40 demo recipients; **3 belong to campaign 3886379, which is outside this document's scope** and is excluded from every figure above and below.

---

### B1 — Demo sent, ghosted, **NO recorded visit** (11 leads)

⚠ **These 11 cannot be described as "never looked".** A missing row in `site_visits` is produced identically by (a) the prospect genuinely never opening the link, (b) a company-domain match miss in the join, or (c) a missing or failed Vercel push for that project. **The three are indistinguishable in this data** (§D, §14.5). The only thing that can be stated is: **no visit is recorded.**

| Prospect | Campaign | Vertical | Demo sent | Days silent | Post-demo msgs from us | Current thread status |
|---|---|---|---|---|---|---|
| Genesis Air Mechanical | 3960357 | HVAC US | 2026-09-17 | 2 | 0 | Too new to be called a ghost |
| Kool Koncepts | 3960357 | HVAC US | 2026-09-15 | 4 | 1 (bump) | Silent |
| Dr Band Clinic | 3950427 | Med spa UK | 2026-09-15 | 4 | 1 (bump) | Silent. **The only med-spa positive in the dataset** |
| Horan Construction | 3950427 | Building contractor UK | 2026-09-15 | 4 | 1 (nudge 1) | Silent |
| Sky House Construction | 3950427 | Building contractor UK | 2026-09-15 | 4 | 1 (nudge 1) | Silent |
| J Taylor Build | 3950427 | Building contractor UK | 2026-09-14 | 5 | 1 (bump) | Silent |
| London Building Solutions | 3950427 | Building contractor UK | 2026-09-14 | 5 | 1 (bump) | Silent. Had asked *"Not sure how you could possibly have done that please show me."* |
| A1 Bespoke | 3950427 | Roofing UK | 2026-09-15 | 4 | 1 (nudge 1) | Silent |
| Franklin Roofing *(neutral)* | 3950427 | Roofing UK | 2026-09-15 | 4 | 1 (bump) | Silent. Had asked *"what makes your any different"* |
| Airmark Air Conditioning | 3892258 | HVAC US | 2026-09-03 | **16** | 4 (full sequence) | Silent through the complete follow-up sequence |
| Climate HVAC Solutions | 3892258 | HVAC US | 2026-09-03 | **16** | 4 (full sequence) | Silent. **Had sent the most enthusiastic first reply in the dataset** (*"best cold email I've received in a long time"*) and, conditionally, *"If you truly rebuilt my website… I'd be interested in check it out"* |

**Observations, stated without inference:** 9 of the 11 are 2–5 days silent with a single follow-up; only the 2 HVAC-USA leads have run the full 16-day, 4-message course. **Two of the 11 had explicitly asked us to prove the site was real** (London Building Solutions, Climate HVAC Solutions) and no visit is recorded for either after the proof was sent.

---

### B2 — Demo sent, prospect ghosted, but **DID visit the demo site** (14 leads) 🔴

**This is the most important cross-reference in this document.** These 14 prospects received a demo, are recorded as having opened it — several of them repeatedly, and several of them days or weeks after it was sent — **and have not replied since the demo landed.** In the email thread alone, all 14 look identical to a dead lead.

Reminder on the units (§D): **`visits` = distinct 4-hour Vercel blocks in which a human hit the site, NOT page views.** `reqs` = raw request count. Bots, crawlers, hosting/VPN networks and Mindaptive's own traffic are stripped before the data is pushed.

| # | Prospect | Lead email | Campaign | Vertical | Smartlead cat. | Demo sent | **Visits** | **Reqs** | **First visit** | **Last visit** | Gap: demo → last visit | Current thread status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Perfect Building Contractor Ltd | `info@perfectbuilders.uk` | 3950427 | Building contractor UK | Interested | 2026-09-14 | **3** | 74 | 2026-09-14 12:00 | 2026-09-15 04:00 | +1 day | Ghosted 5 days. Last words: *"Yes send"* |
| 2 | Azteca HVAC Pros LLC | `christina.dade@aztecahvacpros.com` | 3892258 | HVAC US | Lead Done | 2026-09-04 | **3** | 37 | 2026-09-04 16:00 | **2026-09-14 12:00** | **+10 days** | Ghosted 15 days, full 3-message follow-up sent. Last words: *"Yes."* |
| 3 | DC Air and Heating | `connect@dcairandheating.com` | 3892258 | HVAC US | Lead Done | 2026-09-03 | **3** | 58 | **2026-09-02 16:00** 🐞 | 2026-09-10 00:00 | +7 days | Ghosted 16 days, full 4-message follow-up sent. Last words: *"Send it"* |
| 4 | Free State Cooling and Heating | `fscoolingandheating@gmail.com` | 3892258 | HVAC US | Interested | 2026-09-03 | **3** | 44 | 2026-09-03 12:00 | 2026-09-07 16:00 | +4 days | Ghosted 16 days, full 4-message follow-up sent. Last words: *"Please send it over!"* |
| 5 | Cosmo's Heating and Air Conditioning | `cosmosaclv@gmail.com` | 3892258 | HVAC US | Interested | 2026-09-03 | **3** | 35 | 2026-09-03 12:00 | 2026-09-07 00:00 | +4 days | Ghosted 16 days, full 4-message follow-up sent. Last words: *"Send the link. I'll take a look. Thanks."* |
| 6 | East County Solar Cleaner | `sid@eastcountysolarcleaner.com` | 3960583 | Solar US | Interested | 2026-09-15 | **2** | 24 | 2026-09-16 00:00 | 2026-09-17 16:00 | +2 days | Ghosted 4 days. Last words: *"ok"* |
| 7 | Unique Roofing And Building Services Ltd | `info@uniqueroofingandbuildingservicesltd.com` | 3950427 | Roofing UK | Interested | 2026-09-17 | **2** | 42 | 2026-09-17 04:00 | 2026-09-17 12:00 | same day | Ghosted 2 days. Had asked *"I can't see anything that you've done for my company on website?"* — **the visit record shows he then went and looked, twice** |
| 8 | Leaking Roof | `info@leaking-roof.com` | 3950427 | Roofing UK | Interested | 2026-09-16 | **2** | 81 | 2026-09-16 12:00 | 2026-09-16 16:00 | same day | Ghosted 3 days. **3 distinct visitor signatures** (Community Fibre ×2 devices, Vodafone) — more than one person looked. Last words: *"Link please"* |
| 9 | PROFLO HVAC, INC. | `margie.proflo@gmail.com` | 3892258 | HVAC US | Interested | 2026-09-03 | **2** | 46 | 2026-09-03 12:00 | 2026-09-09 16:00 | +6 days | Ghosted 16 days, full 4-message follow-up sent. Both visits from iPad Safari on two different ISPs. Last words: *"Let's see what you come up with."* |
| 10 | Stackrack Battery Systems | `sales@stackrackbattery.com` | 3960583 | Battery mfr US | Interested | 2026-09-15 | **1** | **124** | 2026-09-15 20:00 | 2026-09-15 20:00 | same day | Ghosted 4 days. **Highest request count per block in scope**, across 2 devices (Windows Chrome 81, iPad Chrome 43). Last words: *"Worth a look"* |
| 11 | West London Building Group Ltd | `info@westlondonbuildinggroup.co.uk` | 3950427 | Building contractor UK | Interested | 2026-09-14 | **1** | 31 | 2026-09-14 16:00 | 2026-09-14 16:00 | same day | Ghosted 5 days. Last words: *"I just want to see what you did then we can talk"* |
| 12 | Golden Oak All Trades LTD | `enquiries@goldenoakalltrades.co.uk` | 3950427 | Building contractor UK | Interested | 2026-09-18 | **1** | 20 | 2026-09-18 12:00 | **2026-09-18 12:00** ⚠ | same day | **1 day old — not a ghost.** ⚠ **This `last_visit` is one day before the data pull (2026-09-19) and is the figure most likely to already be stale.** Last words: *"I dont see the website?"* |
| 13 | Stronghold Roofing And Home Improvements | `info@stronghold-roofing.uk` | 3950427 | Roofing UK | Interested | 2026-09-16 | **1** | 26 | 2026-09-16 12:00 | 2026-09-16 12:00 | same day | Ghosted 3 days. Last words: *"Send me the link to look at the site"* |
| 14 | HSB Renewable Energy Ltd | `info@hsbrenewables.co.uk` | 3912149 | Renewables UK | Interested | 2026-09-09 | **1** | 47 | 2026-09-09 12:00 | 2026-09-09 12:00 | same day | Ghosted 10 days. **2 devices on the same ISP** (Zen Internet, Windows Firefox 25 + Windows Chrome 22) — two people or two browsers. Last words: *"Seems odd, But ok send me the link"* |

**Composition of the 14:** 6 from 3950427 (mixedICP EU), 5 from 3892258 (HVAC USA), 2 from 3960583 (Solar USA Recycled), 1 from 3912149 (HVAC Europe Eng), 0 from 3960357. By vertical: Building contractors UK 3, Roofing UK 3, HVAC US 5, Solar/battery US 2, Renewables UK 1. **13 of the 14 carry Smartlead category `Interested`; 2 carry `Lead Done`** (Azteca, DC Air — a status set with no closing event in either thread, see §14.6).

**Facts recorded without interpretation:**
- **5 of the 14 visited again more than 3 days after the demo was sent** (Azteca +10 days, DC Air +7, PROFLO +6, Free State +4, Cosmo's +4). Azteca's last recorded visit is **ten days after** the demo and **five days after** our final "your website is no longer available" message.
- **4 of the 14 show more than one distinct visitor signature** (Leaking Roof 3, StackRack 2, HSB 2, PROFLO 2, Perfect Building 2), i.e. the site was opened on more than one device/network.
- **5 of the 14 received the complete 4-message post-demo follow-up sequence** (all from campaign 3892258) and replied to none of it, while the visit record shows them returning to the site during that same window.
- **1 of the 14 (Golden Oak) is 1 day old and is in this bucket only by the mechanical definition**, not because the thread is dead.
- 🐞 DC Air's first recorded visit **pre-dates** its demo email by a day (see §6.4).

**No recommendation is drawn from this section**, per §16. It documents what happened: these prospects opened the site and did not write back.

Measured characteristics across all 24:

| Dimension | Finding |
|---|---|
| Time from positive reply → demo | median **5.9h**, mean 9.4h, max 29.2h. **Speed is not the differentiator** — the ghosted group and the live group have overlapping delivery times, and the single slowest delivery (29.2h) became the best deal |
| CTA used in the demo email | **Not standardised.** Three distinct closes appear: (i) *"Just reply if you like the site and I'll send over the pricing and next steps"*; (ii) *"Let me know what you think"* / *"Tell me what you think"*; (iii) *"If it's not better than what you have, tell me what's missing and I'll leave you alone."* |
| Did we ask them to book a call? | **No — in 22 of 24.** No Calendly link appears in the demo email for any of them. The two exceptions (MTF Roofing, Williams Works) got a Calendly link in a *later* message and are both **still live** |
| Did we give a price? | **No — in 24 of 24.** Not one ghosted-after-demo thread ever received a number |
| Did we ask an open-ended question? | Yes in most, but a **low-specificity** one: *"What do you think about your new website?"* / *"Did you try the new Ai Agent feature?"* |
| Was there a clear next step? | **No.** The demo email's implicit next step is "react to this", which leaves the prospect to define the next move |
| Follow-up volume after the demo | 0–4 messages. In campaign 3892258 the ghosts received the **complete** 4-message post-demo sequence (nudge → takedown → final → post-takedown re-offer) and **none of them replied to any of it**. The mixedICP/Recycled ghosts have received 0–1 and are 2–5 days silent — their sequence has not run yet |
| Days silent | 2 to 16 |
| **Did they open the demo?** | **13 of 24 have a recorded visit (B2); 11 do not (B1).** Before the `site_visits` join this was unanswerable. It is now the single largest correction to the picture the email threads alone give |

**Where the age caveat bites hardest:** the 8 leads from campaign 3892258 have been silent 15–16 days **and received the full follow-up sequence.** Those are real ghosts. The 13 from 3950427 / 3960583 / 3960357 have been silent 2–5 days with 0–1 follow-ups. **Their outcome is genuinely unknown and should not be counted as lost.**

## C. Meeting proposed → ghosted
**Count: 1.**

### HVAC Doctors (formerly Palmetto Heating & Cooling) — Greenville, SC — campaign 3892258, lead 4466858118, variant **D**

| # | When (UTC) | Who | Message |
|---|---|---|---|
| 1 | 2026-09-02 13:04 | us (var D) | "I redesigned HVAC Doctors's website this week…" |
| 2 | 2026-09-04 14:23 | us (step 2 B) | "not scam…" |
| 3 | 2026-09-09 11:23 (**+5 days**) | **PROSPECT** | **`"i would like to see the website"`** |
| 4 | 2026-09-09 12:15 (**+52 min**) | us | demo → `https://hvac-doctors-sc.vercel.app` (full text §3.6 b) |
| 5 | 2026-09-09 12:21 (**+6 minutes**) | **PROSPECT** | **`"i like the site... i would like to discuss pricing options... since we are a small company i am in the field daily, however i can set this kind of appointment usually any day after 4pm. let me know what works."`** ← *praise + explicit price request + explicit availability constraint, all in one message* |
| 6 | 2026-09-09 12:43 (+22 min) | us | **Price NOT given; pushed to a call:** `Glad you liked it. Lets schedule that call and go over specifics and pricing. I have some availability tomorrow after 4pm EST. Feel free to select a slot here -> https://calendly.com/andrew-mindaptive/website-redesign … Alternatively you can send me your phone number and I'll give you a call on Whatsapp.` |
| 7 | 2026-09-10 08:42 | us | **Booking landed at 4:30 AM his time — a timezone failure:** `I am in the call. But I think the booking came through as 4:30 AM your time, probably a time zone mix-up. No problem at all. I sent a new Google Meet invite to your email for today at 4:30 PM EST.` |
| 8 | 2026-09-10 20:36 | us | **Second no-show:** `I'm in the call, Mike. Let me know if I should wait for you a while longer…` |
| 9 | 2026-09-11 13:16 | **PROSPECT** | **`"Sorry for the delay, what time zone are you in"`** |
| 10 | 2026-09-11 13:30 (+14 min) | us | `I'm in Central European Time (CET). So 6 hours ahead. The booking page adjusts automatically, so any slot you pick should show your local time.` |
| 11 | 2026-09-14 13:55 (+3 days) | us | `Hi Mike, should we schedule our video call or would you prefer that I call you on whatsapp? Just tell me what time works for you today/tomorrow (15 mins) and I'll send a google meet invite.` |
| 12 | 2026-09-17 11:00 (+3 days) | us | `Mike - please give me your thoughts on this.` |
| — | — | — | **No reply. Silent 8 days.** Smartlead category: Meeting-Booked. |

**Diagnostics:** he asked for pricing at msg 5 and **never received a number in any form**, across 8 days and 5 subsequent emails from us. He stated his availability constraint in that same message. **Two consecutive bookings then failed on timezone**, one landing at 4:30 AM local. Our response latency was consistently fast (6 min, 22 min, 14 min) — **latency is not the failure mode here.**

🔍 **DEMO-SITE VISITS: `visit_count` 1 · `total_requests` 36 · first visit 2026-09-09 12:00 · last visit 2026-09-09 12:00.** One block — the one in which the demo arrived and he replied *"i like the site... i would like to discuss pricing options"* six minutes later. **There is no recorded visit during the 8 days of meeting attempts and silence that followed** (⚠ absence is not proof, §D). Unlike the B2 group, this lead's visit record does not show continued interest after the thread went quiet.

## D. Meeting completed → ghosted
**Count: 1, and the visit data materially weakens this label.**

**Mid-City Heating** (§6.1.3). Call scheduled for 2026-09-14 12:30 EST; prospect acknowledged the Google Meet link (*"Received Thanks,"*). **The email thread has been silent 5 days, and no message was sent by us either.** No price was ever quoted to him. Whether the call took place is not recorded in Smartlead.

🔴 🔍 **DEMO-SITE VISITS: `visit_count` 5 · `total_requests` 114 · first visit 2026-09-08 20:00 · last visit 2026-09-19 04:00.** **The highest visit count and the highest request total of any lead in scope — and the most recent visit is 2026-09-19, the day this data was pulled and five days after the call.** He has returned to the demo site across **five separate 4-hour blocks spanning 11 days**, including after the email thread went quiet.

**Consequence for this category:** on email evidence alone Mid-City reads as "meeting happened, then ghosted". **On the visit evidence he is the most persistently engaged prospect in the dataset.** The label `ghosted` is retained here only because it describes the *email* thread; it is flagged as contradicted by the visit record rather than silently kept.

## E. Price sent → ghosted
**Count: 3.**

| Prospect | Campaign | Price sent | Amount | Days silent | Their question → our answer | Asked them to book a call? | Open-ended question? | Clear next step? | 🔍 **Demo visits (last visit)** |
|---|---|---|---|---|---|---|---|---|---|
| Clear Efficiency | 3960583 | 2026-09-15 | $850 + $49/$79 | **4** | 40 min | **Yes** (Calendly) | "Let me know your thoughts" | Partly — pay on launch, but no date proposed | **none recorded** ⚠ — the only price-stage lead with no visit row at all, despite having asked for the link and then asked the price |
| Omry Building | 3950427 | 2026-09-15 | £850 / £1,250 / £1,450 | **4** | 19 min | **Yes** (Calendly) | No | Yes — *"we usually jump on a call… 4-5 days after that your new website is live"* | 1 visit · 21 reqs · last 2026-09-15 08:00 — **no recorded visit after the price landed** |
| Elevation Roofing | 3950427 | 2026-09-16 | £650 + £35/£65 | **3** | 14 min | **No** | "Let me know what you think" | Partly | 3 visits · 30 reqs · last 2026-09-16 08:00 — the block in which he asked the price; **none after** |

⚠ **All three have been silent 3–4 days and none has received more than one bump. Calling these "ghosted after price" is premature.** It is recorded because the brief asks for the split, but 3–4 days sits inside the normal reply latency observed elsewhere here (Cosytoes took 6 days to decline; **United Heating took 6 days to return with 8 buying questions**).

Additional detail for the analysing agent: **Clear Efficiency received an off-stage nudge.** On 2026-09-18 the generic post-demo message *"What do you think about your new website,?"* (with the broken merge) was sent to a lead who had already received a full price three days earlier — i.e. the post-demo nudge sequence fired on a prospect who was past that stage.

## F. Explicitly declined AFTER seeing the website
**Count: 1.** BDS Services (§6.3.1) — *"Not as expected, except the first section, everything seems the same as existing one"*, sent **8 minutes** after the link arrived.
🔍 **1 visit · 33 reqs · 09-10 12:00 → 09-10 12:00.** A single block, and **no recorded visit after the rebuttal that asked him to click three specific pages.** This is the one decline in the dataset whose visit record shows no return.

## G. Explicitly declined AFTER seeing the price
**Count: 2.**

| Prospect | Price given | Exact decline | Stated reason | Door left open? | 🔍 **Demo visits** |
|---|---|---|---|---|---|
| Cosytoes | £850 / £1,250 (2026-09-09) | *"we are of the opinion that we should stay where we are… We have resolved to 'batten down the hatches'… no new expenditure. Your prices are much more than our current outgoings. Our current website is for information only, and we do not sell to the general public"* | Budget freeze + price high relative to current spend + **no lead-gen need (B2B wholesaler selling via dealers)** | Yes — *"Should we have need of your services in the future then I will contact you"* | **5 visits · 101 reqs · 09-09 08:00 → 2026-09-17 16:00.** ⚠ **Last visit is 2 days AFTER he declined** |
| AC Comfort | $580 + $49/$79 (2026-09-07) | *"Due to the current air conditioning stock issues across the UK… we're not in a position at the moment to commit to purchasing the website. We really love the website so I'll get back in touch once the stock situation has settled down"* | Sector trading uncertainty. **Explicitly NOT the product and NOT the price** | Yes — prospect volunteered to re-contact | **3 visits · 146 reqs (highest in scope) · 09-07 12:00 → 2026-09-18 08:00.** ⚠ **Last visit is 3 days AFTER she declined** |

## H. Timing summary across the whole ghosting analysis

| Transition | n | Median | Mean | Notes |
|---|---|---|---|---|
| Our send → prospect's first reply | 58 | **0.4h** | 4.5h | **39 of 58 replied within 1 hour; 56 of 58 within 24h** |
| Positive reply → our demo delivery | 36 | **5.9h** | 9.4h | max 29.2h |
| Prospect's price question → our price email | 7 | **22 min** | ~40 min | max 1.1h |

### H2. What the visit data adds to the timing picture

**Two prospects kept opening the demo site after formally declining** (Cosytoes +2 days, AC Comfort +3 days) and **one kept opening it after the call and 5 days of email silence** (Mid-City, last visit on the day of the data pull). **Four ghosted leads returned to the site 4–10 days after the demo was sent** (Azteca +10, DC Air +7, PROFLO +6, Free State +4). Recorded as observations; no action is inferred (§16).

**Conversely, of the 7 price conversations, none has a recorded visit after the price email was sent.**

**Slowest demo deliveries (all to positive leads):** Diamond Heating 29.2h, DC Air 22.9h, Dr Band Clinic 22.2h, PROFLO 22.1h, Free State 21.5h, Climate HVAC 20.2h, Sky House 19.9h, A1 Bespoke 19.0h. **The slowest of all — Diamond Heating at 29.2 hours — is the furthest-progressed deal in the dataset**, so slow delivery did not kill it. Seven of the slow deliveries carry an explicit apology in the demo email (*"Sorry for answering the next day. I was locked in on a project yesterday and the day got away from me."*).

---

# 8. Objections and buying signals

Extracted by hand from the 58 human replies. **Nothing is inferred** — a theme is counted only where the prospect used words to that effect.

## 8.1 BUYING SIGNALS

| Signal | Count | Exact example quotes | Verticals | Final outcomes |
|---|---|---|---|---|
| **"send it" / "send the link"** (bare demo request) | **31** | `"Send it"` · `"send the link"` · `"Link please"` · `"Send it over"` · `"Yes send"` · `"Ok where is it?"` · `"Send me the link to judge"` · `"ok"` · `"Sure"` · `"Yes"` | HVAC US ×9, Roofing UK ×7, Building contractors UK ×7, Solar US ×3, HVAC UK ×3, Med spa UK ×1, battery mfr US ×1 | 23 ghosted after demo · 4 live · 4 reached a price conversation |
| **"worth a look" / hedged interest** | 3 | `"Worth a look"` (StackRack) · `"OK send link, I'll at least look at it"` (Airmark) · `"Ok Miac let's take a look and see what youve got"` (Williams Works) | Battery mfr US, HVAC US, Roofing UK | 2 ghosted after demo, 1 live |
| **"how much?" / "what would this cost?"** | **7** | `"how much do you charge for the services you provide?"` (Clear Efficiency) · `"how much for this?"` (Omry) · `"how much would something like that cost , money is tight for me at the minute it's quiet for me"` (Elevation) · `"Seriously, what sort of money are we looking at"` (Cosytoes) · `"Could you let me know what your pricing would be for something like this, including setup and any ongoing monthly costs?"` (AC Comfort) · `"So what is the cost of website as is"` (Diamond) · `"i would like to discuss pricing options"` (HVAC Doctors) | HVAC US ×3, Roofing UK ×1, Building contractor UK ×1, Underfloor heating UK ×1, HVAC UK ×1 | 2 live · 2 explicit losses · 2 ghosted after price · **1 never received a price at all** |
| **explicit praise of the demo** | **7** | `"You when looks great… I love it. 😂"` (Mid-City) · `"i like the site..."` (HVAC Doctors) · `"it does look really impressive, especially the AI assistant and the enquiry flow"` (AC Comfort) · `"I like the flow and easy navigating"` (Diamond) · `"Yh I like it"` (Elevation) · `"Looks good a first view"` (Williams Works) · `"I like it 30% because i like the idea and concept"` (Omry) | HVAC US ×3, HVAC UK ×1, Roofing UK ×2, Building contractor UK ×1 | **Every single one of these 7 progressed to a price question or a meeting.** 3 live · 2 lost · 2 ghosted-after-price. **This is the strongest predictive signal in the dataset.** |
| **"let's talk" / wants a call** | 2 | `"i can set this kind of appointment usually any day after 4pm. let me know what works."` (HVAC Doctors) · `"when would be a good time to discuss further and get more info"` (Diamond) | HVAC US ×2 | 1 no-showed twice then ghosted; 1 live |
| **"can you change X?"** (feature request) | 3 | `"can you develop something that works with my CRM which is field edge"` (Mid-City) · `"the pictures need to be updated, and correction on some features"` (Diamond) · `"itemise new product inclusions from time to time and pricelist alterations etc."` (Cosytoes) | HVAC US ×2, underfloor heating UK ×1 | 1 meeting held · 1 live deal · 1 lost |
| **praise of the cold email itself** | 1 | `"Well that is the best cold email I've received in a long time."` (Climate HVAC Solutions) | HVAC US | **Ghosted after demo** |
| **ownership / procurement questions** | 1 | Ed Kamhawy's 8 numbered questions (§6.1.2) | HVAC US | Live |
| **"we've been meaning to update the site"** | **0** | — | — | **No prospect in this dataset volunteered a pre-existing intent to redesign.** |

## 8.2 OBJECTIONS

| Objection | Count | Exact example quotes | Verticals | Overcome? |
|---|---|---|---|---|
| **Disbelief that we really built something for them** | **5** | `"If you truly rebuilt my website and not created your own from scratch I'd be interested in check it out"` (Climate HVAC) · `"Not sure how you could possibly have done that please show me."` (London Building Solutions) · `"I can't see anything that you've done for my company on website?"` (Unique Roofing) · `"Seems odd, But ok send me the link"` (HSB Renewables) · `"I've never asked you to do anything for me mate what are you on about mate"` (Kinnane Roofing) | HVAC US, Building contractor UK, Roofing UK ×2, Renewables UK | **Partly.** 4 of 5 accepted a demo, so the objection did not block the demo. **0 of 5 progressed past the demo.** Kinnane never accepted it |
| **Dislikes unsolicited outreach** | **8** | see §5.4 — from `"Please stop."` to a full CAN-SPAM cease-and-desist naming individual liability | HVAC US ×5, HVAC UK ×2, Roofing UK ×1 | **0 of 8.** Never engaged |
| **Current site is fine / no need** | 4 | `"not intersted I have good webside"` (Smart Builder London) · `"If you did your research you'll see I have a website. Please stop the emails."` (We Heat London) · `"I guess you havent seen mine Andrew 😅"` (JJK Gas) · `"Got a web site what the problem what makes your any different"` (Franklin Roofing) | Building contractor UK, HVAC UK ×2, Roofing UK | **1 of 4.** Only Franklin accepted a demo — then ghosted. The other 3 ended the conversation |
| **Budget / no new expenditure** | **2** | `"We have resolved to 'batten down the hatches'… no new expenditure. Your prices are much more than our current outgoings."` (Cosytoes) · `"money is tight for me at the minute it's quiet for me"` (Elevation Roofing) | Underfloor heating UK, Roofing UK | **0 of 2.** Cosytoes declined; Elevation went silent. A reframe *was* attempted with Elevation (*"If now is a quite time for you, that is exactly what a new website with better SEO could help solve"*) and drew no reply |
| **Bad timing / market uncertainty** | 2 | `"Due to the current air conditioning stock issues across the UK, we really don't know how the next few months are going to look"` (AC Comfort) · `"until businesses generally see an uplift"` (Cosytoes) | HVAC UK, underfloor heating UK | **0 of 2**, but both prospects left the door open themselves |
| **Thinks it is spam** | 1 | `"Please make this your last email. We dont need anymore spam."` (TDI Refrigeration) | HVAC US | No |
| **The demo isn't different enough from what they have** | 1 | `"Not as expected, except the first section, everything seems the same as existing one"` (BDS Services) | HVAC UK | **No.** A specific, detailed rebuttal was sent (§3.6 d) and drew no reply |
| **Ownership / lock-in / hidden fees** | **1 — but the most detailed objection received** | `"Do I receive full ownership of the source code?"` · `"Can I edit the website myself without paying you for every content change?"` · `"Are there any monthly hosting, software, licensing or maintenance fees required to keep the website running?"` · `"Who owns the domain, website code, images, content and hosting account?"` (Ed Kamhawy, United Heating) | HVAC US | **Unresolved — answered 2026-09-17, awaiting reply.** The answer created a $0/month "you own it outright" option that appears in no other pricing email in this dataset |
| **Already working with someone / contracted elsewhere** | 1 | `"I am contracted to another company."` (Insight Energy) | Renewables UK | No |
| **Worries about domain / hosting ownership** | 1 (within Ed Kamhawy's list) | `"Who owns the domain… and hosting account?"` | HVAC US | Answered, unresolved |
| **Wants proof / portfolio / case studies** | **0** | — | — | **Not one prospect asked for a portfolio, case studies, references or past work.** The free demo appears to substitute for this entirely |
| **Dislikes AI** | **0** | — | — | **Not one negative mention of AI in 58 human replies.** The two explicit mentions are both positive (§10) |
| **Wants SEO proof / rankings evidence** | **0** | — | — | Ed Kamhawy asked *technical implementation* questions about SEO (sitemap, robots.txt, per-page meta, unique H1s) but nobody asked for ranking proof |
| **Prefers phone** | **0** | — | — | Two prospects used or offered phone/WhatsApp as an alternative channel; neither objected to email |
| **Too busy** | **0 in human replies** | — | — | But **heavily present in autoresponders**: 21 of 30 replies in 3912149 and 18 of 39 in 3950427 were OOO or "we're experiencing an exceptionally high volume of calls and emails" messages, several citing annual leave running to late September |
| **Redesign is unnecessary** | 0 distinct from "current site is fine" | — | — | — |

---

# 9. Vertical analysis

Verticals are reported **separately and never merged**. Where a vertical appears in more than one campaign it is shown per campaign as well as pooled, because list quality, geography and campaign age differ.

## 9.1 Quantitative

| Vertical | Campaign(s) | Leads | Emailed | Delivered | Replies (all) | Reply rate | Human replies | Positive | Positive rate (of delivered) | Demos | **Visited demo site** | **Silent-but-visited** | Buying intent | Meetings | Sales |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **HVAC — USA** | 3892258 | 2,409 | 2,409 | 2,367 | 33 | 1.39% | 21 | 11 | **0.46%** | 11 | **9 of 11 (81.8%)** | **5** | 4 | **3** | 0 |
| **HVAC — USA (recycled list)** | 3960357 | 1,781 | 1,561 | 1,523 | 3 | 0.20% | 2 | 2 | 0.13% | 2 | **0 of 2** ⚠ | 0 | 0 | 0 | 0 |
| **HVAC / plumbing — UK** | 3912149 | 1,256 | 1,256 | 1,181 | 30 | 2.54% | 9 | 4 | 0.34% | 4 | **4 of 4 (100%)** | **1** | 2 | 0 | 0 |
| **Solar / renewables — USA (recycled)** | 3960583 | 2,479 | 1,600 | 1,505 | 9 | 0.60% | 5 | 3 | 0.20% | 3 | **2 of 3** | **2** | 1 | 0 | 0 |
| **Roofing — UK** | 3950427 | 897 | 897 | *n/a* | 19 | 2.12% | 10 | 7 | **0.78%** (of leads) | 8 | **5 of 8** | **3** | 0 | 0 | 0 |
| **Building contractors — UK** | 3950427 | 616 | 616 | *n/a* | 13 | 2.11% | 9 | 8 | **1.30%** (of leads) | 8 | **4 of 8** | **3** | 1 | 0 | 0 |
| **Med spas — UK** | 3950427 | 247 | 247 | *n/a* | 5 | 2.02% | 1 | 1 | 0.40% (of leads) | 1 | **0 of 1** ⚠ | 0 | 0 | 0 | 0 |
| **Home renovators — UK** | 3950427 | 197 | 197 | *n/a* | 2 | 1.02% | 1 | 0 | **0.00%** (of leads) | 0 | — *(no demo built)* | 0 | 0 | 0 | 0 |

*n/a — per-sub-vertical delivered counts are not separable because the `/statistics` rows carry `lead_email`, not `vertical`. The campaign-level bounce rate was 6.64%; applying it uniformly would shift the sub-vertical positive rates up by roughly 7% relative, which does not change their ordering.*

**On the two new columns:** *visited demo site* counts demo recipients with at least one recorded human visit (a "visit" = one 4-hour Vercel request block, not a page view — §D). ⚠ **A "0 of N" cell is not evidence that nobody looked**; a domain-match miss or a missing Vercel push is indistinguishable from a genuine non-visit. This matters most for **Med spas (0 of 1)** and **HVAC USA Recycled (0 of 2)**, where N is so small that a single join failure would produce exactly that cell.

**What the visit column adds that the reply column cannot:** **24 of 37 demo recipients (64.9%) opened the site.** The two UK trades segments and HVAC USA are the only ones with enough demos for the figure to carry meaning, and they sit at 62.5%, 50.0% and 81.8% respectively. **HVAC Europe Eng is 4 of 4**, but on 4 demos.

**Rankings, with the sample size that supports each:**

| Ranked on positive rate | Vertical | Positives | Denominator | Is this reliable? |
|---|---|---|---|---|
| 1 | Building contractors UK | 8 | 616 | ⚠ Borderline. 8 positives is the smallest number that can carry a rate at all |
| 2 | Roofing UK | 7 | 897 | ⚠ Borderline |
| 3 | HVAC USA | 11 | 2,367 | ⚠ The largest positive count in the dataset, and **the only vertical with any meetings** |
| 4 | Med spas UK | 1 | 247 | ❌ **No.** 1 positive |
| 5 | HVAC UK | 4 | 1,181 | ❌ Weak |
| 6 | Solar USA | 3 | 1,505 | ❌ Weak, and the campaign is 4 days old with 35% unsent |
| 7 | HVAC USA recycled | 2 | 1,523 | ❌ **No.** 4 days old |
| 8 | Home renovators UK | 0 | 197 | ❌ **No.** Zero positives from 197 leads is consistent with anything from "bad fit" to "normal variance" |

**The honest summary: no vertical comparison in this dataset clears statistical significance.** The only differences with any weight behind them are (a) UK trades (roofing + building contractors, 15 positives from 1,513 leads ≈ 0.99%) versus US HVAC (11 from 2,367 ≈ 0.46%), and (b) the fact that **all three meetings came from one campaign, US HVAC**, which is also the oldest by 6+ days — an age confound that cannot be removed.

## 9.2 Qualitative response patterns, per vertical

### HVAC — USA (3892258 + 3960357)
- **What they cared about:** integration with the tools they already run. Two of the three most-engaged leads asked about a specific CRM/FSM by name — **FieldEdge** (Mid-City) and **WEX Field Service Management** (Diamond). One asked about **Jobber** indirectly via our own demo copy. **Ownership and lock-in** dominated the single most detailed reply received (United Heating's 8 questions: source code, self-editing, monthly fees, domain ownership).
- **What they reacted to:** the AI assistant (positively, twice), the per-service and per-city SEO pages, the qualifying estimate form. Diamond specifically named *"the flow and easy navigating"* and the *"payment estimator"*.
- **Objections:** **by far the most hostile vertical** — 9 of 21 human replies were negative (42.9%), including a legal cease-and-desist, "Please stop.", "stop", "Looking forward for you to f off", "Remove us from your list.", "We dont need anymore spam."
- **Email vs call:** **the only vertical that engaged with calls at all.** 3 of 3 dataset meetings. But 2 of 3 involved a no-show, and one booking landed at **4:30 AM local time**.
- 🔍 **Demo engagement: 9 of 11 demo recipients opened the site (81.8%, the highest of any vertical with more than 4 demos), and 5 of those never replied.** This vertical also contains the **longest post-demo return gaps** in the dataset — Azteca returned 10 days after the demo and 5 days after our final "the website is no longer available" email. **Mid-City's last visit is the day this data was pulled**, 5 days after his call and 5 days into email silence.
- **Price timing:** asked **after** the demo in every case, never before. Two prospects asked for pricing and one of those (HVAC Doctors) **never received a number**.
- **AI assistant reaction:** positive where mentioned; zero negative mentions.
- **Design / SEO / intake / quote flow:** SEO was the most-discussed technical topic (Ed Kamhawy's questions 5 and 6 are entirely about it). Design was praised once ("the flow and easy navigating"); photos were criticised once ("the pictures need to be updated").

### HVAC / plumbing — UK (3912149)
- **What they cared about:** **price relative to current spend.** Cosytoes stated it outright: *"Your prices are much more than our current outgoings."* Also **ongoing change management** — Cosytoes asked specifically to *"itemise new product inclusions from time to time and pricelist alterations etc."*, i.e. what maintenance covers, before caring about the build fee.
- **What they reacted to:** the AI assistant (*"The wonders of AI! How the world is changing"*, *"especially the AI assistant and the enquiry flow"*). **Both explicit AI mentions in the entire dataset come from this vertical, and both are positive.**
- **Objections:** the campaign's dominant characteristic is **absence, not objection** — 21 of 30 replies were machines, many citing annual leave into late September. Where humans did object: "I have a website", budget freeze, market uncertainty, and one product rejection (BDS: "everything seems the same as existing one").
- **Email vs call:** **entirely async. Zero calls, zero calendar bookings, and no Calendly link appears in any of this campaign's threads.** All four positive threads were conducted end-to-end over email, including both full price negotiations.
- 🔍 **Demo engagement: 4 of 4 (100%) — the only vertical where every demo recipient has a recorded visit.** It also has the **two highest request totals in the dataset relative to visits**: AC Comfort 146 requests over 3 blocks and Cosytoes 101 over 5. **Both of them kept opening the site after they had declined** (+3 days and +2 days respectively).
- **Price early?** No — after the demo, in both cases.
- **Design / SEO / intake:** the AI assistant and the enquiry flow were named; design was not commented on except negatively by BDS.

### Solar / renewables — USA (3960583)
- **What they cared about:** cannot be characterised — **3 positive replies, all of which were one or two words** (`"ok"`, `"Worth a look"`, `"Please send the link"`). Only one progressed to a price question, and its content was a bare *"how much do you charge for the services you provide?"*
- **Objections:** 1 negative, but it was the most severe in the dataset (CAN-SPAM cease-and-desist with individual-liability language).
- **Note:** the more interesting signal here is not response behaviour but **list composition** — §4.1's ICP drift.
- **Everything else:** unmeasurable at n=3.

### Roofing — UK (3950427)
- **What they cared about:** **proof it is real.** Two of the seven positives led with disbelief (`"I can't see anything that you've done for my company on website?"`, and Kinnane's outright `"I've never asked you to do anything for me mate"`). A third, Franklin, challenged the premise: `"Got a web site what the problem what makes your any different"`.
- **What they reacted to:** the demo copy for this vertical consistently offered a **roof issue checker / cost estimator** plus per-town SEO pages. Only one roofing prospect commented on any of it: Elevation's `"Yh I like it"` and Williams Works' `"Looks good a first view"`.
- **Objections:** budget (`"money is tight for me at the minute it's quiet for me"` — Elevation) and one hostile stop request.
- **Email vs call:** async. **The two roofing threads that received a Calendly link are the two that are still alive** (MTF, Williams Works).
- **Price early?** No. One price conversation, opened by the prospect after the demo, and it arrived already carrying a budget objection.
- **A notable operational failure:** MTF Roofing replied `"Ive not seen the link to It?? Please re-send"` **two days after the demo was sent** — i.e. the demo email did not reach or was not found by an engaged prospect. 🔍 **MTF has no visit row at all, which independently corroborates his statement** — the one case in the dataset where a "no recorded visit" reading is confirmed by the prospect's own words.
- 🔍 **Demo engagement: 5 of 8 roofing demo recipients opened the site; 3 of those never replied.** Leaking Roof shows **3 distinct visitor signatures** (two ISPs, three devices) inside a single day and still never wrote back.

### Building contractors — UK (3950427)
- **Highest positive rate of any segment (8/616 = 1.30%)** and the **least hostile** (1 negative from 9 human replies).
- **What they cared about:** same proof instinct as roofers (`"Not sure how you could possibly have done that please show me."`), plus one prospect who framed his interest as a **percentage**: `"I like it 30% because i like the idea and concept."` — i.e. explicitly evaluating the concept separately from the execution.
- **What they reacted to:** the demo copy for this segment emphasised a **project planner with early cost guidance / budget range** and per-area SEO pages — a different value prop from the HVAC "answer the phone at 11pm" angle. No prospect commented on it specifically.
- **Objections:** 1 ("not intersted I have good webside").
- **Email vs call:** async. One Calendly link sent (Omry, with the price); no bookings.
- **Price early?** No — Omry asked 18 minutes after receiving the demo.
- 🔍 **Demo engagement: 4 of 8 building-contractor demo recipients opened the site; 3 of those never replied** (Perfect Building, West London, Golden Oak). **Perfect Building Contractor's visits split across Pakistan and GB networks.** The 4 with no recorded visit (Horan, Sky House, J Taylor, London Building Solutions) are all 4–5 days silent with one follow-up — ⚠ absence is not proof.
- **⚠ This segment is not named in the campaign title** (§4.3), so its strong relative showing was arguably unplanned.

### Med spas — UK (3950427)
- **247 leads → 5 replies → 4 of them clinic autoresponders → 1 human positive (`"Yes send it over thanks"`) → demo sent → silence.**
- **Nothing can be said about what this vertical cares about.** The one observable pattern is structural: **every med-spa autoresponder was a patient-facing appointment/booking message** ("Due to the high number of calls and emails we receive it can take up to 7 working days for us to respond… If you would like to book an appointment, please use the following links… PLEASE NOTE: We are unable to reserve appointments via email as a deposit is required"). The `info@` mailboxes for aesthetic clinics are **patient-booking inboxes**, not business inboxes.
- 🔍 **Demo engagement: the single med-spa demo (Dr Band Clinic) has no recorded visit.** ⚠ On N=1 this is uninformative — a single domain-match miss produces exactly this result.
- **Excitement about AI / design / SEO / intake:** no data.

### Home renovators — UK (3950427)
- **197 leads → 2 replies → 1 human (`"No thanks"`) → 0 positives, 0 demos.**
- **Nothing measurable.** Do not conclude the vertical is bad; conclude there is no data.

---

# 10. Feature / value-proposition reaction

**Counted only where a prospect used words about it.** Where a value proposition appears in our copy but no prospect ever mentioned it, that is recorded as **0 mentions** rather than left blank — which is itself a finding, because most of the offer's feature list was never once referenced back by a prospect.

| Value proposition | Positive mentions | Negative / concern mentions | Exact examples | Which vertical reacted |
|---|---|---|---|---|
| **Redesigned / modern website (overall)** | **6** | **1** | ✅ `"You when looks great… I love it. 😂"` (Mid-City, HVAC US) · `"i like the site..."` (HVAC Doctors, HVAC US) · `"it does look really impressive"` (AC Comfort, HVAC UK) · `"I like the flow and easy navigating"` (Diamond, HVAC US) · `"Yh I like it"` (Elevation, Roofing UK) · `"Looks good a first view"` (Williams Works, Roofing UK) · `"I like it 30% because i like the idea and concept"` (Omry, Building contractor UK) ❌ `"Not as expected, except the first section, everything seems the same as existing one"` (BDS, HVAC UK) | HVAC US, HVAC UK, Roofing UK, Building contractors UK |
| **AI assistant / chatbot** | **2** | **0** | ✅ `"especially the AI assistant and the enquiry flow"` (AC Comfort, HVAC UK) · `"The wonders of AI! How the world is changing."` (Cosytoes, HVAC UK) | **HVAC UK only.** **Zero mentions — positive or negative — from any US prospect, any roofer, any building contractor and the one med spa**, despite the AI assistant being named in every step-1 variant except the "Dial button" one, and in every single demo email |
| **SEO** | **0 unprompted positives** | **0 negatives** | The only SEO discussion is **procurement-style**: Ed Kamhawy's `"Does the website include an XML sitemap and robots.txt?"` and `"Does every service and location page have its own unique SEO title, meta description, H1 and content?"` — questions about implementation correctness, not expressions of interest | HVAC US (1 prospect) |
| **Service pages** | **0** | **0** | Never mentioned by any prospect, despite appearing in every demo email | — |
| **Booking / intake flow** | **1** | **0** | ✅ `"especially the AI assistant and the enquiry flow"` (AC Comfort) — the *only* mention | HVAC UK |
| **Quote forms** | **0** | **0** | Never mentioned by a prospect. Appears in essentially every demo email | — |
| **Lead qualification** ("leads arrive sorted/qualified") | **0** | **0** | Never mentioned by a prospect. Appears in essentially every demo email | — |
| **Mobile experience** | **0** | **0** | Never mentioned. Appears in every step-1 variant ("Loads instantly on mobile and pc") | — |
| **Hosting** | **0** | **1 (concern)** | ❌ `"Who owns the domain, website code, images, content and hosting account?"` and `"Are there any monthly hosting, software, licensing or maintenance fees…?"` (United Heating) | HVAC US |
| **Maintenance / ongoing changes** | **0** | **2 (concerns)** | ❌ `"itemise new product inclusions from time to time and pricelist alterations etc."` (Cosytoes) · ❌ `"Can I edit the website myself without paying you for every content change?"` (United Heating) | HVAC UK, HVAC US |
| **Fast turnaround** | **0** | **0** | Never mentioned by a prospect. "live in 5 days" / "4-5 days" appears in 4 of 7 pricing emails | — |
| **Revisions** ("3 rounds") | **0** | **0** | Never mentioned by a prospect. Appears in nearly every demo email and every pricing email | — |
| **Price** | **0 positive** | **2 negative** | ❌ `"Your prices are much more than our current outgoings."` (Cosytoes) · ❌ `"money is tight for me at the minute it's quiet for me"` (Elevation) — *the latter was said while asking the price, i.e. pre-emptively* | HVAC UK, Roofing UK |
| **"Website already built" (the core hook)** | **0 explicit positives** | **5 disbelief** | ❌ `"If you truly rebuilt my website and not created your own from scratch…"` (Climate HVAC) · ❌ `"Not sure how you could possibly have done that please show me."` (London Building Solutions) · ❌ `"I can't see anything that you've done for my company on website?"` (Unique Roofing) · ❌ `"Seems odd, But ok send me the link"` (HSB) · ❌ `"I've never asked you to do anything for me mate what are you on about mate"` (Kinnane) | HVAC US, Building contractor UK, Roofing UK ×2, Renewables UK |
| **CRM / dispatch integration** | **3 (as requests, i.e. interest)** | **0** | ✅ `"can you develop something that works with my CRM which is field edge"` (Mid-City) · ✅ WEX FSM integration drove an entire follow-up email and became a $1,600 line item (Diamond) · ✅ `"Enquiries can be added to your existing CRM workflow"` was the subject of the Diamond proposal | **HVAC US only** |
| **Source-code ownership** | **0** | **1 (concern, high intensity)** | ❌ `"Do I receive full ownership of the source code?"` … `"Who owns the domain, website code, images, content and hosting account?"` (United Heating) | HVAC US |
| **Geography / who we are** | — | **1 (trust concern)** | ❌ `"And do you guys have a partner int the states."` (Mid-City) — answered with *"we're based in Croatia and work directly with US businesses. No middle man."* and the thread continued to a booked call | HVAC US |

**Summary of what the 58 human replies actually engaged with:**
1. **Is this real?** — 5 mentions (the largest single theme)
2. **The website looks good / bad** — 7 positive, 1 negative
3. **What does it cost** — 7 asks, 2 price objections
4. **Will it work with my CRM / who owns it / what are the ongoing fees** — 5 mentions, all from HVAC US
5. **The AI assistant** — 2 mentions, both HVAC UK, both positive
6. Everything else in the offer (SEO pages, quote forms, mobile, revisions, turnaround, lead qualification) — **0 prospect mentions.**

---

# 11. Funnel reconstruction

Stage-to-stage conversion, per campaign. **Flagged drop-offs are marked 🔻.**

## 11.1 Campaign 3960583 — Solar USA Recycled

| Stage | n | Conversion from previous |
|---|---|---|
| Leads in campaign | 2,479 | — |
| Leads emailed | 1,600 | 64.5% 🔻 *(campaign mid-send, not a leak)* |
| Delivered | 1,505 | 94.1% |
| Replies (all) | 9 | 0.60% 🔻 |
| **Human replies** | 5 | 55.6% |
| Positive replies | 3 | 60.0% |
| Demo requests | 3 | 100.0% |
| Demos sent | 3 | 100.0% |
| **Visited demo site** | **2** | **66.7%** |
| Continued after demo | 1 | **33.3%** 🔻 *(50.0% of those who visited)* |
| Meetings | 0 | **0.0%** 🔻 |
| Price discussions | 1 | — |
| Buying intent | 1 | — |
| Closed sales | 0 | — |

**Largest drop-offs:** delivered→reply (99.40% lost) and demo→continued (66.7% lost). ⚠ 4 days old.

## 11.2 Campaign 3960357 — HVAC USA Recycled

| Stage | n | Conversion from previous |
|---|---|---|
| Leads | 1,781 | — |
| Emailed | 1,561 | 87.6% *(mid-send)* |
| Delivered | 1,523 | 97.6% |
| Replies (all) | 3 | 0.20% 🔻 |
| Human replies | 2 | 66.7% |
| Positive | 2 | 100.0% |
| Demo requests | 2 | 100.0% |
| Demos sent | 2 | 100.0% |
| **Visited demo site** | **0** ⚠ | **0.0%** — *no visit row for either; absence is not proof (§D)* |
| Continued after demo | 0 | **0.0%** 🔻 |
| Meetings / price / intent / sales | 0 | — |

**Largest drop-off:** delivered→reply (99.80% lost). ⚠ n=2 human replies; 4 days old. **This funnel is not interpretable.**

## 11.3 Campaign 3950427 — mixedICP EU

| Stage | n | Conversion from previous |
|---|---|---|
| Leads | 1,957 | — |
| Emailed | 1,957 | 100.0% |
| Delivered | 1,827 | 93.4% |
| Replies (all) | 39 | 2.13% 🔻 |
| **Human replies** | 21 | **53.8%** 🔻 *(46% of replies were machines)* |
| Positive | 16 | 76.2% ← **best positive-share of the five** |
| Demo requests | 16 | 100.0% |
| Demos sent | 17 | 100%+ *(one neutral also received one)* |
| **Visited demo site** | **9** | **52.9%** |
| Continued after demo | 4 | **23.5%** 🔻🔻 *(44.4% of those who visited)* |
| Meetings | 0 | **0.0%** 🔻 |
| Price discussions | 2 | 50.0% of those who continued |
| Buying intent | 2 | — |
| Closed sales | 0 | — |

**Largest drop-offs:** delivered→reply (97.87% lost) and **demo→continued (76.5% lost — the biggest post-engagement leak in the dataset)**. ⚠ 6 days old; 13 of the 17 demos are only 2–5 days old.

## 11.4 Campaign 3912149 — HVAC Europe Eng

| Stage | n | Conversion from previous |
|---|---|---|
| Leads | 1,256 | — |
| Emailed | 1,256 | 100.0% |
| Delivered | 1,181 | 94.0% |
| Replies (all) | 30 | 2.54% |
| **Human replies** | 9 | **30.0%** 🔻🔻 ← **the worst machine/human ratio in the dataset: 70% of replies were autoresponders** |
| Positive | 4 | 44.4% |
| Demo requests | 4 | 100.0% |
| Demos sent | 4 | 100.0% |
| **Visited demo site** | **4** | **100.0%** ← *the only campaign where every demo recipient is recorded as having looked* |
| Continued after demo | 3 | **75.0%** ← **the best demo→continued rate of the five** *(75.0% of those who visited)* |
| Meetings | 0 | **0.0%** 🔻 |
| Price discussions | 2 | 66.7% |
| Buying intent | 2 | 100.0% |
| Closed sales | 0 | **0.0%** — *and unlike everywhere else, both price conversations ended in an explicit, reasoned decline rather than silence* |

**Largest drop-offs:** reply→human reply (70% lost to autoresponders) and price→sale (100% lost, n=2). This campaign converts its few real humans **better than any other** and simply has almost none.

## 11.5 Campaign 3892258 — HVAC USA

| Stage | n | Conversion from previous |
|---|---|---|
| Leads | 2,409 | — |
| Emailed | 2,409 | 100.0% |
| Delivered | 2,367 | 98.3% |
| Replies (all) | 33 | 1.39% 🔻 |
| **Human replies** | 21 | 63.6% |
| Positive | 11 | 52.4% *(9 of the 21 were negative)* |
| Demo requests | 11 | 100.0% |
| Demos sent | 11 | 100.0% |
| **Visited demo site** | **9** | **81.8%** ← *the highest visit rate of the five* |
| Continued after demo | 4 | **36.4%** 🔻 *(44.4% of those who visited)* |
| Meetings | 3 | 75.0% of those who continued · **27.3% of positives** |
| Price discussions | 2 | — |
| Buying intent | 4 | — |
| Closed sales | 0 | **0.0%** |

**Largest drop-offs:** delivered→reply (98.61% lost) and demo→continued (63.6% lost). ⚠ 17 days old — the only campaign where demo→continued has genuinely had time to resolve.

## 11.6 Pooled funnel, all five campaigns

| Stage | n | Conversion | Cumulative from delivered |
|---|---|---|---|
| Leads | 9,882 | — | — |
| Emailed | 8,783 | 88.9% | — |
| Delivered | 8,403 | 95.7% | 100% |
| Replies (all) | 114 | **1.36%** 🔻 largest absolute loss | 1.36% |
| **Human replies** | 58 | **50.9%** 🔻 half of all replies are machines | 0.69% |
| Positive replies | 36 | 62.1% | 0.43% |
| Demo requests | 36 | 100.0% | 0.43% |
| **Demos sent** | 37 | **100.0%** ← no leak at all | 0.44% |
| **Visited the demo site** | **24** | **64.9%** ⚠ *(the 13 non-visits may include join misses, §D)* | 0.29% |
| Continued after demo | 12 | **32.4%** of demos · **50.0% of those who visited** 🔻🔻 | 0.14% |
| Meetings | 3 | 25.0% | 0.036% |
| Price discussions | 7 | *(runs partly in parallel with meetings)* | 0.083% |
| Buying intent | 9 | — | 0.107% |
| **Closed sales** | **0** | **0.0%** | **0.000%** |

### The three flagged drop-offs, in order of size

1. **🔻🔻 Delivered → any reply: 98.64% lost (8,289 of 8,403).** The largest absolute loss, and normal for cold email — but it is where 8,289 of the 8,403 emails end.
2. **🔻🔻 Reply → human reply: 49.1% lost (56 of 114).** Half of every reply received is a machine. **This is not uniform** — 70% in 3912149, 46% in 3950427, 36% in 3892258 — and it tracks the mailbox type on the list (`info@`, `support@`, `service@`, helpdesk-backed addresses).
3. **🔻🔻 Demo sent → continued conversation: 67.6% lost (25 of 37).** The largest leak *after* the prospect has actively raised their hand, and the one the age caveat least excuses for campaign 3892258, where 8 of the ghosts have had 15–16 days and a complete 4-message follow-up sequence.

   **The visit data splits this leak in two, and the halves are not the same thing:**
   - **14 of the 25 lost at this stage are recorded as having opened the demo site and then said nothing** (§7B2). Several returned to it days later; one is still visiting on the day the data was pulled. **The loss here is not attention — they looked.**
   - **11 of the 25 have no recorded visit** (§7B1). ⚠ Whether that means they never opened it, or the join missed them, **cannot be determined from this data.**

   Before the `site_visits` join, this 67.6% was a single undifferentiated number. It is now known to be **at least 56% (14/25) prospects who demonstrably engaged with the artefact and did not write back.**

**Stages that are NOT leaking:**
- Positive reply → demo request: **100%** (the CTA asks for exactly this).
- Demo requested → demo sent: **100%**, at a median of 5.9 hours. **No prospect who asked for the link failed to get it.**
- Demo sent → demo opened: **64.9% recorded**, and ⚠ this is a *floor*, not a ceiling, because unrecorded visits are indistinguishable from missing join rows. **In one case (MTF Roofing) the prospect confirmed in writing that he never received the link, so at least one of the 13 non-visits is a genuine delivery failure rather than disinterest.**

**Stages that cannot be assessed:**
- Price → sale (n=7, oldest 12 days, 2 still live, 2 explicit losses with stated non-price reasons).
- Meeting → sale (n=3, one no-showed twice, one had no price ever quoted, one has no evidenced call).

---

# 12. Timing analysis

## 12.1 Time from send to first reply (58 human replies)

| Metric | Value |
|---|---|
| Median | **0.4 hours (24 minutes)** |
| Mean | 4.5 hours |
| Replied within 1 hour | **39 of 58 (67.2%)** |
| Replied within 24 hours | **56 of 58 (96.6%)** |
| Replied after 24 hours | 2 |

**The distribution is extremely front-loaded.** Two thirds of all human replies land inside the first hour. The two slow ones are HVAC Doctors (5 days after step 2) and Diamond Heating (17.5h after step 2). **Practical implication for the analysing agent: a lead that has not replied within a day of a given step will almost certainly not reply to that step.**

## 12.2 Which sequence step caused the reply

| Step | Emails sent (all campaigns) | Replies attributed (all, incl. machine) | Reply rate per step |
|---|---|---|---|
| **Step 1** (the pitch) | 8,782 | **83** | **0.95%** |
| **Step 2** ("48hrs" / "not a scam") | 6,652 | 20 | 0.30% |
| **Step 3** (breakup) | 4,163 | 11 | 0.26% |

Per campaign:

| Campaign | Step 1 | Step 2 | Step 3 |
|---|---|---|---|
| 3960583 Solar USA Recycled | 8 | 1 | *(never sent)* |
| 3960357 HVAC USA Recycled | 2 | 1 | *(never sent)* |
| 3950427 mixedICP EU | 30 | 6 | 3 |
| 3912149 HVAC Europe Eng | 22 | 4 | 4 |
| 3892258 HVAC USA | 21 | 8 | 4 |

**Initial email vs follow-up distribution: 72.8% of replies come from step 1, 17.5% from step 2, 9.6% from step 3.**

**But the composition matters more than the count.** Tracing the outcome of replies by the step that produced them:

| Step that produced the reply | Notable outcomes |
|---|---|
| Step 1 | Most positives, most negatives, most autoresponders. Includes AC Comfort (replied in **9 minutes**), HVAC Doctors, Climate HVAC, and 8 of the 9 negatives in 3892258 |
| Step 2 | **Produced 3 of the 7 price conversations**: Diamond Heating (`"Send me the link to judge"`), Cosytoes (`"We will have a look please."`), BDS Services. Also Mid-City's `"Yes"` arrived after step 3 had already sent but is attributed to step 1's thread |
| **Step 3 (the breakup)** | **Produced the single most commercially serious lead in the dataset — United Heating's Ed Kamhawy** (`"Hey Andrew , I would like to take a look"`), who went on to send 8 procurement questions. Also **Golden Oak All Trades** (`"I dont see the website?"`, now live) and **Mid-City Heating** (replied 1.5h after step 3 landed, became the only completed meeting). Also 3 of the most hostile negatives ("Please stop.", "Please make this your last email", "No thanks Stop embarrassing yourself") |

🔴 **Step 3 has the lowest reply rate (0.26%) and a strikingly high quality of reply.** Of its 11 replies, 3 became the highest-value threads in the dataset. **This cannot be called statistically significant at n=11**, but it is the kind of pattern the brief asks to be preserved rather than averaged away.

## 12.3 Time from positive reply to our response (demo delivery)

| Metric | Value |
|---|---|
| n | 36 |
| Median | **5.9 hours** |
| Mean | 9.4 hours |
| Max | **29.2 hours** (Diamond Heating) |
| Under 2 hours | 9 |
| Over 12 hours | 14 |
| Over 20 hours | 6 |

### Positive leads where we responded slowly (>18 hours), in full

| Prospect | Campaign | Their reply | Delay | Outcome | Did the delay hurt? |
|---|---|---|---|---|---|
| **Diamond Heating** | 3892258 | `"Send me the link to judge"` | **29.2h** | **Best deal in the dataset** — $1,600 proposal live | **No** |
| DC Air and Heating | 3892258 | `"Send it"` | 22.9h | Ghosted after demo (16 days) | Unknown |
| Dr Band Clinic | 3950427 | `"Yes send it over thanks"` | 22.2h | Ghosted after demo (4 days) | Unknown |
| PROFLO HVAC | 3892258 | `"Let's see what you come up with."` | 22.1h | Ghosted after demo (16 days) | Unknown |
| Free State Cooling | 3892258 | `"Please send it over!"` | 21.5h | Ghosted after demo (16 days) | Unknown |
| Climate HVAC Solutions | 3892258 | `"best cold email I've received in a long time…"` | 20.2h | Ghosted after demo (16 days) | Unknown — **this is the most enthusiastic first reply in the dataset and it received a next-day response** |
| Sky House Construction | 3950427 | `"send the link"` | 19.9h | Ghosted after demo (4 days) | Unknown |
| A1 Bespoke | 3950427 | `"Send it over"` | 19.0h | Ghosted after demo (4 days) | Unknown |
| Omry Building | 3950427 | `"let us have a look sweet"` | 17.0h | Reached price, then silent | **No — he replied 18 minutes after the demo** |
| J Taylor Build | 3950427 | `"Ok where is it?"` | 16.8h | Ghosted after demo (5 days) | Unknown |

**Seven of these demo emails carry an explicit apology** for the delay — *"P.S: Sorry for answering the next day. I was locked in on a project yesterday and the day got away from me."* / *"Sorry for answering so late, had a few more inquiries today than expected."* / *"Sorry for getting back to you so late I had a bit more inquiries than usual."*

**The data does not support "slow response killed these deals":** the slowest response in the entire dataset (29.2h) produced the best outcome, and the fastest responses (52 minutes to HVAC Doctors, 2 hours to Mid-City) produced a double no-show and a stalled thread respectively. **Delay correlates with nothing measurable here.**

## 12.4 Time from positive reply to demo delivery — by outcome group

| Group | n | Median delay |
|---|---|---|
| Ghosted after demo | 23 | 6.6h |
| Reached a price conversation | 7 | 5.9h |
| Reached a meeting | 3 | 2.0h |
| Still live | 4 | 2.5h |

⚠ The meeting group's fast median (2.0h) is built on **3 data points**. It is suggestive and nothing more.

## 12.5 Time from demo delivery to next prospect response

Of the 12 prospects who responded after the demo:

| Prospect | Response delay after demo |
|---|---|
| BDS Services | **8 minutes** *(a rejection)* |
| Omry Building | **18 minutes** |
| Mid-City Heating | 1.2 hours |
| Cosytoes | 2.2 hours |
| AC Comfort | 2.4 hours |
| HVAC Doctors | **6 minutes** |
| Diamond Heating | 16.6 hours |
| Williams Works | ~23 hours |
| Elevation Roofing | ~1.6 days *(prompted by nudge 1)* |
| MTF Roofing | ~2 days *(prompted by nudge 1, and only to say the link was missing)* |
| United Heating | **6 days** |
| London Building Solutions / others | *(no response)* |

**Median for those who did respond: ~2.3 hours. 6 of the 12 responded within 3 hours.** Combined with §12.1, the pattern is consistent: **in this dataset, engagement is same-hour or it does not happen** — with United Heating (6 days) as the standing counter-example.

## 12.6 Time to price discussion

| Prospect | Positive reply → price question | Price question → price email |
|---|---|---|
| AC Comfort | 4.0 hours | 3.3 hours |
| Cosytoes | 2.7 hours | 1.1 hours |
| Elevation Roofing | 1.8 days *(via nudge)* | 14 minutes |
| Omry Building | 17.3 hours | 19 minutes |
| Clear Efficiency | 2.7 hours | 40 minutes |
| Diamond Heating | 2.1 days | **3 days / 2 emails** *(the first answer withheld the number and asked for a call)* |
| HVAC Doctors | 58 minutes | **never — 8 days and counting** |

**Our latency in answering a price question is excellent (median 22 minutes) with two exceptions, and both exceptions are the two prospects who asked for a call.** In both those cases the price was deliberately deferred to a call that then did not happen on schedule.

## 12.7 Time to meeting

| Prospect | Positive reply | Meeting requested | Calendly sent | Meeting date | Outcome |
|---|---|---|---|---|---|
| Mid-City Heating | 2026-09-08 19:54 | *(we proposed)* 2026-09-09 13:25 | same message | booked → **no-show 09-11** → rebooked → **2026-09-14 12:30 EST** | Join link acknowledged; nothing since |
| HVAC Doctors | 2026-09-09 11:23 | **prospect proposed** 2026-09-09 12:21 | 2026-09-09 12:43 (**+22 min**) | booked 09-10 04:30 **AM** local (timezone error) → rebooked 09-10 16:30 → **no-show** | Ghosted 8 days |
| Diamond Heating | 2026-09-12 15:36 | **prospect proposed** 2026-09-14 17:51 | 2026-09-14 17:58 (**+7 min**) | **none evidenced in the thread** | Proposal sent instead, 2 days later |

**Time from a meeting request to a Calendly link: 7 and 22 minutes. That stage is not the bottleneck.** What failed downstream was **timezone handling (2 of 3)** and, for Diamond, the meeting simply never being scheduled.

---

# 13. A/B message comparison

## 13.1 The experimental design, as actually run

- **Step 1 carries the A/B test** in all five campaigns (4 variants; 5 in campaign 3960583). Split is near-perfectly even — arms differ by at most 16 sends out of ~600.
- **Step 2 has 2 variants** in all five; **step 3 has none**. Neither is analysed here as an experiment because reply attribution to step 2 is confounded by which step-1 variant opened the thread.
- **Attribution rule used:** a lead's reply is credited to the **step-1 variant that opened their thread**, regardless of which step drew the reply. This is the correct rule — only step 1 differs between arms, so the variant is the property of the thread, not the message.
- **Target audience is identical within each campaign** (the same list, randomly split), so within a campaign the arms are fairly comparable. **Across campaigns they are not** — different lists, geographies, ages and send volumes.

## 13.2 Full per-variant results

### Campaign 3960583 — Solar USA Recycled (5 arms)

| Variant | Subject | Sent | Replies | Reply rate | Positives | Positive rate | Demos | Price | Meetings |
|---|---|---|---|---|---|---|---|---|---|
| A | `my weird hobby` | 320 | 0 | 0.00% | 0 | 0.00% | 0 | 0 | 0 |
| B | `built you a website, no charge to look` | 319 | 2 | 0.63% | 0 | 0.00% | 0 | 0 | 0 |
| **C** | `I built {{co}} a fresh website this week` | 321 | **4** | **1.25%** | **3** | **0.93%** | 3 | 1 | 0 |
| D | `{{co}}'s fresh website is live` | 320 | 2 | 0.63% | 0 | 0.00% | 0 | 0 | 0 |
| E | `{{subjectLine}}` (per-lead) | 320 | 1 | 0.31% | 0 | 0.00% | 0 | 0 | 0 |

**Statement on sample size: this campaign has 9 replies and 3 positives in total. Variant C "winning" rests on 3 positive replies.** At these counts the 95% confidence interval on C's positive rate (0.93%) comfortably contains 0%, and the interval on A's 0% contains C's point estimate. **No variant can be declared better in this campaign.** Worth noting for interest only: C is the variant carrying the `%sender-fir` truncation defect.

### Campaign 3960357 — HVAC USA Recycled (4 arms)

| Variant | Subject | Sent | Replies | Reply rate | Positives | Positive rate |
|---|---|---|---|---|---|---|
| A | `my weird hobby` | 391 | 2 | 0.51% | 1 | 0.26% |
| B | `built you a website, no charge to look` | 392 | 0 | 0.00% | 0 | 0.00% |
| C | `I built {{co}} a fresh website this week` | 390 | 1 | 0.26% | 1 | 0.26% |
| D | `{{co}}'s fresh website is live` | 388 | 0 | 0.00% | 0 | 0.00% |

**Statement on sample size: 3 replies and 2 positives across 1,561 sends. This test contains no information whatsoever.** Any apparent ranking is noise. Do not use it.

### Campaign 3950427 — mixedICP EU (4 arms) — **the best-powered test of the five**

| Variant | Subject | Sent | Replies | Reply rate | Positives | Positive rate | Demos | Price | Meetings |
|---|---|---|---|---|---|---|---|---|---|
| A | `my weird hobby` (uses `{{vertical}}`) | 489 | 9 | 1.84% | 4 | 0.82% | 4 | 0 | 0 |
| B | `built you a website, no charge to look` (uses `{{vertical}}` + "I built hundreds of projects") | 491 | 10 | 2.04% | 3 | 0.61% | 3 | 0 | 0 |
| C | `your redesigned website is live` | 486 | 8 | 1.65% | 4 | 0.82% | 4 | 0 | 0 |
| **D** | `{{co}}'s fresh website is live` ("Dial button…Google reviews") | 490 | **12** | **2.45%** | **5** | **1.02%** | 5 | 1 | 0 |

**Statement on sample size:** the arms are cleanly balanced (486–491 sends each) and this is the largest positive count per arm anywhere in the dataset — **and it is still 3 to 5 positives per arm.** The spread between best (D, 1.02%) and worst (B, 0.61%) is **two positive replies**. **Not significant.** A rough Wilson interval on D's 5/490 runs roughly 0.4%–2.4%, overlapping every other arm. **Do not declare D the winner.**

### Campaign 3912149 — HVAC Europe Eng (4 arms) — **the one result worth flagging**

| Variant | Subject | Sent | Replies | Reply rate | Positives | Positive rate | Demos | Price |
|---|---|---|---|---|---|---|---|---|
| A | `my weird hobby` | 314 | 9 | **2.87%** | **0** | **0.00%** | 0 | 0 |
| B | `built you a website, no charge to look` | 315 | 5 | 1.59% | **0** | **0.00%** | 0 | 0 |
| C | `your redesigned website is live` | 314 | 9 | **2.87%** | 2 | 0.64% | 2 | 1 |
| D | `{{co}}'s fresh website is live` | 313 | 7 | 2.24% | 2 | 0.64% | 2 | 1 |

🔴 **This is the clearest demonstration in the dataset that reply rate and positive rate rank variants differently.** Variant A is **tied for the highest reply rate (2.87%) and has zero positives** — all 9 of its replies were autoresponders, out-of-office notices or hostile. **Statement on sample size: 4 positives across the whole campaign, 2 per winning arm. The A-vs-C difference is 2 replies wide and is not significant.** What *is* robust here is the qualitative point: **ranking on reply rate would have selected the variant with no positive outcomes at all.**

### Campaign 3892258 — HVAC USA (4 arms)

| Variant | Subject | Sent | Replies | Reply rate | Positives | Positive rate | Demos | Meetings | Price |
|---|---|---|---|---|---|---|---|---|---|
| A | `my weird hobby` | 599 | 9 | 1.50% | 2 | 0.33% | 2 | **1** (Mid-City) | 0 |
| B | `built you a website, no charge to look` | 611 | 7 | 1.15% | 3 | 0.49% | 3 | 0 | 0 |
| C | `your redesigned website is live` | 595 | 8 | 1.34% | 2 | 0.34% | 2 | 0 | **1** (United Heating) |
| **D** | `{{co}}'s fresh website is live` | 604 | 9 | 1.49% | **4** | **0.66%** | 4 | **2** (Diamond, HVAC Doctors) | **1** (Diamond) |

**Statement on sample size:** positives range 2–4 per arm across ~600 sends each. **The difference between the best (D, 4) and worst (A/C, 2) arms is two positive replies.** Not significant. The meeting counts (1/0/0/2) rest on 3 events in total and **must not be used to rank variants**.

## 13.3 Pooled variant comparison across campaigns — **read the caveat first**

⚠ **Pooling across campaigns mixes different lists, verticals, geographies and campaign ages.** Variant A's body text also differs between campaigns (the `{{vertical}}` token, "Solar companies" vs "HVAC companies" vs "Roofing companies"). This table is provided because the brief asks for a fair comparison and per-campaign arms are too thin to say anything; it is **not** a clean experiment.

| Variant family | Total sent | Replies | Reply rate | Positives | Positive rate | Positives as % of its own replies | Demos | Meetings | Price convos |
|---|---|---|---|---|---|---|---|---|---|
| **A — "my weird hobby"** | 2,113 | 29 | **1.37%** | 7 | **0.33%** | **24.1%** | 7 | 1 | 0 |
| **B — "built you a website, no charge to look"** | 2,128 | 24 | 1.13% | 6 | 0.28% | 25.0% | 6 | 0 | 0 |
| **C — "I built…" / "your redesigned website is live"** | 2,106 | 30 | **1.42%** | 12 | **0.57%** | **40.0%** | 12 | 0 | 3 |
| **D — "{{co}}'s fresh website is live"** | 2,115 | 30 | **1.42%** | 11 | **0.52%** | 36.7% | 11 | **2** | 2 |
| E — `{{subjectLine}}` (one campaign only) | 320 | 1 | 0.31% | 0 | 0.00% | 0.0% | 0 | 0 | 0 |

⚠ **Variant C is not one message.** It is `"I built {{co}} a fresh website this week"` (with the `%sender-fir` defect) in campaigns 3960583/3960357, and `"your redesigned website is live"` in 3950427/3912149/3892258. **Treating them as one arm is not valid** and the row is shown only for completeness. Splitting it: the `"I built…"` subject sent 711 for 4 positives (0.56%); the `"your redesigned…"` subject sent 1,395 for 8 positives (0.57%).

**What can be said with the pooled data, stated at the right confidence:**
- Reply rate spread across A/B/C/D is **1.13%–1.42%** — a range of 0.29 percentage points on ~2,100 sends each. **Marginal at best.**
- Positive rate spread is **0.28%–0.57%**, i.e. C and D produce roughly **twice** the positives of A and B (23 vs 13 positives from near-identical volume). **This is the only variant-level pattern in the entire dataset that survives pooling, and even it rests on a 10-reply difference.** A rough Wilson interval on C+D pooled (23/4,221 = 0.545%, roughly 0.36%–0.82%) against A+B pooled (13/4,241 = 0.307%, roughly 0.18%–0.52%) shows **overlapping intervals** — so it is a *leaning* signal, not a proven one.
- **Positives as a share of that variant's own replies is the more separated measure: A and B convert 24–25% of their replies into positives, C and D convert 37–40%.**
- **Variant E (`{{subjectLine}}`, the per-lead AI-written subject) ran in one campaign only, 320 sends, 1 reply, 0 positives. It has not been meaningfully tested.**

## 13.4 Common reply themes, per variant

| Variant | Target audience | Common themes in its replies |
|---|---|---|
| A "my weird hobby" | Same list as all arms | Attracted the **highest share of hostile and machine replies**: in 3912149 all 9 of its replies were non-positive; in 3892258 it drew "Please make this your last email. We dont need anymore spam." and "Stop sending email to this address". Its 7 positives were all bare link requests (`"Sure"`, `"Yes"`, `"Link please"`, `"Send it over"`, `"Go on then , show me your work"`, `"Yes."`). Note it also produced the one completed meeting |
| B "built you a website, no charge to look" | Same | Similar profile to A. In 3950427 its version carries the extra social-proof line *"I usually work with {{vertical}} and I built hundreds of projects over the years"*. Drew the disbelief objection twice (London Building Solutions, Unique Roofing) and the "best cold email" praise once (Climate HVAC) |
| C "I built…" / "your redesigned website is live" | Same | **The highest positive-to-reply conversion.** Drew 3 of the 7 price conversations (Clear Efficiency, AC Comfort via D, United Heating). Its replies skew toward engaged questions rather than reflexive stops |
| D "{{co}}'s fresh website is live" ("Dial button…Google reviews") | Same | **The only variant that produced more than one meeting (2 of 3).** Its body is the most concrete of the four — it names specific artefacts (the dial button, the services layout, the Google reviews) rather than "modern design". Drew Diamond Heating, HVAC Doctors, Cosytoes and AC Comfort — **4 of the 7 price conversations trace to D or its campaign-D equivalent** |
| E `{{subjectLine}}` | 320 leads in 3960583 only | Insufficient data |

## 13.5 The one A/B conclusion this dataset supports

**None on statistical grounds.** The strongest available statement, and it is a *leaning* one:

> Across ~8,500 pooled sends, the two variants that describe a **finished, specific artefact** ("I built / your redesigned website **is live**", plus D's concrete feature list) produced 23 positive replies, against 13 from the two variants built on a **hook or a soft ask** ("my weird hobby", "no charge to look"), at essentially identical reply rates. **The confidence intervals overlap.** This is a hypothesis for a properly-powered test, not a result.

**Required sample size note:** to detect a difference between a 0.30% and a 0.55% positive rate at 80% power and 95% confidence would need roughly **12,000–14,000 sends per arm.** The best-powered arm in this dataset has 611.

---

# 14. Data quality / caveats

Everything that makes a conclusion in this document unreliable, listed so the analysing agent can weight accordingly.

## 14.1 Campaign age — the dominant caveat
1. **All five campaigns are ACTIVE.** Nothing here is a final result.
2. **Ages range from 2 to 17 days.** The oldest campaign (3892258) is the only one where post-demo silence has had time to mean anything.
3. **Two campaigns are mid-send.** 3960583 has emailed 1,600 of 2,479 leads (879 never contacted); 3960357 has emailed 1,561 of 1,781 (220 never contacted).
4. **Step 3 has never fired in two campaigns** (3960583, 3960357). Since step 3 produced 3 of the dataset's highest-value threads (§12.2), those campaigns' funnels are missing their most productive follow-up.
5. **10 of the 23 "ghosted after demo" leads have been silent 5 days or fewer**, several with zero follow-ups sent. Labelling them ghosts is provisional. **United Heating returned after 6 days of silence with the most serious buying message in the dataset** — direct proof the label is unsafe at this age.
6. **All 3 "ghosted after price" leads have been silent 3–4 days.** Cosytoes took 6 days to decline; AC Comfort took 8.

## 14.2 Sample size
7. **58 human replies total across 8,403 delivered emails.** Every rate below "human reply" is built on small numbers.
8. **36 positives, 37 demos, 7 price conversations, 3 meetings, 0 sales.** Demo→sale, price→sale and meeting→sale have **no data at all**, not poor data.
9. **Campaign 3960357 has 2 human replies.** It cannot be compared to anything.
10. **No A/B variant comparison in any campaign is statistically significant** (§13). The best-powered arm has 5 positives.
11. **Med spas (1 positive from 247) and Home renovators (0 from 197) have no interpretable results.**

## 14.3 Unequal lead quality and composition
12. **Website coverage is not uniform.** Campaign 3960583 has a website recorded for only **40.6%** of leads; the other four are at 100%. The offer is "I rebuilt your website", so a lead with no website on file is a materially different prospect.
13. **Serious ICP drift in two campaigns** (§4.1, §4.4): a "Solar" list containing a vacuum heat-treating company, an EV-charging network and an electrical wholesaler; an "HVAC" list containing the National Trust charity, a gym, a tool merchant, a radiator showroom and a B2B underfloor-heating wholesaler.
14. **Two campaigns use recycled lists** (3960583, 3960357 by name; **3912149 provably so** — its `custom_fields` carry `campaign_id: "3278845"` and a full set of AI-secretary copy tokens). Recipients may have been emailed before with a different offer, which is not visible in these campaigns' data.
15. **One campaign mixes four verticals** (3950427) and the campaign title names only three.
16. **Two campaigns are named for a geography they do not target:** "mixedICP - **EU**" and "HVAC - **Europe** - Eng" are both UK lists.
17. **Job titles are absent from all five lists** and ~78% of mail went to generic mailboxes. This is the most likely driver of the 49.1% machine-reply rate, and it is not measurable from Smartlead.

## 14.4 Unequal send volumes and sequences
18. **Send volumes per campaign range 1,256–2,409 unique leads**, and per step from 0 to 2,409.
19. **Step counts differ in practice:** three campaigns ran the full 3 steps; two have run 2.
20. **Campaign 3892258 has 904 leads marked `blocked`** in `campaign_lead_stats` (37.5% of its list) versus 70–119 elsewhere. The cause is not exposed by the API. This materially affects its effective denominator and is unexplained.
21. **Follow-up after the demo is hand-written, ad hoc and inconsistent** — 0 to 4 messages, three different CTAs, no standard cadence. **It is not part of the Smartlead sequence at all**, so demo-stage follow-up is not measurable as a controlled variable.

## 14.5 Missing tracking, and the limits of the demo-visit data
22. **No open rate and no click rate on the emails themselves.** `DONT_EMAIL_OPEN` / `DONT_LINK_CLICK` on all five; `open_count` and `click_count` are 0 on all 19,597 rows. **Whether an email was opened is unanswerable.** Only demo-site visits are tracked, and only for leads who got that far.
23. **`visit_count` is NOT a page-view count and must never be reported as one.** Vercel groups requests into **4-hour blocks**, so a "visit" is *one 4-hour block in which a human hit the site*. A prospect who browsed for two hours straight registers **1 visit**; a prospect who glanced twice on different days registers **2**. The raw request figure is the separate column **`total_requests`**, and both are reported side by side throughout this document. The underlying `buckets` column holds requests-per-block if finer resolution is needed.
24. 🔴 **A demo recipient with no recorded visit is NOT evidence that they never looked.** The `site_visits` join is **keyed by company email domain**, not lead id, because **most of these prospects have no `leads_state` row at all** — demo sites are built outside the normal pipeline. The fallback match is the demo URL. Three different causes produce an identical empty result:
    - the prospect genuinely never opened the link,
    - the join failed to match their company domain,
    - the Vercel push for that project was missing or failed.

    **These cannot be distinguished.** Every "0 visits" figure in this document (13 of 37 demo recipients) carries this caveat. One of the 13, **MTF Roofing, is independently confirmed as a genuine non-delivery** — he wrote *"Ive not seen the link to It?? Please re-send"* — which proves the bucket contains at least one delivery failure as well as any true disinterest.
25. 🐞 **The domain-keyed join misfires on freemail domains.** `jlhheating@gmail.com` — a lead who received no demo and replied only *"Stop sending email to this address we're not interested"* — was falsely matched to another prospect's visit record because `gmail.com` is shared. **Four of the five campaigns' lists contain gmail.com leads.** This was found and corrected here (exact-email match first, domain fallback only for company domains); anyone re-running the join must handle it.
26. ⚠ **Golden Oak All Trades' `last_visit` is 2026-09-18, one day before this data was pulled (2026-09-19).** Their demo went out on 09-18 and the thread is 1 day old. **This is the figure most likely to be already stale by the time anyone reads this report**, and their placement in the §7B2 "silent but visited" list is an artefact of the thread's age, not of disengagement.
27. 🐞 **One visit record pre-dates its own demo email.** DC Air and Heating's `first_visit` is 2026-09-02 16:00 while `demo_sent_on` is 2026-09-03. Either the site was deployed and hit before the email went out, or the 4-hour bucketing/timezone handling shifts the boundary. **Unresolved.**
28. **The visit data cannot be re-derived.** Free Vercel observability retains **1 day**; the `site_visits` table is the only long-term record, built by unioning daily `cli/visits.mjs --push` runs. If a push was missed on a given day, that day's visits are gone permanently and look identical to no visits.
29. **Visit data says nothing about what was viewed.** There is no page-level breakdown, no scroll depth and no dwell time. In the one case where it would have mattered most — BDS Services rejecting the demo as *"the same as existing one"* 8 minutes after receiving it, having been pointed at three specific sub-pages in the rebuttal — **it can only be said that no further visit was recorded, not that the sub-pages went unopened.**
30. **No revenue, deal value or payment status.** `campaign_lead_stats.revenue` is 0 on all five and is not wired to anything. The Diamond Heating Stripe payment status is not knowable here.
31. **Meeting outcome is not recorded.** "Meeting-Booked" is a Smartlead category; whether a call happened is only inferable from thread text, and in one of three cases the thread proves it did not.

## 14.6 Replies not correctly labelled by Smartlead
32. **Smartlead's own categories disagree with a hand read in several places.** Examples: `Auto-Reply` on Yeck Heating (a garbled human message), `Do Not Contact` on leads that only sent an OOO, `Interested` on Airmark and Cosmo's who only said "send the link" and then vanished, `Lead Done` on Azteca and DC Air with no closing event, and `Meeting-Booked` on Diamond Heating where no meeting is evidenced. **Every classification in §5–§8 of this document is a hand read, not Smartlead's label.**
33. **`analytics.reply_count` and the `/statistics` reply rows disagree** (e.g. 8 vs 9 on campaign 3960583) because one counts per lead and the other per email. All rates here use `/statistics`.
34. **Duplicate replies inflate raw reply counts.** Briggs Air (3912149) sent the **same out-of-office 8 times**; Plumb Mate sent 4 from different colleagues; Elevation Roofing sent 4 messages in 7 seconds (one of which was the single character `"I"`). All are de-duplicated to one lead here.

## 14.7 Duplicate and dead leads
35. **Acquired / retired businesses are on the lists.** Bill Trombly Plumbing ("now part of Sanford Temperature Control… PLEASE REMOVE INFO@BILLTROMBLY.COM FROM YOUR EMAIL LIST"), Sisu Clinic ("This email address is no longer monitored"), Smart Group Scotland and Turnkey Energy (named contact no longer employed).
36. **No cross-campaign de-duplication was checked.** Whether the same company appears in more than one of the five campaigns is not verified here. Given two campaigns are explicitly "Recycled" and a third is provably recycled from campaign 3278845, **overlap is likely and is not accounted for.**

## 14.8 Inbox rotation and sender differences
37. **A very large rotating sender pool is in use.** Across the 114 replying leads, mail was sent from **60+ distinct mailboxes on 40+ distinct domains** (`mindaptivepro.com`, `mindaptivelabs.com`, `usemindaptive.com`, `getmindaptive.com`, `team-mindaptive.com`, `myndaptive.com`, `mind-aptive.com`, `mindaptive-tech.com`, `mindaptivegpt.com`, `mindaptivebrain.com`, `mindaptivedeep.com`, `trymindaptive.com`, `meetmindaptive.com`, `gomindaptive.com`, `teammindaptive.com`, `mindaptiveagents.com`, `mindaptiveintelligence.com`, and more). **Per-mailbox and per-domain deliverability is not analysed in this document** and could confound every campaign-level comparison. The raw `/statistics` rows needed for that analysis are preserved in `_raw/stats_<campaign_id>.jsonl`.
38. **Two sender personas are in use** — "Andrew Juran" and "Mia Malčić" — and **the signature block is inconsistent** across sends from the same persona (variously "Co-Founder @ Mindaptive.ai", "Co-founder @ Mindaptive", "Co-Founder | Mindaptive.ai" with a full US address block, or a short two-line version). The name is also spelled both "Mia Malcic" and "Mia Malčić" depending on the mailbox. **Persona was not analysed as a variable here.**

## 14.9 Copy defects that reached real prospects (all verified in delivered `SENT` bodies)
39. **`Hi, You didn't ask, I know. I did it anyway. I'm %sender-fir`** — a truncated, duplicated opening line with a cut-off merge token, in variant C of campaigns 3960583 and 3960357. Verified delivered to at least 5 prospects.
40. **`What do you think about your new website,?`** — a failed `{name}` merge in the post-demo nudge. Verified delivered to at least 9 prospects across 4 campaigns.
41. **Persona mix-up:** an email signed `"Best, Mia"` was sent over Andrew Juran's signature block to Cosmo's Heating (3892258, 2026-09-14).
42. **`I'll take the {{companyNickname}}'s redesigned website down`** — a grammatical artefact ("the Diamond's", "the TDI's") in step 3 of all five campaigns, delivered to every lead who reached step 3 (4,163 sends).
43. **Typo `"motived"`** in variants D and E of campaign 3960583 (640 sends).
44. **Lowercase company names** throughout campaign 3950427's rendered emails ("kinnane roofing & guttering services's fresh website is live", "a&j kitchen fitters", "dr band clinic") because `companyNickname` was stored lowercase on that list.
45. **A takedown threat fired on an actively-evaluating prospect** (United Heating received "your new website comes down in about 48 hours" and "I'll be taking the website down this evening" while silently reviewing; he returned regardless). 🔍 **The visit record shows his first visit falls on the same day as the takedown message**, and 4 of the B2 group returned to their sites days after being told the site was coming down or was already gone (Azteca's last visit is 5 days after "Your website is no longer available"). **The takedown claim and the observed behaviour do not match; whether the sites were actually taken down is not recorded anywhere in this data.**
46. **A post-demo nudge fired on a post-price prospect** (Clear Efficiency received "What do you think about your new website,?" three days *after* receiving a full price).

## 14.10 What this document deliberately does not do
47. **No campaign's numbers are merged into another's** anywhere except the explicitly-labelled pooled tables in §1.6, §11.6 and §13.3, each of which carries its own caveat.
48. **The coarse classifier in `app/reply_classifier.py` was not used** for any classification here. All 114 replies were read and classified by hand against the brief's taxonomy.
49. **No AI-generated insight layer** (`campaign_conversations.sync_conversations`, `campaign_report.generate_directives`) was used, per the brief.

---

# 15. Machine-readable export

**File:** `docs/campaign-postmortems/website-offer-campaigns-dataset-2026-09-19.json`
**Format:** JSON array, **114 objects — one per replying lead**, across all 5 campaigns.

**Join note:** demo-visit fields are joined from `analysis/data/demo_visits_by_lead.json` on **exact lead email first, company domain second** (freemail domains excluded from the domain fallback after a false `gmail.com` match was found — §14.5 item 25). **All 37 demos identified from the threads matched a join row; none was missing and none was extra.** The join file's other 3 rows belong to campaign 3886379 and are excluded.

**Scope note:** the export covers **every lead that replied** (114), not all 9,882 leads in the campaigns. Non-replying leads carry no reply, no classification and no thread, so a row for each would be 9,768 near-identical records. The per-campaign and per-variant denominators needed to compute any rate over the full population are in §1, §2 and §13 of this document, and the raw per-send rows are preserved in `_raw/stats_<campaign_id>.jsonl`.

## Fields (all 24, per the brief's list plus tracing IDs)

| Field | Type | Notes |
|---|---|---|
| `campaign_id` | int | **Traces back to Smartlead** |
| `campaign_name` | string | |
| `lead_id` | string | **Traces back to Smartlead** (`GET /campaigns/{campaign_id}/leads/{lead_id}/message-history`) |
| `vertical` | string | Per-lead `custom_fields.vertical` where present, else the campaign-level vertical |
| `sub_vertical` | string / null | **Non-null only for campaign 3950427**, the one campaign with a declared per-lead segment |
| `lead_source` | string | From `custom_fields.ICP_Source`; the literal string `"unknown (custom_fields has no ICP_Source for this lead)"` where absent |
| `company` | string | |
| `prospect_name` | string | Often blank — the lists are company-level |
| `job_title` | null | **Always null. No job title exists in any of the five lists.** |
| `email` | string | The address emailed (note: replies frequently come from a different address; see `all_thread_messages`) |
| `website` | string | |
| `location` | string | |
| `smartlead_category` | string | Smartlead's own label — **kept for comparison, NOT used for classification** |
| `subject_variant` | string | The step-1 variant's subject template |
| `initial_message_variant` | string | `A`–`E` |
| `step1_variant_id` | string | Smartlead's `seq_variant_id` — **traces back to `GET /campaigns/{id}/sequences`** |
| `follow_up_variant` | string | Constant note pointing at §3 (step-2 variant is not separably attributable) |
| `emails_sent` | int | Count of `/statistics` rows for this lead |
| `last_sequence_step_sent` | string | From the leads export |
| `delivered` | 0/1 | |
| `bounced` | 0/1 | |
| `replied` | 1 | Always 1 by construction |
| `reply_class` | enum | `positive` · `neutral` · `negative` · `automated` — **hand-classified** |
| `reply_subclass` | string | The taxonomy subclass from §5 |
| `first_reply_text` | string | The prospect's first reply, plain text, quoted history trimmed |
| `positive` | 0/1 | |
| `demo_requested` | 0/1 | |
| `demo_sent` | 0/1 | |
| `meeting_booked` | 0/1 | |
| `price_discussed` | 0/1 | |
| `buying_intent` | 0/1 | |
| `won` | 0/1 | **0 on all 114** |
| `lost` | 0/1 | 1 for explicit declines and negatives; **0 for ghosts**, which are recorded via `ghost_stage` |
| `ghost_stage` | string | `""` · `ghosted_after_demo` · `ghosted_after_price` · `ghosted_after_meeting_proposed` · `declined_after_demo` · `declined_after_price` |
| `final_status` | string | Free text, dated where a thread is live |
| `all_thread_messages` | array | **Every message in the thread**, chronological: `{type: SENT/REPLY, seq, time, from, to, subject, body}`. Bodies are plain text with quoted history trimmed, truncated at 6,000 chars |
| `notes` | string | Reserved, empty |

### Demo-site visit fields (from `site_visits`, not Smartlead — see §D)

Present on all 114 records; **populated on the 37 that received a demo, `null` on the other 77.**

| Field | Type | Notes |
|---|---|---|
| `demo_built` | 0/1 | 1 for the 37 demo recipients in scope |
| `demo_url` | string / null | The Vercel URL that was sent, e.g. `https://diamond-heat-cool.vercel.app` — **traces back to `site_visits.demo_url`** |
| `demo_sent_on` | date / null | From the join file |
| `demo_visit_count` | int / null | **Distinct 4-hour Vercel blocks with human traffic — NOT page views.** 0 means no visit is recorded, which is not the same as "did not visit" |
| `demo_total_requests` | int / null | Raw human request count. Use this, not `demo_visit_count`, for volume |
| `demo_first_visit` | timestamp / null | Earliest recorded human visit |
| `demo_last_visit` | timestamp / null | Most recent. ⚠ Golden Oak's is 1 day before the pull date and will be stale |
| `demo_visitors` | array / null | Per-visitor records as stored: `{country, isp, device, requests, first, last}`. Bots, crawlers, hosting/VPN networks and Mindaptive's own traffic are already stripped upstream |
| `demo_visited` | 0/1 / null | Derived: 1 if `demo_visit_count > 0` |
| `demo_visit_tracking` | string | An explicit provenance note on every record, so a consumer cannot silently misread a 0. For non-visitors it reads: *"NO visit recorded - may be a genuine non-visit OR a domain-match miss / missing Vercel push; cannot be distinguished"* |
| `silent_but_visited` | 0/1 / null | **1 for the 14 leads in §7B2** — demo sent, site visited, never replied after the demo |
| `replied_after_demo` | "yes"/"no" / null | As carried in the join file |

## Aggregate check (the JSON must reproduce these)

| | 3960583 | 3960357 | 3950427 | 3912149 | 3892258 | **Total** |
|---|---|---|---|---|---|---|
| records | 9 | 3 | 39 | 30 | 33 | **114** |
| `reply_class = automated` | 4 | 1 | 18 | 21 | 12 | **56** |
| `reply_class = positive` | 3 | 2 | 16 | 4 | 11 | **36** |
| `reply_class = neutral` | 1 | 0 | 1 | 1 | 1 | **4** |
| `reply_class = negative` | 1 | 0 | 4 | 4 | 9 | **18** |
| `demo_sent = 1` | 3 | 2 | 17 | 4 | 11 | **37** |
| `demo_visited = 1` | 2 | 0 | 9 | 4 | 9 | **24** |
| `demo_visited = 0` (no row ⚠) | 1 | 2 | 8 | 0 | 2 | **13** |
| `silent_but_visited = 1` | 2 | 0 | 6 | 1 | 5 | **14** |
| `meeting_booked = 1` | 0 | 0 | 0 | 0 | 3 | **3** |
| `price_discussed = 1` | 1 | 0 | 2 | 2 | 2 | **7** |
| `buying_intent = 1` | 1 | 0 | 2 | 2 | 4 | **9** |
| `won = 1` | 0 | 0 | 0 | 0 | 0 | **0** |

## Raw working data also preserved

`docs/campaign-postmortems/_raw/` contains, per campaign:
- `meta_<id>.json` — campaign settings, analytics totals, full sequence templates
- `stats_<id>.jsonl` — **all 19,597 per-send rows** (variant id, step, sent/open/click/reply times, bounce, unsubscribe flags)
- `leads_<id>.csv` — the full leads export including the raw `custom_fields` blob
- `threads_<id>.json` — raw API thread payloads for every replying lead
- `threads_<id>.txt` — the human-readable thread dumps used to write §5–§8
- `sequences.txt` — every template and variant, rendered as plain text
- `derived_<id>.json` — the per-lead variant map and replier/bounce sets used for every rate in this document

---

# 16. Most important requirement — compliance statement

**No strategic recommendations appear in this document.** Nothing here says what to change, what to test next, which vertical to double down on, how to rewrite the copy, when to quote a price, or how to fix the demo→ghost leak. Where a defect, an inconsistency or a leak is identified, it is **described and evidenced**, not acted on.

The following raw material has been preserved for independent analysis:

| Diagnostic axis the brief names | Where the raw material is |
|---|---|
| **List quality** | §4 — per-campaign `custom_fields` inventory, website-coverage rates, source fields, verification fields, the four-way segment split for 3950427, the two documented ICP-drift findings with named companies. Full raw lists in `_raw/leads_*.csv` |
| **Copy** | §3 — every step-1 variant, step-2 variant and step-3 template **verbatim**, with per-variant sent/reply/positive numbers attached. Plus the demo-delivery emails, the four post-demo nudges and all seven pricing emails, none paraphrased. Copy defects itemised in §14.9 |
| **Offer** | §3.8 — all seven price quotes side by side, showing $580 / £650 / $850 / £850 / $950 / $1,200 / $1,600 for the same offer within 16 days. §10 — which parts of the offer prospects actually mentioned (and the long list that nobody ever mentioned) |
| **CTA** | §3 — the step-1 CTA is uniform ("reply and I'll send the link") and §5.2 shows it produced exactly the reply it asks for, 86% of the time, in five words or fewer. §7B — the three different, non-standardised demo-email CTAs and the fact that 22 of 24 ghosted-after-demo threads contained no call-to-book |
| **Vertical fit** | §9 — eight verticals reported separately with the sample size behind each rate, plus per-vertical qualitative patterns and an explicit statement that none of the comparisons is significant |
| **Follow-up** | §12.2 — reply rate and reply *quality* per sequence step, including step 3's three high-value threads. §7B — post-demo follow-up volume, content and outcome per thread. §14.4 — the note that post-demo follow-up is ad hoc and not a controlled variable |
| **Demo delivery** | §3.6 — four full demo emails spanning the range. §12.3–12.5 — delivery latency per lead with outcome, showing the slowest delivery produced the best deal. §6.3 — the only explicit product rejection, with its 8-minute response time |
| **Whether the demo was actually opened** | **§D** — the `site_visits` source, its 4-hour-block semantics and its domain-keyed join limits. **§7B1/B2** — the 37 demos split into 24 recorded visits and 13 non-records, with the **14-lead silent-but-visited list** given in full (visit count, raw requests, first/last visit, visitor signatures, thread status). §6 — per-thread visit figures on every live deal, price thread and decline. §9, §11 — visit stage added per vertical and per funnel. Raw: `analysis/data/demo_visits_by_lead.json`, `demo_visitors_silent_HOT.csv`, `site_visits.json` |
| **Pricing** | §3.8 — all seven pricing emails verbatim plus the comparison table. §6.2 and §7E/G — every price thread reconstructed, including both explicit declines with the prospect's stated reasons in full |
| **Conversion leaks** | §7 — the A–G ghosting split. §11 — stage-by-stage funnel per campaign with the largest drop-offs flagged. §11.6 — the pooled funnel isolating demo→continued (67.6% lost) as the largest post-engagement leak, with the age caveat attached |

**Output files:**
1. `docs/campaign-postmortems/website-offer-campaigns-postmortem-2026-09-19.md` — this document
2. `docs/campaign-postmortems/website-offer-campaigns-dataset-2026-09-19.json` — 114 structured records
3. `docs/campaign-postmortems/_raw/` — all intermediate API data, preserved for re-analysis
