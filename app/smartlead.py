import logging
import time
from typing import Any, Iterator

import httpx

from app.config import settings

log = logging.getLogger("smartlead")

BASE_URL = "https://server.smartlead.ai/api/v1"


class SmartleadError(RuntimeError):
    pass


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=30.0)


def _request(
    method: str,
    path: str,
    params: dict | None = None,
    json: dict | None = None,
    api_key: str | None = None,
) -> Any:
    params = dict(params or {})
    params["api_key"] = api_key or settings.smartlead_api_key

    max_attempts = 5
    backoff = 1.5
    with _client() as client:
        for attempt in range(1, max_attempts + 1):
            resp = client.request(method, path, params=params, json=json)
            if resp.status_code == 429:
                if attempt == max_attempts:
                    raise SmartleadError(f"Rate limited on {path} after {max_attempts} attempts")
                time.sleep(backoff ** attempt)
                continue
            if resp.status_code >= 400:
                raise SmartleadError(
                    f"{method} {path} failed: {resp.status_code} {resp.text[:500]}"
                )
            if not resp.content:
                return None
            if not resp.headers.get("content-type", "").startswith("application/json"):
                return resp.text
            return resp.json()
    raise SmartleadError(f"{method} {path} failed after retries")


def list_campaigns(api_key: str | None = None) -> list[dict]:
    data = _request("GET", "/campaigns/", api_key=api_key)
    return data or []


def fetch_categories(api_key: str | None = None) -> dict[str, int]:
    data = _request("GET", "/leads/fetch-categories", api_key=api_key) or []
    return {item["name"]: item["id"] for item in data}


def list_campaign_leads(
    campaign_id: int, page_size: int = 100, api_key: str | None = None
) -> Iterator[dict]:
    offset = 0
    while True:
        data = _request(
            "GET",
            f"/campaigns/{campaign_id}/leads",
            params={"offset": offset, "limit": page_size},
            api_key=api_key,
        )
        leads = data if isinstance(data, list) else (data or {}).get("data") or []
        if not leads:
            return
        for lead in leads:
            yield lead
        if len(leads) < page_size:
            return
        offset += page_size


def list_email_accounts(page_size: int = 100, api_key: str | None = None) -> Iterator[dict]:
    offset = 0
    while True:
        data = _request(
            "GET", "/email-accounts", params={"offset": offset, "limit": page_size},
            api_key=api_key,
        )
        accounts = data if isinstance(data, list) else (data or {}).get("data") or []
        if not accounts:
            return
        for account in accounts:
            yield account
        if len(accounts) < page_size:
            return
        offset += page_size


def get_message_history(
    campaign_id: int, lead_id: int, api_key: str | None = None
) -> list[dict]:
    data = _request(
        "GET", f"/campaigns/{campaign_id}/leads/{lead_id}/message-history", api_key=api_key
    )
    if data is None:
        return []
    if isinstance(data, dict):
        return data.get("history") or data.get("data") or []
    return data


def get_campaign(campaign_id: int, api_key: str | None = None) -> dict:
    """GET /campaigns/{id} — campaign settings. The fields that matter here are
    `track_settings` (this account runs DONT_EMAIL_OPEN/DONT_LINK_CLICK, i.e.
    open and click tracking are deliberately off, so open rate is not a signal),
    `scheduler_cron_value` (tz + send window) and `send_as_plain_text`."""
    return _request("GET", f"/campaigns/{campaign_id}", api_key=api_key) or {}


def get_campaign_analytics(campaign_id: int, api_key: str | None = None) -> dict:
    """GET /campaigns/{id}/analytics — campaign totals: sent_count, reply_count,
    bounce_count, unique_sent_count, unsubscribed_count, campaign_lead_stats{}.

    Note these disagree with the per-send /statistics rows (verified 2026-07-22:
    reply_count 86 here vs 117 rows from statistics?email_status=replied on
    campaign 3640877 — per-lead vs per-email counting). Use this only for the
    headline card; anything ranked must come from statistics so one consistent
    denominator is used throughout."""
    return _request("GET", f"/campaigns/{campaign_id}/analytics", api_key=api_key) or {}


