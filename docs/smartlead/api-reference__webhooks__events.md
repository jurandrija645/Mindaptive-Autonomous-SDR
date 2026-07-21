<!-- Mirrored from https://api.smartlead.ai/api-reference/webhooks/events — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Webhook Events Reference

> Complete reference of all webhook event types and their payload structures

<Note>
  This is a reference page, not an API endpoint. Use these event types when creating webhooks via the [Create Webhook](/api-reference/webhooks/create) endpoint.
</Note>

## Available Events

### EMAIL\_SENT

Triggered when an email is successfully sent to a lead.

**When**: Immediately after email delivery confirmation\
**Use For**: Tracking send volume, updating CRM status, logging

**Payload Example**:

```json theme={null}
{
  "event_type": "EMAIL_SENT",
  "from_email": "sender@yourcompany.com",
  "to_email": "lead@example.com",
  "to_name": "John Doe",
  "time_sent": "2025-01-15T09:00:00Z",
  "campaign_name": "Q1 Outreach",
  "campaign_id": 123,
  "sequence_number": 1,
  "custom_subject": "Quick question about Acme Corp",
  "custom_email_message": "<html>Email body content...</html>",
  "message_id": "abc123def456"
}
```

***

### FIRST\_EMAIL\_SENT

Triggered only when the first email in a sequence is sent to a lead. Use this instead of `EMAIL_SENT` if you only want to track initial outreach.

**When**: When sequence step 1 is sent\
**Use For**: Tracking new outreach starts, CRM contact creation

**Payload Example**: Same structure as `EMAIL_SENT`, but only fires for `sequence_number: 1`.

***

### EMAIL\_OPEN

Triggered when a lead opens your email (tracking pixel loads).

**When**: When recipient's email client loads the tracking pixel\
**Use For**: Lead scoring, engagement tracking, trigger follow-up actions

**Payload Example**:

```json theme={null}
{
  "event_type": "EMAIL_OPEN",
  "from_email": "sender@yourcompany.com",
  "to_email": "lead@example.com",
  "to_name": "John Doe",
  "time_opened": "2025-01-15T10:30:00Z",
  "campaign_name": "Q1 Outreach",
  "campaign_id": 123,
  "sequence_number": 1
}
```

***

### EMAIL\_LINK\_CLICK

Triggered when a lead clicks a tracked link in your email.

**When**: Immediately when link is clicked\
**Use For**: High intent signals, lead scoring, conversion tracking

**Payload Example**:

```json theme={null}
{
  "event_type": "EMAIL_LINK_CLICK",
  "from_email": "sender@yourcompany.com",
  "to_email": "lead@example.com",
  "to_name": "John Doe",
  "time_clicked": "2025-01-15T10:45:00Z",
  "link_clicked": ["https://example.com/demo"],
  "campaign_name": "Q1 Outreach",
  "campaign_id": 123,
  "sequence_number": 1
}
```

***

### EMAIL\_REPLY

Triggered when a lead replies to your email.

**When**: When reply is received and processed\
**Use For**: Hot lead alerts, CRM updates, sales notifications

**Payload Example**:

```json theme={null}
{
  "event_type": "EMAIL_REPLY",
  "from_email": "sender@yourcompany.com",
  "subject": "Re: Quick question about Acme Corp",
  "to_email": "lead@example.com",
  "to_name": "John Doe",
  "time_replied": "2025-01-15T11:00:00Z",
  "reply_body": "<html>Thanks for reaching out. I'm interested...</html>",
  "preview_text": "Thanks for reaching out. I'm interested...",
  "campaign_name": "Q1 Outreach",
  "campaign_id": 123,
  "client_id": 456,
  "sequence_number": 1
}
```

***

### EMAIL\_BOUNCE

Triggered when an email bounces (delivery fails).

**When**: When email server returns bounce notification\
**Use For**: List cleaning, deliverability monitoring, account health

***

### LEAD\_UNSUBSCRIBED

Triggered when a lead clicks the unsubscribe link.

**When**: Immediately when unsubscribe link is clicked\
**Use For**: Compliance, list management, CRM suppression

**Payload Example**:

```json theme={null}
{
  "event_type": "LEAD_UNSUBSCRIBED",
  "lead_email": "lead@example.com",
  "lead_name": "John Doe",
  "campaign_name": "Q1 Outreach",
  "campaign_id": 123,
  "unsubscribed_client_id_map": {}
}
```

***

### LEAD\_CATEGORY\_UPDATED

Triggered when a lead's category changes (manual or auto-categorization).

**When**: When lead category is updated\
**Use For**: CRM sync, sales routing, workflow automation

**Payload Example**:

```json theme={null}
{
  "event_type": "LEAD_CATEGORY_UPDATED",
  "lead_id": 789,
  "lead_email": "lead@example.com",
  "lead_name": "John",
  "lead_data": {
    "email": "lead@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "phone_number": "+1234567890",
    "company_name": "Acme Corp",
    "website": "https://acmecorp.com",
    "location": "San Francisco, CA",
    "custom_fields": {},
    "linkedin_profile": "https://linkedin.com/in/johndoe",
    "company_url": "https://acmecorp.com",
    "category": {
      "name": "Interested",
      "sentiment_type": "positive"
    }
  },
  "category": "Interested",
  "lead_category_id": 5,
  "campaign_name": "Q1 Outreach",
  "campaign_id": 123,
  "from": "sender@yourcompany.com",
  "to": "lead@example.com",
  "history": [
    {
      "type": "SENT",
      "time": "2025-01-15T09:00:00Z",
      "email_body": "<html>...</html>",
      "subject": "Quick question"
    },
    {
      "type": "REPLY",
      "time": "2025-01-15T11:00:00Z",
      "email_body": "<html>Thanks for reaching out...</html>"
    }
  ],
  "lastReply": {
    "type": "REPLY",
    "time": "2025-01-15T11:00:00Z",
    "email_body": "<html>Thanks for reaching out...</html>"
  }
}
```

