# Mindaptive — Solutions Catalog

This is the reference document for every solution the agency delivers: what each solution does, what problem it solves, how it works technically, and which niche from the 90-day roadmap it's built for. Use this for writing offers, discovery calls, and onboarding.

Organized by the RACE framework (Reach, Acquire, Convert, Expand). We do not do paid ads or organic content/social management — we are not a marketing agency. Our Reach work is limited to AI-automated outbound campaigns.

---

## REACH

### 1. AI-Automated Outbound Campaigns (Cold Email + Multi-Channel)

**Problem it solves:** A B2B/tech firm, or any business that needs more qualified meetings, doesn't have enough people in its pipeline and doesn't have the time or team to run cold outreach manually.

**How it works:** Mindaptive runs the entire cold outreach process for the client — sourcing/scraping leads (scraPEAR), AI-generated icebreakers and personalization, campaign sending, response qualification, and booking meetings directly into the client's calendar. Can extend beyond email to cold LinkedIn outreach or AI voice/SMS outbound calling where relevant.

**Who it's for:** B2B/tech firms selling into trades, clinics, or local services (not installer/clinic owners directly — that's the inbound products below). Paid on outcome (per booked meeting or qualified reply), not a fixed retainer. This is Mindaptive's own proven acquisition model, applied to clients who need the same thing.

---

## ACQUIRE

### 2. AI Voice Receptionist (Voice Agent)

**Problem it solves:** The business misses phone calls when staff are busy, outside business hours, or in the evening/on weekends. Every missed call is a potential lost job — the caller just calls the next business on the Google list.

**How it works:** An AI agent (built on Vapi, with ElevenLabs voice and Deepgram transcription) answers inbound calls like a real employee. It asks the same qualifying questions a human would (urgency, service type, location, availability), and at the end of the call either books directly into the calendar or forwards a summary to the team for follow-up.

**Who it's for:** Veterinarians (emergency calls evenings/weekends), dentists (urgent appointments), potentially med spas (if they want a voice component alongside text).

**Technical note:** Training on specific language and terminology takes ~2 weeks per client (knowledge of services, pricing, typical questions). Not plug-and-play on day one — this is communicated transparently to the client.

### 3. WhatsApp AI Chatbot

**Problem it solves:** Inquiries come in on WhatsApp all day (especially in the EU market where WhatsApp is the dominant communication channel), but they get answered slowly or never if there's no staff monitoring messages.

**How it works:** An AI agent (Claude API + n8n automation) carries the conversation on WhatsApp, answers common questions, qualifies the inquiry, and books an appointment or forwards the contact to the team. Works in the client's language (Croatian, German, English, etc.).

**Who it's for:** All niches — especially strong fit for med spas (treatment inquiries) and real estate (property inquiries).

### 4. Website Chat Widget

**Problem it solves:** A website visitor has a question or is ready to book, but there's no one to answer immediately — the visitor gives up and goes to another site.

**How it works:** A chat widget on the website/contact page, powered by the same AI agent as WhatsApp/voice, catches the visitor at peak intent and guides them to booking or leaving contact info.

**Who it's for:** All niches, especially useful when the client already has good web traffic but is losing conversion.

### 5. Missed-Call Text-Back

**Problem it solves:** Same as the Voice Receptionist, but cheaper and simpler to deliver — when a call goes unanswered, the system automatically sends a text: "We saw you called, how can we help?" instead of letting the call drop into voicemail.

**How it works:** An automation (n8n) triggers on the missed-call event from the phone system and sends a personalized SMS/WhatsApp message immediately.

**Who it's for:** A good frontend/entry option for niches where we want a lower price point and more reliable delivery than a full voice agent (lower risk of something going wrong, since there's no live conversation the AI has to carry).

### 6. Speed-to-Lead / Instant Response System

**Problem it solves:** A lead fills out a website form or an inquiry comes in through an ad (Meta/Google), but the business responds hours or days later — by then the lead has already gone to a competitor or lost interest.

**How it works:** An automation that catches the new inquiry (form submission, new CRM row, new email) and sends a personalized response (email/SMS/WhatsApp) within minutes, plus, where possible, a direct booking link.

**Who it's for:** Med spas (ghosted consultation inquiries), real estate (property inquiries) — really a core product for every niche because it's the fastest and cheapest automation to deliver.

### 7. Automated Review Generation System

