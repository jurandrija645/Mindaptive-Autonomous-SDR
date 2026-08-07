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
from app import writing_rules
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
    # This one also runs on our own drafts (the dashboard's English tab), which
    # carry the app's ** bold markers — dropping them would show Andrew an
    # English version with emphasis the outgoing message has and it doesn't.
    "Keep any **double asterisk** markers around the words that carry the same "
    "emphasis in English. "
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
        # Model comes from the "Translating the thread to English" row of the
        # dashboard's Models panel (falls back to ANTHROPIC_TRANSLATE_MODEL).
        # The instructions live in _SYSTEM, not in the model, so switching
        # providers here changes who executes them, not what they are.
        from app import llm, models_registry

        text, _ = llm.complete_for(
            models_registry.ROLE_TRANSLATE, _SYSTEM, numbered, max_tokens=4096
        )
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


# Shared by both localizers below. Every rule here comes from a message that
# actually went out badly.
#
# The one that forced this rewrite: "I'm closing this file" came back as "Ich
# schließe diese Datei" — which in German means closing a computer file, and
# reads as machine output. An English office idiom had been carried across word
# for word. The same message also used "Dir/deinem", the informal address, in
# first-contact outreach to a clinic, where German business writing takes "Sie".
#
# Both are the same underlying error: the model was translating instead of
# writing. So these prompts no longer ask for a translation at all.
_NATIVE_RULES = """\
You are a native {language} speaker and this is YOUR email. You are not
translating it — you are writing it.

Read the English, work out what the sender is actually doing (backing off,
nudging, offering something, closing the loop), then write that in {language}
the way you would if the English did not exist. The reader must never be able to
tell it started in another language.

Hard rules:
- NEVER go word for word. If your {language} sentence has the same shape and
  word order as the English one, you translated it. Rewrite it.
- Idioms and figures of speech almost never survive. "Closing this file" is an
  English office idiom; rendering it literally in {language} describes a
  computer file and reads like a machine wrote it. Either use the equivalent
  {language} expression a native would reach for, or drop the figure of speech
  and say the plain thing.
- Formality: match what the thread is already doing. In languages with a formal
  and an informal address (German Sie/du, French vous/tu, Spanish usted/tú,
  Dutch u/je, Italian Lei/tu, Polish Pan-Pani/ty), business outreach to someone
  the sender has not met takes the FORMAL form, unless the recipient wrote to
  them informally first. Getting this wrong is the fastest way to look foreign.
- Keep every concrete detail exactly as given: names, company names, numbers,
  dates, URLs and links. Do not translate a proper noun.
- Keep the same meaning, the same intent and roughly the same length. Do not add
  information, do not remove a point, do not invent a new offer.
- Read your output back as that native speaker. If you would not type that
  sentence to a real customer, it is wrong — rewrite it before answering.
"""


_LOCALIZE_SYSTEM_TEMPLATE = (
    _NATIVE_RULES
    + "\nThis is a full outreach email. Preserve the paragraph structure and any "
    "call to action. A signature is appended separately after your output, so do "
    "not add one — write only the body, whatever its length, sender or content. "
    "Output only the email body: no subject line, no commentary and no questions "
    "back. If anything about it looks unusual, write it as-is rather than "
    "asking.\n\n" + writing_rules.short_rules()
)


_QUICK_LOCALIZE_SYSTEM_TEMPLATE = (
    _NATIVE_RULES
    + "\nThis is one short, pre-approved follow-up line. Do not add anything and "
    "do not change what it says — but the WORDING is yours to choose freely, and "
    "it must sound like something a native speaker typed quickly, not like a "
    "rendering of an English sentence. Output only the message, nothing else.\n\n"
    + writing_rules.short_rules()
)


def localize_quick_text(
    english_text: str, target_language_code: str | None, model: str | None = None
) -> str:
    """Localize a quick-pick canned follow-up into the lead's language.

    Skips the full drafter pipeline (system prompt, knowledge base, tools) —
    the wording is already fixed and pre-approved, so one small call is enough.

    It runs on the DRAFTING model, not `anthropic_translate_model`, even though
    it is one sentence. This is an outgoing message a real lead reads, and Haiku
    produced "Ich schließe diese Datei" for "I'm closing this file" — a literal
    rendering that means closing a computer file. The cheap model is for
    reading-comprehension translations of what leads send us; anything we send
    them goes through the same model that writes the drafts (see
    localize_draft, which already made this call for the same reason).

    Which capable model is now Andrew's choice, not a constant: it runs on the
    "Translating templates" role, which by default follows the drafting model,
    and `model` (the dashboard's Generate dropdown) overrides both — so picking
    a model there moves templates with it, as you'd expect from one visible
    control."""
    if not target_language_code or target_language_code.lower() == "en":
        return english_text
    from app import llm, models_registry

    system = _QUICK_LOCALIZE_SYSTEM_TEMPLATE.format(language=language_name(target_language_code))
    try:
        text, _ = llm.complete_for(
            models_registry.ROLE_TEMPLATE, system, english_text,
            max_tokens=1024, model=model,
        )
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
    affects what the lead receives.

    Honours an OpenRouter pick too — this runs off the same dropdown as
    generate/regenerate, so the model Andrew chose there has to work here or
    "Apply to draft" would 404 on a `vendor/model` id."""
    # Imported here rather than at module scope: models_registry imports db,
    # which app/campaign_* modules import alongside translator — a top-level
    # import would make that a cycle.
    from app import llm, models_registry

    system = _LOCALIZE_SYSTEM_TEMPLATE.format(language=language_name(target_language_code))
    text, _ = llm.complete_for(
        models_registry.ROLE_DRAFT, system, english_text, max_tokens=2048, model=model
    )
    return text.strip() or english_text
