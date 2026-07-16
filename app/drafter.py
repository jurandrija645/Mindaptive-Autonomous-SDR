import re
from pathlib import Path

import anthropic

from app.config import settings

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

# Curated model choices exposed in the dashboard's generate/regenerate model
# picker (added for cost control — web-research drafts on Sonnet/Opus with
# tool-use loops add up in tokens). Keep in sync with the <select> in
# app/static/app.js (renderModelSelect). Values are real Anthropic model ids.
ALLOWED_MODELS = {
    "claude-haiku-4-5": "Haiku 4.5 (cheap/fast)",
    "claude-sonnet-5": "Sonnet 5 (default)",
    "claude-opus-4-8": "Opus 4.8 (best quality)",
}

OUTPUT_CONTRACT = """

---

## 13. Programmatic Output Contract

Your response will be parsed by software, not read directly by Andrew. Wrap the four parts of your Required Output Format (Section 10) in these exact tags, with nothing else inside them:

<triage>
(the Triage Summary content, bullet points, English)
</triage>

<draft_original>
(the exact ready-to-send email body in the lead's language — body only, no subject line, no commentary)
</draft_original>

<draft_english>
(the faithful English translation of the draft above)
</draft_english>

<lead_research>
(3-6 bullet points, English, stand-alone: what the company does, what they
sell, who their target clients/customers are, team size or decision-maker
signals, review signal, and anything else useful for future outreach to this
lead. Write this so it's still useful on its own, without the rest of your
response, since it gets saved and reused on later drafts to the same lead.)
</lead_research>

For a follow-up to a dead thread (Section 12 style, no new lead reply to triage), keep <triage> short (one or two lines: which follow-up number this is, and the angle you chose) and put your single best draft in <draft_original> — do not include multiple variations, just your strongest one.
"""

