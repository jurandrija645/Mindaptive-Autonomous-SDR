import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app import auto_replies, db, detector, reply_classifier, scheduler, smartlead
from app.config import settings


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "db.sqlite"))
    monkeypatch.setattr(auto_replies, "available", lambda: True)
    db.init_db()
    thread = [detector.NormalizedMessage("reply", datetime(2026, 11, 4, tzinfo=timezone.utc), "msg-1", "Yes please", from_email="lead@example.com")]
    with db.db_session() as conn:
        db.upsert_lead_state(conn, 20, 10, email="lead@example.com", status="active")
        draft_id = db.create_draft(conn, lead_id=20, campaign_id=10, kind="reply", status="pending",
            body_html="<p>Here is the brochure.</p>", lead_email="lead@example.com", sender_email="sender@example.com",
            thread_snapshot=json.dumps([m.__dict__ for m in thread], default=str), reply_message_id="msg-1")
    return draft_id, thread


def test_toggle_defaults_off_and_only_queues_new_approved_replies(state):
    draft_id, thread = state
    with patch.object(reply_classifier, "classify", return_value=(reply_classifier.INTERESTED, "ok")) as classify:
        assert not auto_replies.schedule_reviewed(draft_id, thread)
        classify.assert_not_called()
        auto_replies.set_enabled(True)
        assert auto_replies.schedule_reviewed(draft_id, thread)
    with db.db_session() as conn:
        d = dict(db.get_draft(conn, draft_id))
        assert d["status"] == "scheduled" and d["kind"] == auto_replies.KIND
        assert db.get_setting(conn, auto_replies.APPROVAL + str(draft_id)) == auto_replies.fingerprint(d)
    auto_replies.set_enabled(False)
    with db.db_session() as conn:
        d = db.get_draft(conn, draft_id)
        assert d["status"] == "pending" and d["kind"] == "reply"


@pytest.mark.parametrize("label", [reply_classifier.UNKNOWN, reply_classifier.NOT_INTERESTED,
                                     reply_classifier.AUTO_REPLY, reply_classifier.WRONG_PERSON])
def test_only_interested_replies_are_queued(state, label):
    draft_id, thread = state
    auto_replies.set_enabled(True)
    with patch.object(reply_classifier, "classify", return_value=(label, "test")):
        assert not auto_replies.schedule_reviewed(draft_id, thread)
    with db.db_session() as conn:
        assert db.get_draft(conn, draft_id)["status"] == "pending"


def test_opt_out_stops_and_blocks_without_sending(state):
    draft_id, thread = state
    thread[-1].body = "Please stop emailing me"
    auto_replies.set_enabled(True)
    with patch.object(settings, "dry_run", False), patch.object(scheduler, "_push_category_to_smartlead"), \
         patch.object(smartlead, "unsubscribe_lead_globally") as unsub, \
         patch.object(smartlead, "add_to_global_block_list") as block, \
         patch.object(smartlead, "reply_to_thread") as send:
        assert not auto_replies.schedule_reviewed(draft_id, thread)
        unsub.assert_called_once_with(20)
        block.assert_called_once_with("lead@example.com")
        send.assert_not_called()
    with db.db_session() as conn:
        assert db.get_lead_state(conn, 20, 10)["status"] == "blacklisted"
        assert db.get_draft(conn, draft_id)["status"] == "stale"


def test_presend_rejects_modified_draft_new_messages_and_negative_live_category(state):
    draft_id, thread = state
    auto_replies.set_enabled(True)
    with patch.object(reply_classifier, "classify", return_value=(reply_classifier.INTERESTED, "ok")):
        assert auto_replies.schedule_reviewed(draft_id, thread)
    with db.db_session() as conn:
        draft = dict(db.get_draft(conn, draft_id))
    overview = {"email_campaign_leads_mappings": [{"email_campaign_id": 10, "is_active": True, "lead_category_id": 1}]}
    with patch.object(smartlead, "get_lead_campaign_overview", return_value=overview), \
         patch.object(smartlead, "fetch_categories", return_value={"Interested": 1, "Do Not Contact": 2}):
        assert auto_replies.presend(draft, thread)
        assert not auto_replies.presend({**draft, "body_html": "Changed"}, thread)
        changed = [*thread, detector.NormalizedMessage("sent", datetime.now(timezone.utc), "msg-2", "Already replied")]
        assert not auto_replies.presend(draft, changed)
        overview["email_campaign_leads_mappings"][0]["lead_category_id"] = 2
        assert not auto_replies.presend(draft, thread)


def test_classifier_unavailable_fails_closed_for_automation():
    with patch.object(reply_classifier.llm, "complete_for", side_effect=RuntimeError("offline")):
        assert reply_classifier.classify("Yes", fail_closed=True)[0] == reply_classifier.UNKNOWN


def test_auto_send_stops_when_disabled_before_send(state):
    draft_id, thread = state
    auto_replies.set_enabled(True)
    with patch.object(reply_classifier, "classify", return_value=(reply_classifier.INTERESTED, "ok")):
        assert auto_replies.schedule_reviewed(draft_id, thread)
    with db.db_session() as conn:
        draft = dict(db.get_draft(conn, draft_id))
    auto_replies.set_enabled(False)
    with patch.object(scheduler.pipeline, "fetch_normalized_thread", return_value=thread), \
         patch.object(smartlead, "reply_to_thread") as send:
        assert scheduler._send_due_draft(draft) == "pending"
        send.assert_not_called()


def test_second_draft_for_same_reply_cannot_be_queued(state):
    draft_id, thread = state
    auto_replies.set_enabled(True)
    with patch.object(reply_classifier, "classify", return_value=(reply_classifier.INTERESTED, "ok")):
        assert auto_replies.schedule_reviewed(draft_id, thread)
        with db.db_session() as conn:
            other = db.create_draft(conn, lead_id=20, campaign_id=10, kind="reply", status="pending",
                body_html="hello", lead_email="lead@example.com", reply_message_id="msg-1")
        assert not auto_replies.schedule_reviewed(other, thread)


def test_failed_global_block_is_retried(state):
    _, _ = state
    with patch.object(settings, "dry_run", False), patch.object(scheduler, "_push_category_to_smartlead"), \
         patch.object(smartlead, "unsubscribe_lead_globally"), \
         patch.object(smartlead, "add_to_global_block_list", side_effect=[RuntimeError("offline"), None]) as block:
        scheduler.record_do_not_contact(20, 10, email="lead@example.com")
        with db.db_session() as conn:
            assert db.get_setting(conn, "dnc_suppression_pending:20")
        scheduler.retry_dnc_suppressions()
        assert block.call_count == 2
        with db.db_session() as conn:
            assert db.get_setting(conn, "dnc_suppression_pending:20") is None


def test_claimed_reply_is_blocked_if_contact_opted_out_in_another_campaign(state):
    draft_id, thread = state
    with db.db_session() as conn:
        db.upsert_lead_state(conn, 21, 11, email="lead@example.com", status="blacklisted")
        draft = dict(db.get_draft(conn, draft_id))
    with patch.object(scheduler.pipeline, "fetch_normalized_thread") as fetch, \
         patch.object(smartlead, "reply_to_thread") as send:
        assert scheduler._send_due_draft(draft) == "stale"
        fetch.assert_not_called()
        send.assert_not_called()
