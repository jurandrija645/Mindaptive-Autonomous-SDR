import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, main, smartlead, subsequence_overview
from app.config import settings


class SubsequenceOverviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        change = patch.object(settings, "db_path", str(Path(self.tmp.name) / "test.db"))
        change.start()
        self.addCleanup(change.stop)
        db.init_db()
        pacing = patch.object(subsequence_overview, "_pace_read")
        pacing.start()
        self.addCleanup(pacing.stop)
        self.child = {"id": 11, "parent_campaign_id": 10, "name": "Physio", "status": "ACTIVE"}
        self.member = {"campaign_lead_map_id": "100", "status": "STARTED",
                       "lead": {"id": 20, "first_name": "Sam", "email": "sam@example.com"}}

    def mapping(self, status="STARTED", active=True):
        return {"id": "100", "email_campaign_id": "11", "status": status,
                "is_active": active, "next_timestamp_to_reach": "2026-11-04 10:00:00+00",
                "email_campaign": {"sequence_count": 4}}

    def test_native_counts_only_distinct_sent_steps_and_uses_live_schedule(self):
        details = [{"status": "SENT", "email_campaign_seq_id": 1},
                   {"status": "SENT", "email_campaign_seq_id": 1},
                   {"status": "DRAFTED", "email_campaign_seq_id": 2},
                   {"status": "STOPPED", "email_campaign_seq_id": 3}]
        with patch.object(smartlead, "get_lead_campaign_overview", return_value={"email_campaign_leads_mappings": [self.mapping()]}), patch.object(smartlead, "get_lead_sequence_details", return_value=details):
            result = subsequence_overview._native_member(self.child, self.member)
        self.assertEqual((result["sent"], result["total"]), (1, 4))
        self.assertEqual(result["next_send_at"], "2026-11-04 10:00:00+00")
        self.assertEqual(result["campaign_id"], 10)

    def test_paused_or_inactive_does_not_advertise_a_next_send(self):
        for mapping, child in [(self.mapping("PAUSED"), self.child), (self.mapping(active=False), self.child), (self.mapping(), dict(self.child, status="PAUSED"))]:
            with self.subTest(mapping=mapping, child=child), patch.object(smartlead, "get_lead_campaign_overview", return_value={"email_campaign_leads_mappings": [mapping]}), patch.object(smartlead, "get_lead_sequence_details", return_value=[]):
                result = subsequence_overview._native_member(child, self.member)
                self.assertIsNone(result["next_send_at"])

    def test_failed_reads_are_unknown_not_zero(self):
        with patch.object(smartlead, "get_lead_campaign_overview", side_effect=RuntimeError("offline")), patch.object(smartlead, "get_lead_sequence_details", side_effect=RuntimeError("offline")):
            result = subsequence_overview._native_member(self.child, self.member)
        self.assertIsNone(result["sent"])
        self.assertIsNone(result["next_send_at"])
        self.assertEqual(len(result["warnings"]), 2)

    def test_archive_hides_automatic_sequence_archive_but_not_manual(self):
        with db.db_session() as conn:
            now = db.now_iso()
            seq = conn.execute("INSERT INTO sequences (name, trigger_category, created_at, updated_at) VALUES (?, ?, ?, ?)", ("Test", "Sequence trigger", now, now)).lastrowid
            for lid, reason in [(20, "Sequence trigger"), (21, "manual")]:
                db.upsert_lead_state(conn, lid, 10, name=str(lid), archived_at=now, archive_reason=reason)
                conn.execute("INSERT INTO sequence_enrollments (sequence_id, lead_id, campaign_id, state, anchor_at, enrolled_at) VALUES (?, ?, 10, 'active', ?, ?)", (seq, lid, now, now))
        self.assertEqual([r["lead_id"] for r in main._archive_payload()["archived"]], [21])


if __name__ == "__main__":
    unittest.main()
