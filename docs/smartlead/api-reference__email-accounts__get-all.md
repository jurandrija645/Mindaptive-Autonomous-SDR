<!-- Mirrored from https://api.smartlead.ai/api-reference/email-accounts/get-all — regenerate with scripts/fetch_smartlead_docs.py, do not hand-edit. -->

> ## Documentation Index
> Fetch the complete documentation index at: https://api.smartlead.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get All Email Accounts

> Retrieve all email accounts with advanced filtering and pagination options

<Note>
  Returns email accounts with SMTP/IMAP credentials, warmup status, and campaign associations. Supports filtering by connection status, warmup state, email provider, and usage status.
</Note>

## Query Parameters

<ParamField query="api_key" type="string" required>
  Your SmartLead API key
</ParamField>

<ParamField query="offset" type="number" default="0">
  Pagination offset (minimum: 0)
</ParamField>

<ParamField query="limit" type="number" default="100">
  Number of accounts to return per page (minimum: 1, maximum: 100)
</ParamField>

<ParamField query="isInUse" type="string">
  Filter by usage status. Valid values: `true` (used in campaigns), `false` (not used in campaigns)
</ParamField>

<ParamField query="emailWarmupStatus" type="string">
  Filter by warmup status. Valid values: `ACTIVE`, `INACTIVE`
</ParamField>

<ParamField query="isSmtpSuccess" type="string">
  Filter by SMTP connection status. Valid values: `true` (connected), `false` (failed)
</ParamField>

<ParamField query="isWarmupBlocked" type="string">
  Filter by warmup blocked status. Valid values: `true` (blocked), `false` (not blocked)
</ParamField>

<ParamField query="esp" type="string">
  Filter by email service provider. Valid values: `GMAIL`, `OUTLOOK`, `SMTP`
</ParamField>

<ParamField query="username" type="string">
  Filter by email username (partial match supported)
</ParamField>

<ParamField query="client_id" type="number">
  Filter by client ID (for multi-tenant accounts)
</ParamField>

<ParamField query="fetch_campaigns" type="string">
  If `true`, includes an array of campaign IDs for each email account. Returns a `campaign_ids` field on each account object.
</ParamField>

