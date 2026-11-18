import csv, io, json, logging, sys
from datetime import datetime,timezone
from app import db,smartlead
from app.config import settings
logging.disable(logging.CRITICAL)
with db.db_session() as c:
 states=[dict(r) for r in c.execute('SELECT * FROM leads_state')]
 drafts=[dict(r) for r in c.execute('SELECT id,lead_id,campaign_id,kind,status,reply_message_id,created_at,sent_at,scheduled_at FROM drafts')]
 enroll=[dict(r) for r in c.execute('SELECT * FROM sequence_enrollments')]
 print('',file=sys.stderr)
campaigns=list(smartlead.list_campaigns())
exports={}
for cp in campaigns:
 cid=cp['id']
 raw=smartlead.export_campaign_leads_csv(cid)
 rows=list(csv.DictReader(io.StringIO(raw)))
 fields=['id','campaign_lead_map_id','first_name','last_name','email','category','status','reply_count','is_unsubscribed','is_interested','last_email_sequence_sent','company_name','website']
 exports[str(cid)]=[{k:r.get(k) for k in fields} for r in rows]
 print('Export',cid,len(rows),file=sys.stderr,flush=True)
print(json.dumps(dict(captured_at=datetime.now(timezone.utc).isoformat(),states=states,drafts=drafts,enrollments=enroll,campaigns=campaigns,exports=exports,categories=smartlead.fetch_categories(),config={k:getattr(settings,k) for k in ['followup_wait_days','hot_followup_wait_hours','max_followups','revive_after_days','followup_business_days','auto_send_followups','public_base_url','scan_interval_minutes']})))
