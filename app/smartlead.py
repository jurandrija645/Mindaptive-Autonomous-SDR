import time
from typing import Any, Iterator

import httpx

from app.config import settings

BASE_URL = "https://server.smartlead.ai/api/v1"


class SmartleadError(RuntimeError):
    pass


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=30.0)


def _request(method: str, path: str, params: dict | None = None, json: dict | None = None) -> Any:
    params = dict(params or {})
    params["api_key"] = settings.smartlead_api_key

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
            return resp.json()
    raise SmartleadError(f"{method} {path} failed after retries")


def list_campaigns() -> list[dict]:
    data = _request("GET", "/campaigns/")
    return data or []


def fetch_categories() -> dict[str, int]:
    data = _request("GET", "/leads/fetch-categories") or []
    return {item["name"]: item["id"] for item in data}


def list_campaign_leads(campaign_id: int, page_size: int = 100) -> Iterator[dict]:
    offset = 0
    while True:
        data = _request(
            "GET",
            f"/campaigns/{campaign_id}/leads",
            params={"offset": offset, "limit": page_size},
        )
        leads = data if isinstance(data, list) else (data or {}).get("data") or []
        if not leads:
            return
        for lead in leads:
            yield lead
        if len(leads) < page_size:
            return
        offset += page_size


def list_email_accounts(page_size: int = 100) -> Iterator[dict]:
    offset = 0
    while True:
        data = _request(
            "GET", "/email-accounts", params={"offset": offset, "limit": page_size}
        )
        accounts = data if isinstance(data, list) else (data or {}).get("data") or []
        if not accounts:
            return
        for account in accounts:
            yield account
        if len(accounts) < page_size:
            return
        offset += page_size


def get_message_history(campaign_id: int, lead_id: int) -> list[dict]:
    data = _request("GET", f"/campaigns/{campaign_id}/leads/{lead_id}/message-history")
    if data is None:
        return []
    if isinstance(data, dict):
        return data.get("history") or data.get("data") or []
    return data


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
    lead_id: int,
    email_body: str,
    reply_message_id: str,
    reply_email_time: str,
) -> Any:
    return _request(
        "POST",
        f"/campaigns/{campaign_id}/reply-email-thread",
        json={
            "lead_id": lead_id,
            "email_body": email_body,
            "reply_message_id": reply_message_id,
            "reply_email_time": reply_email_time,
        },
    )


def normalize_lead(raw: dict, campaign_id: int) -> dict:
    inner = raw.get("lead") if isinstance(raw.get("lead"), dict) else raw
    custom_fields = inner.get("custom_fields") or raw.get("custom_fields")
    return {
        "id": inner.get("id") or raw.get("lead_id") or raw.get("id"),
        "campaign_id": campaign_id,
        "email": inner.get("email") or raw.get("email"),
        "first_name": inner.get("first_name") or raw.get("first_name"),
        "company_name": inner.get("company_name") or raw.get("company_name"),
        "website": inner.get("website") or raw.get("website"),
        "custom_fields": custom_fields,
        "lead_category_id": raw.get("lead_category_id") or inner.get("lead_category_id"),
    }


def create_webhook(callback_url: str, event_types: list[str]) -> Any:
    return _request(
        "POST",
        "/webhooks",
        json={"url": callback_url, "event_types": event_types},
    )


def list_webhooks() -> Any:
    return _request("GET", "/webhooks")
