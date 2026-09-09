import asyncio
import hashlib
import hmac
import json
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import db, drafter, interested_sheet, main, pipeline, reply_classifier, scheduler, smartlead, webhook
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

    def test_sender_without_persona_calendar_does_not_override_client_booking_link(self):
        message = drafter._build_user_message(
            "reply",
            {
                "name": "Alex",
                "email": "alex@example.com",
                "sender_name": "Kurt Johnson",
                "calendar_link": "",
            },
            "Lead: Yes please, send the code.",
            use_web_search=False,
        )
        self.assertIn("Follow the system prompt and knowledge base", message)
        self.assertNotIn("No booking link is available", message)
        self.assertNotIn("offer to send times instead", message)

    def test_onebody_positive_templates_contain_fixed_booking_handover(self):
        source = Path("clients/onebodyldn/knowledge/response-templates.md").read_text(
            encoding="utf-8"
        )
        direct_start = source.index('## Direct-to-worker — "yes" / wants the code')
        corporate_start = source.index('## Corporate / HR — "yes" for the team')
        insurance_start = source.index('## "Do you take my insurance?"')
        direct = source[direct_start:corporate_start]
        corporate = source[corporate_start:insurance_start]
        for template in (direct, corporate):
            self.assertIn("OBLACCESS55", template)
            self.assertIn("https://onebodyldn.connect.tm3app.com/book/", template)
        self.assertIn("{{nearest_clinic}} is closest to you", direct)
        self.assertNotIn("£4.99", direct)

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

    def test_smartlead_filter_names_ooo_as_auto_reply(self):
        source = Path("app/static/app.js").read_text(encoding="utf-8")
        start = source.index("function smartleadCategoryLabel")
        end = source.index("function smartleadFilterLabel", start)
        script = source[start:end] + "\nconsole.log(smartleadCategoryLabel('Out Of Office'));"
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=True
        )
        self.assertEqual(result.stdout.strip(), "Auto-reply / Out of office")

    def test_change_status_dropdown_keeps_interested_restore_action(self):
        source = Path("app/static/app.js").read_text(encoding="utf-8")
        self.assertIn("state.categoryList = data.categories;", source)
        self.assertIn('const restoring = name === "Interested";', source)
        self.assertIn('This restores them to your inbox.', source)
        self.assertNotIn(
            'data.categories.filter((c) => c !== "Interested")', source
        )

    def test_category_push_refreshes_filter_mirror_only_after_success(self):
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 20, 10, category="auto_reply")
        with patch.object(settings, "dry_run", False), patch.object(
            smartlead, "fetch_categories", return_value={"Out Of Office": 6}
        ), patch.object(smartlead, "update_lead_category") as update:
            update.side_effect = RuntimeError("temporary failure")
            scheduler._push_category_to_smartlead(10, 20, "Out Of Office")
            with db.db_session() as conn:
                self.assertIsNone(db.get_lead_state(conn, 20, 10)["smartlead_category"])
            update.side_effect = None
            scheduler._push_category_to_smartlead(10, 20, "Out Of Office")
            with db.db_session() as conn:
                self.assertEqual(db.get_lead_state(conn, 20, 10)["smartlead_category"], "Out Of Office")
            update.assert_called_with(10, 20, 6, pause_lead=False)

    def test_regular_followup_clock_respects_cadence_and_existing_draft(self):
        from app import detector
        now = datetime.now(timezone.utc)
        thread = [detector.NormalizedMessage(
            kind="sent", timestamp=now - timedelta(days=3, hours=12),
            message_id="sent-1", body="Our last message",
        )]
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 20, 10, name="Fred", category="waiting", temperature="warm")
            row = dict(db.get_lead_state(conn, 20, 10))
        with patch.object(settings, "followup_wait_days", (3, 4, 6, 8)), patch.object(
            scheduler.signatures, "is_sendable", return_value=True
        ), patch.object(db, "has_open_draft", return_value=True):
            later = dict(row, followup_count=1)
            self.assertFalse(scheduler._queue_due_followup(later, 10, thread))
            with db.db_session() as conn:
                self.assertEqual(db.get_lead_state(conn, 20, 10)["category"], "waiting")
                db.upsert_lead_state(conn, 20, 10, category="reply")
                stale_reply = dict(db.get_lead_state(conn, 20, 10), followup_count=1)
            self.assertFalse(scheduler._queue_due_followup(stale_reply, 10, thread))
            with db.db_session() as conn:
                self.assertEqual(db.get_lead_state(conn, 20, 10)["category"], "waiting")
            scheduler._queue_due_followup(row, 10, thread)
            with db.db_session() as conn:
                self.assertEqual(db.get_lead_state(conn, 20, 10)["category"], "followup")

    def test_followup_timing_persists_and_recalculates_both_directions(self):
        from app import followup_settings, detector
        timestamp = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        message = dict(kind="sent", timestamp=timestamp, message_id="sent-1", body="Hello")
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 20, 10, interested=1, category="waiting")
            db.put_lead_thread(conn, 20, 10, json.dumps([message]), "sent-1", timestamp)
        with patch.object(settings, "followup_wait_days", (3, 4, 6, 8)), patch.object(
            settings, "hot_followup_wait_hours", 24
        ), patch.object(scheduler.signatures, "is_sendable", return_value=True):
            followup_settings.save({"days": 3, "hot_hours": 0})
            settings.followup_wait_days = (99,)
            followup_settings.load()
            self.assertEqual(settings.followup_wait_days, (3,))
            self.assertEqual(settings.hot_followup_wait_hours, 0)
            followup_settings.refresh_due_statuses()
            with db.db_session() as conn:
                self.assertEqual(db.get_lead_state(conn, 20, 10)["category"], "followup")
            followup_settings.save({"days": 5, "hot_hours": 0})
            followup_settings.refresh_due_statuses()
            with db.db_session() as conn:
                self.assertEqual(db.get_lead_state(conn, 20, 10)["category"], "waiting")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 0)
            with self.assertRaises(ValueError):
                followup_settings.save({"days": 0, "hot_hours": 0})
            self.assertEqual(settings.followup_wait_days, (5,))

    def test_followup_settings_api_validates_and_saves(self):
        client = TestClient(main.app)
        with patch.object(main, "require_auth", return_value=None), patch.object(
            settings, "followup_wait_days", (3, 4, 6, 8)
        ), patch.object(settings, "hot_followup_wait_hours", 24):
            self.assertEqual(client.get("/api/followup-settings").json()["cadence"], [3, 4, 6, 8])
            bad = client.post("/api/followup-settings", json={"days": 2.5, "hot_hours": 0})
            self.assertEqual(bad.status_code, 400)
            saved = client.post("/api/followup-settings", json={"days": 4, "hot_hours": 0})
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["cadence"], [4])
            self.assertEqual(client.get("/api/followup-settings").json()["hot_hours"], 0)

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

    def test_booking_name_fallback_requires_approved_code_and_marks_sheet(self):
        client = TestClient(main.app)
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, 20, 10, interested=1, name="Ben Broughton - Primis",
                email="lead@original.example", category="reply",
            )
        booking_text = """Booking Confirmed
Client Name: Mr Ben Broughton
Email: ben.personal@example.com
Discount Code: OBLACCESS55
"""
        with patch.object(settings, "booking_webhook_secret", ""), patch.object(
            settings, "booking_match_codes", ("OBLACCESS55", "OBLACCESS25")
        ), patch.object(settings, "dry_run", True), patch.object(
            webhook.interested_sheet, "mark_booked_match"
        ) as mark_sheet, patch.object(
            webhook.interested_sheet, "record_booking", return_value="recorded"
        ) as record_booking:
            missing_code = client.post(
                "/webhooks/booking-confirmed",
                json={"name": "Mr Ben Broughton", "email": "different@example.com"},
            )
            self.assertEqual(missing_code.status_code, 404)
            response = client.post(
                "/webhooks/booking-confirmed", json={"body": booking_text}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["matched_by"], "name")
            mark_sheet.assert_called_once_with(
                email="lead@original.example", name="Ben Broughton - Primis", lead_id=20
            )
            self.assertEqual(
                record_booking.call_args.kwargs["attribution"],
                webhook.interested_sheet.ATTRIBUTION_CONTACTED,
            )
        with db.db_session() as conn:
            row = db.get_lead_state(conn, 20, 10)
            self.assertEqual((row["status"], row["category"]), ("booked", "booked"))

    def test_signed_calendly_booking_matches_email_then_trusted_full_name(self):
        client = TestClient(main.app)
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, 20, 10, interested=1, name="Mr Ben Broughton - Primis",
                email="lead@original.example", category="reply",
            )
        payload = {
            "event": "invitee.created",
            "payload": {
                "uri": "https://api.calendly.com/invitees/booking-1",
                "email": "ben.personal@example.com",
                "name": "Ben Broughton",
                "scheduled_event": {
                    "event_type": "https://api.calendly.com/event_types/30min",
                    "start_time": "2026-09-12T09:00:00Z",
                },
            },
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = int(time.time())
        signature = hmac.new(
            b"calendly-test-key",
            str(timestamp).encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        with patch.object(
            settings, "calendly_webhook_signing_key", "calendly-test-key"
        ), patch.object(
            settings, "calendly_event_type_uri",
            "https://api.calendly.com/event_types/30min",
        ), patch.object(settings, "dry_run", True), patch.object(
            webhook.interested_sheet, "mark_booked_match"
        ) as mark_sheet, patch.object(
            webhook.interested_sheet, "record_booking", return_value="recorded"
        ) as record_booking:
            response = client.post(
                "/webhooks/calendly",
                content=raw,
                headers={
                    "content-type": "application/json",
                    "calendly-webhook-signature": f"t={timestamp},v1={signature}",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matched_by"], "name")
        mark_sheet.assert_called_once_with(
            email="lead@original.example", name="Mr Ben Broughton - Primis", lead_id=20
        )
        self.assertEqual(
            record_booking.call_args.kwargs["booking_id"],
            "https://api.calendly.com/invitees/booking-1",
        )
        with db.db_session() as conn:
            row = db.get_lead_state(conn, 20, 10)
            self.assertEqual((row["status"], row["category"]), ("booked", "booked"))

    def test_calendly_rejects_bad_signature_and_ignores_other_event_type(self):
        client = TestClient(main.app)
        payload = {
            "event": "invitee.created",
            "payload": {
                "email": "lead@example.com",
                "name": "Lead Person",
                "scheduled_event": {
                    "event_type": "https://api.calendly.com/event_types/other"
                },
            },
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = int(time.time())
        valid = hmac.new(
            b"calendly-test-key",
            str(timestamp).encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        with patch.object(
            settings, "calendly_webhook_signing_key", "calendly-test-key"
        ), patch.object(
            settings, "calendly_event_type_uri",
            "https://api.calendly.com/event_types/30min",
        ):
            rejected = client.post(
                "/webhooks/calendly",
                content=raw,
                headers={"calendly-webhook-signature": f"t={timestamp},v1=bad"},
            )
            ignored = client.post(
                "/webhooks/calendly",
                content=raw,
                headers={"calendly-webhook-signature": f"t={timestamp},v1={valid}"},
            )
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(ignored.status_code, 200)
        self.assertEqual(ignored.json()["status"], "ignored")

    def test_booking_matches_chris_to_christian_only_with_approved_code(self):
        client = TestClient(main.app)
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, 20, 10, interested=1, name="Chris Roberts",
                email="christian.roberts@sucfin.com", category="reply",
            )
        with patch.object(settings, "booking_webhook_secret", ""), patch.object(
            settings, "booking_match_codes", ("OBLACCESS55",)
        ), patch.object(settings, "dry_run", True), patch.object(
            webhook.interested_sheet, "mark_booked_match"
        ) as mark_sheet, patch.object(
            webhook.interested_sheet, "record_booking", return_value="recorded"
        ):
            response = client.post(
                "/webhooks/booking-confirmed",
                json={
                    "email": "different.personal@gmail.com",
                    "client_name": "Mr Christian Roberts",
                    "discount_code": "OBLACCESS55",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matched_by"], "name")
        mark_sheet.assert_called_once_with(
            email="christian.roberts@sucfin.com", name="Chris Roberts", lead_id=20
        )

    def test_booking_with_shared_code_is_recorded_without_a_smartlead_lead(self):
        client = TestClient(main.app)
        with patch.object(settings, "booking_webhook_secret", ""), patch.object(
            settings, "booking_match_codes", ("OBLACCESS55",)
        ), patch.object(
            webhook.interested_sheet, "record_booking", return_value="recorded"
        ) as record_booking:
            response = client.post(
                "/webhooks/booking-confirmed",
                json={
                    "booking_id": "outlook-message-123",
                    "email": "colleague@example.com",
                    "client_name": "New Colleague",
                    "discount_code": "OBLACCESS55",
                    "location": "Blackfriars",
                    "date": "18 September 2026",
                    "time": "10:00",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["attribution"], "shared_code")
        self.assertEqual(response.json()["matches"], [])
        kwargs = record_booking.call_args.kwargs
        self.assertEqual(kwargs["booking_id"], "outlook-message-123")
        self.assertEqual(kwargs["location"], "Blackfriars")
        self.assertEqual(kwargs["appointment_date"], "18 September 2026")
        self.assertEqual(
            kwargs["attribution"], webhook.interested_sheet.ATTRIBUTION_SHARED
        )

    def test_unmatched_shared_booking_retries_when_sheet_is_unavailable(self):
        client = TestClient(main.app)
        with patch.object(settings, "booking_webhook_secret", ""), patch.object(
            settings, "booking_match_codes", ("OBLACCESS55",)
        ), patch.object(
            webhook.interested_sheet, "record_booking", return_value="failed"
        ):
            response = client.post(
                "/webhooks/booking-confirmed",
                json={
                    "email": "colleague@example.com",
                    "client_name": "New Colleague",
                    "discount_code": "OBLACCESS55",
                },
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_recorded")

    def test_booking_sheet_creates_summary_and_deduplicates_provider_id(self):
        with patch.object(settings, "interested_sheet_id", "sheet-1"), patch.object(
            interested_sheet.sheets, "list_tabs", return_value=[]
        ), patch.object(interested_sheet.sheets, "create_tab") as create_tab, patch.object(
            interested_sheet.sheets, "write_header"
        ), patch.object(interested_sheet.sheets, "write_range") as write_range, patch.object(
            interested_sheet.sheets, "read_column", return_value=["booking_id"]
        ), patch.object(interested_sheet.sheets, "append_row") as append_row:
            status = interested_sheet.record_booking(
                booking_id="provider-123",
                email="colleague@example.com",
                name="New Colleague",
                code="OBLACCESS55",
                location="Blackfriars",
                appointment_date="18 September 2026",
                appointment_time="10:00",
                recorded_at="2026-09-09T12:00:00+00:00",
                attribution=interested_sheet.ATTRIBUTION_SHARED,
            )
        self.assertEqual(status, "recorded")
        self.assertEqual(
            [call.args[1] for call in create_tab.call_args_list],
            [interested_sheet.BOOKINGS_TAB, interested_sheet.BOOKING_SUMMARY_TAB],
        )
        self.assertEqual(write_range.call_count, 4)
        row = append_row.call_args.args[2]
        self.assertEqual(row[0], "provider-123")
        self.assertEqual(row[8], interested_sheet.ATTRIBUTION_SHARED)

    def test_onebody_booking_workflow_forwards_name_and_code(self):
        workflow = json.loads(
            Path("clients/onebodyldn/n8n-booking-workflow.json").read_text(encoding="utf-8")
        )
        nodes = {node["name"]: node for node in workflow["nodes"]}
        extractor = nodes["Extract booked email"]["parameters"]["jsCode"]
        request_body = nodes["Mark booked"]["parameters"]["jsonBody"]
        self.assertIn("discount_code: field('Discount Code')", extractor)
        self.assertIn("booking_id: String($json.id", extractor)
        self.assertIn("client_name: $json.client_name", request_body)
        self.assertIn("discount_code: $json.discount_code", request_body)
        self.assertIn("location: $json.location", request_body)
        self.assertIn("date: $json.date", request_body)
        self.assertIn("time: $json.time", request_body)

    def test_explicit_all_booked_reply_is_deterministic(self):
        label, _ = reply_classifier.classify("Many thanks — all booked!")
        self.assertEqual(label, reply_classifier.BOOKED)
        with patch.object(reply_classifier.llm, "complete_for", return_value=("INTERESTED", {})):
            label, _ = reply_classifier.classify("Sorry, we're all booked up this week")
        self.assertEqual(label, reply_classifier.INTERESTED)

    def test_scan_cannot_unbook_lead_when_smartlead_drifts(self):
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, 20, 10, interested=1, name="Ben", email="ben@example.com"
            )
            db.mark_lead_booked(conn, 20, 10)
        lead = {
            "id": 20, "campaign_id": 10, "email": "ben@example.com",
            "company_name": "Acme", "website": "", "first_name": "Ben",
        }
        with patch.object(scheduler, "_push_category_to_smartlead") as push, patch.object(
            pipeline, "fetch_normalized_thread",
            side_effect=AssertionError("booked lead must not fetch or reopen its thread"),
        ):
            scheduler._process_lead(
                lead, "Campaign", is_booked=False, smartlead_category="Interested"
            )
            push.assert_called_once_with(10, 20, settings.meeting_booked_category_name, pause=True)
        with db.db_session() as conn:
            row = db.get_lead_state(conn, 20, 10)
            self.assertEqual((row["status"], row["category"]), ("booked", "booked"))
            scheduler._mark_lead_waiting_on_them(conn, 20, 10)
        with db.db_session() as conn:
            row = db.get_lead_state(conn, 20, 10)
            self.assertEqual((row["status"], row["category"]), ("booked", "booked"))

    def test_only_manual_category_change_releases_booking(self):
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 20, 10, interested=1, email="ben@example.com")
            db.mark_lead_booked(conn, 20, 10)
        with patch.object(main, "require_auth", return_value=None), patch.object(
            settings, "dry_run", True
        ):
            response = TestClient(main.app).post(
                "/api/leads/10/20/category", json={"category_name": "Interested"}
            )
        self.assertEqual(response.status_code, 200)
        with db.db_session() as conn:
            row = db.get_lead_state(conn, 20, 10)
            self.assertEqual((row["status"], row["category"]), ("active", "waiting"))

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
