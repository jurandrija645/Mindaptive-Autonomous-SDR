import json
from pathlib import Path
from app import db, smartlead, sheets, interested_sheet, booking_guard
from app.config import settings

print(json.dumps({'dry_run': settings.dry_run, 'sheet_enabled': bool(settings.interested_sheet_id)}), flush=True)
with db.db_session() as conn:
    local = [dict(r) for r in conn.execute("SELECT lead_id,campaign_id,email,name,status,smartlead_category,booked_at FROM leads_state WHERE status='booked' ORDER BY booked_at DESC")]
    pending = [dict(r) for r in conn.execute("SELECT key,value FROM app_settings WHERE key LIKE 'booked_pause_pending:%'")]
print(json.dumps({'local_booked_rows':len(local),'pending':pending}), flush=True)
cats=smartlead.fetch_categories()
print(json.dumps({'categories':cats}), flush=True)
rows=interested_sheet._booking_rows(settings.interested_sheet_id)
print(json.dumps({'sheet_bookings':len(rows)}), flush=True)
for number, cells in rows[-35:]:
    email=cells[5]
    with db.db_session() as conn:
        matches=[dict(r) for r in db.find_lead_by_email(conn,email)] if email else []
    lid=cells[11] or (matches[0]['lead_id'] if matches else None)
    result={'sheet_row':number,'name':cells[4],'email':email,'attribution':cells[8], 'matched_by':cells[9], 'sheet_campaign':cells[10],'sheet_lead':cells[11], 'local':[{'lead_id':r['lead_id'],'campaign_id':r['campaign_id'],'status':r['status'],'smartlead_category':r['smartlead_category']} for r in matches]}
    if lid:
        try:
            result['mappings']=smartlead.get_lead_campaign_overview(int(lid))['email_campaign_leads_mappings']
        except Exception as exc: result['error']=type(exc).__name__
    print(json.dumps(result),flush=True)
print(json.dumps({'live_guard_source':Path(booking_guard.__file__).read_text(),'live_record_source':Path('/srv/app/scheduler.py').read_text().split('def record_explicit_booking(')[1].split('_new_reply_lock')[0]}),flush=True)

