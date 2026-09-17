import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db, main, prospect_contacts
from app.config import settings

TOKEN = "test-ingest-token"

PAYLOAD = {
    "domain": "bdsservicesltd.co.uk",
    "website": "https://bdsservicesltd.co.uk/",
    "company": "BDS Services",
    "demo_url": "https://bdsservices.vercel.app",
    "source": "WebsiteGenerator/BDSServices",
    "channels": {
        "whatsapp": [{"value": "07429776336", "confirmed": False, "reason": "mobile number", "sources": ["https://bdsservicesltd.co.uk/"]}],
        "phones": [{"value": "07429776336", "sources": ["https://bdsservicesltd.co.uk/"]}],
        "emails": [
            {"value": "info@bdsservicesltd.co.uk", "sources": ["a"]},
            {"value": "shubama00@gmail.com", "sources": ["a"]},
        ],
        "facebook": [{"value": "https://www.facebook.com/Bdsserviceslimited", "sources": ["a"]}],
        "instagram": [{"value": "https://www.instagram.com/bds__services_44", "sources": ["a"]}],
        "tiktok": [{"value": "https://www.tiktok.com/@bdsservicesltd44", "sources": ["a"]}],
    },
}


class ProspectContactsTests(unittest.TestCase):
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
        return self.client.post("/api/prospect-contacts", json=body, headers=headers)

    def test_rejects_missing_or_wrong_token(self):
        self.assertEqual(self.post(PAYLOAD, token=None).status_code, 401)
        self.assertEqual(self.post(PAYLOAD, token="nope").status_code, 401)

    def test_saved_before_lead_exists_then_attaches_by_gmail_address(self):
        res = self.post(PAYLOAD)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["matched_leads"], [])
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 7, 1, email="Shubama00@gmail.com", company="BDS")
            row = prospect_contacts.for_lead(conn, db.get_lead_state(conn, 7, 1))
        self.assertIsNotNone(row)
        icons = prospect_contacts.merge_icon_channels({"linkedin": "https://www.linkedin.com/in/x"}, row)
        self.assertEqual(icons["whatsapp"], "07429776336")
        self.assertEqual(icons["email"], "info@bdsservicesltd.co.uk")
        self.assertEqual(icons["linkedin"], "https://www.linkedin.com/in/x")  # research result kept

    def test_matches_existing_lead_by_website_and_repush_merges(self):
        with db.db_session() as conn:
            db.upsert_lead_state(conn, 8, 2, email="owner@other.com", website="https://www.bdsservicesltd.co.uk")
        self.assertEqual(len(self.post(PAYLOAD).json()["matched_leads"]), 1)
        again = {
            "domain": "www.bdsservicesltd.co.uk",
            "channels": {"whatsapp": [{"value": "+447000000001", "confirmed": True, "reason": "found by hand", "sources": ["manual"]}]},
        }
        self.assertEqual(self.post(again).status_code, 200)
        with db.db_session() as conn:
            site = prospect_contacts.payload(prospect_contacts.for_lead(conn, db.get_lead_state(conn, 8, 2)))
        self.assertEqual([w["value"] for w in site["channels"]["whatsapp"]], ["+447000000001", "07429776336"])
        self.assertEqual(site["demo_url"], "https://bdsservices.vercel.app")  # kept from first push
        self.assertIn("tiktok", site["channels"])


if __name__ == "__main__":
    unittest.main()
