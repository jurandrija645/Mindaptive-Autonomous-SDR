"""The AI half of campaign analysis: turn the numbers and the conversations into
a diagnosis and a plan for the next run.

Two independent reports, both cached on the campaign_reports row:

- `report_md` (Layer 1) — one call over the variant/slot/subject statistics.
  Answers which subject line, CTA, offer and angle earn replies, and proposes
  the variant line-up for the next run.
- `conversation_md` (Layer 2) — a map/reduce over the real conversations.
  Extraction runs in batches and is cached per conversation, so re-analyzing a
  campaign only pays for threads that are new.

The prompts carry three hard rules, all of them earned from this data:

1. Open and click rate do not exist. Tracking is off account-wide because it
   hurts deliverability, so `open_count` is 0 on every row. A model left to its
   own habits will reach for "improve your open rate" advice that is unusable
   here and implies data we deliberately do not collect.
2. Never call a winner on `not_enough_data`. Campaign 3640877 has 42 human
   replies split across six variants; almost every comparison is noise, and a
   confident ranking of noise is worse than no ranking.
3. Quote, never paraphrase, when citing what a lead said — the quotes are how
   Andrew checks the synthesis against reality.
"""

import json
import logging
import re
import threading

import anthropic

from app import campaign_analytics, campaign_conversations, db, smartlead
from app.config import settings

log = logging.getLogger("campaign_report")

# `max_tokens` bounds thinking *plus* visible output, and adaptive thinking is on
# by default on claude-sonnet-5. The first run of this module asked for a long
# report inside 8k tokens and got back nothing at all: the model spent all 8,000
# on thinking and had none left to answer with (stop_reason "max_tokens", a lone
# empty thinking block). These reports need real room.
_REPORT_MAX_TOKENS = 32000
# The extraction step emits compact JSON, so it needs far less headroom — but
# still more than the thinking it does on the way there.
_EXTRACT_MAX_TOKENS = 16000
_EXTRACT_BATCH = 12

