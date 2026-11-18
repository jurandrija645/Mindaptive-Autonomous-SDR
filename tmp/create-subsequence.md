> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Subsequence Campaign

> Create a child campaign (subsequence) with conditional trigger logic

> [!NOTE]
>
> Create branching campaign logic by defining subsequences that trigger based on lead behavior. Essential for sophisticated nurture workflows.

## Query Parameters

**api\_key** `string` *required*

Your SmartLead API key

## Request Body

**parent\_campaign\_id** `number` *required*

ID of the parent campaign this subsequence belongs to

**name** `string`

Name for the subsequence campaign. Defaults to `"Untitled Subsequence"` if not provided.

**conditionEvents** `array`

Array of trigger conditions that move a lead into this subsequence. Pass `[]` to create a subsequence with no conditions.

**Condition event properties**

**conditionEvents\[].eventType** `string` *required*

The trigger event type. Must be one of:

* `OPEN_AN_EMAIL` — Lead opened an email
* `CLICK_ON_AN_EMAIL_LINK` — Lead clicked a link in an email
* `REPLY_AN_EMAIL` — Lead replied to an email
* `REPLY_MESSAGE_BODY_TEXT` — Lead replied with specific text in the body
* `CATEGORY` — Lead was categorized into a specific category

**conditionEvents\[].categoryId** `number`

Category ID. Required when `eventType` is `CATEGORY`.

**conditionEvents\[].text** `string`

Text to match in the reply body. Used when `eventType` is `REPLY_MESSAGE_BODY_TEXT`.

**conditionEvents\[].eventSubType** `string`

Optional sub-type for the event.

**client\_id** `number`

Client ID (for agency/white-label accounts)

> [!NOTE]
>
> The top-level body keys use `snake_case` (`parent_campaign_id`, `client_id`) while the nested condition keys use `camelCase` (`eventType`, `categoryId`, `eventSubType`). The `conditionEvents` key itself is also `camelCase`.

> [!NOTE]
>
> The API supports 5 event types listed above. Additional event types visible in the UI (such as re-engagement, bounce-based, opens/clicks counters, and LinkedIn events) are not available through this endpoint.

```bash cURL theme={null}
curl -X POST "https://server.smartlead.ai/api/v1/campaigns/create-subsequence?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "parent_campaign_id": 123,
    "name": "Follow-up Sequence",
    "conditionEvents": [
      {"eventType": "CATEGORY", "categoryId": 6},
      {"eventType": "REPLY_MESSAGE_BODY_TEXT", "text": "pricing"}
    ]
  }'
```

```python Python theme={null}
import requests

API_KEY = "YOUR_API_KEY"

response = requests.post(
    "https://server.smartlead.ai/api/v1/campaigns/create-subsequence",
    params={"api_key": API_KEY},
    json={
        "parent_campaign_id": 123,
        "name": "Follow-up Sequence",
        "conditionEvents": [
            {"eventType": "CATEGORY", "categoryId": 6},
            {"eventType": "REPLY_MESSAGE_BODY_TEXT", "text": "pricing"}
        ]
    }
)

result = response.json()
print(f"Subsequence created with ID: {result['id']}")
```

```javascript JavaScript theme={null}
const API_KEY = 'YOUR_API_KEY';

const response = await fetch(
  `https://server.smartlead.ai/api/v1/campaigns/create-subsequence?api_key=${API_KEY}`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      parent_campaign_id: 123,
      name: 'Follow-up Sequence',
      conditionEvents: [
        { eventType: 'CATEGORY', categoryId: 6 },
        { eventType: 'REPLY_MESSAGE_BODY_TEXT', text: 'pricing' }
      ]
    })
  }
);

const result = await response.json();
console.log(`Subsequence created with ID: ${result.id}`);
```

## Response Fields

**ok** `boolean`

`true` on successful creation

**id** `number`

Unique identifier for the newly created subsequence campaign

**name** `string`

Subsequence name (either provided or `"Untitled Subsequence"`)

**parent\_campaign\_id** `number`

ID of the parent campaign

**created\_at** `string`

ISO 8601 timestamp when the subsequence was created

## Response Codes

**200** `Success`

Subsequence campaign created successfully

**400** `Bad Request`

Invalid request body. The endpoint validates body keys strictly — unrecognized keys are rejected.

**401** `Unauthorized`

Invalid or missing API key

**422** `Validation Error`

Request validation failed. Check parameter types and required fields.

**500** `Internal Server Error`

Server error occurred

```json 200 - Success theme={null}
{
  "ok": true,
  "id": 456,
  "name": "Follow-up Sequence",
  "parent_campaign_id": 123,
  "created_at": "2026-08-19T10:29:20.609Z"
}
```

```json 400 - Bad Request theme={null}
{
  "statusCode": 400,
  "error": "Bad Request",
  "message": "\"condition_events\" is not allowed",
  "validation": {
    "source": "body",
    "keys": ["condition_events"]
  }
}
```

```json 401 - Unauthorized theme={null}
{
  "message": "Invalid API Key"
}
```

## Related Endpoints

* [Create Campaign](https://api.smartlead.ai/api-reference/campaigns/create.md)
* [Push to Subsequence](https://api.smartlead.ai/api-reference/inbox/push-to-subsequence.md)
* [Update Subsequence Conditions](https://api.smartlead.ai/api-reference/campaigns/update-subsequence-conditions)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.