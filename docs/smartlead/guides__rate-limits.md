<!-- Mirrored from https://api.smartlead.ai/guides/rate-limits — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Rate Limits Guide

> Understand SmartLead API rate limits, implement backoff strategies, and optimize your request patterns to avoid throttling

## Overview

SmartLead applies rate limits to protect the platform and ensure fair access for all users. This guide explains the rate limit structure, how to detect when you're being throttled, and strategies for building efficient integrations.

## Rate Limit Structure

SmartLead enforces rate limits on a per-API-key basis:

| Tier       | Requests per Minute | Requests per Hour | Burst Limit        |
| ---------- | ------------------- | ----------------- | ------------------ |
| Standard   | 60                  | 1,000             | 10 requests/second |
| Pro        | 120                 | 3,000             | 20 requests/second |
| Enterprise | Custom              | Custom            | Custom             |

<Note>
  Rate limits apply to your API key across all endpoints combined. A mix of campaign, lead, and analytics requests all count toward the same limit.
</Note>

## Detecting Rate Limits

When you exceed the limit, the API returns a `429 Too Many Requests` response:

```json theme={null}
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Too many requests. Please retry after 30 seconds.",
    "retry_after": 30
  }
}
```

### Rate Limit Headers

Check response headers to monitor your usage:

| Header                  | Description                                   |
| ----------------------- | --------------------------------------------- |
| `X-RateLimit-Limit`     | Maximum requests allowed in the window        |
| `X-RateLimit-Remaining` | Requests remaining in the current window      |
| `X-RateLimit-Reset`     | Unix timestamp when the window resets         |
| `Retry-After`           | Seconds to wait before retrying (only on 429) |

```python Python theme={null}
import requests
import os

API_KEY = os.getenv("SMARTLEAD_API_KEY")
BASE_URL = "https://server.smartlead.ai/api/v1"

response = requests.get(
    f"{BASE_URL}/campaigns/",
    params={"api_key": API_KEY}
)

# Check rate limit status
limit = response.headers.get("X-RateLimit-Limit")
remaining = response.headers.get("X-RateLimit-Remaining")
reset = response.headers.get("X-RateLimit-Reset")

print(f"Limit: {limit} | Remaining: {remaining} | Resets at: {reset}")
```

## Backoff Strategies

### Exponential Backoff with Jitter

The recommended approach for handling rate limits:

```python Python theme={null}
import time
import random

def request_with_backoff(method, endpoint, payload=None, max_retries=5):
    """Make request with exponential backoff on rate limits."""
    for attempt in range(max_retries + 1):
        response = requests.request(
            method,
            f"{BASE_URL}/{endpoint}",
            params={"api_key": API_KEY},
            json=payload,
            timeout=30
        )

        if response.status_code == 429:
            if attempt == max_retries:
                raise Exception("Rate limit exceeded after max retries")

            # Use Retry-After header if available
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                delay = float(retry_after)
            else:
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                delay = (2 ** attempt) + random.uniform(0, 1)

            print(f"Rate limited. Waiting {delay:.1f}s (attempt {attempt + 1})")
            time.sleep(delay)
            continue

        response.raise_for_status()
        return response.json()
```

### Proactive Rate Limiting

Instead of waiting for 429s, track your usage and throttle proactively:

```python Python theme={null}
import time
from collections import deque

class RateLimiter:
    """Client-side rate limiter to avoid 429 errors."""

    def __init__(self, max_per_minute=50):
        self.max_per_minute = max_per_minute
        self.requests = deque()

    def wait_if_needed(self):
        """Block until it's safe to make another request."""
        now = time.time()

        # Remove requests older than 60 seconds
        while self.requests and self.requests[0] < now - 60:
            self.requests.popleft()

        if len(self.requests) >= self.max_per_minute:
            # Wait until the oldest request expires
            wait_time = 60 - (now - self.requests[0])
            if wait_time > 0:
                print(f"Throttling: waiting {wait_time:.1f}s")
                time.sleep(wait_time)

        self.requests.append(time.time())

# Usage
limiter = RateLimiter(max_per_minute=50)  # Stay under the 60/min limit

for campaign_id in campaign_ids:
    limiter.wait_if_needed()
    data = make_request("GET", f"campaigns/{campaign_id}/analytics")
```

