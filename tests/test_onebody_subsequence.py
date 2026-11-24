from unittest.mock import patch

import pytest

from app import db, onebody_subsequence as sub, smartlead
from app.config import settings

PHYSIO_LINK = "https://onebodyldn.connect.tm3app.com/book/partnerships/physiotherapy_1/physiotherapy_assessment_treatment_45_min"
M20_LINK = "https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_20_min"
CATEGORIES = {"Interested": 1, "Do Not Contact": 4, "Information Request": 5, "Out Of Office": 6, "Meeting Booked": 177154,
              "Interested in 45 Physio": 197614, "Interested in 45 Sports": 197615}
CAMPAIGNS = [{"id": 100, "parent_campaign_id": None}, {"id": 101, "parent_campaign_id": 100},
             {"id": 102, "parent_campaign_id": 100}, {"id": 200, "parent_campaign_id": None}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(sub, "available", lambda: True)
    monkeypatch.setattr(smartlead, "fetch_categories", lambda: dict(CATEGORIES))
    monkeypatch.setattr(smartlead, "list_campaigns", lambda: CAMPAIGNS)
    db.init_db()


def overview(category=1, extra=()):
    rows = [{"email_campaign_id": "100", "lead_category_id": category}]
    rows += [{"email_campaign_id": str(c), "lead_category_id": None} for c in extra]
    return {"email_campaign_leads_mappings": rows}


def draft(kind="auto_response", campaign=100):
    return {"id": 1, "lead_id": 7, "campaign_id": campaign, "kind": kind}


def run(body, ov, d=None):
    with patch.object(smartlead, "get_lead_campaign_overview", return_value=ov), \
         patch.object(smartlead, "update_lead_category") as update:
        result = sub.after_reply_sent(d or draft(), body)
    return result, update


def test_link_decides_category():
    assert sub.target_for(f"<a href='{PHYSIO_LINK}'>book</a>") == sub.PHYSIO
    assert sub.target_for(M20_LINK) == sub.SPORTS
    assert sub.target_for(PHYSIO_LINK + " " + M20_LINK) is None
    assert sub.target_for("Thanks, see you soon") is None


@pytest.mark.parametrize("link,target_id", [(PHYSIO_LINK, 197614), (M20_LINK, 197615)])
def test_plain_interested_moves(env, link, target_id):
    result, update = run(link, overview(1))
    update.assert_called_once_with(100, 7, target_id, pause_lead=False)
    assert result in (sub.PHYSIO, sub.SPORTS)
    with db.db_session() as conn:
        assert db.get_lead_state(conn, 7, 100)["smartlead_category"] == result


def test_uncategorised_and_information_request_move(env):
    assert run(PHYSIO_LINK, overview(None))[1].called
    assert run(PHYSIO_LINK, overview(5))[1].called
    assert run(PHYSIO_LINK, overview(6))[1].called  # stale Out Of Office


@pytest.mark.parametrize("category", [4, 177154, 197614, 197615])
def test_other_categories_left_alone(env, category):
    result, update = run(PHYSIO_LINK, overview(category))
    assert result is None and not update.called


def test_lead_already_in_a_subsequence_left_alone(env):
    result, update = run(PHYSIO_LINK, overview(1, extra=[101]))
    assert result is None and not update.called


def test_campaign_without_subsequence_left_alone(env):
    ov = {"email_campaign_leads_mappings": [{"email_campaign_id": "200", "lead_category_id": 1}]}
    result, update = run(PHYSIO_LINK, ov, draft(campaign=200))
    assert result is None and not update.called


@pytest.mark.parametrize("kind", ["followup", "sequence", "aftercare"])
def test_only_replies(env, kind):
    result, update = run(PHYSIO_LINK, overview(1), draft(kind=kind))
    assert result is None and not update.called


def test_signature_link_is_ignored(env):
    """The signature's own physio 'Book a session' link must not make a massage reply ambiguous."""
    d = {**draft(), "body_html": f"<p>Here you go: {M20_LINK}</p>"}
    result, update = run(f"<p>Here you go: {M20_LINK}</p><table>{PHYSIO_LINK}</table>", overview(1), d)
    assert result == sub.SPORTS
    update.assert_called_once_with(100, 7, 197615, pause_lead=False)


def test_reply_without_link_left_alone(env):
    result, update = run("Fair question, happy to help.", overview(1))
    assert result is None and not update.called


def test_dry_run_and_errors_never_raise(env, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    assert not run(PHYSIO_LINK, overview(1))[1].called
    monkeypatch.setattr(settings, "dry_run", False)
    with patch.object(smartlead, "get_lead_campaign_overview", side_effect=smartlead.SmartleadError("x")):
        assert sub.after_reply_sent(draft(), PHYSIO_LINK) is None


def test_not_onebody(env, monkeypatch):
    monkeypatch.setattr(sub, "available", lambda: False)
    assert not run(PHYSIO_LINK, overview(1))[1].called
