"""On-demand English translation of a lead's thread, using a cheap model.

Draft *writing* stays on Sonnet (see app/drafter.py). This is only for letting
Andrew read a foreign-language thread in English on click — a low-stakes task, so
it runs on the cheapest Claude model (`ANTHROPIC_TRANSLATE_MODEL`, default
claude-haiku-4-5), tool-free, in a single call for the whole thread.
"""
import logging
import re

import anthropic
from langdetect import DetectorFactory, detect

from app.config import settings

log = logging.getLogger("translator")

# Deterministic language detection (langdetect is randomised by default).
DetectorFactory.seed = 0

_SEG_RE = re.compile(r"\[\[(\d+)\]\]")

LANG_NAMES = {
    "en": "English", "it": "Italian", "nl": "Dutch", "de": "German", "fr": "French",
    "es": "Spanish", "pt": "Portuguese", "pl": "Polish", "sv": "Swedish", "da": "Danish",
    "no": "Norwegian", "fi": "Finnish", "ro": "Romanian", "cs": "Czech", "hu": "Hungarian",
    "el": "Greek", "tr": "Turkish", "ru": "Russian", "uk": "Ukrainian", "hr": "Croatian",
    "sk": "Slovak", "sl": "Slovenian", "bg": "Bulgarian", "lt": "Lithuanian", "lv": "Latvian",
    "et": "Estonian",
}


def language_name(code: str | None) -> str:
    if not code:
        return "the recipient's language"
    return LANG_NAMES.get(code.lower(), code)


def detect_language(text: str) -> str | None:
    text = (text or "").strip()
    if len(text) < 20:
        return None
    try:
        return detect(text)
    except Exception:
        return None

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


_LOCALIZE_SYSTEM_TEMPLATE = (
    "You are localizing a cold-outreach email. Andrew wrote the draft below in "
    "English; rewrite it in {language} as a natural, native email a real business "
    "owner would actually send — not a stiff literal translation. Keep the tone "
    "brief, direct, and peer-to-peer: no corporate fluff, no over-formality, no "
    "pricing. Preserve the paragraph structure and every concrete detail (names, "
    "numbers, links, the call-to-action). A signature is appended separately after "
    "your output, so do not add one — only rewrite what's given. Output only the "
    "rewritten email body: no subject line, no commentary."
)


_QUICK_LOCALIZE_SYSTEM_TEMPLATE = (
    "Translate this short cold-outreach follow-up message into {language}. It's "
    "already a fixed, approved bit of casual wording, so just translate it "
    "naturally, the way a real person typing quickly would say it. Do not "
    "rewrite, expand, or add anything. Preserve names and links exactly as "
    "given. Output only the translated message, nothing else."
)


def localize_quick_text(english_text: str, target_language_code: str | None) -> str:
    """Cheap (Haiku), fixed-wording localization for the quick-pick canned
    follow-ups — these are pre-approved snippets, not something Claude is
    drafting, so this skips the full drafter pipeline (system prompt,
    knowledge base, tools) entirely and just translates in one small call."""
    if not target_language_code or target_language_code.lower() == "en":
        return english_text
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    system = _QUICK_LOCALIZE_SYSTEM_TEMPLATE.format(language=language_name(target_language_code))
    try:
        resp = client.messages.create(
            model=settings.anthropic_translate_model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": english_text}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text.strip() or english_text
    except Exception:
        log.exception("quick-pick localization failed")
        return english_text


def localize_draft(english_text: str, target_language_code: str | None) -> str:
    """Turn Andrew's English edit into the real, native-language draft that gets
    sent. This is the OUTGOING message, so — unlike the cheap reading-comprehension
    translations elsewhere in this module — it runs on the drafting model
    (Sonnet), not Haiku: quality here directly affects what the lead receives."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    system = _LOCALIZE_SYSTEM_TEMPLATE.format(language=language_name(target_language_code))
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": english_text}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text.strip() or english_text
