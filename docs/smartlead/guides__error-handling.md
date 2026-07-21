<!-- Mirrored from https://api.smartlead.ai/guides/error-handling — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Error Handling Guide

> Handle SmartLead API errors gracefully — understand HTTP status codes, parse error responses, implement retry logic, and debug common issues

## Overview

The SmartLead API uses standard HTTP status codes and structured error responses to communicate what went wrong. This guide covers how to interpret errors, implement robust retry logic, and debug the most common issues.

## HTTP Status Codes

| Code  | Meaning               | Action                                                         |
| ----- | --------------------- | -------------------------------------------------------------- |
| `200` | Success               | Request completed successfully                                 |
| `201` | Created               | Resource created successfully                                  |
| `400` | Bad Request           | Fix the request payload — check required fields and data types |
| `401` | Unauthorized          | Check your API key                                             |
| `403` | Forbidden             | You don't have access to this resource                         |
| `404` | Not Found             | The resource (campaign, lead, etc.) doesn't exist              |
| `409` | Conflict              | Duplicate resource — the lead or campaign already exists       |
| `422` | Unprocessable Entity  | Validation failed — check field values                         |
| `429` | Too Many Requests     | Rate limited — slow down and retry after the delay             |
| `500` | Internal Server Error | SmartLead server issue — retry with exponential backoff        |
| `503` | Service Unavailable   | Temporary outage — retry after a short delay                   |

## Error Response Format

Error responses follow a consistent JSON structure:

```json theme={null}
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "email field is required for all leads in lead_list",
    "details": {
      "field": "lead_list[2].email",
      "constraint": "required"
    }
  }
}
```

## Implementing Error Handling

### Basic Error Handler

<CodeGroup>
  ```python Python theme={null}
  import requests
  import os

  API_KEY = os.getenv("SMARTLEAD_API_KEY")
  BASE_URL = "https://server.smartlead.ai/api/v1"

  def make_request(method, endpoint, payload=None):
      """Make an API request with comprehensive error handling."""
      url = f"{BASE_URL}/{endpoint}"
      params = {"api_key": API_KEY}

      try:
          if method == "GET":
              response = requests.get(url, params=params, timeout=30)
          elif method == "POST":
              response = requests.post(url, params=params, json=payload, timeout=30)
          elif method == "PATCH":
              response = requests.patch(url, params=params, json=payload, timeout=30)
          elif method == "DELETE":
              response = requests.delete(url, params=params, timeout=30)

          # Raise for HTTP errors
          response.raise_for_status()
          return response.json()

      except requests.exceptions.HTTPError as e:
          status = e.response.status_code
          error_body = e.response.json() if e.response.content else {}

          if status == 400:
              print(f"Bad request: {error_body.get('error', {}).get('message', 'Unknown')}")
          elif status == 401:
              print("Invalid API key. Check your SMARTLEAD_API_KEY.")
          elif status == 404:
              print(f"Resource not found: {endpoint}")
          elif status == 429:
              print("Rate limited. Retry after a delay.")
          elif status >= 500:
              print(f"Server error ({status}). Retry later.")
          else:
              print(f"HTTP {status}: {error_body}")

          raise

      except requests.exceptions.ConnectionError:
          print("Connection failed. Check your network.")
          raise

      except requests.exceptions.Timeout:
          print("Request timed out. Try again.")
          raise
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = process.env.SMARTLEAD_API_KEY;
  const BASE_URL = 'https://server.smartlead.ai/api/v1';

  async function makeRequest(method, endpoint, payload = null) {
    const url = `${BASE_URL}/${endpoint}?api_key=${API_KEY}`;

    const options = {
      method,
      headers: { 'Content-Type': 'application/json' }
    };

    if (payload && ['POST', 'PATCH', 'PUT'].includes(method)) {
      options.body = JSON.stringify(payload);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      const message = errorBody?.error?.message || response.statusText;

      switch (response.status) {
        case 400:
          throw new Error(`Bad request: ${message}`);
        case 401:
          throw new Error('Invalid API key');
        case 404:
          throw new Error(`Not found: ${endpoint}`);
        case 429:
          throw new Error('Rate limited — retry after delay');
        default:
          throw new Error(`HTTP ${response.status}: ${message}`);
      }
    }

    return response.json();
  }
  ```
</CodeGroup>

### Retry with Exponential Backoff

For transient errors (429, 500, 503), implement automatic retries:

