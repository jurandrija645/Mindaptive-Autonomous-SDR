<!-- Mirrored from https://api.smartlead.ai/api-reference/inbox/update-category — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Lead Category

> Assign or change the category for a lead (Interested, Not Interested, etc.)

<Note>
  Categories help organize leads by response type. Common categories: Interested, Not Interested, Meeting Request, Do Not Contact. Get category IDs from the categories endpoint.
</Note>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

## Request Body

<ParamField body="email_lead_map_id" type="number" required>
  The ID of the lead-campaign mapping to update. This is the `campaign_lead_map_id` from inbox or campaign leads endpoints.
</ParamField>

<ParamField body="category_id" type="number" required>
  The category ID to assign. Use `null` to remove category assignment.

  **Common Categories**:

  * `1` - Interested
  * `2` - Meeting Request
  * `3` - Not Interested
  * `4` - Do Not Contact
  * `5` - Information Request
  * Custom categories (your defined IDs)
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl -X PATCH "https://server.smartlead.ai/api/v1/master-inbox/update-category?api_key=YOUR_KEY" \
    -H "Content-Type: application/json" \
    -d '{
      "email_lead_map_id": 2433664091,
      "category_id": 1
    }'
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"

  # Mark lead as interested
  payload = {
      "email_lead_map_id": 2433664091,
      "category_id": 1  # Interested
  }

  response = requests.patch(
      "https://server.smartlead.ai/api/v1/master-inbox/update-category",
      params={"api_key": API_KEY},
      json=payload
  )

  if response.status_code == 200:
      print("Lead categorized as Interested")
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  // Mark lead as interested
  const payload = {
    email_lead_map_id: 2433664091,
    category_id: 1  // Interested
  };

  const response = await fetch(
    `https://server.smartlead.ai/api/v1/master-inbox/update-category?api_key=${API_KEY}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }
  );

  console.log('Lead categorized');
  ```
</RequestExample>

## Response Codes

<ResponseField name="200" type="Success">
  Category updated successfully
</ResponseField>

<ResponseField name="401" type="Unauthorized">
  Invalid API key
</ResponseField>

<ResponseField name="404" type="Not Found">
  Lead mapping not found
</ResponseField>

<ResponseField name="422" type="Validation Error">
  Invalid category\_id or email\_lead\_map\_id
</ResponseField>

<ResponseExample>
  ```json 200 - Success theme={null}
  {
    "success": true,
    "message": "Lead category updated successfully"
  }
  ```

  ```json 404 - Not Found theme={null}
  {
    "error": "Lead mapping not found"
  }
  ```

  ```json 422 - Validation Error theme={null}
  {
    "error": "category_id must be a valid number or null"
  }
  ```
</ResponseExample>

## Common Use Cases

### Mark as Interested

```python theme={null}
update_category(lead_map_id, category_id=1)  # Interested
```

### Mark as Not Interested

```python theme={null}
update_category(lead_map_id, category_id=3)  # Not Interested
```

### Mark as Meeting Request

```python theme={null}
update_category(lead_map_id, category_id=2)  # Meeting Request
```

### Remove Category

```python theme={null}
update_category(lead_map_id, category_id=None)  # Unassign
```

## Getting email\_lead\_map\_id

The `email_lead_map_id` is returned as `campaign_lead_map_id` from inbox endpoints:

```json From inbox response theme={null}
{
  "campaign_lead_map_id": "2433664091",  // Use this as email_lead_map_id
  "lead": {...}
}
```

## Related Endpoints

* [Get Lead Categories](/api-reference/leads/categories)
* [Get Inbox Messages](/api-reference/inbox/get-messages)
* [Get Unread Replies](/api-reference/inbox/get-unread)
