<!-- Mirrored from https://api.smartlead.ai/api-reference/inbox/get-messages — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Inbox Replies

> Retrieve all lead replies across all campaigns in your unified inbox

<Note>
  Your central hub for all lead responses across campaigns. Essential for managing conversations, tracking engagement, and ensuring no reply goes unnoticed.
</Note>

## Overview

Retrieves all replies from leads across all campaigns in your unified inbox. This is the primary endpoint for managing all incoming responses from your outreach efforts.

**Key Features**:

* Unified view of all replies across campaigns
* Optional full message history retrieval
* Comprehensive filtering by campaign, account, team, tags, clients
* Lead category filtering
* Date range and engagement status filtering
* Flexible sorting options

**Use Cases**:

* **Response management**: Central inbox for all campaign replies
* **Team collaboration**: Filter by assigned team members
* **Performance tracking**: Monitor reply rates and patterns
* **Lead qualification**: Filter by category and engagement
* **Client reporting**: Segment replies by client
* **Follow-up workflows**: Identify leads needing attention

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

<ParamField query="fetch_message_history" type="boolean" default="false">
  Include full email thread history.

  * `true`: Returns complete conversation thread (slower, more data)
  * `false`: Returns only latest message (faster, recommended for list views)

  **Performance tip**: Use `false` for list views, `true` only when viewing individual conversations.
</ParamField>

## Request Body

<ParamField body="offset" type="number" default="0">
  Number of records to skip for pagination. Must be non-negative.
</ParamField>

<ParamField body="limit" type="number" default="20">
  Number of records to return per page. Must be between 1 and 20.
</ParamField>

<ParamField body="filters" type="object">
  Advanced filtering options

  <Expandable title="filters properties">
    <ParamField body="filters.search" type="string">
      Search term to filter replies by lead email, name, or message content.
      Maximum 30 characters.
    </ParamField>

    <ParamField body="filters.leadCategories" type="object">
      Filter by lead category assignment

      <Expandable title="leadCategories properties">
        <ParamField body="leadCategories.unassigned" type="boolean">
          Include leads without category assignment
        </ParamField>

        <ParamField body="leadCategories.isAssigned" type="boolean">
          Include leads with category assignment
        </ParamField>

        <ParamField body="leadCategories.categoryIdsNotIn" type="array">
          Exclude specific category IDs (max 10 items)
        </ParamField>

        <ParamField body="leadCategories.categoryIdsIn" type="array">
          Include only specific category IDs (max 10 items)
        </ParamField>
      </Expandable>
    </ParamField>

    <ParamField body="filters.emailStatus" type="string or array">
      Filter by email engagement status. Can be a single status or array.

      Valid values: `Opened`, `Clicked`, `Replied`, `Unsubscribed`, `Bounced`, `Accepted`, `Not Replied`

      Examples:

      * Single: `"Replied"`
      * Multiple: `["Replied", "Clicked"]`
    </ParamField>

    <ParamField body="filters.campaignId" type="number or array">
      Filter by campaign ID(s).

      * Single: `12345`
      * Multiple: `[12345, 12346, 12347]` (max 5 campaigns for this endpoint)
    </ParamField>

    <ParamField body="filters.emailAccountId" type="number or array">
      Filter by email account ID(s).

      * Single: `789`
      * Multiple: `[789, 790, 791, ...]` (max 20 accounts)
    </ParamField>

    <ParamField body="filters.campaignTeamMemberId" type="number or array">
      Filter by assigned team member(s).

      * Single: `456`
      * Multiple: `[456, 457, 458]` (max 10 members)
    </ParamField>

    <ParamField body="filters.campaignTagId" type="number or array">
      Filter by campaign tag(s).

      * Single: `5`
      * Multiple: `[5, 6, 7]` (max 10 tags)
    </ParamField>

    <ParamField body="filters.campaignClientId" type="number or array">
      Filter by client ID(s).

      * Single: `100`
      * Multiple: `[100, 101, 102]` (max 10 clients)
    </ParamField>

    <ParamField body="filters.replyTimeBetween" type="array">
      Filter by reply date range. Array of 2 ISO 8601 datetime strings.

      Format: `["start_datetime", "end_datetime"]`

      Example: `["2025-01-01T00:00:00Z", "2025-01-31T23:59:59Z"]`
    </ParamField>
  </Expandable>
</ParamField>

