"""Weekly inbox-placement tests and what a failed one does to a mailbox.

Smartlead's warmup reputation cannot see spam placement: on 27 Oct 2026 every one
of Mindaptive's 127 mailboxes read 100% while the 21 Oct SmartDelivery seed test
put about a third of the same mailboxes in spam. So once a week every sending
mailbox is tested against Smartlead's seed inboxes, and the latest result per
mailbox decides:

- at or above the placement threshold (default 90% inbox) the mailbox may send,
  and its stage follows reputation as usual (deliverability_health);
- below it the mailbox is held in rehab whatever its reputation, and is taken
  out of every active campaign, with its leads moved to the mailboxes that stay.
  A campaign is never emptied: if all its mailboxes failed, it is left alone and
  an alert is raised instead.

Tests made by hand in the Smartlead UI are read too; they are evidence like ours.
Creating a test spends placement credits, so it only happens when
PLACEMENT_TESTS_ENABLED is on (or when someone asks for one explicitly), and
taking mailboxes out of campaigns also needs the Health switch on and
DRY_RUN=false.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

from app import db, smartlead
from app.config import settings

log = logging.getLogger("placement")

BATCH_SIZE = 50           # the size every test made by hand so far has used
PROVIDER_IDS = [20, 21]   # G Suite and Office365, the account's seed groups
MIN_SEEDS = 2             # fewer seed results than this is not a verdict
# A test can stay ACTIVE for days when a seed never receives its copy; read
# whatever arrived once it is this old.
READ_AFTER_HOURS = 36
LOOKBACK_DAYS = 21

_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---- reading results ----

def latest_by_email(conn) -> dict[str, dict]:
    """Each mailbox's most recent conclusive result."""
    rows = conn.execute(
        """SELECT p.* FROM mailbox_placement p
           JOIN (SELECT email, MAX(tested_at) AS at FROM mailbox_placement GROUP BY email) last
             ON last.email = p.email AND last.at = p.tested_at"""
    ).fetchall()
    return {row["email"]: dict(row) for row in rows}


def failing_emails(conn, threshold: int) -> set[str]:
    return {email for email, row in latest_by_email(conn).items() if row["inbox_pct"] < threshold}


def _score(row: dict) -> tuple[str, int, int, int] | None:
    email = str(row.get("email") or row.get("from_email") or "").strip().lower()
    if not email:
        return None
    folders = Counter(
        str(((d.get("reply") or {}).get("mail_folder")) or "")
        for d in row.get("details") or []
    )
    folders.pop("", None)  # seed has not received it (yet)
    total = sum(folders.values())
    if total < MIN_SEEDS:
        return None
    inbox = folders.get("Inbox", 0)
    return email, inbox, folders.get("Spam", 0), total


