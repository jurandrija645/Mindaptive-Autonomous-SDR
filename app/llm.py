"""One call path for every non-drafter LLM request in the app.

Before this, five places built their own `anthropic.Anthropic()` client with
their own model string, which is why the model picker could only ever reach the
drafter: making translation or campaign analysis switchable meant editing each
of them. They all go through `complete()` now, so a new provider or a new
per-task model choice is a change here and nowhere else.

(`app/drafter.py` keeps its own Anthropic call: it needs the web_search/web_fetch
tool loop, pause_turn continuations and two cache_control breakpoints, none of
which the other callers want. It routes to OpenRouter through the same
`app/openrouter.py` this module uses.)

Provider-specific parameters are applied by capability, not by hope:
`thinking` and `output_config.effort` are Anthropic-only AND unsupported on
Haiku 4.5 (adaptive thinking needs a 4.6+ model, and `effort` 400s on Haiku), so
they are attached only when the resolved model actually accepts them. Sending
them blindly is what would break the moment someone picked Haiku for campaign
analysis.
"""

import logging

import anthropic

from app import models_registry, openrouter
from app.config import settings

log = logging.getLogger(__name__)


def complete(
    model: str,
    system: str | None,
    user_message: str,
    max_tokens: int = 4096,
    effort: str | None = None,
    stream: bool = False,
) -> str:
    """One completion, in and out as plain text.

    `effort` is a hint, not a guarantee — it is dropped for providers and models
    that don't support it rather than raising, so a task's model can be switched
    freely without its call site having to know what the new model supports.
    `stream` likewise only affects the Anthropic path, where a large max_tokens
    would otherwise risk an HTTP timeout.
    """
    if models_registry.provider_for(model) == models_registry.PROVIDER_OPENROUTER:
        return openrouter.complete(
            model, system or "", user_message, max_tokens=max_tokens
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": user_message}],
    }
    if system:
        kwargs["system"] = system
    if models_registry.supports_effort(model):
        kwargs["thinking"] = {"type": "adaptive"}
        if effort:
            kwargs["output_config"] = {"effort": effort}

    if stream:
        with client.messages.stream(**kwargs) as s:
            response = s.get_final_message()
    else:
        response = client.messages.create(**kwargs)
    return "".join(b.text for b in response.content if b.type == "text").strip()


def complete_for(
    role: str,
    system: str | None,
    user_message: str,
    max_tokens: int = 4096,
    effort: str | None = None,
    stream: bool = False,
    model: str | None = None,
) -> tuple[str, str]:
    """`complete()` keyed by task role instead of model id — the model comes from
    whatever that role is set to in the dashboard's Models panel (see
    models_registry.model_for). An explicit `model` still wins, for the paths
    that carry a per-request override.

    Returns `(text, model_used)` so callers can record which model actually ran.
    """
    resolved = models_registry.resolve(model) if model else models_registry.model_for(role)
    return complete(resolved, system, user_message, max_tokens, effort, stream), resolved
