"""Is this inbound reply worth drafting an answer to?

This is n8n's `OpenAI` → `Switch` node pair, moved into the app so Smartlead's
webhook can point straight at `/webhooks/smartlead` with nothing in between.
The n8n chain classified with gpt-5-mini and only forwarded RELEVANT replies;
everything else was dropped on the floor, which meant the dashboard never heard
about an out-of-office, a rejection or an unsubscribe at all.

Two rules this keeps, deliberately:

- **The verdict gates drafting, never visibility.** Every reply is recorded and
  shown in the inbox (see db.mark_lead_replied); the classifier only decides
  whether Claude spends tokens writing an answer and whether the lead is pushed
  to Smartlead's "Interested" category. A message you can't see is the bug this
  whole change exists to fix, and a classifier is exactly the wrong thing to put
  in front of it — it will be wrong sometimes, and being wrong should cost a
  wasted draft, not a lost lead.
- **It fails OPEN.** No key, no answer, a timeout, an unparseable verdict: treat
  the reply as relevant. The cost of a needless draft is a few cents; the cost
  of silently ignoring a real buyer is the account.

The categories and their wording are carried over from the n8n prompt so the
behaviour Andrew already tuned doesn't change underneath him.
"""

import logging

from app import llm, models_registry
from app.email_clean import to_plain_text

log = logging.getLogger("reply_classifier")

# The reply's own text is all that's needed, and a long quoted history is both
# noise and tokens. to_plain_text already drops the quoted part.
_MAX_CHARS = 4000

INTERESTED = "interested"
AUTO_REPLY = "auto_reply"
NOT_INTERESTED = "not_interested"

_SYSTEM = (
    "You are an AI text classification system. Your sole function is to analyze "
    "the provided text and assign it exactly one of three categories: "
    "INTERESTED, AUTO_REPLY or NOT_INTERESTED."
)

_USER = """**CATEGORY DEFINITIONS:**
* **INTERESTED** — a real person wrote this and the conversation is alive:
- Any interest in continuing the conversation.
- Inquiries about price, a demo, a meeting.
- Forwarding the email to a relevant colleague.
- A question, an objection, or a request to talk at a specific later time.

* **AUTO_REPLY** — nobody actually read it; a machine answered:
- "Out of office" / holiday / away message.
- Autoresponder or ticket acknowledgement ("we have received your email").
- "We will respond within X hours/days..."
- Delivery failure, blocked message, or an anti-spam verification challenge.

* **NOT_INTERESTED** — a person answered and the answer is no:
- Rejection.
- Unsubscribe or removal request, or a data-protection complaint.
- "Wrong person" / "we don't handle this".
- A reply that clearly ends the communication.

An out-of-office that also says to get in touch at a named later date is
INTERESTED, not AUTO_REPLY — a person wrote that sentence.

**MANDATORY COMMAND:**
Carefully read the text below. After your analysis, your output **must be only \
one word**: INTERESTED, AUTO_REPLY or NOT_INTERESTED.
You must not write anything else. No explanations, no greetings, and no period at the end.

**TEXT TO ANALYZE:**
{text}"""


def is_relevant(reply_text: str) -> tuple[bool, str]:
    """`(relevant, reason)` — the two-way view, for callers that only need to
    know whether to spend a draft."""
    label, reason = classify(reply_text)
    return label == INTERESTED, reason


def classify(reply_text: str) -> tuple[str, str]:
    """`(label, reason)` where label is INTERESTED / AUTO_REPLY / NOT_INTERESTED.

    Fails open to INTERESTED — see the module docstring."""
    text = to_plain_text(reply_text or "").strip()
    if not text:
        return INTERESTED, "empty message — nothing to classify, treated as interested"

    try:
        # 512 tokens for a one-word answer, and it has to be. A reasoning model
        # bills its thinking against this same budget, so a tight cap doesn't
        # buy a short answer — it truncates the answer. At 64 the out-of-office
        # case came back as the literal string "NOT_RELEV", which then failed to
        # parse and failed open into a wasted draft. Same trap as
        # _OPENROUTER_DRAFT_MAX_TOKENS and _REPORT_MAX_TOKENS. On the default
        # model this ceiling is worth about $0.0001 even if it were ever hit.
        verdict, _ = llm.complete_for(
            models_registry.ROLE_CLASSIFY,
            _SYSTEM,
            _USER.format(text=text[:_MAX_CHARS]),
            max_tokens=512,
        )
    except Exception as exc:
        log.warning("reply classifier failed (%s) — treating reply as interested", exc)
        return INTERESTED, f"classifier unavailable ({exc.__class__.__name__}) — treated as interested"

    # Prefixes, not whole words: a reasoning model that runs out of budget
    # returns a truncated verdict, and "NOT_INTER" is still unambiguous. The
    # negative is tested first because "NOT_INTERESTED" contains "INTERESTED".
    normalized = verdict.strip().upper()
    if "NOT_INTER" in normalized:
        return NOT_INTERESTED, "classified NOT_INTERESTED (rejection / unsubscribe / wrong person)"
    if "AUTO_REPL" in normalized or "AUTO REPL" in normalized:
        return AUTO_REPLY, "classified AUTO_REPLY (autoresponder / out-of-office / bounce)"
    if "INTEREST" in normalized:
        return INTERESTED, "classified INTERESTED"
    log.warning("reply classifier returned %r — treating reply as interested", verdict[:100])
    return INTERESTED, f"classifier gave an unrecognized verdict ({verdict[:40]!r}) — treated as interested"
