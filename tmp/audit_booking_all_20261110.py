import json
from app import db, smartlead, interested_sheet, webhook
from app.config import settings

categories=smartlead.fetch_categories()
booked_id=next(v for k,v in categories.items() if 'meetingbooked'==''.join(c.lower() for c in k if c.isalnum()))
all_rows=interested_sheet._booking_rows(settings.interested_sheet_id)
for number,cells in all_rows:
    with db.db_session() as conn:
        matches,by=webhook._booking_matches(conn,cells[5],cells[4],cells[7])
        matches=[dict(r) for r in matches]
    result={'row':number,'name':cells[4],'email':cells[5],'attribution':cells[8],'matched_by_now':by,'lead_id':cells[11],'local':[{'lead_id':r['lead_id'],'campaign_id':r['campaign_id'],'status':r['status']} for r in matches]}
    lid=cells[11] or (matches[0]['lead_id'] if matches else None)
    if lid:
        try:
            overview=smartlead.get_lead_campaign_overview(int(lid))
            result['mappings']=[{'campaign':m['email_campaign_id'],'category':m.get('lead_category_id'),'status':m.get('status'),'active':m.get('is_active')} for m in overview['email_campaign_leads_mappings']]
        except Exception as exc: result['error']=type(exc).__name__
    print(json.dumps(result),flush=True)
print(json.dumps({'booked_id':booked_id}),flush=True)
