"""Read-only overview of local and Smartlead-native subsequence memberships."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app import db, sequences, smartlead

log = logging.getLogger(__name__)
_lock = threading.Lock()
_loading = False
_snapshot = None
_pace_lock = threading.Lock()
_last_read = 0.0


def _pace_read():
    # Reserve most of the shared Smartlead budget for replies and booking
    # protection. The overview is read-only and runs in the background.
    global _last_read
    with _pace_lock:
        delay = 4.0 - (time.monotonic() - _last_read)
        if delay > 0:
            time.sleep(delay)
        _last_read = time.monotonic()


def start_refresh():
    """Refresh outside the HTTP request, which may outlive the tunnel timeout."""
    global _loading
    with _lock:
        if _loading:
            return
        _loading = True

    def run():
        global _loading, _snapshot
        try:
            result = overview()
        except Exception:
            log.exception("Subsequence overview failed")
            result = {"members": [], "warnings": ["Could not load subsequences. Try again."]}
        with _lock:
            _snapshot = result
            _loading = False

    threading.Thread(target=run, daemon=True, name="subsequence-overview").start()


def snapshot():
    with _lock:
        return {"loading": _loading, **(_snapshot or {"members": [], "warnings": []})}


def _native_member(child, member):
    lead = member.get("lead") or {}
    lead_id = lead.get("id")
    mapping_id = member.get("campaign_lead_map_id")
    result = {
        "source": "Smartlead", "sequence_name": child.get("name") or "Subsequence",
        "campaign_id": int(child["parent_campaign_id"]), "lead_id": lead_id,
        "name": " ".join(filter(None, [lead.get("first_name"), lead.get("last_name")])) or lead.get("email") or "Lead",
        "email": lead.get("email") or "", "company": lead.get("company_name") or "",
        "status": member.get("status") or "UNKNOWN", "campaign_status": child.get("status") or "UNKNOWN",
        "sent": None, "total": None, "next_send_at": None, "warnings": [],
    }
    if not lead_id or not mapping_id:
        result["warnings"].append("Membership details unavailable")
        return result
    try:
        _pace_read()
        overview = smartlead.get_lead_campaign_overview(int(lead_id))
        mapping = next((m for m in overview["email_campaign_leads_mappings"]
                        if str(m.get("id")) == str(mapping_id) and str(m.get("email_campaign_id")) == str(child["id"])), None)
        if mapping is None:
            raise ValueError("Mapping missing from overview")
        result["status"] = mapping.get("status") or "UNKNOWN"
        if mapping.get("is_active") is False:
            result["status"] = "INACTIVE"
        campaign = mapping.get("email_campaign") or {}
        result["total"] = campaign.get("sequence_count")
        if result["status"] in {"STARTED", "INPROGRESS"} and result["campaign_status"] == "ACTIVE":
            result["next_send_at"] = mapping.get("next_timestamp_to_reach")
    except Exception:
        log.exception("Could not read subsequence schedule for mapping %s", mapping_id)
        result["warnings"].append("Schedule unavailable")
    try:
        _pace_read()
        details = smartlead.get_lead_sequence_details(int(mapping_id), int(child["id"]))
        # A stats response can contain multiple rows for a step; count the
        # distinct sent steps, not drafted/stopped rows or repeated attempts.
        sent = [d for d in details if str(d.get("status") or "").upper() == "SENT"]
        if any(d.get("email_campaign_seq_id") is None for d in sent):
            raise ValueError("Sent step has no ID")
        result["sent"] = len({str(d["email_campaign_seq_id"]) for d in sent})
    except Exception:
        log.exception("Could not read sent subsequence steps for mapping %s", mapping_id)
        result["warnings"].append("Sent count unavailable")
    return result


def overview():
    with db.db_session() as conn:
        rows = conn.execute("SELECT * FROM sequence_enrollments ORDER BY enrolled_at DESC").fetchall()
        local = []
        for row in rows:
            p = sequences.enrollment_payload(conn, row)
            local.append({"source": "Responder", "sequence_name": p["sequence_name"],
                          "campaign_id": p["campaign_id"], "lead_id": p["lead_id"],
                          "name": p["lead_name"] or p["lead_email"] or "Lead",
                          "company": p["lead_company"], "email": p["lead_email"],
                          "status": p["state"].upper(), "campaign_status": "ACTIVE",
                          "sent": p["steps_sent"], "total": p["step_count"],
                          "next_send_at": p["next_send_at"] if p["state"] == "active" else None,
                          "warnings": []})
    warnings = []
    jobs = []
    try:
        children = [c for c in smartlead.list_campaigns() if c.get("parent_campaign_id")]
        for child in children:
            try:
                jobs.extend((child, member) for member in smartlead.list_campaign_leads(int(child["id"])))
            except Exception:
                log.exception("Could not read subsequence %s", child.get("id"))
                warnings.append(f"Could not load members of {child.get('name') or 'a Smartlead subsequence'}.")
    except Exception:
        log.exception("Could not list Smartlead subsequences")
        warnings.append("Could not load Smartlead subsequences. Try again.")
    with ThreadPoolExecutor(max_workers=4) as pool:
        native = list(pool.map(lambda args: _native_member(*args), jobs))
    return {"members": local + native, "warnings": warnings}
