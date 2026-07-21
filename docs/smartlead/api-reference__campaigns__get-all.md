<!-- Mirrored from https://api.smartlead.ai/api-reference/campaigns/get-all — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get All Campaigns

> Retrieves all email campaigns for the authenticated user with comprehensive campaign data including status, schedule set

<Note>
  Retrieves all email campaigns for the authenticated user with comprehensive campaign data including status, schedule settings, tracking configuration, AI matching preferences, and sending limits Essential for dashboard displays, campaign selection interfaces, and bulk operations across portfolio.
</Note>

## Overview

Retrieves all email campaigns for the authenticated user with comprehensive campaign data including status, schedule settings, tracking configuration, AI matching preferences, and sending limits

**Key Features**:

* Returns campaigns ordered by ID descending (newest first)
* Supports optional client\_id filtering for agency/white-label accounts managing multiple clients
* When include\_tags=true, returns campaign tags with tag IDs, names, and colors for categorization and filtering
* Returns direct array of campaign objects (not wrapped)

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

<ParamField query="client_id" type="number">
  Filter campaigns by specific client ID
</ParamField>

<ParamField query="include_tags" type="boolean" default="false">
  Include campaign tags in the response
</ParamField>

## Response

<ResponseField name="success" type="boolean">
  Indicates if the request was successful
</ResponseField>

<ResponseField name="campaigns" type="array">
  Array of campaign objects

  <Expandable title="Campaign Object Fields">
    <ResponseField name="id" type="number">
      Unique campaign identifier
    </ResponseField>

    <ResponseField name="user_id" type="number">
      ID of the user who owns this campaign
    </ResponseField>

    <ResponseField name="name" type="string">
      Campaign name set by user
    </ResponseField>

    <ResponseField name="status" type="string">
      Current campaign status: `ACTIVE`, `PAUSED`, `STOPPED`, `ARCHIVED`, `DRAFTED`
    </ResponseField>

    <ResponseField name="created_at" type="string">
      ISO 8601 timestamp when campaign was created
    </ResponseField>

    <ResponseField name="updated_at" type="string">
      ISO 8601 timestamp of last modification
    </ResponseField>

    <ResponseField name="track_settings" type="array">
      Tracking configuration. Array can contain:

      * `"DONT_EMAIL_OPEN"` - Disable open tracking
      * `"DONT_LINK_CLICK"` - Disable click tracking
      * Empty array `[]` - Track everything
    </ResponseField>

    <ResponseField name="scheduler_cron_value" type="object">
      Sending schedule configuration

      <Expandable title="Schedule Object">
        <ResponseField name="tz" type="string">
          Timezone (IANA format, e.g., "America/New\_York")
        </ResponseField>

        <ResponseField name="days" type="array">
          Days of week to send (0=Sunday, 1=Monday, ..., 6=Saturday)
        </ResponseField>

        <ResponseField name="startHour" type="string">
          Start sending time (24-hour format, e.g., "09:00")
        </ResponseField>

        <ResponseField name="endHour" type="string">
          Stop sending time (24-hour format, e.g., "17:00")
        </ResponseField>
      </Expandable>
    </ResponseField>

    <ResponseField name="min_time_btwn_emails" type="number">
      Minimum minutes to wait between consecutive emails. Higher values (120+) appear more natural and improve deliverability.
    </ResponseField>

    <ResponseField name="max_leads_per_day" type="number">
      Maximum number of leads to contact per day across all email accounts
    </ResponseField>

    <ResponseField name="stop_lead_settings" type="string">
      When to stop emailing a lead: `REPLY_TO_AN_EMAIL`, `OPENED_EMAIL`, `CLICKED_LINK`, or `NEVER`
    </ResponseField>

    <ResponseField name="schedule_start_time" type="string">
      Scheduled start time for campaign (ISO 8601 format), `null` if starting immediately
    </ResponseField>

    <ResponseField name="enable_ai_esp_matching" type="boolean">
      When `true`, SmartLead's AI automatically matches leads with optimal email accounts based on provider and deliverability history
    </ResponseField>

    <ResponseField name="send_as_plain_text" type="boolean">
      When `true`, emails are sent as plain text instead of HTML for better deliverability with technical audiences
    </ResponseField>

    <ResponseField name="follow_up_percentage" type="number">
      Percentage of leads that receive follow-up emails (0-100)
    </ResponseField>

    <ResponseField name="unsubscribe_text" type="string">
      Custom unsubscribe footer text
    </ResponseField>

    <ResponseField name="parent_campaign_id" type="number">
      If this is a subsequence, references the parent campaign ID. `null` for main campaigns.
    </ResponseField>

    <ResponseField name="client_id" type="number">
      Associated client ID for agency/white-label accounts. `null` for direct user campaigns.
    </ResponseField>

    <ResponseField name="tags" type="array">
      Campaign tags (only included if `include_tags=true`)

      <Expandable title="Tag Object">
        <ResponseField name="tag_id" type="number">
          Tag identifier
        </ResponseField>

        <ResponseField name="tag_name" type="string">
          Tag name
        </ResponseField>

        <ResponseField name="tag_color" type="string">
          Tag color (hex format, e.g., "#FF5733")
        </ResponseField>
      </Expandable>
    </ResponseField>
  </Expandable>