<Note>
  The `LEAD_CATEGORY_UPDATED` event includes the full conversation history between the sending account and the lead, including all sent emails, replies, and threaded replies.
</Note>

***

### CAMPAIGN\_STATUS\_CHANGED

Triggered when a campaign's status changes (e.g., started, paused, completed).

**When**: When campaign status is updated\
**Use For**: Workflow automation, status dashboards, notifications

***

### UNTRACKED\_REPLIES

Triggered when an untracked reply is received — a reply that doesn't match a known lead in the campaign.

**When**: When an untracked reply is detected\
**Use For**: Catch-all inbox monitoring, forwarded replies

***

### MANUAL\_STEP\_REACHED

Triggered when a lead reaches a manual step in the email sequence (e.g., a step that requires human action like a phone call or LinkedIn message).

**When**: When the sequence advances a lead to a manual step\
**Use For**: Task creation, sales team notifications, CRM task assignment

***

### EMAIL\_ACCOUNT\_DISCONNECTED

Triggered when a sending email account is disconnected (SMTP/IMAP failure).

**When**: When an email account connection fails\
**Use For**: Account health monitoring, alerting

<Note>
  This event uses a separate per-user webhook configuration (`notify_on_disconnect.webhookUrl` in user settings), not the standard campaign webhook system.
</Note>

***

### LINKEDIN\_DISCONNECTED

Triggered when a LinkedIn cookie becomes invalid.

**When**: When LinkedIn cookie validation fails\
**Use For**: Account health monitoring, alerting

<Note>
  This event uses a separate per-user webhook configuration, not the standard campaign webhook system.
</Note>

***

## Webhook Configuration

When creating a webhook, specify which events you want to receive using the `event_type_map` object:

```json Webhook Config Example theme={null}
{
  "webhook_url": "https://your-server.com/webhook",
  "association_type": "campaign",
  "email_campaign_id": 123,
  "event_type_map": {
    "EMAIL_SENT": true,
    "EMAIL_OPEN": true,
    "EMAIL_LINK_CLICK": true,
    "EMAIL_REPLY": true,
    "EMAIL_BOUNCE": true,
    "LEAD_UNSUBSCRIBED": true,
    "LEAD_CATEGORY_UPDATED": true,
    "CAMPAIGN_STATUS_CHANGED": false,
    "UNTRACKED_REPLIES": false,
    "MANUAL_STEP_REACHED": false
  }
}
```

For `LEAD_CATEGORY_UPDATED`, you can also specify which categories to listen to via the `category_id_map`:

```json Category Filter Example theme={null}
{
  "event_type_map": {
    "LEAD_CATEGORY_UPDATED": true
  },
  "category_id_map": {
    "5": true,
    "6": true
  }
}
```

## Handling Webhooks

### Example Handler (Python/Flask)

```python theme={null}
from flask import Flask, request

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    data = request.json
    event = data['event_type']

    if event == 'EMAIL_REPLY':
        # High priority - lead replied!
        send_slack_notification(
            f"New reply from {data['to_email']}"
        )
        update_crm(data['to_email'], status='Engaged')

    elif event == 'EMAIL_OPEN':
        # Medium priority - lead is interested
        increment_lead_score(data['to_email'])

    elif event == 'EMAIL_BOUNCE':
        # Clean up - remove from lists
        remove_from_all_campaigns(data.get('to_email'))

    elif event == 'LEAD_CATEGORY_UPDATED':
        # Sync category to CRM
        update_crm_category(data['lead_email'], data['category'])

    return {'status': 'received'}, 200
```

### Example Handler (JavaScript/Express)

```javascript theme={null}
app.post('/webhook', express.json(), (req, res) => {
  const event = req.body;

  // Acknowledge receipt immediately
  res.status(200).json({ status: 'received' });

  // Process asynchronously
  switch(event.event_type) {
    case 'EMAIL_REPLY':
      console.log(`Reply from ${event.to_email}: ${event.preview_text}`);
      // Send to CRM, trigger workflows, etc.
      break;

    case 'EMAIL_OPEN':
      console.log(`${event.to_email} opened email`);
      // Update lead score
      break;

    case 'LEAD_CATEGORY_UPDATED':
      console.log(`${event.lead_email} categorized as ${event.category}`);
      // Sync to CRM
      break;
  }
});
```

## Best Practices

<Tip>
  **Return 200 Quickly**: Process webhooks asynchronously to avoid timeouts. SmartLead will retry if your server doesn't respond with 200 in time.
</Tip>

<Tip>
  **Implement Idempotency**: Use event fields like `campaign_id` + `to_email` + `event_type` + timestamp to handle duplicate deliveries.
</Tip>

<Warning>
  **Webhook Level Priority**: If a User-level webhook exists, it will override Client and Campaign-level webhooks for the same event type.
</Warning>

## Related Endpoints

* [Create Webhook](/api-reference/webhooks/create)
* [Get Webhook](/api-reference/webhooks/get)
* [Update Webhook](/api-reference/webhooks/update)
* [Delete Webhook](/api-reference/webhooks/delete)