<ParamField body="sortBy" type="string" default="REPLY_TIME_DESC">
  Sort order for results

  * `REPLY_TIME_DESC`: Most recent replies first (default)
  * `SENT_TIME_DESC`: Most recently sent emails first
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST "https://server.smartlead.ai/api/v1/master-inbox/inbox-replies?api_key=YOUR_KEY&fetch_message_history=false" \
    -H "Content-Type: application/json" \
    -d '{
      "offset": 0,
      "limit": 20,
      "filters": {
        "emailStatus": "Replied",
        "campaignId": [12345, 12346],
        "leadCategories": {
          "categoryIdsIn": [1]
        }
      },
      "sortBy": "REPLY_TIME_DESC"
    }'
  ```

  ```python Python theme={null}
  import requests
  from datetime import datetime, timedelta

  API_KEY = "YOUR_API_KEY"

  # Example 1: Get today's replies from interested leads
  today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat() + 'Z'
  now = datetime.now().isoformat() + 'Z'

  payload = {
      "offset": 0,
      "limit": 20,
      "filters": {
          "emailStatus": "Replied",
          "leadCategories": {
              "categoryIdsIn": [1]  # Interested category
          },
          "replyTimeBetween": [today_start, now]
      },
      "sortBy": "REPLY_TIME_DESC"
  }

  response = requests.post(
      "https://server.smartlead.ai/api/v1/master-inbox/inbox-replies",
      params={
          "api_key": API_KEY,
          "fetch_message_history": False  # Fast list view
      },
      json=payload
  )

  result = response.json()
  print(f"Today's interested replies: {result.get('total_count', 0)}")

  # Process each reply
  for message in result.get('messages', []):
      lead = message['lead']
      last_msg = message['last_message']
      print(f"\n{lead['email']}: {last_msg['subject']}")
      print(f"Replied at: {last_msg['received_at']}")
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  // Example 2: Get unread replies with full message history
  async function getUnreadReplies() {
    const payload = {
      offset: 0,
      limit: 20,
      filters: {
        emailStatus: 'Replied',
        // Add more filters as needed
      },
      sortBy: 'REPLY_TIME_DESC'
    };

    const response = await fetch(
      `https://server.smartlead.ai/api/v1/master-inbox/inbox-replies?api_key=${API_KEY}&fetch_message_history=true`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }
    );

    const result = await response.json();
    
    // Process replies with full conversation context
    for (const message of result.messages || []) {
      console.log(`\n${message.lead.email}`);
      
      if (message.message_history) {
        console.log(`  Thread length: ${message.message_history.length} messages`);
        // Display full conversation
        message.message_history.forEach((msg, idx) => {
          console.log(`  ${idx + 1}. [${msg.direction}] ${msg.subject}`);
        });
      }
    }
    
    return result;
  }

  getUnreadReplies();
  ```

  ```python Advanced: Multi-Campaign Comparison theme={null}
  # Example 3: Compare reply rates across campaigns
  campaigns_to_compare = [12345, 12346, 12347]

  results_by_campaign = {}

  for campaign_id in campaigns_to_compare:
      payload = {
          "filters": {
              "campaignId": campaign_id,
              "emailStatus": "Replied"
          },
          "limit": 20
      }
      
      response = requests.post(
          "https://server.smartlead.ai/api/v1/master-inbox/inbox-replies",
          params={"api_key": API_KEY, "fetch_message_history": False},
          json=payload
      )
      
      data = response.json()
      results_by_campaign[campaign_id] = {
          'total_replies': data.get('total_count', 0),
          'messages': data.get('messages', [])
      }

  # Analyze results
  for campaign_id, data in results_by_campaign.items():
      print(f"Campaign {campaign_id}: {data['total_replies']} replies")
  ```
</RequestExample>

## Response Codes

<ResponseField name="200" type="Success">
  Request successful - inbox replies retrieved
</ResponseField>

<ResponseField name="401" type="Unauthorized">
  Invalid or missing API key
</ResponseField>

<ResponseField name="422" type="Validation Error">
  Request validation failed. Common issues:

  * `limit` > 20
  * More than 5 campaign IDs
  * More than 20 email account IDs
  * More than 10 items in other array filters
  * Invalid date format
</ResponseField>

<ResponseField name="500" type="Internal Server Error">
  Server error occurred
</ResponseField>

<ResponseExample>
  ```json 200 - Success (without message history) theme={null}
  {
    "messages": [
      {
        "id": "msg_xyz789",
        "campaign_lead_map_id": "2433664091",
        "lead": {
          "email": "sarah@startup.io",
          "first_name": "Sarah",
          "last_name": "Johnson",
          "company": "Startup Inc",
          "phone": "+1-555-0100"
        },
        "campaign": {
          "id": 12345,
          "name": "Q1 2025 SaaS Outreach"
        },
        "email_account": {
          "id": 789,
          "email": "sales@yourcompany.com",
          "name": "Sales Team"
        },
        "last_message": {
          "id": "email_abc123",
          "subject": "Re: Partnership Opportunity",
          "body": "Thanks for reaching out! I'm interested in learning more about your solution...",
          "received_at": "2025-01-20T14:30:00Z",
          "sent_from": "sarah@startup.io",
          "sent_to": "sales@yourcompany.com"
        },
        "email_status": "Replied",
        "category": {
          "id": 1,
          "name": "Interested"
        },
        "assigned_to": {
          "id": 456,
          "name": "Jane Smith",
          "email": "jane@yourcompany.com"
        },
        "stats": {
          "total_sent": 3,
          "total_opened": 2,
          "total_clicked": 1,
          "total_replied": 1,
          "last_activity": "2025-01-20T14:30:00Z"
        },
        "is_read": false,
        "is_important": false,
        "is_archived": false,
        "tags": ["hot-lead", "enterprise"]
      }
    ],
    "total_count": 1,
    "offset": 0,
    "limit": 20
  }
  ```

  ```json 200 - Success (with message history) theme={null}
  {
    "messages": [
      {
        "id": "msg_xyz789",
        "campaign_lead_map_id": "2433664091",
        "lead": {...},
        "last_message": {...},
        "message_history": [
          {
            "id": "msg_1",
            "subject": "Partnership Opportunity",
            "body": "Hi Sarah, I noticed your company...",
            "direction": "outbound",
            "sent_at": "2025-01-15T10:00:00Z",
            "opened_at": "2025-01-15T10:30:00Z"
          },
          {
            "id": "msg_2",
            "subject": "Re: Partnership Opportunity",
            "body": "Thanks for reaching out! I'm interested...",
            "direction": "inbound",
            "received_at": "2025-01-20T14:30:00Z"
          }
        ],
        "email_status": "Replied",
        "...": "..."
      }
    ],
    "total_count": 1
  }
  ```

  ```json 401 - Unauthorized theme={null}
  {
    "message": "Invalid API Key"
  }
  ```

  ```json 422 - Validation Error theme={null}
  {
    "error": "campaignId array cannot exceed 5 items",
    "field": "filters.campaignId",
    "provided_count": 10,
    "max_allowed": 5
  }
  ```
</ResponseExample>

## Common Workflows

### Daily Inbox Check

```python theme={null}
def check_daily_inbox():
    """Get all unread replies from today"""
    today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat() + 'Z'
    now = datetime.now().isoformat() + 'Z'
    
    payload = {
        "filters": {
            "emailStatus": "Replied",
            "replyTimeBetween": [today_start, now]
        },
        "sortBy": "REPLY_TIME_DESC",
        "limit": 20
    }
    
    response = get_inbox_replies(payload, fetch_history=False)
    
    unread = [msg for msg in response['messages'] if not msg['is_read']]
    print(f"{len(unread)} unread replies today")
    
    return unread
