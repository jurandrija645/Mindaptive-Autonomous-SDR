<!-- Mirrored from https://api.smartlead.ai/api-reference/campaigns/reply-email-thread — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Reply to Campaign Lead

> Send a reply email to a lead within campaign context

<Note>
  Reply to leads directly from campaign view. Maintains conversation thread and tracks reply in campaign statistics.
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

<ParamField body="email_stats_id" type="string" required>
  Email statistics ID of the message to reply to
</ParamField>

<ParamField body="email_body" type="string" required>
  Reply email body content
</ParamField>

<ParamField body="to_email" type="string">
  Recipient email (optional, defaults to lead email)
</ParamField>

<ParamField body="to_first_name" type="string">
  Recipient first name
</ParamField>

<ParamField body="to_last_name" type="string">
  Recipient last name
</ParamField>

<ParamField body="scheduled_time" type="string">
  Schedule reply for later (ISO 8601)
</ParamField>

<ParamField body="reply_message_id" type="string">
  Message ID being replied to
</ParamField>

<ParamField body="reply_email_body" type="string">
  Original email body (for context)
</ParamField>

<ParamField body="reply_email_time" type="string">
  Original email timestamp
</ParamField>

<ParamField body="cc" type="string">
  CC recipients (comma-separated)
</ParamField>

<ParamField body="bcc" type="string">
  BCC recipients (comma-separated)
</ParamField>

<ParamField body="schedule_condition" type="string">
  Scheduling condition
</ParamField>

<ParamField body="add_signature" type="boolean">
  Include email signature
</ParamField>

<ParamField body="seq_type" type="string">
  Sequence type
</ParamField>

<ParamField body="attachments" type="array">
  File attachments

  <Expandable title="Attachment Object">
    <ParamField body="file_name" type="string">
      File name
    </ParamField>

    <ParamField body="file_url" type="string" required>
      File URL
    </ParamField>

    <ParamField body="file_type" type="string">
      MIME type
    </ParamField>

    <ParamField body="file_size" type="number">
      File size in bytes
    </ParamField>
  </Expandable>
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST "https://server.smartlead.ai/api/v1/campaigns/123/reply-email-thread?api_key=YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "email_stats_id": "abc-123",
      "email_body": "Thanks for your interest! Let me know if you have any questions.",
      "add_signature": true
    }'
  ```

  ```python Python theme={null}
  import requests

  def reply_to_lead(campaign_id, email_stats_id, body, add_signature=True):
      payload = {
          "email_stats_id": email_stats_id,
          "email_body": body,
          "add_signature": add_signature
      }
      
      response = requests.post(
          f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/reply-email-thread",
          params={"api_key": "YOUR_API_KEY"},
          json=payload
      )
      
      if response.status_code == 200:
          print("✅ Reply sent")
      
      return response.json()

  reply_to_lead(123, "abc-123", "Happy to help! Let me know your questions.")
  ```
</RequestExample>

## Response Example

<ResponseExample>
  ```json 200 theme={null}
  {
    "success": true,
    "message": "Reply sent successfully"
  }
  ```
</ResponseExample>