</ResponseField>

<RequestExample>
  ```bash cURL theme={null}
  curl -X GET "https://server.smartlead.ai/api/v1/campaigns/?api_key=YOUR_API_KEY&include_tags=true"
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"
  url = "https://server.smartlead.ai/api/v1/campaigns/"

  response = requests.get(
      url, 
      params={
          "api_key": API_KEY,
          "include_tags": True
      }
  )

  campaigns = response.json()
  print(f"Total campaigns: {len(campaigns['campaigns'])}")
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  async function getAllCampaigns() {
    const response = await fetch(
      `https://server.smartlead.ai/api/v1/campaigns/?api_key=${API_KEY}&include_tags=true`
    );
    
    const data = await response.json();
    return data.campaigns;
  }

  getAllCampaigns().then(campaigns => {
    console.log(`Found ${campaigns.length} campaigns`);
  });
  ```

  ```php PHP theme={null}
  <?php
  $api_key = 'YOUR_API_KEY';
  $url = 'https://server.smartlead.ai/api/v1/campaigns/';

  $ch = curl_init();
  curl_setopt($ch, CURLOPT_URL, "$url?api_key=$api_key&include_tags=true");
  curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

  $response = curl_exec($ch);
  curl_close($ch);

  $data = json_decode($response, true);
  echo "Total campaigns: " . count($data['campaigns']);
  ?>
  ```
</RequestExample>

<ResponseExample>
  ```json Response (Actual from API - Direct Array) theme={null}
  [
    {
      "id": 2710262,
      "user_id": 196026,
      "created_at": "2025-11-25T10:43:46.826Z",
      "updated_at": "2025-11-25T14:02:21.776Z",
      "status": "ACTIVE",
      "name": "Cold Outreach Q1 2024",
      "track_settings": ["DONT_EMAIL_OPEN", "DONT_LINK_CLICK"],
      "scheduler_cron_value": {
        "tz": "America/New_York",
        "days": [1, 2, 3, 4, 5],
        "endHour": "19:00",
        "startHour": "09:00"
      },
      "min_time_btwn_emails": 24,
      "max_leads_per_day": 100,
      "stop_lead_settings": "REPLY_TO_AN_EMAIL",
      "schedule_start_time": null,
      "enable_ai_esp_matching": true,
      "send_as_plain_text": false,
      "follow_up_percentage": 20,
      "unsubscribe_text": "",
      "parent_campaign_id": null,
      "client_id": null,
      "tags": [
        {
          "tag_id": 1,
          "tag_name": "Q1",
          "tag_color": "#FF5733"
        }
      ]
    }
  ]
  ```

  <Note>
    **Response Format**: This endpoint returns a direct array of campaigns, not wrapped in a success object. Each campaign contains comprehensive configuration including schedule, tracking settings, AI preferences, and sending limits.
  </Note>

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

## Response Codes

<ResponseField name="200" type="Success">
  Campaigns retrieved successfully
</ResponseField>

<ResponseField name="401" type="Unauthorized">
  Invalid or missing API key
</ResponseField>

<ResponseField name="500" type="Internal Server Error">
  Server error occurred
</ResponseField>

## Filtering Campaigns

You can filter campaigns by:

* **Client ID**: Get campaigns for a specific client
* **Status**: Use the campaign status filter in your application logic after fetching
* **Tags**: Include tags to filter on your end

## Pagination

Currently, this endpoint returns all campaigns. For large accounts with many campaigns, consider implementing pagination on your end or contact support for enterprise pagination options.

<Tip>
  Cache campaign lists to reduce API calls. Only fetch when you need fresh data.
</Tip>

## Common Use Cases

### Get Active Campaigns Only

```python Python theme={null}
import requests

API_KEY = "YOUR_API_KEY"
url = "https://server.smartlead.ai/api/v1/campaigns/"

response = requests.get(url, params={"api_key": API_KEY})
campaigns = response.json()

active_campaigns = [
    c for c in campaigns['campaigns'] 
    if c['status'] == 'ACTIVE'
]

print(f"Active campaigns: {len(active_campaigns)}")
```

### Get Campaigns by Client

```python Python theme={null}
client_id = 456

response = requests.get(
    url, 
    params={
        "api_key": API_KEY,
        "client_id": client_id
    }
)

campaigns = response.json()
```

## Related Endpoints

* [Get Campaign by ID](/api-reference/campaigns/get-by-id)
* [Create Campaign](/api-reference/campaigns/create)
* [Update Campaign Status](/api-reference/campaigns/update-status)
* [Get Campaign Statistics](/api-reference/campaigns/statistics)