```

### Priority Lead Follow-up

```python theme={null}
def get_hot_leads():
    """Get interested leads that replied recently"""
    three_days_ago = (datetime.now() - timedelta(days=3)).isoformat() + 'Z'
    
    payload = {
        "filters": {
            "leadCategories": {
                "categoryIdsIn": [1, 2]  # Interested, Meeting Request
            },
            "replyTimeBetween": [three_days_ago, datetime.now().isoformat() + 'Z']
        },
        "sortBy": "REPLY_TIME_DESC"
    }
    
    return get_inbox_replies(payload)
```

### Team Workload Distribution

```python theme={null}
def get_team_workload(team_member_ids):
    """Check reply counts for each team member"""
    workload = {}
    
    for member_id in team_member_ids:
        payload = {
            "filters": {
                "campaignTeamMemberId": member_id,
                "emailStatus": "Replied"
            },
            "limit": 1  # Just need count
        }
        
        response = get_inbox_replies(payload)
        workload[member_id] = response.get('total_count', 0)
    
    return workload
```

### Campaign Performance Monitor

```python theme={null}
def monitor_campaign_replies(campaign_ids, start_date, end_date):
    """Track reply metrics across campaigns"""
    payload = {
        "filters": {
            "campaignId": campaign_ids[:5],  # Max 5
            "replyTimeBetween": [start_date, end_date]
        },
        "limit": 20
    }
    
    response = get_inbox_replies(payload)
    messages = response.get('messages', [])
    
    # Calculate metrics
    metrics = {
        'total_replies': len(messages),
        'interested': len([m for m in messages 
                          if m.get('category', {}).get('id') == 1]),
        'by_campaign': {}
    }
    
    for msg in messages:
        campaign_id = msg['campaign']['id']
        if campaign_id not in metrics['by_campaign']:
            metrics['by_campaign'][campaign_id] = 0
        metrics['by_campaign'][campaign_id] += 1
    
    return metrics
