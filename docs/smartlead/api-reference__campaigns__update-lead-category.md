<!-- Mirrored from https://api.smartlead.ai/api-reference/campaigns/update-lead-category — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Lead Category in Campaign

> Assign or change the category for a lead within a campaign

<Note>
  Categorize leads (Interested, Not Interested, etc.) for better organization and reporting.
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

<ParamField body="category_id" type="number">
  Category ID to assign (use `null` to remove category)
</ParamField>

<ParamField body="pause_lead" type="boolean" default="false">
  Pause the lead after categorizing
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl -X POST "https://server.smartlead.ai/api/v1/campaigns/123/leads/789/category?api_key=YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{"category_id": 1, "pause_lead": false}'
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"

  def update_lead_category(campaign_id, lead_id, category_id, pause=False):
      payload = {
          "category_id": category_id,
          "pause_lead": pause
      }
      
      response = requests.post(
          f"https://server.smartlead.ai/api/v1/campaigns/{campaign_id}/leads/{lead_id}/category",
          params={"api_key": API_KEY},
          json=payload
      )
      
      if response.status_code == 200:
          print(f"✅ Lead categorized as {category_id}")
      
      return response.json()

  # Mark as interested and pause
  update_lead_category(123, 789, category_id=1, pause=True)
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  async function updateCategory(campaignId, leadId, categoryId, pause = false) {
    const response = await fetch(
      `https://server.smartlead.ai/api/v1/campaigns/${campaignId}/leads/${leadId}/category?api_key=${API_KEY}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_id: categoryId, pause_lead: pause })
      }
    );
    
    return response.json();
  }

  await updateCategory(123, 789, 1, true);
  ```
</RequestExample>

## Response Example

<ResponseExample>
  ```json 200 theme={null}
  {
    "success": true,
    "message": "Lead category updated"
  }
  ```
</ResponseExample>

## Related Endpoints

* [Get Lead Categories](/api-reference/leads/categories)
* [Update Category (Master Inbox)](/api-reference/inbox/update-category)
