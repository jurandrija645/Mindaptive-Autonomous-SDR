"""OneBody: put a lead into its "Interested in 45 ..." subsequence once we have sent the booking link.

Smartlead AI labels a positive reply plain "Interested", and no subsequence triggers on that.
Each OneBody cold campaign has two child campaigns whose lead condition is the category
"Interested in 45 Physio" or "Interested in 45 Sports" (the latter also carries the
20-minute massage). Without the move, a lead who got the booking link is never followed up.

The move is deterministic, not a classifier guess: it fires only after a reply that actually
went out and contains a partnership booking link, and the link decides which category:

    /book/partnerships/physiotherapy...   -> Interested in 45 Physio
    /book/partnerships/sports_massage...  -> Interested in 45 Sports

It never touches a lead that
  - sits in any category other than plain Interested / Meeting Request / Information Request /
    Out Of Office / Auto Reply (Do Not Contact, Meeting Booked, the two subsequence categories, anything set by hand), or
  - has already been in a subsequence of this campaign (Andrija keeps those in plain
    Interested on purpose, 23 Nov 2026), or
  - is in a campaign that has no subsequence at all.

Best-effort: a failure is logged and never affects the send.
"""
import logging
import re

from app import client_assets, db, smartlead
from app.config import settings

log = logging.getLogger(__name__)

PHYSIO = "Interested in 45 Physio"
SPORTS = "Interested in 45 Sports"
# Categories a fresh positive reply can carry before we answer it. Out Of Office / Auto
# Reply stay on a lead after an earlier auto-responder even when the person later writes back.
MOVABLE = {"interested", "meetingrequest", "informationrequest", "outofoffice", "autoreply"}
REPLY_KINDS = {"reply", "auto_response"}

_LINK = re.compile(r"/book/partnerships/(physiotherapy|sports_massage)", re.I)


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def available() -> bool:
    return client_assets.CLIENT_DIR == client_assets.REPO_ROOT / "clients" / "onebodyldn"


def target_for(body: str) -> str | None:
    """The subsequence category the booking link in `body` belongs to, or None.

    A reply with both links is ambiguous and is left alone."""
    kinds = {m.lower() for m in _LINK.findall(body or "")}
    if kinds == {"physiotherapy"}:
        return PHYSIO
    if kinds == {"sports_massage"}:
        return SPORTS
    return None


def _children(campaign_id: int) -> set[int]:
    return {
        int(c["id"]) for c in smartlead.list_campaigns()
        if str(c.get("parent_campaign_id") or "") == str(campaign_id)
    }


def after_reply_sent(draft: dict, body: str) -> str | None:
    """Move the lead to its subsequence category. Returns the category set, or None."""
    if not available() or draft.get("kind") not in REPLY_KINDS:
        return None
    target = target_for(body)
    if not target:
        return None
    campaign_id, lead_id = int(draft["campaign_id"]), int(draft["lead_id"])
    try:
        children = _children(campaign_id)
        if not children:
            log.info("subsequence move: campaign %s has no subsequence; lead %s left as is",
                     campaign_id, lead_id)
            return None
        mappings = smartlead.get_lead_campaign_overview(lead_id)["email_campaign_leads_mappings"]
        if any(int(m.get("email_campaign_id") or 0) in children for m in mappings):
            log.info("subsequence move: lead %s was already in a subsequence of %s; left as is",
                     lead_id, campaign_id)
            return None
        mine = [m for m in mappings if str(m.get("email_campaign_id")) == str(campaign_id)]
        if not mine:
            return None
        categories = smartlead.fetch_categories()  # {name: id}
        names = {str(v): _norm(k) for k, v in categories.items()}
        current = mine[0].get("lead_category_id")
        if current and names.get(str(current)) not in MOVABLE:
            log.info("subsequence move: lead %s/%s is in category %s; left as is",
                     campaign_id, lead_id, current)
            return None
        target_id = next((v for k, v in categories.items() if _norm(k) == _norm(target)), None)
        if target_id is None:
            log.warning("subsequence move: category %r not found in Smartlead", target)
            return None
        if settings.dry_run:
            log.info("[DRY_RUN] would set lead %s/%s to %r", campaign_id, lead_id, target)
            return None
        smartlead.update_lead_category(campaign_id, lead_id, int(target_id), pause_lead=False)
        with db.db_session() as conn:
            db.upsert_lead_state(conn, lead_id, campaign_id, smartlead_category=target)
        log.info("subsequence move: lead %s/%s -> %r", campaign_id, lead_id, target)
        return target
    except Exception:
        log.exception("subsequence move failed for lead %s/%s", campaign_id, lead_id)
        return None