def get_campaign_sequences(campaign_id: int, api_key: str | None = None) -> list[dict]:
    """GET /campaigns/{id}/sequences — the email steps and their A/B variants.

    Returns a bare list of steps, each with `seq_number`, `subject`,
    `email_body`, `seq_delay_details` and `sequence_variants[]` (note: the docs
    call the key `seq_variants`; the real response uses `sequence_variants`).
    Each variant carries `id`, `variant_label` ("A".."F"), `subject`,
    `email_body`. Verified against campaigns 3640877/3599203/3562710."""
    data = _request("GET", f"/campaigns/{campaign_id}/sequences", api_key=api_key)
    if data is None:
        return []
    if isinstance(data, dict):
        return data.get("data") or []
    return data


def iter_campaign_statistics(
    campaign_id: int,
    sent_time_start_date: str | None = None,
    page_size: int = 1000,
    api_key: str | None = None,
) -> Iterator[dict]:
    """GET /campaigns/{id}/statistics — one row per sent email. This is the only
    endpoint that ties a send to the variant that produced it.

    The documented response (`is_opened`/`is_replied` booleans) is wrong. Real
    rows, verified 2026-07-22: `stats_id`, `lead_email`, `lead_category`,
    `sequence_number`, `email_campaign_seq_id`, `seq_variant_id`,
    `email_subject` and `email_message` (both fully rendered, variables already
    substituted), `sent_time`, `open_time`, `click_time`, `reply_time`,
    `open_count`, `click_count`, `is_unsubscribed`, `is_bounced`,
    `ignore_reply`. Wrapper is {total_stats, data, offset, limit}; `limit` caps
    at 1000.

    `sent_time_start_date` makes the sync incremental — the rows are ~10 KB
    each (they carry the full rendered body), so a full pull of a 7.5k-send
    campaign moves ~75 MB and should happen exactly once."""
    offset = 0
    while True:
        params: dict[str, Any] = {"offset": offset, "limit": page_size}
        if sent_time_start_date:
            params["sent_time_start_date"] = sent_time_start_date
        data = _request(
            "GET", f"/campaigns/{campaign_id}/statistics", params=params, api_key=api_key
        )
        rows = data if isinstance(data, list) else (data or {}).get("data") or []
        if not rows:
            return
        for row in rows:
            yield row
        if len(rows) < page_size:
            return
        offset += page_size


def export_campaign_leads_csv(campaign_id: int, api_key: str | None = None) -> str:
    """GET /campaigns/{id}/leads-export — the campaign's leads as real CSV
    (content-type text/csv, so _request returns it as text).

    Columns: id, campaign_lead_map_id, status, category, is_interested,
    created_at, first_name, last_name, email, phone_number, company_name,
    website, location, custom_fields, linkedin_profile, company_url,
    is_unsubscribed, unsubscribed_client_id_map, last_email_sequence_sent,
    open_count, click_count, reply_count.

    `custom_fields` is a JSON blob holding every variable the campaign was
    built from (subjectLine1-4, CTA1-3, Pitch1-2, Offer1-2, Icebreaker, ...) —
    i.e. this is the source spreadsheet, recovered from Smartlead. It is also
    the only bulk email -> lead_id map (the statistics rows carry only the
    email), which the conversation sync needs. ~22 MB on a 5k-lead campaign."""
    data = _request("GET", f"/campaigns/{campaign_id}/leads-export", api_key=api_key)
    return data if isinstance(data, str) else ""


# The literal token is part of the documented URL, not a secret or a parameter.
_BULK_HISTORY_TOKEN = "bbfbdsFGHlBr76ruhjvh6fhHL"


def get_message_history_bulk(
    campaign_id: int, lead_ids: list[str | int], api_key: str | None = None
) -> dict[str, dict]:
    """POST /campaigns/{id}/message-history-for-leads/<token> — full threads for
    many leads in one call, keyed by lead id: {"<lead_id>": {"history": [...]}}.

    The docs claim each message carries only `subject`/`sent_at`. That is wrong
    (verified 2026-07-22): messages have the same shape as the single-lead
    message-history endpoint — `type` ("SENT"/"REPLY"), `from`, `to`, `time`,
    `subject`, `email_body` (full HTML), `stats_id`, `message_id` — plus
    `email_seq_number` on SENT messages, which is what tells us which follow-up
    step earned a reply.

    Passing `lead_ids: null` means "every lead in the campaign" and would pull
    thousands of threads, so an empty list returns {} instead."""
    if not lead_ids:
        return {}
    data = _request(
        "POST",
        f"/campaigns/{campaign_id}/message-history-for-leads/{_BULK_HISTORY_TOKEN}",
        json={"lead_ids": [str(lead_id) for lead_id in lead_ids]},
        api_key=api_key,
    )
    return data if isinstance(data, dict) else {}


