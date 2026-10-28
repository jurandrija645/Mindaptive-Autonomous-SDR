"""A booking stops outreach across this account, including native subsequences.

Local hooks freeze before network calls. The periodic repair catches changes
made only in Smartlead; it reads booked parents in bulk, not every lead's
thread. Native sends belong to Smartlead, so external-only changes have a
polling delay. Responder sends also check live mappings immediately before send.
Never resumes a paused lead or uses the global opt-out list for a booking.
"""
import json
import logging
import re
import threading

from app import db, smartlead
from app.config import settings

log = logging.getLogger("booking_guard")
_sweep_lock = threading.Lock()
SENDABLE = {"STARTED", "INPROGRESS"}
_PENDING = "booked_pause_pending:"


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _email(value) -> str:
    return str(value or "").strip().lower()


def _identity(conn, lead_id: int, email: str = "") -> tuple[str, list]:
    if not email:
        row = conn.execute("SELECT email FROM leads_state WHERE lead_id = ? AND email IS NOT NULL LIMIT 1", (lead_id,)).fetchone()
        email = row["email"] if row else ""
    email = _email(email)
    rows = conn.execute(
        "SELECT * FROM leads_state WHERE lead_id = ? OR (? != '' AND lower(trim(email)) = ?)",
        (lead_id, email, email),
    ).fetchall()
    return email, rows


def is_locally_booked(lead_id: int, email: str = "") -> bool:
    with db.db_session() as conn:
        _, rows = _identity(conn, lead_id, email)
        return any(r["status"] == "booked" for r in rows)


def freeze_local(lead_id: int, campaign_id: int, email: str = "") -> None:
    """Persist the booking and invalidate every local campaign's open work."""
    with db.db_session() as conn:
        email, rows = _identity(conn, lead_id, email)
        if not any(r["lead_id"] == lead_id and r["campaign_id"] == campaign_id for r in rows):
            db.upsert_lead_state(conn, lead_id, campaign_id, email=email or None)
            _, rows = _identity(conn, lead_id, email)
        for row in rows:
            # Preserve stronger DNC suppression; its drafts are already frozen.
            if row["status"] != "blacklisted":
                db.mark_lead_booked(conn, row["lead_id"], row["campaign_id"])


def enforce_booked_lead(lead_id: int, campaign_id: int, email: str = "") -> dict:
    """Freeze now, pause every sendable native mapping; failures retry on sweep."""
    freeze_local(lead_id, campaign_id, email)
    result = {"paused": [], "errors": []}
    if settings.dry_run:
        return result
    # Durable retries also cover a failed parent pause when there is no native
    # child to discover in the periodic membership scan.
    key = _PENDING + str(lead_id)
    with db.db_session() as conn:
        db.set_setting(conn, key, json.dumps({"lead_id": lead_id, "campaign_id": campaign_id, "email": email}))
    try:
        overview = smartlead.get_lead_campaign_overview(lead_id)
    except Exception:
        log.exception("could not load booked lead %s; native pause will retry", lead_id)
        result["errors"].append(lead_id)
        return result
    for mapping in overview["email_campaign_leads_mappings"]:
        if mapping.get("is_active") is False or mapping.get("status") not in SENDABLE:
            continue
        try:
            cid = int(mapping["email_campaign_id"])
            smartlead.pause_campaign_lead(cid, lead_id)
            result["paused"].append(cid)
        except Exception:
            log.exception("could not pause booked lead %s mapping %s", lead_id, mapping.get("id"))
            result["errors"].append(mapping.get("id"))
    if not result["errors"]:
        with db.db_session() as conn:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
    return result


def allow_send(lead_id: int, campaign_id: int, email: str = "") -> bool:
    """Fail closed on unreadable live status. Used by ALL responder draft kinds."""
    if is_locally_booked(lead_id, email):
        freeze_local(lead_id, campaign_id, email)
        return False
    if settings.dry_run:
        return True
    overview = smartlead.get_lead_campaign_overview(lead_id)
    mappings = overview["email_campaign_leads_mappings"]
    if not any(str(m.get("email_campaign_id")) == str(campaign_id) and m.get("is_active") is not False for m in mappings):
        raise smartlead.SmartleadError("Could not verify this lead's campaign before sending.")
    categories = smartlead.fetch_categories()
    booked_ids = {str(cid) for name, cid in categories.items() if _norm(name) == _norm(settings.meeting_booked_category_name)}
    if not booked_ids:
        raise smartlead.SmartleadError("Could not verify the Meeting Booked category before sending.")
    if any(str(m.get("lead_category_id")) in booked_ids for m in mappings):
        enforce_booked_lead(lead_id, campaign_id, overview.get("email") or email)
        return False
    # A booking webhook may have committed while the two API calls were running.
    if is_locally_booked(lead_id, email):
        freeze_local(lead_id, campaign_id, email)
        return False
    return True


