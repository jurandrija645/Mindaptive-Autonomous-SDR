"""What the campaign's messages actually SAY — the missing half of the analysis.

Everything in `campaign_analytics.py` measures slots by their token: `CTA1`
earned 20 replies, `Icebreaker2` leans above baseline. That is unreadable. You
cannot decide to keep a CTA you have never read, and a report that ranks
`Offer1` over `Offer2` tells you nothing you can act on.

The text exists — it is just scattered. Smartlead stores the *template*
(`{{CTA1}}` inside an HTML body) on the sequence, and the *values* per lead in
the leads-export `custom_fields` blob. This module joins the two back together
so every variant can be shown as the whole email a human would read, and every
slot as the sentence it actually inserts.

Three problems it has to solve, all of them real in this data:

1. **Languages.** EU campaigns mail the same slot in 8+ languages — the
   `subjectLine1` of one lead is "client inquiry process" and of the next
   "vraag over het boekingsproces". Andrew reads English, and comparing copy
   across languages is meaningless anyway. So each slot is resolved to its most
   common *English* value; a campaign with no English at all falls back to the
   dominant language plus a cached Claude translation.
2. **Fixed copy vs per-lead personalization.** `subjectLine1` is one sentence
   reused across hundreds of leads; an icebreaker may be written per lead. A
   single "representative value" is honest for the first and a lie for the
   second, so `personalized` is measured (distinct values / leads) and carried
   through to the UI, which then shows examples instead of one value.
3. **HTML.** Bodies are email HTML. Substitution happens on the HTML, and the
   result is flattened to text afterwards, so slot values containing their own
   markup survive.
"""

import json
import logging
import re
from collections import Counter, defaultdict

from app import db, writing_rules
from app.campaign_analytics import slot_role
from app.email_clean import to_plain_text

log = logging.getLogger("campaign_copy")

_SLOT_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

# How many leads to read when resolving slot text. The values repeat heavily
# (hundreds of leads share one subject line), so a sample settles the ranking
# long before the full 5k-lead export would — and each row carries a ~2 KB JSON
# blob that has to be parsed.
_SAMPLE_LEADS = 1500

# Above this share of distinct values the slot is per-lead copy, not a fixed
# block: 400 leads with 380 different icebreakers is personalization.
#
# 0.25 rather than something stricter because these slots are usually a fixed
# sentence with a personalized tail ("...and came across Dr. Theodor R"), which
# lands around 0.44 on campaign 3640877 — while genuinely fixed copy like
# `Pitch1` sits at 0.003, so the two are nowhere near each other.
_PERSONALIZED_RATIO = 0.25
_PERSONALIZED_MIN_DISTINCT = 12


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------

# Function words are the giveaway: content words drift between languages but
# "the / your / with" versus "de / uw / met" separates English from the Germanic
# and Romance languages this account mails cleanly enough for picking a sample.
_EN_MARKERS = {
    "the", "and", "your", "you", "for", "with", "that", "this", "have", "are",
    "how", "what", "we", "our", "is", "to", "of", "in", "on", "it", "they",
    "from", "would", "can", "get", "just", "about", "if", "who", "when", "not",
    "most", "more", "their", "there", "was", "want", "need", "into", "than",
}
_FOREIGN_MARKERS = {
    # nl
    "de", "het", "een", "van", "voor", "met", "op", "je", "uw", "wij", "niet",
    "zijn", "aan", "die", "dat", "ook", "maar", "over", "bij", "worden",
    # de
    "und", "der", "die", "das", "für", "mit", "sie", "ist", "auf", "nicht",
    "ein", "eine", "wir", "ihre", "ihr", "zu", "den", "dem", "oder", "auch",
    # fr
    "les", "des", "une", "pour", "avec", "vous", "nous", "est", "que", "dans",
    "sur", "pas", "votre", "plus", "leur", "sont", "ce", "au", "du", "aux",
    # es / pt / it
    "los", "las", "para", "con", "usted", "por", "como", "más", "sua", "seu",
    "não", "uma", "che", "per", "sono", "della", "gli", "sul",
    # scandi / fi / pl / cz
    "och", "att", "för", "att", "inte", "vi", "er", "til", "af", "ikke",
    "ja", "on", "ei", "sekä", "oraz", "jest", "nie", "się", "pro", "jak",
}
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def english_score(text: str) -> float:
    """-1 (clearly not English) .. 1 (clearly English), 0 for "no idea".

    Scored on function-word share rather than a language-detection dependency:
    the strings here are often 4-8 words long, where the heavyweight detectors
    are no better than this and pull in a package for it."""
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    if not words:
        return 0.0
    english = sum(1 for w in words if w in _EN_MARKERS)
    foreign = sum(1 for w in words if w in _FOREIGN_MARKERS and w not in _EN_MARKERS)
    hits = english + foreign
    if not hits:
        # No function word matched either way. Very short strings land here;
        # non-ASCII letters are still evidence against English.
        return -0.3 if re.search(r"[äöüßøåæçñéèêàùìíóú]", text or "", re.IGNORECASE) else 0.0
    return (english - foreign) / hits


