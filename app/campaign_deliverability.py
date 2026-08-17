"""Did this campaign fail on the copy, or on where the mail was going?

Every other layer of the campaign analysis compares things Andrew wrote — this
one compares things he didn't. A lead's mailbox provider is fixed before the
first word is drafted, and it decides which filter the email has to clear.

Three questions, in the order they should be trusted:

1. **What is the mix?** How much of this campaign's audience sits on Microsoft,
   on Google, or on the long tail. Descriptive; always available.
2. **Inside this campaign, did the mix matter?** Reply rate per provider, with
   the same Wilson intervals and `not_enough_data` thresholds the variant
   analysis uses. This is the strong comparison: every slice got the same copy,
   the same sender, the same sequence, on the same days, so the copy cannot
   explain a gap between them.
3. **Across campaigns, does it keep mattering?** Pooled per-provider rates from
   every campaign ever analyzed, plus a split of Microsoft-heavy campaigns
   against the rest. This is the accumulated knowledge that lets a *future*
   analysis say "this one didn't bomb on copy" — and it is the reason
   `campaign_esp_stats` is written on every run and never cleaned up.

**The confound is stated, not hidden.** Provider correlates with company type:
Microsoft 365 skews enterprise, Google skews startups and younger SMBs, and the
German dental campaigns land almost entirely on small local hosters. So a gap
between providers is not proof of a spam filter — it can be the ICP underneath
it. Question 2 controls for the copy but not for who those people are, and every
verdict this module emits carries that caveat so the AI brief cannot quietly
upgrade it into a causal claim. What it does establish is the thing Andrew
actually wants: that the copy is not the only suspect.
"""

import logging
from collections import defaultdict

from app import campaign_analytics, db, mailbox_provider

log = logging.getLogger("campaign_deliverability")

# The campaign's own totals, stored beside its slices under a provider key that
# cannot collide with a real one.
TOTALS_KEY = "_all"

# A slice smaller than this is shown in the table but never becomes a finding —
# a 40-recipient provider says nothing either way.
#
# Note there is deliberately no matching floor on the number of *replies*. The
# test in `diagnose` is whether two Wilson intervals overlap, and a slice with a
# large denominator and almost no replies is exactly the case that test handles
# well: 1 reply from 730 delivered puts the true rate under 0.8% with 95%
# confidence, which separates cleanly from a field replying at 1.1%. A
# successes floor guards against overclaiming a HIGH rate from few trials; it
# would here suppress the strongest evidence of a low one, which is the whole
# thing this module exists to find.
MIN_SLICE_DELIVERED = 150

# A campaign counts as "heavy" on a provider at this share of its audience. Set
# where it is because the interesting case is a campaign that is mostly one
# provider, not one that merely leans.
HEAVY_SHARE = 0.6

# How many campaigns must sit on each side before the cross-campaign split is
# allowed to say anything at all.
MIN_CAMPAIGNS_PER_SIDE = 3


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def sync_domains(campaign_id: int, progress=None) -> int:
    """Make sure every domain this campaign mailed has a provider on file.

    Reads the recipients out of `campaign_sends` rather than the leads export,
    so the mix describes who was actually *mailed* — a lead sitting in the
    campaign who never received anything has no bearing on deliverability."""
    with db.db_session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT lead_email FROM campaign_sends WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
    domains = {
        domain
        for row in rows
        if (domain := mailbox_provider.domain_of(row["lead_email"]))
    }
    if not domains:
        return 0
    resolved = mailbox_provider.resolve(domains, progress=progress)
    log.info("campaign %s: %d recipient domains resolved", campaign_id, len(resolved))
    return len(resolved)


def _provider_map(conn, outcomes: list[dict]) -> dict[str, str]:
    """lead_email -> provider, from the cache only. Never resolves: this runs on
    the Overview tab's read path, which must not make network calls."""
    domains = {
        domain
        for outcome in outcomes
        if (domain := mailbox_provider.domain_of(outcome["lead_email"]))
    }
    cached = {
        row["domain"]: row["provider"]
        for row in db.get_mailbox_domains(conn, sorted(domains))
    }
    mapping = {}
    for outcome in outcomes:
        domain = mailbox_provider.domain_of(outcome["lead_email"])
        mapping[outcome["lead_email"]] = cached.get(domain, "unresolved") if domain else "unresolved"
    return mapping


