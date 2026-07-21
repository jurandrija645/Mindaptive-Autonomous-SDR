<!-- Mirrored from https://api.smartlead.ai/api-reference/inbox/reply — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Reply to Email

> Send a reply to a lead in an email thread

<Note>
  Send replies to leads directly from the inbox. Maintains thread continuity and tracks all responses.
</Note>

## Overview

Sends a reply email to a lead, maintaining the email thread. Can send immediately or schedule for later.

**Key Features:**

* Thread continuity maintained
* Optional scheduling
* CC/BCC support
* Attachments support
* Signature inclusion
* Reply tracking in conversation history

## Path Parameters

<ParamField path="campaign_id" type="integer" required>
  Campaign ID
</ParamField>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

## Request Body

<ParamField body="email_stats_id" type="string" required>
  Email stats ID for the message to reply to
</ParamField>

<ParamField body="email_body" type="string" required>
  Reply email body content
</ParamField>

<ParamField body="to_email" type="string">
  Recipient email (optional, defaults to lead email)
</ParamField>

<ParamField body="to_first_name" type="string">
  Recipient first name (optional)
</ParamField>

<ParamField body="to_last_name" type="string">
  Recipient last name (optional)
</ParamField>

<ParamField body="scheduled_time" type="string">
  Schedule send time (ISO 8601 format)
</ParamField>

<ParamField body="reply_message_id" type="string">
  Message ID being replied to
</ParamField>

<ParamField body="reply_email_body" type="string">
  Original email body being replied to
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
  Scheduling condition (optional)
</ParamField>

<ParamField body="add_signature" type="boolean">
  Include email signature
</ParamField>

<ParamField body="seq_type" type="string">
  Sequence type (optional)
</ParamField>

<ParamField body="attachments" type="array">
  File attachments array

  <Expandable title="attachment properties">
    <ParamField body="file_name" type="string">
      File name
    </ParamField>

    <ParamField body="file_url" type="string" required>
      File URL (required)
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
  curl -X POST "https://server.smartlead.ai/api/v1/campaigns/12345/reply-email-thread?api_key=YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "email_stats_id": "abc-123",
      "email_body": "Thanks for your interest! Let me know if you have any questions.",
      "add_signature": true
    }'
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"
  CAMPAIGN_ID = 12345

  def send_reply(campaign_id, email_stats_id, body, schedule_time=None, add_signature=True):
      payload = {
          "email_stats_id": email_stats_id,
          "email_body": body,
          "add_signature": add_signature
      }

      if schedule_time:
          payload["scheduled_time"] = schedule_time

      response = requests.post(
          f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/reply-email-thread",
          params={"api_key": API_KEY},
          json=payload
      )

      return response.json()

  # Send immediate reply
  send_reply(CAMPAIGN_ID, "abc-123", "Thanks for your interest!")

  # Schedule reply for tomorrow 9 AM
  from datetime import datetime, timedelta
  tomorrow_9am = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0).isoformat() + 'Z'
  send_reply(CAMPAIGN_ID, "abc-124", "Following up on our previous conversation", schedule_time=tomorrow_9am)
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';
  const CAMPAIGN_ID = 12345;

  async function sendReply(campaignId, emailStatsId, body, options = {}) {
    const payload = {
      email_stats_id: emailStatsId,
      email_body: body,
      add_signature: options.add_signature !== false,
      ...options
    };

    const response = await fetch(
      `https://server.smartlead.ai/api/v1/campaigns/${campaignId}/reply-email-thread?api_key=${API_KEY}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }
    );

    return response.json();
  }

  // Send reply
  await sendReply(CAMPAIGN_ID, 'abc-123', 'Happy to help!');
  ```
</RequestExample>

## Related Endpoints

* [Forward Email](/api-reference/inbox/forward)
* [Get Inbox Messages](/api-reference/inbox/get-messages)
