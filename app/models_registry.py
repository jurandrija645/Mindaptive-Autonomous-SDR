"""The one place that knows which models the dashboard offers, who provides
them, and what they cost.

Two providers:

- **anthropic** — `claude-*` ids, called through the Anthropic SDK. Only these
  get web search/fetch tools, prompt caching and the overnight Batch API, so
  the batch pre-generation path (app/batch_gen.py) always resolves to an
  Anthropic model no matter what the default is set to.
- **openrouter** — `vendor/model` ids, called through app/openrouter.py. No web
  tools, no caching; much cheaper per token.

`provider_for` splits them on the id itself (Anthropic ids are `claude-*`,
OpenRouter ids always contain a `/`), so nothing has to carry a provider column
around — `drafts.model` keeps storing the plain id it always did.

**Prices are per million tokens.** The Anthropic ones are hardcoded (they change
rarely and are worth having correct with no network call); the OpenRouter ones
are pulled live from OpenRouter's own /models endpoint and cached for 12h, with
the values below as the offline fallback — a stale hardcoded price is the one
thing that makes a cost-comparison picker actively misleading.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

from app import db, openrouter
from app.config import settings

log = logging.getLogger(__name__)

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENROUTER = "openrouter"

DEFAULT_MODEL_SETTING_KEY = "default_model"

# id -> (label, $/M input, $/M output). Prices verified against Anthropic's
# published rates 2026-08-05; Sonnet 5 carries a $2/$10 introductory rate
# through 2026-08-31, listed here at its standard price.
ANTHROPIC_MODELS: dict[str, tuple[str, float, float]] = {
    "claude-haiku-4-5": ("Haiku 4.5", 1.00, 5.00),
    "claude-sonnet-5": ("Sonnet 5", 3.00, 15.00),
    "claude-opus-4-8": ("Opus 4.8", 5.00, 25.00),
    "claude-opus-5": ("Opus 5", 5.00, 25.00),
}

# The OpenRouter models offered in the picker. This is a curated shortlist, not
# OpenRouter's full ~340-model catalog: a dropdown of 340 entries is unusable,
# and most of them are worse than what's here at writing multilingual sales
# email. Add an id to this list (or to OPENROUTER_MODELS in .env, which is
# appended to it) and it shows up with live pricing on the next restart.
CURATED_OPENROUTER_MODELS: list[str] = [
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "google/gemini-3.5-flash",
    "openai/gpt-5.6-terra",
    "x-ai/grok-4.5",
    "moonshotai/kimi-k2.6",
    "z-ai/glm-5.2",
    "qwen/qwen3.7-plus",
]

# Offline fallback only — used when OpenRouter's /models endpoint can't be
# reached. Snapshot taken 2026-08-05; the live fetch overrides all of it.
_OPENROUTER_FALLBACK: dict[str, tuple[str, float, float]] = {
    "deepseek/deepseek-v4-flash": ("DeepSeek V4 Flash", 0.14, 0.28),
    "deepseek/deepseek-v4-pro": ("DeepSeek V4 Pro", 0.44, 0.87),
    "google/gemini-3.5-flash": ("Gemini 3.5 Flash", 1.50, 9.00),
    "openai/gpt-5.6-terra": ("GPT-5.6 Terra", 1.00, 6.00),
    "x-ai/grok-4.5": ("Grok 4.5", 2.00, 6.00),
    "moonshotai/kimi-k2.6": ("Kimi K2.6", 0.59, 2.48),
    "z-ai/glm-5.2": ("GLM 5.2", 0.76, 2.42),
    "qwen/qwen3.7-plus": ("Qwen3.7 Plus", 0.32, 1.28),
}

_CATALOG_TTL = timedelta(hours=12)
_catalog_lock = threading.Lock()
_catalog_cache: dict | None = None
_catalog_fetched_at: datetime | None = None


def provider_for(model_id: str) -> str:
    """Anthropic ids are `claude-*`; every OpenRouter id is `vendor/model`."""
    return PROVIDER_OPENROUTER if "/" in (model_id or "") else PROVIDER_ANTHROPIC


def openrouter_model_ids() -> list[str]:
    """Curated list plus anything added via OPENROUTER_MODELS in .env, deduped
    with the curated entries first so the picker's order stays stable."""
    ids = list(CURATED_OPENROUTER_MODELS)
    for extra in (settings.openrouter_extra_models or "").split(","):
        extra = extra.strip()
        if extra and extra not in ids:
            ids.append(extra)
    return ids


