# OneBodyLDN — campaign analysis
**Data pulled 2026-09-19 · campaigns "Direct Clients - First Campaign" (3876232) and "Direct Clients - Round 2 - 5-10min proximity" (3930675)**

## Headline

7,125 people emailed. 222 real replies (3.21%), 64 said yes (0.92%), **16 booked a session.**

That is a working campaign. The offer lands, the copy works, and half the
positives come from follow-ups. But three things are each costing more bookings
than any copy change would win back:

1. **Microsoft mailboxes stopped receiving us on ~4 September.** That is 57% of the list.
2. **The booking flow loses people who already said yes.** At least 8 of the 48 non-booked positives hit a broken code, a broken payment page, or a surprise fee.
3. **Nobody is being asked to bring their colleagues**, though 7 leads offered unprompted.

---

## 1. The Microsoft problem (biggest single issue)

Reply rate to Microsoft-hosted recipients, step 1, by day sent:

| Date | Campaign | Microsoft sent | reply % | Google sent | reply % |
|---|---|---|---|---|---|
| Aug 31 | C1 | 204 | **16.2%** | 42 | 23.8% |
| Sep 1 | C1 | 323 | **17.6%** | 96 | 13.5% |
| Sep 2 | C1 | 415 | 13.3% | 128 | 7.0% |
| Sep 3 | C1 | 303 | 11.6% | 87 | 12.6% |
| Sep 4 | C1 | 281 | 6.8% | 97 | 9.3% |
| Sep 7 | C1 | 128 | 2.3% | 108 | 10.2% |
| Sep 10 | C2 | 403 | **0.5%** | 212 | 9.9% |
| Sep 11 | C2 | 417 | 1.4% | 159 | 11.9% |
| Sep 14-18 | C2 | 1,479 | **0.3%** | 662 | 8.9% |

(all replies including autoresponders, which is why these run higher than the human-only rates elsewhere)

**Google is flat across the whole period. Microsoft fell off a cliff.** Same
sender, same copy, same days. Pooled over both campaigns:

| Recipient host | Share of list | Bounce | Human replies | Positive rate | Booked |
|---|---|---|---|---|---|
| Microsoft 365 / Outlook | **57.1%** (3,951) | 1.25% | 76 — **1.92%** | 0.76% | 5 |
| Google Workspace / Gmail | 22.9% (1,587) | 1.73% | 112 — **7.06%** | 1.58% | 9 |
| Security gateway (Mimecast/Proofpoint etc.) | 16.9% (1,168) | **8.96%** | 26 — 2.23% | 0.43% | 2 |
| Other / self-hosted | 3.0% (205) | 3.30% | 8 — 3.90% | 1.95% | 0 |

Within Campaign 1 alone, Microsoft replied at 3.93%. Within Campaign 2, 0.48%.
Google went the *other* way over the same fortnight — 6.14% to 7.55%. Copy cannot
explain a gap that only one mailbox provider sees.

**It is junk-foldering, not blocking.** Bounces to Microsoft stayed at 1.2%
throughout. Microsoft is accepting the mail and filing it in Junk — which is why
nothing looks broken inside Smartlead. One lead confirmed it in writing:

> "Thanks for chasing this up — **it ended up in my SPAM folder the first time**."
> — Chris Roberts, Sucden Financial (who then booked)

**Why it happened:** 21 sending domains, all on the same `onebody*` naming
pattern, registered together, every one sending 25/day. Microsoft correlates
domains by registration pattern and infrastructure and penalises them as a group.
Warmup reputation still reads 92-100%, but that measures the warmup pool, not
real inboxes — it will never warn you about this.

