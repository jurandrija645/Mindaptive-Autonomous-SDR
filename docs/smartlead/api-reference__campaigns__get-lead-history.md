<!-- Mirrored from https://api.smartlead.ai/api-reference/campaigns/get-lead-history — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Lead Message History

> Retrieve complete email conversation history for a specific lead

<Note>
  View full email thread history with a lead. Essential for understanding conversation context and lead engagement.
</Note>

## Path Parameters

<ParamField path="campaign_id" type="number" required>
  Campaign ID
</ParamField>

<ParamField path="lead_id" type="number" required>
  Lead ID
</ParamField>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

<ParamField query="event_time_gt" type="string">
  Filter messages after this timestamp (ISO 8601)
</ParamField>

<ParamField query="show_plain_text_response" type="boolean">
  Include plain text version of emails
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl "https://server.smartlead.ai/api/v1/campaigns/123/leads/789/message-history?api_key=YOUR_KEY"
  ```

  ```python Python theme={null}
  import requests

  response = requests.get(
      f"https://server.smartlead.ai/api/v1/campaigns/123/leads/789/message-history",
      params={"api_key": "YOUR_API_KEY", "show_plain_text_response": True}
  )

  history = response.json()
  for msg in history['messages']:
      direction = "➡️ " if msg['direction'] == 'outbound' else "⬅️ "
      print(f"{direction}{msg['subject']} - {msg['sent_at']}")
  ```
</RequestExample>

## Response Example

<ResponseExample>
  ```json 200 theme={null}
  {
    "messages": [
      {
        "id": "msg_1",
        "subject": "Partnership Opportunity",
        "direction": "outbound",
        "sent_at": "2025-01-15T10:00:00Z",
        "opened_at": "2025-01-15T10:30:00Z"
      },
      {
        "id": "msg_2",
        "subject": "Re: Partnership Opportunity",
        "direction": "inbound",
        "received_at": "2025-01-20T14:00:00Z"
      }
    ]
  }
  ```
</ResponseExample>
