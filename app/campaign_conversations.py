"""Qualitative layer — read what leads actually wrote back.

The variant maths (app/campaign_analytics.py) can say *that* a message earns
fewer replies. It cannot say why someone was annoyed, which lead magnet they
asked for, or what they misunderstood about the offer. That only comes from
reading the conversations.

The population here is deliberately narrow: leads who answered like *people*.
Auto-Reply and Out Of Office are excluded — on campaign 3640877 they are twice
as numerous as real replies, and feeding them to the model would drown the
signal in "I am currently on holiday". Not Interested and Do Not Contact are
kept: a rejection is one of the most informative things a lead can send.

Threads come from Smartlead's bulk message-history endpoint, which returns full
bodies plus `email_seq_number` on our sends — that last field is what makes
"which follow-up earned this reply" answerable.
"""

import hashlib
import json
import logging
from collections import Counter, defaultdict

from app import db, smartlead
from app.campaign_analytics import is_positive, normalize_category
from app.email_clean import to_plain_text

log = logging.getLogger("campaign_conversations")

# Not a person writing to us. Everything else — including Not Interested, Do Not
# Contact and Wrong Person — is a real human response worth learning from.
# "Wrong Person" and "Redirect" stay in on purpose: someone telling us we
# targeted the wrong contact is a targeting lesson, not noise.
NON_HUMAN_CATEGORIES = {
    "auto-reply",
    "auto reply",
    "out of office",
    "sender originated bounce",
    "",
}

# Smartlead categories that name the specific asset the lead asked for. Andrew
# offers several lead magnets, and Smartlead is already tagging which one landed
# — so "which magnet works" is a count, not an inference.
MAGNET_CATEGORIES = {
    "interested for video": "video",
    "interested in installer video": "video",
    "interested for toolkit": "toolkit",
    "interested for calculator": "calculator",
}

_BULK_CHUNK = 25


def is_human_response(category: str | None) -> bool:
    return normalize_category(category) not in NON_HUMAN_CATEGORIES


def magnet_for(category: str | None) -> str | None:
    return MAGNET_CATEGORIES.get(normalize_category(category))


def real_responders(conn, campaign_id: int) -> list[dict]:
    """Leads who genuinely replied, with the step-1 variant they were sent and
    the lead_id needed to fetch their thread.

    lead_id comes from campaign_lead_vars (the leads-export CSV) because the
    statistics rows carry only the email address."""
    rows = conn.execute(
        """SELECT s.lead_email,
                  MAX(s.lead_category)  AS category,
                  MIN(s.reply_time)     AS first_reply_at,
                  v.lead_id             AS lead_id,
                  v.company_name        AS company
             FROM campaign_sends s
             LEFT JOIN campaign_lead_vars v
                    ON v.campaign_id = s.campaign_id AND v.lead_email = s.lead_email
            WHERE s.campaign_id = ? AND s.reply_time IS NOT NULL
            GROUP BY s.lead_email""",
        (campaign_id,),
    ).fetchall()

    # The variant a lead was assigned lives on their step-1 row.
    variant_by_email = {
        row["lead_email"]: (row["seq_variant_id"], row["variant_label"])
        for row in conn.execute(
            """SELECT s.lead_email, s.seq_variant_id, v.variant_label
                 FROM campaign_sends s
                 LEFT JOIN campaign_variants v
                        ON v.campaign_id = s.campaign_id
                       AND v.seq_variant_id = s.seq_variant_id
                WHERE s.campaign_id = ? AND s.sequence_number = 1""",
            (campaign_id,),
        ).fetchall()
    }

    out = []
    for row in rows:
        if not is_human_response(row["category"]) or not row["lead_id"]:
            continue
        variant_id, variant_label = variant_by_email.get(row["lead_email"], (None, None))
        out.append(
            {
                "lead_id": str(row["lead_id"]),
                "lead_email": row["lead_email"],
                "company": row["company"],
                "category": row["category"],
                "first_reply_at": row["first_reply_at"],
                "seq_variant_id": variant_id,
                "variant_label": variant_label,
            }
        )
    return out


