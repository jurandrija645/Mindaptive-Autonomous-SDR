import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db, main, prospect_contacts, site_visits
from app.config import settings

TOKEN = "test-ingest-token"

PAYLOAD = {
    "domain": "bdsservicesltd.co.uk",
    "demo_url": "https://bds-services.vercel.app",
    "vercel_project": "bds-services",
    "source": "WebsiteGenerator/BDSServices",
    "buckets": {"2026-09-10T12:00:00.000Z": 33},
    "visitors": [
        {
            "country": "GB",
            "isp": "Virgin Media",
            "device": "Windows Chrome",
            "requests": 33,
            "first": "2026-09-10T12:00:00.000Z",
            "last": "2026-09-10T12:00:00.000Z",
        }
    ],
}


class SiteVisitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(settings, "db_path", str(Path(self.tmp.name) / "t.db")),
            patch.object(settings, "contact_ingest_token", TOKEN),
        ]
        for p in self.patches:
            p.start()
        db.init_db()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def post(self, body, token=TOKEN):
        headers = {"authorization": f"Bearer {token}"} if token else {}
        return self.client.post("/api/site-visits", json=body, headers=headers)

    def test_rejects_missing_or_wrong_token(self):
        self.assertEqual(self.post(PAYLOAD, token=None).status_code, 401)
        self.assertEqual(self.post(PAYLOAD, token="nope").status_code, 401)

    def test_saved_before_lead_exists_then_attaches_by_website(self):
        res = self.post(PAYLOAD)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["visit_count"], 1)
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 9, 3, email="owner@bdsservicesltd.co.uk", website="https://www.bdsservicesltd.co.uk")
            lead = db.get_lead_state(conn, 9, 3)
            visits = site_visits.payload(site_visits.for_lead(conn, lead))
        self.assertEqual(visits["visit_count"], 1)
        self.assertEqual(visits["demo_url"], "https://bds-services.vercel.app")
        self.assertEqual(visits["visitors"][0]["isp"], "Virgin Media")

    def test_overlapping_pushes_do_not_inflate_the_count(self):
        self.post(PAYLOAD)
        self.post(PAYLOAD)  # the daily run reports the same 30-day window again
        body = self.post(
            {
                "domain": "bdsservicesltd.co.uk",
                "buckets": {"2026-09-10T12:00:00.000Z": 33, "2026-09-14T08:00:00.000Z": 12},
                "visitors": [
                    {"country": "GB", "isp": "Virgin Media", "device": "Windows Chrome", "requests": 45, "first": "2026-09-10T12:00:00.000Z", "last": "2026-09-14T08:00:00.000Z"}
                ],
            }
        ).json()
        self.assertEqual(body["visit_count"], 2)
        self.assertEqual(body["first_at"], "2026-09-10T12:00:00.000Z")
        self.assertEqual(body["last_at"], "2026-09-14T08:00:00.000Z")
        with db.db_session() as conn:
            row = conn.execute("SELECT * FROM site_visits WHERE domain = 'bdsservicesltd.co.uk'").fetchone()
        self.assertEqual(row["total_requests"], 45)  # 33 + 12, not 33 + 33 + 45
        self.assertEqual(len(site_visits.payload(row)["visitors"]), 1)  # same visitor merged

    def test_history_survives_vercel_retention(self):
        """A later push covering only 24h must not erase older visits."""
        self.post(PAYLOAD)
        body = self.post({"domain": "bdsservicesltd.co.uk", "buckets": {"2026-09-18T16:00:00.000Z": 5}, "visitors": []}).json()
        self.assertEqual(body["visit_count"], 2)
        self.assertEqual(body["first_at"], "2026-09-10T12:00:00.000Z")

    def test_finds_row_through_saved_contacts_for_a_gmail_lead(self):
        prospect_payload = {
            "domain": "bdsservicesltd.co.uk",
            "channels": {"emails": [{"value": "shubama00@gmail.com", "sources": ["a"]}]},
        }
        self.client.post("/api/prospect-contacts", json=prospect_payload, headers={"authorization": f"Bearer {TOKEN}"})
        self.post(PAYLOAD)
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 10, 4, email="shubama00@gmail.com", company="BDS")
            lead = db.get_lead_state(conn, 10, 4)
            contacts_row = prospect_contacts.for_lead(conn, lead)
            visits = site_visits.for_lead(conn, lead, contacts_row)
        self.assertIsNotNone(visits)
        self.assertEqual(visits["visit_count"], 1)

    def test_rejects_bad_body(self):
        self.assertEqual(self.post({"buckets": {}}).status_code, 400)
        self.assertEqual(self.post({"domain": "x.com", "buckets": []}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
