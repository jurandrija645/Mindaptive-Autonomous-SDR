<!-- Mirrored from https://api.smartlead.ai/core/webhooks — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Webhooks

> Set up real-time notifications for campaign events

## What are Webhooks?

Webhooks allow you to receive real-time notifications when events occur in your SmartLead campaigns. Instead of polling the API, SmartLead will send HTTP POST requests to your server when events happen.

## Use Cases

<CardGroup cols={2}>
  <Card title="CRM Integration" icon="database">
    Update your CRM when leads reply or book meetings
  </Card>

  <Card title="Lead Scoring" icon="chart-line">
    Score leads based on engagement (opens, clicks)
  </Card>

  <Card title="Notifications" icon="bell">
    Get Slack/Email alerts for important replies
  </Card>

  <Card title="Analytics" icon="chart-bar">
    Send data to your analytics platform
  </Card>
</CardGroup>

## Available Events

| Event                | Description           | When Triggered                |
| -------------------- | --------------------- | ----------------------------- |
| `EMAIL_SENT`         | Email sent to lead    | After successful delivery     |
| `EMAIL_OPENED`       | Lead opened email     | When tracking pixel loads     |
| `EMAIL_CLICKED`      | Lead clicked link     | When tracked link is clicked  |
| `EMAIL_REPLIED`      | Lead replied to email | When reply is received        |
| `EMAIL_BOUNCED`      | Email bounced         | When email fails to deliver   |
| `EMAIL_UNSUBSCRIBED` | Lead unsubscribed     | When unsubscribe link clicked |

## Webhook Payload Format

All webhook events follow this structure:

```json theme={null}
{
  "event": "EMAIL_REPLIED",
  "timestamp": "2024-01-15T10:30:00Z",
  "campaign_id": 123,
  "campaign_name": "Cold Outreach Q1",
  "lead_id": 789,
  "email_account_id": 456,
  "lead": {
    "email": "lead@example.com",
    "first_name": "Jane",
    "last_name": "Doe",
    "company_name": "Acme Corp",
    "custom_fields": {
      "job_title": "CEO"
    }
  },
  "sequence_number": 1,
  "email": {
    "subject": "Quick question",
    "message_id": "abc123@smartlead.ai"
  },
  "reply": {
    "subject": "Re: Quick question",
    "body": "Thanks for reaching out...",
    "received_at": "2024-01-15T10:30:00Z"
  }
}
```

## Setting Up Webhooks

<Steps>
  <Step title="Create Webhook Endpoint">
    Set up an HTTPS endpoint on your server that accepts POST requests

    ```python Python theme={null}
    from flask import Flask, request

    app = Flask(__name__)

    @app.route('/webhook', methods=['POST'])
    def handle_webhook():
        data = request.json
        event = data['event']
        
        if event == 'EMAIL_REPLIED':
            # Handle reply
            lead_email = data['lead']['email']
            reply_body = data['reply']['body']
            # Your logic here
            
        return {'status': 'success'}, 200
    ```
  </Step>

  <Step title="Register Webhook in SmartLead">
    Use the API to register your webhook URL

    ```bash cURL theme={null}
    curl -X POST "https://server.smartlead.ai/api/v1/webhook/create?api_key=YOUR_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "CRM Integration",
        "webhook_url": "https://your-server.com/webhook",
        "email_campaign_id": 123,
        "association_type": 3,
        "event_type_map": {
          "EMAIL_REPLIED": true,
          "EMAIL_OPENED": true
        }
      }'
    ```
  </Step>

  <Step title="Test Your Webhook">
    SmartLead will send test events when you save the webhook
  </Step>

  <Step title="Go Live">
    Activate your campaign and start receiving events
  </Step>
</Steps>

## Webhook Association Types

Webhooks can be associated with:

* **User Level** (association\_type: 1): Receive events from all campaigns
* **Client Level** (association\_type: 2): Events for specific client's campaigns
* **Campaign Level** (association\_type: 3): Events from a single campaign

## Event Examples

### EMAIL\_SENT