<RequestExample>
  ```bash cURL theme={null}
  curl "https://server.smartlead.ai/api/v1/email-accounts/?api_key=YOUR_KEY&limit=50&emailWarmupStatus=ACTIVE&isSmtpSuccess=true"
  ```

  ```python Python theme={null}
  import requests

  API_KEY = "YOUR_API_KEY"

  response = requests.get(
      "https://server.smartlead.ai/api/v1/email-accounts/",
      params={
          "api_key": API_KEY,
          "limit": 50,
          "offset": 0,
          "emailWarmupStatus": "ACTIVE",
          "isSmtpSuccess": "true",
          "esp": "GMAIL"
      }
  )

  accounts = response.json()
  print(f"Total accounts: {len(accounts)}")

  # Display account details
  for account in accounts:
      print(f"{account['from_email']} - Warmup: {account['warmup_details']['status'] if account['warmup_details'] else 'None'}")
  ```

  ```javascript JavaScript theme={null}
  const API_KEY = 'YOUR_API_KEY';

  const params = new URLSearchParams({
    api_key: API_KEY,
    limit: 50,
    offset: 0,
    emailWarmupStatus: 'ACTIVE',
    isSmtpSuccess: 'true',
    esp: 'GMAIL'
  });

  const response = await fetch(
    `https://server.smartlead.ai/api/v1/email-accounts/?${params}`
  );

  const accounts = await response.json();
  console.log(`Total accounts: ${accounts.length}`);

  // Display account details
  accounts.forEach(account => {
    const warmupStatus = account.warmup_details?.status || 'None';
    console.log(`${account.from_email} - Warmup: ${warmupStatus}`);
  });
  ```
</RequestExample>

## Response Fields

The response is an array of email account objects, each containing:

<AccordionGroup>
  <Accordion title="Account Information">
    <ResponseField name="id" type="number">
      Unique email account identifier
    </ResponseField>

    <ResponseField name="from_name" type="string">
      Display name for outgoing emails
    </ResponseField>

    <ResponseField name="from_email" type="string">
      Email address
    </ResponseField>

    <ResponseField name="username" type="string">
      Email account username
    </ResponseField>

    <ResponseField name="type" type="string">
      Account type: `GMAIL`, `OUTLOOK`, or `SMTP`
    </ResponseField>

    <ResponseField name="client_id" type="number | null">
      Associated client ID
    </ResponseField>

    <ResponseField name="campaign_count" type="number">
      Number of campaigns using this email account
    </ResponseField>

    <ResponseField name="created_at" type="timestamp">
      When the account was added
    </ResponseField>

    <ResponseField name="updated_at" type="timestamp">
      When the account was last updated
    </ResponseField>
  </Accordion>

  <Accordion title="SMTP Configuration">
    <ResponseField name="smtp_host" type="string">
      SMTP server hostname
    </ResponseField>

    <ResponseField name="smtp_port" type="number">
      SMTP server port
    </ResponseField>

    <ResponseField name="smtp_port_type" type="string">
      SMTP port type (SSL/TLS/STARTTLS)
    </ResponseField>

    <ResponseField name="is_smtp_success" type="boolean">
      Whether SMTP connection is successful
    </ResponseField>

    <ResponseField name="smtp_failure_error" type="string | null">
      SMTP connection error message if failed
    </ResponseField>
  </Accordion>

  <Accordion title="IMAP Configuration">
    <ResponseField name="imap_host" type="string">
      IMAP server hostname
    </ResponseField>

    <ResponseField name="imap_port" type="number">
      IMAP server port
    </ResponseField>

    <ResponseField name="imap_port_type" type="string">
      IMAP port type (SSL/TLS)
    </ResponseField>

    <ResponseField name="imap_username" type="string">
      IMAP username
    </ResponseField>

    <ResponseField name="is_different_imap_account" type="boolean">
      Whether IMAP uses different credentials than SMTP
    </ResponseField>

    <ResponseField name="is_imap_success" type="boolean">
      Whether IMAP connection is successful
    </ResponseField>

    <ResponseField name="imap_failure_error" type="string | null">
      IMAP connection error message if failed
    </ResponseField>
  </Accordion>

  <Accordion title="Sending Configuration">
    <ResponseField name="message_per_day" type="number">
      Maximum messages allowed per day
    </ResponseField>

    <ResponseField name="daily_sent_count" type="number">
      Messages sent today
    </ResponseField>

    <ResponseField name="signature" type="string | null">
      Email signature HTML
    </ResponseField>

    <ResponseField name="custom_tracking_domain" type="string | null">
      Custom domain for tracking links
    </ResponseField>

    <ResponseField name="bcc_email" type="string | null">
      BCC email address for all outgoing emails
    </ResponseField>

    <ResponseField name="different_reply_to_address" type="string | null">
      Custom reply-to email address
    </ResponseField>

    <ResponseField name="minTimeToWaitInMins" type="number">
      Minimum time to wait between emails (in minutes)
    </ResponseField>
  </Accordion>

  <Accordion title="Warmup Details">
    <ResponseField name="warmup_details" type="object | null">
      Email warmup status and metrics

      <Expandable title="Warmup properties">
        <ResponseField name="status" type="string">
          Warmup status: `ACTIVE`, `INACTIVE`, `PAUSED`
        </ResponseField>

        <ResponseField name="total_sent_count" type="number">
          Total emails sent during warmup
        </ResponseField>

        <ResponseField name="total_spam_count" type="number">
          Total emails marked as spam
        </ResponseField>

        <ResponseField name="warmup_reputation" type="string">
          Warmup reputation percentage (e.g., "95%")
        </ResponseField>

        <ResponseField name="warmup_key_id" type="number">
          Warmup service key identifier
        </ResponseField>

        <ResponseField name="warmup_created_at" type="timestamp">
          When warmup was started
        </ResponseField>

        <ResponseField name="reply_rate" type="number">
          Warmup reply rate percentage
        </ResponseField>

        <ResponseField name="blocked_reason" type="string | null">
          Reason if warmup is blocked
        </ResponseField>
      </Expandable>
    </ResponseField>
  </Accordion>

  <Accordion title="Tags">
    <ResponseField name="tags" type="array">
      Tags assigned to this email account. Always included in the response.

      <Expandable title="Tag properties">
        <ResponseField name="tag_id" type="number">
          Unique tag identifier
        </ResponseField>

        <ResponseField name="tag_name" type="string">
          Tag display name
        </ResponseField>

        <ResponseField name="tag_color" type="string">
          Tag color as a hex code (e.g., `#F5B1FC`)
        </ResponseField>
      </Expandable>
    </ResponseField>
  </Accordion>

  <Accordion title="Campaign IDs (Optional)">
    <ResponseField name="campaign_ids" type="array">
      Array of campaign IDs using this email account. Only included when `fetch_campaigns=true` is passed as a query parameter.
    </ResponseField>
  </Accordion>
