"""One-off: run the cheap reply classifier over leads already sitting in the
inbox and sort the autoresponders and rejections out of the red tier.

The ongoing paths (webhook, reply-catch scan) classify a reply as it arrives.
This is for the backlog that accumulated before they did — the inbox filled
with "Thank you for your email, we aim to respond within 24 hours", because a
clinic's autoresponder is structurally a reply and nothing was reading it.

Classifies the lead's own last message from `last_message_preview`, which is
already plain text and is what a human would judge from. Leads with no preview
are skipped rather than guessed at.

    docker compose exec app python -m scripts.sort_inbox_replies --dry-run
    docker compose exec app python -m scripts.sort_inbox_replies

Nothing here is destructive in a way the dashboard can't undo: `auto_reply`
only re-labels, and `not_interested` archives (recoverable from the Archive
tab). Run --dry-run first and read the verdicts.
"""

import argparse
import logging

from app import db, reply_classifier

logging.basicConfig(level=logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="classify and print, change nothing")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--recheck-archived",
        action="store_true",
        help=(
            "Re-judge leads this script previously archived and put back any that now "
            "read as a live conversation. For after the prompt improves — the first "
            "pass filed a lead who had forwarded us to a colleague under 'no'."
        ),
    )
    args = parser.parse_args()

    db.init_db()
    if args.recheck_archived:
        _recheck_archived(args.dry_run)
        return

    with db.db_session() as conn:
        rows = conn.execute(
            """SELECT lead_id, campaign_id, name, email, last_message_preview
               FROM leads_state
               WHERE interested = 1 AND status != 'stopped' AND archived_at IS NULL
                 AND category = 'reply' AND last_message_preview IS NOT NULL
                 AND TRIM(last_message_preview) != ''
               ORDER BY last_message_at DESC LIMIT ?""",
            (args.limit,),
        ).fetchall()

    print("%d lead(s) in the awaiting-reply tier to check\n" % len(rows))
    counts: dict[str, int] = {}
    for row in rows:
        label, reason = reply_classifier.classify(row["last_message_preview"])
        counts[label] = counts.get(label, 0) + 1
        who = (row["name"] or row["email"] or str(row["lead_id"]))[:32]
        preview = " ".join((row["last_message_preview"] or "").split())[:60]
        print("  %-14s %-32s %s" % (label, who, preview))
        if not args.dry_run and label != reply_classifier.INTERESTED:
            with db.db_session() as conn:
                db.sort_replied_lead(conn, row["lead_id"], row["campaign_id"], label)

    print("\n  %s" % counts)
    if args.dry_run:
        print("  (dry run — nothing changed)")


def _recheck_archived(dry_run: bool) -> None:
    """Bring back everything an earlier version of this script archived.

    That version acted on a `not_interested` verdict by archiving and stopping
    the lead. It was wrong often enough to matter — see `db.sort_replied_lead`
    — so the verdict now only re-labels, and these rows have to come out of the
    archive to match. Unconditional on purpose: re-judging them with the same
    model that misfiled them is not evidence. They land back in the inbox
    labelled `not_interested`, out of the red tier, one click from archived if
    that is what Andrew decides.

    Matches on the auto-sorted reason string, so anything archived by hand is
    left alone."""
    with db.db_session() as conn:
        rows = conn.execute(
            """SELECT lead_id, campaign_id, name, email, last_message_preview
               FROM leads_state
               WHERE archive_reason LIKE '%auto-sorted%'
               ORDER BY archived_at DESC"""
        ).fetchall()

    print("%d auto-archived lead(s) to bring back\n" % len(rows))
    for row in rows:
        who = (row["name"] or row["email"] or str(row["lead_id"]))[:30]
        preview = " ".join((row["last_message_preview"] or "").split())[:58]
        print("  restore  %-30s %s" % (who, preview))
        if not dry_run:
            with db.db_session() as conn:
                db.upsert_lead_state(
                    conn, row["lead_id"], row["campaign_id"],
                    archived_at=None, archive_reason=None,
                    status="active", category="not_interested",
                )

    print("\n  restored: %d" % len(rows))
    if dry_run:
        print("  (dry run — nothing changed)")


if __name__ == "__main__":
    main()