**Problem it solves:** A business has few or no reviews (or reviews that are old/sparse), which hurts trust and conversion at the exact moment a prospect is comparing options on Google.

**How it works:** An automated sequence (SMS/WhatsApp/email) triggers after a completed job or appointment, asking the customer for a review and sending a direct link to the relevant platform (Google, Facebook, industry-specific directories). Can route unhappy customers to a private feedback form instead of a public review, to protect the rating.

**Who it's for:** Any business with weak review signal on Google/their site relative to competitors. Works well as a standalone offer or as an add-on to any other module — review count and recency is one of the fastest, cheapest trust signals to fix.

---

## CONVERT

### 8. Booking/Calendar Integration

**Problem it solves:** Even when the client (lead) wants to book, the process is hard — back-and-forth calls, email exchanges. Every extra step in the process loses a percentage of people.

**How it works:** Direct integration of the AI agent (voice/chat/WhatsApp) with the client's calendar (Google Calendar, Calendly, or a native PMS system if one exists) — the appointment is booked immediately within the conversation, no back-and-forth.

**Who it's for:** Part of every package above, not a standalone product.

### 9. Nurture / Follow-Up Sequence (Ghosted Leads, No-Show Recovery)

**Problem it solves:** A lead showed interest (filled out a form, booked a consultation) but never showed up or never completed the purchase — and the business simply writes them off instead of continuing contact.

**How it works:** An automated sequence of messages (email/SMS/WhatsApp) over 1-3 weeks that reminds, offers additional value, or asks why the deal didn't happen — the goal is to bring some of these "dead" leads back into the pipeline.

**Who it's for:** Med spas (ghosted consultations), dentists/vets (no-show appointments).

### 10. Sales Follow-Up & Quote Automation

**Problem it solves:** A quote or proposal goes out, and then nothing — the sales rep either forgets to follow up or doesn't have a system for chasing it, and deals stall in limbo instead of closing or dying cleanly.

**How it works:** An automated sequence tied to the quote/proposal stage in the CRM — reminders to the prospect, automatic escalation to a human rep when a reply comes in, and a scripted cadence (interest check, urgency, direct yes/no) if the prospect goes quiet.

**Who it's for:** Larger B2B clients or higher-ticket sales processes where a quote sits for days/weeks before a decision — less relevant for low-ticket, fast-decision inbound niches.

---

## EXPAND

### 11. No-Show Reduction / Automated Reminder Sequence

**Problem it solves:** The business is fully booked, but loses revenue on no-show appointments — the slot is held in the calendar, but the customer doesn't show, and that slot can no longer be filled. For a practice already at capacity, this is a pure loss with no upside.

**How it works:** An automated reminder sequence (SMS/WhatsApp/email) before the appointment, with a one-tap/one-reply confirmation option. If the client doesn't confirm within a set window, the system automatically releases the slot and triggers module 12 (Waitlist Backfill).

**Who it's for:** Any niche with scheduled appointments where fill rate is already high — physiotherapists, clinics, veterinarians already close to capacity. Especially relevant for leads who reject the standard offer with "we're full" — this doesn't add new inquiries, it just protects the existing calendar.

### 12. Waitlist / Cancellation Backfill

**Problem it solves:** A client cancels last-minute, and that slot stays empty unless someone manually calls down the waitlist — which rarely happens fast enough to fill the slot the same day.

**How it works:** When an appointment is cancelled (or a no-show is confirmed via module 11), the automation (n8n) immediately contacts the waitlist in priority order (SMS/WhatsApp) until the slot is filled. The business doesn't have to do anything manually — it just gets notified once it's filled.

**Who it's for:** Businesses that have explicitly said they don't want to grow their inquiry list, but have a problem with empty slots after cancellations. This is a direct answer to the "we're full, we don't want a bigger waitlist" objection — it fixes revenue leakage without adding new volume.

### 13. Intelligent Overflow Triage / Referral Routing

**Problem it solves:** A business at capacity still receives inquiries it can't take on, and the owner/staff spends time manually declining or redirecting each one (a manual "we're full" reply).

**How it works:** An AI agent (chat/WhatsApp/email) automatically triages the incoming inquiry: if there's spare capacity (e.g. a different service, a different client type), it books immediately; if not, it adds them to a waitlist or redirects them to a partner/external resource — all without manual intervention. The business only gets the inquiries that actually require its decision.