def run_native_booking_guard() -> dict:
    """Repair native subsequences every 30s, including manual Smartlead bookings.

    Seven reads for OneBody's four children/two parents; no per-lead network
    unless a booking needs enforcement. One failed parent/child never hides
    bookings found in other campaigns. Every pass retries unpaused matches.
    """
    result = {"checked": 0, "paused": 0, "errors": 0}
    if not _sweep_lock.acquire(blocking=False):
        return result
    try:
        with db.db_session() as conn:
            pending = conn.execute("SELECT value FROM app_settings WHERE key LIKE ? LIMIT 20", (_PENDING + "%",)).fetchall()
        for row in pending:
            data = json.loads(row["value"])
            # A manual category change can release the booking lock. Never
            # enforce a stale retry after that explicit release.
            if not is_locally_booked(data["lead_id"], data.get("email") or ""):
                with db.db_session() as conn:
                    conn.execute("DELETE FROM app_settings WHERE key = ?", (_PENDING + str(data["lead_id"]),))
                continue
            outcome = enforce_booked_lead(**data)
            result["paused"] += len(outcome["paused"])
            result["errors"] += len(outcome["errors"])
        campaigns = smartlead.list_campaigns()
        children = [c for c in campaigns if c.get("parent_campaign_id") and c.get("status") in {"ACTIVE", "PAUSED"}]
        if not children:
            return result
        categories = smartlead.fetch_categories()
        booked_ids = {str(cid) for name, cid in categories.items() if _norm(name) == _norm(settings.meeting_booked_category_name)}
        if not booked_ids:
            raise smartlead.SmartleadError("Native booking guard cannot resolve Meeting Booked.")
        with db.db_session() as conn:
            local = conn.execute("SELECT lead_id, campaign_id, email FROM leads_state WHERE status = 'booked'").fetchall()
        booked = {int(r["lead_id"]): int(r["campaign_id"]) for r in local}
        booked_emails = {_email(r["email"]): int(r["campaign_id"]) for r in local if _email(r["email"])}
        for parent_id in {int(c["parent_campaign_id"]) for c in children}:
            for category_id in booked_ids:
                try:
                    for row in smartlead.list_campaign_leads(parent_id, category_id=int(category_id)):
                        if str(row.get("lead_category_id")) not in booked_ids:
                            continue
                        lead = row.get("lead") or {}
                        if lead.get("id"):
                            booked[int(lead["id"])] = parent_id
                        if _email(lead.get("email")):
                            booked_emails[_email(lead["email"])] = parent_id
                except Exception:
                    result["errors"] += 1
                    log.exception("native booking guard could not read parent %s", parent_id)
        handled = set()
        for child in children:
            try:
                for row in smartlead.list_campaign_leads(int(child["id"])):
                    if row.get("status") not in SENDABLE:
                        continue
                    result["checked"] += 1
                    lead = row.get("lead") or {}
                    lid = int(lead["id"])
                    email = _email(lead.get("email"))
                    source = booked.get(lid) or booked_emails.get(email)
                    if str(row.get("lead_category_id")) in booked_ids:
                        source = int(child["id"])
                    if source is None or lid in handled:
                        continue
                    handled.add(lid)
                    outcome = enforce_booked_lead(lid, source, email)
                    result["paused"] += len(outcome["paused"])
                    result["errors"] += len(outcome["errors"])
            except Exception:
                result["errors"] += 1
                log.exception("native booking guard could not process child %s", child["id"])
        return result
    except Exception:
        result["errors"] += 1
        log.exception("native booking guard failed; will retry")
        return result
    finally:
        _sweep_lock.release()
