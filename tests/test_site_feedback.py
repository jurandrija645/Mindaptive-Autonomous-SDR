import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db, site_feedback


class SiteFeedbackAnswerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db.settings, "db_path", str(Path(self.temp.name) / "f.db"))
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_scope_acceptance_keeps_its_details_and_is_hot(self):
        with db.db_session() as conn:
            row = site_feedback.save(conn, {
                "host": "https://www.acme.vercel.app/",
                "answer": "accept",
                "detail": "Scope uk-core-v1 accepted for Acme\nName: Jo\nEmail: jo@acme.test",
            })
            stored = conn.execute("SELECT * FROM site_feedback WHERE id=?", (row["id"],)).fetchone()
        out = site_feedback.payload([stored])[0]
        self.assertEqual(out["answer"], "accept")
        self.assertIn("jo@acme.test", out["detail"])
        self.assertEqual(out["reply_within_minutes"], site_feedback.REPLY_WITHIN_MINUTES)

    def test_like_still_drops_its_detail_and_unknown_answers_fail(self):
        with db.db_session() as conn:
            self.assertIsNone(site_feedback.save(conn, {"host": "a.test", "answer": "like", "detail": "x"})["detail"])
            with self.assertRaises(ValueError):
                site_feedback.save(conn, {"host": "a.test", "answer": "maybe"})


if __name__ == "__main__":
    unittest.main()
