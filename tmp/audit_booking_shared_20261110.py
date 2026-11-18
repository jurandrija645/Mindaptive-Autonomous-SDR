import json
from app import smartlead, interested_sheet
from app.config import settings
for number,cells in interested_sheet._booking_rows(settings.interested_sheet_id):
    if cells[11] or not cells[5]: continue
    result={'row':number,'name':cells[4],'email':cells[5]}
    try:
        lead=smartlead.get_lead_by_email(cells[5])
        result['lead_id']=lead.get('id')
        result['campaigns']=lead.get('lead_campaign_data')
    except Exception as exc: result['error']=type(exc).__name__
    print(json.dumps(result),flush=True)
