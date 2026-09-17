import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import db, detector, main, pipeline, scheduler, sequences, signatures, smartlead
from app.config import settings

LONDON = ZoneInfo("Europe/London")
CAMPAIGN, LEAD = 10, 20


def msg(kind, when, mid, body="Hello"):
    return detector.NormalizedMessage(
        kind=kind, timestamp=when, message_id=mid, body=body,
        from_email="kurt@onebody.test" if kind == "sent" else "lead@example.com",
        to_email="lead@example.com" if kind == "sent" else "kurt@onebody.test",
        stats_id=f"stats-{mid}",
    )


class TimingTests(unittest.TestCase):
    def window(self, **kw):
        base = dict(
            zone="Europe/London", window_start="07:00", window_end="09:00",
            weekdays_only=True, seed="1:1",
        )
        base.update(kw)
        return sequences.compute_send_at(**base)

    def test_delay_counts_calendar_days_from_the_email_into_the_morning_window(self):
        anchor = datetime(2026, 9, 14, 16, 0, tzinfo=LONDON)  # Monday 4pm
        now = anchor + timedelta(minutes=5)
        send = self.window(anchor=anchor, delay_days=2, now=now).astimezone(LONDON)
        self.assertEqual(send.date(), date(2026, 9, 16))  # Wednesday
        self.assertTrue(7 <= send.hour < 9)

    def test_weekend_rolls_to_monday(self):
        anchor = datetime(2026, 9, 18, 10, 0, tzinfo=LONDON)  # Friday
        send = self.window(anchor=anchor, delay_days=1, now=anchor).astimezone(LONDON)
        self.assertEqual(send.date(), date(2026, 9, 21))

    def test_same_seed_gives_the_same_minute(self):
        anchor = datetime(2026, 9, 14, 16, 0, tzinfo=LONDON)
        a = self.window(anchor=anchor, delay_days=2, now=anchor)
        b = self.window(anchor=anchor, delay_days=2, now=anchor)
        c = self.window(anchor=anchor, delay_days=2, now=anchor, seed="1:2")
        self.assertEqual(a, b)
        self.assertEqual(a.date(), c.date())

    def test_late_but_window_still_open_sends_soon_not_tomorrow(self):
        anchor = datetime(2026, 9, 14, 7, 0, tzinfo=LONDON)
        now = datetime(2026, 9, 16, 8, 50, tzinfo=LONDON)
        send = self.window(anchor=anchor, delay_days=2, now=now, seed="x").astimezone(LONDON)
        self.assertEqual(send.date(), date(2026, 9, 16))
        self.assertTrue(now < send < datetime(2026, 9, 16, 9, 0, tzinfo=LONDON))

    def test_window_closed_moves_to_next_weekday_never_the_afternoon(self):
        anchor = datetime(2026, 9, 14, 7, 0, tzinfo=LONDON)
        now = datetime(2026, 9, 18, 15, 0, tzinfo=LONDON)  # Friday afternoon, overdue
        send = self.window(anchor=anchor, delay_days=2, now=now).astimezone(LONDON)
        self.assertEqual(send.date(), date(2026, 9, 21))
        self.assertTrue(7 <= send.hour < 9)

    def test_dst_change_keeps_local_morning(self):
        anchor = datetime(2026, 10, 23, 12, 0, tzinfo=LONDON)  # clocks go back Oct 25
        send = self.window(anchor=anchor, delay_days=3, now=anchor).astimezone(LONDON)
        self.assertEqual(send.date(), date(2026, 10, 26))
        self.assertTrue(7 <= send.hour < 9)
        self.assertEqual(send.utcoffset(), timedelta(0))

    def test_us_leads_use_eight_to_ten_eastern(self):
        seq = {"timezone_mode": "auto", "window_start": "07:00", "window_end": "09:00"}
        lead = {"timezone_guess": "America/New_York", "campaign_name": "HVAC - USA"}
        self.assertEqual(sequences.send_window(seq, lead), ("America/New_York", "08:00", "10:00"))
        seq_ch = dict(seq, timezone_mode="America/Chicago")
        self.assertEqual(sequences.send_window(seq_ch, lead), ("America/New_York", "08:00", "10:00"))

    def test_client_default_zone_beats_the_old_zagreb_fallback(self):
        seq = {"timezone_mode": "auto", "window_start": "07:00", "window_end": "09:00"}
        lead = {"timezone_guess": "Europe/Zagreb", "campaign_name": "Office workers"}
        with patch.object(settings, "default_lead_timezone", "Europe/London"):
            self.assertEqual(sequences.send_window(seq, lead)[0], "Europe/London")
        explicit = dict(seq, timezone_mode="Europe/Berlin")
        self.assertEqual(sequences.send_window(explicit, lead)[0], "Europe/Berlin")


class SequenceFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db_path = settings.db_path
        settings.db_path = str(Path(self.tmp.name) / "test.db")
        db.init_db()
        self.patches = [
            patch.object(signatures, "is_sendable", return_value=True),
            patch.object(signatures, "get_signature_html", return_value="<table>sig</table>"),
            patch.object(settings, "dry_run", True),
            patch.object(settings, "default_lead_timezone", "Europe/London"),
        ]
        for p in self.patches:
            p.start()
        self.anchor = datetime.now(timezone.utc) - timedelta(days=5)
        self.thread = [
            msg("sent", self.anchor - timedelta(days=10), "cold-1"),
            msg("reply", self.anchor - timedelta(days=1), "reply-1", "Yes please"),
            msg("sent", self.anchor, "andrew-1", "Here's the code"),
        ]
        with db.db_session() as conn:
            db.upsert_lead_state(
                conn, LEAD, CAMPAIGN, email="lead@example.com", name="Jane Doe",
                company="Acme Ltd", campaign_name="Office workers", interested=1,
                category="interested_55", smartlead_category="Interested 55",
            )
            self.sequence_id = sequences.create_sequence(
                conn, {"name": "55 min", "trigger_category": "Interested 55"}
            )
            for delay, text in ((2, "<p>Hi {name}, <strong>still</strong> keen?</p>"), (3, "<p>Two</p>"), (4, "<p>Three</p>")):
                sequences.add_step(conn, self.sequence_id, {"delay_days": delay, "body_html": text})

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        settings.db_path = self.old_db_path
        self.tmp.cleanup()

    def enroll(self, thread=None):
        with db.db_session() as conn:
            seq = sequences.get_sequence(conn, self.sequence_id)
            return sequences.enroll(conn, seq, LEAD, CAMPAIGN, thread or self.thread)

    def enrollment(self):
        with db.db_session() as conn:
            return sequences.open_enrollment_for_lead(conn, LEAD, CAMPAIGN) or conn.execute(
                "SELECT * FROM sequence_enrollments ORDER BY id DESC LIMIT 1"
            ).fetchone()

    def draft(self, draft_id):
        with db.db_session() as conn:
            return db.get_draft(conn, draft_id)

    def make_due(self):
        with db.db_session() as conn:
            conn.execute(
                "UPDATE drafts SET scheduled_at = ? WHERE status = 'scheduled'",
                ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
            )

    # --- enrolling ---

    def test_enroll_schedules_first_step_from_andrews_email(self):
        row = self.enroll()
        self.assertEqual(row["state"], "active")
        draft = self.draft(row["draft_id"])
        self.assertEqual(draft["kind"], "sequence")
        self.assertEqual(draft["status"], "scheduled")
        self.assertIn("Hi Jane,", draft["body_html"])
        self.assertIn("<strong>still</strong>", draft["body_html"])
        self.assertEqual(draft["signature_html"], "<table>sig</table>")
        self.assertEqual(datetime.fromisoformat(row["anchor_at"]), self.anchor)

    def test_cannot_enroll_when_lead_wrote_last(self):
        thread = self.thread[:2]
        with self.assertRaises(sequences.SequenceError) as ctx:
            self.enroll(thread)
        self.assertIn("waiting on your reply", str(ctx.exception))

    def test_no_silent_re_enrollment(self):
        self.enroll()
        with db.db_session() as conn:
            sequences.remove(conn, self.enrollment()["id"])
        with self.assertRaises(sequences.SequenceError) as ctx:
            self.enroll()
        self.assertIn("Re-enroll", str(ctx.exception))
        with db.db_session() as conn:
            seq = sequences.get_sequence(conn, self.sequence_id)
            row = sequences.enroll(conn, seq, LEAD, CAMPAIGN, self.thread, re_enroll=True)
        self.assertEqual(row["state"], "active")

    def test_enroll_dismisses_ai_followup_candidate(self):
        with db.db_session() as conn:
            db.upsert_candidate(conn, LEAD, CAMPAIGN, "followup", reason="due")
        self.enroll()
        with db.db_session() as conn:
            status = conn.execute("SELECT status FROM candidates").fetchone()["status"]
        self.assertEqual(status, "dismissed")

    # --- sending ---

    def test_due_steps_send_in_order_then_finish(self):
        self.enroll()
        for step in (1, 2, 3):
            self.make_due()
            with patch.object(pipeline, "fetch_normalized_thread", return_value=self.thread):
                scheduler.run_due_send_loop()
            row = self.enrollment()
            self.assertEqual(row["steps_sent"], step)
        self.assertEqual(row["state"], "completed")
        self.assertEqual(row["pending_category"], "Sequence finished")
        with db.db_session() as conn:
            kinds = conn.execute("SELECT status FROM drafts WHERE kind='sequence'").fetchall()
            lead = db.get_lead_state(conn, LEAD, CAMPAIGN)
        self.assertEqual([k["status"] for k in kinds], ["sent", "sent", "sent"])
        # Sending a step must not put the lead on the AI follow-up clock.
        self.assertNotEqual(lead["category"], "waiting")

    def test_housekeeping_writes_finish_category(self):
        self.enroll()
        with db.db_session() as conn:
            conn.execute("UPDATE sequence_enrollments SET state='completed', pending_category='Sequence finished'")
        with patch.object(settings, "dry_run", False), patch.object(
            smartlead, "fetch_categories", return_value={"Sequence finished": 9}
        ), patch.object(smartlead, "update_lead_category") as update:
            sequences.run_housekeeping()
        update.assert_called_once_with(CAMPAIGN, LEAD, 9, pause_lead=False)
        self.assertIsNone(self.enrollment()["pending_category"])

    def test_claimed_draft_is_not_sent_twice(self):
        row = self.enroll()
        self.make_due()
        with db.db_session() as conn:
            db.update_draft(conn, row["draft_id"], status="sending")
        with patch.object(scheduler, "_send_due_draft") as send:
            scheduler.run_due_send_loop()
        send.assert_not_called()

    def test_two_send_failures_stop_with_error(self):
        self.enroll()
        with patch.object(settings, "dry_run", False), patch.object(
            pipeline, "fetch_normalized_thread", return_value=self.thread
        ), patch.object(sequences, "presend_check", return_value=sequences.SEND), patch.object(
            smartlead, "reply_to_thread", side_effect=RuntimeError("boom")
        ):
            self.make_due()
            scheduler.run_due_send_loop()
            self.assertEqual(self.enrollment()["send_failures"], 1)
            self.assertEqual(self.enrollment()["state"], "active")
            self.make_due()
            scheduler.run_due_send_loop()
        self.assertEqual(self.enrollment()["state"], "error")

    # --- stopping (the plan's test matrix) ---

    def test_reply_stops_sequence_and_queues_interested(self):
        row = self.enroll()
        with db.db_session() as conn:
            db.mark_lead_replied(
                conn, LEAD, CAMPAIGN, preview="Question",
                received_at=datetime.now(timezone.utc).isoformat(),
            )
        stopped = self.enrollment()
        self.assertEqual(stopped["state"], "stopped")
        self.assertEqual(stopped["stop_reason"], "replied")
        self.assertEqual(stopped["pending_category"], "Interested")
        self.assertEqual(self.draft(row["draft_id"])["status"], "stale")

    def test_old_reply_seen_again_does_not_stop(self):
        self.enroll()
        with db.db_session() as conn:
            db.mark_lead_replied(
                conn, LEAD, CAMPAIGN, preview="Yes please",
                received_at=(self.anchor - timedelta(days=1)).isoformat(),
            )
        self.assertEqual(self.enrollment()["state"], "active")

    def test_booking_stops_sequence(self):
        self.enroll()
        with db.db_session() as conn:
            db.mark_lead_booked(conn, LEAD, CAMPAIGN)
        self.assertEqual(self.enrollment()["stop_reason"], "booked")
        self.assertIsNone(self.enrollment()["pending_category"])

    def test_do_not_contact_stops_sequence(self):
        self.enroll()
        with db.db_session() as conn:
            db.mark_lead_do_not_contact(conn, LEAD, CAMPAIGN)
        self.assertEqual(self.enrollment()["stop_reason"], "dnc")

    def test_presend_catches_reply_every_other_path_missed(self):
        self.enroll()
        self.make_due()
        replied = self.thread + [msg("reply", datetime.now(timezone.utc) - timedelta(minutes=2), "reply-2")]
        with patch.object(pipeline, "fetch_normalized_thread", return_value=replied), patch.object(
            smartlead, "reply_to_thread"
        ) as send:
            scheduler.run_due_send_loop()
        send.assert_not_called()
        self.assertEqual(self.enrollment()["stop_reason"], "replied")

    def live_send(self, record, categories=None):
        self.make_due()
        with patch.object(settings, "dry_run", False), patch.object(
            pipeline, "fetch_normalized_thread", return_value=self.thread
        ), patch.object(smartlead, "get_lead_by_email", return_value=record), patch.object(
            smartlead, "fetch_categories",
            return_value=categories or {"Interested": 1, "Interested 55": 55, "Meeting-Booked": 6},
        ), patch.object(smartlead, "reply_to_thread", return_value="queued") as send:
            scheduler.run_due_send_loop()
        return send

    def campaign_row(self, category_id, last_reply_at=None):
        return {"lead_campaign_data": [
            {"campaign_id": CAMPAIGN, "lead_category_id": category_id, "last_reply_at": last_reply_at}
        ]}

    def test_live_send_goes_out_when_still_in_trigger_category(self):
        self.enroll()
        send = self.live_send(self.campaign_row(55))
        send.assert_called_once()
        self.assertIn("<table>sig</table>", send.call_args.args[1])
        self.assertEqual(self.enrollment()["steps_sent"], 1)

    def test_booked_in_smartlead_ui_is_caught_before_send(self):
        self.enroll()
        send = self.live_send(self.campaign_row(6))
        send.assert_not_called()
        self.assertEqual(self.enrollment()["stop_reason"], "booked")
        with db.db_session() as conn:
            self.assertEqual(db.get_lead_state(conn, LEAD, CAMPAIGN)["status"], "booked")

    def test_status_changed_in_smartlead_ui_is_caught_before_send(self):
        self.enroll()
        send = self.live_send(self.campaign_row(1))
        send.assert_not_called()
        self.assertEqual(self.enrollment()["stop_reason"], "status_changed")

    def test_smartlead_reply_time_is_caught_before_send(self):
        self.enroll()
        send = self.live_send(self.campaign_row(55, datetime.now(timezone.utc).isoformat()))
        send.assert_not_called()
        self.assertEqual(self.enrollment()["stop_reason"], "replied")

    def test_smartlead_lookup_failure_waits_instead_of_sending(self):
        row = self.enroll()
        self.make_due()
        with patch.object(settings, "dry_run", False), patch.object(
            pipeline, "fetch_normalized_thread", return_value=self.thread
        ), patch.object(smartlead, "get_lead_by_email", side_effect=RuntimeError("429")), patch.object(
            smartlead, "reply_to_thread"
        ) as send:
            scheduler.run_due_send_loop()
        send.assert_not_called()
        self.assertEqual(self.draft(row["draft_id"])["status"], "scheduled")
        self.assertEqual(self.enrollment()["state"], "active")

    def test_retired_mailbox_stops_sequence(self):
        self.enroll()
        self.make_due()
        with patch.object(settings, "dry_run", False), patch.object(
            pipeline, "fetch_normalized_thread", return_value=self.thread
        ), patch.object(sequences, "presend_check", return_value=sequences.SEND), patch.object(
            signatures, "is_sendable", return_value=False
        ), patch.object(smartlead, "reply_to_thread") as send:
            scheduler.run_due_send_loop()
        send.assert_not_called()
        self.assertEqual(self.enrollment()["stop_reason"], "mailbox_dead")

    def test_smartlead_category_change_stops_after_grace_but_not_paused(self):
        self.enroll()
        with patch.object(settings, "dry_run", False):
            sequences.on_smartlead_category(LEAD, CAMPAIGN, "Not Interested")
            self.assertEqual(self.enrollment()["state"], "active")  # inside the grace window
            with db.db_session() as conn:
                conn.execute(
                    "UPDATE sequence_enrollments SET enrolled_at = ?",
                    ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),),
                )
            sequences.on_smartlead_category(LEAD, CAMPAIGN, "Interested 55")
            self.assertEqual(self.enrollment()["state"], "active")
            sequences.on_smartlead_category(LEAD, CAMPAIGN, "Not Interested")
        self.assertEqual(self.enrollment()["stop_reason"], "status_changed")

    def test_ai_followup_clock_skips_enrolled_lead(self):
        self.enroll()
        with db.db_session() as conn:
            row = db.get_lead_state(conn, LEAD, CAMPAIGN)
            conn.execute("UPDATE leads_state SET category='waiting'")
            row = db.get_lead_state(conn, LEAD, CAMPAIGN)
        self.assertFalse(scheduler._queue_due_followup(row, CAMPAIGN, self.thread))

    # --- out of office ---

    def test_out_of_office_pauses_and_resume_restarts(self):
        self.enroll()
        ooo_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        with db.db_session() as conn:
            db.mark_lead_replied(conn, LEAD, CAMPAIGN, preview="Away", received_at=ooo_at.isoformat())
            db.sort_replied_lead(conn, LEAD, CAMPAIGN, "auto_reply", message_id="ooo-1")
        paused = self.enrollment()
        self.assertEqual((paused["state"], paused["stop_reason"]), ("paused", "auto_reply"))
        self.assertIsNone(paused["pending_category"])

        # The reply-catch pass replays the same out-of-office every tick.
        with db.db_session() as conn:
            db.mark_lead_replied(conn, LEAD, CAMPAIGN, preview="Away", received_at=ooo_at.isoformat())
            db.sort_replied_lead(conn, LEAD, CAMPAIGN, "auto_reply", message_id="ooo-1")
        self.assertEqual(self.enrollment()["state"], "paused")

        thread = self.thread + [msg("reply", ooo_at, "ooo-1", "Out of office until Monday")]
        with db.db_session() as conn:
            row = sequences.resume(conn, paused["id"], thread, in_days=3)
        self.assertEqual(row["state"], "active")
        self.assertEqual(row["pending_category"], "Interested 55")
        send_at = datetime.fromisoformat(row["next_send_at"])
        self.assertGreaterEqual(send_at, datetime.now(timezone.utc) + timedelta(days=2))

    def test_resume_refused_after_a_real_reply(self):
        self.enroll()
        with db.db_session() as conn:
            sequences.pause(conn, self.enrollment()["id"])
            paused = self.enrollment()
        later = datetime.now(timezone.utc) + timedelta(seconds=5)
        thread = self.thread + [msg("reply", later, "reply-3")]
        with db.db_session() as conn, self.assertRaises(sequences.SequenceError):
            sequences.resume(conn, paused["id"], thread)

    def test_return_date_is_read_once(self):
        self.enroll()
        with db.db_session() as conn:
            conn.execute(
                "UPDATE sequence_enrollments SET state='paused', stop_reason='auto_reply', resume_checked=0"
            )
        ooo = self.thread + [msg("reply", datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc), "ooo", "Back Monday")]
        pipeline.cache_normalized_thread(CAMPAIGN, LEAD, ooo)
        from app import llm
        with patch.object(llm, "complete_for", return_value=("2026-09-21", "m")) as call:
            sequences.run_housekeeping()
            sequences.run_housekeeping()
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.enrollment()["suggested_resume_at"], "2026-09-21")

    def test_interested_push_waits_for_classifier_and_respects_moves(self):
        self.enroll()
        with db.db_session() as conn:
            db.mark_lead_replied(
                conn, LEAD, CAMPAIGN, preview="?", received_at=datetime.now(timezone.utc).isoformat()
            )
        with patch.object(settings, "dry_run", False), patch.object(
            smartlead, "fetch_categories", return_value={"Interested": 1}
        ), patch.object(smartlead, "update_lead_category") as update:
            sequences.run_housekeeping()
            update.assert_not_called()  # still inside CATEGORY_PUSH_DELAY
            sequences.run_housekeeping(now=datetime.now(timezone.utc) + timedelta(minutes=5))
            update.assert_called_once_with(CAMPAIGN, LEAD, 1, pause_lead=False)

    # --- editing ---

    def test_editing_a_step_rerenders_queued_email_unless_hand_edited(self):
        row = self.enroll()
        with db.db_session() as conn:
            step_id = sequences.get_steps(conn, self.sequence_id)[0]["id"]
            sequences.update_step(conn, self.sequence_id, step_id, {"body_html": "<p>New {name}</p>"})
            new = sequences.open_enrollment_for_lead(conn, LEAD, CAMPAIGN)
            self.assertEqual(db.get_draft(conn, new["draft_id"])["body_html"], "<p>New Jane</p>")
            self.assertEqual(db.get_draft(conn, new["draft_id"])["scheduled_at"], self.draft(row["draft_id"])["scheduled_at"])
            db.update_draft(conn, new["draft_id"], body_html="<p>My own words</p>")
            sequences.update_step(conn, self.sequence_id, step_id, {"body_html": "<p>Newer</p>"})
            newest = sequences.open_enrollment_for_lead(conn, LEAD, CAMPAIGN)
            self.assertEqual(db.get_draft(conn, newest["draft_id"])["body_html"], "<p>My own words</p>")

    def test_switching_sequence_off_pulls_queued_email(self):
        row = self.enroll()
        with db.db_session() as conn:
            sequences.update_sequence(conn, self.sequence_id, {"active": False})
        self.assertEqual(self.draft(row["draft_id"])["status"], "skipped")
        self.assertIsNone(self.enrollment()["draft_id"])
        with db.db_session() as conn:
            sequences.update_sequence(conn, self.sequence_id, {"active": True})
        self.assertIsNotNone(self.enrollment()["draft_id"])

    def test_trigger_cannot_reuse_a_status_the_app_owns(self):
        with db.db_session() as conn, self.assertRaises(sequences.SequenceError):
            sequences.create_sequence(conn, {"name": "x", "trigger_category": "Meeting booked"})

    # --- dashboard status change ---

    def test_status_dropdown_enrolls_and_refuses_cleanly(self):
        client = TestClient(main.app)
        with patch.object(main, "require_auth", return_value=None), patch.object(
            pipeline, "fetch_normalized_thread", return_value=self.thread
        ):
            ok = client.post(f"/api/leads/{CAMPAIGN}/{LEAD}/category", json={"category_name": "Interested 55"})
            self.assertEqual(ok.status_code, 200, ok.text)
            self.assertEqual(ok.json()["enrollment"]["state"], "active")
            again = client.post(f"/api/leads/{CAMPAIGN}/{LEAD}/category", json={"category_name": "Interested 55"})
            self.assertEqual(again.status_code, 409)
            moved = client.post(f"/api/leads/{CAMPAIGN}/{LEAD}/category", json={"category_name": "Interested"})
            self.assertEqual(moved.status_code, 200)
        self.assertEqual(self.enrollment()["stop_reason"], "status_changed")

    def test_retired_sequence_draft_is_requeued(self):
        row = self.enroll()
        with db.db_session() as conn:
            # e.g. a Regenerate on the lead's page retiring every open draft
            db.update_draft(conn, row["draft_id"], status="skipped")
        sequences.run_housekeeping()
        healed = self.enrollment()
        self.assertEqual(healed["state"], "active")
        self.assertNotEqual(healed["draft_id"], row["draft_id"])
        self.assertEqual(self.draft(healed["draft_id"])["step_position"], 1)
        self.assertEqual(self.draft(healed["draft_id"])["scheduled_at"], self.draft(row["draft_id"])["scheduled_at"])

    def test_cancel_on_scheduled_tab_skips_to_next_email(self):
        row = self.enroll()
        client = TestClient(main.app)
        with patch.object(main, "require_auth", return_value=None):
            response = client.post(f"/api/drafts/{row['draft_id']}/skip")
        self.assertEqual(response.status_code, 200)
        after = self.enrollment()
        self.assertEqual(after["steps_sent"], 1)
        self.assertEqual(self.draft(after["draft_id"])["step_position"], 2)

    def test_adopt_poll_stops_sequence_on_new_reply(self):
        self.enroll()
        now = datetime.now(timezone.utc).isoformat()
        with patch.object(smartlead, "list_recent_replies", return_value=[{
            "email_lead_id": LEAD, "email_campaign_id": CAMPAIGN, "last_reply_time": now,
            "lead_category_id": 55,
        }]), patch.object(smartlead, "fetch_categories", return_value={"Interested 55": 55}):
            scheduler._adopt_unknown_repliers()
        self.assertEqual(self.enrollment()["stop_reason"], "replied")


if __name__ == "__main__":
    unittest.main()