<Tip>
  Set your client-side limit to 80% of the actual limit (e.g., 50 requests/minute when the limit is 60). This buffer accounts for timing differences and prevents edge-case throttling.
</Tip>

## Optimizing Request Patterns

### Batch Operations

Instead of making individual requests per lead, use batch endpoints:

```python Python theme={null}
# Bad: 100 individual requests
for lead in leads:
    requests.post(f"{BASE_URL}/campaigns/{cid}/leads",
                  params={"api_key": API_KEY},
                  json={"lead_list": [lead]})

# Good: 1 batch request for up to 400 leads
requests.post(f"{BASE_URL}/campaigns/{cid}/leads",
              params={"api_key": API_KEY},
              json={"lead_list": leads[:400]})
```

### Cache Responses

Cache data that doesn't change often to reduce API calls:

```python Python theme={null}
import functools
import time

_cache = {}

def cached_request(endpoint, ttl_seconds=300):
    """Cache GET requests for a specified TTL."""
    now = time.time()

    if endpoint in _cache:
        data, cached_at = _cache[endpoint]
        if now - cached_at < ttl_seconds:
            return data

    data = make_request("GET", endpoint)
    _cache[endpoint] = (data, now)
    return data

# Campaigns list doesn't change often — cache for 5 minutes
campaigns = cached_request("campaigns/", ttl_seconds=300)

# Analytics change frequently — cache for 1 minute
analytics = cached_request(f"campaigns/{cid}/analytics", ttl_seconds=60)
```

### Use Webhooks Instead of Polling

Instead of polling for new replies every few seconds:

```python Python theme={null}
# Bad: Polling every 30 seconds (2 requests/minute per campaign)
while True:
    response = requests.get(f"{BASE_URL}/campaigns/{cid}/leads",
                           params={"api_key": API_KEY, "status": "INTERESTED"})
    time.sleep(30)
```

Set up a webhook to receive events in real time with zero API calls:

```python Python theme={null}
# Good: Register a webhook once, receive events instantly
requests.post(f"{BASE_URL}/webhooks",
              params={"api_key": API_KEY},
              json={
                  "webhook_url": "https://yourapp.com/hooks/smartlead",
                  "event_types": ["EMAIL_REPLIED"]
              })
```

See the [Webhook Integration Guide](/guides/webhook-integration) for full details.

### Parallelize with Rate Awareness

When you need to make many requests, use controlled concurrency:

```python Python theme={null}
import concurrent.futures
import time

limiter = RateLimiter(max_per_minute=50)

def fetch_campaign_data(campaign_id):
    limiter.wait_if_needed()
    return make_request("GET", f"campaigns/{campaign_id}/analytics")

# Process campaigns with controlled parallelism
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = {
        executor.submit(fetch_campaign_data, cid): cid
        for cid in campaign_ids
    }

    for future in concurrent.futures.as_completed(futures):
        cid = futures[future]
        try:
            data = future.result()
            print(f"Campaign {cid}: {data.get('total_sent', 0)} sent")
        except Exception as e:
            print(f"Campaign {cid} failed: {e}")
```

## Troubleshooting

<AccordionGroup>
  <Accordion title="Getting 429 errors with low request volume">
    Check if another integration or script is using the same API key. Rate limits are per-key, not per-client. Consider using separate API keys for different integrations.
  </Accordion>

  <Accordion title="Rate limits feel too restrictive">
    Review your request patterns — are you polling when you could use webhooks? Are you making individual requests when batch endpoints are available? If you genuinely need higher limits, contact SmartLead support about Enterprise plans.
  </Accordion>

  <Accordion title="Retry-After header is missing on 429 response">
    Default to exponential backoff starting at 1 second. Most rate limit windows reset within 60 seconds.
  </Accordion>
</AccordionGroup>

## What's Next?

<CardGroup cols={2}>
  <Card title="Error Handling Guide" icon="shield" href="/guides/error-handling">
    Handle all API errors gracefully
  </Card>

  <Card title="Best Practices" icon="star" href="/guides/best-practices">
    Build production-grade SmartLead integrations
  </Card>
</CardGroup>