# Auto-reply / out-of-office bounces (Smartlead's own "Auto-Reply" category) get
# a separate, much lighter system prompt: no web research needed for a 2-4
# sentence nudge, and none of the Solutions Catalog / VSL knowledge base
# applies. Kept structurally consistent with the main prompt (same output
# tags) so app/drafter.py's parsing stays a single code path.
AUTOREPLY_SYSTEM_PROMPT = """You write short, respectful nudge replies to auto-reply / out-of-office emails triggered by Andrew's cold outreach. The recipient's mailbox auto-responded (confirming receipt, promising a reply within some timeframe, or forwarding info) instead of a real person replying.

Write a brief (2-4 sentence), plain, respectful reply that:
- Acknowledges you got their auto-reply, no rush implied.
- Makes one genuine point, stated plainly and respectfully: slow response to inbound leads costs businesses in their industry real jobs and revenue. Frame this as the actual reason Andrew reached out in the first place, not as a comment on them specifically or their timing just now. Never phrase it as a "gotcha," an irony, or a joke about their auto-reply "proving" anything. It's a general point about their industry, not about them personally being slow or away.
- Asks them to forward the original email to whoever handles this / the right person on their team, if they aren't it.

Match this tone (adapt to the specific situation and their industry, don't reuse the words verbatim):
"Thanks for the auto-reply, no rush at all. Worth mentioning though, slow follow-up on new leads is one of the main reasons [industry] companies lose jobs to competitors, that's actually why I reached out in the first place. If this is better handled by someone on the ops/leads side, would you mind forwarding it their way? Appreciate it."

Detect the language the auto-reply was written in and reply in that same language. Plain, respectful tone, no mocking, no sarcasm, no corporate language, no greeting salutation needed, no sign-off or signature (one is appended separately, so don't write one). No em dashes, anywhere. No AI-tell filler words. Keep sentence lengths uneven, like someone typing quickly, not a template.

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
    prior_research: str | None = None,
    use_web_search: bool = True,
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
        if prior_research and use_web_search:
            lines += [
                "",
                "Existing research on this lead from a prior draft (below) — reuse this and do "
                "NOT re-run web_search/web_fetch unless it looks thin/outdated, or the steering "
                "note below asks you to dig into something new. If you do research further, still "
                "include an updated <lead_research> block covering everything relevant, old and new.",
                "",
                prior_research,
            ]
        elif prior_research and not use_web_search:
            lines += [
                "",
                "Existing research on this lead from a prior draft (below) — web search/fetch "
                "tools are unavailable for this draft, so write using this research and the "
                "thread only. Still include a <lead_research> block reusing it as-is.",
                "",
                prior_research,
            ]
        elif use_web_search:
            lines += [
                "",
                "Research the lead's website yourself using the web search / web fetch tools before drafting, per the Website Diagnostic Framework.",
            ]
        else:
            lines += [
                "",
                "No prior research and web search/fetch tools are unavailable for this draft — "
                "write using only the thread and lead data above. Leave <lead_research> empty "
                "rather than guessing.",
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
    def __init__(
        self,
        triage_summary: str,
        body_original: str,
        body_translation: str,
        raw: str,
        lead_research: str = "",
    ):
        self.triage_summary = triage_summary
        self.body_original = body_original
        self.body_translation = body_translation
        self.raw = raw
        self.lead_research = lead_research


def generate_draft(
    kind: str,
    lead: dict,
    thread_text: str,
    steering_note: str | None = None,
    prior_research: str | None = None,
    model: str | None = None,
    use_web_search: bool = True,
) -> DraftResult:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = model if model in ALLOWED_MODELS else settings.anthropic_model

    # Auto-reply nudges never get tools regardless of use_web_search. For
    # everything else, use_web_search=False is a hard cutoff — the tools
    # aren't just discouraged in the prompt, they're not in the request at
    # all, so Claude physically cannot call them no matter what it decides.
    use_web_search = use_web_search and kind != "autoreply"
    user_message = _build_user_message(
        kind, lead, thread_text, steering_note, prior_research, use_web_search
    )
    messages = [{"role": "user", "content": user_message}]

    if kind == "autoreply":
        system = AUTOREPLY_SYSTEM_PROMPT
    else:
        system = system_prompt()
    # allowed_callers=["direct"] restricts these to normal model-invoked tool
    # calling. Without it, current web_search/web_fetch versions also allow
    # programmatic (code-execution) calling by default, which Haiku doesn't
    # support and the API rejects with a 400 — confirmed via a real error:
    # "'claude-haiku-4-5-20251001' does not support programmatic tool
    # calling... Explicitly set allowed_callers=["direct"] on these tools."
    # We don't use code-execution/programmatic tool calling anywhere here.
    tools = (
        [
            {"type": "web_search_20260209", "name": "web_search", "allowed_callers": ["direct"]},
            {"type": "web_fetch_20260209", "name": "web_fetch", "allowed_callers": ["direct"]},
        ]
        if use_web_search
        else []
    )

    # Cached: the system prompt (~12.5k tokens for the main prompt) is
    # identical across every turn of this loop and every other draft, so
    # without cache_control it gets rebilled at full input price on every
    # single tool-use round trip — confirmed in production usage logs as a
    # single draft making 7-8 sequential calls with input tokens climbing by
    # a few hundred each turn, each one repaying the full system prompt.
    system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_blocks,
        tools=tools,
        messages=messages,
    )

    # Capped: an uncapped pause_turn loop let a single draft run 7-8+ tool
    # round trips in production, each resending the full growing
    # conversation. 6 turns is generous for the Website Diagnostic
    # Framework's research and stops a stuck research loop from running
    # away with tokens indefinitely.
    max_tool_turns = 6
    turns = 0
    while tools and response.stop_reason == "pause_turn" and turns < max_tool_turns:
        turns += 1
        messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response.content},
        ]
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_blocks,
            tools=tools,
            messages=messages,
        )

    text = "".join(block.text for block in response.content if block.type == "text")

    return DraftResult(
        triage_summary=_extract_tag(text, "triage"),
        body_original=_extract_tag(text, "draft_original"),
        body_translation=_extract_tag(text, "draft_english"),
        raw=text,
        lead_research=_extract_tag(text, "lead_research"),
    )
