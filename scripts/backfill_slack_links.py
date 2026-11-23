"""One-off: link the reply notifications already in a Slack channel to their
leads, so app/slack_links.py can mark them answered / booked like new ones.

Run inside the client's container, after SLACK_BOT_TOKEN is set (it also needs
channels:history, or groups:history for a private channel):

    python -m scripts.backfill_slack_links --channel C0BN1FR0NAH --days 30          # dry run
    python -m scripts.backfill_slack_links --channel C0BN1FR0NAH --days 30 --go

Each "Ekipica dosla je poruka od ... Poslao: <email>" message is matched to the
lead by email. The next slack_links sync (every minute) then checks each lead's
Smartlead thread for a reply sent after the post (posts newer than 14 days)
and adds ✅, and adds 📅 to every lead that has booked.
"""
import argparse
import re
import time
from datetime import datetime, timezone

import httpx

from app import db, slack_links
from app.config import settings

EMAIL = re.compile(r"Poslao:\s*<?(?:mailto:)?([^\s|<>]+@[^\s|<>]+)", re.I)


def history(channel: str, oldest: float):
    cursor = None
    while True:
        params = {"channel": channel, "oldest": str(oldest), "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = httpx.get("https://slack.com/api/conversations.history", params=params,
                         headers={"Authorization": f"Bearer {settings.slack_bot_token}"}, timeout=30).json()
        if not data.get("ok"):
            raise SystemExit(f"Slack conversations.history: {data.get('error')}")
        yield from data.get("messages", [])
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--go", action="store_true")
    args = ap.parse_args()
    if not settings.slack_bot_token:
        raise SystemExit("SLACK_BOT_TOKEN is not set")
    db.init_db()
    oldest = time.time() - args.days * 86400
    found = linked = unknown = 0
    for msg in history(args.channel, oldest):
        if msg.get("thread_ts") not in (None, msg.get("ts")):
            continue
        m = EMAIL.search(msg.get("text") or "")
        if not m or "Ekipica" not in (msg.get("text") or ""):
            continue
        found += 1
        email = m.group(1).lower()
        with db.db_session() as conn:
            rows = db.find_lead_by_email(conn, email)
            if not rows:
                unknown += 1
                print("no lead for", email)
                continue
            row = max(rows, key=lambda r: r["updated_at"] or "")
            posted_at = datetime.fromtimestamp(float(msg["ts"]), timezone.utc).isoformat()
            if args.go:
                linked += slack_links.record_post(conn, channel=args.channel, ts=msg["ts"],
                                                  campaign_id=row["campaign_id"], lead_id=row["lead_id"],
                                                  email=email, posted_at=posted_at)
            else:
                linked += 1
    print(f"notifications {found}, linked {linked}, no matching lead {unknown}"
          + ("" if args.go else "  (dry run, nothing written)"))


if __name__ == "__main__":
    main()
