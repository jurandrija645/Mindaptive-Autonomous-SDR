import contextlib
import contextvars
import logging
import time
from typing import Any, Iterator

import httpx

from app.config import settings

log = logging.getLogger("smartlead")

BASE_URL = "https://server.smartlead.ai/api/v1"

# The account whose key `_request` should use when a call doesn't pass one
# explicitly. Lets the whole campaign-analysis chain (which scatters ~6 Smartlead
# calls across three modules) run against a chosen account without threading an
# api_key argument through every function — the caller pins the account once, at
# the top of the request handler or background worker, via `use_account`.
# A ContextVar starts fresh in each new thread, so the pin must be set inside the
# analysis worker thread, not merely inherited from the request that spawned it.
_active_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "smartlead_active_api_key", default=None
)


@contextlib.contextmanager
def use_account(api_key: str | None):
    token = _active_api_key.set(api_key)
    try:
        yield
    finally:
        _active_api_key.reset(token)


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
    params["api_key"] = api_key or _active_api_key.get() or settings.smartlead_api_key

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
                return _decode(resp)
            return resp.json()
    raise SmartleadError(f"{method} {path} failed after retries")


def _decode(resp) -> str:
    """Text body, decoded with the right charset rather than the assumed one.

    `leads-export` returns text/csv with no charset in the header, so httpx
    falls back to UTF-8 — but the file is Windows-1252. Every German and French
    lead's copy came back with U+FFFD in place of its accents ("Viele Gr��e"),
    which then flowed into the analysis as the campaign's actual wording. Only
    guess when the server declined to say."""
    if resp.charset_encoding:
        return resp.text
    raw = resp.content
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


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


def get_lead(lead_id: int, api_key: str | None = None) -> dict:
    """GET /leads/{id} — one lead, without paginating its whole campaign.

    A global lookup, so no campaign_id is needed. Carries everything the
    LinkedIn export wants and `normalize_lead` throws away: `last_name`,
    `phone_number`, `linkedin_profile`, `company_url`, and the full
    `custom_fields`.

    The published response shape is wrong in three ways — verified against the
    Mindaptive Jones test lead 2026-08-10. The real body is
    `{"ok": true, "message": "...", "data": [ {lead} ]}`: the docs show a bare
    lead object with no wrapper, `data` is a one-element LIST rather than an
    object, and the example omits every field above. It also carries no
    `lead_category_id`, so a caller that needs the category still has to go
    through `list_campaign_leads`.
    """
    data = _request("GET", f"/leads/{lead_id}", api_key=api_key)
    if isinstance(data, dict) and "data" in data:
        data = data.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    return data or {}


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


def list_recent_replies(limit: int = 20, api_key: str | None = None) -> list[dict]:
    """POST /master-inbox/inbox-replies — the newest lead replies across *every*
    campaign, newest first, in a single call.

    This is the only cheap way to learn about a lead who has never been seen
    before. Everything else we poll is keyed off leads we already track, so a
    lead replying for the first time — the most valuable message the app ever
    receives — was invisible until the next full daily scan walked their
    campaign.

    Verified against the live API 2026-08-11. The response is
    `{"ok": true, "data": [...], "offset", "limit"}` — a `data` key, not the
    documented `messages`, and no `total_count`. Each row is a lead summary,
    not a message: `email_lead_id`, `email_campaign_id`, `email_campaign_name`,
    `lead_email`, `lead_first_name`/`lead_last_name`, `lead_category_id`,
    `last_reply_time`, `has_new_unread_email`. There is no message body —
    that's what makes it fast (`fetch_message_history=false`), so a caller
    that needs the text still fetches the thread for the few leads that are
    actually new. `limit` is capped at 20 by the API."""
    data = _request(
        "POST",
        "/master-inbox/inbox-replies",
        params={"fetch_message_history": "false"},
        json={
            "offset": 0,
            "limit": max(1, min(int(limit), 20)),
            "filters": {"emailStatus": "Replied"},
            "sortBy": "REPLY_TIME_DESC",
        },
        api_key=api_key,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list):
            return rows
    return []


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


# Everything Smartlead documents as writable on a campaign lead
# (docs/smartlead/api-reference__campaigns__update-lead.md). Anything outside
# this set is a typo or a guess, and `update_lead` refuses it rather than
# posting a key the API will either ignore silently or 400 on.
LEAD_UPDATE_FIELDS = frozenset({
    "email", "first_name", "last_name", "company_name", "phone_number",
    "website", "location", "linkedin_profile", "company_url", "custom_fields",
})


def update_lead(campaign_id: int, lead_id: int, fields: dict) -> Any:
    """POST /campaigns/{id}/leads/{id}/ — write lead details back to Smartlead.

    Only the keys passed in are sent. `email` is required by the endpoint even
    when it is not the thing being changed (it is how Smartlead identifies the
    lead), so callers have to have it.

    Partial-update semantics are the assumption here: the reference's own
    JavaScript example updates `company_name` while sending neither
    `first_name` nor `last_name`, which would be a destructive example if
    omitted fields were cleared. Worth re-checking against the live API before
    leaning on this for anything but a rename — `custom_fields` is the campaign
    analysis's source spreadsheet (see app/campaign_copy.py), so that is what a
    wipe would cost. Called fail-soft from main.api_set_lead_name for the same
    reason: the local rename must stand even if this call is rejected.
    """
    unknown = sorted(set(fields) - LEAD_UPDATE_FIELDS)
    if unknown:
        raise SmartleadError(f"Not writable on a Smartlead lead: {unknown}")
    if not fields.get("email"):
        raise SmartleadError("update_lead needs the lead's email — Smartlead requires it")
    resp = _request("POST", f"/campaigns/{campaign_id}/leads/{lead_id}/", json=dict(fields))
    log.info(
        "update_lead: campaign_id=%s lead_id=%s fields=%s response=%r",
        campaign_id, lead_id, sorted(fields), resp,
    )
    return resp


