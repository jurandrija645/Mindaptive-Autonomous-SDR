# One Body LDN — current partnership booking options

Updated 2026-10-29 with Kurt's clinic exclusions relayed by Andrew.
Other offer terms retain the 2026-10-28 updates below; original briefing:
Internal source: https://www.loom.com/share/d32795e804ec49a6b1cff5722392bca3
The Loom is an operator briefing, not a video to send to leads.

This file is the source of truth for current offer durations, booking links,
location restrictions and code validity. It supersedes older campaign copy,
past messages and old research on these points. Read the thread to understand
what was promised, but use these current booking rules in new replies.

## Use partnership links exclusively

**Mia, 2026-11-11: clearly tell recipients to select the clinic they want from
the list on the booking page before choosing a time.** If recommending a clinic,
say to select that clinic on the page; when no clinic is agreed, ask them to
choose the eligible clinic that suits them. Naming a clinic without telling
them to select it is not sufficient. For 45-minute massage, remind them to
choose from the eligible clinics on that specific booking page. Apply this to
people booking from the brochure as well. Never override a corrected or
rejected clinic or claim a particular slot is available.

All offer bookings must use the relevant link below. Do not send normal
website booking links or the old `/book/services/` link, even for a lead who
received it before. Do not use the public pricing page as a booking link.

| Appointment | Availability | Exact booking link |
| --- | --- | --- |
| Physiotherapy assessment and treatment, 45 minutes | All locations except the five below | https://onebodyldn.connect.tm3app.com/book/partnerships/physiotherapy_1/physiotherapy_assessment_treatment_45_min |
| Sports massage, 20 minutes | All locations except the five below | https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_20_min |
| Sports massage, 45 minutes | Only the nine priority locations below | https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_45_min |

## Fenchurch Street is closed

