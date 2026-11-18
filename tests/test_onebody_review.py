import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import drafter, onebody_review


def draft():
    return drafter.DraftResult("", "Book at https://example.com with VIP8401. £4.99 fee. Share the brochure. Share the link too.", "", "")


def call_review(result, response):
    with patch.object(onebody_review, "enabled", return_value=True), \
         patch.object(onebody_review.models_registry, "provider_for", return_value="openrouter"), \
         patch.object(onebody_review.openrouter, "complete", return_value=response):
        return onebody_review.review(result, "[sent] earlier email\n[reply] yes", {"name": "Andy"}, "vendor/model")


def test_review_removes_duplicate_without_losing_booking_terms():
    result = draft()
    revised = "Book at https://example.com with VIP8401. £4.99 fee. Share the brochure."
    reviewed = call_review(result, json.dumps({"decision": "revise", "body": revised, "reason": "duplicate"}))
    assert reviewed.body_original == revised


@pytest.mark.parametrize("response", [
    "not json",
    json.dumps({"decision": "hold", "body": "", "reason": "unknown clinic"}),
    json.dumps({"decision": "revise", "body": "Book at https://elsewhere.com with VIP8401. £4.99 fee."}),
    json.dumps({"decision": "revise", "body": "Book at https://example.com with VIP8401."}),
    json.dumps({"decision": "revise", "body": "Book at https://example.com with VIP8401. £4.99 fee. Share the brochure — thanks."}),
    json.dumps({"decision": "pass", "body": "Book at https://example.com with VIP8401. £4.99 fee. {{name}}"}),
    json.dumps({"decision": "pass", "body": "Book at https://example.com with VIP8401. £4.99 fee. OBLACCESS55. Share the brochure."}),
    json.dumps({"decision": "pass", "body": "Book at https://example.com with VIP8401. £4.99 fee."}),
])
def test_review_failure_never_returns_unchecked_draft(response):
    with pytest.raises(onebody_review.ReviewError):
        call_review(draft(), response)


def test_other_clients_do_not_call_reviewer():
    result = draft()
    with patch.object(onebody_review, "enabled", return_value=False), \
         patch.object(onebody_review.openrouter, "complete") as complete:
        assert onebody_review.review(result, "", {}, "vendor/model") is result
        complete.assert_not_called()


@pytest.mark.parametrize("url", [
    "https://example.com.",
    "**https://example.com**",
    "[Book here](https://example.com)",
    "<a href=\"https://example.com\">Book here</a>",
])
def test_link_formatting_does_not_count_as_a_changed_target(url):
    body = f"Book at {url} with VIP8401. £4.99 fee. Share the brochure."
    reviewed = call_review(draft(), json.dumps({"decision": "revise", "body": body}))
    assert reviewed.body_original == body


@pytest.mark.parametrize("url", ["https://elsewhere.com", "https://example.com/?offer=different"])
def test_real_target_changes_still_need_human_review(url):
    body = f"Book at {url} with VIP8401. £4.99 fee. Share the brochure."
    with pytest.raises(onebody_review.ReviewError, match="changed a link"):
        call_review(draft(), json.dumps({"decision": "revise", "body": body}))


def test_reviewer_can_verify_a_clinic_outside_the_priority_list():
    from app import client_assets
    body = draft().body_original
    with patch.object(onebody_review, "enabled", return_value=True), \
         patch.object(client_assets, "CLIENT_DIR", client_assets.REPO_ROOT / "clients" / "onebodyldn"), \
         patch.object(onebody_review.models_registry, "provider_for", return_value="openrouter"), \
         patch.object(onebody_review.openrouter, "complete", return_value=json.dumps({"decision": "pass", "body": body})) as complete:
        onebody_review.review(draft(), "[reply] Could it be at Shoreditch?", {}, "vendor/model")
    system = complete.call_args.args[1]
    assert "Shoreditch | 75 Great Eastern Street, London, EC2A 3HN" in system
    assert "free-offer eligibility and exclusions" in system
