import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


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

    interested_category_name: str = os.getenv(
        "INTERESTED_CATEGORY_NAME", "Interested"
    )
    followup_wait_days: int = int(os.getenv("FOLLOWUP_WAIT_DAYS", "3"))
    max_followups: int = int(os.getenv("MAX_FOLLOWUPS", "4"))
    daily_scan_hour_utc: int = int(os.getenv("DAILY_SCAN_HOUR_UTC", "6"))

    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    calendly_link: str = os.getenv(
        "CALENDLY_LINK", "https://calendly.com/andrew-mindaptive/30min"
    )


settings = Settings()