# ---------------------------------------------------------------------------
# This campaign
# ---------------------------------------------------------------------------

def _slice(bucket: list[dict], baselines: tuple[float, float, float]) -> dict:
    return campaign_analytics.with_verdicts(
        campaign_analytics.lead_metrics(bucket), *baselines
    )


def breakdown(conn, campaign_id: int, outcomes: list[dict] | None = None) -> dict:
    """The provider mix and how each slice performed. Cache-only, so it is safe
    on the Overview read path; `sync_domains` is what fills the cache."""
    outcomes = (
        campaign_analytics.lead_outcomes(conn, campaign_id) if outcomes is None else outcomes
    )
    if not outcomes:
        return {"resolved": False, "reason": "This campaign has no sends recorded yet."}

    providers = _provider_map(conn, outcomes)
    overall = campaign_analytics.lead_metrics(outcomes)
    baselines = (
        overall["reply_rate"], overall["positive_rate"], overall["positive_per_reply"]
    )

    by_provider: dict[str, list[dict]] = defaultdict(list)
    by_group: dict[str, list[dict]] = defaultdict(list)
    for outcome in outcomes:
        provider = providers.get(outcome["lead_email"], "unresolved")
        by_provider[provider].append(outcome)
        by_group[mailbox_provider.group_of(provider)].append(outcome)

    known = sum(len(b) for group, b in by_group.items() if group != "unknown")
    if not known:
        return {
            "resolved": False,
            "reason": "No recipient domain has been checked yet — run Analyze to look them up.",
        }

    provider_rows = []
    for provider, bucket in by_provider.items():
        entry = _slice(bucket, baselines)
        entry.update(
            {
                "provider": provider,
                "label": mailbox_provider.label_for(provider),
                "group": mailbox_provider.group_of(provider),
                "share": len(bucket) / len(outcomes),
            }
        )
        provider_rows.append(entry)
    provider_rows.sort(key=lambda row: -row["sent"])

    group_rows = []
    for group, bucket in by_group.items():
        entry = _slice(bucket, baselines)
        entry.update(
            {
                "group": group,
                "label": mailbox_provider.GROUP_LABELS.get(group, group),
                # Share is of the *classified* audience: quoting "92% Microsoft"
                # is only honest if the domains we couldn't check are out of the
                # denominator rather than silently diluting it.
                "share": len(bucket) / known if group != "unknown" else len(bucket) / len(outcomes),
            }
        )
        group_rows.append(entry)
    group_rows.sort(key=lambda row: -row["share"])

    return {
        "resolved": True,
        "leads": len(outcomes),
        "classified": known,
        "unknown": len(outcomes) - known,
        "overall": overall,
        "groups": group_rows,
        "providers": provider_rows,
    }


def store(conn, campaign_id: int, data: dict) -> int:
    """Persist the breakdown so it can be compared against future campaigns.

    This is the "save this for each campaign" half of the feature: the per-lead
    data behind it is re-synced and overwritten constantly, but these ~10 rows
    per campaign are small enough to keep forever, which is what makes the
    cross-campaign pattern possible at all."""
    if not data.get("resolved"):
        return 0
    rows = [
        {
            "provider": row["provider"],
            "provider_group": row["group"],
            "leads": row["sent"],
            "delivered": row["delivered"],
            "bounced": row["bounced"],
            "replies": row["replies"],
            "positives": row["positives"],
            "booked": row["booked"],
            "unsubscribed": row["unsubscribed"],
        }
        for row in data["providers"]
    ]
    overall = data["overall"]
    rows.append(
        {
            "provider": TOTALS_KEY,
            "provider_group": TOTALS_KEY,
            "leads": overall["sent"],
            "delivered": overall["delivered"],
            "bounced": overall["bounced"],
            "replies": overall["replies"],
            "positives": overall["positives"],
            "booked": overall["booked"],
            "unsubscribed": overall["unsubscribed"],
        }
    )
    return db.replace_campaign_esp_stats(conn, campaign_id, rows)


