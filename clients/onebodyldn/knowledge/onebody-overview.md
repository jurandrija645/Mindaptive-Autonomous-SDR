# One Body LDN — company reference

Everything you're allowed to claim about the company comes from this file. If a
lead asks something that isn't answered here, say you'll check and offer to
follow up — do not extrapolate or invent a number, review count, insurer name or
clinical claim.

Source: `source-docs/Typeform - Results Table.pdf` (Kurt Johnson's own answers,
submitted 2026-08-03) and `source-docs/One Body LDN — Cold Email Campaigns
(Draft 2).docx` (the cold outreach this app is replying to).

## What One Body LDN is

A private physiotherapy clinic group with **38 locations across London**
(the full list is in `locations.md`), each hosted inside an existing gym,
serviced office or fitness studio near where people already work. Every
treatment is delivered by an **HCPC-registered physiotherapist** — never a
sports therapist or unregulated practitioner — combining hands-on manual
treatment with personalised rehabilitation, not a generic printed exercise
sheet.

## The two ideal clients

1. **Corporate London professionals** — finance, law, architecture, tech,
   consulting, admin. Commute into a central London office, have private
   health insurance or workplace wellbeing benefits (or enough disposable
   income to self-fund), and want treatment that fits around work: nearby
   clinic, fast appointment, easy online booking.
2. **Post-operative rehab clients** — recovering from orthopaedic surgery
   (ACL, rotator cuff, joint replacement, spinal surgery, fracture repair),
   need structured longer-term rehab, motivated to follow a programme.

## The offer this app is replying to

Two live cold-email campaigns (see `response-templates.md` for the actual
copy the leads already received):

- **Campaign A — HR / Partnership.** Sent to Heads of People, HR Directors,
  Benefits/Wellbeing Managers. The ask: a free 55-minute physio session
  (proper assessment plus hands-on treatment) for **every person on their
  team**, at no cost to the employer, no contract, nothing to integrate —
  just a code and a one-pager they can share internally (e.g. on Slack).
- **Campaign B — direct to office workers.** Sent to individual professionals
  near a clinic. The ask: reply and get a **free 55-minute session**,
  hands-on treatment included. If they have private health insurance
  (Bupa, AXA, Vitality, WPA, Aviva or another insurer), the pitch adds that
  it's very likely already covered and One Body LDN runs the whole insurance
  claim for them, start to finish, so nothing lands back on the lead's desk.

Both campaigns are new — the first replies from these sequences are what
you'll be drafting. There's no accumulated back-catalogue of "how we usually
answer this" yet, so lean on this file and the templates rather than assuming
prior convention.

## Why someone should trust this over a competitor

- **NPS of +79** ("world class"), from a structured analysis of 4,859 client
  survey responses collected Jan–Jun 2026 — well above the private healthcare
  industry average of +30 to +50.
- **7,764 reviews at a 4.9 average.**
- Client testimonials and case studies (chronic sciatica, neck pain and
  headaches, tibial fracture rehab, knee injury/spinal fracture, hip
  flexor/Achilles rehab, reverse shoulder replacement rehab, thoracic
  spine/sciatica for an athlete, shin splints) are published at
  `onebodyldn.com/about-us/client-testimonials`. You may reference that page
  exists and what kind of cases it covers; don't quote a specific figure from
  an individual case study unless it's in this file.
- **What competitors get wrong:** the industry has drifted toward
  exercise-only physio — generic printed programmes, or sports therapists
  doing work that should be done by a registered physiotherapist. Every
  One Body LDN session is hands-on and delivered by an HCPC-registered
  physio. Competitors also tend to make insurance hard to use; One Body LDN
  activates and manages the client's cover end-to-end, including booking
  insured appointments online.
- **Same-day / same-week appointments** — no long NHS-style wait.
- Multiple central London locations and extended hours, so treatment fits
  around a working day.

## Insurance — what you can say

One Body LDN accepts and actively manages claims with **Bupa, AXA, Vitality,
WPA, Aviva and other major private health insurers**. If a lead has cover
through their employer or personally, tell them we run the claim process from
start to finish — they don't handle the paperwork. If they don't know whether
physio is included in their cover, say most people don't realise it is, and
offer to check for them once they confirm their insurer.

## Pricing — what you can and can't say

**Never state an exact fee, price, or discount percentage in an email.** The
things you're allowed to say plainly, because they're the offer itself, not a
disclosed price:

- The first session offered in the cold email is **free** (a 55-minute
  session with hands-on treatment, or a free 25-minute assessment, depending
  on which variant the lead received — check the thread for what was
  actually promised).
- If a lead has no insurance and needs more sessions beyond the free one,
  ongoing in-clinic rates are available and are cheaper when booked directly
  with the treating therapist — but don't quote a number. Say pricing is
  straightforward and offer to have it confirmed with the booking code, or
  point them to the insurance route if they have cover.
- If a lead has insurance, reinforce that sessions are typically at no cost
  to them once their claim is set up — again, without quoting a currency
  figure.

## Booking code / booking link — placeholder, needs a real value

The cold emails promise "a code" and, in the direct-to-worker campaign, a
"book here today" link. **Neither a real discount-code format nor a real
booking URL has been supplied yet.** Until Andrew fills these in (see
`response-templates.md`), do not invent one:

- If asked for the code or booking link and you don't have a real value from
  the thread or prior research, say it's coming right over / confirm the
  clinic first, and let Andrew fill in the actual code before send — don't
  write a fake code or guess a URL like `onebodyldn.com/book`.

## Sender personas

Cold outreach and replies go out under two names — **Kurt Johnson**
(co-founder) and **Rebecca Bossick**. Sign off using whichever persona's
mailbox the thread is actually running on (the app tells you which one).

## Common objections and how to answer them

- **"Is this legit / who are you?"** — Point to the review count and NPS,
  and that every physio is HCPC-registered (the UK's statutory regulator for
  physiotherapists) — not a masseuse or unregulated therapist.
- **"What's the catch?"** — There isn't one beyond the obvious: it's a way
  for a new clinic to get people through the door. No contract, nothing to
  sign, no obligation to book again after the first session.
- **"I don't think I need physio."** — Don't push a medical claim. Ask what's
  bothering them (desk-related back/neck/shoulder pain is the common case)
  and reframe the free session as a low-effort way to find out, not a
  commitment.
- **"Do you take my insurer?"** — Confirm which of Bupa/AXA/Vitality/WPA/
  Aviva they have (or ask if unsure), and say we'll handle the claim.
- **Silence / no reply** — see the follow-up guidance in `prompts/system.md`.

## What this app does NOT need to compute

`{icebreaker}`, `{walkTime}`, `{nearestStation}` and the geocoded
`{nearestClinic}` value in the cold-email templates are generated by the
separate outreach tooling that built the campaign, not by this responder. By
the time a lead replies, the thread already contains whichever clinic was
named in the email they got — read it from there rather than recomputing it.
If a lead asks about a clinic that wasn't already named (e.g. "is there one
nearer to X"), use `locations.md` to find the closest match by area name.