def _openrouter_live_prices() -> dict[str, dict]:
    """Cached (12h) snapshot of OpenRouter's /models. Returns {} if the fetch
    fails — callers fall back to _OPENROUTER_FALLBACK."""
    global _catalog_cache, _catalog_fetched_at
    now = datetime.now(timezone.utc)
    with _catalog_lock:
        fresh = (
            _catalog_cache is not None
            and _catalog_fetched_at is not None
            and now - _catalog_fetched_at < _CATALOG_TTL
        )
        if fresh:
            return _catalog_cache
        try:
            _catalog_cache = openrouter.fetch_catalog()
            _catalog_fetched_at = now
        except Exception:
            log.warning("openrouter: model catalog fetch failed, using fallback prices", exc_info=True)
            # Cache the failure for the TTL too, so a dead endpoint doesn't add
            # a 10s timeout to every dashboard load.
            _catalog_cache = _catalog_cache or {}
            _catalog_fetched_at = now
        return _catalog_cache


def catalog() -> list[dict]:
    """Every offered model, Anthropic first, as dicts the API hands straight to
    the dashboard: id, label, provider, input/output $ per M tokens, whether the
    provider's key is configured, and whether it can do web research."""
    out: list[dict] = []
    anthropic_ready = bool(settings.anthropic_api_key)
    for model_id, (label, price_in, price_out) in ANTHROPIC_MODELS.items():
        out.append({
            "id": model_id,
            "label": label,
            "provider": PROVIDER_ANTHROPIC,
            "provider_label": "Anthropic",
            "input_per_mtok": price_in,
            "output_per_mtok": price_out,
            "web_search": True,
            "available": anthropic_ready,
        })

    live = _openrouter_live_prices()
    openrouter_ready = openrouter.is_configured()
    for model_id in openrouter_model_ids():
        fallback = _OPENROUTER_FALLBACK.get(model_id)
        entry = live.get(model_id) or {}
        label = entry.get("name") or (fallback[0] if fallback else model_id)
        price_in = entry.get("input")
        price_out = entry.get("output")
        if price_in is None and fallback:
            price_in = fallback[1]
        if price_out is None and fallback:
            price_out = fallback[2]
        out.append({
            "id": model_id,
            "label": _clean_or_label(label),
            "provider": PROVIDER_OPENROUTER,
            "provider_label": "OpenRouter",
            "input_per_mtok": price_in,
            "output_per_mtok": price_out,
            # No pause_turn tool loop on this path — see app/openrouter.py.
            "web_search": False,
            "available": openrouter_ready,
        })
    return out


def _clean_or_label(name: str) -> str:
    """OpenRouter names come through as "DeepSeek: DeepSeek V4 Flash 0423" —
    the vendor prefix is already shown as the provider, so drop it."""
    return name.split(": ", 1)[1] if ": " in name else name


def model_ids() -> set[str]:
    return {m["id"] for m in catalog()}


def is_allowed(model_id: str | None) -> bool:
    """Whether a model id came from the picker. Every request-supplied model
    goes through this before it reaches an API call."""
    if not model_id:
        return False
    if provider_for(model_id) == PROVIDER_ANTHROPIC:
        return model_id in ANTHROPIC_MODELS
    return model_id in set(openrouter_model_ids())


def default_model() -> str:
    """The model used when the caller didn't pick one: the dashboard-set default
    (app_settings.default_model) if it's still valid, else ANTHROPIC_MODEL."""
    try:
        with db.db_session() as conn:
            stored = db.get_setting(conn, DEFAULT_MODEL_SETTING_KEY)
    except Exception:
        log.warning("could not read default model from the DB", exc_info=True)
        stored = None
    if stored and is_allowed(stored):
        return stored
    return settings.anthropic_model


def set_default_model(model_id: str) -> None:
    if not is_allowed(model_id):
        raise ValueError(f"unknown model: {model_id}")
    with db.db_session() as conn:
        db.set_setting(conn, DEFAULT_MODEL_SETTING_KEY, model_id)


def resolve(model_id: str | None) -> str:
    """Validate a caller-supplied model, falling back to the default."""
    return model_id if is_allowed(model_id) else default_model()


def resolve_anthropic(model_id: str | None) -> str:
    """Same, but guaranteed to be an Anthropic model — for the paths that can't
    use OpenRouter at all (the Batch API in app/batch_gen.py, and the cheap
    thread translations in app/translator.py). If the current default is an
    OpenRouter model, this falls back to ANTHROPIC_MODEL rather than sending a
    `vendor/model` id to Anthropic and 404ing."""
    if model_id and is_allowed(model_id) and provider_for(model_id) == PROVIDER_ANTHROPIC:
        return model_id
    fallback = default_model()
    if provider_for(fallback) == PROVIDER_ANTHROPIC:
        return fallback
    return settings.anthropic_model