### What to do
- **Stop sending to Microsoft domains now.** Let the reputation decay out (3-4 weeks minimum).
- **Split campaigns by recipient provider.** Resolve the MX record before import and run Google and Microsoft as separate campaigns on separate sending domains. Andrew's own account already proved this works — the old "B2B Tech ... - Google" / "... - Office" split campaigns.
- **Stand up a fresh, separate domain set for Microsoft**: different registrar, different naming pattern, warmed 4+ weeks, capped at **10-15/day**, not 25.
- **Enrol in Microsoft SNDS and JMRP** so you get visibility instead of guessing.
- Meanwhile **Google is performing beautifully at 7.06%** — push volume there while Microsoft recovers.

---

## 2. Which message won

Six variants ran on the first campaign. Variants **E and F had identical bodies
and differed only in the subject line** — a clean test:

| Variant | Subject | n | Reply | Positive | Booked |
|---|---|---|---|---|---|
| **E** | **"you walk past us every day"** | 449 | **6.68%** | **2.23%** | 3 |
| F | "we are a {proximity} from your office" | 453 | 3.09% | 0.88% | 1 |

Identical words in the body. **More than double the replies from the subject line
alone.** Pooled across both campaigns:

| Subject line | n | Reply | Positive | Booked |
|---|---|---|---|---|
| **you walk past us every day** | 3,041 | **3.52%** | 0.95% | 8 |
| the benefit nobody uses | 448 | 3.35% | **1.56%** | 2 |
| we are a {proximity} from your office | 3,432 | 2.91% | 0.82% | 6 |

The winning body (variant E) is the short, concrete one:

> I noticed your London office is about {proximity} from our {nearest clinic} clinic. We've got 38 physio locations across London and we treat people from KPMG, Deloitte, and PwC. We fix backs, necks and shoulders. Mostly the kind people pick up from sitting at a desk eight hours a day.
>
> So here's what I'd like to do give you: a 55-minute session with an HCPC-registered physio, completely on me. Proper assessment plus hands-on treatment, not an exercise sheet.
>
> Want me to send the booking link over? It is completely on me.

**"the benefit nobody uses"** (the private-health-cover angle) deserves a proper
retest. It had the **highest positive rate of any variant** and only ran to 448
people. The insurance angle keeps appearing in replies as a buying signal, not an
objection.

### What to do
- Make **"you walk past us every day" plus variant E's body** the control.
- Retest **"the benefit nobody uses"** at 1,500+ as the challenger.
- Fix the typo in the winning body: *"here's what I'd like to do give you"*.

---

## 3. Who to target

**Industry — and this survives the provider problem.** Checked separately inside
each provider, so it is not just a deliverability artefact:

| Industry | n | Reply | Positive | Booked |
|---|---|---|---|---|
| Publishing | 144 | 6.94% | 1.39% | 0 |
| **Media Production** | 278 | **6.47%** | **2.88%** | 1 |
| Design | 123 | 5.69% | 1.63% | 1 |
| Venture Capital & PE | 129 | 5.43% | 0.78% | 1 |
| **Marketing & Advertising** | 570 | 5.09% | 1.40% | **3** |
| Staffing & Recruiting | 431 | 4.87% | 1.16% | 1 |
| Management Consulting | 316 | 3.48% | 1.27% | 0 |
| **IT & Services** | 1,385 | 3.10% | 1.16% | **5** |
| Financial Services | 667 | 2.55% | 1.35% | 3 |
| Insurance | 360 | 2.22% | 0.28% | 0 |

Inside Google alone: Media Production **12.12%**, Marketing 8.15%, against
Financial Services 3.52%. Inside Microsoft alone: Publishing 5.33%, Staffing
4.07%, against Financial Services 1.28%. **Creative, media and recruitment beat
finance and insurance on both providers.**

**Company size — 26 to 100 employees is the sweet spot.** In Campaign 1:
11-25 = 6.59%, 26-50 = 4.63%, 51-100 = 5.82%, **1000+ = 0.92%**.
Large corporates do not respond. Drop 1000+ entirely.

**Job titles.** Head of Finance (5.56%), Founder (4.05%), Head of Marketing
(3.81%), Partner (3.73%), COO (2.63%), CEO (2.61%). Dead: **Chief Financial
Officer 0.70%**, **Product Owner 0 out of 65**. Note the split — "Head of
Finance" works, "Chief Financial Officer" does not. Past a certain seniority it
stops working.