# ---------------------------------------------------------------------------
# Across campaigns — the part that accumulates
# ---------------------------------------------------------------------------

def _rate(successes: int, trials: int) -> dict:
    low, high = campaign_analytics.wilson_interval(successes, trials)
    return {
        "successes": successes,
        "trials": trials,
        "rate": successes / trials if trials else 0.0,
        "ci": [round(low, 5), round(high, 5)],
    }


def history(conn, exclude_campaign_id: int | None = None) -> dict:
    """What every analyzed campaign together says about mailbox providers.

    `exclude_campaign_id` leaves the campaign being diagnosed out of its own
    evidence. Without it, a campaign that is 92% Microsoft would dominate the
    Microsoft pool it is then compared against, and the comparison would be
    partly against itself."""
    rows = db.list_campaign_esp_stats(conn)
    if not rows:
        return {"campaigns": 0, "groups": [], "split": None}

    pooled: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_campaign: dict[int, dict] = {}
    for row in rows:
        campaign_id = row["campaign_id"]
        entry = per_campaign.setdefault(
            campaign_id,
            {
                "campaign_id": campaign_id,
                "name": row["campaign_name"] or f"Campaign {campaign_id}",
                "groups": defaultdict(int),
                "delivered": 0,
                "replies": 0,
                "positives": 0,
                "bounced": 0,
            },
        )
        if row["provider"] == TOTALS_KEY:
            entry["delivered"] = row["delivered"]
            entry["replies"] = row["replies"]
            entry["positives"] = row["positives"]
            entry["bounced"] = row["bounced"]
            continue
        group = row["provider_group"] or mailbox_provider.group_of(row["provider"])
        entry["groups"][group] += row["leads"]
        if campaign_id == exclude_campaign_id:
            continue
        bucket = pooled[group]
        for field in ("leads", "delivered", "bounced", "replies", "positives", "booked"):
            bucket[field] += row[field]

    groups = []
    for group, bucket in pooled.items():
        if group == "unknown":
            continue
        groups.append(
            {
                "group": group,
                "label": mailbox_provider.GROUP_LABELS.get(group, group),
                "delivered": bucket["delivered"],
                "replies": bucket["replies"],
                "positives": bucket["positives"],
                "bounced": bucket["bounced"],
                "leads": bucket["leads"],
                "reply": _rate(bucket["replies"], bucket["delivered"]),
                "positive": _rate(bucket["positives"], bucket["delivered"]),
                "bounce": _rate(bucket["bounced"], bucket["leads"]),
            }
        )
    groups.sort(key=lambda row: -row["delivered"])

    campaigns = []
    for entry in per_campaign.values():
        classified = sum(count for name, count in entry["groups"].items() if name != "unknown")
        if not classified or not entry["delivered"]:
            continue
        campaigns.append(
            {
                "campaign_id": entry["campaign_id"],
                "name": entry["name"],
                "delivered": entry["delivered"],
                "replies": entry["replies"],
                "positives": entry["positives"],
                "reply_rate": entry["replies"] / entry["delivered"],
                "microsoft_share": entry["groups"].get("microsoft", 0) / classified,
                "google_share": entry["groups"].get("google", 0) / classified,
                "other_share": entry["groups"].get("other", 0) / classified,
            }
        )
    campaigns.sort(key=lambda row: -row["microsoft_share"])

    others = [c for c in campaigns if c["campaign_id"] != exclude_campaign_id]
    return {
        # The campaigns actually contributing evidence, not the total on file —
        # the panel says "what N campaigns say", and the current one isn't one of
        # them. On the very first campaign ever analyzed this is 0, which is what
        # makes the whole history block correctly disappear.
        "campaigns": len(others),
        "groups": groups,
        # Excluded from the comparison for the same reason it is excluded from
        # the pooled table — a campaign must not be part of the record it is
        # being judged against. It stays in `by_campaign`, which is the listing
        # rather than the evidence.
        "split": _heavy_split(others),
        "by_campaign": campaigns,
    }


