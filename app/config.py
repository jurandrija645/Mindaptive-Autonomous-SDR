import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int_list(name: str, default: str) -> tuple[int, ...]:
    """Comma-separated int list env var, e.g. FOLLOWUP_WAIT_DAYS=3,4,6,8.
    A single value (the old scalar form) still works and behaves as before."""
    raw = os.getenv(name, default)
    vals = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    return vals or tuple(int(part.strip()) for part in default.split(","))


@dataclass
class Settings:
    smartlead_api_key: str = os.getenv("SMARTLEAD_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    app_password: str = os.getenv("APP_PASSWORD", "")
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    n8n_webhook_url: str = os.getenv("N8N_WEBHOOK_URL", "")
    smartlead_webhook_secret: str = os.getenv("SMARTLEAD_WEBHOOK_SECRET", "")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080")

    db_path: str = os.getenv("DB_PATH", "/data/responder.db")
    # Draft images live beside the DB, on the same Docker volume.
    upload_dir: str = os.getenv("UPLOAD_DIR", "/data/uploads")

    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", True))
    auto_send_followups: bool = field(
        default_factory=lambda: _bool("AUTO_SEND_FOLLOWUPS", False)
    )
    # After the daily scan, pre-generate every due follow-up draft in one
    # Anthropic Batch API job (50% token discount, results within ~1h) so the
    # morning dashboard is a ready review queue. Generation only — sending
    # still always requires a click (unless AUTO_SEND_FOLLOWUPS is also on).
    # Approved on-by-default by Andrew, 2026-07-19.
    auto_generate_followups: bool = field(
        default_factory=lambda: _bool("AUTO_GENERATE_FOLLOWUPS", True)
    )

    interested_category_name: str = os.getenv(
        "INTERESTED_CATEGORY_NAME", "Interested"
    )
    autoreply_category_name: str = os.getenv(
        "AUTOREPLY_CATEGORY_NAME", "Auto-Reply"
    )
    # Smartlead's own "meeting booked" lead category — the app's success
    # signal. Matched case/punctuation-insensitively (the real account has it
    # as "Meeting-Booked"), so "Meeting booked" etc. also resolve.
    meeting_booked_category_name: str = os.getenv(
        "MEETING_BOOKED_CATEGORY_NAME", "Meeting-Booked"
    )
    # Days to wait before follow-up #N — indexed by how many follow-ups have
    # already gone out (last value repeats past the end of the list). A single
    # number keeps the old fixed cadence; "3,4,6,8" spaces touches further
    # apart as the thread goes colder.
    followup_wait_days: tuple[int, ...] = field(
        default_factory=lambda: _int_list("FOLLOWUP_WAIT_DAYS", "3")
    )
    # A lead rated 🔥 very hot (app/lead_temperature.py — they asked to meet,
    # call or see a demo) is chased on this many HOURS instead of the day-based
    # cadence above. Only ever shortens the wait, never lengthens it. 0 turns
    # the short cadence off and puts hot leads back on FOLLOWUP_WAIT_DAYS; they
    # still sort to the top of the inbox either way.
    hot_followup_wait_hours: int = int(os.getenv("HOT_FOLLOWUP_WAIT_HOURS", "24"))
    max_followups: int = int(os.getenv("MAX_FOLLOWUPS", "4"))
    # After the follow-up cap is hit, quietly resurface the lead for one
    # revival touch once this many days pass with no reply. 0 disables.
    revive_after_days: int = int(os.getenv("REVIVE_AFTER_DAYS", "60"))
    daily_scan_hour_utc: int = int(os.getenv("DAILY_SCAN_HOUR_UTC", "6"))
    # How often (minutes) to run the lightweight reply-catch scan
    # (scheduler.run_reply_catch_scan) — the safety net for replies the webhook
    # missed (it's fire-and-forget, and a reply that lands during a deploy
    # restart is lost), so Andrew never has to click "Rescan now" to see a reply.
    # Cheap: it only re-checks leads we already track as live conversations and
    # bulk-fetches their threads (~one Smartlead call per campaign), so a tight
    # cadence stays far under the API rate limit. 0 disables.
    scan_interval_minutes: int = int(os.getenv("SCAN_INTERVAL_MINUTES", "5"))

    # How often to ask Smartlead "who has written to us lately?" — the poll that
    # decides how long a lead's FIRST reply stays invisible
    # (scheduler.run_new_reply_poll). Two API calls and no per-lead work, so it
    # runs far more often than the reply-catch pass above. 0 disables.
    new_reply_poll_seconds: int = int(os.getenv("NEW_REPLY_POLL_SECONDS", "60"))

    # Which model sorts an incoming reply into "real prospect" vs "out of office
    # / rejection" (app/reply_classifier.py), deciding whether to spend a draft
    # on it. This is the job the n8n workflow's gpt-5-mini node used to do
    # before Smartlead's webhook pointed straight at the app. One word in, one
    # word out, on every single reply — so the default is the cheapest model in
    # the picker. Overridable per-install here and, at runtime, from the
    # dashboard's Models panel ("Sorting incoming replies").
    reply_classifier_model: str = os.getenv(
        "REPLY_CLASSIFIER_MODEL", "deepseek/deepseek-v4-flash"
    )

    # Detect the lead's language from their reply when Smartlead has no
    # "Language Code" custom field. That is a Claude call per lead during the
    # scan, so an English-only client (AeroDefense) should turn it off: it saves
    # tens of thousands of calls and makes the scan work even with no Anthropic
    # credit, since the scan then needs no model at all.
    detect_language: bool = field(
        default_factory=lambda: _bool("DETECT_LANGUAGE", True)
    )

    # Skip leads whose last outbound message came from a mailbox Smartlead no
    # longer returns — the mailbox is retired, so the thread can't be replied
    # to. AeroDefense needs this; Mindaptive's mailboxes are all live and its
    # personas resolve by name hint, so it stays off by default.
    require_known_sender: bool = field(
        default_factory=lambda: _bool("REQUIRE_KNOWN_SENDER", False)
    )

    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    anthropic_translate_model: str = os.getenv(
        "ANTHROPIC_TRANSLATE_MODEL", "claude-haiku-4-5"
    )

    # OpenRouter — a second model provider for draft writing. Set the key and
    # every OpenRouter model in app/models_registry.py shows up in the
    # dashboard's model picker alongside the Anthropic ones (labelled by
    # provider, with live per-million-token prices pulled from OpenRouter's own
    # /models endpoint). Leave blank and the picker is Anthropic-only.
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    # Extra OpenRouter model ids to offer, comma-separated (e.g.
    # "qwen/qwen3.7-plus,mistralai/mistral-medium-3-5"). Added on top of the
    # curated list in models_registry.CURATED_OPENROUTER_MODELS, so a new model
    # can be tried without a code change.
    openrouter_extra_models: str = os.getenv("OPENROUTER_MODELS", "")

    calendly_link: str = os.getenv(
        "CALENDLY_LINK", "https://calendly.com/andrew-mindaptive/30min"
    )

    # Google Sheets — the "Export for LinkedIn" button (app/exports/sheet_export.py).
    # OAuth rather than a service account: Andrew already owns both spreadsheets,
    # so acting as him needs nothing shared and no key file placed on the droplet.
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    # Optional. The refresh token normally lives in app_settings (obtained via
    # the dashboard's Connect flow), but the two containers have separate
    # databases — setting this in .env.aerodefense lets the second one reuse the
    # consent the first already gave instead of doing its own round trip.
    google_refresh_token: str = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    # Spreadsheet this client's leads are exported into, one tab per sending
    # persona. Per client, so it belongs in each .env. Blank hides the button.
    linkedin_sheet_id: str = os.getenv("LINKEDIN_SHEET_ID", "")
    # Where a lead goes when its thread was sent from a mailbox that no longer
    # maps to a persona (AeroDefense's retired anna@/linda@/lexi.r@ inboxes).
    # Created with a header row if the spreadsheet doesn't have it.
    linkedin_sheet_fallback_tab: str = os.getenv("LINKEDIN_SHEET_FALLBACK_TAB", "Other")

    # Optional automatic worklist (app/interested_sheet.py): every lead that
    # clears reply_classifier as INTERESTED gets a row here the moment it
    # happens, no click required — unlike the LinkedIn sheet above, which is
    # per-lead and manual. Blank (the default) means the module no-ops.
    # Reuses the same Google OAuth connection as the LinkedIn export.
    interested_sheet_id: str = os.getenv("INTERESTED_SHEET_ID", "")

    # Shared secret for POST /webhooks/booking-confirmed (app/webhook.py) — an
    # external automation (e.g. an n8n flow watching a booking-confirmation
    # inbox) calls this to record a meeting booked outside Smartlead's own
    # category flow. Same header/query-param convention as
    # SMARTLEAD_WEBHOOK_SECRET. Blank disables the route's secret check, which
    # is fine for local testing but should always be set once this is public.
    booking_webhook_secret: str = os.getenv("BOOKING_WEBHOOK_SECRET", "")


settings = Settings()
