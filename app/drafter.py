import re
from pathlib import Path

import anthropic

from app.config import settings

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

OUTPUT_CONTRACT = """

---

## 13. Programmatic Output Contract

Your response will be parsed by software, not read directly by Andrew. Wrap the three parts of your Required Output Format (Section 10) in these exact tags, with nothing else inside them:

<triage>
(the Triage Summary content, bullet points, English)
</triage>

<draft_original>
(the exact ready-to-send email body in the lead's language — body only, no subject line, no commentary)
</draft_original>

<draft_english>
(the faithful English translation of the draft above)
</draft_english>

For a follow-up to a dead thread (Section 12 style, no new lead reply to triage), keep <triage> short (one or two lines: which follow-up number this is, and the angle you chose) and put your single best draft in <draft_original> — do not include multiple variations, just your strongest one.
"""

# Auto-reply / out-of-office bounces (Smartlead's own "Auto-Reply" category) get
# a separate, much lighter system prompt: no web research needed for a 2-4
# sentence nudge, and none of the Solutions Catalog / VSL knowledge base
# applies. Kept structurally consistent with the main prompt (same output
# tags) so app/drafter.py's parsing stays a single code path.
AUTOREPLY_SYSTEM_PROMPT = """You write short, casual nudge replies to auto-reply / out-of-office emails triggered by Andrew's cold outreach. The recipient's mailbox auto-responded (confirming receipt, promising a reply within some timeframe, or forwarding info) instead of a real person replying.

Write a brief (2-4 sentence), light, slightly witty reply that:
- Acknowledges you got their auto-reply.
- If it fits naturally (don't force it), makes a light, non-snarky observation connecting the delayed-response theme to the value of fast response times in general — a small ironic nod, not a pitch.
- Asks them to forward the original email to whoever handles this / the right person on their team, if they aren't it.

Match this tone (adapt the idea to the specific situation — don't reuse the words verbatim):
"Ha, funny timing. I got your auto-reply about delayed responses right after sending an email about how slow responses cost [industry] missed jobs. Not a dig at you, just kind of proves the point. If this is better suited for someone on the ops/leads side, mind forwarding it over? Appreciate it!"

Detect the language the auto-reply was written in and reply in that same language. Casual tone, no corporate language, no greeting salutation needed, no sign-off or signature — one is appended separately, so don't write one.

---

Wrap your response in exactly these tags, nothing else inside them:

<triage>
(one line: what triggered the auto-reply, e.g. "Auto-reply / OOO from <domain>")
</triage>

<draft_original>
(the exact ready-to-send nudge, in the auto-reply's own language — body only, no subject, no commentary)
</draft_original>

<draft_english>
(faithful English translation of the draft above)
</draft_english>
"""


def _load_system_prompt() -> str:
    base = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
    knowledge_parts = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        knowledge_parts.append(f"\n\n---\n\n# Reference: {path.stem}\n\n{path.read_text(encoding='utf-8')}")
    return base + OUTPUT_CONTRACT + "".join(knowledge_parts)


_SYSTEM_PROMPT = None


def system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _load_system_prompt()
    return _SYSTEM_PROMPT


def _build_user_message(
    kind: str,
    lead: dict,
    thread_text: str,
    steering_note: str | None = None,
) -> str:
    if kind == "autoreply":
        task_desc = "short nudge reply to their auto-reply/out-of-office message"
    elif kind == "followup":
        task_desc = "follow-up (no new reply from the lead)"
    else:
        task_desc = "response to the lead's latest reply"
    lines = [
        f"Task: draft a {task_desc}.",
        "",
        "Lead data:",
        f"- Name: {lead.get('name', '')}",
        f"- Company: {lead.get('company', '')}",
        f"- Email: {lead.get('email', '')}",
        f"- Website: {lead.get('website', '')}",
        f"- Campaign: {lead.get('campaign_name', '')}",
    ]
    custom_fields = lead.get("custom_fields")
    if custom_fields:
        lines.append(f"- Custom fields: {custom_fields}")
    if kind != "autoreply":
        lines += [
            "",
            "Research the lead's website yourself using the web search / web fetch tools before drafting, per the Website Diagnostic Framework.",
        ]
    lines += [
        "",
        "Full email thread (oldest to newest):",
        thread_text,
    ]
    if steering_note:
        lines += ["", f"Additional steering note from Andrew for this regeneration: {steering_note}"]
    return "\n".join(lines)


def _extract_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


class DraftResult:
    def __init__(self, triage_summary: str, body_original: str, body_translation: str, raw: str):
        self.triage_summary = triage_summary
        self.body_original = body_original
        self.body_translation = body_translation
        self.raw = raw


def generate_draft(
    kind: str,
    lead: dict,
    thread_text: str,
    steering_note: str | None = None,
) -> DraftResult:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    user_message = _build_user_message(kind, lead, thread_text, steering_note)
    messages = [{"role": "user", "content": user_message}]

    # Auto-reply nudges are short and need no research — skip the big
    # knowledge-base prompt and the web tools entirely (faster, cheaper).
    if kind == "autoreply":
        system = AUTOREPLY_SYSTEM_PROMPT
        tools = []
    else:
        system = system_prompt()
        tools = [
            {"type": "web_search_20260209", "name": "web_search"},
            {"type": "web_fetch_20260209", "name": "web_fetch"},
        ]

    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=system,
        tools=tools,
        messages=messages,
    )

    while tools and response.stop_reason == "pause_turn":
        messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response.content},
        ]
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )

    text = "".join(block.text for block in response.content if block.type == "text")

    return DraftResult(
        triage_summary=_extract_tag(text, "triage"),
        body_original=_extract_tag(text, "draft_original"),
        body_translation=_extract_tag(text, "draft_english"),
        raw=text,
    )