def collect_results() -> dict:
    """Read every finished test from the last three weeks that is not read yet."""
    tests = smartlead.list_placement_tests()
    cutoff = _now() - timedelta(days=LOOKBACK_DAYS)
    read = 0
    with db.db_session() as conn:
        done = {r["spam_test_id"] for r in conn.execute(
            "SELECT spam_test_id FROM placement_tests WHERE collected_at IS NOT NULL")}
    for test in tests:
        test_id = int(test["spam_test_id"])
        created = _parse(test.get("created_at"))
        if test_id in done or not created or created < cutoff:
            continue
        finished = test.get("status") == "COMPLETED" or created <= _now() - timedelta(hours=READ_AFTER_HOURS)
        if not finished:
            continue
        rows = [s for s in (_score(r) for r in smartlead.placement_sender_report(test_id)) if s]
        with db.db_session() as conn:
            conn.execute(
                """INSERT INTO placement_tests(spam_test_id,test_name,created_at,origin,sender_count,status,collected_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(spam_test_id) DO UPDATE SET status=excluded.status,
                     collected_at=excluded.collected_at,sender_count=excluded.sender_count""",
                (test_id, test.get("test_name"), _iso(created), "external", len(rows), test.get("status"), _iso()),
            )
            for email, inbox, spam, total in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO mailbox_placement(spam_test_id,email,tested_at,inbox,spam,total,inbox_pct)
                       VALUES (?,?,?,?,?,?,?)""",
                    (test_id, email, _iso(created), inbox, spam, total, round(100 * inbox / total)),
                )
        read += 1
    return {"tests_read": read}


# ---- starting a test ----

def _home_campaigns(senders: list[str]) -> dict[str, int]:
    """Each mailbox's campaign for the test copy.

    SmartDelivery only accepts senders attached to the campaign whose step is
    being sent ("Sender email accounts ... not used in the campaign", 400), so a
    mailbox is tested with the copy it actually sends: the configured campaign
    if it is in it, otherwise its newest active campaign, otherwise its newest
    campaign of any status. A mailbox in no campaign cannot be tested.
    """
    wanted = set(senders)
    campaigns = sorted(smartlead.list_campaigns(), key=lambda c: (c.get("status") != "ACTIVE", -int(c["id"])))
    preferred = settings.placement_campaign_id
    if preferred:
        campaigns.sort(key=lambda c: int(c["id"]) != preferred)
    home: dict[str, int] = {}
    for campaign in campaigns:
        if len(home) == len(wanted):
            break
        if campaign.get("status") in ("DRAFTED", "STOPPED"):
            continue
        for account in smartlead.get_campaign_email_accounts(int(campaign["id"])):
            email = (account.get("from_email") or "").strip().lower()
            if email in wanted and email not in home:
                home[email] = int(campaign["id"])
    return home


def _first_step(campaign_id: int) -> int:
    steps = sorted(smartlead.get_campaign_sequences(campaign_id), key=lambda s: s.get("seq_number") or 0)
    if not steps:
        raise RuntimeError(f"Campaign {campaign_id} has no sequence steps")
    return int(steps[0]["id"])


def _created_id(response, test_name: str) -> int | None:
    for node in (response, (response or {}).get("data") if isinstance(response, dict) else None):
        if isinstance(node, dict):
            for key in ("spam_test_id", "id", "spamTestId"):
                if isinstance(node.get(key), int):
                    return node[key]
    for test in smartlead.list_placement_tests():
        if test.get("test_name") == test_name:
            return int(test["spam_test_id"])
    return None


def start_test(*, emails: list[str] | None = None, label: str | None = None, origin: str = "weekly") -> dict:
    """Test every connected, warming mailbox (or just ``emails``), 50 per test.

    The weekly job only runs with PLACEMENT_TESTS_ENABLED; passing ``emails``
    is an explicit request and runs regardless, but never under DRY_RUN.
    """
    if emails is None and not settings.placement_tests_enabled:
        return {"started": False, "reason": "PLACEMENT_TESTS_ENABLED is off"}
    if not _lock.acquire(blocking=False):
        return {"started": False, "reason": "already_running"}
    try:
        from app import deliverability_health as health

        excluded = health.excluded_domains()
        accounts = [
            a for a in smartlead.list_email_accounts()
            if (a.get("warmup_details") or {}).get("status") == "ACTIVE" and a.get("is_smtp_success")
        ]
        senders = sorted(
            {(a.get("from_email") or "").strip().lower() for a in accounts} - {""}
        )
        senders = [e for e in senders if health._domain(e) not in excluded]
        if emails is not None:
            wanted = {e.strip().lower() for e in emails}
            senders = [e for e in senders if e in wanted]
        if not senders:
            return {"started": False, "reason": "no mailboxes to test"}
        home = _home_campaigns(senders)
        untestable = sorted(set(senders) - set(home))
        groups: dict[int, list[str]] = {}
        for email in senders:
            if email in home:
                groups.setdefault(home[email], []).append(email)
        batches = [
            (cid, members[i:i + BATCH_SIZE])
            for cid, members in groups.items()
            for i in range(0, len(members), BATCH_SIZE)
        ]
        if settings.dry_run:
            return {"started": False, "reason": "dry_run", "would_test": len(senders) - len(untestable),
                    "tests": len(batches), "untestable": untestable}
        stamp = _now().strftime("%Y-%m-%d")
        created = []
        for n, (campaign_id, batch) in enumerate(batches, start=1):
            sequence_id = _first_step(campaign_id)
            name = f"{label or 'Weekly placement'} {stamp} {n}/{len(batches)}"
            payload = {
                "test_name": name,
                "description": "Automatic placement test from the SDR Health tab",
                "spam_filters": ["spam_assassin"],
                "link_checker": True,
                "campaign_id": campaign_id,
                "sequence_mapping_id": sequence_id,
                "provider_ids": PROVIDER_IDS,
                "sender_accounts": batch,
                "all_email_sent_without_time_gap": False,
                "min_time_btwn_emails": 10,
                "min_time_unit": "minutes",
                "is_warmup": False,
            }
            test_id = _created_id(smartlead.create_placement_test(payload), name)
            if test_id is None:
                log.error("placement test %s created but its id could not be found", name)
                continue
            with db.db_session() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO placement_tests(spam_test_id,test_name,created_at,origin,sender_count,status)
                       VALUES (?,?,?,?,?, 'ACTIVE')""",
                    (test_id, name, _iso(), origin, len(batch)),
                )
            created.append(test_id)
        return {"started": True, "tests": created, "mailboxes": len(senders) - len(untestable), "untestable": untestable}
    finally:
        _lock.release()


