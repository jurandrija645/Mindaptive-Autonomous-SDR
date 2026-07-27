"""Quantitative campaign analysis — which message variant actually earns replies.

The core idea: a Smartlead A/B variant is not an opaque blob, it's a *recipe of
slots*. Campaign 3640877's six step-1 variants are all
`{{subjectLineN}} + {{Greeting}} + {{icebreaker*}} + {{PitchN}} + {{OfferN}} +
{{CTAN}} + {{Goodbye}}`, differing only in which numbered slot value each one
picks. Slots therefore repeat across variants — CTA1 appears in both A and C,
Pitch2 in C, D, E and F.

That means we can measure a *slot* by pooling every variant that uses it, which
gives 2-3x the sample of a six-way variant split. With ~117 replies spread over
six variants, the variant-level split is mostly noise; the slot-level split is
where a real signal can appear. Both are computed, but the slot view is the one
worth acting on.

Two constraints this module exists to respect:

1. Open and click tracking are deliberately off on this account
   (`DONT_EMAIL_OPEN` / `DONT_LINK_CLICK` — they hurt deliverability), so
   `open_count` is 0 on every row. Replies are the only outcome signal. No open
   or click rate is computed anywhere here, on purpose.
2. The samples are small. Every rate ships with a Wilson confidence interval and
   a verdict label, so `Not enough data` is a first-class answer rather than a
   ranking of noise.
"""

import csv
import io
import json
import logging
import math
import re
from collections import Counter, defaultdict
from typing import Any, Iterable

from app import db, smartlead

log = logging.getLogger("campaign_analytics")

# A reply Smartlead filed under one of these is a robot, not a person. They are
# excluded from every reply rate — leaving them in badly distorts the ranking
# (a 20-reply sample from campaign 3640877 was 11 Auto-Reply + 5 Out Of Office).
ROBOT_CATEGORIES = {
    "auto-reply",
    "auto reply",
    "out of office",
    "sender originated bounce",
}

# What counts as a win. Every `Interested*` category plus a booked meeting.
#
# The magnet-specific categories ("Interested for video", "Interested for
# toolkit", "Interested for calculator") used to be excluded, which left 0-5
# positives per variant on a six-way split — every comparison collapsed to
# `not_enough_data` and the positive column ranked nothing. Someone who asks for
# the video is a lead who put their hand up, so they count; Meeting-Booked is
# still reported on its own as the strongest signal.
POSITIVE_PREFIXES = ("interested", "meeting")
# Guard against the categories that merely *contain* a positive word.
NEGATIVE_CATEGORIES = {"not interested", "do not contact", "wrong person"}

# Rates below these are reported but never ranked — see verdict().
MIN_DELIVERED = 300
MIN_REPLIES = 10
# Conversion ("of those who replied, how many were interested") is measured over
# repliers, a denominator two orders of magnitude smaller than delivered.
MIN_CONVERSION_TRIALS = 15
MIN_CONVERSION_SUCCESSES = 3

_SLOT_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

# Slot names are hand-written per campaign and drift in style: `subjectLine1`,
# `SubjectLine1_translated`, `Icebreaker1` vs `icebreaker2`, `CTAprototype`.
# Roles are matched on the normalized stem so all three active campaigns bucket
# the same way.
_ROLE_PATTERNS = [
    ("subject", ("subjectline", "subject")),
    ("greeting", ("greeting",)),
    ("icebreaker", ("icebreaker",)),
    ("pitch", ("pitch",)),
    ("painpoint", ("painpoint", "pain")),
    ("socialproof", ("socialproof", "proof", "casestudy")),
    ("offer", ("offer",)),
    ("cta", ("cta", "calltoaction")),
    ("signoff", ("goodbye", "signoff", "signature")),
    ("followup", ("followup",)),
]


def normalize_category(value: str | None) -> str:
    return (value or "").strip().lower()


def is_robot(category: str | None) -> bool:
    return normalize_category(category) in ROBOT_CATEGORIES


def is_positive(category: str | None) -> bool:
    value = normalize_category(category)
    if value in NEGATIVE_CATEGORIES:
        return False
    return value.startswith(POSITIVE_PREFIXES)


def is_booked(category: str | None) -> bool:
    """The hard win, reported separately from the wider `positive`. "Meeting
    Request" is a lead asking for one, not one on the calendar, so it counts as
    positive but not as booked."""
    return normalize_category(category).replace("-", " ").startswith("meeting booked")


# ---------------------------------------------------------------------------
# Slot parsing
# ---------------------------------------------------------------------------

def parse_slots(subject: str | None, body: str | None) -> list[str]:
    """Every {{variable}} in a variant, in order, deduped. This is the variant's
    recipe — what makes two variants comparable slot by slot."""
    found = _SLOT_RE.findall(f"{subject or ''}\n{body or ''}")
    return list(dict.fromkeys(found))