**Who it's for:** Solo practitioners or small practices that manually reply to every inquiry with the same standard message (see example: Impeccable Behaviour, Penny Ashby) — this automates that manual work without increasing the number of clients the business has to take on.

### 14. Reactivation / Win-Back Campaigns

**Problem it solves:** A business has a base of past customers who haven't returned in months or years, and no systematic way of bringing them back — the revenue sitting in the existing customer list goes untouched.

**How it works:** A segmented outbound sequence (email/SMS/WhatsApp) to past customers who've gone quiet, offering a reason to come back (seasonal reminder, new service, limited-time offer). Can be triggered on a time-since-last-visit basis pulled from the CRM.

**Who it's for:** Clients with an existing customer base and a CRM/booking history to mine — dental, med spa, vet, any recurring-service business with a natural revisit cycle (cleanings, check-ups, maintenance).

### 15. Upsell / Cross-Sell Automation

**Problem it solves:** A business is at or near capacity but isn't maximizing revenue per client — it has room to sell more to the customers it already has, but no system prompts that conversation at the right moment.

**How it works:** An automated sequence tied to a completed booking or purchase that suggests a relevant next service, membership, or package upgrade, timed to the client's service cycle (e.g. post-treatment offer, membership renewal nudge).

**Who it's for:** Clients where "more leads" isn't the constraint — capacity or willingness to grow inbound volume is limited, but there's real headroom in revenue per existing client.

---

## Packages by Niche (90-Day Roadmap)

**Med Spa**
Focus problem: Inquiries (web form, Meta ads, Instagram DM) go unanswered for hours, and ghosted consultations aren't followed up.
Package: Speed-to-Lead (#6) + Nurture Sequence for ghosted consultations (#9) + WhatsApp Chatbot (#3) for ongoing inquiries.
Frontend price: €1,500-2,000 setup.

**Veterinarians**
Focus problem: Emergency calls evenings/weekends when the clinic is closed, and missed calls during the day.
Package: AI Voice Receptionist (#2) focused on after-hours + overflow, with booking integration.
Frontend price: €1,500-2,000 setup.

**Dentists**
Focus problem: No-show appointments and slow booking of urgent appointments.
Package: AI Voice Receptionist (#2) + Missed-Call Text-Back (#5) as a lighter alternative where the client doesn't want full voice.
Frontend price: €1,500-2,000 setup. Treat as a test niche (most saturated with competition).

**Physio (new niche, mentioned in email conversations)**
Focus problem: Acute injury on a weekend/evening, patient can't reach anyone until Monday and goes elsewhere.
Package: Missed-Call Text-Back (#5) + Speed-to-Lead (#6), voice as an upgrade option.

**Real Estate**
Focus problem: Property inquiries go unanswered while the agent isn't at their desk; the lead goes to another agent/agency.
Package: Speed-to-Lead (#6) + WhatsApp Chatbot (#3).

**B2B Outbound (proven model, separate track)**
Package: #1 standalone — not inbound automation, but a service Mindaptive delivers manually/semi-automatically.

**"Full Capacity" (situational, not a vertical)**
Focus problem: The business is at capacity and explicitly doesn't want more inquiries, but is losing revenue on no-shows/cancellations, or spending time manually triaging inquiries it can't take.
Package: No-Show Reduction (#11) + Waitlist Backfill (#12), with Overflow Triage (#13) as an option for solo practitioners doing manual triage.
When to use: When a lead responds with "we're full" / "we don't want a bigger waitlist" — this is the alternative offer instead of the standard Acquire pitch.

---

## Retainer — What's Included (All Niches)

The retainer (€500-800/mo) is not "hosting" — it includes: monthly monitoring of conversations/performance, one improvement or new micro-workflow per month, and support if the AI doesn't know how to answer something new (adding it to training). This justifies the price and reduces the risk of a poorly-trained agent actively causing damage (as in the example where booking rate dropped due to an under-trained AI).

---

## Note on Sales Sequencing (Frontend → Upsell)

For all inbound niches: sell ONE simple solution as the frontend (usually Speed-to-Lead or Missed-Call Text-Back, since they're the most reliable to deliver), and add Voice/WhatsApp/Nurture as an upsell once the client sees initial results and trusts the agency. Don't sell all modules at once in the first offer — that's too expensive and too big an "ask" for a cold prospect.