</AccordionGroup>

## Response Codes

<ResponseField name="200" type="Success">
  Email accounts retrieved successfully
</ResponseField>

<ResponseField name="401" type="Unauthorized">
  Invalid or missing API key
</ResponseField>

<ResponseField name="422" type="Validation Error">
  Invalid query parameters (check limit range and filter values)
</ResponseField>

<ResponseField name="500" type="Internal Server Error">
  Server error occurred
</ResponseField>

<ResponseExample>
  ```json 200 - Success theme={null}
  [
    {
      "id": 123,
      "created_at": "2025-01-15T10:30:00.000Z",
      "updated_at": "2025-11-26T08:00:00.000Z",
      "user_id": 456,
      "from_name": "John Doe",
      "from_email": "john@example.com",
      "minTimeToWaitInMins": 5,
      "username": "john@example.com",
      "password": "encrypted_password",
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "smtp_port_type": "TLS",
      "message_per_day": 50,
      "different_reply_to_address": null,
      "is_different_imap_account": false,
      "imap_username": "john@example.com",
      "imap_password": "encrypted_password",
      "imap_host": "imap.gmail.com",
      "imap_port": 993,
      "imap_port_type": "SSL",
      "signature": "<p>Best regards,<br>John</p>",
      "custom_tracking_domain": null,
      "bcc_email": null,
      "is_smtp_success": true,
      "is_imap_success": true,
      "smtp_failure_error": null,
      "imap_failure_error": null,
      "type": "GMAIL",
      "daily_sent_count": 25,
      "client_id": null,
      "campaign_count": 3,
      "tags": [
        {
          "tag_id": 10,
          "tag_name": "Winners",
          "tag_color": "#B1FCCF"
        },
        {
          "tag_id": 15,
          "tag_name": "Webinar Emails",
          "tag_color": "#F5B1FC"
        }
      ],
      "warmup_details": {
        "status": "ACTIVE",
        "total_sent_count": 450,
        "total_spam_count": 2,
        "warmup_reputation": "95%",
        "warmup_key_id": 789,
        "warmup_created_at": "2025-01-15T10:30:00.000Z",
        "reply_rate": 15,
        "blocked_reason": null
      },
      "campaign_ids": [101, 102, 103]
    }
  ]
  ```

  ```json 401 - Unauthorized theme={null}
  {
    "message": "Invalid API Key"
  }
  ```

  ```json 422 - Validation Error theme={null}
  {
    "error": "limit must be less than or equal to 100"
  }
  ```
</ResponseExample>

## Usage Notes

<Info>
  The `tags` array is always included in the response. The `campaign_ids` array is only included when `fetch_campaigns=true` is passed as a query parameter.
</Info>

<Info>
  Passwords are base64 encoded in the response for security. Decode them before use in your SMTP/IMAP clients.
</Info>

<Tip>
  Use filters to find specific accounts:

  * Filter by `isSmtpSuccess=false` to find accounts with connection issues
  * Filter by `isInUse=false` to find unused accounts
  * Filter by `emailWarmupStatus=ACTIVE` to find accounts currently warming up
</Tip>

## Related Endpoints

* [Get Email Account by ID](/api-reference/email-accounts/get-by-id)
* [Get All Tags](/api-reference/email-accounts/tags)
* [Add SMTP Email Account](/api-reference/email-accounts/add-smtp)
* [Update Email Account](/api-reference/email-accounts/update)
