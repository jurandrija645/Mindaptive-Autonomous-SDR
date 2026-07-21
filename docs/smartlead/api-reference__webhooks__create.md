<!-- Mirrored from https://api.smartlead.ai/api-reference/webhooks/create — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Webhook

> Create webhook to receive real-time notifications for campaign events like opens, clicks, and replies

<Note>
  Webhooks allow you to receive real-time HTTP POST notifications when specific events occur in your campaigns. Configure webhooks at user, client, or campaign level.
</Note>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

## Request Body

<ParamField body="webhook_url" type="string" required>
  The URL where webhook notifications will be sent via HTTP POST
</ParamField>

<ParamField body="association_type" type="string" required>
  Scope of the webhook. Valid values:

  * `user` - User level (all campaigns)
  * `client` - Client level (all campaigns for a client)
  * `campaign` - Campaign level (single campaign)
</ParamField>

<ParamField body="email_campaign_id" type="number">
  Campaign ID (required when association\_type=3)
</ParamField>

<ParamField body="name" type="string">
  Webhook name for identification
</ParamField>

<ParamField body="event_type_map" type="object">
  Map of events to subscribe to. Set each event key to `true` to enable. Available events:

  * `EMAIL_SENT` - Email sent
  * `FIRST_EMAIL_SENT` - First email of sequence sent
  * `EMAIL_OPEN` - Email opened
  * `EMAIL_LINK_CLICK` - Link clicked
  * `EMAIL_REPLY` - Lead replied
  * `EMAIL_BOUNCE` - Email bounced
  * `LEAD_UNSUBSCRIBED` - Lead unsubscribed
  * `LEAD_CATEGORY_UPDATED` - Lead category changed
  * `CAMPAIGN_STATUS_CHANGED` - Campaign status changed
  * `UNTRACKED_REPLIES` - Untracked reply received
  * `MANUAL_STEP_REACHED` - Manual step reached in sequence
</ParamField>

<ParamField body="category_id_map" type="object">
  Map of category IDs to filter events by lead category
</ParamField>

<ParamField body="client_id" type="number">
  Client ID (required when association\_type=2)
</ParamField>

<ParamField body="event_type" type="string">
  Specific event type to subscribe to
</ParamField>

<ParamField body="category_id" type="number">
  Specific lead category ID to filter events by
</ParamField>

<ParamField body="webhook_type" type="string">
  Webhook type identifier
</ParamField>

<ParamField body="force_create" type="boolean" default="false">
  Force creation even if a similar webhook exists
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST "https://server.smartlead.ai/api/v1/webhook/create?api_key=YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Reply Notifications",
      "webhook_url": "https://your-domain.com/webhook",
      "email_campaign_id": 123,
      "association_type": "campaign",
      "event_type_map": {
        "EMAIL_REPLY": true,
        "EMAIL_OPEN": true
      }
    }'
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"

  payload = {
      "name": "Reply Notifications",
      "webhook_url": "https://your-domain.com/webhook",
      "email_campaign_id": 123,
      "association_type": "campaign",
      "event_type_map": {
          "EMAIL_REPLY": True,
          "EMAIL_OPEN": True
      }
  }

  response = requests.post(
      "https://server.smartlead.ai/api/v1/webhook/create",
      params={"api_key": API_KEY},
      json=payload
  )

  result = response.json()
  print(f"Webhook created with ID: {result['id']}")
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  const payload = {
    name: 'Reply Notifications',
    webhook_url: 'https://your-domain.com/webhook',
    email_campaign_id: 123,
    association_type: 'campaign',
    event_type_map: {
      EMAIL_REPLY: true,
      EMAIL_OPEN: true
    }
  };

  const response = await fetch(
    `https://server.smartlead.ai/api/v1/webhook/create?api_key=${API_KEY}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }
  );

  const result = await response.json();
  console.log(`Webhook created with ID: ${result.id}`);
  ```
</RequestExample>

## Webhook Payload

When an event occurs, SmartLead sends a POST request to your `webhook_url`. The payload structure varies by event type. Here's an example for `EMAIL_REPLY`:

```json theme={null}
{
  "event_type": "EMAIL_REPLY",
  "from_email": "sender@yourcompany.com",
  "subject": "Re: Quick question about Acme Corp",
  "to_email": "lead@example.com",
  "to_name": "John Doe",
  "time_replied": "2025-01-15T11:00:00Z",
  "reply_body": "<html>Thanks for reaching out...</html>",
  "preview_text": "Thanks for reaching out...",
  "campaign_name": "Q1 Outreach",
  "campaign_id": 123,
  "client_id": 456,
  "sequence_number": 1
}
```

See [Webhook Events](/api-reference/webhooks/events) for all event payloads.

## Association Types

<AccordionGroup>
  <Accordion title="User Level (user)">
    Receives events from all campaigns owned by the user. Use when you want centralized notifications. If a User-level webhook exists, it takes priority over Client and Campaign-level webhooks.
  </Accordion>

  <Accordion title="Client Level (client)">
    Receives events from all campaigns for a specific client. Useful for agency/white-label setups. Requires `client_id` in the request body.
  </Accordion>

  <Accordion title="Campaign Level (campaign)">
    Receives events only from a specific campaign. Most common use case for per-campaign tracking. Requires `email_campaign_id` in the request body.
  </Accordion>
</AccordionGroup>

## Response Codes

<ResponseField name="200" type="Success">
  Webhook created successfully
</ResponseField>

<ResponseField name="401" type="Unauthorized">
  Invalid or missing API key
</ResponseField>

<ResponseField name="422" type="Validation Error">
  Missing required fields or invalid association\_type
</ResponseField>

<ResponseField name="500" type="Internal Server Error">
  Server error occurred
</ResponseField>

<ResponseExample>
  ```json 200 - Success theme={null}
  {
    "ok": true,
    "id": 456,
    "webhook_url": "https://your-domain.com/webhook"
  }
  ```

  ```json 401 - Unauthorized theme={null}
  {
    "message": "Invalid API Key"
  }
  ```

  ```json 422 - Validation Error theme={null}
  {
    "error": "webhook_url is required"
  }
  ```
</ResponseExample>

## Related Endpoints

* [Get Webhook](/api-reference/webhooks/get)
* [Update Webhook](/api-reference/webhooks/update)
* [Delete Webhook](/api-reference/webhooks/delete)
* [Webhook Events](/api-reference/webhooks/events)