```json theme={null}
{
  "event": "EMAIL_SENT",
  "timestamp": "2024-01-15T09:00:00Z",
  "campaign_id": 123,
  "lead_id": 789,
  "email_account_id": 456,
  "sequence_number": 1,
  "lead": {
    "email": "lead@example.com",
    "first_name": "Jane"
  }
}
```

### EMAIL\_OPENED

```json theme={null}
{
  "event": "EMAIL_OPENED",
  "timestamp": "2024-01-15T10:30:00Z",
  "campaign_id": 123,
  "lead_id": 789,
  "sequence_number": 1,
  "opened_count": 3,
  "first_opened_at": "2024-01-15T10:30:00Z",
  "last_opened_at": "2024-01-15T14:20:00Z"
}
```

### EMAIL\_REPLIED

```json theme={null}
{
  "event": "EMAIL_REPLIED",
  "timestamp": "2024-01-15T11:00:00Z",
  "campaign_id": 123,
  "lead_id": 789,
  "email_account_id": 456,
  "sequence_number": 1,
  "reply": {
    "subject": "Re: Quick question",
    "body": "Thanks for reaching out. I'm interested...",
    "received_at": "2024-01-15T11:00:00Z",
    "message_id": "reply-abc123"
  },
  "lead": {
    "email": "lead@example.com",
    "first_name": "Jane",
    "last_name": "Doe"
  }
}
```

### EMAIL\_CLICKED

```json theme={null}
{
  "event": "EMAIL_CLICKED",
  "timestamp": "2024-01-15T10:45:00Z",
  "campaign_id": 123,
  "lead_id": 789,
  "sequence_number": 1,
  "link": {
    "url": "https://example.com/demo",
    "clicked_at": "2024-01-15T10:45:00Z"
  }
}
```

## Webhook Security

### Verify Webhook Origin

Always verify webhooks come from SmartLead:

```python Python theme={null}
import hmac
import hashlib

def verify_webhook(payload, signature, secret):
    """Verify webhook signature"""
    expected = hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature)
```

<Warning>
  Always use HTTPS for your webhook endpoint to ensure data is encrypted in transit.
</Warning>

### Best Practices

1. **Return 200 Quickly**: Process webhooks asynchronously
2. **Implement Retry Logic**: Handle temporary failures
3. **Validate Payload**: Check all required fields exist
4. **Log Everything**: Keep webhook logs for debugging
5. **Use Idempotency**: Handle duplicate events gracefully

## Example Implementations

### Node.js/Express

```javascript theme={null}
const express = require('express');
const app = express();

app.post('/webhook', express.json(), (req, res) => {
  const { event, lead, reply } = req.body;
  
  // Quickly acknowledge receipt
  res.status(200).json({ status: 'received' });
  
  // Process asynchronously
  process.nextTick(() => {
    switch(event) {
      case 'EMAIL_REPLIED':
        console.log(`Reply from ${lead.email}: ${reply.body}`);
        // Update your CRM, send notifications, etc.
        break;
      case 'EMAIL_OPENED':
        console.log(`${lead.email} opened email`);
        break;
    }
  });
});

app.listen(3000);
```

### Python/Flask

```python theme={null}
from flask import Flask, request
import logging

app = Flask(__name__)
logger = logging.getLogger(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
    # Log the event
    logger.info(f"Received {data['event']} event")
    
    # Quick response
    response = {'status': 'received'}
    
    # Process asynchronously (use Celery, etc.)
    process_webhook_async(data)
    
    return response, 200

def process_webhook_async(data):
    event = data['event']
    
    if event == 'EMAIL_REPLIED':
        # Update CRM
        update_crm_contact(
            email=data['lead']['email'],
            status='Replied'
        )
        
        # Send Slack notification
        send_slack_notification(
            f"New reply from {data['lead']['first_name']}!"
        )
```

## Webhook Management

### Create Webhook