# ---- acting on results ----

def enforce() -> dict:
    """Take mailboxes whose latest test failed out of every active campaign."""
    from app import deliverability_health as health  # health imports this module

    policy = health.load_policy()
    excluded = health.excluded_domains(policy)
    with db.db_session() as conn:
        failing = {e for e in failing_emails(conn, policy["placement_threshold"]) if health._domain(e) not in excluded}
    if not failing:
        return {"campaigns": 0, "removed": 0}
    may_write = policy["auto_apply"] and not settings.dry_run
    touched = removed = 0
    alerts = []
    for campaign in smartlead.list_campaigns():
        if campaign.get("status") != "ACTIVE":
            continue
        cid = int(campaign["id"])
        attached = smartlead.get_campaign_email_accounts(cid)
        bad = [a for a in attached if (a.get("from_email") or "").strip().lower() in failing]
        if not bad:
            continue
        emails = sorted((a.get("from_email") or "").lower() for a in bad)
        if len(bad) == len(attached):
            action, detail = "kept_last_mailboxes", "every mailbox in this campaign failed its placement test"
            alerts.append({"type": "campaign_all_mailboxes_failed_placement", "campaign": campaign.get("name"), "mailboxes": len(bad)})
        elif not may_write:
            action, detail = "would_remove", "Health switch off or DRY_RUN on"
        else:
            ids = [int(a["id"]) for a in bad]
            try:
                smartlead.remove_campaign_email_accounts(cid, ids)
                for i in range(0, len(ids), 100):
                    smartlead.reallocate_campaign_mailboxes(cid, ids[i:i + 100])
                action, detail = "removed", f"{len(ids)} mailboxes removed and their leads reallocated"
                removed += len(ids)
                alerts.append({"type": "mailboxes_removed_after_placement", "campaign": campaign.get("name"), "mailboxes": emails})
            except smartlead.SmartleadError as exc:
                action, detail = "failed", str(exc)[:500]
        touched += 1
        with db.db_session() as conn:
            conn.execute(
                """INSERT INTO placement_actions(at,campaign_id,campaign_name,emails_json,action,detail)
                   VALUES (?,?,?,?,?,?)""",
                (_iso(), cid, campaign.get("name"), json.dumps(emails), action, detail),
            )
    for alert in alerts:
        health._notify(alert)
    return {"campaigns": touched, "removed": removed}


def run_collect_and_enforce() -> dict:
    """The frequent job: read finished tests, then act if a verdict changed."""
    try:
        read = collect_results()
        result = {**read, **(enforce() if read["tests_read"] else {})}
        if read["tests_read"]:
            from app import deliverability_health as health

            health.trigger()  # move held mailboxes to rehab now, not tomorrow
        return result
    except Exception:
        log.exception("placement collect/enforce failed")
        return {"error": True}


def run_weekly() -> dict:
    try:
        return start_test()
    except Exception:
        log.exception("weekly placement test failed to start")
        return {"started": False, "error": True}
