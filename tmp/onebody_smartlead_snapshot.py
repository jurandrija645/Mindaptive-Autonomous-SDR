import json
from app import smartlead
result = {'campaigns': smartlead.list_campaigns(), 'categories': smartlead.fetch_categories(),
          'angie_lead': smartlead.get_lead(4816229373),
          'angie_thread': smartlead.get_message_history(4235286,4816229373)}
print(json.dumps(result,default=str))