def looks_english(text: str) -> bool:
    return english_score(text) > 0.2


# ---------------------------------------------------------------------------
# Resolving what each slot says
# ---------------------------------------------------------------------------

def _campaign_tokens(conn, campaign_id: int) -> dict[str, str]:
    """Every token used by any variant of this campaign -> its role."""
    tokens: dict[str, str] = {}
    for row in db.list_campaign_variants(conn, campaign_id):
        for token in json.loads(row["slots_json"] or "[]"):
            tokens[token] = slot_role(token)
    return tokens


def resolve_slot_texts(conn, campaign_id: int) -> list[dict]:
    """Read the lead export and work out, per token, what it actually says.

    Preference order for the representative value: most common English value,
    then most common value of any language. "Most common" rather than "first
    seen" matters — the export is not ordered, and the first row could easily be
    the one Finnish lead."""
    tokens = _campaign_tokens(conn, campaign_id)
    if not tokens:
        return []

    rows = conn.execute(
        """SELECT custom_fields_json FROM campaign_lead_vars
             WHERE campaign_id = ? AND custom_fields_json IS NOT NULL
             LIMIT ?""",
        (campaign_id, _SAMPLE_LEADS),
    ).fetchall()

    counts: dict[str, Counter] = defaultdict(Counter)
    parsed: list[dict] = []
    for row in rows:
        try:
            fields = json.loads(row["custom_fields_json"] or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(fields, dict):
            continue
        parsed.append(fields)
        for token in tokens:
            value = fields.get(token)
            if isinstance(value, str) and value.strip():
                counts[token][value.strip()] += 1

    reference = _reference_lead(parsed, tokens)

    out = []
    for token, role in sorted(tokens.items()):
        values = counts.get(token)
        if not values:
            continue
        total = sum(values.values())
        distinct = len(values)
        personalized = (
            distinct >= _PERSONALIZED_MIN_DISTINCT
            and distinct / total >= _PERSONALIZED_RATIO
        )

        english = [(value, n) for value, n in values.most_common() if looks_english(value)]
        if english:
            best, lang = english[0][0], "en"
        else:
            best, lang = values.most_common(1)[0][0], "other"

        # A per-lead slot has no "most common" value worth showing, and picking
        # each one independently produced an incoherent email: the subject line
        # was "the invisalign bit" over a body about dementia care, because the
        # two came from different leads. Personalized slots therefore all come
        # from one reference lead, so the rendered email reads as one message.
        if personalized:
            from_reference = (reference.get(token) or "").strip()
            if from_reference:
                best = from_reference
                lang = "en" if looks_english(from_reference) else lang

        # Examples only earn their space when the value varies per lead; for
        # fixed copy the single value already is the whole story.
        examples = [value for value, _ in (english or values.most_common())[:4]]

        out.append(
            {
                "campaign_id": campaign_id,
                "token": token,
                "role": role,
                "text": _tidy(best),
                # Already English -> the translation column is just a copy, so
                # the translate pass has nothing to do and costs nothing.
                "text_en": _tidy(best) if lang == "en" else None,
                "lang": lang,
                "personalized": 1 if personalized else 0,
                "distinct_values": distinct,
                "examples_json": json.dumps(
                    [_tidy(e) for e in examples] if personalized else [], ensure_ascii=False
                ),
                "updated_at": db.now_iso(),
            }
        )
    return out


def _reference_lead(leads: list[dict], tokens: dict[str, str]) -> dict:
    """One lead whose variables stand in for the per-lead slots everywhere.

    Picked for being both English and complete: an English lead missing half the
    fields would leave holes in the rendered email, and a complete German one
    would put German sentences into an English report."""
    best: dict = {}
    best_score = float("-inf")
    for fields in leads:
        present = 0
        score = 0.0
        for token in tokens:
            value = fields.get(token)
            if isinstance(value, str) and value.strip():
                present += 1
                score += english_score(value)
        if not present:
            continue
        # Completeness counts as much as language: a missing slot is a hole in
        # the email, so both are weighted rather than one used as a tiebreak.
        total = score + present * 0.5
        if total > best_score:
            best, best_score = fields, total
    return best


def _tidy(value: str) -> str:
    """Slot values arrive with stray markup and whitespace from the spreadsheet."""
    text = to_plain_text(value) if "<" in value else value
    return re.sub(r"[ \t]+", " ", text).strip()


def sync_slot_texts(conn, campaign_id: int) -> int:
    rows = resolve_slot_texts(conn, campaign_id)
    return db.upsert_campaign_slot_texts(conn, campaign_id, rows)


def slot_text_map(conn, campaign_id: int) -> dict[str, dict]:
    """token -> {text, text_en, display, lang, personalized, examples}.

    `display` is the one field the UI and the prompts should read: English when
    we have it, the original otherwise. Nothing downstream should have to decide
    that again."""
    out = {}
    for row in db.list_campaign_slot_texts(conn, campaign_id):
        text = row["text"] or ""
        text_en = row["text_en"] or ""
        try:
            examples = json.loads(row["examples_json"] or "[]")
        except ValueError:
            examples = []
        out[row["token"]] = {
            "token": row["token"],
            "role": row["role"],
            "text": text,
            "text_en": text_en or None,
            "display": text_en or text,
            "lang": row["lang"],
            "translated": bool(text_en and row["lang"] != "en"),
            "personalized": bool(row["personalized"]),
            "distinct_values": row["distinct_values"],
            "examples": examples,
        }
    return out


# ---------------------------------------------------------------------------
# Rendering a whole email
# ---------------------------------------------------------------------------

# Tokens that carry per-lead data rather than copy under test. Rendering the
# sample lead's real name here would read as if the email were about that one
# company; a labelled placeholder keeps it obvious what varies.
_PLACEHOLDER_ROLES = {"other"}


def _placeholder(token: str) -> str:
    pretty = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", token).replace("_", " ").strip().lower()
    return "{" + pretty + "}"


def render_email(template: str | None, texts: dict[str, dict]) -> str:
    """Substitute every {{token}} with what it says, then flatten to plain text.

    Substitution happens on the raw HTML so a slot value carrying its own markup
    is flattened together with the template rather than escaped into view."""
    if not template:
        return ""

    def replace(match: re.Match) -> str:
        token = match.group(1)
        entry = texts.get(token)
        if not entry:
            return _placeholder(token)
        if entry["role"] in _PLACEHOLDER_ROLES:
            return _placeholder(token)
        # `display` for a personalized slot is the reference lead's own value
        # (see _reference_lead), so every personalized slot in this email comes
        # from the same lead and the message reads as one coherent email.
        return entry["display"] or _placeholder(token)

    return to_plain_text(_SLOT_RE.sub(replace, template))


def variant_emails(conn, campaign_id: int) -> dict[int, dict]:
    """Every variant as a readable English email plus its slot breakdown.

    The breakdown is what makes the email actionable: you read the message, then
    see which sentence in it belongs to `CTA1` — the thing the numbers rank."""
    texts = slot_text_map(conn, campaign_id)
    out: dict[int, dict] = {}
    for row in db.list_campaign_variants(conn, campaign_id):
        slots = json.loads(row["slots_json"] or "[]")
        breakdown = []
        for token in slots:
            entry = texts.get(token)
            role = entry["role"] if entry else slot_role(token)
            if role == "other":
                continue
            breakdown.append(
                {
                    "token": token,
                    "role": role,
                    "text": (entry or {}).get("display") or "",
                    "personalized": bool((entry or {}).get("personalized")),
                    "examples": (entry or {}).get("examples") or [],
                    "translated": bool((entry or {}).get("translated")),
                }
            )
        out[row["seq_variant_id"]] = {
            "seq_variant_id": row["seq_variant_id"],
            "seq_number": row["seq_number"],
            "variant_label": row["variant_label"],
            "subject": render_email(row["subject_template"], texts),
            "body": render_email(row["body_template"], texts),
            "slot_breakdown": breakdown,
            "any_translated": any(item["translated"] for item in breakdown),
        }
    return out


# ---------------------------------------------------------------------------
# Translation (only for campaigns that ran in no English at all)
# ---------------------------------------------------------------------------

_TRANSLATE_PROMPT = """\
Translate each of these cold-email fragments into natural English. They are
pieces of a sales email — a subject line, an opening line, an offer, a call to
action — so translate them the way a native English copywriter would write that
fragment, not word-for-word.

Keep any {{placeholder}} tokens exactly as they are. Keep the length and the
register of the original: a curt 5-word subject line stays a curt 5-word subject
line.

{style}

Return ONLY a JSON object mapping each id to its English text, no prose.

```json
{items}
```
"""


def translate_slot_texts(conn, campaign_id: int, model: str | None = None, progress=None) -> int:
    """Fill `text_en` for slots whose value is not English.

    Runs once per distinct value and is cached, so an all-English campaign
    (every US campaign) never makes this call at all, and an EU campaign pays
    for it on the first analysis only."""
    pending = [
        {"id": row["token"], "text": row["text"]}
        for row in db.list_campaign_slot_texts(conn, campaign_id)
        if not row["text_en"] and (row["text"] or "").strip()
    ]
    if not pending:
        return 0
    if progress:
        progress(f"Translating {len(pending)} message fragments to English…")

    from app import llm, models_registry

    text, _ = llm.complete_for(
        models_registry.ROLE_ANALYSIS,
        None,
        _TRANSLATE_PROMPT.format(
            style=writing_rules.short_rules(),
            items=json.dumps(pending, indent=1, ensure_ascii=False),
        ),
        max_tokens=8000,
        model=model,
    )
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        mapping = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            log.warning("campaign %s: translation returned unparseable output", campaign_id)
            return 0
        try:
            mapping = json.loads(match.group(0))
        except ValueError:
            return 0
    if not isinstance(mapping, dict):
        return 0

    done = 0
    for token, english in mapping.items():
        if isinstance(english, str) and english.strip():
            db.set_campaign_slot_translation(conn, campaign_id, token, english.strip())
            done += 1
    log.info("campaign %s: translated %d slot values", campaign_id, done)
    return done
