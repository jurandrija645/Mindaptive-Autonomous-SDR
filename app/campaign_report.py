"""The AI half of campaign analysis: turn the numbers and the conversations into
a diagnosis and a plan for the next run.

Two reports, both cached on the campaign_reports row:

- `conversation_md` — a map/reduce over the real conversations, answering what
  moved someone toward a meeting and what lost them. Extraction runs in batches
  and is cached per conversation, so re-analyzing a campaign only pays for
  threads that are new.
- `directives_md` — the short brief on the AI analysis tab: Do this / Don't do
  this / This audience / Next test. Fed BOTH the statistics (with the real
  English copy of every slot) and the conversation extractions, because an
  instruction backed by only one of those is either unexplained or unsupported.

`directives_md` replaced a seven-section essay (`report_md`, still in the schema,
no longer written). The essay restated the data instead of telling Andrew what to
type, and nobody read past the first screen. Anything structural it used to
derive — which component won, what to hold fixed next run, how many sends that
needs — is now computed in `campaign_analytics.recommendations` and rendered as a
panel; the model explains those, it does not decide them.

The prompts carry four hard rules. Three are earned from this data; the fourth
is the app-wide house voice (`prompts/human-writing.md`, via app/writing_rules),
which binds anything this app writes — reports included, not only the emails:

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

from app import (
    campaign_analytics,
    campaign_conversations,
    campaign_copy,
    db,
    smartlead,
    writing_rules,
)
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
   stripped out. "Positive" means any Interested category (including the ones
   naming a specific asset, like "Interested for video") or a booked meeting.
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
4. WRITE THE REPORT ITSELF LIKE A HUMAN. The house style guide below is not
   only for the emails this app drafts — it binds this report too. A brief that
   reads like a consultancy deck is a brief nobody finishes.
"""


def _ground_rules() -> str:
    """The three data rules plus the house voice.

    Composed at call time rather than baked in as a constant so editing
    `prompts/human-writing.md` changes the reports without a code change — the
    same contract the SDR prompt and the knowledge base already have."""
    return _GROUND_RULES + writing_rules.as_section()


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
    """Everything the report reasons over — including what the copy actually says.

    Every slot entry carries the real English sentence it inserts and the funnel
    stage it belongs to, and every variant carries the whole email as a reader
    would see it. A critique of `{{CTA1}}` is worthless unless the model has read
    what CTA1 says, and the first version of this brief shipped tokens only."""
    outcomes = campaign_analytics.lead_outcomes(conn, campaign_id)
    summary = campaign_analytics.campaign_summary(conn, campaign_id, outcomes)
    slots = campaign_analytics.slot_metrics(conn, campaign_id, outcomes)
    texts = campaign_copy.slot_text_map(conn, campaign_id)
    emails = campaign_copy.variant_emails(conn, campaign_id)

    for role, entries in slots.items():
        stage = campaign_analytics.stage_of(role)
        for entry in entries:
            text = texts.get(entry["slot"]) or {}
            entry["text"] = text.get("display") or ""
            entry["personalized"] = bool(text.get("personalized"))
            entry["examples"] = text.get("examples") or []
            entry["stage"] = stage
            entry["judged_on"] = campaign_analytics.STAGE_METRIC[stage]["label"]

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

    variants = campaign_analytics.variant_metrics(conn, campaign_id, outcomes)
    for variant in variants:
        email = emails.get(variant["seq_variant_id"]) or {}
        variant["subject_as_sent"] = email.get("subject") or ""
        variant["body_as_sent"] = email.get("body") or ""

    return {
        "campaign": {"id": campaign_id, "name": campaign_name, **settings_row},
        "totals": summary,
        "variants": variants,
        "slots": slots,
        "recommendations": campaign_analytics.recommendations(
            conn, campaign_id, outcomes, texts
        ),
        "rendered_subjects": campaign_analytics.subject_metrics(
            conn, campaign_id, outcomes=outcomes
        ),
        "reply_by_step": campaign_analytics.reply_step_metrics(conn, campaign_id, outcomes),
    }


