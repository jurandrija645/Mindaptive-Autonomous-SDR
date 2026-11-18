import json
from app import auto_replies, db, models_registry
from app.config import settings

with db.db_session() as conn:
    leads = [dict(r) for r in conn.execute(
        "SELECT lead_id,campaign_id,name,email,company,category,status,last_message_at "
        "FROM leads_state WHERE lower(email)='konstantin@iconoclast.tv' OR name LIKE '%Kissimov%'"
    )]
    drafts = [dict(r) for lead in leads for r in conn.execute(
        "SELECT id,lead_id,campaign_id,kind,status,created_at,sent_at,scheduled_at,send_error "
        "FROM drafts WHERE lead_id=? AND campaign_id=? ORDER BY id DESC LIMIT 5",
        (lead['lead_id'],lead['campaign_id']))]
print(json.dumps({'auto_replies':auto_replies.enabled(),
                  'auto_send_followups':settings.auto_send_followups,
                  'dry_run':settings.dry_run, 'model':models_registry.resolve(None),
                  'leads':leads, 'drafts':drafts}, default=str))
