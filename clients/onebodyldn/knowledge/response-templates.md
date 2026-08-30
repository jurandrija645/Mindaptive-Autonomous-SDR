# One Body LDN — response templates

These campaigns are brand new — there is no history of real replies yet, so
these templates are a first draft, not a backlog of copy that's already been
approved and sent. Andrew should read and adjust these before the first real
reply goes out, same as he would tune any new template from the modal.

Two placeholders are **not yet real values** — see the "Not filled in yet"
note at the bottom before using either template for a real send.

Use `{{first_name}}` and `{{company_name}}` filled from the lead record, and
sign off with whichever persona (Kurt Johnson or Rebecca Bossick) actually
sent the thread — the app tells you which.

---

## Direct-to-worker — "yes" / wants the code

The lead replied positively to Campaign B (the individual free-session offer)
— said yes, asked how to book, or asked for the code/link directly. Keep it
short. Remove all friction: this is a free session, not a high-ticket sale,
so don't ask qualifying questions before handing over the next step.

Hi {{first_name}},

Great, here's your code: {{booking_code}}

You can book your free session here: {{booking_link}}

We're at {{nearest_clinic}} — [X-minute] walk from your office. If you'd
rather I run this through your insurance instead of the free session, just
tell me who your provider is and I'll take care of it.

Kurt

*(Adjust "your office" if the thread never established one — e.g. a lead who
didn't reply from a corporate address — and drop the insurance line if the
lead has already said they don't have cover.)*

---

## Corporate / HR — "yes" for the team

The lead replied positively to Campaign A (the free-session-for-the-team
offer to HR/People/Benefits contacts).

Hi {{first_name}},

Brilliant — I'll get the code and the one-pager over to you so your team can
book in whenever suits them. No contract, nothing to sign, nothing for you to
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

Never state a number, a percentage, or the word "discount" with a figure
attached. The free session *is* the price message — lean on that.

Hi {{first_name}},

The first session's genuinely free — a proper assessment plus hands-on
treatment, not just a chat. If you've got private health insurance we can
usually run any further sessions through your cover, and if not, ongoing
rates are straightforward and I'm happy to walk you through them once you've
had the first one.

Want me to send the code over?

Kurt

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

## Not filled in yet — fill these in before a real send

- **`{{booking_code}}`** — there's no discount/booking code system defined
  yet. Don't invent one. Until Andrew supplies the real format (or a way to
  generate one per lead), the model should say the code is coming and let
  Andrew add it before the draft is sent, rather than writing a fake code
  into the email.
- **`{{booking_link}}`** — no confirmed booking URL yet either (a
  `onebodyldn.com` booking page is likely but hasn't been confirmed — don't
  guess it). Same handling: leave it to Andrew to fill in, or replace this
  line in the template once the real URL is confirmed.

Once both are real, wire them the way AeroDefense wires its persona
`calendar_link` — either hardcode a single link here if it's the same for
everyone, or add `booking_link`/`booking_code` fields to `personas.json` if
they differ per sender, and pass them into the prompt the same way
`sender_name` and `calendar_link` are passed for AeroDefense
(`app/pipeline.py`, `app/batch_gen.py`).