_DIRECTIVES_PROMPT = """\
You are a cold-email strategist briefing Mindaptive.ai (AI receptionist /
lead-response automation for small service businesses) on one outbound campaign.

{rules}

WHAT THIS OUTPUT IS FOR. Andrew writes the next campaign and answers replies by
hand. He does not want an essay about this campaign — he wants a short set of
instructions he can follow while writing. Every line must be something he can
DO. If a line does not change what he types, delete it.

HOW THE MESSAGES ARE BUILT. Each A/B variant is a recipe of slots — a subject, an
icebreaker, a pitch, an offer, a CTA — and the same slot value is reused across
several variants, so a slot's numbers pool every variant that uses it. Each slot
entry carries `text`: the real sentence it inserts. Judge that text. Quote it.

WHICH NUMBER JUDGES WHICH PART. The subject line and the icebreaker are all the
reader sees before deciding whether to answer, so they are judged on REPLY RATE —
with open tracking off, replies are our only proxy for "this got read". The
pitch, offer and CTA sit below that decision, so they are judged on the POSITIVE
SHARE OF REPLIES: of the people who did answer, how many answered well. Each slot
entry states its own `stage` and `judged_on`. Never say a CTA "has a low reply
rate" — the CTA did not earn the reply, the subject line did.

THE `recommendations` BLOCK IS ALREADY DECIDED. It was computed statistically,
not by you. Do not overturn it, re-rank it, or contradict a `status`. Your job is
to explain each one in a sentence a person can act on, and to add the copy
judgement the maths cannot make.

ENGLISH ONLY. This campaign may have gone out in several languages. All copy in
the data has been resolved to English. Write only in English, never mention
translation, localisation, or any language as a factor, and never claim one
language performs differently — that was never measured.

THE NUMBERS AND THE COPY:
```json
{brief}
```

WHAT LEADS ACTUALLY WROTE BACK (already extracted per conversation):
```json
{conversations}
```

Write markdown with exactly these four sections and nothing else. HARD LIMIT:
about one screen. No preamble, no summary of the campaign, no restating the data.

## Do this
5–7 bullets, most important first. Each is an instruction with the reason and the
number attached, in this shape:
**Instruction.** Why it works, with the count. e.g.
**Open with the booking-process question, not the AI pitch.** It pulled 23 of 42
replies; the pitch-first opening pulled 10.
Cover the subject line, the opening line, the offer and the CTA. If a component
is unresolved, the instruction is "keep using X for now" — say so plainly rather
than inventing a preference.

## Don't do this
4–6 bullets, same shape. Each must name something concretely present in the copy
or the replies — a phrase, a structure, a length, an ask — and why it costs. No
generic cold-email advice.

## This audience
3–4 bullets on what these specific people care about and react badly to, each
backed by a verbatim quote from a real reply. This is the section that tells
Andrew how to talk to them once they answer.

## Next test
The plan from `recommendations.next_test`, in 3–5 lines: what to hold fixed
(name the actual copy), the one thing to vary, and how many sends per arm it
needs before it can be read. Then, if you are proposing new copy for the varied
slot, write it out ready to paste — no more than two options.
"""


def generate_directives(
    conn, campaign_id: int, campaign_name: str = "", model: str | None = None
) -> tuple[str, dict]:
    """The short brief shown on the AI analysis tab.

    Fed both layers on purpose: the numbers say which CTA won, the conversations
    say why, and an instruction with only one of those behind it is either
    unexplained or unsupported."""
    brief = build_stats_brief(conn, campaign_id, campaign_name)
    prompt = _DIRECTIVES_PROMPT.format(
        rules=_ground_rules(),
        brief=json.dumps(brief, indent=1, default=str),
        conversations=json.dumps(
            _extraction_records(conn, campaign_id), indent=1, ensure_ascii=False, default=str
        ),
    )
    return _write_report(prompt, model or settings.anthropic_model), brief


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
  reacted to. Never paraphrase; copy their words in the language they wrote in.
- "trigger_en": that same quote in English. If they already wrote in English,
  repeat it unchanged. This is the one that gets shown, so it must read as
  natural English, not a word-for-word gloss.
- "friction": anything they misread, doubted, or found confusing — verbatim if
  possible, else null.
- "friction_en": the English of "friction", same rule, or null.
- "salvageable": true/false — could a different angle still win this lead?
- "salvage_angle": one sentence IN ENGLISH on what that angle would be, or null.

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


# Bump when the extraction schema changes. Cached extractions from an older
# version are re-run, because a field added to the prompt (the English quote)
# would otherwise never appear on the conversations extracted before it existed
# — and those are most of them.
_EXTRACT_VERSION = 2


def _needs_extraction(row) -> bool:
    if not row["extract_json"]:
        return True
    try:
        return json.loads(row["extract_json"]).get("_v") != _EXTRACT_VERSION
    except (ValueError, AttributeError):
        return True