**Walking distance — the real story is subtler than it first looks.** The raw
numbers say close leads reply more, but that is confounded: Campaign 1 was the
0-4 min list and Campaign 2 was the 5-10 min list, so distance and the Microsoft
collapse move together. Checking **inside Google only**, where deliverability was
never affected:

| Walk time | n | Reply | Positive | Booked |
|---|---|---|---|---|
| 0-4 min | 562 | 6.58% | 1.78% | 5 |
| 5 min | 181 | 8.29% | 2.21% | 2 |
| 6-8 min | 493 | 7.10% | 2.03% | 2 |
| 9-10 min | 351 | 7.12% | **0.28%** | **0** |

**Distance does not change whether people reply — it changes whether they book.**
Up to 8 minutes everything holds. At 9-10 minutes the reply rate is unchanged but
positives collapse to near zero and nothing books at all. People will answer a
nice email from anywhere; they will only walk about eight minutes for a free
session.

### What to do
- Cap the radius at **8 minutes**. 9-10 minutes generates replies that never convert.
- Lead with **Media Production, Marketing & Advertising, Publishing, Design, Staffing, IT Services**.
- Target **26-100 employees**. Drop 1000+.
- Target **Head of / Founder / Partner / COO**. Skip CFO and Product Owner.

---

## 4. Why people who said yes did not book

64 positives. **16 booked. 48 did not.** This is where the money is, and it is not
a copy problem — it is a checkout problem.

**Counted across all 172 conversations** (unique leads, from their own words):

| Theme | Leads |
|---|---|
| Left the company / wrong person | **28** |
| Flat no | 24 |
| Out of office / annual leave | 22 |
| Active pain or injury mentioned (buying signal) | 10 |
| Insurance question (Bupa/AXA/Aviva/Cash Plan) | 8 |
| Too busy, later | 8 |
| **Offered to share with their team** | **7** |
| Works from home | 7 |
| **Confused by the £4.99 against "free"** | **6** |
| **Booking system broke on them** | **4** |
| Suspicious of "free" | 4 |
| Office moved | 3 |

### 4a. The booking system is losing sold customers

> "Sorry I give up. **Your payment system is atrocious.** It's really buggy, does not allow me to put my card expiry date in. If I can pay the £4 at your reception on Wednesday then you can book me in, otherwise I will give this a miss." ... "I gave up. **It would have been good publicity for you, I could have shared my experience with colleagues and my network.**"
> — Kofil Ali, Head of Desk, Sucden Financial

> "Not sure what I'm doing wrong but **the magic link always says it's expired** even if I click it 30 seconds after I've received it so I can't get past that stage to book."
> — Beth Denham, Cube

> "I've tried to book an appointment but **the code doesn't work**. Would you be able to book an appointment for the afternoon of Weds 23rd for me please?"
> — Amanda John, Partner, Gunnercooke

> "I tried to book but **the payment page is weird and it declined my card**."
> — Leopold, Tom & Co

Four people who were completely sold and were stopped at the door. Each was worth
a booked session and, as Kofil says himself, a referral network.

### 4b. "Free" then £4.99 reads as a bait and switch

> "Just trying to book now but **it's asking me to pay £4.99 online, is that expected?**" — Beth Denham
>
> "Thanks, Rebecca. **Your initial email indicated it was a free session?**" — Amanda John

The fee is defensible — it holds the slot and cuts no-shows. But discovering it at
checkout after five emails saying "completely on me" costs trust at the exact
moment of commitment.

### 4c. Several people asked us to just book it for them

Four leads explicitly asked OneBody to pick the time. Dean Forbes' EA wrote: "if
you could send over a few dates and times when you have availability." Nobody
took them up on it by simply making the booking.

