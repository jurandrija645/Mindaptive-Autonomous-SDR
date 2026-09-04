import asyncio
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import db, main, pipeline, scheduler, smartlead, webhook
from app.config import settings


class _NoStartThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db_path = settings.db_path
        settings.db_path = str(Path(self.tmp.name) / "test.db")
        db.init_db()

    def tearDown(self):
        settings.db_path = self.old_db_path
        self.tmp.cleanup()

    def test_thread_fetch_populates_cache(self):
        raw = [
            {
                "type": "REPLY",
                "time": "2026-09-04T12:00:00+00:00",
                "message_id": "reply-1",
                "email_body": "Hello",
                "from": "lead@example.com",
            }
        ]
        with patch.object(smartlead, "get_message_history", return_value=raw):
            thread = pipeline.fetch_normalized_thread(10, 20)
        self.assertEqual(thread[-1].message_id, "reply-1")
        with db.db_session() as conn:
            cached = db.get_lead_thread(conn, 20, 10)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["latest_message_id"], "reply-1")

    def test_current_cache_avoids_live_smartlead_fetch(self):
        timestamp = "2026-09-04T12:00:00+00:00"
        cached_thread = [
            {
                "kind": "reply",
                "timestamp": timestamp,
                "message_id": "reply-1",
                "body": "Hello",
                "from_email": "lead@example.com",
                "to_email": "sender@example.com",
                "stats_id": "stats-1",
                "cc": "",
            }
        ]
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, 20, 10, interested=1, last_message_at=timestamp,
                category="reply",
            )
            db.put_lead_thread(
                conn, 20, 10, json.dumps(cached_thread), "reply-1", timestamp
            )
        with patch.object(
            pipeline, "fetch_normalized_thread",
            side_effect=AssertionError("live fetch should not run"),
        ):
            result = main._load_thread_raw(10, 20)
        self.assertEqual(result[0]["message_id"], "reply-1")

    def test_webhook_claim_is_durable_and_failed_event_can_retry(self):
        with db.db_session() as conn:
            self.assertTrue(db.claim_webhook_event(conn, "event-1", 10, 20))
        with db.db_session() as conn:
            self.assertFalse(db.claim_webhook_event(conn, "event-1", 10, 20))
            db.finish_webhook_event(conn, "event-1", "failed", "temporary")
        with db.db_session() as conn:
            self.assertTrue(db.claim_webhook_event(conn, "event-1", 10, 20))

    def test_webhook_records_reply_before_background_work(self):
        old_secret = settings.smartlead_webhook_secret
        settings.smartlead_webhook_secret = "test-secret"
        payload = {
            "campaign_id": 10,
            "sl_email_lead_id": 20,
            "to_email": "lead@example.com",
            "to_name": "Alex",
            "time_replied": "2026-09-04T12:00:00Z",
            "reply_message": {"text": "Yes, please send the code."},
        }
        try:
            with patch.object(webhook.threading, "Thread", _NoStartThread):
                with TestClient(main.app) as client:
                    response = client.post(
                        "/webhooks/smartlead",
                        json=payload,
                        headers={"X-Webhook-Secret": "test-secret"},
                    )
                    self.assertEqual(response.status_code, 202)
            with db.db_session() as conn:
                lead = db.get_lead_state(conn, 20, 10)
            self.assertEqual(lead["category"], "reply")
            self.assertIn("send the code", lead["last_message_preview"])
        finally:
            settings.smartlead_webhook_secret = old_secret

    def test_retry_after_header_wins(self):
        response = httpx.Response(429, headers={"Retry-After": "7"})
        self.assertEqual(smartlead._retry_delay(response, 1), 7.0)

    def test_retry_after_http_date_is_supported(self):
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=10)
        response = httpx.Response(
            429, headers={"Retry-After": retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")}
        )
        delay = smartlead._retry_delay(response, 1)
        self.assertGreater(delay, 8.0)
        self.assertLessEqual(delay, 10.0)

    def test_reply_campaigns_are_spread_across_sweep(self):
        scheduler._reply_campaign_last_checked.clear()
        ids = list(range(1, 22))
        batches = [
            scheduler._reply_campaign_batch(ids, 5, now_mono=1000 + minute * 60)
            for minute in range(5)
        ]
        self.assertTrue(all(len(batch) <= 5 for batch in batches))
        self.assertEqual(set().union(*batches), set(ids))

    def _draft(self):
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, 20, 10, interested=1, category="reply",
                last_message_at="2026-09-04T12:00:00+00:00",
            )
            return db.create_draft(
                conn,
                lead_id=20,
                campaign_id=10,
                kind="reply",
                body_html="Hello",
                status="pending",
            )

    def test_send_is_claimed_before_smartlead_and_failure_is_retryable(self):
        draft_id = self._draft()
        old_password = settings.app_password
        settings.app_password = "pw"

        def fail_after_claim(draft):
            self.assertEqual(draft["status"], "sending")
            raise RuntimeError("temporary upstream failure")

        try:
            with patch.object(main.scheduler, "_send_due_draft", side_effect=fail_after_claim):
                with TestClient(main.app, raise_server_exceptions=False) as client:
                    client.post("/login", data={"password": "pw"})
                    response = client.post(
                        f"/api/drafts/{draft_id}/send", json={"body_html": "Edited"}
                    )
            self.assertEqual(response.status_code, 500)
            with db.db_session() as conn:
                draft = db.get_draft(conn, draft_id)
            self.assertEqual(draft["status"], "pending")
            self.assertIn("temporary upstream", draft["send_error"])
        finally:
            settings.app_password = old_password

    def test_sending_draft_rejects_second_send(self):
        draft_id = self._draft()
        old_password = settings.app_password
        settings.app_password = "pw"
        with db.db_session() as conn:
            db.update_draft(conn, draft_id, status="sending")
        try:
            with TestClient(main.app) as client:
                client.post("/login", data={"password": "pw"})
                response = client.post(f"/api/drafts/{draft_id}/send", json={})
            self.assertEqual(response.status_code, 409)
        finally:
            settings.app_password = old_password

    def test_slow_send_does_not_block_the_event_loop(self):
        draft_id = self._draft()
        entered = threading.Event()

        def slow_send(_draft):
            entered.set()
            time.sleep(0.3)
            return "sent"

        async def exercise():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                with (
                    patch.object(main, "require_auth", return_value=None),
                    patch.object(main.scheduler, "_send_due_draft", side_effect=slow_send),
                ):
                    send_task = asyncio.create_task(
                        client.post(f"/api/drafts/{draft_id}/send", json={})
                    )
                    self.assertTrue(await asyncio.to_thread(entered.wait, 0.2))
                    started = time.perf_counter()
                    inbox_response = await client.get("/api/inbox")
                    inbox_elapsed = time.perf_counter() - started
                    send_response = await send_task
            return inbox_response, inbox_elapsed, send_response

        inbox_response, inbox_elapsed, send_response = asyncio.run(exercise())
        self.assertEqual(inbox_response.status_code, 200)
        self.assertLess(inbox_elapsed, 0.2)
        self.assertEqual(send_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