def update_lead_category(
    campaign_id: int, lead_id: int, category_id: int, pause_lead: bool = False
) -> Any:
    """POST /campaigns/{id}/leads/{id}/category — the real Smartlead action for
    recategorizing a lead (e.g. to "Not Interested"). `pause_lead` also stops
    Smartlead's own automated sequence for this lead."""
    return _request(
        "POST",
        f"/campaigns/{campaign_id}/leads/{lead_id}/category",
        json={"category_id": category_id, "pause_lead": pause_lead},
    )


def reply_to_thread(
    campaign_id: int,
    email_body: str,
    reply_message_id: str,
    reply_email_time: str,
    email_stats_id: str,
    cc: str = "",
    to_email: str = "",
) -> Any:
    """POST /campaigns/{id}/reply-email-thread. Body schema confirmed against
    https://api.smartlead.ai/reference/reply-to-lead-from-master-inbox-via-api
    on 2026-07-16: email_stats_id and email_body are the only required fields;
    lead_id is NOT a valid key here (rejected with "lead_id is not allowed").
    `cc`/`bcc` (comma-separated) and `to_email` are optional per the same
    reference — without cc, colleagues the lead CC'd on their reply are not
    included on ours.

    `to_email` was verified accepted against the real API on 2026-07-21 (probe
    send to the Mindaptive Jones test lead returned the usual plain-text
    success). It matters because the docs say To "defaults to lead email" —
    i.e. the *imported* address, which is wrong whenever outreach went to a
    generic info@ and a real person answered from their own mailbox. Passing
    it explicitly makes the recipient shown in the dashboard exactly the
    recipient that gets the mail, instead of relying on Smartlead's default."""
    payload = {
        "email_stats_id": email_stats_id,
        "email_body": email_body,
        "reply_message_id": reply_message_id,
        "reply_email_time": reply_email_time,
    }
    if to_email:
        payload["to_email"] = to_email
    if cc:
        payload["cc"] = cc
    log.info(
        "[SIG-DEBUG] reply_to_thread: campaign_id=%s email_stats_id=%s email_body_len=%d "
        "contains_table_tag=%s to=%s cc=%s",
        campaign_id, email_stats_id, len(email_body or ""), "<table" in (email_body or ""),
        to_email or "(smartlead default)", cc or "(none)",
    )
    resp = _request("POST", f"/campaigns/{campaign_id}/reply-email-thread", json=payload)
    log.info("[SIG-DEBUG] reply_to_thread: response=%r", resp)
    return resp


def normalize_lead(raw: dict, campaign_id: int) -> dict:
    inner = raw.get("lead") if isinstance(raw.get("lead"), dict) else raw
    custom_fields = inner.get("custom_fields") or raw.get("custom_fields") or {}
    return {
        "id": inner.get("id") or raw.get("lead_id") or raw.get("id"),
        "campaign_id": campaign_id,
        "email": inner.get("email") or raw.get("email"),
        "first_name": inner.get("first_name") or raw.get("first_name"),
        "company_name": inner.get("company_name") or raw.get("company_name"),
        "website": inner.get("website") or raw.get("website"),
        "custom_fields": custom_fields,
        "lead_category_id": raw.get("lead_category_id") or inner.get("lead_category_id"),
        # Smartlead's own per-lead "Language Code" custom field (e.g. "de") —
        # confirmed present on real leads (verified 2026-07-16). More reliable
        # than guessing from a short auto-reply snippet via langdetect.
        "language_code": (custom_fields or {}).get("language_code") or None,
    }


def create_webhook(callback_url: str, event_types: list[str]) -> Any:
    return _request(
        "POST",
        "/webhooks",
        json={"url": callback_url, "event_types": event_types},
    )


def list_webhooks() -> Any:
    return _request("GET", "/webhooks")