### What to do, in order of value
1. **Fix the booking platform.** The expired-magic-link bug and the card-expiry field are costing confirmed sessions. This outranks every marketing change on this page.
2. **Say "£4.99 to hold your slot" in the email that hands over the code**, every time, before they click. The newer templates started doing this around 16 Sept — make it universal. Reframe it: *"There's a £4.99 deposit that holds your slot. It keeps no-shows down, which is how we can keep giving these away."*
3. **Offer to book it for them.** For anyone who says yes, reply with two concrete slots and make the booking. "Tuesday 2pm or Thursday 10am at Bank — say the word and I'll put it in." Self-serve is losing to a human.
4. **Chase the 48 unconverted positives now**, with the fee explained and an offer to book manually. Fastest win available — they already said yes.

---

## 5. The opportunity nobody has taken: teams

Seven leads offered, unprompted, to bring colleagues:

> "I'd be happy to **share it on our London office Slack channel**... There's about **30 in our London office**, so I'm sure a few people will be interested." — Alexander Timmons, Crowdcube
>
> "Does this apply to **other members of staff** at our company or just to me?" — Jason Bingham, CCO, Palmer
>
> "Can I also **share this with my coworkers**?" — Arjun Bains, GetAgent
>
> "I'd be happy to look at **getting the offer shared across the wider business**." — Layla Zghari, Emap
>
> "I'd be more than happy to **put you in touch with a few contacts**." — Joyce McCarthy, EC1 Partners

One reply can be thirty sessions. Right now the answer is a friendly "yes, share
the code" with nothing behind it.

**Build the team offer properly:** a one-pager, a company-specific code, a
per-company booking page, and an offer to run an on-site taster morning. This is
the HR/partnership campaign hiding inside the direct campaign, and the leads are
asking for it by name.

---

## 6. Follow-ups are doing half the work

| Step | Reached | Replies | Positives |
|---|---|---|---|
| 1 | 6,921 | 129 (1.86%) | 32 |
| 2 | 5,491 | 61 (1.11%) | 24 |
| 3 | 3,588 | 32 (0.89%) | 8 |

**42% of all replies and 50% of all positives came from a follow-up.** Step 2 is
almost as productive as step 1 for positives. Several bookings came from the
"This will be my last email" breakup — Andy Berg and Alexis Renaudin both replied
to that exact message.

The sequence stops at 3. **Add steps 4 and 5.** Step 3 is still returning 0.89%
with no sign of exhaustion, and the breakup email is a proven closer — it belongs
at step 5, not step 3.

---

## 7. Smaller findings

- **Rebecca Bossick outperforms Kurt Johnson.** Of her repliers 39% were positive, with **12 bookings**; Kurt's were 32% positive with 3. "Clinical Director" carries more weight than "Co-Founder" for a health offer. (Replies only — Smartlead does not expose sends per persona, so treat as directional.)
- **Security-gateway domains bounce at 8.96%** and account for 56% of all bounces while being 17% of the list. Resolve the MX before import and drop or quarantine them. The responder already does MX lookups at roughly 200/second.
- **28 leads had left the company.** The list is ageing. Re-verify before the next run.
- **Out-of-office is a scheduling signal, not a dead end** — 22 leads were on leave and several booked once chased on return. Read the return date and follow up then; the responder already extracts it.
- **No unsubscribes at all** across 7,125 sends. The offer is genuinely welcome. People are not annoyed by it.
- **Office moves cost nothing** thanks to 38 locations — three leads had moved and were saved by naming a nearer clinic. Keep doing that.

---

## The five things, ranked

1. **Fix Microsoft deliverability.** 57% of the list is going to Junk. Nothing else here is worth as much.
2. **Fix the booking checkout and state the £4.99 up front.** Sold customers are being lost at the door.
3. **Work the 48 positives who never booked** — offer to book it for them.
4. **Build the team/colleague offer.** Seven people asked for it.
5. **Retarget:** 8-minute radius, creative/media/recruitment, 26-100 employees, Head-of titles. Add follow-up steps 4 and 5.
