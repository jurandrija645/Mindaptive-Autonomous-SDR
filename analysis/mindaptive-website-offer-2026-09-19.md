# Mindaptive — "Website offer" campaign analysis
**Data pulled 2026-09-19 · all six campaigns with "Website" in the name**

| ID | Campaign | Launched | Leads |
|---|---|---|---|
| 3892258 | Website offer - HVAC - USA | 2 Sep | 2,409 |
| 3886379 | Website offer - Electric | 1 Sep | 625 |
| 3912149 | Website offer - HVAC - Europe - Eng | 7 Sep | 1,256 |
| 3950427 | Website offer - mixedICP - EU (roofers, medspas, remodelers) | 13 Sep | 1,957 |
| 3960357 | Website offer - HVAC - USA - Recycled | 15 Sep | 1,561 |
| 3960583 | Website offer - Solar - USA - Recycled | 15 Sep | 1,600 |

## Headline

9,408 emailed. 394 bounced. 66 human replies (0.73%). 34 said yes. **3 meetings booked.**

Roughly **3,100 emails per booked meeting.** That is the number to fix.

But the reply rate is not the bottleneck, and this is the finding that matters
most:

> **40 demo sites were sent. 26 leads went completely silent afterwards.
> 14 of those 26 actually visited the site we built them — several of them
> two or three times, some coming back more than a week later.**

They looked. They came back. They said nothing. And nothing in the system reacted
to that.

---

## 1. The real bottleneck is the demo hand-off, not the cold email

The funnel, all six campaigns:

| Stage | Count | Conversion |
|---|---|---|
| Delivered | 9,014 | — |
| Human replies | 66 | 0.73% |
| Non-negative replies | 37 | 56% of replies |
| **Demo sites built and sent** | **40** | — |
| Replied after receiving the demo | 14 | **35%** |
| Asked about price | 10 | 25% |
| **Meetings booked** | **3** | **7.5% of demos** |

Restricting to demos sent 5+ days ago, so recent ones do not drag it down:

| Cohort | Demos | Replied | Silent | Booked |
|---|---|---|---|---|
| Sent 5+ days ago (fair test) | 23 | 10 (43%) | **13 (57%)** | 3 (13%) |
| Sent in last 5 days | 17 | 4 | 13 | 0 |

Building a whole website is by far the most expensive thing in this funnel, and
**more than half of them land in silence.**

### They are looking. That is the point.

Demo-site visit tracking (`site_visits`, pushed from Vercel) against who replied:

| Lead | Category | Replied after demo? | Visits | Last visit |
|---|---|---|---|---|
| perfectbuilders.uk | Interested | **silent** | 3 | 15 Sep |
| aztecahvacpros.com | Lead Done | **silent** | 3 | 14 Sep |
| dcairandheating.com | Lead Done | **silent** | 3 | 10 Sep |
| freestatehvac.com | Interested | **silent** | 3 | 7 Sep |
| cosmosaclv.com | Interested | **silent** | 3 | 7 Sep |
| eastcountysolarcleaner.com | Interested | **silent** | 2 | 17 Sep |
| uniqueroofing... | Interested | **silent** | 2 | 17 Sep |
| leaking-roof.com | Interested | **silent** | 2 | 16 Sep |
| proflowhvacandplumbing.com | Interested | **silent** | 2 | 9 Sep |
| goldenoakalltrades.co.uk | Interested | **silent** | 1 | 18 Sep |
| ...and 4 more | | | | |

**Of those who replied after the demo: 11 of 14 have recorded visits.
Of those who went silent: 14 of 26 have recorded visits.**

Azteca opened the site three times, the last one ten days after it was sent, and
never wrote a word. Golden Oak visited yesterday. These are not cold leads. They
are warm leads with no mechanism pointed at them.

### Why they go quiet

Reading the threads, the demo hand-off email consistently:

- **asks for an opinion instead of asking for a meeting.** Every version ends with "Let me know what you think" or "Did you try the new AI Agent feature?" That is homework, and it has no calendar link attached to a reason.
- **sells features, not money.** "An AI agent on every page", "seven real service pages", "a guided estimate flow". None of that says *more booked jobs*.
- **leaves the ownership questions unanswered** until the prospect raises them. One did, in full:

> "1. What platform was the website built with? 2. **Do I receive full ownership of the source code?** 3. Can I edit the website myself without paying you for every content change? ... 7. **Are there any monthly hosting, software, licensing or maintenance fees?** 8. Who owns the domain, website code, images..."
> — Ed Kamhawy, United Heating and Cooling

That is the serious buyer's checklist, and it arrives *after* the silence. Most
prospects will not bother asking — they will just assume the worst and drop it.

### What to do — highest value on this page

1. **Trigger a follow-up off the visit signal.** The data is already in the database and is doing nothing. "Saw you had another look at the site — want me to walk you through it for ten minutes?" sent the day someone revisits is the warmest email in the whole business. **14 leads qualify right now.**
2. **Rewrite the demo email to ask for the call, not for feedback.** One specific ask, one calendar link, a reason to get on it ("fifteen minutes and I'll show you the AI agent taking a live call and give you an exact number").
3. **Put the FAQ on the demo page itself**: who owns it, can I edit it, what does it cost, what is monthly. Ed's eight questions are the script.
4. **Put a "Book a call" button on the demo site.** They are already on the page, twice.
5. **Lead the demo email with the outcome.** Not "an AI agent on every page" but "this answers the phone at 11pm when someone's AC just died, and books the job."

---

## 2. Which campaigns and verticals actually work

| Campaign | Delivered | Bounce | Replies | Positives | Booked |
|---|---|---|---|---|---|
| **mixedICP - EU** (roofers, medspas, remodelers) | 1,827 | **6.64%** | 23 — **1.26%** | 17 — **0.93%** | 0 |
| HVAC - USA | 2,367 | 1.74% | 21 — 0.89% | 9 — 0.38% | **3** |
| Electric | 611 | 2.24% | 6 — 0.98% | 1 — 0.16% | 0 |
| HVAC - Europe - Eng | 1,181 | 5.97% | 10 — 0.85% | 2 — 0.17% | 0 |
| Solar - USA - Recycled | 1,505 | **5.94%** | 4 — 0.27% | 3 — 0.20% | 0 |
| HVAC - USA - Recycled | 1,523 | 2.43% | 2 — 0.13% | 2 — 0.13% | 0 |

**mixedICP is the standout** — 2.4x the positive rate of HVAC USA, and 5-7x the
recycled lists. Inside it, the vertical breakdown is decisive:

| Vertical | n | Reply | Positive |
|---|---|---|---|
| **Building contractors** | 586 | **1.54%** | **1.37%** |
| **Roofing companies** | 826 | 1.33% | 0.97% |
| Med spas | 230 | 0.87% | 0.43% |
| Home renovators | 185 | 0.54% | 0.00% |

And at the finer ICP level, **UK builders hit 4.81% reply / 3.85% positive on 104
leads** — by a distance the best-performing segment in the entire account.

**The recycled lists are dead.** 0.27% and 0.13%. Re-mailing a burned list is
costing sender reputation for almost nothing. Stop.

### What to do
- **Double down on UK/EU building contractors and roofers.** That is where the demand is.
- **Drop home renovators and med spas** from the mixed ICP.
- **Stop the recycled campaigns.** They return nothing and cost reputation.
- HVAC USA is the only campaign that has booked anything — keep it, but it is a volume play, not an efficiency one.

---

## 3. Deliverability: bounce rate is the quiet problem

**Overall bounce is 4.19%.** Three campaigns are above 5%, which is the level at
which mailbox providers start treating you as a list-quality problem:

| Campaign | Bounce | |
|---|---|---|
| mixedICP - EU | **6.64%** | danger |
| HVAC - Europe - Eng | **5.97%** | danger |
| Solar - USA - Recycled | **5.94%** | danger |
| HVAC - USA - Recycled | 2.43% | |
| Electric | 2.24% | |
| HVAC - USA | 1.74% | fine |

Where the bounces actually come from:

| Recipient host | Leads | Bounce rate | Share of all bounces |
|---|---|---|---|
| Other / self-hosted | 1,697 | **9.90%** | 42.6% |
| Google Workspace | 3,495 | 2.03% | 18.0% |
| Security gateway | 588 | **10.71%** | 16.0% |
| **No mail server at all** | 55 | **72.73%** | 10.2% |
| Microsoft 365 | 2,727 | 1.39% | 9.6% |

**55 leads were emailed at domains with no MX record.** Those could never have
been delivered. Self-hosted and security-gateway domains together are 24% of the
list and produce 59% of the bounces.

The fix is already built. `mailbox_provider.resolve()` does MX lookups at roughly
200 per second and is currently only used *after the fact* for analysis. **Run it
as a pre-send list filter**: drop "no mail server", quarantine security gateways
and small self-hosted domains into a low-volume campaign. That alone takes the
account from 4.19% to comfortably under 3%.

The verified-email tier confirms it:

| Selection tier | n | Bounce | Reply | Booked |
|---|---|---|---|---|
| **A — site-confirmed email** | 2,283 | **1.51%** | 0.92% | **3** |
| B — pattern-guess email | 220 | 3.93% | 0.45% | 0 |

**All three bookings came from tier A.** Guessed emails bounce more, reply less,
and have booked nothing. Stop sending to them.

---

## 4. Google beats Microsoft, roughly 2 to 1

Pooled across all six campaigns:

| Recipient host | Share of list | Bounce | Replies | Positive rate | Booked |
|---|---|---|---|---|---|
| **Google Workspace / Gmail** | 38.0% (3,424) | 2.03% | 28 — **0.82%** | **0.50%** | **2** |
| Microsoft 365 / Outlook | 29.8% (2,689) | 1.39% | 12 — 0.45% | 0.19% | 0 |
| Other / self-hosted | 17.0% (1,529) | 9.90% | 15 — 0.98% | 0.52% | 1 |
| Security gateway | 5.8% (525) | 10.71% | 3 — 0.57% | **0.00%** | 0 |
| Hostinger | 3.2% (287) | 0.35% | 3 — 1.05% | 0.70% | 0 |

Microsoft is 30% of the list, produces 15% of the positives and **has never
booked a meeting.** Security gateways are 5.8% of the list, bounce at 10.7% and
have produced zero positives from 525 sends.

Unlike OneBodyLDN there is no sudden collapse here — Mindaptive's Microsoft
performance is uniformly weak rather than newly broken. Still worth splitting
Google and Microsoft into separate campaigns with separate domains, which is
exactly what the old "B2B Tech - Google" / "- Office" campaigns in this same
account did.

---

## 5. What the cold email itself should say

Pooled step-1 subject lines:

| Subject | n | Reply | Positive | Booked |
|---|---|---|---|---|
| **{companyNickname}'s fresh website is live** | 2,185 | **0.92%** | **0.50%** | **2** |
| your redesigned website is live | 1,481 | 0.88% | 0.41% | 0 |
| my weird hobby | 2,183 | 0.82% | 0.32% | 1 |
| I built {companyNickname} a fresh website this week | 674 | 0.59% | 0.59% | 0 |
| built you a website, no charge to look | 2,188 | 0.50% | 0.27% | 0 |

The intervals overlap, so treat this as leaning rather than proven — but the
pattern is consistent: **"it's live / it's done" beats "I built you one" beats "no
charge to look."** Stating it as finished and waiting outperforms framing it as a
free offer. The word "free" appears to attract less, not more.

### The trust problem is real and measurable

Mindaptive has literally had to add a follow-up that reads:

> "This might sound a bit odd... **but it is not scam.** I'm real person and literally did this for {company}."

And the negative replies confirm why:

> "I've never asked you to do anything for me mate what are you on about mate"
> "Looking forward for you to f off"
> "Stop embarrassing yourself"
> "Please make this your last email. We dont need anymore spam."

Against that, when it lands it *really* lands:

> "Well **that is the best cold email I've received in a long time.** If you truly rebuilt my website and not created your own from scratch I'd be interested in check it out"
> — Tom Eddleman, Owner, Climate HVAC Solutions

Tom then visited nothing and never replied again after the demo — which is the
whole problem in one thread.

