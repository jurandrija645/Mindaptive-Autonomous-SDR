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

# What counts as a win. Confirmed with Andrew: Interested and a booked meeting.
# "Information Request" and the magnet-specific categories are tracked
# separately as engagement rather than folded in here, so the headline number
# stays the one he actually cares about.
POSITIVE_CATEGORIES = {
    "interested",
    "meeting-booked",
    "meeting booked",
    "meeting request",
}

# Rates below these are reported but never ranked — see verdict().
MIN_DELIVERED = 300
MIN_REPLIES = 10

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
    return normalize_category(category) in POSITIVE_CATEGORIES


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


def verdict(successes: int, trials: int, baseline: float) -> str:
    """How much to trust this row against the campaign's own baseline rate.

    `not_enough_data` is deliberately returned before any comparison: with a
    handful of replies per variant, a "winner" is usually noise, and the report
    is instructed never to call one on this label."""
    if trials < MIN_DELIVERED or successes < MIN_REPLIES:
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
        "bounce_rate": bounced / sent if sent else 0.0,
        "reply_rate": replies / delivered if delivered else 0.0,
        "positive_rate": positives / delivered if delivered else 0.0,
    }


def _with_verdicts(bucket: dict, reply_baseline: float, positive_baseline: float) -> dict:
    delivered = bucket["delivered"]
    reply_low, reply_high = wilson_interval(bucket["replies"], delivered)
    pos_low, pos_high = wilson_interval(bucket["positives"], delivered)
    bucket["reply_ci"] = [round(reply_low, 5), round(reply_high, 5)]
    bucket["positive_ci"] = [round(pos_low, 5), round(pos_high, 5)]
    bucket["reply_verdict"] = verdict(bucket["replies"], delivered, reply_baseline)
    bucket["positive_verdict"] = verdict(bucket["positives"], delivered, positive_baseline)
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
    return {"variants": variants, "sends": sends, "lead_vars": lead_vars}


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


def baselines(rows: list[dict]) -> tuple[float, float]:
    overall = _metrics(rows)
    return overall["reply_rate"], overall["positive_rate"]


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
        "bounce_rate": bounced / sent if sent else 0.0,
        "reply_rate": replies / delivered if delivered else 0.0,
        "positive_rate": positives / delivered if delivered else 0.0,
    }


def variant_metrics(conn, campaign_id: int, outcomes: list[dict] | None = None) -> list[dict]:
    """Per-variant outcomes, attributed across the whole sequence (see
    lead_outcomes).

    Reported for completeness, but six variants splitting ~40 human replies
    means most rows land on `not_enough_data`; slot_metrics is where the usable
    signal is."""
    outcomes = lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    overall = _lead_metrics(outcomes)
    reply_base, positive_base = overall["reply_rate"], overall["positive_rate"]
    variants = {v["seq_variant_id"]: dict(v) for v in db.list_campaign_variants(conn, campaign_id)}

    grouped: dict[int | None, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome["seq_variant_id"]].append(outcome)

    out = []
    for variant_id, bucket in grouped.items():
        meta = variants.get(variant_id, {})
        slots = json.loads(meta.get("slots_json") or "[]")
        entry = _with_verdicts(_lead_metrics(bucket), reply_base, positive_base)
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
    reply_base, positive_base = overall["reply_rate"], overall["positive_rate"]
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
            entry = _with_verdicts(_lead_metrics(bucket), reply_base, positive_base)
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


def subject_metrics(
    conn, campaign_id: int, limit: int = 25, outcomes: list[dict] | None = None
) -> list[dict]:
    """Outcomes per *rendered* subject line. The templates only say
    `{{subjectLine1}}`; this is the actual text that landed in the inbox, which
    is what a subject-line critique has to reason about."""
    outcomes = lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    overall = _lead_metrics(outcomes)
    reply_base, positive_base = overall["reply_rate"], overall["positive_rate"]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        subject = (outcome["email_subject"] or "").strip()
        if subject:
            grouped[subject].append(outcome)
    entries = []
    for subject, bucket in grouped.items():
        entry = _with_verdicts(_lead_metrics(bucket), reply_base, positive_base)
        entry["subject"] = subject
        entries.append(entry)
    entries.sort(key=lambda entry: (-entry["replies"], -entry["sent"]))
    return entries[:limit]


def step_metrics(conn, campaign_id: int) -> list[dict]:
    """Outcomes per sequence step — is the campaign carried by the first email or
    by the follow-ups?"""
    rows = _load(conn, campaign_id, step=None)
    reply_base, positive_base = baselines(rows)
    grouped: dict[int | None, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["sequence_number"]].append(row)
    entries = []
    for step, bucket in sorted(grouped.items(), key=lambda item: (item[0] is None, item[0])):
        entry = _with_verdicts(_metrics(bucket), reply_base, positive_base)
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
