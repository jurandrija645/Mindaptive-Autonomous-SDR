import re

import anthropic

from app import client_assets, models_registry, openrouter, writing_rules
from app.config import settings

# Per-client when CLIENT_DIR is set, repo root otherwise (see client_assets).
PROMPTS_DIR = client_assets.PROMPTS_DIR
KNOWLEDGE_DIR = client_assets.KNOWLEDGE_DIR

# The model picker's choices (Anthropic + OpenRouter, with prices) live in
# app/models_registry.py — it is the single source the dashboard's dropdown,
# the default-model setting and every validation check below read from.

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
""" + writing_rules.as_section()


def _output_contract() -> str:
    """A client can ship its own contract at `<CLIENT_DIR>/prompts/output-contract.md`.
    The default below cites section numbers from Mindaptive's system.md, which
    another client's prompt won't have."""
    override = PROMPTS_DIR / "output-contract.md"
    if override.exists():
        return "\n\n---\n\n" + override.read_text(encoding="utf-8")
    return OUTPUT_CONTRACT


def _load_system_prompt() -> str:
    base = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
    knowledge_parts = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        knowledge_parts.append(f"\n\n---\n\n# Reference: {path.stem}\n\n{path.read_text(encoding='utf-8')}")
    # The house voice goes last, after the knowledge base, so it is the most
    # recent instruction the model has read when it starts writing. It is also
    # deliberately outside system.md: the same rules bind the translator and the
    # auto-reply path, which never load system.md at all.
    return (
        base
        + _output_contract()
        + "".join(knowledge_parts)
        + writing_rules.as_section()
    )


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
    followup_stage: str | None = None,
    previous_draft: str | None = None,
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
    ]
    # followup_stage (set by pipeline.create_draft from the lead's
    # followup_count): "final" = last follow-up before the cap → use the
    # Section 12 "closing this file" breakup pattern, which reliably gets a
    # response out of dead threads. "revive" = the lead went cold past the cap
    # and this is a one-off revival touch months later → fresh angle, no guilt.
    if followup_stage == "final":
        lines += [
            "This is the FINAL follow-up for this lead. Write it as the graceful "
            "close-out from Section 12 ('closing this file, it seems that now is not "
            "the right time...') — polite, zero pressure, door left open. Adapt the "
            "wording to this lead, don't copy it verbatim.",
            "",
        ]
    elif followup_stage == "revive":
        lines += [
            "This is a REVIVAL touch: months have passed since the thread went cold "
            "and the previous follow-up sequence ended. Re-open casually with a fresh "
            "angle (something new about their business or a different solution fit) — "
            "do NOT reference the silence, apologize, or rehash old follow-ups. Write "
            "it like a peer circling back because something reminded you of them.",
            "",
        ]
    lines += [
        "Lead data:",
        f"- Name: {lead.get('name', '')}",
        f"- Company: {lead.get('company', '')}",
        f"- Email: {lead.get('email', '')}",
        f"- Website: {lead.get('website', '')}",
        f"- Campaign: {lead.get('campaign_name', '')}",
    ]
    # Section 9 of the system prompt tells the model to detect the thread's
    # language and answer in it. That works until it doesn't — a short thread, a
    # lead who quoted an English signature back at us — and the app already
    # knows the answer from Smartlead's own per-lead field (see
    # app/lead_language.py). So state it, and leave §9 as the fallback for the
    # leads where nothing knows.
    if lead.get("language"):
        lines.append(
            f"- Write this email in {lead.get('language_name') or lead['language']} "
            f"({lead['language']}). This is the language the lead reads; it is not a "
            "guess from the thread. The English translation goes in the "
            "<draft_english> block as usual."
        )
    custom_fields = lead.get("custom_fields")
    if custom_fields:
        lines.append(f"- Custom fields: {custom_fields}")
    # Only populated for clients whose personas carry their own booking link
    # (see app/client_assets.personas). Mindaptive leaves both blank and keeps
    # using the Calendly URL written into its system.md.
    sender_name = lead.get("sender_name") or ""
    calendar_link = lead.get("calendar_link") or ""
    if sender_name:
        lines.append(f"- You are writing as: {sender_name}")
    if calendar_link:
        lines.append(
            f"- {sender_name or 'This sender'}'s booking link — use this exact URL "
            f"wherever a template calls for a calendar link: {calendar_link}"
        )
    elif sender_name:
        lines.append(
            "- No booking link is available for this sender. Do not invent one; "
            "offer to send times instead."
        )
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
    # The draft being replaced, last in the message so it is the freshest thing
    # in context when the model starts writing.
    #
    # Regenerate used to send nothing but the steering note: the old draft was
    # marked skipped and the model wrote a brand new email from scratch. So
    # "make the second paragraph shorter" produced a completely different
    # message, because there was no second paragraph to shorten — the model had
    # never seen one. The text below is also whatever is in the editor right
    # now, so any hand edits Andrew made survive the regeneration.
    if previous_draft:
        lines += ["", "=== THE DRAFT YOU ARE REVISING ===", previous_draft, "=== END OF DRAFT ==="]
        if steering_note:
            lines += [
                "",
                f"Andrew's instruction for this revision: {steering_note}",
                "",
                "THIS IS AN EDIT, NOT A NEW EMAIL. Start from the draft above and apply "
                "ONLY that instruction. Every sentence the instruction does not touch "
                "must come back word for word as it already is — same wording, same "
                "order, same paragraph breaks, same opening and closing lines. Do not "
                "reword, tighten, reorder or 'improve' anything you were not asked to "
                "change, even where you would have written it differently yourself. If "
                "the instruction only concerns one sentence, exactly one sentence "
                "changes. Output the whole message, including the untouched parts.",
            ]
        else:
            lines += [
                "",
                "Andrew regenerated without an instruction, which means this draft did "
                "not land. Write a genuinely different one — a different angle, opening "
                "and CTA, not a reshuffle of the same sentences.",
            ]
    elif steering_note:
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


def parse_draft_response(text: str) -> DraftResult:
    """Parse the model's tagged output (Section 13 output contract) into a
    DraftResult — shared by the interactive path below and the Batch API path
    (app/batch_gen.py), so both produce identical draft rows."""
    return DraftResult(
        triage_summary=_extract_tag(text, "triage"),
        body_original=_extract_tag(text, "draft_original"),
        body_translation=_extract_tag(text, "draft_english"),
        raw=text,
        lead_research=_extract_tag(text, "lead_research"),
    )


def build_batch_request_params(
    kind: str,
    lead: dict,
    thread_text: str,
    prior_research: str | None = None,
    followup_stage: str | None = None,
    model: str | None = None,
) -> dict:
    """Message params for ONE request inside an Anthropic Batch API job
    (app/batch_gen.py) — mirrors generate_draft's request exactly, minus the
    web tools: a batch result can't continue a pause_turn tool loop, so batch
    generation is only used for leads whose research already exists. The
    identical cached system prompt is shared across every request in the
    batch (and with the interactive path).

    Always resolves to an Anthropic model: the Batch API is Anthropic's, so an
    OpenRouter default must not leak into it."""
    model = models_registry.resolve_anthropic(model)
    user_message = _build_user_message(
        kind, lead, thread_text, None, prior_research,
        use_web_search=False, followup_stage=followup_stage,
    )
    return {
        "model": model,
        "max_tokens": 4096,
        "system": [
            {"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral", "ttl": "1h"}}
        ],
        "messages": [{"role": "user", "content": user_message}],
    }


def generate_draft(
    kind: str,
    lead: dict,
    thread_text: str,
    steering_note: str | None = None,
    prior_research: str | None = None,
    model: str | None = None,
    use_web_search: bool = True,
    followup_stage: str | None = None,
    previous_draft: str | None = None,
) -> DraftResult:
    model = models_registry.resolve(model)
    if models_registry.provider_for(model) == models_registry.PROVIDER_OPENROUTER:
        return _generate_via_openrouter(
            kind, lead, thread_text, steering_note, prior_research, model,
            followup_stage, previous_draft,
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Auto-reply nudges never get tools regardless of use_web_search. For
    # everything else, use_web_search=False is a hard cutoff — the tools
    # aren't just discouraged in the prompt, they're not in the request at
    # all, so Claude physically cannot call them no matter what it decides.
    use_web_search = use_web_search and kind != "autoreply"
    user_message = _build_user_message(
        kind, lead, thread_text, steering_note, prior_research, use_web_search,
        followup_stage, previous_draft,
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
    # max_uses / max_content_tokens: hard server-side caps on research spend.
    # A single uncapped web_fetch can pull tens of thousands of tokens of page
    # content into the conversation, and that content is then RE-SENT on every
    # pause_turn continuation below — so one oversized fetch multiplies across
    # the whole loop. 4 searches + 4 fetches at <=10k tokens each is plenty for
    # the Website Diagnostic Framework (homepage + a contact/reviews page).
    tools = (
        [
            {
                "type": "web_search_20260209",
                "name": "web_search",
                "allowed_callers": ["direct"],
                "max_uses": 4,
            },
            {
                "type": "web_fetch_20260209",
                "name": "web_fetch",
                "allowed_callers": ["direct"],
                "max_uses": 4,
                "max_content_tokens": 10000,
            },
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
    #
    # ttl="1h" (vs the default 5-min ephemeral): drafts are click-triggered and
    # spread through the day, so with a 5-min TTL the cache expires between
    # drafts and each new draft re-pays the full system-prompt WRITE on its
    # first turn. A 1-hour TTL keeps the identical prompt warm across a working
    # session and the daily scan's batch of reply auto-drafts, so most drafts'
    # first turn is a 0.1x cache READ instead. (1h writes cost 2x vs 1.25x, so
    # this pays off at >=3 drafts/hour on the same model — the normal pattern;
    # caches are model-scoped, so this benefits the default model path.) No beta
    # header needed on the first-party API. Output is identical either way.
    system_blocks = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    ]

    # Top-level cache_control auto-places a breakpoint on the LAST cacheable
    # block of the request (messages tier — the system prompt keeps its own
    # explicit 1h breakpoint above; max 4 breakpoints per request, we use 2).
    # Without it, only the system prompt is cached and every pause_turn
    # continuation below re-pays the full growing conversation (user message +
    # all accumulated web search/fetch results) at full input price. With it,
    # each continuation reads the previous turns at ~0.1x and only pays full
    # price for the newest tool results. Loop turns are seconds apart, so the
    # default 5-minute TTL is more than enough here.
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_blocks,
        tools=tools,
        messages=messages,
        cache_control={"type": "ephemeral"},
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
            cache_control={"type": "ephemeral"},
        )

    text = "".join(block.text for block in response.content if block.type == "text")

    return parse_draft_response(text)


# Reasoning models bill their thinking against max_tokens, exactly like
# Anthropic's adaptive thinking does (see the ANTHROPIC_MODEL note in CLAUDE.md
# and _REPORT_MAX_TOKENS, which had to grow for the same reason: an 8k budget
# came back completely empty because all of it went to thinking). 4096 was
# enough for a plain chat model and far too little for DeepSeek V4 Pro on this
# output contract, which asks for a triage block, the draft, an English version
# and a research block after reading a long objection thread — it spent the lot
# reasoning and returned no answer at all. That failure is lead-dependent, which
# is what made it look arbitrary: the harder the reply is to think about, the
# likelier it is to run out before writing anything.
_OPENROUTER_DRAFT_MAX_TOKENS = 16000


def _generate_via_openrouter(
    kind: str,
    lead: dict,
    thread_text: str,
    steering_note: str | None,
    prior_research: str | None,
    model: str,
    followup_stage: str | None,
    previous_draft: str | None,
) -> DraftResult:
    """Same prompt, same output contract, one plain chat completion.

    `use_web_search=False` is not a choice here — the OpenRouter path has no
    tools at all (see app/openrouter.py), so the user message is built to tell
    the model exactly that: reuse `prior_research` if it exists, otherwise write
    from the thread alone and leave <lead_research> empty rather than inventing
    facts about the lead's business. Research a lead once on an Anthropic model
    and it is reused by every OpenRouter draft that follows."""
    system = AUTOREPLY_SYSTEM_PROMPT if kind == "autoreply" else system_prompt()
    user_message = _build_user_message(
        kind, lead, thread_text, steering_note, prior_research,
        use_web_search=False, followup_stage=followup_stage,
        previous_draft=previous_draft,
    )
    text = openrouter.complete(model, system, user_message, max_tokens=_OPENROUTER_DRAFT_MAX_TOKENS)
    return parse_draft_response(text)
