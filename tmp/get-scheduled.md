> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Scheduled Emails

> Retrieve emails queued for future sending with schedule time sorting

> [!NOTE]
>
> View and manage your scheduled email queue. Essential for reviewing upcoming sends and optimizing send times.

## Overview

Retrieves scheduled emails queued to be sent at a future time. Unique sorting by scheduled time helps manage your outreach pipeline.

**Scheduled Sorting (Unique to this endpoint):**

* `SCHEDULED_TIME_ASC`: Earliest scheduled sends first (next to send)
* `SCHEDULED_TIME_DESC`: Latest scheduled sends first

## Query Parameters

**api\_key** `string` *required*

Your SmartLead API key

**fetch\_message\_history** `boolean` (default: false)

Include full thread history

## Request Body

**offset** `number` (default: 0)

Pagination offset

**limit** `number` (default: 20)

Records per page (1-20)

**filters** `object`

Standard inbox filters - campaignId max 5, emailAccountId max 10

**sortBy** `string`

**Unique Options**: `SCHEDULED_TIME_ASC` or `SCHEDULED_TIME_DESC`

```bash cURL theme={null}
curl -X POST "https://server.smartlead.ai/api/v1/master-inbox/scheduled?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sortBy": "SCHEDULED_TIME_ASC", "limit": 20}'
```

```python Python theme={null}
import requests

API_KEY = "YOUR_API_KEY"

# Get next scheduled emails
response = requests.post(
    "https://server.smartlead.ai/api/v1/master-inbox/scheduled",
    params={"api_key": API_KEY},
    json={"sortBy": "SCHEDULED_TIME_ASC", "limit": 20}
)

scheduled = response.json()
print(f"Next {len(scheduled.get('messages', []))} scheduled emails")
```

```javascript JavaScript theme={null}
const response = await fetch(
  `https://server.smartlead.ai/api/v1/master-inbox/scheduled?api_key=${API_KEY}`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({sortBy: 'SCHEDULED_TIME_ASC', limit: 20})
  }
);
```

## Response Example

```json 200 theme={null}
{
  "messages": [{
    "campaign_lead_map_id": "2433664091",
    "scheduled_time": "2025-01-21T09:00:00Z",
    "email_status": "Scheduled"
  }],
  "total_count": 1
}
```

## Related Endpoints

* [Get Sent Emails](https://api.smartlead.ai/api-reference/inbox/get-sent.md)
* [Get Inbox Messages](https://api.smartlead.ai/api-reference/inbox/get-messages.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.