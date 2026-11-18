> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Lead Sequence Details

> Get the send status of every sequence step for a lead in a campaign

> [!NOTE]
>
> Returns one entry per email stats row for the lead map, in all statuses (for example `SENT` and `STOPPED`), ordered by `sent_time`. Get `leadMapId` from [Get Lead Campaign Overview](https://api.smartlead.ai/api-reference/leads/campaign-overview.md) (`id`) or `campaign_lead_map_id` from the campaign's leads.

## Path Parameters

**leadMapId** `number` *required*

Lead map ID (positive integer)

## Query Parameters

**api\_key** `string` *required*

Your SmartLead API key (client API keys are not allowed)

**campaignId** `number`

Campaign ID to restrict the results to (positive integer)

```bash cURL theme={null}
curl "https://server.smartlead.ai/api/v1/leads/987654/sequence-details?api_key=YOUR_KEY&campaignId=123"
```

```python Python theme={null}
import requests

response = requests.get(
    "https://server.smartlead.ai/api/v1/leads/987654/sequence-details",
    params={"api_key": "YOUR_API_KEY", "campaignId": 123}
)
for step in response.json()["data"]:
    print(step["email_campaign_seq_id"], step["status"])
```

## Response

**data** `array`

**items**

**status** `string`

Send status of the step

**sent\_time** `string | null`

When the step was sent

**status\_message** `string | null`

Status message

**email\_campaign\_seq\_id** `number`

Sequence ID

```json 200 theme={null}
{
  "ok": true,
  "message": "Lead sequence details fetched successfully",
  "data": [
    {
      "status": "SENT",
      "sent_time": "2026-09-20T09:00:00.000Z",
      "status_message": null,
      "email_campaign_seq_id": 5001
    },
    {
      "status": "STOPPED",
      "sent_time": null,
      "status_message": null,
      "email_campaign_seq_id": 5002
    }
  ]
}
```

```json 500 theme={null}
{
  "ok": false,
  "message": "Error fetching lead sequence details"
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.