def reply_to_thread(
    campaign_id: int,
    email_body: str,
    reply_message_id: str,
    reply_email_time: str,
    email_stats_id: str,
    cc: str = "",
    to_email: str = "",
    attachments: list[dict] | None = None,
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
    recipient that gets the mail, instead of relying on Smartlead's default.

    `attachments` was verified end to end on 2026-07-31 (probe send to the same
    test lead; the PDF arrived in the recipient's inbox). Each entry needs
    `file_url` and Smartlead's servers **fetch it themselves**, so the URL must
    be publicly reachable without a session — see app/library.py, which is what
    serves them. `file_size` is accepted and then dropped from the stored
    message; it's sent anyway because the reference lists it."""
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
    if attachments:
        payload["attachments"] = [
            {
                "file_name": a["file_name"],
                "file_url": a["file_url"],
                "file_type": a.get("file_type") or "application/octet-stream",
                "file_size": a.get("file_size") or 0,
            }
            for a in attachments
        ]
    log.info(
        "[SIG-DEBUG] reply_to_thread: campaign_id=%s email_stats_id=%s email_body_len=%d "
        "contains_table_tag=%s to=%s cc=%s attachments=%s",
        campaign_id, email_stats_id, len(email_body or ""), "<table" in (email_body or ""),
        to_email or "(smartlead default)", cc or "(none)",
        [a["file_url"] for a in payload.get("attachments", [])] or "(none)",
    )
    resp = _request("POST", f"/campaigns/{campaign_id}/reply-email-thread", json=payload)
    log.info("[SIG-DEBUG] reply_to_thread: response=%r", resp)
    return resp


# Smartlead custom fields that carry the lead's language, in the order we trust
# them. There is more than one because the campaigns were built at different
# times by different scrapers: `language_code` is what HealthClinics - EU and
# Dental Clinics - EU write, `targetLanguage` is what SolarPanel - EU, HVAC - EU
# and Solar Panel - USA r2 write. Only `language_code` was ever read, so every
# lead in the second group had no language on file at all — and a quick-pick
# template for one of them went out in English, because that is what
# translator.localize_quick_text does when handed no language (verified against
# the live API 2026-08-10: SolarPanel - EU alone has es/de/nl/sv/no/fi/ca/gl
# leads, all invisible to us). Keys are matched loosely (case and separators
# ignored) so "Language Code", "language_code" and "targetLanguage" all land.
_LANGUAGE_FIELDS = ("languagecode", "targetlanguage", "language")


def _language_from_custom_fields(custom_fields: dict | None) -> str | None:
    """The lead's 2-letter language code, from whichever field carries it.

    Values are trustworthy when present: across 36 leads in three EU campaigns
    the claimed code matched the language our own outbound email was actually
    written in, every time. An empty string is treated as absent — 24 Dental
    leads carry `language_code: ""`.
    """
    if not isinstance(custom_fields, dict):
        return None
    normalized = {}
    for key, value in custom_fields.items():
        flat = "".join(ch for ch in str(key).lower() if ch.isalnum())
        # First key wins on a collision; nothing in the live data collides.
        normalized.setdefault(flat, value)
    for field in _LANGUAGE_FIELDS:
        code = str(normalized.get(field) or "").strip().lower()[:2]
        if code.isalpha() and len(code) == 2:
            return code
    return None


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
        # Smartlead's own per-lead language custom field (e.g. "de") — more
        # reliable than guessing from a short auto-reply snippet via langdetect.
        # See _LANGUAGE_FIELDS: which field holds it depends on the campaign.
        "language_code": _language_from_custom_fields(custom_fields),
    }


def create_webhook(
    callback_url: str,
    event_types: list[str],
    association_type: str = "user",
    campaign_id: int | None = None,
    name: str = "Mindaptive Responder",
) -> Any:
    """POST /webhook/create — subscribe this app to Smartlead events.

    The previous version of this function posted `{"url", "event_types"}` to
    `/webhooks`, which is not an endpoint that exists; nothing called it, so
    nothing ever noticed. The real shape (Smartlead's own reference, and the
    field names its GET returns): `webhook_url`, `association_type`
    ("user" = every campaign, "campaign" = one), and `event_type_map`, a map of
    event name to boolean rather than a list.

    `association_type="user"` is the default deliberately — a per-campaign
    registration has to be repeated for every campaign created from then on,
    and forgetting once means that campaign's replies are silently invisible.
    """
    body: dict = {
        "webhook_url": callback_url,
        "association_type": association_type,
        "name": name,
        "event_type_map": {event: True for event in event_types},
    }
    if campaign_id is not None:
        body["email_campaign_id"] = campaign_id
    return _request("POST", "/webhook/create", json=body)


def list_campaign_webhooks(campaign_id: int, api_key: str | None = None) -> list[dict]:
    """GET /campaigns/{id}/webhooks — the webhooks firing for one campaign.

    Per campaign is the only listing the API offers: there is no `GET
    /webhooks` (it 404s, verified 2026-08-11), so "is anything registered?" can
    only be answered campaign by campaign."""
    data = _request("GET", f"/campaigns/{campaign_id}/webhooks", api_key=api_key)
    return data if isinstance(data, list) else []
