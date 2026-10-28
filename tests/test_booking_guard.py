import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from app import booking_guard, db, detector, main, pipeline, scheduler, signatures, smartlead
from app.config import settings


def mapping(cid, status="STARTED", category=None):
    return {"id": str(cid + 1000), "email_campaign_id": str(cid),
            "status": status, "lead_category_id": category, "is_active": True}


class BookingGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(settings, "db_path", str(Path(self.tmp.name) / "test.db"))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.dry = patch.object(settings, "dry_run", False)
        self.dry.start()
        self.addCleanup(self.dry.stop)
        self.category = patch.object(settings, "meeting_booked_category_name", "Meeting-Booked")
        self.category.start()
        self.addCleanup(self.category.stop)
        db.init_db()
        with db.db_session() as conn:
            for cid in (10, 11):
                db.upsert_lead_state(conn, 20, cid, email="lead@example.com", name="Lead", status="active")
        # Any unintended real network access fails immediately.
        self.network = patch.object(smartlead, "_request", side_effect=AssertionError("Unexpected network"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def book(self, cid=10):
        with db.db_session() as conn:
            db.mark_lead_booked(conn, 20, cid)

    def test_local_booking_in_another_campaign_stops_every_draft_kind_before_thread_fetch(self):
        self.book()
        for kind in ("reply", "autoreply", "followup", "sequence"):
            with self.subTest(kind=kind), db.db_session() as conn:
                did = db.create_draft(conn, lead_id=20, campaign_id=11, kind=kind,
                    triage_summary="test", body_html="test", status="sending")
            with db.db_session() as conn:
                draft = dict(db.get_draft(conn, did))
            with patch.object(pipeline, "fetch_normalized_thread") as thread, patch.object(smartlead, "reply_to_thread") as send:
                self.assertEqual(scheduler._send_due_draft(draft), "stale")
            thread.assert_not_called()
            send.assert_not_called()
            with db.db_session() as conn:
                self.assertEqual(db.get_draft(conn, did)["status"], "stale")

    def test_remote_parent_booking_blocks_child_even_if_local_status_is_stale(self):
        overview={"email": "lead@example.com", "email_campaign_leads_mappings": [mapping(10, "PAUSED", 7), mapping(11)]}
        with patch.object(smartlead, "get_lead_campaign_overview", return_value=overview), patch.object(
            smartlead, "fetch_categories", return_value={"MEETING booked":7}
        ), patch.object(smartlead, "pause_campaign_lead") as pause:
            self.assertFalse(booking_guard.allow_send(20, 11))
        pause.assert_called_once_with(11, 20)
        with db.db_session() as conn:
            self.assertTrue(all(r[0]=="booked" for r in conn.execute("SELECT status FROM leads_state")))

    def test_unreadable_or_missing_remote_category_fails_closed(self):
        with patch.object(smartlead, "get_lead_campaign_overview", side_effect=smartlead.SmartleadError("offline")):
            with self.assertRaises(smartlead.SmartleadError):
                booking_guard.allow_send(20, 11)
        with patch.object(smartlead, "get_lead_campaign_overview", return_value={"email_campaign_leads_mappings":[mapping(11)]}), patch.object(
            smartlead, "fetch_categories", return_value={"Interested":1}
        ):
            with self.assertRaises(smartlead.SmartleadError):
                booking_guard.allow_send(20, 11)

    def test_nonbooked_lead_can_send_and_missing_campaign_cannot(self):
        with patch.object(smartlead, "get_lead_campaign_overview", return_value={"email_campaign_leads_mappings":[mapping(11)]}), patch.object(
            smartlead, "fetch_categories", return_value={"Meeting Booked":7}
        ):
            self.assertTrue(booking_guard.allow_send(20,11))
            with self.assertRaises(smartlead.SmartleadError):
                booking_guard.allow_send(20,99)

    def test_booking_during_live_check_is_seen_before_send(self):
        def read(_):
            self.book()
            return {"email_campaign_leads_mappings":[mapping(11)]}
        with patch.object(smartlead, "get_lead_campaign_overview", side_effect=read), patch.object(
            smartlead, "fetch_categories", return_value={"Meeting Booked":7}
        ):
            self.assertFalse(booking_guard.allow_send(20,11))

    def test_send_path_never_calls_send_endpoint_if_live_booking_or_lookup_failure(self):
        thread=[detector.NormalizedMessage(kind="sent",timestamp=datetime.now(timezone.utc),
            message_id="outbound",body="Hello",from_email="sender@example.com",to_email="lead@example.com",stats_id="s1")]
        for outcome in (False,smartlead.SmartleadError("booking lookup offline")):
            with self.subTest(outcome=outcome), db.db_session() as conn:
                did=db.create_draft(conn,lead_id=20,campaign_id=11,kind="followup",triage_summary="test",body_html="test",status="sending")
            with db.db_session() as conn:
                draft=dict(db.get_draft(conn,did))
            with patch.object(pipeline,"fetch_normalized_thread",return_value=thread), patch.object(
                signatures,"is_sendable",return_value=True
            ), patch.object(signatures,"get_signature_html",return_value=""), patch.object(
                booking_guard,"allow_send",side_effect=outcome if isinstance(outcome,Exception) else None,return_value=outcome
            ), patch.object(smartlead,"reply_to_thread") as send:
                if isinstance(outcome,Exception):
                    with self.assertRaises(smartlead.SmartleadError):
                        scheduler._send_due_draft(draft)
                else:
                    self.assertEqual(scheduler._send_due_draft(draft),"stale")
            send.assert_not_called()

    def test_pause_all_active_mappings_but_never_resume_or_touch_unrelated_people(self):
        with db.db_session() as conn:
            db.upsert_lead_state(conn,21,10,email="other@example.com",status="active")
        overview={"email_campaign_leads_mappings":[mapping(10),mapping(11,"INPROGRESS"),mapping(12,"PAUSED"),mapping(13,"COMPLETED")]}
        with patch.object(smartlead,"get_lead_campaign_overview",return_value=overview), patch.object(smartlead,"pause_campaign_lead") as pause:
            outcome=booking_guard.enforce_booked_lead(20,10)
        self.assertEqual(outcome,{"paused":[10,11],"errors":[]})
        self.assertEqual(pause.call_count,2)
        with db.db_session() as conn:
            self.assertEqual(db.get_lead_state(conn,21,10)["status"],"active")

    def test_dry_run_freezes_locally_without_remote_writes(self):
        with patch.object(settings,"dry_run",True), patch.object(smartlead,"get_lead_campaign_overview") as remote:
            booking_guard.enforce_booked_lead(20,10)
            self.assertFalse(booking_guard.allow_send(20,11))
        remote.assert_not_called()

    def test_failed_pause_persists_and_retries_after_restart_even_without_children(self):
        overview={"email_campaign_leads_mappings":[mapping(11)]}
        with patch.object(smartlead,"get_lead_campaign_overview",return_value=overview), patch.object(
            smartlead,"pause_campaign_lead",side_effect=smartlead.SmartleadError("offline")
        ):
            self.assertTrue(booking_guard.enforce_booked_lead(20,10)["errors"])
        with db.db_session() as conn:
            self.assertIsNotNone(db.get_setting(conn,"booked_pause_pending:20"))
        with patch.object(smartlead,"get_lead_campaign_overview",return_value=overview), patch.object(
            smartlead,"pause_campaign_lead"
        ) as pause, patch.object(smartlead,"list_campaigns",return_value=[]):
            self.assertEqual(booking_guard.run_native_booking_guard()["paused"],1)
        pause.assert_called_once_with(11,20)
        with db.db_session() as conn:
            self.assertIsNone(db.get_setting(conn,"booked_pause_pending:20"))

    def test_sweep_catches_booked_parent_and_preserves_eligible_children(self):
        def leads(cid,**kw):
            if cid==10:
                self.assertEqual(kw,{"category_id":7})
                return [{"lead_category_id":7,"lead":{"id":20,"email":"lead@example.com"}}]
            return [{"status":"STARTED","lead":{"id":lid,"email":email}} for lid,email in [(20,"lead@example.com"),(21,"other@example.com")]]
        with patch.object(smartlead,"list_campaigns",return_value=[{"id":11,"parent_campaign_id":10,"status":"ACTIVE"}]), patch.object(
            smartlead,"fetch_categories",return_value={"Meeting Booked":7}
        ), patch.object(smartlead,"list_campaign_leads",side_effect=leads), patch.object(
            smartlead,"get_lead_campaign_overview",return_value={"email_campaign_leads_mappings":[mapping(11)]}
        ), patch.object(smartlead,"pause_campaign_lead") as pause:
            self.assertEqual(booking_guard.run_native_booking_guard(),{"checked":2,"paused":1,"errors":0})
        pause.assert_called_once_with(11,20)

    def test_booking_hook_freezes_before_remote_calls_and_does_not_hold_a_write_transaction(self):
        def pause(_):
            with db.db_session() as conn:
                self.assertEqual(db.get_lead_state(conn,20,10)["status"],"booked")
                db.set_setting(conn,"parallel-writer","worked")
            return {"email_campaign_leads_mappings":[]}
        with patch.object(smartlead,"get_lead_campaign_overview",side_effect=pause), patch.object(
            scheduler,"_push_category_to_smartlead"
        ), patch.object(scheduler.interested_sheet,"mark_booked_match"):
            scheduler.record_explicit_booking(20,10,record_sheet=False)

    def test_dashboard_booking_pauses_native_child_before_returning(self):
        with patch.object(main,"require_auth",return_value=None), patch.object(
            smartlead,"fetch_categories",return_value={"Meeting-Booked":7}
        ), patch.object(smartlead,"update_lead_category"), patch.object(
            smartlead,"get_lead_campaign_overview",return_value={"email_campaign_leads_mappings":[mapping(10,"PAUSED",7),mapping(11)]}
        ), patch.object(smartlead,"pause_campaign_lead") as pause:
            response=TestClient(main.app).post('/api/leads/10/20/category',json={"category_name":"Meeting-Booked"})
        self.assertEqual(response.status_code,200,response.text)
        pause.assert_called_once_with(11,20)

    def test_sweep_still_enforces_local_booking_when_remote_parent_listing_fails(self):
        self.book()
        def leads(cid,**kw):
            if cid==10:
                raise smartlead.SmartleadError('parent unavailable')
            return [{"status":"STARTED","lead":{"id":20,"email":"lead@example.com"}}]
        with patch.object(smartlead,"list_campaigns",return_value=[{"id":11,"parent_campaign_id":10,"status":"ACTIVE"}]), patch.object(
            smartlead,"fetch_categories",return_value={"Meeting Booked":7}
        ), patch.object(smartlead,"list_campaign_leads",side_effect=leads), patch.object(
            smartlead,"get_lead_campaign_overview",return_value={"email_campaign_leads_mappings":[mapping(11)]}
        ), patch.object(smartlead,"pause_campaign_lead") as pause:
            result=booking_guard.run_native_booking_guard()
        self.assertEqual(result,{"checked":1,"paused":1,"errors":1})
        pause.assert_called_once_with(11,20)


class BookingAdapterTests(unittest.TestCase):
    def test_filtered_booked_listing_paginates_and_preserves_envelopes(self):
        rows=[{"lead":{"id":i}} for i in range(100)]
        with patch.object(smartlead,"_request",side_effect=[{"data":rows},[{"lead":{"id":101}}]]) as request:
            self.assertEqual(len(list(smartlead.list_campaign_leads(10,category_id=7))),101)
        self.assertEqual(request.call_args_list[1].kwargs["params"],{"offset":100,"limit":100,"lead_category_id":7})

    def test_overview_rejects_missing_or_invalid_mappings(self):
        for value in ({},None,{"data":{}},{"data":{"email_campaign_leads_mappings":None}}):
            with self.subTest(value=value), patch.object(smartlead,"_request",return_value=value):
                with self.assertRaises(smartlead.SmartleadError):
                    smartlead.get_lead_campaign_overview(20)


if __name__=="__main__":
    unittest.main()
