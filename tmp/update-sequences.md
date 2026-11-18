> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Campaign Sequences

> Create or update email sequences for multi-step campaigns

> [!NOTE]
>
> Creates new sequences (id: null) or updates existing ones. Each sequence needs: seq\_number, email\_body, and delay in days. Cannot modify while campaign is ACTIVE - pause first.

## Overview

Create new email sequences or update existing ones for a campaign. Sequences define your multi-step email outreach flow.

**Key Features**:

* Create new sequences by setting `id: null`
* Update existing sequences by including their `id`
* Configure delays between emails (0-365 days)
* Add A/B testing variants with `seq_variants`
* Subject line optional for follow-ups (uses "Re:" on previous)

> [!WARNING]
>
> Cannot modify sequences while campaign is **ACTIVE**. Pause campaign first, make changes, then resume.

## Path Parameters

**campaign\_id** `number` *required*

The campaign ID

## Query Parameters

**api\_key** `string` *required*

Your SmartLead API key

## Request Body

**sequences** `array` *required*

Array of sequence objects

**Sequence Object**

**id** `number`

Sequence ID (null for new, number for update)

**seq\_number** `number` *required*

Sequence position (1, 2, 3, etc.)

**subject** `string`

Email subject line (can include {{variables}})

**email\_body** `string` *required*

Email content (supports HTML and {{variables}})

**seq\_delay\_details** `object` *required*

Delay configuration

**properties**

**delay\_in\_days** `number` *required*

Days to wait before sending

```bash cURL theme={null}
curl -X POST "https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/sequences?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "sequences": [
      {
        "id": null,
        "seq_number": 1,
        "subject": "Hello {{first_name}}",
        "email_body": "<p>Hi {{first_name}},</p><p>I wanted to reach out...</p>",
        "seq_delay_details": {
          "delay_in_days": 0
        }
      },
      {
        "id": null,
        "seq_number": 2,
        "subject": "",
        "email_body": "<p>Just following up on my previous email...</p>",
        "seq_delay_details": {
          "delay_in_days": 3
        }
      }
    ]
  }'
```

```python Python theme={null}
import requests

API_KEY = "YOUR_API_KEY"

response = requests.post(
    "https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/sequences",
    params={"api_key": API_KEY},
    json={
        "sequences": [
            {
                "id": None,
                "seq_number": 1,
                "subject": "Hello {{first_name}}",
                "email_body": "<p>Hi {{first_name}},</p><p>I wanted to reach out...</p>",
                "seq_delay_details": {"delay_in_days": 0}
            },
            {
                "id": None,
                "seq_number": 2,
                "subject": "",
                "email_body": "<p>Just following up on my previous email...</p>",
                "seq_delay_details": {"delay_in_days": 3}
            }
        ]
    }
)

result = response.json()
print(result)
```

```javascript JavaScript theme={null}
const API_KEY = 'YOUR_API_KEY';

const response = await fetch(
  `https://server.smartlead.ai/api/v1/campaigns/${campaignId}/sequences?api_key=${API_KEY}`,
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sequences: [
        {
          id: null,
          seq_number: 1,
          subject: 'Hello {{first_name}}',
          email_body: '<p>Hi {{first_name}},</p><p>I wanted to reach out...</p>',
          seq_delay_details: { delay_in_days: 0 }
        },
        {
          id: null,
          seq_number: 2,
          subject: '',
          email_body: '<p>Just following up on my previous email...</p>',
          seq_delay_details: { delay_in_days: 3 }
        }
      ]
    })
  }
);

const result = await response.json();
console.log(result);
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

```json 200 - Success theme={null}
{
  "ok": true,
  "data": [
    {
      "id": 1001,
      "seq_number": 1,
      "subject": "Hello {{first_name}}",
      "email_body": "<p>Hi {{first_name}},</p><p>I wanted to reach out...</p>"
    },
    {
      "id": 1002,
      "seq_number": 2,
      "subject": "Re: Hello {{first_name}}",
      "email_body": "<p>Just following up on my previous email...</p>"
    }
  ]
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

## Personalization Variables

Use these in subject and body:

* `{{first_name}}`, `{{last_name}}`
* `{{company_name}}`, `{{website}}`
* `{{location}}`, `{{linkedin_profile}}`
* Any custom field: `{{job_title}}`, `{{industry}}`, etc.

## Sequence Best Practices

> [!TIP]
>
> Keep first email under 125 words for best response rates

> [!TIP]
>
> Wait 3-5 days between follow-ups - don't be too aggressive

> [!TIP]
>
> Each email should provide new value, not just "checking in"

## Implementation Details

Use id:null to create new sequences. Include existing id to update. Cannot modify sequences while campaign is active.

**Response Format**: object

## Related Endpoints

* [Get Campaign Sequences](https://api.smartlead.ai/api-reference/campaigns/get-sequences.md)
* [Sequences Concept Guide](https://api.smartlead.ai/core/sequences.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.