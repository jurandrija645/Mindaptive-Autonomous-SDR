<!-- Mirrored from https://api.smartlead.ai/api-reference/campaigns/get-lead-by-id — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Lead by ID

> Retrieve detailed information about a specific lead

<Note>
  Get complete lead details including contact info, engagement stats, category, and custom fields. This is a global lead lookup across all campaigns.
</Note>

## Path Parameters

<ParamField path="lead_id" type="number" required>
  Lead ID
</ParamField>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl "https://server.smartlead.ai/api/v1/leads/789?api_key=YOUR_KEY"
  ```

  ```python Python theme={null}
  import requests

  response = requests.get(
      "https://server.smartlead.ai/api/v1/leads/789",
      params={"api_key": "YOUR_API_KEY"}
  )

  lead = response.json()
  print(f"Lead: {lead['email']}")
  print(f"Status: {lead['status']}")
  print(f"Category: {lead.get('category_name', 'Uncategorized')}")
  ```
</RequestExample>

## Response Example

<ResponseExample>
  ```json 200 theme={null}
  {
    "id": 789,
    "email": "john@company.com",
    "first_name": "John",
    "last_name": "Doe",
    "company_name": "ACME Corp",
    "status": "INPROGRESS",
    "category_id": 1,
    "category_name": "Interested",
    "email_stats": {
      "is_opened": true,
      "is_clicked": true,
      "is_replied": true
    },
    "custom_fields": {
      "job_title": "CEO"
    }
  }
  ```
</ResponseExample>
