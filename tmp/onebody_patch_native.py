import json
from app import smartlead

ids = [4235673, 4235670, 4235352, 4235340]
fee = "There's a small £4.99 booking fee that holds your time slot."
sharing = 'Feel free to share the link and code with colleagues too, each person at {{company_name}} gets one free session.'
result = {'paused_leads': [], 'campaigns': []}
# These three have a newer reply or a booked category in the parent campaign.
for cid,email in [(4235670,'seandowney@rgjones.co.uk'),(4235340,'lila.szczesnowicz@signal-ai.com'),
                  (4235352,'ben.butler@hawesandco.co.uk')]:
    matches=[r['lead']['id'] for r in smartlead.list_campaign_leads(cid) if r['lead']['email']==email]
    assert len(matches)==1
    lid=matches[0]
    response=smartlead._request('POST',f'/campaigns/{cid}/leads/{lid}/pause')
    result['paused_leads'].append({'campaign_id':cid,'lead_id':lid,'response':response})
for cid in ids:
    original=smartlead.get_campaign_sequences(cid)
    assert len(original)==4 and all(not s.get('sequence_variants') for s in original)
    payload=[]
    for s in original:
        body=s['email_body'].replace('Just pick our {{nearestClinic}} clinic and a time that suits you.',
                                    'Pick the clinic and time that suit you.')
        body=body.replace(" There's a £4.99 booking fee to hold the slot, that's all.", '')
        body=body.replace('Feel free to share the link and code with colleagues too, each person gets one free session.', sharing)
        marker='<div>{Best regards|Kind regards|Thanks}</div>'
        assert marker in body
        if sharing not in body:
            body=body.replace(marker, '<div>'+sharing+'</div><br>'+marker)
        body=body.replace('<div>'+sharing+'</div>', '<div>'+fee+'</div><br><div>'+sharing+'</div>')
        assert '{{nearestClinic}}' not in body and '£4.99' in body and sharing in body
        payload.append({'id':s['id'],'seq_number':s['seq_number'],'subject':s['subject'],
                        'email_body':body,'seq_delay_details':{'delay_in_days':s['seq_delay_details']['delay_in_days']}})
    smartlead._request('POST',f'/campaigns/{cid}/status',json={'status':'PAUSED'})
    try:
        response=smartlead._request('POST',f'/campaigns/{cid}/sequences',json={'sequences':payload})
        actual=smartlead.get_campaign_sequences(cid)
        assert [(s['id'],s['email_body']) for s in actual]==[(s['id'],s['email_body']) for s in payload]
    finally:
        smartlead._request('POST',f'/campaigns/{cid}/status',json={'status':'START'})
    result['campaigns'].append({'id':cid,'response':response,'verified_steps':len(actual),
                                'status':smartlead.get_campaign(cid)['status']})
print(json.dumps(result,default=str))