**The credibility gap is between claim and proof.** Suggestion: put a screenshot
or a short screen-recording of the actual built site *in the first email*. The
claim "I built you a website" is unbelievable in text and self-evident in a
picture. It also removes a round trip from the funnel — right now the entire step
2 exists just to send a link.

---

## 6. Follow-ups earn 39% of replies — and the sequence is too short

| Step | Reached | Replies | Positives |
|---|---|---|---|
| 1 | 9,014 | 40 (0.44%) | 24 |
| 2 | 7,219 | 15 (0.21%) | 7 |
| 3 | 4,686 | 11 (0.23%) | 3 |

**39% of replies come from follow-ups**, and step 3 is still producing at the same
rate as step 2 — no exhaustion. Both bookings in HVAC USA came at steps 2 and 3.

The "scarcity" follow-ups genuinely work. "I'll take the site down in 48 hours"
and "This is my last email" pulled several of the best conversations in the
account, including two of the three bookings. But the scarcity is being spent on
the *cold* step, before anyone has seen anything. It would be worth far more
pointed at the 14 people who have already looked at their demo.

### What to do
- **Add steps 4 and 5.** Nothing suggests the sequence is used up at 3.
- **Move the takedown-deadline email into the post-demo sequence**, where it applies to someone who has actually seen the thing being taken away.

---

## 7. Meetings booked are being lost to scheduling friction

Three meetings booked. Two of the three had no-shows or timezone chaos:

> "I am in the call. But I think the booking came through as **4:30 AM your time**, probably a time zone mix-up."
> — to Mike, HVAC Doctors. He then no-showed twice and asked "what time zone are you in". Still unbooked.

> "I tried to call but **the number you placed on the WhatsApp has too many digits.** Do you have a different number?"
> — Russell Graham, Mid-City Heating

At three meetings total, losing one to a Calendly timezone default is a third of
the output.

### What to do
- Force the Calendly timezone to the prospect's, detected from their address or phone, and **state the time in their timezone in plain text** in the confirmation email.
- Give the US number (+1 718 550 4279) as the WhatsApp contact, not the Croatian one. "+385 97 766 9883" reads as an error to a US contractor.
- Send a reminder the morning of, and one an hour before.

---

## 8. Pricing is landing fine over email — stop avoiding it

The house rule is no pricing over email, but the record does not support it. Both
deals that advanced furthest did so *because* numbers were sent:

- **Diamond Heating** got a full tiered breakdown ($950 / $1,200 / $1,600 plus monthly) and stayed engaged, asking for more detail on tiers.
- **Cosytoes** got itemised pricing, took it to colleagues, and came back with a clear, honest no — "Your prices are much more than our current outgoings" — which is useful information, fast.
- **Volt N Vent** asked "what would the cost be?" and was told "the cost question is exactly what the call is for." **They never replied again.**

For a $950-$1,600 product sold to an owner-operator who is out on jobs all day, a
15-minute discovery call is a bigger ask than the price. Deflecting the price
question is costing conversations.

### What to do
- **Answer the price question in the email**, with a range and a simple two-option structure (own it outright vs. we run it), then ask for the call to confirm scope.
- Publish the tiers on the demo page so it is answered before it is asked.

---

## The seven things, ranked

1. **Fire a follow-up when someone revisits their demo site.** The data exists, 14 leads qualify today, and it is the warmest signal in the business.
2. **Rewrite the demo hand-off email**: ask for the call, lead with outcomes, attach the ownership/pricing FAQ, put a booking button on the demo page.
3. **Filter the list by MX before sending.** Kill "no mail server", quarantine security gateways. Takes bounce from 4.19% to under 3%.
4. **Send only tier-A verified emails.** All three bookings came from them.
5. **Refocus on UK/EU building contractors and roofers** — the best segment in the account by a distance. Kill the recycled campaigns and the home-renovator/med-spa slices.
6. **Answer pricing in writing** instead of deflecting to a call.
7. **Fix the scheduling friction**: timezone-correct Calendly, US WhatsApp number, same-day reminders. Add follow-up steps 4 and 5.
