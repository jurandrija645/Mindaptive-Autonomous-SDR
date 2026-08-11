"""Which language we write to a lead in — one rule, one place.

Three sources know something about a lead's language, and they were consulted in
a different order by every path that needed one. That is what made translation
look random: the scan asked Smartlead's per-lead field first, a quick template
asked the cached `leads_state.language` column first, a generated draft was
never told anything and had to guess from the thread, and the localizers treat
"en" and "no idea" identically — both mean *send the English*.

Measured against the live API on 2026-08-11, across the 336 leads in the local
database: 186 stored languages matched Smartlead's own per-lead field, **16 did
not**, and 11 of those 16 said `en` for a lead whose entire thread — their
replies and our sends — was German, Dutch, Swedish, Slovak or Catalan. Every
template sent to one of them went out in English at full confidence. So the
cached column is exactly the thing that must not be trusted first.

The order below is that finding plus what the app already believed:

1. **Smartlead's own per-lead language field** (`language_code` / `targetLanguage`
   — see `smartlead._LANGUAGE_FIELDS`). Per-lead campaign data, not a guess, and
   it is the language the whole sequence was merged in. It agreed with the
   thread in every one of the 16 disagreements above.
2. **The thread itself**, lead's replies before our own sends. 39% of the
   account's leads carry no language field at all (every B2B campaign, Solar
   Panel - Germany, the HVAC USA runs) — for them the thread is all there is,
   and it is enough: Smartlead merged the sequence in the lead's own language,
   so what we mailed them says what they read.

   This does reverse one earlier promise. `thread_language` used to rank the
   lead's own replies above everything, on the grounds that a Danish lead who
   answers in English wants English back. That reads well and mails badly: it
   is a langdetect call on whatever they last typed, so a two-line English
   out-of-office, a quoted signature or a polite "Thanks!" flips a German
   clinic to English — the exact failure being fixed here, and English is the
   one wrong answer that looks completely normal on the way out. Their replies
   still decide it whenever Smartlead has no field, which is most of the leads
   that ever had this problem. To answer a bilingual lead in English anyway,
   regenerate with a steering note.
3. **The cached `leads_state.language` column**, last: a snapshot of 1 or 2 taken
   whenever the lead was last scanned, kept only so a lead whose thread we can't
   read still has an answer.

`resolve` returns the source alongside the code so a caller can say *why* a
message is going out in English instead of silently sending it.
"""

import logging

from app import smartlead
from app.email_clean import to_plain_text
from app.translator import detect_language

log = logging.getLogger(__name__)

# Where a resolved code came from, most trusted first.
SOURCE_FIELD = "smartlead"   # Smartlead's per-lead language custom field
SOURCE_REPLY = "reply"       # detected in the lead's own writing
SOURCE_SENT = "sent"         # detected in an email we sent them
SOURCE_STORED = "stored"     # the cached leads_state.language column
SOURCE_NONE = "none"         # nothing anywhere says what this lead reads


def smartlead_field(campaign_id: int, lead_id: int) -> str | None:
    """Smartlead's own per-lead language field, fetched live.

    For the callers that build their lead dict out of `leads_state` — the
    dashboard's Generate and template buttons, the webhook — which used to pass
    the cached `language` column as if it were this field. It isn't: the column
    is a snapshot written by the last scan that reached this lead, and `resolve`
    ranks this field first, so handing it the cache would put the stale value
    straight back on top.

    Fail-soft: a Smartlead hiccup returns None and `resolve` falls through to
    the thread, which is the same evidence it always had. One small GET on paths
    that already fetch a thread and then call a model.
    """
    try:
        raw = smartlead.get_lead(lead_id)
    except Exception:
        log.warning("could not fetch lead %s for its language field", lead_id, exc_info=True)
        return None
    if not raw:
        return None
    return smartlead.normalize_lead(raw, campaign_id).get("language_code")


def _detect_in(thread, kind: str) -> str | None:
    """Language of the most recent message of `kind` we can actually read.

    Newest first, and `to_plain_text` drops the quoted history, so a German
    message with our English signature under it still reads as German.
    Detection needs 20+ characters (see translator.detect_language), so a
    two-word "Thanks!" is skipped rather than guessed at.
    """
    for msg in reversed(thread or ()):
        if msg.kind == kind:
            code = detect_language(to_plain_text(msg.body))
            if code:
                return code
    return None


def thread_language(thread) -> str | None:
    """Language of the conversation: the lead's own replies first, then our
    sends. Local (langdetect), so it costs nothing and can be used at the last
    moment before a message goes out."""
    return _detect_in(thread, "reply") or _detect_in(thread, "sent")


def resolve(
    thread=None,
    lead: dict | None = None,
    lead_row=None,
    use_detection: bool = True,
) -> tuple[str | None, str]:
    """`(2-letter code, source)` for this lead — see the module docstring for
    why the sources rank the way they do.

    Every argument is optional, because the callers hold different things: the
    scan has a fresh Smartlead lead, the send paths have a thread, the webhook
    has neither. `use_detection=False` skips the langdetect steps for clients
    that mail in one language only (`DETECT_LANGUAGE`).
    """
    code = str((lead or {}).get("language_code") or "").strip().lower()[:2]
    if code.isalpha() and len(code) == 2:
        return code, SOURCE_FIELD

    if use_detection and thread:
        code = _detect_in(thread, "reply")
        if code:
            return code, SOURCE_REPLY
        code = _detect_in(thread, "sent")
        if code:
            return code, SOURCE_SENT

    stored = None
    if lead_row is not None:
        try:
            stored = lead_row["language"]
        except (KeyError, IndexError):
            stored = None
    if stored:
        return str(stored).strip().lower()[:2], SOURCE_STORED

    return None, SOURCE_NONE
