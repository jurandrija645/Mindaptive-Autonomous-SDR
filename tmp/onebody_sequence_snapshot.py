import json
from datetime import datetime, timezone
from app import db
from app.config import settings

with db.db_session() as conn:
    def rows(sql):
        return [dict(r) for r in conn.execute(sql).fetchall()]
    result = {
        'now': datetime.now(timezone.utc).isoformat(),
        'dry_run': settings.dry_run,
        'sequences': rows('SELECT * FROM sequences'),
        'steps': rows('SELECT * FROM sequence_steps'),
        'enrollments': rows('''SELECT e.*, s.name sequence_name, ls.name lead_name, ls.company,
            ls.email, ls.status lead_status, ls.smartlead_category,
            d.status draft_status, d.scheduled_at, d.sent_at, d.send_error, d.body_html
            FROM sequence_enrollments e JOIN sequences s ON s.id=e.sequence_id
            LEFT JOIN leads_state ls ON ls.lead_id=e.lead_id AND ls.campaign_id=e.campaign_id
            LEFT JOIN drafts d ON d.id=e.draft_id ORDER BY e.enrolled_at DESC'''),
        'angie': rows("SELECT * FROM leads_state WHERE lower(name) LIKE '%angie%' OR lower(company) LIKE '%goldfinch%'"),
        'sequence_drafts': rows("SELECT id,lead_id,campaign_id,enrollment_id,step_position,status,scheduled_at,sent_at,send_error,body_html FROM drafts WHERE kind='sequence' AND created_at >= '2026-10-24'"),
    }
print(json.dumps(result, default=str))