def _build_thread(history: list[dict]) -> dict:
    """Normalize one lead's raw history into ordered, plain-text turns.

    Bodies are cleaned with the app's existing email_clean helpers, which already
    strip HTML and quoted reply history — without that, every reply would arrive
    at the model with our own previous email quoted underneath it, tripling the
    token cost and inviting the model to analyze our own copy as if the lead had
    written it."""
    turns = []
    for message in sorted(history, key=lambda m: m.get("time") or ""):
        text = to_plain_text(message.get("email_body"))
        if not text:
            continue
        is_ours = (message.get("type") or "").upper() == "SENT"
        turns.append(
            {
                "who": "us" if is_ours else "them",
                "at": message.get("time"),
                "subject": message.get("subject"),
                "step": _int(message.get("email_seq_number")) if is_ours else None,
                "text": text,
            }
        )

    ours = [turn for turn in turns if turn["who"] == "us"]
    theirs = [turn for turn in turns if turn["who"] == "them"]

    first_reply = theirs[0] if theirs else None
    reply_step = None
    hours = None
    if first_reply:
        # The step that earned the reply is the last thing we sent before it.
        preceding = [t for t in ours if (t["at"] or "") <= (first_reply["at"] or "")]
        if preceding:
            reply_step = preceding[-1]["step"]
            hours = _hours_between(preceding[-1]["at"], first_reply["at"])

    return {
        "turns": turns,
        "our_msg_count": len(ours),
        "their_msg_count": len(theirs),
        "first_reply_at": first_reply["at"] if first_reply else None,
        "first_reply_after_step": reply_step,
        "hours_to_reply": hours,
    }


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hours_between(earlier: str | None, later: str | None) -> float | None:
    from datetime import datetime

    if not earlier or not later:
        return None
    try:
        start = datetime.fromisoformat(earlier.replace("Z", "+00:00"))
        end = datetime.fromisoformat(later.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((end - start).total_seconds() / 3600, 2)


def sync_conversations(campaign_id: int, progress=None) -> int:
    """Fetch and store every real responder's thread.

    A thread whose content hash is unchanged keeps its cached AI extraction, so
    re-analyzing a campaign only pays for conversations that are actually new."""
    with db.db_session() as conn:
        responders = real_responders(conn, campaign_id)
        existing = {
            row["lead_id"]: row["thread_hash"]
            for row in db.list_campaign_conversations(conn, campaign_id)
        }
    if not responders:
        return 0

    by_id = {person["lead_id"]: person for person in responders}
    lead_ids = list(by_id)
    stored = 0
    for start in range(0, len(lead_ids), _BULK_CHUNK):
        chunk = lead_ids[start : start + _BULK_CHUNK]
        if progress:
            progress(f"Reading conversations {start + 1}–{start + len(chunk)} of {len(lead_ids)}…")
        payload = smartlead.get_message_history_bulk(campaign_id, chunk)
        for lead_id, blob in payload.items():
            person = by_id.get(str(lead_id))
            if not person:
                continue
            thread = _build_thread((blob or {}).get("history") or [])
            if not thread["turns"]:
                continue
            thread_hash = hashlib.sha256(
                json.dumps(thread["turns"], sort_keys=True).encode("utf-8")
            ).hexdigest()
            fields = {
                "lead_email": person["lead_email"],
                "company": person["company"],
                "category": person["category"],
                "variant_label": person["variant_label"],
                "seq_variant_id": person["seq_variant_id"],
                "thread_json": json.dumps(thread["turns"], ensure_ascii=False),
                "our_msg_count": thread["our_msg_count"],
                "their_msg_count": thread["their_msg_count"],
                "first_reply_after_step": thread["first_reply_after_step"],
                "first_reply_at": thread["first_reply_at"] or person["first_reply_at"],
                "hours_to_reply": thread["hours_to_reply"],
                "thread_hash": thread_hash,
            }
            if existing.get(str(lead_id)) != thread_hash:
                # Content changed (or is new): drop the stale extraction so the
                # next analysis re-reads it.
                fields["extract_json"] = None
                fields["extracted_at"] = None
            with db.db_session() as conn:
                db.upsert_campaign_conversation(conn, campaign_id, str(lead_id), **fields)
            stored += 1

    with db.db_session() as conn:
        db.update_campaign_sync(conn, campaign_id, convos_synced_at=db.now_iso())
    log.info("campaign %s: stored %d conversations", campaign_id, stored)
    return stored


def conversation_stats(conn, campaign_id: int) -> dict:
    """Pure counting over the stored threads — no AI. These are the numbers the
    synthesis prompt is given so it never has to estimate a frequency."""
    rows = db.list_campaign_conversations(conn, campaign_id)
    if not rows:
        return {"total": 0}

    by_category = Counter()
    by_step = defaultdict(lambda: {"replies": 0, "positives": 0})
    by_variant = defaultdict(Counter)
    magnets = Counter()
    multi_turn = 0
    reply_hours = []

    for row in rows:
        category = row["category"] or "Uncategorized"
        by_category[category] += 1
        step = row["first_reply_after_step"]
        if step:
            by_step[step]["replies"] += 1
            if is_positive(row["category"]):
                by_step[step]["positives"] += 1
        if row["variant_label"]:
            by_variant[row["variant_label"]][category] += 1
        magnet = magnet_for(row["category"])
        if magnet:
            magnets[magnet] += 1
        if (row["their_msg_count"] or 0) > 1:
            multi_turn += 1
        if row["hours_to_reply"] is not None:
            reply_hours.append(row["hours_to_reply"])

    reply_hours.sort()
    return {
        "total": len(rows),
        "by_category": dict(by_category.most_common()),
        "positives": sum(1 for row in rows if is_positive(row["category"])),
        "by_reply_step": {
            step: dict(counts) for step, counts in sorted(by_step.items())
        },
        "by_variant": {label: dict(counts) for label, counts in sorted(by_variant.items())},
        "magnets_requested": dict(magnets.most_common()),
        "multi_turn_conversations": multi_turn,
        "one_and_done": len(rows) - multi_turn,
        "median_hours_to_reply": (
            reply_hours[len(reply_hours) // 2] if reply_hours else None
        ),
    }


def thread_for_prompt(row, max_chars: int = 1800) -> dict:
    """One conversation, trimmed for the extraction prompt. Our own outreach is
    truncated harder than their reply — we already know what we sent, and what
    they wrote is the part being analyzed."""
    turns = json.loads(row["thread_json"] or "[]")
    compact = []
    for turn in turns:
        limit = max_chars if turn["who"] == "them" else 700
        text = turn["text"]
        if len(text) > limit:
            text = text[:limit] + " […]"
        compact.append(
            {
                "who": turn["who"],
                "step": turn.get("step"),
                "subject": turn.get("subject"),
                "text": text,
            }
        )
    return {
        "lead_id": row["lead_id"],
        "company": row["company"],
        "category": row["category"],
        "variant": row["variant_label"],
        "replied_after_step": row["first_reply_after_step"],
        "turns": compact,
    }
