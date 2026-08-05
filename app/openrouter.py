"""OpenRouter client — the second model provider behind the dashboard's model
picker (see app/models_registry.py for the catalog and app/drafter.py for where
a draft is routed to it).

OpenRouter speaks the OpenAI chat-completions shape, not Anthropic's Messages
API, so this is plain httpx rather than an SDK: one POST, one string back. Two
things the Anthropic path has are deliberately absent here:

- **No web search/fetch tools.** OpenRouter exposes web access as a per-model
  `:online` plugin with its own pricing and no pause_turn loop, so drafts on an
  OpenRouter model are written from the thread + stored research only
  (`use_web_search=False` is forced in drafter.generate_draft). Research a lead
  once on an Anthropic model and every later OpenRouter draft reuses it.
- **No prompt caching.** Anthropic bills the ~12.5k-token system prompt at 0.1x
  on a cache read; OpenRouter's caching is provider-specific and not requestable
  through this endpoint, so every OpenRouter draft pays full input price. That is
  still far cheaper on a model like DeepSeek V4 Flash ($0.14/M in) than an
  uncached Sonnet call — but it's why the picker shows the real per-token price
  rather than pretending the two providers cost the same per draft.
"""

import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"

# Drafts run the full system prompt + thread through a single call and can take
# a while on a reasoning model; the interactive generate path already runs in a
# background thread (see candidates.generate_for_lead_in_background), so a long
# timeout here costs nothing but avoids killing a draft mid-write.
REQUEST_TIMEOUT = 180.0
# Catalog fetch is a small GET on the dashboard's critical path — keep it short
# and fall back to the hardcoded prices if OpenRouter is slow.
CATALOG_TIMEOUT = 10.0


class OpenRouterError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.openrouter_api_key)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # OpenRouter uses these purely for its own dashboard attribution.
        "HTTP-Referer": settings.public_base_url or "http://localhost:8080",
        "X-Title": "Mindaptive Responder",
    }


def fetch_catalog() -> dict[str, dict]:
    """`{model_id: {name, input, output, context}}` — prices are per MILLION
    tokens (OpenRouter returns per-token strings, converted here).

    Public endpoint: no key needed, so the picker can still show live prices
    before OPENROUTER_API_KEY is set. Raises on failure; the caller
    (models_registry) falls back to its hardcoded prices."""
    resp = httpx.get(f"{BASE_URL}/models", timeout=CATALOG_TIMEOUT)
    resp.raise_for_status()
    out: dict[str, dict] = {}
    for entry in resp.json().get("data") or []:
        model_id = entry.get("id")
        if not model_id:
            continue
        pricing = entry.get("pricing") or {}
        out[model_id] = {
            "name": entry.get("name") or model_id,
            "input": _per_million(pricing.get("prompt")),
            "output": _per_million(pricing.get("completion")),
            "context": entry.get("context_length"),
        }
    return out


def _per_million(raw) -> float | None:
    try:
        return round(float(raw) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def complete(model: str, system: str, user_message: str, max_tokens: int = 4096) -> str:
    """One chat completion, returned as plain text."""
    if not is_configured():
        raise OpenRouterError(
            "OPENROUTER_API_KEY is not set — pick an Anthropic model, or add the key to .env."
        )
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    }
    resp = httpx.post(
        f"{BASE_URL}/chat/completions",
        headers=_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise OpenRouterError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    # OpenRouter surfaces upstream provider failures as a 200 with an `error`
    # object instead of `choices` — check before indexing.
    if data.get("error"):
        raise OpenRouterError(f"OpenRouter error: {data['error']}")
    choices = data.get("choices") or []
    if not choices:
        raise OpenRouterError(f"OpenRouter returned no choices: {str(data)[:500]}")
    message = choices[0].get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        # A reasoning model that spent the whole budget thinking returns empty
        # content with the reasoning field populated — say so plainly rather
        # than storing a blank draft.
        if message.get("reasoning"):
            raise OpenRouterError(
                f"{model} returned only reasoning and no answer — "
                "the token budget ran out before it wrote the draft."
            )
        raise OpenRouterError(f"{model} returned an empty response.")
    return text
