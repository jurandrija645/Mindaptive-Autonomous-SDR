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
    args = parser.parse_args()

    db.init_db()
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


if __name__ == "__main__":
    main()
