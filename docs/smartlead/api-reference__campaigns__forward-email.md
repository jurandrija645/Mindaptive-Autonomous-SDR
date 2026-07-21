<!-- Mirrored from https://api.smartlead.ai/api-reference/campaigns/forward-email — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Forward Campaign Email

> Forward a campaign email to other recipients

<Note>
  Forward campaign emails to team members or external recipients. Maintains thread context.
</Note>

## Path Parameters

<ParamField path="campaign_id" type="number" required>
  Campaign ID
</ParamField>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

## Request Body

Based on email campaigns forward schema - likely similar to reply-email-thread with forward-specific fields.

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST "https://server.smartlead.ai/api/v1/campaigns/123/forward-email?api_key=YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{}'
  ```

  ```python Python theme={null}
  import requests

  # Implementation details need verification from controller
  response = requests.post(
      f"https://server.smartlead.ai/api/v1/campaigns/123/forward-email",
      params={"api_key": "YOUR_API_KEY"},
      json={}
  )
  ```
</RequestExample>

## Response Example

<ResponseExample>
  ```json 200 theme={null}
  {
    "success": true
  }
  ```
</ResponseExample>

<Warning>
  Schema needs verification from controller implementation - check `/server/controller/v1/campaigns/forwardEmailByReplyId.js`
</Warning>