Kurt, 2026-11-02: Fenchurch Street has **closed**; it moved urgently to
Marble Arch. Unlike the five below this is permanent, so you may say it has
closed. Never offer, book or confirm it, even when the cold email or
`nearestClinic` named it. Point the lead to **Aldgate East** or **Monument**
(Kurt's own suggestion), then Liverpool Street or City of London for physio 45
and massage 20. For sports massage 45 use Aldgate East, then Moorgate (the
only priority clinics nearby). Do not give a walk time. Marble Arch: do not
offer it until its address and booking-link status are confirmed here.

Holborn moves in the week of 2026-11-09 to c/o The Gym Group London Bloomsbury,
Coram St, WC1N 1HB, about 0.8 km north-west of the old address. Same clinic
name and booking link. Give the new address for appointments from 9 November.

## Clinics where the free session is not offered

Kurt, 2026-10-29: **Twickenham, Battersea, Chiswick, Finsbury Park and
Vauxhall** are fully booked. He removed them from all three partnership links
on purpose. Never offer, book or confirm a free session at these clinics, and
never name one as the lead's clinic in a booking handover, even if the cold
email or `nearestClinic` named it. This also overrides a previously agreed
clinic, prior research and legacy-code offers. These clinics have not been
declared closed; do not promise when free sessions will return.

When a lead's clinic is one of these five, say briefly that it is fully booked
at the moment and offer the nearest clinic on the link instead:

| Not offered | Physio 45 / massage 20 alternatives | Massage 45 alternatives |
| --- | --- | --- |
| Twickenham | Fulham or Southfields (effectively tied), then Hammersmith; favour Southfields when equally convenient | Southfields, then Wimbledon |
| Battersea | Victoria, then Clapham or Waterloo | Waterloo, then High Street Kensington |
| Chiswick | Hammersmith, then West Kensington | West Kensington, then High Street Kensington |
| Finsbury Park | Islington, then Camden | Moorgate, then Aldgate East |
| Vauxhall | Victoria, then Elephant and Castle or Waterloo | Waterloo, then Moorgate |

Distances are straight-line, not travel time. Respect a lead's own preference
over this table, within current offer eligibility. See `clinic-routing.md`
for postcodes, approximate distances, backups and source evidence. These
are nearby eligible suggestions, not verified live appointment slots.
Do not change the offer type/duration or treat a replacement as agreed.

The pasted source ran the next label (`Sports Massage`) into the physio URL.
The physio URL ends at `_45_min`; `Sports` is not part of the URL.

Match the appointment to the lead's request. For a physio campaign's simple
positive reply, use the 45-minute physio link.

The two "Priority Clinics" campaigns (Smartlead 4235278 and 4235286, from
26 October 2026) offer each lead either physio or a 45-minute sports massage
at a priority clinic; the lead's `offer` custom field and the opening email
say which. A simple positive reply gets the link for the offer that email
made: `massage` → the 45-minute sports massage link, `physio` → the 45-minute
physio link. 307 leads in these campaigns got an opening email naming
Twickenham before Kurt took it off the links. On 2026-10-29 their
`nearestClinic` field was changed in Smartlead to Southfields, West Kensington
or Wimbledon (nearest priority clinic to their office), so later follow-ups
name that clinic. If the thread mentions Twickenham, say it is fully booked
right now and offer the clinic now in `nearestClinic`; do not quote a walk
time to it. Per Andrew's
28 October update, include the £4.99 booking fee with either offer.
Send the matching massage link
when massage is requested; do not silently substitute massage for physio.
If the lead wants 45-minute massage at an otherwise eligible location outside
the priority list, offer 20-minute massage there or 45-minute massage at a listed clinic that suits
them. Do not claim 45-minute massage is available at every clinic.

The "Nearest Clinic - Walk 15min - 18 Nov" campaign (Smartlead 4649171, from
18 November 2026) names the lead's nearest clinic, which is usually NOT a
priority clinic. Its `offer` custom field is `physio` or `massage20`:
`physio` → the 45-minute physio link (with the £4.99 fee line);
`massage20` → the 20-minute sports massage link. Never send these leads the
45-minute massage link unless they ask for it and accept a priority clinic.
Step 4 of this campaign asks whether a colleague would use the offer; if the
lead replies with a colleague's name or asks to pass it on, send the link and
`VIP8401` with the share line so they can forward it.

## Priority locations

Bookings are wanted across the eligible network. Prioritise these quieter
locations when they suit the lead, and action interest in them promptly:

- Wimbledon
- Aldgate East
- Hendon
- High Street Kensington
- Mill Hill
- Moorgate
- Southfields
- Waterloo
- West Kensington

Twickenham was on Kurt's original list of ten but is now fully booked and not
offered (see above).

These nine locations are the full eligibility list for 45-minute sports
massage. Physio 45 minutes and sports massage 20 minutes remain available
across all locations except the five not offered. Respect a lead's preferred area and clinic; do not
send them to an inconvenient clinic just to fill a quiet location. The list
does not confirm an address or a live appointment slot. Use `locations.md`
for known addresses; do not invent missing addresses or availability.

## Codes and the previous offer

Kurt confirmed on 2026-10-21 that **`VIP8401` works on all three offers**:
45-minute physiotherapy assessment and treatment, 20-minute sports massage,
and 45-minute sports massage at the nine eligible clinics. Include `VIP8401`
with the relevant partnership link in booking handovers. Codes are no longer
pending. The location restrictions above still apply.

**Direct mail, Waterloo, from 2026-11-09.** Printed pieces do not use
`VIP8401`. `WATERLOOWORK` is the office pack (letter, poster, cards, and the
follow-up email). `WATERLOOHOME` is the resident leaflet. Kurt says both are
live on the partnership links. If a reply quotes either code, book with that
code and the three links above, at Waterloo. Do not swap in `VIP8401`. Same
one-session rule and the same booking-fee line as every other handover.

**One person may claim only one of the three free offers, once in total.**
This is not one use per offer, clinic, booking or email address. A person
cannot claim physio and then claim either massage offer as another free
session. Do not suggest that switching email addresses resets eligibility,
or that switching codes (including the old code) grants another free session.

Andrew updated the lead-facing wording on 2026-10-28. Do not include
warnings about charges for repeat bookings or using another email address.
Keep the eligibility rule above internally, and include one invitation to
share the attached brochure with every booking/code handover. The brochure
already contains the link and code; don't add a separate sharing invitation.
For example:

> Feel free to share the attached brochure with your colleagues at {{company_name}}. Each person gets one free session.

For later handovers in the same thread, rephrase it briefly while retaining
that each colleague gets one free session.

Fill {{company_name}} with the actual company from the lead record or the
latest thread/signature. A correction in the conversation outranks imported
data. If it cannot be established, say "each person on your team"; never
invent a company or leave braces in the draft. Keep the personalized message
in every physio or massage booking/code handover, including shortened replies.

For HR/team offers, each colleague has their own single free-offer allowance;
it is not one redemption for the whole company. If directly asked about
repeat eligibility, explain the one-session-per-person limit without a
charge warning. Do not invent any charge amount or collection method.

**Mia confirmed on 2026-11-03 that the old `OBLACCESS55` code no longer
exists.** Treat `OBLACESS55` as a misspelling of the same retired code.
Never offer either spelling, claim the old code still works, or return to
the old `/book/services/` URLs. Use **`VIP8401`** and the matching partnership
link above for every new booking handover, even when the thread contains
the old offer. The previous 55-minute session is historical; current physio
is 45 minutes. Keep historical messages and booking-attribution records
unchanged; they are evidence, not instructions for the next email.

Andrew's explicit update on 2026-10-28 requires the booking-fee disclosure
for ALL three offers, including 20- and 45-minute sports massage:
"There's a small £4.99 booking fee that holds your time slot."
Include it whenever giving the booking link or code, even when shortening.
This supersedes the earlier instruction that massage booking fees were
unconfirmed. Do not describe it as the price of treatment or invent refunds,
deductions or waivers.

## Clinic corrections and automated follow-ups

Current clinic exclusions above override historical clinic choices. Among
eligible clinics, the latest conversation wins over the opening email and
`nearestClinic`.
If a lead rejects a clinic, never mention it as their clinic again. When
several alternatives have been offered without a choice, say "the clinic
that suits you". Smartlead's automated subsequences must use that generic
wording rather than `{{nearestClinic}}`: they cannot read the latest thread.
