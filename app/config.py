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
    max_followups: int = int(os.getenv("MAX_FOLLOWUPS", "4"))
    # After the follow-up cap is hit, quietly resurface the lead for one
    # revival touch once this many days pass with no reply. 0 disables.
    revive_after_days: int = int(os.getenv("REVIVE_AFTER_DAYS", "60"))
    daily_scan_hour_utc: int = int(os.getenv("DAILY_SCAN_HOUR_UTC", "6"))

    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    anthropic_translate_model: str = os.getenv(
        "ANTHROPIC_TRANSLATE_MODEL", "claude-haiku-4-5"
    )

    calendly_link: str = os.getenv(
        "CALENDLY_LINK", "https://calendly.com/andrew-mindaptive/30min"
    )


settings = Settings()