def extract_conversations(campaign_id: int, model: str | None = None, progress=None) -> int:
    """Map step: structured extraction per conversation, cached on the row.

    Only conversations without a current cached extraction are sent, so a
    re-analysis after a few new replies costs a fraction of the first run."""
    model = model or settings.anthropic_model
    with db.db_session() as conn:
        pending = [
            campaign_conversations.thread_for_prompt(row)
            for row in db.list_campaign_conversations(conn, campaign_id)
            if _needs_extraction(row)
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
                extraction["_v"] = _EXTRACT_VERSION
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

WHAT THIS IS FOR. Andrew answers these replies by hand. The question this report
exists to answer is: **what did we say that moved someone toward a meeting, and
what did we say that lost them?** Not "here is a list of the conversations" — he
can read those himself. Every claim must be a pattern across conversations, with
a count and a quote.

Additional rules for this part:
- QUOTE, NEVER PARAPHRASE, when citing what a lead said. The quotes are how this
  report gets fact-checked.
- COUNT, NEVER ESTIMATE. The counts are given to you below; use them.
- If a pattern rests on fewer than 5 conversations, say so in the sentence where
  you claim it.
- ENGLISH ONLY. Replies arrived in several languages; write everything in
  English, translate any quote you cite, and never treat language as a factor —
  it was not measured.
- SEPARATE THE WIN FROM THE LOSS. A conversation that reached "Meeting-Booked" or
  any "Interested" category is a win; "Not Interested" and "Do Not Contact" are
  losses. Contrast them explicitly — the whole value here is the difference.

COUNTS (already computed — do not recompute):
```json
{stats}
```

PER-CONVERSATION EXTRACTIONS:
```json
{extractions}
```

Write a markdown report with exactly these sections. Keep it tight — a
paragraph and a few bullets each, never a wall.

## What moves people toward a meeting
The patterns shared by the conversations that ended positively: what we said, at
which step, and how they answered. Counts and quotes. If the positive
conversations have nothing in common, say that.

## What loses them
The patterns shared by the rejections and the silences after a first reply.
Name the specific ask, phrase or structure that preceded each, quoted.

## Objections, ranked
Each objection type with its count and one verbatim quote, most common first,
and the one sentence that answers it best.

## What they asked us for
Which assets leads requested, in their own words, and which of our offers nobody
ever asked about. If nobody asked for an asset, say so and say what it implies.

## How to run the conversation after a first reply
The practical script: what to send first, what to never send, when to push for
the meeting and when to hold back. This is what the app's own reply drafts
should follow.

## Playbook edits
3–5 concrete instructions for `prompts/system.md`, each phrased so Andrew can
paste it straight in. No rewriting of the whole file.
"""


def _extraction_records(conn, campaign_id: int) -> list[dict]:
    """The per-conversation extractions, joined to the outcome each one had.

    `category` is what makes the report possible: without it the model can see
    what a lead said but not whether the conversation ended in a meeting."""
    records = []
    for row in db.list_campaign_conversations(conn, campaign_id):
        if not row["extract_json"]:
            continue
        try:
            item = json.loads(row["extract_json"])
        except ValueError:
            continue
        item["category"] = row["category"]
        item["outcome"] = (
            "positive" if campaign_analytics.is_positive(row["category"]) else "not_positive"
        )
        item["variant"] = row["variant_label"]
        item["replied_after_step"] = row["first_reply_after_step"]
        item["their_message_count"] = row["their_msg_count"]
        item["company"] = row["company"]
        records.append(item)
    return records


def generate_conversation_report(conn, campaign_id: int, model: str | None = None) -> str:
    extractions = _extraction_records(conn, campaign_id)

    if not extractions:
        return (
            "_No human replies have been recorded for this campaign yet — "
            "only automated ones (Auto-Reply / Out Of Office), which are excluded "
            "on purpose. There is nothing to read here until real replies arrive._"
        )

    stats = campaign_conversations.conversation_stats(conn, campaign_id)
    prompt = _SYNTHESIS_PROMPT.format(
        rules=_ground_rules(),
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
        # Only campaigns that ran in no English at all pay for this; an
        # all-English campaign finds nothing to translate and makes no call.
        with db.db_session() as conn:
            campaign_copy.translate_slot_texts(conn, campaign_id, model=model, progress=stage)

        # Conversations run first: the directives brief is fed the extractions,
        # so "this CTA wins" can be explained by what people actually wrote.
        conversation_md = None
        if "conversations" in layers:
            campaign_conversations.sync_conversations(campaign_id, progress=stage)
            extract_conversations(campaign_id, model=model, progress=stage)
            stage("Working out what wins and what loses conversations…")
            with db.db_session() as conn:
                conversation_md = generate_conversation_report(conn, campaign_id, model)

        directives_md = None
        brief = None
        if "variants" in layers:
            stage("Writing the brief for the next run…")
            with db.db_session() as conn:
                directives_md, brief = generate_directives(
                    conn, campaign_id, campaign_name, model
                )

        fields = {
            "status": "done",
            "stage": None,
            "generated_at": db.now_iso(),
            "model": model,
            "error": None,
        }
        if directives_md is not None:
            fields["directives_md"] = directives_md
            fields["stats_json"] = json.dumps(brief, default=str)
            # The long-form essay this replaced is no longer written; clear any
            # cached copy so the tab can't serve the old wall of text.
            fields["report_md"] = None
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
