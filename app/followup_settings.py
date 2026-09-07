"""Per-client follow-up timing, persisted in the client's existing database."""
import json

from app import db
from app.config import settings

KEY = "followup_timing"


def payload():
    return {
        "days": settings.followup_wait_days[0],
        "cadence": list(settings.followup_wait_days),
        "hot_hours": settings.hot_followup_wait_hours,
        "max_followups": settings.max_followups,
        "revive_after_days": settings.revive_after_days,
    }


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("Provide follow-up timing as an object.")
    days = data.get("days")
    hot_hours = data.get("hot_hours")
    if type(days) is not int or not 1 <= days <= 365:
        raise ValueError("Follow-up interval must be a whole number from 1 to 365 days.")
    if type(hot_hours) is not int or not 0 <= hot_hours <= 8760:
        raise ValueError("Very hot lead interval must be 0 to 8760 hours (0 disables it).")
    return {"days": days, "hot_hours": hot_hours}


def apply(data):
    settings.followup_wait_days = (data["days"],)
    settings.hot_followup_wait_hours = data["hot_hours"]


def load():
    with db.db_session() as conn:
        saved = db.get_setting(conn, KEY)
    if saved:
        apply(validate(json.loads(saved)))


def save(data):
    values = validate(data)
    with db.db_session() as conn:
        db.set_setting(conn, KEY, json.dumps(values))
    apply(values)
    return payload()


def refresh_due_statuses():
    """Re-evaluate cached conversations, with no model call or email send."""
    from datetime import datetime
    from app import detector, scheduler

    with db.db_session() as conn:
        rows = conn.execute("""
            SELECT l.*, t.thread_json FROM leads_state l
            JOIN lead_threads t USING (campaign_id, lead_id)
            WHERE l.interested = 1 AND l.status IN ('active', 'awaiting_reply')
              AND l.category IN ('waiting', 'followup')
        """).fetchall()
    for row in rows:
        thread = [detector.NormalizedMessage(
            **{**message, "timestamp": datetime.fromisoformat(message["timestamp"])}
        ) for message in json.loads(row["thread_json"])]
        if thread and thread[-1].kind == "sent":
            scheduler._queue_due_followup(row, row["campaign_id"], thread)
