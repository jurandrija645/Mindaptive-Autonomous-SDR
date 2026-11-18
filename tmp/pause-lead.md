> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Pause Campaign Lead

> Temporarily pause a specific lead in a campaign

> [!NOTE]
>
> Pause outreach to a specific lead without removing them from the campaign. Can be resumed later.

## Path Parameters

**campaign\_id** `number` *required*

Campaign ID

**lead\_id** `number` *required*

Lead ID to pause

## Query Parameters

**api\_key** `string` *required*

Your SmartLead API key

```bash cURL theme={null}
curl -X POST "https://server.smartlead.ai/api/v1/campaigns/123/leads/789/pause?api_key=YOUR_KEY"
```

```python Python theme={null}
import requests

API_KEY = "YOUR_API_KEY"

def pause_lead(campaign_id, lead_id):
    response = requests.post(
        f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads/{lead_id}/pause",
        params={"api_key": API_KEY}
    )
    
    if response.status_code == 200:
        print(f"✅ Lead {lead_id} paused")
    
    return response.json()

pause_lead(123, 789)
```

```javascript JavaScript theme={null}
const API_KEY = 'YOUR_API_KEY';

async function pauseLead(campaignId, leadId) {
  const response = await fetch(
    `https://server.smartlead.ai/api/v1/campaigns/${campaignId}/leads/${leadId}/pause?api_key=${API_KEY}`,
    { method: 'POST' }
  );
  
  return response.json();
}

await pauseLead(123, 789);
```

## Response Example

```json 200 theme={null}
{
  "success": true,
  "message": "Lead paused successfully"
}
```

## Related Endpoints

* [Resume Lead](https://api.smartlead.ai/api-reference/campaigns/resume-lead.md)
* [Get Campaign Leads](https://api.smartlead.ai/api-reference/campaigns/get-leads.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.