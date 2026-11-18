> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Campaign Status

> Change the status of a campaign (start, pause, stop).

> [!NOTE]
>
> Change the status of a campaign (start, pause, stop) Updates campaign status to START, PAUSE, or STOP

## Path Parameters

**campaign\_id** `number` *required*

The ID of the campaign to update

## Query Parameters

**api\_key** `string` *required*

Your SmartLead API key

## Request Body

**status** `string` *required*

New campaign status

Valid values (from API\_EMAIL\_CAMPAIGN\_STATUS):

* `START` - Start or resume campaign (not "ACTIVE")
* `PAUSED` - Temporarily pause sending
* `STOPPED` - Permanently stop campaign
* `ARCHIVED` - Archive the campaign

Note: Use "START" not "ACTIVE" when activating a campaign

```bash cURL theme={null}
curl -X POST "https://server.smartlead.ai/api/v1/campaigns/123/status?api_key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"status": "START"}'
```

```python Python theme={null}
import requests

API_KEY = "YOUR_API_KEY"
campaign_id = 123

response = requests.post(
    f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/status",
    params={"api_key": API_KEY},
    json={"status": "ACTIVE"}
)

print("Campaign started!" if response.status_code == 200 else "Error")
```

```javascript JavaScript theme={null}
const API_KEY = 'YOUR_API_KEY';
const campaignId = 123;

const response = await fetch(
  `https://server.smartlead.ai/api/v1/campaigns/${campaignId}/status?api_key=${API_KEY}`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: 'ACTIVE' })
  }
);

console.log('Campaign started!');
```

## Response Codes

**200** `Success`

Request successful

**400** `Bad Request`

Invalid request parameters or malformed request body

**401** `Unauthorized`

Invalid or missing API key. Check your authentication.

**404** `Not Found`

The requested resource (campaign, lead, email account, etc.) does not exist or you don't have access to it

**422** `Validation Error`

Request validation failed. Check parameter types, required fields, and value constraints.

**429** `Rate Limit Exceeded`

Too many requests. Please slow down and retry after the rate limit resets.

**500** `Internal Server Error`

Server error occurred. Please try again or contact support if the issue persists.

**503** `Service Unavailable`

API is temporarily unavailable or under maintenance. Please try again later.

```json Success theme={null}
{
  "success": true,
  "message": "Campaign status updated successfully",
  "campaign": {
    "id": 123,
    "status": "ACTIVE"
  }
}
```

```json 401 - Unauthorized theme={null}
{
  "message": "Invalid API Key"
}
```

```json 404 - Not Found theme={null}
{
  "error": "Resource not found"
}
```

```json 422 - Validation Error theme={null}
{
  "error": "Invalid parameters provided"
}
```

## Status Descriptions

| Status | What It Does | Reversible? |
| - | - | - |
| **ACTIVE** | Starts sending emails according to schedule | Yes |
| **PAUSED** | Temporarily stops all sending | Yes |
| **STOPPED** | Permanently stops campaign | No |
| **ARCHIVED** | Hides from active campaigns list | Yes |

> [!WARNING]
>
> **STOPPED** status is permanent and cannot be undone. Use **PAUSED** if you might want to resume later.

## When to Use Each Status

### ACTIVE

* Campaign is fully configured
* All sequences added
* Email accounts connected
* Leads imported
* Ready to send

### PAUSED

* Need to make adjustments
* Waiting for more leads
* Testing sequences
* Temporary hold

### STOPPED

* Campaign completed its goal
* Pivoting strategy
* No longer needed
* Permanently ending

### ARCHIVED

* Campaign is done but keep for records
* Want to hide from active list
* May reference later

## Implementation Details

START status triggers campaign validation and begins sending. STOP is permanent. Use PAUSE for temporary holds.

**Response Format**: object

## Related Endpoints

* [Get Campaign by ID](https://api.smartlead.ai/api-reference/campaigns/get-by-id.md)
* [Update Campaign Settings](https://api.smartlead.ai/api-reference/campaigns/update-settings.md)
* [Delete Campaign](https://api.smartlead.ai/api-reference/campaigns/delete.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.