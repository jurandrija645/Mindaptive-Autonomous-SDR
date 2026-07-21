<!-- Mirrored from https://api.smartlead.ai/api-reference/campaigns/update-lead — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Campaign Lead Details

> Update lead information including contact details and custom fields

<Note>
  Update lead's contact information, company details, and custom fields within a campaign.
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

## Request Body

<ParamField body="email" type="string" required>
  Lead email address
</ParamField>

<ParamField body="first_name" type="string">
  First name
</ParamField>

<ParamField body="last_name" type="string">
  Last name
</ParamField>

<ParamField body="company_name" type="string">
  Company name
</ParamField>

<ParamField body="phone_number" type="string">
  Phone number
</ParamField>

<ParamField body="website" type="string">
  Website URL
</ParamField>

<ParamField body="location" type="string">
  Geographic location
</ParamField>

<ParamField body="linkedin_profile" type="string">
  LinkedIn profile URL
</ParamField>

<ParamField body="company_url" type="string">
  Company website
</ParamField>

<ParamField body="custom_fields" type="object">
  Custom field key-value pairs (max 200 fields)
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST "https://server.smartlead.ai/api/v1/campaigns/123/leads/789/?api_key=YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "email": "john.doe@company.com",
      "first_name": "John",
      "last_name": "Doe",
      "company_name": "ACME Corp Updated",
      "custom_fields": {
        "job_title": "CEO",
        "company_size": "50-200"
      }
    }'
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"

  def update_lead(campaign_id, lead_id, **fields):
      response = requests.post(
          f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads/{lead_id}/",
          params={"api_key": API_KEY},
          json=fields
      )
      
      if response.status_code == 200:
          print(f"✅ Lead {lead_id} updated")
      
      return response.json()

  # Update lead details
  update_lead(
      123, 789,
      email="john.doe@company.com",
      first_name="John",
      last_name="Doe",
      company_name="ACME Corp",
      custom_fields={"job_title": "CEO", "industry": "SaaS"}
  )
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  async function updateLead(campaignId, leadId, fields) {
    const response = await fetch(
      `https://server.smartlead.ai/api/v1/campaigns/${campaignId}/leads/${leadId}/?api_key=${API_KEY}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields)
      }
    );
    
    return response.json();
  }

  await updateLead(123, 789, {
    email: 'john.doe@company.com',
    company_name: 'ACME Corp',
    custom_fields: { job_title: 'CEO' }
  });
  ```
</RequestExample>

## Response Example

<ResponseExample>
  ```json 200 theme={null}
  {
    "success": true,
    "message": "Lead updated successfully"
  }
  ```
</ResponseExample>

## Related Endpoints

* [Add Leads](/api-reference/campaigns/add-leads)
* [Get Campaign Leads](/api-reference/campaigns/get-leads)