def _heavy_split(campaigns: list[dict]) -> dict | None:
    """Microsoft-heavy campaigns against the rest — the claim Andrew wants to be
    able to make, stated only when there is enough of a record to make it.

    Campaign-level rather than lead-level on purpose: this is the question "do
    campaigns aimed at Microsoft audiences do worse", and the unit of that
    question is a campaign."""
    heavy = [c for c in campaigns if c["microsoft_share"] >= HEAVY_SHARE]
    rest = [c for c in campaigns if c["microsoft_share"] < HEAVY_SHARE]
    if len(heavy) < MIN_CAMPAIGNS_PER_SIDE or len(rest) < MIN_CAMPAIGNS_PER_SIDE:
        return {
            "status": "not_enough_data",
            "heavy_campaigns": len(heavy),
            "other_campaigns": len(rest),
            "note": (
                f"Needs at least {MIN_CAMPAIGNS_PER_SIDE} analyzed campaigns on each side "
                f"before Microsoft-heavy campaigns can be compared against the rest "
                f"({len(heavy)} vs {len(rest)} so far)."
            ),
        }

    heavy_rate = _rate(
        sum(c["replies"] for c in heavy), sum(c["delivered"] for c in heavy)
    )
    rest_rate = _rate(
        sum(c["replies"] for c in rest), sum(c["delivered"] for c in rest)
    )
    if heavy_rate["ci"][1] < rest_rate["ci"][0]:
        status = "heavy_worse"
    elif heavy_rate["ci"][0] > rest_rate["ci"][1]:
        status = "heavy_better"
    else:
        status = "no_difference"
    return {
        "status": status,
        "threshold": HEAVY_SHARE,
        "heavy_campaigns": len(heavy),
        "other_campaigns": len(rest),
        "heavy": heavy_rate,
        "rest": rest_rate,
        "note": _split_note(status, heavy_rate, rest_rate, len(heavy), len(rest)),
    }


def _split_note(status: str, heavy: dict, rest: dict, n_heavy: int, n_rest: int) -> str:
    heavy_pct = f"{heavy['rate']:.2%}"
    rest_pct = f"{rest['rate']:.2%}"
    if status == "heavy_worse":
        return (
            f"Across {n_heavy + n_rest} analyzed campaigns, the {n_heavy} that were mostly "
            f"Microsoft mailboxes replied at {heavy_pct} against {rest_pct} for the other "
            f"{n_rest}, and the two confidence intervals don't overlap."
        )
    if status == "heavy_better":
        return (
            f"Microsoft-heavy campaigns actually did better here — {heavy_pct} against "
            f"{rest_pct} across {n_heavy + n_rest} campaigns."
        )
    return (
        f"No difference yet between Microsoft-heavy campaigns and the rest "
        f"({heavy_pct} vs {rest_pct} over {n_heavy + n_rest} campaigns) — the intervals overlap."
    )


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------

CAVEAT = (
    "Mailbox provider travels with company type — Microsoft skews enterprise, "
    "Google skews younger SMBs, and small local businesses sit on regional "
    "hosters. A gap between providers inside one campaign rules out the copy, "
    "since every slice got the same email, but it cannot separate a spam filter "
    "from a different kind of company. Read it as a suspect, not a cause."
)


def _find(rows: list[dict], key: str, value: str) -> dict | None:
    return next((row for row in rows if row.get(key) == value), None)