def _stem(token: str) -> str:
    """`SubjectLine1_translated` -> `subjectline`. Strips the translation suffix
    (SolarPanel's slots all carry it), trailing digits, and separators, so the
    numbered siblings of one role collapse onto the same stem."""
    stem = token.lower()
    for suffix in ("_translated", "_translation", "translated"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    stem = stem.strip("_")
    stem = re.sub(r"[_\s-]", "", stem)
    return re.sub(r"\d+$", "", stem)


def slot_role(token: str) -> str:
    """Bucket a slot into the part of the message it fills. `other` is a real
    answer for per-lead data like `first_name` or `Address` — those are
    personalization, not a testable message component."""
    stem = _stem(token)
    for role, prefixes in _ROLE_PATTERNS:
        if any(stem.startswith(prefix) for prefix in prefixes):
            return role
    return "other"


# Roles worth ranking. `greeting`, `signoff` and `other` vary per lead rather
# than per variant, so pooling them measures the audience, not the copy.
TESTABLE_ROLES = ("subject", "icebreaker", "pitch", "painpoint", "socialproof", "offer", "cta")


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval. Chosen over the normal approximation because
    it stays sane at the tiny counts and near-zero rates this data actually has
    (3 positives out of 1,200 sends would give a nonsensical negative lower
    bound under the normal approximation). Pure stdlib — no scipy dependency."""
    if trials <= 0:
        return (0.0, 0.0)
    phat = successes / trials
    denominator = 1 + z * z / trials
    center = phat + z * z / (2 * trials)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * trials)) / trials)
    return (
        max(0.0, (center - margin) / denominator),
        min(1.0, (center + margin) / denominator),
    )


def verdict(
    successes: int,
    trials: int,
    baseline: float,
    min_trials: int = MIN_DELIVERED,
    min_successes: int = MIN_REPLIES,
) -> str:
    """How much to trust this row against the campaign's own baseline rate.

    `not_enough_data` is deliberately returned before any comparison: with a
    handful of replies per variant, a "winner" is usually noise, and the report
    is instructed never to call one on this label.

    The thresholds are arguments because the two questions this module asks have
    very different denominators: "did they reply" is measured over ~500
    delivered emails per variant, "did the reply go well" over the ~20 people
    who actually answered."""
    if trials < min_trials or successes < min_successes:
        return "not_enough_data"
    low, high = wilson_interval(successes, trials)
    if low > baseline:
        return "solid_above"
    if high < baseline:
        return "solid_below"
    rate = successes / trials
    return "leaning_above" if rate > baseline else "leaning_below"


def _metrics(rows: Iterable[dict]) -> dict:
    """Outcome counts for one bucket of sends. `delivered` is the denominator
    for every rate: a bounced email was never read by anyone, so counting it
    against the copy would penalize whichever variant happened to draw more
    dead addresses.

    Two traps in the raw data, both verified against campaign 3640877:

    - `lead_category` is a *lead-level* label Smartlead stamps on every one of
      that lead's send rows, including ones that drew no reply at all (84 such
      rows on this campaign). Only `reply_time` marks an actual reply; the
      category merely classifies it.
    - One reply shows up on several rows when the lead was mid-sequence — the
      same Out Of Office appears against both step 1 and step 2. Replies are
      therefore counted per unique lead, so a bucket spanning steps can't count
      one person twice.
    """
    sent = bounced = unsubscribed = 0
    replied_leads: dict[str, str | None] = {}
    for row in rows:
        sent += 1
        if row["is_bounced"]:
            bounced += 1
        if row["is_unsubscribed"]:
            unsubscribed += 1
        if row["reply_time"]:
            key = row["lead_email"] or row["stats_id"]
            # Keep the most decisive label if the same lead is seen twice: a
            # human category beats a robot one.
            existing = replied_leads.get(key)
            if key not in replied_leads or (is_robot(existing) and not is_robot(row["lead_category"])):
                replied_leads[key] = row["lead_category"]

    robots = sum(1 for category in replied_leads.values() if is_robot(category))
    human = [category for category in replied_leads.values() if not is_robot(category)]
    replies = len(human)
    positives = sum(1 for category in human if is_positive(category))
    delivered = sent - bounced
    return {
        "sent": sent,
        "bounced": bounced,
        "delivered": delivered,
        "unsubscribed": unsubscribed,
        "robot_replies": robots,
        "replies": replies,
        "positives": positives,
        "booked": sum(1 for category in human if is_booked(category)),
        "bounce_rate": bounced / sent if sent else 0.0,
        "reply_rate": replies / delivered if delivered else 0.0,
        "positive_rate": positives / delivered if delivered else 0.0,
        # Of the people who did answer, how many answered *well*. This is the
        # number that isolates the bottom of the email (offer, CTA) from the
        # top (subject, icebreaker) — see ROLE_STAGE.
        "positive_per_reply": positives / replies if replies else 0.0,
    }


def _with_verdicts(
    bucket: dict,
    reply_baseline: float,
    positive_baseline: float,
    conversion_baseline: float = 0.0,
) -> dict:
    delivered = bucket["delivered"]
    replies = bucket["replies"]
    reply_low, reply_high = wilson_interval(replies, delivered)
    pos_low, pos_high = wilson_interval(bucket["positives"], delivered)
    conv_low, conv_high = wilson_interval(bucket["positives"], replies)
    bucket["reply_ci"] = [round(reply_low, 5), round(reply_high, 5)]
    bucket["positive_ci"] = [round(pos_low, 5), round(pos_high, 5)]
    bucket["conversion_ci"] = [round(conv_low, 5), round(conv_high, 5)]
    bucket["reply_verdict"] = verdict(replies, delivered, reply_baseline)
    bucket["positive_verdict"] = verdict(bucket["positives"], delivered, positive_baseline)
    # Conversion is measured over repliers, not over delivered, so it needs its
    # own (much smaller) thresholds — 20 replies is a real sample for "of the
    # people who answered, how many answered well", while 20 delivered is not.
    bucket["conversion_verdict"] = verdict(
        bucket["positives"],
        replies,
        conversion_baseline,
        min_trials=MIN_CONVERSION_TRIALS,
        min_successes=MIN_CONVERSION_SUCCESSES,
    )
    return bucket


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def _statistics_row(campaign_id: int, raw: dict) -> dict | None:
    stats_id = raw.get("stats_id")
    if not stats_id:
        return None
    return {
        "stats_id": stats_id,
        "campaign_id": campaign_id,
        "lead_email": (raw.get("lead_email") or "").strip().lower() or None,
        "sequence_number": _as_int(raw.get("sequence_number")),
        "email_campaign_seq_id": _as_int(raw.get("email_campaign_seq_id")),
        "seq_variant_id": _as_int(raw.get("seq_variant_id")),
        "email_subject": raw.get("email_subject"),
        "sent_time": raw.get("sent_time"),
        "reply_time": raw.get("reply_time"),
        "lead_category": raw.get("lead_category"),
        "is_bounced": 1 if raw.get("is_bounced") else 0,
        "is_unsubscribed": 1 if raw.get("is_unsubscribed") else 0,
        "click_time": raw.get("click_time"),
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sync_variants(campaign_id: int) -> int:
    """Mirror the campaign's sequence variants and parse each one's slot recipe."""
    steps = smartlead.get_campaign_sequences(campaign_id)
    rows = []
    for step in steps:
        seq_number = _as_int(step.get("seq_number"))
        variants = step.get("sequence_variants") or step.get("seq_variants") or []
        if not variants:
            # A step with no A/B variants still has one implicit message. Record
            # it under a negative pseudo-id so follow-up steps show up in the
            # variant table instead of silently vanishing.
            rows.append(
                {
                    "campaign_id": campaign_id,
                    "seq_variant_id": -(seq_number or 0),
                    "seq_number": seq_number,
                    "variant_label": "—",
                    "subject_template": step.get("subject"),
                    "body_template": step.get("email_body"),
                    "slots_json": json.dumps(
                        parse_slots(step.get("subject"), step.get("email_body"))
                    ),
                }
            )
            continue
        for variant in variants:
            rows.append(
                {
                    "campaign_id": campaign_id,
                    "seq_variant_id": _as_int(variant.get("id")),
                    "seq_number": seq_number,
                    "variant_label": variant.get("variant_label") or variant.get("variant_name"),
                    "subject_template": variant.get("subject"),
                    "body_template": variant.get("email_body"),
                    "slots_json": json.dumps(
                        parse_slots(variant.get("subject"), variant.get("email_body"))
                    ),
                }
            )
    with db.db_session() as conn:
        db.replace_campaign_variants(conn, campaign_id, rows)
    return len(rows)


def sync_sends(campaign_id: int, full: bool = False, progress=None) -> int:
    """Pull per-send statistics rows. Incremental by default: only sends newer
    than the last synced `sent_time` are fetched, because a full pull carries
    the rendered body of every email (~10 KB/row, ~75 MB for a 7.5k-send
    campaign) and only needs to happen once.

    A small overlap window is intentional — re-fetching the last synced
    timestamp catches replies that arrived after a send was first recorded, and
    the upsert is keyed on stats_id so nothing duplicates."""
    since = None
    if not full:
        with db.db_session() as conn:
            existing = db.get_campaign_sync(conn, campaign_id)
        since = existing["last_sent_time"] if existing else None

    batch: list[dict] = []
    total = 0
    newest = since
    for raw in smartlead.iter_campaign_statistics(campaign_id, sent_time_start_date=since):
        row = _statistics_row(campaign_id, raw)
        if row is None:
            continue
        batch.append(row)
        if row["sent_time"] and (newest is None or row["sent_time"] > newest):
            newest = row["sent_time"]
        if len(batch) >= 1000:
            with db.db_session() as conn:
                total += db.upsert_campaign_sends(conn, batch)
            batch = []
            if progress:
                progress(f"Synced {total:,} sends…")
    if batch:
        with db.db_session() as conn:
            total += db.upsert_campaign_sends(conn, batch)

    with db.db_session() as conn:
        db.update_campaign_sync(
            conn, campaign_id, last_sent_time=newest, sends_synced_at=db.now_iso()
        )
    log.info("campaign %s: synced %d sends (since=%s)", campaign_id, total, since)
    return total


def sync_lead_vars(campaign_id: int, progress=None) -> int:
    """Parse the leads-export CSV into campaign_lead_vars — the campaign's source
    variables, plus the email -> lead_id map the conversation sync needs."""
    if progress:
        progress("Downloading lead export…")
    text = smartlead.export_campaign_leads_csv(campaign_id)
    if not text:
        return 0
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        email = (record.get("email") or "").strip().lower()
        if not email:
            continue
        rows.append(
            {
                "campaign_id": campaign_id,
                "lead_email": email,
                "lead_id": (record.get("id") or "").strip() or None,
                "company_name": record.get("company_name") or None,
                "category": record.get("category") or None,
                "reply_count": _as_int(record.get("reply_count")) or 0,
                "last_email_sequence_sent": _as_int(record.get("last_email_sequence_sent")),
                "custom_fields_json": record.get("custom_fields") or "{}",
            }
        )
    written = 0
    for start in range(0, len(rows), 500):
        with db.db_session() as conn:
            written += db.upsert_campaign_lead_vars(conn, rows[start : start + 500])
    with db.db_session() as conn:
        db.update_campaign_sync(conn, campaign_id, vars_synced_at=db.now_iso())
    log.info("campaign %s: synced %d lead variable rows", campaign_id, written)
    return written


def sync_campaign(campaign_id: int, full: bool = False, progress=None) -> dict:
    if progress:
        progress("Reading sequence variants…")
    variants = sync_variants(campaign_id)
    if progress:
        progress("Reading send statistics…")
    sends = sync_sends(campaign_id, full=full, progress=progress)
    lead_vars = sync_lead_vars(campaign_id, progress=progress)

    # Imported late: campaign_copy reads slot_role from this module, so importing
    # it at the top would close the cycle.
    from app import campaign_copy

    if progress:
        progress("Reading what each message component says…")
    with db.db_session() as conn:
        slot_texts = campaign_copy.sync_slot_texts(conn, campaign_id)
    return {
        "variants": variants,
        "sends": sends,
        "lead_vars": lead_vars,
        "slot_texts": slot_texts,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _load(conn, campaign_id: int, step: int | None = 1) -> list[dict]:
    sql = "SELECT * FROM campaign_sends WHERE campaign_id = ?"
    params: list[Any] = [campaign_id]
    if step is not None:
        sql += " AND sequence_number = ?"
        params.append(step)
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def baselines(rows: list[dict]) -> tuple[float, float, float]:
    return _baselines_of(_metrics(rows))


def _baselines_of(overall: dict) -> tuple[float, float, float]:
    """The three campaign-wide rates every row is judged against: reply rate,
    positive rate, and positives-per-reply."""
    return overall["reply_rate"], overall["positive_rate"], overall["positive_per_reply"]


def lead_outcomes(conn, campaign_id: int) -> list[dict]:
    """One record per lead who entered the sequence, carrying the step-1 variant
    they were assigned and whether they *ever* replied.

    Attribution is deliberately sequence-wide rather than step-wise. Only step 1
    has A/B variants — steps 2-4 are a single shared follow-up — so the variant
    is the only thing that differs between two leads, and a reply at step 2 is
    still a reply to the sequence that variant opened. Scoring on step-1 rows
    alone threw away two thirds of the evidence (14 human replies instead of
    42) and biased the result toward whichever variant happened to provoke an
    immediate answer.
    """
    rows = _load(conn, campaign_id, step=None)
    by_lead: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = row["lead_email"] or row["stats_id"]
        by_lead[key].append(row)

    outcomes = []
    for lead_email, lead_rows in by_lead.items():
        lead_rows.sort(key=lambda row: (row["sequence_number"] or 0, row["sent_time"] or ""))
        first = next((row for row in lead_rows if row["sequence_number"] == 1), lead_rows[0])
        replies = [row for row in lead_rows if row["reply_time"]]
        human = [row for row in replies if not is_robot(row["lead_category"])]
        first_human = min(human, key=lambda row: row["reply_time"]) if human else None
        outcomes.append(
            {
                "lead_email": lead_email,
                "seq_variant_id": first["seq_variant_id"],
                "email_subject": first["email_subject"],
                "sent_time": first["sent_time"],
                "steps_sent": len(lead_rows),
                # A step-1 bounce means the address is dead; the copy never had
                # a chance, so these leave the denominator entirely.
                "bounced": any(row["is_bounced"] for row in lead_rows),
                "unsubscribed": any(row["is_unsubscribed"] for row in lead_rows),
                "robot_reply": bool(replies) and not human,
                "replied": first_human is not None,
                "category": first_human["lead_category"] if first_human else None,
                "positive": bool(first_human and is_positive(first_human["lead_category"])),
                "reply_step": first_human["sequence_number"] if first_human else None,
            }
        )
    return outcomes


def _lead_metrics(outcomes: Iterable[dict]) -> dict:
    """Same shape as _metrics, but over lead records rather than send rows."""
    outcomes = list(outcomes)
    sent = len(outcomes)
    bounced = sum(1 for o in outcomes if o["bounced"])
    delivered = sent - bounced
    replies = sum(1 for o in outcomes if o["replied"])
    positives = sum(1 for o in outcomes if o["positive"])
    return {
        "sent": sent,
        "bounced": bounced,
        "delivered": delivered,
        "unsubscribed": sum(1 for o in outcomes if o["unsubscribed"]),
        "robot_replies": sum(1 for o in outcomes if o["robot_reply"]),
        "replies": replies,
        "positives": positives,
        "booked": sum(1 for o in outcomes if is_booked(o["category"])),
        "bounce_rate": bounced / sent if sent else 0.0,
        "reply_rate": replies / delivered if delivered else 0.0,
        "positive_rate": positives / delivered if delivered else 0.0,
        "positive_per_reply": positives / replies if replies else 0.0,
    }


def variant_metrics(conn, campaign_id: int, outcomes: list[dict] | None = None) -> list[dict]:
    """Per-variant outcomes, attributed across the whole sequence (see
    lead_outcomes).

    Reported for completeness, but six variants splitting ~40 human replies
    means most rows land on `not_enough_data`; slot_metrics is where the usable
    signal is."""
    outcomes = lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    overall = _lead_metrics(outcomes)
    reply_base, positive_base, conv_base = _baselines_of(overall)
    variants = {v["seq_variant_id"]: dict(v) for v in db.list_campaign_variants(conn, campaign_id)}

    grouped: dict[int | None, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome["seq_variant_id"]].append(outcome)

    out = []
    for variant_id, bucket in grouped.items():
        meta = variants.get(variant_id, {})
        slots = json.loads(meta.get("slots_json") or "[]")
        entry = _with_verdicts(_lead_metrics(bucket), reply_base, positive_base, conv_base)
        entry.update(
            {
                "seq_variant_id": variant_id,
                "variant_label": meta.get("variant_label") or "?",
                "subject_template": meta.get("subject_template"),
                "slots": slots,
                "recipe": {
                    role: [s for s in slots if slot_role(s) == role]
                    for role in TESTABLE_ROLES
                    if any(slot_role(s) == role for s in slots)
                },
            }
        )
        out.append(entry)
    out.sort(key=lambda entry: (-entry["positive_rate"], -entry["reply_rate"]))
    return out


def slot_metrics(conn, campaign_id: int, outcomes: list[dict] | None = None) -> dict[str, list[dict]]:
    """The headline analysis: outcomes per slot value, pooling every variant that
    uses it. CTA1's numbers are variants A and C combined, so the comparison
    against CTA2 (B and D) rests on roughly double the sample a single variant
    would give."""
    outcomes = lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    overall = _lead_metrics(outcomes)
    reply_base, positive_base, conv_base = _baselines_of(overall)
    variants = {v["seq_variant_id"]: dict(v) for v in db.list_campaign_variants(conn, campaign_id)}

    by_variant: dict[int | None, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        by_variant[outcome["seq_variant_id"]].append(outcome)

    # role -> slot token -> pooled sends
    pooled: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    users: dict[str, set[str]] = defaultdict(set)
    for variant_id, bucket in by_variant.items():
        meta = variants.get(variant_id)
        if not meta:
            continue
        label = meta.get("variant_label") or "?"
        for token in json.loads(meta.get("slots_json") or "[]"):
            role = slot_role(token)
            if role not in TESTABLE_ROLES:
                continue
            pooled[role][token].extend(bucket)
            users[token].add(label)

    out: dict[str, list[dict]] = {}
    for role, tokens in pooled.items():
        entries = []
        for token, bucket in tokens.items():
            entry = _with_verdicts(_lead_metrics(bucket), reply_base, positive_base, conv_base)
            entry.update(
                {
                    "slot": token,
                    "role": role,
                    "used_by": sorted(users[token]),
                }
            )
            entries.append(entry)
        entries.sort(key=lambda entry: (-entry["positive_rate"], -entry["reply_rate"]))
        out[role] = entries
    return out


# ---------------------------------------------------------------------------
# Which number judges which part of the email
# ---------------------------------------------------------------------------

# A reader meets the email in two stages, and the same number cannot judge both.
#
# The subject line and the icebreaker are all that is visible before the decision
# to keep reading — with open tracking off, the reply rate is the only proxy we
# have for "this got opened and held attention", so those two roles are judged on
# it. Everything below the fold (pitch, pain point, proof, offer, CTA) is only
# read by someone who already got that far, so judging it on reply rate mostly
# re-measures the subject line above it. Those are judged on how many of the
# people who *did* reply replied positively.
#
# This is Andrew's own framing and it is the difference between "variant B is
# worse" and "variant B's subject works, its CTA doesn't".
ROLE_STAGE = {
    "subject": "attention",
    "icebreaker": "attention",
    "pitch": "conversion",
    "painpoint": "conversion",
    "socialproof": "conversion",
    "offer": "conversion",
    "cta": "conversion",
}

STAGE_METRIC = {
    "attention": {
        "rate": "reply_rate",
        "verdict": "reply_verdict",
        "ci": "reply_ci",
        "successes": "replies",
        "trials": "delivered",
        "label": "reply rate",
        "why": "the subject line and opening are all the reader sees before deciding to reply, so replies measure them",
    },
    "conversion": {
        "rate": "positive_per_reply",
        "verdict": "conversion_verdict",
        "ci": "conversion_ci",
        "successes": "positives",
        "trials": "replies",
        "label": "positive share of replies",
        "why": "this part is only read by someone already reading, so it is judged on how well the replies it drew turned out",
    },
}


def stage_of(role: str) -> str:
    return ROLE_STAGE.get(role, "conversion")


# Which unresolved role is worth spending the next run on, best first. Attention
# gates everything underneath it: a better CTA on an email nobody answers is
# worth nothing, so the top of the message gets resolved first.
_TEST_PRIORITY = ("subject", "icebreaker", "cta", "offer", "pitch", "painpoint", "socialproof")


def required_per_arm(baseline: float, relative_lift: float = 0.5) -> int:
    """Sends per arm needed to see a `relative_lift` change at ~80% power, 95%.

    The usual two-proportion formula, reduced: n = 16·p(1-p)/Δ². It exists to
    make "not enough data" a number Andrew can plan around instead of a shrug —
    at a 4% reply rate, resolving a 50% difference needs ~1,500 sends per arm,
    which is the honest reason six variants over 2,900 leads resolved nothing."""
    if baseline <= 0 or baseline >= 1:
        return 0
    delta = baseline * relative_lift
    return int(math.ceil(16 * baseline * (1 - baseline) / (delta * delta)))


def _separation(top: dict, rest: dict, metric: dict) -> str:
    """Does the leader actually clear the field, or is it just ahead?

    Compares the two Wilson intervals directly rather than each against the
    campaign baseline: "CTA1 beats CTA2" is the question being asked, and both
    can sit above baseline while being indistinguishable from each other."""
    if not top or not rest:
        return "unresolved"
    if top[metric["trials"]] < 1 or rest[metric["trials"]] < 1:
        return "unresolved"
    # The *leader* must have a real sample of its own. Without this line every
    # role on campaign 3640877 came back "ahead, not proven" off 2 positives out
    # of 20 replies — a ranking of noise wearing a hedge, which is worse than
    # saying nothing.
    if top[metric["verdict"]] == "not_enough_data":
        return "unresolved"
    top_low = top[metric["ci"]][0]
    if top_low > rest[metric["ci"]][1]:
        return "clear"
    # "Leaning" means the leader's plausible worst case still beats the rest of
    # the field's actual rate. A bare ratio (1.0% vs 0.8%) does not clear that.
    if top_low > rest[metric["rate"]] and top[metric["rate"]] > rest[metric["rate"]] * 1.2:
        return "leaning"
    return "unresolved"


def _pooled(entries: list[dict], metric: dict) -> dict:
    """Everything except the leader, added up — the field it has to beat."""
    successes = sum(entry[metric["successes"]] for entry in entries)
    trials = sum(entry[metric["trials"]] for entry in entries)
    low, high = wilson_interval(successes, trials)
    return {
        metric["successes"]: successes,
        metric["trials"]: trials,
        metric["rate"]: successes / trials if trials else 0.0,
        metric["ci"]: [round(low, 5), round(high, 5)],
        metric["verdict"]: "not_enough_data" if trials < 1 else "pooled",
        "tokens": [entry["slot"] for entry in entries],
    }


def recommendations(
    conn,
    campaign_id: int,
    outcomes: list[dict] | None = None,
    texts: dict[str, dict] | None = None,
) -> dict:
    """Read the slot tables and say what to do: which component to keep, which is
    still open, and what the next run should hold fixed while it varies one thing.

    Deliberately deterministic. The AI report is asked to explain and phrase
    these, never to derive them — a recommendation that changes wording every
    time it is regenerated is not a recommendation.

    `texts` (from app.campaign_copy.slot_text_map) is optional and only supplies
    the human-readable copy; the logic never depends on it.
    """
    outcomes = lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    slots = slot_metrics(conn, campaign_id, outcomes)
    overall = _lead_metrics(outcomes)
    texts = texts or {}

    def copy_of(token: str) -> str:
        return (texts.get(token) or {}).get("display") or ""

    findings = []
    for role in TESTABLE_ROLES:
        entries = slots.get(role) or []
        if not entries:
            continue
        stage = stage_of(role)
        metric = STAGE_METRIC[stage]
        ranked = sorted(entries, key=lambda e: (-e[metric["rate"]], -e[metric["trials"]]))
        if len(ranked) < 2:
            findings.append(
                {
                    "role": role,
                    "stage": stage,
                    "metric": metric["label"],
                    "status": "untested",
                    "winner": ranked[0]["slot"],
                    "winner_text": copy_of(ranked[0]["slot"]),
                    "winner_rate": ranked[0][metric["rate"]],
                    "runner_up": None,
                    "runner_up_text": "",
                    "runner_up_rate": 0.0,
                    "options": len(ranked),
                    "action": (
                        f"Only one {role} was ever used, so nothing has been compared. "
                        "Write a second one if this component is worth testing."
                    ),
                }
            )
            continue

        top, rest = ranked[0], ranked[1:]
        field = _pooled(rest, metric)
        status = _separation(top, field, metric)
        findings.append(
            {
                "role": role,
                "stage": stage,
                "metric": metric["label"],
                "metric_why": metric["why"],
                "status": status,
                "winner": top["slot"],
                "winner_text": copy_of(top["slot"]),
                "winner_rate": top[metric["rate"]],
                "winner_successes": top[metric["successes"]],
                "winner_trials": top[metric["trials"]],
                "runner_up": ranked[1]["slot"],
                "runner_up_text": copy_of(ranked[1]["slot"]),
                "runner_up_rate": ranked[1][metric["rate"]],
                "field_rate": field[metric["rate"]],
                "options": len(ranked),
                "action": _action_for(role, status, top, ranked[1], metric, overall),
            }
        )

    resolved = [f for f in findings if f["status"] in ("clear", "leaning")]
    open_roles = [f for f in findings if f["status"] == "unresolved"]
    next_role = next(
        (role for role in _TEST_PRIORITY if any(f["role"] == role for f in open_roles)),
        None,
    )
    next_finding = next((f for f in open_roles if f["role"] == next_role), None)

    plan = None
    if next_finding:
        arms = [
            {"token": next_finding["winner"], "text": next_finding["winner_text"]},
            {"token": next_finding["runner_up"], "text": next_finding["runner_up_text"]},
        ]
        stage = next_finding["stage"]
        baseline = (
            overall["reply_rate"] if stage == "attention" else overall["positive_per_reply"]
        )
        plan = {
            "vary": next_finding["role"],
            "vary_stage": stage,
            "arms": arms,
            "hold_fixed": [
                {
                    "role": f["role"],
                    "token": f["winner"],
                    "text": f["winner_text"],
                    "status": f["status"],
                }
                for f in resolved
            ],
            "per_arm_sends": required_per_arm(baseline),
            "baseline": baseline,
            "why": (
                f"Everything else stays on its current best so the only thing that differs "
                f"between the two arms is the {next_finding['role']}. With {len(findings)} "
                f"components varying at once, no single one can be attributed."
            ),
        }
    elif findings:
        plan = {
            "vary": None,
            "arms": [],
            "hold_fixed": [
                {
                    "role": f["role"],
                    "token": f["winner"],
                    "text": f["winner_text"],
                    "status": f["status"],
                }
                for f in findings
            ],
            "per_arm_sends": 0,
            "baseline": overall["reply_rate"],
            "why": (
                "Every component has a leader. Run the winning combination as a single "
                "control and test a genuinely new angle against it rather than re-splitting "
                "the same copy."
            ),
        }

    return {
        "findings": findings,
        "next_test": plan,
        "sends_needed_per_arm_reply": required_per_arm(overall["reply_rate"]),
        "sends_needed_per_arm_positive": required_per_arm(overall["positive_rate"]),
    }


def _action_for(role: str, status: str, top: dict, second: dict, metric: dict, overall: dict) -> str:
    rate = f"{top[metric['rate']]:.1%}"
    other = f"{second[metric['rate']]:.1%}"
    counts = f"{top[metric['successes']]}/{top[metric['trials']]}"
    if status == "clear":
        return (
            f"Keep {top['slot']} and retire the rest. {rate} vs {other} on {metric['label']} "
            f"({counts}), and the gap clears the confidence interval."
        )
    if status == "leaning":
        return (
            f"Run {top['slot']} as the control — it leads on {metric['label']} "
            f"({rate} vs {other}, {counts}) but the gap is not yet proven. Keep only it and "
            f"{second['slot']} in the next run so the comparison gets the whole sample."
        )
    baseline = overall["reply_rate"] if metric["rate"] == "reply_rate" else overall["positive_per_reply"]
    need = required_per_arm(baseline)
    return (
        f"Unresolved — {top['slot']} and {second['slot']} are indistinguishable "
        f"({rate} vs {other} on {metric['label']}). Either drop this from the test and "
        f"pick one arbitrarily, or give it ~{need:,} sends per arm."
    )


def subject_metrics(
    conn, campaign_id: int, limit: int = 25, outcomes: list[dict] | None = None
) -> list[dict]:
    """Outcomes per *rendered* subject line. The templates only say
    `{{subjectLine1}}`; this is the actual text that landed in the inbox, which
    is what a subject-line critique has to reason about."""
    outcomes = lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    overall = _lead_metrics(outcomes)
    reply_base, positive_base, conv_base = _baselines_of(overall)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        subject = (outcome["email_subject"] or "").strip()
        if subject:
            grouped[subject].append(outcome)
    entries = []
    for subject, bucket in grouped.items():
        entry = _with_verdicts(_lead_metrics(bucket), reply_base, positive_base, conv_base)
        entry["subject"] = subject
        entries.append(entry)
    entries.sort(key=lambda entry: (-entry["replies"], -entry["sent"]))
    return entries[:limit]


def step_metrics(conn, campaign_id: int) -> list[dict]:
    """Outcomes per sequence step — is the campaign carried by the first email or
    by the follow-ups?"""
    rows = _load(conn, campaign_id, step=None)
    reply_base, positive_base, conv_base = baselines(rows)
    grouped: dict[int | None, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["sequence_number"]].append(row)
    entries = []
    for step, bucket in sorted(grouped.items(), key=lambda item: (item[0] is None, item[0])):
        entry = _with_verdicts(_metrics(bucket), reply_base, positive_base, conv_base)
        entry["step"] = step
        entries.append(entry)
    return entries


def slot_examples(conn, campaign_id: int, token: str, limit: int = 6) -> list[str]:
    """What a slot actually *says*. The templates hold `{{CTA1}}`; the text lives
    per-lead in the export's custom_fields, and the report is useless without
    it — you cannot critique a CTA you have not read."""
    rows = conn.execute(
        """SELECT custom_fields_json FROM campaign_lead_vars
           WHERE campaign_id = ? AND custom_fields_json IS NOT NULL LIMIT 400""",
        (campaign_id,),
    ).fetchall()
    seen: list[str] = []
    for row in rows:
        try:
            fields = json.loads(row["custom_fields_json"] or "{}")
        except (ValueError, TypeError):
            continue
        value = (fields.get(token) or "").strip()
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= limit:
            break
    return seen


def reply_step_metrics(conn, campaign_id: int, outcomes: list[dict] | None = None) -> list[dict]:
    """Which step earned each reply — how far into the sequence follow-ups keep
    paying. Denominator is leads who actually *reached* that step, so step 4's
    rate isn't flattered by the leads who never got that far."""
    outcomes = lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    reached: dict[int, int] = defaultdict(int)
    for outcome in outcomes:
        if outcome["bounced"]:
            continue
        for step in range(1, outcome["steps_sent"] + 1):
            reached[step] += 1
    replies: dict[int, int] = defaultdict(int)
    positives: dict[int, int] = defaultdict(int)
    for outcome in outcomes:
        if outcome["reply_step"]:
            replies[outcome["reply_step"]] += 1
            if outcome["positive"]:
                positives[outcome["reply_step"]] += 1
    return [
        {
            "step": step,
            "reached": reached[step],
            "replies": replies.get(step, 0),
            "positives": positives.get(step, 0),
            "reply_rate": replies.get(step, 0) / reached[step] if reached[step] else 0.0,
        }
        for step in sorted(reached)
    ]


def campaign_summary(conn, campaign_id: int, outcomes: list[dict] | None = None) -> dict:
    """Everything the Overview tab and the Layer-1 report brief need."""
    outcomes = lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    return {
        "campaign_id": campaign_id,
        "overall": _lead_metrics(outcomes),
        "leads": len(outcomes),
        "sends": sum(o["steps_sent"] for o in outcomes),
        "by_category": dict(
            sorted(
                Counter(o["category"] for o in outcomes if o["category"]).items(),
                key=lambda item: -item[1],
            )
        ),
    }