```bash cURL theme={null}
curl -X POST "https://server.smartlead.ai/api/v1/webhook/create?api_key=YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Webhook",
    "webhook_url": "https://your-server.com/webhook",
    "email_campaign_id": 123,
    "association_type": 3,
    "event_type_map": {
      "EMAIL_SENT": true,
      "EMAIL_OPENED": true,
      "EMAIL_CLICKED": true,
      "EMAIL_REPLIED": true,
      "EMAIL_BOUNCED": true
    }
  }'
```

### Get Webhook Details

```bash cURL theme={null}
curl -X GET "https://server.smartlead.ai/api/v1/webhook/123?api_key=YOUR_API_KEY"
```

### Delete Webhook

```bash cURL theme={null}
curl -X DELETE "https://server.smartlead.ai/api/v1/webhook/delete/123?api_key=YOUR_API_KEY"
```

## Retry Logic

SmartLead will retry failed webhook deliveries:

* **1st retry**: After 1 minute
* **2nd retry**: After 5 minutes
* **3rd retry**: After 15 minutes
* **4th retry**: After 1 hour
* **5th retry**: After 6 hours

After 5 failed attempts, the webhook will be disabled.

## Debugging Webhooks

### Common Issues

<AccordionGroup>
  <Accordion title="Webhook Not Receiving Events">
    **Check**:

    * URL is publicly accessible
    * HTTPS is properly configured
    * Firewall allows SmartLead IPs
    * Server is returning 200 status code
  </Accordion>

  <Accordion title="Events Arriving Out of Order">
    **Solution**: Use the `timestamp` field to order events, not arrival time
  </Accordion>

  <Accordion title="Duplicate Events">
    **Solution**: Use idempotency keys (lead\_id + event + timestamp)
  </Accordion>

  <Accordion title="Webhook Disabled">
    **Reason**: Too many failures (5+ consecutive errors)
    **Solution**: Fix your endpoint and re-enable webhook
  </Accordion>
</AccordionGroup>

### Test Your Webhook

Use a webhook testing service:

* [webhook.site](https://webhook.site)
* [requestbin.com](https://requestbin.com)
* Postman's webhook collection feature

## Integration Examples

### Update HubSpot

```python theme={null}
def handle_reply_webhook(data):
    """Update HubSpot when lead replies"""
    if data['event'] == 'EMAIL_REPLIED':
        hubspot_contact_id = find_contact_by_email(
            data['lead']['email']
        )
        
        if hubspot_contact_id:
            update_hubspot_contact(
                contact_id=hubspot_contact_id,
                properties={
                    'lead_status': 'Engaged',
                    'last_activity': data['timestamp'],
                    'reply_text': data['reply']['body']
                }
            )
```

### Send Slack Notification

```python theme={null}
import requests

def send_slack_notification(data):
    """Send Slack alert for replies"""
    if data['event'] == 'EMAIL_REPLIED':
        slack_webhook_url = 'YOUR_SLACK_WEBHOOK_URL'
        
        message = {
            'text': f"🎉 New reply from {data['lead']['first_name']}!",
            'attachments': [{
                'color': 'good',
                'fields': [
                    {
                        'title': 'Lead',
                        'value': data['lead']['email'],
                        'short': True
                    },
                    {
                        'title': 'Campaign',
                        'value': data['campaign_name'],
                        'short': True
                    },
                    {
                        'title': 'Reply',
                        'value': data['reply']['body'][:100] + '...',
                        'short': False
                    }
                ]
            }]
        }
        
        requests.post(slack_webhook_url, json=message)
```

## Rate Limiting

Webhook deliveries are not subject to API rate limits. However, ensure your server can handle:

* **Burst traffic**: Many events arriving simultaneously
* **Sustained load**: Continuous event stream during active campaigns

<Tip>
  Use a queue system (Redis, RabbitMQ) to handle webhook events asynchronously.
</Tip>

## Related Endpoints

* [Create Webhook](/api-reference/webhooks/create)
* [Get Webhook](/api-reference/webhooks/get)
* [Delete Webhook](/api-reference/webhooks/delete)
* [Webhook Events Reference](/api-reference/webhooks/events)