def diagnose(data: dict, past: dict) -> dict:
    """The deterministic answer, decided here and merely explained by the AI —
    the same division of labour as campaign_analytics.recommendations, and for
    the same reason: a diagnosis that rewords itself on every regeneration is
    not a diagnosis."""
    if not data.get("resolved"):
        return {"status": "unknown", "headline": "", "detail": "", "caveat": ""}

    groups = data["groups"]
    findings = []
    for group in ("microsoft", "google", "other"):
        mine = _find(groups, "group", group)
        if not mine or mine["delivered"] < MIN_SLICE_DELIVERED:
            continue
        # The field this slice has to beat: every other classified slice pooled,
        # which is the whole rest of the campaign under identical copy.
        rest = [
            row for row in groups
            if row["group"] not in (group, "unknown")
        ]
        rest_replies = sum(row["replies"] for row in rest)
        rest_delivered = sum(row["delivered"] for row in rest)
        if rest_delivered < MIN_SLICE_DELIVERED:
            continue
        rest_rate = _rate(rest_replies, rest_delivered)
        mine_rate = _rate(mine["replies"], mine["delivered"])
        if mine_rate["ci"][1] < rest_rate["ci"][0]:
            direction = "below"
        elif mine_rate["ci"][0] > rest_rate["ci"][1]:
            direction = "above"
        else:
            continue
        findings.append(
            {
                "group": group,
                "label": mine["label"],
                "share": mine["share"],
                "direction": direction,
                "rate": mine_rate,
                "rest": rest_rate,
            }
        )

    split = (past or {}).get("split") or {}
    history_note = split.get("note") or ""
    # Carried separately so the dashboard can show "not enough campaigns yet" as
    # the quiet note it is, rather than dressing it up as a finding.
    history_status = split.get("status") or "not_enough_data"

    # Biggest slice first, not whichever group happened to be checked first: if
    # both Microsoft and Google underperform, the one that explains more of the
    # campaign is the one worth leading with.
    below = sorted((f for f in findings if f["direction"] == "below"), key=lambda f: -f["share"])
    worst = below[0] if below else None
    if worst:
        share = f"{worst['share']:.0%}"
        detail = (
            f"Inside this campaign, {worst['label']} recipients replied at "
            f"{worst['rate']['rate']:.2%} ({worst['rate']['successes']} of "
            f"{worst['rate']['trials']:,}) against {worst['rest']['rate']:.2%} "
            f"({worst['rest']['successes']} of {worst['rest']['trials']:,}) for everyone "
            f"else. They all got the same emails, so the copy cannot explain that gap."
        )
        status = "provider_drag" if worst["share"] >= 0.35 else "provider_gap"
        headline = (
            f"{share} of this audience is on {worst['label']}, and that slice replied "
            f"worse than the rest of the campaign."
            if worst["share"] >= 0.35
            else f"{worst['label']} recipients ({share} of the audience) replied worse than the rest."
        )
        return {
            "status": status,
            "headline": headline,
            "detail": detail,
            "history": history_note,
            "history_status": history_status,
            "caveat": CAVEAT,
            "findings": findings,
        }

    above = sorted((f for f in findings if f["direction"] == "above"), key=lambda f: -f["share"])
    best = above[0] if above else None
    if best:
        return {
            "status": "provider_gap",
            "headline": (
                f"{best['label']} recipients ({best['share']:.0%} of the audience) "
                f"replied better than the rest of the campaign."
            ),
            "detail": (
                f"{best['rate']['rate']:.2%} ({best['rate']['successes']} of "
                f"{best['rate']['trials']:,}) against {best['rest']['rate']:.2%} elsewhere. "
                f"Worth weighting the next list toward them."
            ),
            "history": history_note,
            "history_status": history_status,
            "caveat": CAVEAT,
            "findings": findings,
        }

    biggest = groups[0] if groups else None
    mix = ", ".join(
        f"{row['share']:.0%} {row['label']}" for row in groups if row["group"] != "unknown"
    )
    return {
        "status": "no_provider_effect",
        "headline": f"No provider is dragging this campaign down. Mix: {mix}.",
        "detail": (
            "Every slice with enough replies to judge is within the confidence interval of "
            "the rest, so where the mail was going is not what separated this campaign's "
            "results — look at the copy and the list instead."
            if biggest
            else ""
        ),
        "history": history_note,
            "history_status": history_status,
        "caveat": CAVEAT,
        "findings": findings,
    }


def report(conn, campaign_id: int, outcomes: list[dict] | None = None) -> dict:
    """Everything the Overview panel and the AI brief need, in one call."""
    data = breakdown(conn, campaign_id, outcomes)
    past = history(conn, exclude_campaign_id=campaign_id)
    data["history"] = past
    data["diagnosis"] = diagnose(data, past)
    return data