```python Python theme={null}
import time
import random

def make_request_with_retry(method, endpoint, payload=None, max_retries=3):
    """Make an API request with exponential backoff retry."""
    for attempt in range(max_retries + 1):
        try:
            return make_request(method, endpoint, payload)

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code

            # Only retry on transient errors
            if status not in [429, 500, 502, 503]:
                raise

            if attempt == max_retries:
                print(f"Failed after {max_retries} retries")
                raise

            # Exponential backoff with jitter
            delay = (2 ** attempt) + random.uniform(0, 1)

            # Respect Retry-After header if present
            retry_after = e.response.headers.get("Retry-After")
            if retry_after:
                delay = max(delay, float(retry_after))

            print(f"Retry {attempt + 1}/{max_retries} in {delay:.1f}s...")
            time.sleep(delay)

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt == max_retries:
                raise

            delay = (2 ** attempt) + random.uniform(0, 1)
            print(f"Connection issue. Retry {attempt + 1}/{max_retries} in {delay:.1f}s...")
            time.sleep(delay)
```

<Tip>
  Always add random jitter to your backoff delay. Without jitter, multiple clients retrying at the same intervals will create "thundering herd" problems that amplify the load on the server.
</Tip>

## Common Errors and Solutions

<AccordionGroup>
  <Accordion title="401 — Invalid API key">
    **Cause:** The `api_key` parameter is missing, expired, or incorrect.

    **Fix:** Verify your API key in SmartLead Settings → API Keys. Regenerate if needed. Ensure the key is passed as a query parameter: `?api_key=YOUR_KEY`.
  </Accordion>

  <Accordion title="400 — email field is required">
    **Cause:** One or more leads in your `lead_list` are missing the `email` field.

    **Fix:** Validate your data before sending. Every lead object must have an `email` field with a valid email address.

    ```python theme={null}
    # Validate before import
    valid_leads = [lead for lead in leads if lead.get("email")]
    invalid_leads = [lead for lead in leads if not lead.get("email")]
    if invalid_leads:
        print(f"Skipping {len(invalid_leads)} leads without email")
    ```
  </Accordion>

  <Accordion title="400 — Lead list exceeds maximum size">
    **Cause:** You're trying to import more than 400 leads in a single request.

    **Fix:** Batch your imports into groups of 400 or fewer. See the [Lead Management Guide](/guides/lead-management) for a batching example.
  </Accordion>

  <Accordion title="404 — Campaign not found">
    **Cause:** The campaign ID doesn't exist or belongs to a different account.

    **Fix:** Verify the campaign ID by listing your campaigns first:

    ```python theme={null}
    campaigns = make_request("GET", "campaigns/")
    for c in campaigns.get("campaigns", []):
        print(f"ID: {c['id']} — {c['name']}")
    ```
  </Accordion>

  <Accordion title="409 — Lead already exists in campaign">
    **Cause:** A lead with the same email address is already in this campaign.

    **Fix:** This isn't necessarily an error — SmartLead prevents duplicate sends. Check the `skipped_leads` array in the import response for details.
  </Accordion>

  <Accordion title="429 — Rate limit exceeded">
    **Cause:** Too many requests in a short time period.

    **Fix:** Implement exponential backoff (see above). Check the `Retry-After` header for the recommended wait time. See the [Rate Limits Guide](/guides/rate-limits) for details.
  </Accordion>

  <Accordion title="500 — Internal server error">
    **Cause:** An unexpected error on SmartLead's servers.

    **Fix:** Retry with exponential backoff. If the error persists, check the [SmartLead status page](https://status.smartlead.ai) and contact support with the request details.
  </Accordion>
</AccordionGroup>

## Debugging Tips

### Log Every Request and Response

```python Python theme={null}
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("smartlead")

def make_request_debug(method, endpoint, payload=None):
    url = f"{BASE_URL}/{endpoint}"
    logger.debug(f"Request: {method} {url}")
    if payload:
        logger.debug(f"Payload: {payload}")

    response = requests.request(
        method, url,
        params={"api_key": API_KEY},
        json=payload,
        timeout=30
    )

    logger.debug(f"Response: {response.status_code}")
    logger.debug(f"Body: {response.text[:500]}")

    response.raise_for_status()
    return response.json()
```

### Validate Data Before Sending

```python Python theme={null}
def validate_lead(lead):
    """Validate a lead object before import."""
    errors = []

    if not lead.get("email"):
        errors.append("Missing email")
    elif "@" not in lead["email"]:
        errors.append(f"Invalid email format: {lead['email']}")

    if not lead.get("first_name"):
        errors.append("Missing first_name (will affect personalization)")

    return errors

# Validate batch before import
for i, lead in enumerate(lead_list):
    errors = validate_lead(lead)
    if errors:
        print(f"Lead {i}: {', '.join(errors)}")
```

## What's Next?

<CardGroup cols={2}>
  <Card title="Rate Limits Guide" icon="gauge" href="/guides/rate-limits">
    Understand rate limits and optimize request patterns
  </Card>

  <Card title="Best Practices" icon="star" href="/guides/best-practices">
    Build reliable integrations with production-grade patterns
  </Card>
</CardGroup>
