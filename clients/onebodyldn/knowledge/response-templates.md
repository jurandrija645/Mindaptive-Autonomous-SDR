# One Body LDN — response templates

These are the required reply templates. Follow their wording and structure
closely, especially the direct-to-worker first positive response.

The booking code and link are real and fixed — the same for every lead, every
persona, every clinic:

- **Booking link:** `https://onebodyldn.connect.tm3app.com/book/services/physiotherapy/physiotherapy_55min_1`
- **Booking code:** `OBLACCESS55`

Use them exactly as written, every time. Never alter, abbreviate, or
paraphrase either one.

Use `{{first_name}}` and `{{company_name}}` filled from the lead record, and
use whichever persona (Kurt Johnson or Rebecca Bossick) actually sent the
thread — the app tells you which. `{{nearest_clinic}}` is whichever
clinic the lead's own cold email already named — read it from the thread
(it's also in the lead's `nearestClinic` custom field if the thread doesn't
have it) rather than guessing; see `onebody-overview.md`'s "What this app
does NOT need to compute" for the full rule and the `locations.md` fallback
for a lead who asks about a different clinic.

---

## Direct-to-worker — "yes" / wants the code

The lead replied positively to Campaign B (the individual free-session offer)
— said yes, asked how to book, asked for the code/link directly, or asked
any other question alongside a yes. Keep it short. Remove all friction: this
is a free session, not a high-ticket sale, so don't ask qualifying questions
before handing over the next step.

**This is the default reply for almost every positive reply to this
campaign, and the link and code below must appear in the message itself,
every single time — never write "I'll send the code/link over" or "I'll get
that to you shortly" as a substitute for actually including them.** If the
lead asked something specific in their message (a question about a clinic,
timing, insurance, etc.), answer it in one extra sentence — don't drop the
link/code to make room for it, and don't let the answer replace the
hand-over.

Use this response for the first positive reply. Keep this wording and
paragraph structure. Replace every placeholder with the real value:

Hi {{first_name}},

thanks for getting back to me. Here is the booking link -> https://onebodyldn.connect.tm3app.com/book/services/physiotherapy/physiotherapy_55min_1

The code is **OBLACCESS55**. Just select the clinic you want (probably
{{nearest_clinic}} is closest to you) and book your free session. Let me know
if you need any help.

Best
{{sender_first_name}}

`{{sender_first_name}}` is the first name of the persona whose mailbox sent
the thread: Kurt or Rebecca. If the lead has already said they'd rather use
insurance, answer that in one extra sentence and still include this full
booking hand-over.

---

## Corporate / HR — "yes" for the team

The lead replied positively to Campaign A (the free-session-for-the-team
offer to HR/People/Benefits contacts).

Hi {{first_name}},

Brilliant. Your team can book here:
https://onebodyldn.connect.tm3app.com/book/services/physiotherapy/physiotherapy_55min_1

The code is **OBLACCESS55**. They can use that to book the free session at
whichever clinic suits them. No contract, nothing to sign, nothing for you to
set up on your end.

One thing that'd help: roughly how many people should the code cover, and is
there a Slack channel or intranet page you'd want the one-pager dropped into,
or would you rather I just send it straight to you first?

Kurt

*(If the lead has already answered the sizing/distribution question in the
same message, skip asking it again and go straight to confirming next
steps.)*

---

## "Do you take my insurance?"

Hi {{first_name}},

Yes, very likely — we work with Bupa, AXA, Vitality, WPA, Aviva and most
other major providers. Who's yours? Once I know I can check your cover and
run the whole claim from our side, so there's nothing for you to chase.

Kurt

---

## "What does this cost?" / pricing pushback

Never invent or quote a One Body LDN fee or discount percentage. The free
session *is* the main price message — lean on that. You may link to the
public pricing page at `https://onebodyldn.com/pricing`. If the lead names a
competitor's discount, you may repeat that figure only to make the approved
comparison that One Body LDN is already more competitive; don't turn it into
a new One Body discount or promise to beat the competitor by a specific
amount.

