"""On-demand English translation of a lead's thread, using a cheap model.

Draft *writing* stays on Sonnet (see app/drafter.py). This is only for letting
Andrew read a foreign-language thread in English on click — a low-stakes task, so
it runs on the cheapest Claude model (`ANTHROPIC_TRANSLATE_MODEL`, default
claude-haiku-4-5), tool-free, in a single call for the whole thread.
"""
import logging
import re

import anthropic

from app.config import settings

log = logging.getLogger("translator")

_SEG_RE = re.compile(r"\[\[(\d+)\]\]")

_SYSTEM = (
    "You are a translation engine. Translate each numbered segment into natural, "
    "faithful English. If a segment is already English, return it unchanged. "
    "Preserve meaning and tone; do not summarize, explain, or add commentary. "
    "Reproduce the exact [[n]] marker, each on its own line, immediately before "
    "that segment's translation, and output nothing else."
)


def _parse_segments(text: str, n: int, fallback: list[str]) -> list[str]:
    parts: dict[int, str] = {}
    matches = list(_SEG_RE.finditer(text))
    for idx, m in enumerate(matches):
        k = int(m.group(1))
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        parts[k] = text[start:end].strip()
    return [parts.get(i + 1) or fallback[i] for i in range(n)]


def translate_segments(texts: list[str]) -> list[str]:
    """Translate a list of plain-text segments to English in one call.

    Falls back to the original text for any segment the model doesn't return, and
    on any API error returns the inputs unchanged so the UI degrades gracefully.
    """
    items = [t if (t and t.strip()) else "" for t in texts]
    if not any(items):
        return list(items)

    numbered = "\n\n".join(f"[[{i + 1}]]\n{t}" for i, t in enumerate(items))
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.anthropic_translate_model,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[{"role": "user", "content": numbered}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return _parse_segments(text, len(items), fallback=items)
    except Exception:
        log.exception("thread translation failed")
        return list(items)


def translate_text(text: str) -> str:
    return translate_segments([text])[0]
