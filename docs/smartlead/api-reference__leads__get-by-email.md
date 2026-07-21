<!-- Mirrored from https://api.smartlead.ai/api-reference/leads/get-by-email — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Lead by Email

> Search for a lead by email address and retrieve all associated campaign data

<Note>
  Returns lead details including personal information, custom fields, and all campaigns the lead is enrolled in. Returns empty object if lead not found.
</Note>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

<ParamField query="email" type="string" required>
  The email address to search for
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl "https://server.smartlead.ai/api/v1/leads/?api_key=YOUR_KEY&email=john@example.com"
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"
  email = "john@example.com"

  response = requests.get(
      "https://server.smartlead.ai/api/v1/leads/",
      params={
          "api_key": API_KEY,
          "email": email
      }
  )

  result = response.json()
  if result:
      print(f"Found lead: {result['first_name']} {result['last_name']}")
      print(f"Enrolled in {len(result['lead_campaign_data'])} campaigns")
  else:
      print("Lead not found")
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';
  const email = 'john@example.com';

  const response = await fetch(
    `https://server.smartlead.ai/api/v1/leads/?api_key=${API_KEY}&email=${encodeURIComponent(email)}`
  );

  const result = await response.json();
  if (Object.keys(result).length > 0) {
    console.log(`Found lead: ${result.first_name} ${result.last_name}`);
    console.log(`Enrolled in ${result.lead_campaign_data.length} campaigns`);
  } else {
    console.log('Lead not found');
  }
  ```
</RequestExample>

## Response Fields

<ResponseField name="id" type="number">
  Unique lead identifier
</ResponseField>

<ResponseField name="email" type="string">
  Lead's email address
</ResponseField>

<ResponseField name="first_name" type="string">
  Lead's first name
</ResponseField>

<ResponseField name="last_name" type="string">
  Lead's last name
</ResponseField>

<ResponseField name="phone_number" type="string">
  Lead's phone number
</ResponseField>

<ResponseField name="company_name" type="string">
  Company name
</ResponseField>

<ResponseField name="website" type="string">
  Company website
</ResponseField>

<ResponseField name="location" type="string">
  Lead's location
</ResponseField>

<ResponseField name="linkedin_profile" type="string">
  LinkedIn profile URL
</ResponseField>

<ResponseField name="company_url" type="string">
  Company URL
</ResponseField>

<ResponseField name="custom_fields" type="object">
  Custom fields object containing personalization data
</ResponseField>

<ResponseField name="is_unsubscribed" type="boolean">
  Whether the lead is globally unsubscribed
</ResponseField>

<ResponseField name="unsubscribed_client_id_map" type="object">
  Map of client IDs where lead is unsubscribed
</ResponseField>

<ResponseField name="created_at" type="timestamp">
  ISO 8601 timestamp of when the lead was created
</ResponseField>

<ResponseField name="lead_campaign_data" type="array">
  Array of campaigns this lead is enrolled in

  <Expandable title="Campaign data properties">
    <ResponseField name="campaign_lead_map_id" type="number">
      Unique identifier for the lead-campaign mapping
    </ResponseField>

    <ResponseField name="campaign_id" type="number">
      Campaign ID
    </ResponseField>

    <ResponseField name="campaign_name" type="string">
      Campaign name
    </ResponseField>

    <ResponseField name="client_id" type="number">
      Client ID who owns the campaign
    </ResponseField>

    <ResponseField name="client_email" type="string">
      Email of the client who owns the campaign
    </ResponseField>

    <ResponseField name="lead_category_id" type="number | null">
      Category ID assigned to this lead in the campaign
    </ResponseField>
  </Expandable>
</ResponseField>

## Response Codes

<ResponseField name="200" type="Success">
  Lead retrieved successfully (returns empty object if not found)
</ResponseField>

<ResponseField name="401" type="Unauthorized">
  Invalid or missing API key
</ResponseField>

<ResponseField name="422" type="Validation Error">
  Missing or invalid email parameter
</ResponseField>

<ResponseField name="500" type="Internal Server Error">
  Server error occurred
</ResponseField>

<ResponseExample>
  ```json 200 - Success theme={null}
  {
    "id": 2995276770,
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "phone_number": "+1234567890",
    "company_name": "Acme Corp",
    "website": "https://acme.com",
    "location": "San Francisco, CA",
    "linkedin_profile": "https://linkedin.com/in/johndoe",
    "company_url": "https://acme.com",
    "custom_fields": {
      "job_title": "CEO",
      "industry": "Technology"
    },
    "is_unsubscribed": false,
    "unsubscribed_client_id_map": null,
    "created_at": "2025-11-25T12:54:54.000Z",
    "lead_campaign_data": [
      {
        "campaign_lead_map_id": 2433664091,
        "campaign_id": 123,
        "campaign_name": "Q4 Outreach",
        "client_id": 456,
        "client_email": "user@company.com",
        "lead_category_id": 789
      }
    ]
  }
  ```

  ```json 200 - Lead Not Found theme={null}
  {}
  ```

  ```json 401 - Unauthorized theme={null}
  {
    "message": "Invalid API Key"
  }
  ```

  ```json 422 - Validation Error theme={null}
  {
    "error": "email is required"
  }
  ```
</ResponseExample>

## Related Endpoints

* [Get Campaign Leads](/api-reference/leads/get-by-campaign)
* [Add Leads to Campaign](/api-reference/leads/add-to-campaign)
* [Unsubscribe Lead](/api-reference/leads/unsubscribe)
