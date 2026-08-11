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

_SYSTEM = (
    "You are an AI text classification system. Your sole function is to analyze "
    "the provided text and assign it one of two categories: RELEVANT or NOT_RELEVANT."
)

_USER = """**CATEGORY DEFINITIONS:**
* **RELEVANT:**
- Any interest in continuing the conversation.
- Inquiries about price, a demo, a meeting
- Forwarding the email to a relevant colleague.

* **NOT_RELEVANT:**
- Rejection
- unsubscribe request
- "out of office" message
- reply that clearly ends the communication.
- Auto-reply or an Autoresponder message
- Response like -- "We will respond within X hours/days..."

**MANDATORY COMMAND:**
Carefully read the text inside the quotation marks below. After your analysis, your \
output **must be only one word**: RELEVANT or NOT_RELEVANT.
You must not write anything else. No explanations, no greetings, and no period at the end.

**TEXT TO ANALYZE:**
{text}"""


def is_relevant(reply_text: str) -> tuple[bool, str]:
    """`(relevant, reason)`. Fails open — see the module docstring."""
    text = to_plain_text(reply_text or "").strip()
    if not text:
        return True, "empty message — nothing to classify, treating as relevant"

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
        log.warning("reply classifier failed (%s) — treating reply as relevant", exc)
        return True, f"classifier unavailable ({exc.__class__.__name__}) — treated as relevant"

    # "NOT_RELEVANT" contains "RELEVANT", so the negative has to be tested
    # first. The prefix match rather than the whole word is deliberate: a
    # truncated verdict is still unambiguous, and reading "NOT_RELEV" as
    # relevant is the one misparse that costs a real draft every time.
    normalized = verdict.strip().upper()
    if "NOT_RELEV" in normalized:
        return False, "classified NOT_RELEVANT (rejection / auto-reply / out-of-office)"
    if "RELEVANT" in normalized:
        return True, "classified RELEVANT"
    log.warning("reply classifier returned %r — treating reply as relevant", verdict[:100])
    return True, f"classifier gave an unrecognized verdict ({verdict[:40]!r}) — treated as relevant"
