import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db, main, pipeline, slack_links
from app.config import settings
from app.detector import NormalizedMessage


def _iso(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


class SlackLinksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []
        self.patches = [
            patch.object(settings, "db_path", str(Path(self.tmp.name) / "t.db")),
            patch.object(settings, "smartlead_webhook_secret", "s3cret"),
            patch.object(settings, "slack_bot_token", "xoxb-test"),
            patch.object(slack_links, "_slack", self.fake_slack),
            patch.object(pipeline, "fetch_normalized_thread", lambda cid, lid: []),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def fake_slack(self, method, payload):
        self.calls.append((method, payload))
        return {"ok": True}

    def post(self, ts="111.1", lead_id=7, email="lead@acme.test", minutes_ago=30):
        with db.db_session() as conn:
            slack_links.record_post(conn, channel="C1", ts=ts, campaign_id=3, lead_id=lead_id,
                                    email=email, posted_at=_iso(minutes_ago))

    def row(self, ts="111.1"):
        with db.db_session() as conn:
            return conn.execute("SELECT * FROM slack_posts WHERE ts = ?", (ts,)).fetchone()

    def reactions(self):
        return [p["name"] for m, p in self.calls if m == "reactions.add"]

    def test_webhook_records_link_once_and_checks_secret(self):
        body = {"channel": "C1", "ts": "222.2", "campaign_id": 3, "lead_id": 9, "email": "A@B.test"}
        self.assertEqual(self.client.post("/webhooks/slack-posted", json=body).status_code, 401)
        headers = {"X-Webhook-Secret": "s3cret"}
        self.assertEqual(self.client.post("/webhooks/slack-posted", json=body, headers=headers).json()["status"], "recorded")
        self.assertEqual(self.client.post("/webhooks/slack-posted", json=body, headers=headers).json()["status"], "duplicate")
        self.assertEqual(self.row("222.2")["email"], "a@b.test")
        bad = self.client.post("/webhooks/slack-posted", json={"channel": "C1"}, headers=headers)
        self.assertEqual(bad.status_code, 400)

    def test_sent_reply_marks_post_answered_with_tick_and_thread_note(self):
        self.post()
        self.post(ts="333.3", lead_id=8, email="other@acme.test")
        draft = {"id": 1, "lead_id": 7, "lead_email": "lead@acme.test", "kind": "reply",
                 "body_html": "<p>Hi Jo, yes we take Bupa.</p>"}
        with db.db_session() as conn:
            self.assertEqual(slack_links.mark_answered(conn, draft, _iso(0), sender="Kurt"), 1)
        slack_links.run_sync()
        self.assertEqual(self.reactions(), ["white_check_mark"])
        note = [p for m, p in self.calls if m == "chat.postMessage"][0]
        self.assertEqual(note["thread_ts"], "111.1")
        self.assertIn("Kurt", note["text"])
        self.assertIn("yes we take Bupa", note["text"])
        self.assertIsNone(self.row("333.3")["answered_at"])
        self.calls.clear()
        slack_links.run_sync()
        self.assertEqual(self.calls, [])

    def test_sequence_step_and_later_post_are_not_answers(self):
        self.post(minutes_ago=-5)  # posted after the send
        with db.db_session() as conn:
            self.assertEqual(slack_links.mark_answered(
                conn, {"lead_id": 7, "kind": "reply", "body_html": "x"}, _iso(0)), 0)
            self.assertEqual(slack_links.mark_answered(
                conn, {"lead_id": 7, "kind": "sequence", "body_html": "x"}, _iso(-10)), 0)

    def test_held_draft_gets_warning_unless_answered(self):
        self.post()
        self.post(ts="444.4", lead_id=8, email="other@acme.test")
        with db.db_session() as conn:
            slack_links.mark_held(conn, 7, "lead@acme.test", "Lead asks for a refund")
            slack_links.mark_held(conn, 8, "other@acme.test", "Complaint")
            slack_links.mark_answered(conn, {"lead_id": 8, "kind": "reply", "body_html": "Sorted"}, _iso(0))
        slack_links.run_sync()
        warned = [p["timestamp"] for m, p in self.calls if m == "reactions.add" and p["name"] == "warning"]
        self.assertEqual(warned, ["111.1"])
        self.assertTrue(any("refund" in p["text"] for m, p in self.calls if m == "chat.postMessage"))

    def test_booking_adds_calendar_once(self):
        self.post()
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 7, 99, email="lead@acme.test")
            db.mark_lead_booked(conn, 7, 99)
        slack_links.run_sync()
        slack_links.run_sync()
        self.assertEqual(self.reactions(), ["date"])

    def test_reply_sent_from_smartlead_directly_is_detected(self):
        self.post(minutes_ago=60)
        sent = NormalizedMessage(kind="sent", timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
                                 message_id="<m>", body="<p>Here is the link</p>")
        with patch.object(pipeline, "fetch_normalized_thread", lambda cid, lid: [sent]):
            slack_links.run_sync()
        self.assertEqual(self.reactions(), ["white_check_mark"])
        self.assertIn("Smartleada", self.row()["answered_note"])

    def test_slack_failure_is_retried_and_no_token_posts_nothing(self):
        self.post()
        with db.db_session() as conn:
            slack_links.mark_answered(conn, {"lead_id": 7, "kind": "reply", "body_html": "x"}, _iso(0))
        with patch.object(slack_links, "_slack", side_effect=RuntimeError("down")):
            slack_links.run_sync()
        self.assertEqual(self.row()["answered_pushed"], 0)
        with patch.object(settings, "slack_bot_token", ""):
            slack_links.run_sync()
        self.assertEqual(self.calls, [])
        slack_links.run_sync()
        self.assertEqual(self.row()["answered_pushed"], 1)


if __name__ == "__main__":
    unittest.main()


def test_full_text_keeps_whole_reply_without_signature_or_history():
    from app import slack_links
    html = ("<p>Hi Steve,</p><p>No problem at all.</p><p>Here's the link: "
            "https://onebodyldn.connect.tm3app.com/book/partnerships/sports_massage_2/sports_massage_20_min</p>"
            "<p>Use code VIP8401.</p>" + "<p>" + "word " * 60 + "</p>")
    out = slack_links._full_text(html)
    assert out.startswith("> Hi Steve,")
    assert "VIP8401" in out and "sports_massage_20_min" in out and "…" not in out
    plain = "Hi Tom, No catch really. Use code VIP8401 . Kurt in ig Kurt Johnson Co-Founder @ One Body LDN On Mon, 23 Nov wrote: old"
    out = slack_links._full_text(plain)
    assert "VIP8401" in out and "Co-Founder" not in out and "old" not in out
