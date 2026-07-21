<!-- Mirrored from https://api.smartlead.ai/api-reference/webhooks/get — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Webhook

> Get configuration details for a specific webhook by ID

## Path Parameters

<ParamField path="webhook_id" type="number" required>
  The webhook id
</ParamField>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

## Request Body

<Note>No request body required</Note>

<RequestExample>
  ```bash cURL theme={null}
  curl "https://server.smartlead.ai/api/v1/webhook/{webhook_id}?api_key=YOUR_KEY"
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"

  response = requests.get(
      "https://server.smartlead.ai/api/v1/webhook/{webhook_id}",
      params={"api_key": API_KEY}
  )

  result = response.json()
  print(result)
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  const response = await fetch(
    `https://server.smartlead.ai/api/v1/webhook/${webhook_id}?api_key=${API_KEY}`
  );

  const result = await response.json();
  console.log(result);
  ```
</RequestExample>

## Response Codes

<ResponseField name="200" type="Success">
  Request successful
</ResponseField>

<ResponseField name="400" type="Bad Request">
  Invalid request parameters or malformed request body
</ResponseField>

<ResponseField name="401" type="Unauthorized">
  Invalid or missing API key. Check your authentication.
</ResponseField>

<ResponseField name="404" type="Not Found">
  The requested resource (campaign, lead, email account, etc.) does not exist or you don't have access to it
</ResponseField>

<ResponseField name="422" type="Validation Error">
  Request validation failed. Check parameter types, required fields, and value constraints.
</ResponseField>

<ResponseField name="429" type="Rate Limit Exceeded">
  Too many requests. Please slow down and retry after the rate limit resets.
</ResponseField>

<ResponseField name="500" type="Internal Server Error">
  Server error occurred. Please try again or contact support if the issue persists.
</ResponseField>

<ResponseField name="503" type="Service Unavailable">
  API is temporarily unavailable or under maintenance. Please try again later.
</ResponseField>

<ResponseExample>
  ```json 200 - Success theme={null}
  {
    "ok": true,
    "data": {
      "id": 456,
      "email_campaign_id": 123,
      "name": "Campaign Analytics Webhook",
      "webhook_url": "https://your-server.com/webhooks/smartlead",
      "event_type_map": {
        "EMAIL_SENT": true,
        "EMAIL_OPEN": true,
        "EMAIL_LINK_CLICK": true,
        "EMAIL_REPLY": true
      },
      "category_id_map": {},
      "created_at": "2026-03-15T10:30:00Z",
      "updated_at": "2026-03-20T14:22:00Z"
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
</ResponseExample>

## Related Endpoints

* [Create Webhook](/api-reference/webhooks/create)
* [Update Webhook](/api-reference/webhooks/update)
* [Delete Webhook](/api-reference/webhooks/delete)
* [Webhook Events](/api-reference/webhooks/events)
