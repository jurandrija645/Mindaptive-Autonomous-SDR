<!-- Mirrored from https://api.smartlead.ai/api-reference/campaigns/get-leads — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Campaign Leads

> Retrieve all leads in a campaign with comprehensive filtering and pagination

<Note>
  Fetch all leads in a campaign with advanced filtering by status, category, engagement, and date ranges. Essential for lead management, reporting, and analysis.
</Note>

## Overview

Retrieves all leads associated with a campaign with comprehensive filtering options similar to Master Inbox endpoints.

**Key Features:**

* Pagination support (offset/limit, max 100 per request)
* Filter by lead status (STARTED, INPROGRESS, COMPLETED, PAUSED, STOPPED)
* Filter by email engagement (opened, clicked, replied, bounced, etc.)
* Filter by lead category
* Date range filtering (created\_at, last\_sent\_time, event\_time)

## Path Parameters

<ParamField path="campaign_id" type="number" required>
  Campaign ID
</ParamField>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

<ParamField query="offset" type="number" default="0">
  Pagination offset (minimum 0)
</ParamField>

<ParamField query="limit" type="number" default="100">
  Records per page (minimum 1, maximum 100)
</ParamField>

<ParamField query="created_at_gt" type="string">
  Filter leads created after this date (ISO 8601 format)
</ParamField>

<ParamField query="last_sent_time_gt" type="string">
  Filter leads with last email sent after this date (ISO 8601 format)
</ParamField>

<ParamField query="event_time_gt" type="string">
  Filter by last event time (ISO 8601 format)
</ParamField>

<ParamField query="status" type="string">
  Lead status filter

  Valid values:

  * `STARTED` - Lead added, sequence not started
  * `INPROGRESS` - Currently in sequence
  * `COMPLETED` - Sequence completed
  * `PAUSED` - Lead paused
  * `STOPPED` - Lead stopped
</ParamField>

<ParamField query="lead_category_id" type="number">
  Filter by specific category ID
</ParamField>

<ParamField query="emailStatus" type="string">
  Filter by email engagement status

  Valid values:

  * `is_opened` - Email was opened
  * `is_clicked` - Link was clicked
  * `is_bounced` - Email bounced
  * `is_replied` - Lead replied
  * `is_unsubscribed` - Lead unsubscribed
  * `is_spam` - Marked as spam
  * `is_accepted` - Email accepted by server
  * `not_replied` - Opened but didn't reply
  * `is_sender_bounced` - Sender bounce
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  # Get replied leads
  curl "https://server.smartlead.ai/api/v1/campaigns/123/leads?api_key=YOUR_KEY&emailStatus=is_replied&limit=100"
  ```

  ```python Python theme={null}
  import requests
  from datetime import datetime, timedelta

  API_KEY = "YOUR_API_KEY"
  campaign_id = 123

  # Example 1: Get all replied leads
  params = {
      "api_key": API_KEY,
      "emailStatus": "is_replied",
      "limit": 100,
      "offset": 0
  }

  response = requests.get(
      f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads",
      params=params
  )

  leads = response.json()
  print(f"Replied leads: {leads['total']}")

  # Example 2: Get leads added in last 7 days
  seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()

  params = {
      "api_key": API_KEY,
      "created_at_gt": seven_days_ago,
      "limit": 100
  }

  new_leads = requests.get(
      f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads",
      params=params
  ).json()

  print(f"New leads (7 days): {new_leads['total']}")

  # Example 3: Get in-progress leads with high engagement
  params = {
      "api_key": API_KEY,
      "status": "INPROGRESS",
      "emailStatus": "is_clicked",
      "limit": 100
  }

  engaged_leads = requests.get(
      f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads",
      params=params
  ).json()

  # Example 4: Paginate through all leads
  def get_all_leads(campaign_id):
      all_leads = []
      offset = 0
      limit = 100
      
      while True:
          response = requests.get(
              f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads",
              params={"api_key": API_KEY, "offset": offset, "limit": limit}
          )
          
          data = response.json()
          leads = data.get('leads', [])
          
          if not leads:
              break
              
          all_leads.extend(leads)
          offset += limit
          
          if offset >= data.get('total', 0):
              break
      
      return all_leads
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';
  const campaignId = 123;

  // Get replied leads
  async function getRepliedLeads(campaignId) {
    const response = await fetch(
      `https://server.smartlead.ai/api/v1/campaigns/${campaignId}/leads?api_key=${API_KEY}&emailStatus=is_replied&limit=100`
    );
    
    const data = await response.json();
    console.log(`Replied leads: ${data.total}`);
    return data.leads;
  }

  // Get leads by category
  async function getLeadsByCategory(campaignId, categoryId) {
    const response = await fetch(
      `https://server.smartlead.ai/api/v1/campaigns/${campaignId}/leads?api_key=${API_KEY}&lead_category_id=${categoryId}&limit=100`
    );
    
    return response.json();
  }

  await getRepliedLeads(123);
  ```
</RequestExample>

## Response Example

<ResponseExample>
  ```json 200 - Success theme={null}
  {
    "total": 150,
    "leads": [
      {
        "id": 789,
        "email": "john@company.com",
        "first_name": "John",
        "last_name": "Doe",
        "company_name": "ACME Corp",
        "status": "INPROGRESS",
        "category_id": 1,
        "category_name": "Interested",
        "created_at": "2025-01-15T10:00:00Z",
        "last_sent_time": "2025-01-20T09:00:00Z",
        "email_stats": {
          "is_opened": true,
          "is_clicked": true,
          "is_replied": true,
          "is_bounced": false
        },
        "custom_fields": {
          "job_title": "CEO",
          "industry": "SaaS"
        }
      }
    ],
    "offset": 0,
    "limit": 100
  }
  ```
</ResponseExample>

## Common Workflows

### Export Interested Leads

```python theme={null}
# Get all interested leads
interested = get_leads(
    campaign_id=123,
    filters={"lead_category_id": 1}
)

# Export to CSV
import csv
with open('interested_leads.csv', 'w') as f:
    writer = csv.DictWriter(f, fieldnames=['email', 'name', 'company'])
    for lead in interested['leads']:
        writer.writerow({
            'email': lead['email'],
            'name': f"{lead['first_name']} {lead['last_name']}",
            'company': lead.get('company_name', '')
        })
```

## Related Endpoints

* [Add Leads to Campaign](/api-reference/campaigns/add-leads)
* [Get Lead by ID](/api-reference/campaigns/get-lead-by-id)
* [Export Leads](/api-reference/campaigns/export-leads)
