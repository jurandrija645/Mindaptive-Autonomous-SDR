import json
from app import db, models_registry, client_assets
from app.config import settings

with db.db_session() as conn:
    stored = db.get_setting(conn, models_registry.DEFAULT_MODEL_SETTING_KEY)
print(json.dumps({
    "client": client_assets.CLIENT_LABEL,
    "configured_model": settings.anthropic_model,
    "saved_draft_model": stored,
    "effective_draft_model": models_registry.default_model(),
    "effective_batch_model": models_registry.resolve_anthropic(None),
    "auto_generate_followups": settings.auto_generate_followups,
    "auto_send_followups": settings.auto_send_followups,
    "dry_run": settings.dry_run,
}, ensure_ascii=False))