_GROUND_RULES = """\
Hard rules for this analysis — all three exist because of how this data was collected:

1. OPEN AND CLICK RATE DO NOT EXIST. Open and link tracking are switched off
   across this account on purpose (tracking pixels hurt deliverability), so
   every open/click number is a structural zero, not a real measurement. Never
   mention open rate, click rate, or any advice that depends on them.
2. REPLIES ARE THE ONLY OUTCOME SIGNAL. A "reply" here always means a human
   reply — Smartlead's Auto-Reply and Out Of Office categories are already
   stripped out. "Positive" means the lead was categorised Interested or
   Meeting-Booked.
3. RESPECT THE CONFIDENCE LABELS. Every rate carries a verdict:
   - not_enough_data — too few sends or replies to compare. You MUST NOT
     declare this a winner or a loser. Say it is unresolved and state roughly
     how many more sends it needs.
   - leaning_above / leaning_below — a direction, not a result. Say "leaning"
     and never "proves" or "clearly wins".
   - solid_above / solid_below — the confidence interval clears the campaign
     baseline. Only these justify a firm claim.
   Cite the actual counts (e.g. "16 replies from 1,490 delivered") next to any
   claim. Never invent a number that is not in the data given to you.
"""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _text_of(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text").strip()


def _write_report(prompt: str, model: str) -> str:
    """One long-form report call.

    Streamed because `max_tokens` this large risks an HTTP timeout on a
    non-streaming request (the SDK refuses some of them outright). Effort is
    pinned high: the whole point of this call is a careful reading of thin,
    easily-misread data."""
    with _client().messages.stream(
        model=model,
        max_tokens=_REPORT_MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()
    text = _text_of(response)
    if not text:
        raise RuntimeError(
            f"model returned no text (stop_reason={response.stop_reason}); "
            "if this is 'max_tokens', raise _REPORT_MAX_TOKENS"
        )
    return text


# ---------------------------------------------------------------------------
# Layer 1 — the statistics brief
# ---------------------------------------------------------------------------

def build_stats_brief(conn, campaign_id: int, campaign_name: str = "") -> dict:
    """Everything Layer 1 reasons over. Slot entries carry real example text —
    a critique of `{{CTA1}}` is worthless unless the model has read what CTA1
    actually says."""
    outcomes = campaign_analytics.lead_outcomes(conn, campaign_id)
    summary = campaign_analytics.campaign_summary(conn, campaign_id, outcomes)
    slots = campaign_analytics.slot_metrics(conn, campaign_id, outcomes)

    for entries in slots.values():
        for entry in entries:
            entry["examples"] = campaign_analytics.slot_examples(conn, campaign_id, entry["slot"])

    settings_row = {}
    try:
        raw = smartlead.get_campaign(campaign_id)
        settings_row = {
            "timezone": (raw.get("scheduler_cron_value") or {}).get("tz"),
            "send_window": f"{(raw.get('scheduler_cron_value') or {}).get('startHour')}–"
            f"{(raw.get('scheduler_cron_value') or {}).get('endHour')}",
            "send_days": (raw.get("scheduler_cron_value") or {}).get("days"),
            "plain_text": raw.get("send_as_plain_text"),
            "stop_on": raw.get("stop_lead_settings"),
        }
    except Exception as exc:  # settings are context, not essential
        log.warning("campaign %s: could not read settings: %s", campaign_id, exc)

    return {
        "campaign": {"id": campaign_id, "name": campaign_name, **settings_row},
        "totals": summary,
        "variants": campaign_analytics.variant_metrics(conn, campaign_id, outcomes),
        "slots": slots,
        "rendered_subjects": campaign_analytics.subject_metrics(
            conn, campaign_id, outcomes=outcomes
        ),
        "reply_by_step": campaign_analytics.reply_step_metrics(conn, campaign_id, outcomes),
    }


_LAYER1_PROMPT = """\
You are a cold-email strategist reviewing one outbound campaign for Mindaptive.ai,
which sells AI receptionist / lead-response automation to small service businesses.

{rules}

HOW THE VARIANTS WORK — this is the key to the whole analysis. Each A/B variant is
a recipe assembled from slots: a subject slot, an icebreaker, a pitch, an offer and
a CTA. The same slot value is reused across several variants (CTA1 might appear in
both variant A and variant C), so a slot's numbers pool every variant that uses it
and rest on a much larger sample than any single variant. Judge SLOTS first —
that is where the signal is — and treat the per-variant table as secondary.

Each slot entry includes `examples`: the real text that slot inserts, taken from
the campaign's own lead data. Critique that text specifically. Quote it.

THE DATA:
```json
{brief}
```

Write a markdown report with exactly these sections:

## Verdict
Three bullets: what is working, what is broken, and the single biggest lever.

## Subject lines
Which rendered subject lines earn replies and which do not, and WHY — length,
question vs statement, specificity vs curiosity, whether it reads as automated.
Quote the actual subject text.

## CTAs
Rank the CTA slots and explain the mechanism: what is each one asking the reader
to do, and how much effort does it demand?

## Offer and angle
Which pitch/offer framing pulls positive replies, and what that says about what
this audience cares about.

## Tone and structure
Length, formality, personalization depth, and anything that reads as mass mail.

## Deliverability
Bounce rate, unsubscribes, and step-by-step drop-off. Flag anything that
threatens inbox placement. This is separate from copy quality — do not confuse
a deliverability problem for a copy problem.

## Fixes
Ranked, concrete, each with the expected effect and the reasoning.

## Next run — variant plan
The most important section. Give 4–6 concrete variant recipes for the next run,
each written as an explicit slot combination (subject + icebreaker + pitch +
offer + CTA). For every variant state:
- exactly what it is testing (ONE variable different from its comparison),
- which current variant it replaces and why that one is being retired,
- the full new copy for any slot value you are proposing, written out ready to
  paste — not described.
End with how many sends per variant are needed before the result can be read,
based on the reply rates actually observed here.
"""


def generate_variant_report(conn, campaign_id: int, campaign_name: str = "", model: str | None = None) -> tuple[str, dict]:
    brief = build_stats_brief(conn, campaign_id, campaign_name)
    model = model or settings.anthropic_model
    prompt = _LAYER1_PROMPT.format(
        rules=_GROUND_RULES, brief=json.dumps(brief, indent=1, default=str)
    )
    return _write_report(prompt, model), brief


# ---------------------------------------------------------------------------
# Layer 2 — conversation mining
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = """\
You are analysing real replies to a cold-email campaign from Mindaptive.ai, which
sells AI receptionist / lead-response automation to small service businesses.

For EACH conversation below, return one JSON object. Base every field only on what
the lead actually wrote. If a field cannot be determined from the text, use null.

Fields:
- "lead_id": copy it back exactly.
- "intent": one of "wants_more_info", "wants_meeting", "asked_for_asset",
  "referred_us_elsewhere", "polite_decline", "hard_decline", "angry",
  "already_solved", "wrong_target", "unclear".
- "objection_type": null, or one of "price", "timing", "already_have_solution",
  "not_decision_maker", "no_trust", "unclear_offer", "no_need",
  "company_changing", "privacy_or_spam", "language_barrier".
- "magnet_requested": which asset they asked for ("video", "toolkit",
  "calculator", "demo", "pricing", "case_study") or null.
- "tone": "warm", "neutral", "curt" or "hostile".
- "trigger": a SHORT VERBATIM QUOTE from the lead showing what in our email they
  reacted to. Never paraphrase; copy their words.
- "friction": anything they misread, doubted, or found confusing — verbatim if
  possible, else null.
- "salvageable": true/false — could a different angle still win this lead?
- "salvage_angle": one sentence on what that angle would be, or null.

Return ONLY a JSON array, no prose, no code fence.

CONVERSATIONS:
```json
{conversations}
```
"""


def _parse_json_array(text: str) -> list[dict]:
    """Models occasionally wrap JSON in a fence or add a sentence around it."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            return []
    return parsed if isinstance(parsed, list) else []


def extract_conversations(campaign_id: int, model: str | None = None, progress=None) -> int:
    """Map step: structured extraction per conversation, cached on the row.

    Only conversations without a cached extraction are sent, so a re-analysis
    after a few new replies costs a fraction of the first run."""
    model = model or settings.anthropic_model
    with db.db_session() as conn:
        pending = [
            campaign_conversations.thread_for_prompt(row)
            for row in db.list_campaign_conversations(conn, campaign_id, unextracted_only=True)
        ]
    if not pending:
        return 0

    done = 0
    for start in range(0, len(pending), _EXTRACT_BATCH):
        chunk = pending[start : start + _EXTRACT_BATCH]
        if progress:
            progress(f"Reading replies {start + 1}–{start + len(chunk)} of {len(pending)}…")
        response = _client().messages.create(
            model=model,
            max_tokens=_EXTRACT_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[
                {
                    "role": "user",
                    "content": _EXTRACT_PROMPT.format(
                        conversations=json.dumps(chunk, indent=1, ensure_ascii=False)
                    ),
                }
            ],
        )
        extractions = {
            str(item.get("lead_id")): item
            for item in _parse_json_array(_text_of(response))
            if isinstance(item, dict)
        }
        with db.db_session() as conn:
            for conversation in chunk:
                extraction = extractions.get(str(conversation["lead_id"]))
                if not extraction:
                    continue
                db.upsert_campaign_conversation(
                    conn,
                    campaign_id,
                    str(conversation["lead_id"]),
                    extract_json=json.dumps(extraction, ensure_ascii=False),
                    extracted_at=db.now_iso(),
                )
                done += 1
    log.info("campaign %s: extracted %d conversations", campaign_id, done)
    return done


_SYNTHESIS_PROMPT = """\
You are a cold-email strategist for Mindaptive.ai (AI receptionist / lead-response
automation for small service businesses), reviewing every real human reply to one
campaign.

{rules}

Additional rules for this part:
- QUOTE, NEVER PARAPHRASE, when citing what a lead said. The quotes are how this
  report gets fact-checked.
- COUNT, NEVER ESTIMATE. The counts are given to you below; use them.
- If a pattern rests on fewer than 5 conversations, say so explicitly in the
  sentence where you claim it.

COUNTS (already computed — do not recompute):
```json
{stats}
```

PER-CONVERSATION EXTRACTIONS:
```json
{extractions}
```

Write a markdown report with exactly these sections:

## How people actually reply
The objection taxonomy with counts, each backed by a verbatim quote.

## Lead magnets and assets
Which assets leads ask for, in what words, and which offers are ignored. If no
lead asked for an asset, say that plainly and say what it implies.

## Follow-up effectiveness
Which step earns replies and which earns irritation. Say directly whether the
sequence should be longer or shorter, and where it should stop.

## What irritates vs what engages
The concrete triggers, quoted. Be specific about the phrasing that caused each.

## Who is salvageable
Patterns among the declines that a different angle could still win, and the
angle for each.

## Strategy for interested leads
How to run the conversation after a first positive reply: which asset to lead
with, what to say next, what to avoid. This drives how the app's own reply
drafts should be written.

## Suggested changes to our playbook
Specific, quotable edits for `prompts/system.md` (how the AI writes replies) and
`knowledge/solutions-catalog.md` (what we offer). Phrase each as a concrete
instruction Andrew could paste in. Do not rewrite the whole file.
"""


def generate_conversation_report(conn, campaign_id: int, model: str | None = None) -> str:
    rows = db.list_campaign_conversations(conn, campaign_id)
    extractions = []
    for row in rows:
        if not row["extract_json"]:
            continue
        try:
            item = json.loads(row["extract_json"])
        except ValueError:
            continue
        item["category"] = row["category"]
        item["variant"] = row["variant_label"]
        item["replied_after_step"] = row["first_reply_after_step"]
        item["company"] = row["company"]
        extractions.append(item)

    if not extractions:
        return (
            "_No human replies have been recorded for this campaign yet — "
            "only automated ones (Auto-Reply / Out Of Office), which are excluded "
            "on purpose. There is nothing to read here until real replies arrive._"
        )

    stats = campaign_conversations.conversation_stats(conn, campaign_id)
    prompt = _SYNTHESIS_PROMPT.format(
        rules=_GROUND_RULES,
        stats=json.dumps(stats, indent=1, default=str),
        extractions=json.dumps(extractions, indent=1, ensure_ascii=False),
    )
    return _write_report(prompt, model or settings.anthropic_model)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_analysis(
    campaign_id: int,
    campaign_name: str = "",
    layers: tuple[str, ...] = ("variants", "conversations"),
    model: str | None = None,
    full_sync: bool = False,
    api_key: str | None = None,
) -> None:
    """Sync, analyze and cache. Runs on a background thread (see app/main.py) —
    a full first sync plus two Claude calls is far past the ~100s Cloudflare
    tunnel timeout, so this must never be awaited by a request.

    `api_key` selects which Smartlead account the sync reads from. It's pinned
    for the whole body via smartlead.use_account so the ~6 scattered Smartlead
    calls downstream all hit the right account without threading it through each
    signature — and, crucially, it's set inside *this* thread, since a ContextVar
    doesn't carry into the worker from the request that spawned it."""
    model = model or settings.anthropic_model

    def stage(text: str) -> None:
        with db.db_session() as conn:
            db.update_campaign_report(conn, campaign_id, stage=text)
        log.info("campaign %s: %s", campaign_id, text)

    with db.db_session() as conn:
        db.start_campaign_report(conn, campaign_id, "Starting…")

    try:
      with smartlead.use_account(api_key):
        campaign_analytics.sync_campaign(campaign_id, full=full_sync, progress=stage)

        report_md = None
        brief = None
        if "variants" in layers:
            stage("Analyzing variants…")
            with db.db_session() as conn:
                report_md, brief = generate_variant_report(conn, campaign_id, campaign_name, model)

        conversation_md = None
        if "conversations" in layers:
            campaign_conversations.sync_conversations(campaign_id, progress=stage)
            extract_conversations(campaign_id, model=model, progress=stage)
            stage("Writing the conversation report…")
            with db.db_session() as conn:
                conversation_md = generate_conversation_report(conn, campaign_id, model)

        fields = {
            "status": "done",
            "stage": None,
            "generated_at": db.now_iso(),
            "model": model,
            "error": None,
        }
        if report_md is not None:
            fields["report_md"] = report_md
            fields["stats_json"] = json.dumps(brief, default=str)
        if conversation_md is not None:
            fields["conversation_md"] = conversation_md
        with db.db_session() as conn:
            db.update_campaign_report(conn, campaign_id, **fields)
        log.info("campaign %s: analysis complete", campaign_id)
    except Exception as exc:
        log.exception("campaign %s: analysis failed", campaign_id)
        with db.db_session() as conn:
            db.update_campaign_report(
                conn, campaign_id, status="failed", stage=None, error=str(exc)[:500]
            )


_running_lock = threading.Lock()
_running: set[int] = set()


def is_running(campaign_id: int) -> bool:
    return campaign_id in _running


def run_analysis_in_background(campaign_id: int, campaign_name: str = "", **kwargs) -> bool:
    """Start run_analysis on a background thread and return immediately.

    Same reason as candidates.generate_for_lead_in_background: a first sync plus
    several Claude calls runs for minutes, far past Cloudflare's ~100s tunnel
    timeout. Returns False if this campaign is already analyzing, so a double
    click or a poll can't stack two runs over the same tables."""
    with _running_lock:
        if campaign_id in _running:
            return False
        _running.add(campaign_id)

    def _worker():
        try:
            run_analysis(campaign_id, campaign_name, **kwargs)
        except Exception:
            log.exception("run_analysis failed for campaign %s", campaign_id)
        finally:
            with _running_lock:
                _running.discard(campaign_id)

    threading.Thread(target=_worker, daemon=True).start()
    return True
