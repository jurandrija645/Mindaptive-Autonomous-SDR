<!-- Mirrored from https://api.smartlead.ai/core/leads — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Understanding Leads

> Learn about lead management in SmartLead

## What is a Lead?

A lead in SmartLead is a prospect you want to reach via email. Each lead has:

* **Contact Information**: Email, name, company details
* **Custom Fields**: Unlimited personalization data
* **Status**: Current state in campaign (STARTED, INPROGRESS, COMPLETED)
* **Category**: User-defined labels (Interested, Not Interested, etc.)
* **Activity History**: All interactions tracked

## Lead Lifecycle

<Steps>
  <Step title="Added to Campaign">
    Lead is imported to a campaign
  </Step>

  <Step title="Emails Sent">
    Sequences are sent according to schedule
  </Step>

  <Step title="Engagement Tracked">
    Opens, clicks, replies recorded
  </Step>

  <Step title="Categorized">
    Responses categorized (Interested, etc.)
  </Step>

  <Step title="Completed or Paused">
    Campaign completes or lead is paused
  </Step>
</Steps>

## Lead Status

| Status         | Description                 |
| -------------- | --------------------------- |
| **STARTED**    | Lead added, waiting to send |
| **INPROGRESS** | Actively receiving emails   |
| **COMPLETED**  | All sequences sent          |
| **PAUSED**     | Temporarily stopped         |
| **STOPPED**    | Permanently stopped         |
| **BLOCKED**    | In block list               |

## Lead Categories

Default categories:

* **Interested**: Positive response
* **Meeting Request**: Wants to meet
* **Not Interested**: Negative response
* **Do Not Contact**: Hard opt-out
* **Information Request**: Needs more info
* **Custom Categories**: Create your own

## Custom Fields

Add unlimited personalization data:

```json theme={null}
{
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "custom_fields": {
    "job_title": "CEO",
    "industry": "Technology",
    "company_size": "50-100",
    "pain_point": "Lead generation",
    "annual_revenue": "$5M-$10M",
    "linkedin": "https://linkedin.com/in/johndoe"
  }
}
```

Use in emails: `{{job_title}}`, `{{industry}}`, etc.

## Best Practices

<AccordionGroup>
  <Accordion title="Verify Emails First">
    Use the email verification API before adding leads to improve deliverability
  </Accordion>

  <Accordion title="Use Custom Fields">
    Add 5-10 custom fields for better personalization and higher reply rates
  </Accordion>

  <Accordion title="Segment Your Leads">
    Create separate campaigns for different personas or industries
  </Accordion>

  <Accordion title="Monitor Engagement">
    Track opens, clicks, replies to identify hot leads
  </Accordion>
</AccordionGroup>

## Related Endpoints

* [Add Leads to Campaign](/api-reference/leads/add-to-campaign)
* [Get Campaign Leads](/api-reference/leads/get-by-campaign)
* [Get Lead Categories](/api-reference/leads/categories)
* [Update Lead](/api-reference/leads/update)
