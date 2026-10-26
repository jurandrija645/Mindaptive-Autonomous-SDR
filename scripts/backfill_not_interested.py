"""Import existing negative leads for review, without drafting or sending mail.

Run in the intended container: python -m scripts.backfill_not_interested
Requires SHOW_NOT_INTERESTED_LEADS=true. Manual archives and contact suppression
are preserved by the same importer used by the daily scan and reply poll.
"""
import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import db, detector, pipeline, scheduler, smartlead
from app.config import settings


def main():
    if not settings.show_not_interested_leads:
        raise SystemExit("Enable SHOW_NOT_INTERESTED_LEADS on the intended account first")
    folder = Path(settings.db_path).parent / "negative-review-backfill"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with sqlite3.connect(settings.db_path) as source, sqlite3.connect(folder / f"{stamp}.db") as backup:
        source.backup(backup)
    results = []
    for campaign in smartlead.list_campaigns():
        cid = campaign["id"]
        rows = csv.DictReader(io.StringIO(smartlead.export_campaign_leads_csv(cid)))
        leads = [r for r in rows if scheduler.norm_category_name(r.get("category") or "")
                 == scheduler.norm_category_name(settings.not_interested_category_name)
                 and str(r.get("is_unsubscribed")).lower() != "true"]
        if not leads:
            continue
        bulk = smartlead.get_message_history_bulk(cid, [int(r["id"]) for r in leads])
        for lead in leads:
            lid = int(lead["id"])
            entry = bulk.get(str(lid)) or {}
            raw = entry.get("history") if isinstance(entry, dict) else entry
            thread = detector.normalize_thread(raw or [])
            # A failed/empty history must not leave a blank, apparently repaired row.
            if not thread:
                results.append(dict(campaign_id=cid, lead_id=lid, outcome="empty_history"))
                continue
            pipeline.cache_normalized_thread(cid, lid, thread)
            scheduler._show_not_interested_lead(
                dict(lead, id=lid, campaign_id=cid,
                     name=" ".join(p for p in (lead.get("first_name"), lead.get("last_name")) if p)),
                campaign.get("name") or "", lead["category"], thread=thread,
            )
            with db.db_session() as conn:
                visible = any(r["lead_id"] == lid and r["campaign_id"] == cid for r in db.list_inbox(conn))
            results.append(dict(campaign_id=cid, lead_id=lid, outcome="visible" if visible else "preserved_hidden"))
        print(json.dumps(dict(campaign=campaign.get("name"), reviewed=len(leads))), flush=True)
    (folder / f"{stamp}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(dict(total=len(results), visible=sum(r["outcome"] == "visible" for r in results),
                         empty_history=sum(r["outcome"] == "empty_history" for r in results))), flush=True)


if __name__ == "__main__":
    main()
