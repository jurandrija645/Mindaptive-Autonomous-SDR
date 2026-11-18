"""Generated messages stay reviewable; second-pass failures only stop automation."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import auto_replies, batch_gen, candidates, db, detector, drafter, main, onebody_review, pipeline, smartlead
from app.config import settings


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "responder.db"))
    monkeypatch.setattr(onebody_review, "enabled", lambda: True)
    monkeypatch.setattr(auto_replies, "available", lambda: True)
    db.init_db()
    thread = [
        detector.NormalizedMessage("sent", datetime(2026, 11, 8, tzinfo=timezone.utc), "sent-1", "Free session?", from_email="rebecca@example.com"),
        detector.NormalizedMessage("reply", datetime(2026, 11, 9, tzinfo=timezone.utc), "reply-1", "Yes, could it be in Shoreditch?", from_email="lead@example.com"),
    ]
    with db.db_session() as conn:
        db.upsert_lead_state(conn, 20, 10, name="Alex", email="lead@example.com", interested=1, status="awaiting_reply", category="reply")
    monkeypatch.setattr(pipeline, "fetch_normalized_thread", lambda *_: thread)
    monkeypatch.setattr(candidates.lead_language, "smartlead_field", lambda *_: "en")
    monkeypatch.setattr(pipeline.lead_language, "resolve", lambda **_: ("en", "test"))
    monkeypatch.setattr(pipeline.signatures, "get_signature_html", lambda *_: "<p>Rebecca</p>")
    monkeypatch.setattr(pipeline.signatures, "persona_name", lambda *_: "Rebecca")
    monkeypatch.setattr(pipeline.signatures, "calendar_link_for", lambda *_: "")
    monkeypatch.setattr(pipeline.models_registry, "resolve", lambda *_: "test/model")
    monkeypatch.setattr(pipeline.models_registry, "resolve_anthropic", lambda *_: "test-model")
    body = "Hi Alex, here is the brochure with the session details for your colleagues."
    monkeypatch.setattr(drafter, "generate_draft", lambda *_, **__: drafter.DraftResult("Interested", body, "", ""))
    return thread, body


@pytest.mark.parametrize("error", [
    onebody_review.ReviewError("OneBody review changed a link; draft held"),
    onebody_review.ReviewError("OneBody review: human review required"),
    onebody_review.ReviewError("OneBody review could not approve the draft"),
    RuntimeError("review provider offline"),
])
@pytest.mark.parametrize("automatic", [False, True])
def test_review_failure_keeps_original_visible_and_never_auto_sends(state, error, automatic):
    thread, body = state
    auto_replies.set_enabled(automatic)
    with patch.object(onebody_review, "review", side_effect=error), \
         patch.object(smartlead, "reply_to_thread") as send, \
         patch.object(auto_replies.reply_classifier, "classify") as classify:
        draft_id = candidates.generate_for_lead(10, 20)
        assert not auto_replies.schedule_reviewed(draft_id, thread)
        classify.assert_not_called()
        send.assert_not_called()
    with db.db_session() as conn:
        saved = db.get_draft(conn, draft_id)
        assert saved["status"] == "pending" and saved["kind"] == "reply"
        assert body in saved["body_html"]
        assert not saved["scheduled_at"] and not saved["sent_at"]
        assert onebody_review.warning(draft_id, conn)
        assert main._draft_payload(saved)["review_warning"]
    assert onebody_review.held(10, 20, "reply-1")


@pytest.mark.parametrize("automatic", [False, True])
def test_manual_generate_only_creates_pending_draft_even_with_auto_mode_on(state, automatic):
    _, body = state
    auto_replies.set_enabled(automatic)
    with patch.object(onebody_review, "review", side_effect=lambda result, *_: result), \
         patch.object(auto_replies, "schedule_reviewed") as schedule, \
         patch.object(smartlead, "reply_to_thread") as send:
        draft_id = candidates.generate_for_lead(10, 20)
        schedule.assert_not_called()
        send.assert_not_called()
    with db.db_session() as conn:
        draft = db.get_draft(conn, draft_id)
        assert draft["status"] == "pending"
        assert body in draft["body_html"]
        assert onebody_review.warning(draft_id, conn) is None


def test_legacy_hold_without_draft_does_not_block_new_generation(state):
    onebody_review.set_hold(10, 20, "reply-1")
    assert not onebody_review.held(10, 20, "reply-1")


def test_regeneration_success_replaces_warning_and_old_hold(state):
    with patch.object(onebody_review, "review", side_effect=onebody_review.ReviewError("bad link")):
        previous_id = candidates.generate_for_lead(10, 20)
    with patch.object(onebody_review, "review", side_effect=lambda result, *_: result):
        draft_id = candidates.generate_for_lead(10, 20)
    with db.db_session() as conn:
        assert db.get_draft(conn, previous_id)["status"] == "skipped"
        assert db.get_draft(conn, draft_id)["status"] == "pending"
        assert onebody_review.warning(draft_id, conn) is None
    assert not onebody_review.held(10, 20)


def test_primary_generation_failure_preserves_previous_draft(state):
    with patch.object(onebody_review, "review", side_effect=lambda result, *_: result):
        previous_id = candidates.generate_for_lead(10, 20)
    with patch.object(drafter, "generate_draft", side_effect=RuntimeError("primary provider offline")):
        with pytest.raises(RuntimeError, match="primary provider offline"):
            candidates.generate_for_lead(10, 20)
    with db.db_session() as conn:
        assert db.get_draft(conn, previous_id)["status"] == "pending"


def test_batch_review_failure_stores_draft_without_auto_scheduling(state, monkeypatch):
    thread, body = state
    monkeypatch.setattr(settings, "auto_send_followups", True)
    with db.db_session() as conn:
        db.upsert_candidate(conn, 20, 10, "followup", lead_email="lead@example.com")
        candidate = db.list_candidates(conn)[0]
        cid = candidate["id"]
        db.update_candidate(conn, cid, status="generating")
    response = SimpleNamespace(custom_id=f"cand-{cid}", result=SimpleNamespace(type="succeeded",
        message=SimpleNamespace(content=[SimpleNamespace(type="text", text=f"<draft_original>{body}</draft_original>")])))
    with patch.object(batch_gen.detector, "decide", return_value=SimpleNamespace(action=detector.Action.FOLLOWUP)), \
         patch.object(onebody_review, "review", side_effect=onebody_review.ReviewError("bad link")), \
         patch.object(smartlead, "reply_to_thread") as send:
        assert batch_gen._handle_result(response)
        send.assert_not_called()
    with db.db_session() as conn:
        saved_candidate = db.get_candidate(conn, cid)
        assert saved_candidate["status"] == "drafted"
        saved = db.get_draft(conn, saved_candidate["draft_id"])
        assert saved["status"] == "pending" and not saved["scheduled_at"]
        assert onebody_review.warning(saved["id"], conn)
