"""On-demand English translation of a lead's thread, using a cheap model.

Draft *writing* stays on Sonnet (see app/drafter.py). This is only for letting
Andrew read a foreign-language thread in English on click — a low-stakes task, so
it runs on the cheapest Claude model (`ANTHROPIC_TRANSLATE_MODEL`, default
claude-haiku-4-5), tool-free, in a single call for the whole thread.
"""
import hashlib
import logging
import re

import anthropic
from langdetect import DetectorFactory, detect

from app import db
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


def source_hash(text: str) -> str:
    """Cache key for a translation: sha256 of the trimmed plain-text source. A
    sent email is immutable, so this key is stable forever."""
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def translate_segments_cached(conn, texts: list[str]) -> list[str]:
    """Cache-aware sibling of translate_segments. For each segment:
      - empty/whitespace → returned as-is (never hashed or stored);
      - already in the DB cache (by source_hash) → served free;
      - already English (langdetect) → returned unchanged with NO API call, and cached;
      - otherwise → translated (all such misses in ONE translate_segments call) and cached.
    A given message body is thus only ever sent to Claude once, ever.
    """
    n = len(texts)
    results: list[str | None] = [None] * n
    hashes: dict[int, str] = {}
    for i, t in enumerate(texts):
        if not (t and t.strip()):
            results[i] = t
            continue
        hashes[i] = source_hash(t)

    if not hashes:
        return [r if r is not None else "" for r in results]

    cached = db.get_cached_translations(conn, list(dict.fromkeys(hashes.values())))

    # Collect the genuine misses, deduped by hash so an identical message that
    # appears twice is only ever sent to the model once.
    missing: dict[str, str] = {}  # hash -> representative source text
    for i, h in hashes.items():
        if h in cached:
            results[i] = cached[h]
        elif detect_language(texts[i]) == "en":
            # Already English — no call needed; echo it back and remember that.
            results[i] = texts[i]
            db.put_cached_translation(conn, h, texts[i])
            cached[h] = texts[i]
        elif h not in missing:
            missing[h] = texts[i]

    if missing:
        miss_hashes = list(missing.keys())
        englishes = translate_segments([missing[h] for h in miss_hashes])
        for h, english in zip(miss_hashes, englishes):
            cached[h] = english
            db.put_cached_translation(conn, h, english)

    # Fill every index (including duplicates) from the now-complete cache map.
    for i, h in hashes.items():
        if results[i] is None:
            results[i] = cached.get(h, texts[i])

    return [r if r is not None else "" for r in results]


_LOCALIZE_SYSTEM_TEMPLATE = (
    "Rewrite the email below in {language} as a natural, native email a real "
    "business owner would actually send — not a stiff literal translation. Keep "
    "the tone brief, direct, and peer-to-peer: no corporate fluff, no "
    "over-formality, no pricing. Preserve the paragraph structure and every "
    "concrete detail (names, numbers, links, any call-to-action present). A "
    "signature is appended separately after your output, so do not add one — "
    "only rewrite what's given, whatever its length, sender, or content. Output "
    "only the rewritten email body: no subject line, no commentary, and no "
    "questions back — if anything about the email looks unusual, translate it "
    "as-is rather than asking about it."
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


def localize_draft(english_text: str, target_language_code: str | None, model: str | None = None) -> str:
    """Turn Andrew's English edit into the real, native-language draft that gets
    sent. This is the OUTGOING message, so — unlike the cheap reading-comprehension
    translations elsewhere in this module — it runs on the drafting model Andrew
    picked in the dashboard's model dropdown (falling back to the default
    drafting model), not the cheap translate model: quality here directly
    affects what the lead receives."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    system = _LOCALIZE_SYSTEM_TEMPLATE.format(language=language_name(target_language_code))
    resp = client.messages.create(
        model=model or settings.anthropic_model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": english_text}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text.strip() or english_text
