import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import crm, db, main
from app.config import settings


class CrmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(settings, "db_path", str(Path(self.tmp.name) / "t.db")),
            patch.object(crm, "require_auth", lambda request: None),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def lead(self, lead_id, **fields):
        with db.db_session() as conn:
            db.upsert_lead_state(conn, lead_id, 1, name=f"Lead {lead_id}", company="Acme",
                                 email=f"l{lead_id}@acme.test", **fields)

    def board(self):
        return self.client.get("/api/crm/board").json()

    def test_booking_creates_a_deal_in_the_first_column(self):
        self.lead(1)
        with db.db_session() as conn:
            db.mark_lead_booked(conn, 1, 1)
        deals = self.board()["deals"]
        self.assertEqual([(d["lead_id"], d["stage"]) for d in deals], [(1, "meeting_booked")])

    def test_board_backfills_bookings_recorded_before_the_crm(self):
        self.lead(2, status="booked", booked_at="2026-08-01T10:00:00+00:00")
        deals = self.board()["deals"]
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["stage_changed_at"], "2026-08-01T10:00:00+00:00")

    def test_removed_deal_is_not_resurrected_by_sync_but_can_be_added_back(self):
        self.lead(3)
        with db.db_session() as conn:
            db.mark_lead_booked(conn, 3, 1)
        deal_id = self.board()["deals"][0]["id"]
        self.client.delete(f"/api/crm/deals/{deal_id}")
        with db.db_session() as conn:
            db.mark_lead_booked(conn, 3, 1)
        self.assertEqual(self.board()["deals"], [])
        res = self.client.post("/api/crm/deals", json={"campaign_id": 1, "lead_id": 3}).json()
        self.assertEqual(res["id"], deal_id)
        self.assertEqual(len(self.board()["deals"]), 1)

    def test_move_orders_the_column_and_logs_the_stage_change(self):
        for i in (4, 5):
            self.lead(i)
            self.client.post("/api/crm/deals", json={"campaign_id": 1, "lead_id": i})
        ids = {d["lead_id"]: d["id"] for d in self.board()["deals"]}
        self.client.post(f"/api/crm/deals/{ids[4]}/move", json={"stage": "negotiating", "before_id": None})
        self.client.post(f"/api/crm/deals/{ids[5]}/move", json={"stage": "negotiating", "before_id": ids[4]})
        col = [d["lead_id"] for d in self.board()["deals"] if d["stage"] == "negotiating"]
        self.assertEqual(col, [5, 4])
        items = self.client.get(f"/api/crm/deals/{ids[4]}").json()["items"]
        self.assertTrue(any(i["kind"] == "event" and "Negotiating" in i["body"] for i in items))

    def test_items_todo_link_and_next_step_on_the_card(self):
        res = self.client.post("/api/crm/deals", json={"name": "Jane", "company": "Walk-in Ltd"}).json()
        deal_id = res["id"]
        self.client.post(f"/api/crm/deals/{deal_id}/items", json={"kind": "todo", "title": "Send proposal", "due_date": "2026-09-20"})
        bad = self.client.post(f"/api/crm/deals/{deal_id}/items", json={"kind": "link", "url": "javascript:alert(1)"})
        self.assertEqual(bad.status_code, 400)
        detail = self.client.post(f"/api/crm/deals/{deal_id}/items", json={"kind": "link", "url": "docs.google.com/x"}).json()
        self.assertIn("https://docs.google.com/x", [i["url"] for i in detail["items"]])
        card = self.board()["deals"][0]
        self.assertEqual(card["next_todo"], {"title": "Send proposal", "due_date": "2026-09-20"})
        todo = next(i for i in detail["items"] if i["kind"] == "todo")
        self.client.patch(f"/api/crm/items/{todo['id']}", json={"done": True})
        self.assertIsNone(self.board()["deals"][0]["next_todo"])

    def test_lead_detail_reports_the_deal(self):
        self.lead(6)
        with db.db_session() as conn:
            self.assertIsNone(crm.deal_for_lead(conn, 6, 1))
            crm.add_lead(conn, 6, 1)
            self.assertEqual(crm.deal_for_lead(conn, 6, 1)["stage"], "meeting_booked")


if __name__ == "__main__":
    unittest.main()