```

## Message History vs List View

### When to Use `fetch_message_history=false` (Recommended)

* ✅ **List views**: Displaying inbox overview
* ✅ **Counting replies**: Just need totals
* ✅ **Quick filtering**: Finding specific leads
* ✅ **Dashboard displays**: Overview metrics
* ✅ **Mobile apps**: Faster loading
* ✅ **Pagination**: Browsing multiple pages

**Performance**: \~10x faster, \~90% less data transferred

### When to Use `fetch_message_history=true`

* ✅ **Conversation view**: Displaying full thread
* ✅ **Reply context**: Need full conversation history
* ✅ **AI analysis**: Processing full threads
* ✅ **Detailed reporting**: Complete interaction data
* ✅ **CRM sync**: Syncing full conversation history

**Trade-off**: Slower response, much more data, but complete context

```python theme={null}
# Fast list view
list_view_response = get_inbox_replies(
    payload,
    fetch_history=False  # Fast
)

# Then fetch details only when user clicks
def view_conversation(message_id):
    detailed_response = get_inbox_replies(
        {"filters": {"messageId": message_id}},
        fetch_history=True  # Full context
    )
    return detailed_response
```

## Filtering Best Practices

### 1. Use Appropriate Array Limits

```python theme={null}
# ✅ GOOD: Within limits
filters = {
    "campaignId": [12345, 12346, 12347],  # Max 5 OK
    "emailAccountId": [1, 2, 3, ..., 20],  # Max 20 OK
    "campaignTeamMemberId": [10, 11, 12]  # Max 10 OK
}

# ❌ BAD: Exceeds limits
filters = {
    "campaignId": [1, 2, 3, 4, 5, 6, 7],  # ERROR: Max 5
}
```

### 2. Combine Category Filters

```python theme={null}
# Get engaged leads, exclude uninterested
filters = {
    "leadCategories": {
        "isAssigned": True,  # Has a category
        "categoryIdsNotIn": [3, 4]  # Exclude "Not Interested", "Do Not Contact"
    }
}
```

### 3. Smart Date Ranges

```python theme={null}
# Rolling windows for consistent monitoring
def get_recent_replies(days=7):
    end = datetime.now()
    start = end - timedelta(days=days)
    
    return {
        "replyTimeBetween": [
            start.isoformat() + 'Z',
            end.isoformat() + 'Z'
        ]
    }
```

### 4. Progressive Filtering

```python theme={null}
# Start broad, narrow down based on results
def find_replies_progressive():
    # Step 1: Get all replies
    payload1 = {"filters": {"emailStatus": "Replied"}}
    result1 = get_inbox_replies(payload1)
    
    if result1['total_count'] > 100:
        # Step 2: Add time filter
        payload2 = {
            "filters": {
                "emailStatus": "Replied",
                "replyTimeBetween": get_recent_replies(7)
            }
        }
        result2 = get_inbox_replies(payload2)
        
        if result2['total_count'] > 50:
            # Step 3: Add category filter
            payload3 = payload2.copy()
            payload3["filters"]["leadCategories"] = {"categoryIdsIn": [1]}
            return get_inbox_replies(payload3)
        
        return result2
    
    return result1
```

## Performance Optimization

1. **Disable message history for lists**: 10x faster
2. **Use pagination properly**: Limit=20 is optimal
3. **Filter by campaign/account**: Reduces query scope
4. **Cache frequently accessed data**: Store client-side
5. **Batch similar requests**: Group by filter criteria
6. **Use appropriate sort orders**: Match your use case

## Error Handling

```python theme={null}
def safe_get_inbox_replies(payload, fetch_history=False):
    """Get inbox replies with error handling"""
    try:
        response = requests.post(
            "https://server.smartlead.ai/api/v1/master-inbox/inbox-replies",
            params={
                "api_key": API_KEY,
                "fetch_message_history": fetch_history
            },
            json=payload,
            timeout=30  # 30 second timeout
        )
        
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 422:
            print(f"Validation error: {e.response.json()}")
            # Adjust payload and retry
        elif e.response.status_code == 429:
            print("Rate limited - waiting 60 seconds")
            time.sleep(60)
            return safe_get_inbox_replies(payload, fetch_history)
        else:
            print(f"HTTP error: {e}")
            
    except requests.exceptions.Timeout:
        print("Request timed out - try with smaller limit or disable message history")
        
    except Exception as e:
        print(f"Unexpected error: {e}")
    
    return None
```

## Related Endpoints

* [Get Sent Emails](/api-reference/inbox/get-sent) - All sent emails
* [Get Unread Replies](/api-reference/inbox/get-unread) - Only unread replies
* [Get Assigned to Me](/api-reference/inbox/get-assigned) - My assigned replies
* [Get Important](/api-reference/inbox/get-important) - Flagged replies
* [Mark Read](/api-reference/inbox/mark-read) - Update read status
* [Update Category](/api-reference/inbox/update-category) - Categorize leads
* [Reply to Message](/api-reference/inbox/reply) - Send reply
