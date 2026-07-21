<!-- Mirrored from https://api.smartlead.ai/api-reference/leads/categories — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Lead Categories

> Retrieve all available lead categories including global and user-specific categories

<Note>
  Returns both global categories (available to all users) and categories you've created. Categories are used to organize and filter leads based on their engagement or status.
</Note>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl "https://server.smartlead.ai/api/v1/leads/fetch-categories?api_key=YOUR_KEY"
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"

  response = requests.get(
      "https://server.smartlead.ai/api/v1/leads/fetch-categories",
      params={"api_key": API_KEY}
  )

  categories = response.json()
  print(f"Total categories: {len(categories)}")

  # Filter by sentiment
  positive_categories = [c for c in categories if c['sentiment_type'] == 'positive']
  print(f"Positive sentiment categories: {len(positive_categories)}")
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  const response = await fetch(
    `https://server.smartlead.ai/api/v1/leads/fetch-categories?api_key=${API_KEY}`
  );

  const categories = await response.json();
  console.log(`Total categories: ${categories.length}`);

  // Filter by sentiment
  const positiveCategories = categories.filter(c => c.sentiment_type === 'positive');
  console.log(`Positive sentiment categories: ${positiveCategories.length}`);
  ```
</RequestExample>

## Response Fields

The response is an array of category objects, each containing:

<ResponseField name="id" type="number">
  Unique category identifier
</ResponseField>

<ResponseField name="name" type="string">
  Category name (e.g., "Interested", "Not Interested", "Meeting Booked")
</ResponseField>

<ResponseField name="sentiment_type" type="string">
  Sentiment classification of the category. Values: `positive`, `negative`, `neutral`
</ResponseField>

<ResponseField name="created_at" type="timestamp">
  ISO 8601 timestamp of when the category was created
</ResponseField>

## Response Codes

<ResponseField name="200" type="Success">
  Categories retrieved successfully
</ResponseField>

<ResponseField name="401" type="Unauthorized">
  Invalid or missing API key
</ResponseField>

<ResponseField name="500" type="Internal Server Error">
  Server error occurred
</ResponseField>

<ResponseExample>
  ```json 200 - Success theme={null}
  [
  {
      "id": 1,
      "name": "Interested",
      "sentiment_type": "positive",
      "created_at": "2024-01-15T10:30:00.000Z"
    },
    {
      "id": 2,
      "name": "Not Interested",
      "sentiment_type": "negative",
      "created_at": "2024-01-15T10:30:00.000Z"
    },
    {
      "id": 3,
      "name": "Meeting Booked",
      "sentiment_type": "positive",
      "created_at": "2024-01-15T10:30:00.000Z"
    },
    {
      "id": 789,
      "name": "Follow Up Later",
      "sentiment_type": "neutral",
      "created_at": "2025-11-20T14:22:00.000Z"
  }
  ]
  ```

  ```json 401 - Unauthorized theme={null}
  {
    "message": "Invalid API Key"
  }
  ```
</ResponseExample>

## Usage Notes

<Info>
  Categories are sorted by ID in ascending order. Global categories (available to all users) have lower IDs, while user-created categories have higher IDs.
</Info>

<Tip>
  Use the category ID when updating a lead's category via the Update Lead Category endpoint. The sentiment type helps you filter leads for reporting and analytics.
</Tip>

## Related Endpoints

* [Get Campaign Leads](/api-reference/leads/get-by-campaign) - Filter leads by category
* [Get Lead by Email](/api-reference/leads/get-by-email) - View lead's assigned category
