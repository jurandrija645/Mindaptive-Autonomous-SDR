> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Lead Campaign Overview

> Get a lead's details and every campaign it is in, with its status and current sequence step in each

> [!NOTE]
>
> Get `leadId` from [Get Lead by Email](https://api.smartlead.ai/api-reference/leads/get-by-email.md). Each item in `email_campaign_leads_mappings` is one campaign the lead is in. Its `id` is the lead map ID used by [Get Lead Sequence Details](https://api.smartlead.ai/api-reference/leads/sequence-details.md). For inactive mappings (`is_active: false`), `status`, `revenue`, `current_seq_num`, `next_timestamp_to_reach`, `email_campaign_id` and `email_account_id` are returned as `"XXX"`.

## Path Parameters

**leadId** `number` *required*

Lead ID

## Query Parameters

**api\_key** `string` *required*

Your SmartLead API key (client API keys are not allowed)

```bash cURL theme={null}
curl "https://server.smartlead.ai/api/v1/leads/55501/campaign-overview?api_key=YOUR_KEY"
```

```python Python theme={null}
import requests

response = requests.get(
    "https://server.smartlead.ai/api/v1/leads/55501/campaign-overview",
    params={"api_key": "YOUR_API_KEY"}
)
for mapping in response.json()["data"]["email_campaign_leads_mappings"]:
    print(mapping["email_campaign"]["name"], mapping["status"], mapping["current_seq_num"])
```

## Response

**data** `object`

The lead (`id`, `email`, `first_name`, `last_name`, `phone_number`, `company_name`, `website`, `company_url`, `location`, `custom_fields`, `linkedin_profile`, `esp_domain_type`) and `email_campaign_leads_mappings`.

**email\_campaign\_leads\_mappings items**

**id** `string`

Lead map ID

**status** `string`

Lead status in the campaign

**lead\_category\_id** `number | null`

Lead category ID

**revenue** `string | null`

Revenue

**current\_seq\_num** `string`

Current sequence step number

**next\_timestamp\_to\_reach** `string | null`

Next scheduled send time

**email\_campaign\_id** `string`

Campaign ID

**email\_account\_id** `string | null`

Assigned email account ID

**is\_active** `boolean`

Whether the mapping is active

**email\_campaign** `object`

`id` (string), `name`, `status`, `sequence_count` (number of sequence steps)

```json 200 theme={null}
{
  "ok": true,
  "message": "Campaign lead overview fetched successfully",
  "data": {
    "id": 55501,
    "email": "john.doe@acme.com",
    "last_name": "Doe",
    "first_name": "John",
    "phone_number": null,
    "company_name": "Acme",
    "website": "https://acme.com",
    "company_url": "acme.com",
    "location": null,
    "custom_fields": {},
    "linkedin_profile": null,
    "esp_domain_type": 1,
    "email_campaign_leads_mappings": [
      {
        "id": "987654",
        "status": "INPROGRESS",
        "lead_category_id": null,
        "revenue": null,
        "current_seq_num": "2",
        "next_timestamp_to_reach": "2026-09-30T09:00:00+00:00",
        "email_campaign_id": "123",
        "email_account_id": "321",
        "is_active": true,
        "email_campaign": {
          "id": "123",
          "name": "Q4 Outreach",
          "status": "ACTIVE",
          "sequence_count": 3
        }
      }
    ]
  }
}
```

```json 500 theme={null}
{
  "ok": false,
  "message": "Error fetching campaign lead overview"
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.