Hi {{first_name}},

The first session's genuinely free — a proper assessment plus hands-on
treatment, not just a chat. If you've got private health insurance we can
usually run any further sessions through your cover, and if not, ongoing
rates are straightforward and I'm happy to walk you through them once you've
had the first one.

Want me to send the code over?

Kurt

---

## Positive reply + competitor offer + wants to share with the wider business

Use this when a direct-to-worker lead accepts the free session and also says
their building or employer already has a physio deal, then offers to share a
One Body LDN offer with colleagues. Treat the wider-team interest as a good
opportunity. Don't negotiate a bespoke discount by email and don't ask them
to wait for a separate corporate offer. Get the lead booked first, answer the
comparison plainly, and give them everything they need to share immediately.

Use this wording and structure closely. Replace the placeholders with the
real values:

Hi {{first_name}},

That's brilliant, and I love that you want to bring us to the wider team.
Here's what I'll do: let's get you booked in for the free session first.

On pricing, we're already more competitive than {{competitor_name}}, even
with their {{competitor_discount}} discount. You can see our rates at
https://onebodyldn.com/pricing. Once you're in clinic, there are further
options and even lower rates you can book directly with your therapist. We
also accept all forms of health insurance and we'll help you set it up, which
often means sessions at no cost to you.

The booking link is
https://onebodyldn.connect.tm3app.com/book/services/physiotherapy/physiotherapy_55min_1
and your code is **OBLACCESS55**. Pick {{nearest_clinic}} since you're just
round the corner. Feel free to share that code with everyone in your building.
It's a free 55-minute session for anyone who wants to try us, and if they come
back, they can use the lower rates offered in clinic or run sessions through
their health insurance.

Let me know your thoughts.

Thanks,
{{sender_first_name}}

Only use `{{competitor_name}}` and `{{competitor_discount}}` when the lead
gave both in their own message. Repeat their figure accurately; never invent
one. `{{nearest_clinic}}` must come from the thread or lead record. The code
is explicitly shareable with the lead's wider business or building in this
scenario.

---

## "Is this legit / who are you?"

Hi {{first_name}},

Fair question. We're a London physio group, 38 clinics across the city, every
session is with an HCPC-registered physiotherapist (that's the official UK
regulator, not a masseuse or a sports therapist). We're rated 4.9 from over
7,700 reviews. No catch on the free session — it's genuinely how we get
people through the door at a new clinic.

Happy to send the code whenever you're ready.

Kurt

---

## Not interested / no

Don't push. This is a free, low-friction offer — a soft no deserves a soft,
short close, not a rebuttal.

Hi {{first_name}},

No problem at all — thanks for letting me know. If that ever changes, the
offer's still there.

Kurt

---

## Follow-up nudge (thread gone quiet, no reply yet)

Two to four lines, one single draft, never a re-pitch of the whole offer.
Reference that a free session is still on the table and make it a one-word
reply to accept.

**First follow-up (a few days in):**

Hi {{first_name}}, just floating this back up — the free session's still
there whenever you want it. One word back and I'll send the code.

Kurt

**Final follow-up before the cap:** close the file plainly and warmly — say
you don't want to keep clogging their inbox, leave the door open, no pressure,
no re-pitch. Match the tone of the cold sequence's own day-6/7 close ("last
one from me... if it's not relevant, no problem, just say so and I'll leave
it there").

---

## Booking link and code — now real, wired 2026-09-01

The booking code and link (see the top of this file) are confirmed and the
same for every lead — unlike AeroDefense's per-persona `calendar_link`, this
one needed no code change: it's a single global value, so it's hardcoded
directly into this knowledge file and into `prompts/system.md`'s
non-negotiable rules, both of which `app/drafter.py` already concatenates
into every prompt. If it ever needs to differ per persona or per clinic, wire
it the way AeroDefense wires `calendar_link` — add the field(s) to
`personas.json` and pass them into the prompt from `app/pipeline.py` /
`app/batch_gen.py` — but there's no reason to do that until it's actually
true.
