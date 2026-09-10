import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from app import db, deliverability_health as health, smartlead


class DeliverabilityPhaseTests(unittest.TestCase):
    def row(self, phase="rehab", days=0, day="2026-09-01"):
        return {"phase": phase, "perfect_days": days, "last_observation_day": day}

    def test_low_reputation_enters_rehab_immediately(self):
        phase, days, transition = health._next_phase(self.row("full"), 89, "2026-09-02")
        self.assertEqual((phase, days, transition), ("rehab", 0, "full->rehab"))

    def test_repeated_checks_same_day_do_not_advance_streak(self):
        phase, days, transition = health._next_phase(self.row(days=3), 100, "2026-09-01")
        self.assertEqual((phase, days, transition), ("rehab", 3, None))

    def test_fifth_perfect_day_moves_rehab_to_comeback(self):
        with patch.object(health.settings, "mailbox_phase_stable_days", 5):
            phase, days, transition = health._next_phase(self.row(days=4), 100, "2026-09-02")
        self.assertEqual((phase, days, transition), ("comeback", 0, "rehab->comeback"))

    def test_comeback_nonperfect_day_resets_but_does_not_overreact(self):
        phase, days, transition = health._next_phase(self.row("comeback", 3), 97, "2026-09-02")
        self.assertEqual((phase, days, transition), ("comeback", 0, None))

    def test_first_check_preserves_existing_rehab_and_comeback_limits(self):
        rehab = {"message_per_day": 5, "warmup_details": {"warmup_max_count": 40}}
        comeback = {"message_per_day": 15, "warmup_details": {"warmup_max_count": 30}}
        full = {"message_per_day": 25, "warmup_details": {"warmup_max_count": 25}}
        self.assertEqual(health._initial_phase(rehab), "rehab")
        self.assertEqual(health._initial_phase(comeback), "comeback")
        self.assertEqual(health._initial_phase(full), "full")


class SmartleadWarmupFallbackTests(unittest.TestCase):
    def test_range_fields_fall_back_only_on_validation_error(self):
        with patch.object(
            smartlead,
            "_request",
            side_effect=[smartlead.SmartleadError("422 invalid field"), {"ok": True}],
        ) as request:
            result, variation = smartlead.update_email_account_warmup(
                12, minimum=32, maximum=40
            )
        self.assertEqual(result, {"ok": True})
        self.assertFalse(variation)
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("warmup_min_count", request.call_args_list[1].kwargs["json"])


class DeliverabilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "health.db")
        self.db_patch = patch.object(db.settings, "db_path", self.db_path)
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_monitoring_records_mailbox_domain_and_no_smartlead_write(self):
        account = {
            "id": 7,
            "from_email": "andrew@example.com",
            "message_per_day": 25,
            "is_smtp_success": True,
            "is_imap_success": True,
            "warmup_details": {"status": "ACTIVE", "warmup_reputation": "88%"},
        }
        auth = ({"mx": True, "spf": True, "dmarc": True, "dmarc_policy": "reject"}, None)
        with (
            patch.object(health.smartlead, "list_email_accounts", return_value=iter([account])),
            patch.object(health, "_authentication", return_value=auth),
            patch.object(health, "_apivoid_blacklist", return_value=([], ["test source"], None)),
            patch.object(health.settings, "deliverability_auto_apply", False),
            patch.object(health.smartlead, "update_email_account_limit") as update_limit,
        ):
            result = health.run_health_check(force_domains=True)
        self.assertEqual(result["mailboxes"], 1)
        update_limit.assert_not_called()
        snap = health.snapshot()
        self.assertEqual(snap["counts"]["rehab"], 1)
        self.assertEqual(snap["mailboxes"][0]["cold_daily_limit"], 25)
        self.assertEqual(snap["mailboxes"][0]["target_cold"], 5)
        self.assertEqual(snap["domains"][0]["status"], "healthy")


class ApiVoidTests(unittest.TestCase):
    def test_detected_engines_are_returned_with_full_checked_breakdown(self):
        payload = {
            "blacklists": {
                "engines": {
                    "0": {"name": "Clean list", "detected": False},
                    "1": {"name": "Listed engine", "detected": True},
                }
            }
        }
        response = Mock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        with (
            patch.object(health.settings, "apivoid_api_key", "test-key"),
            patch.object(health.httpx, "post", return_value=response) as post,
        ):
            listed, checked, error = health._apivoid_blacklist("example.com")
        self.assertEqual(listed, ["Listed engine"])
        self.assertEqual(checked, ["Clean list", "Listed engine"])
        self.assertIsNone(error)
        self.assertEqual(post.call_args.kwargs["json"], {"host": "example.com"})
        self.assertEqual(post.call_args.kwargs["headers"]["X-API-Key"], "test-key")

    def test_empty_engine_response_is_unknown_not_clean(self):
        response = Mock()
        response.json.return_value = {"blacklists": {"engines": {}}}
        response.raise_for_status.return_value = None
        with (
            patch.object(health.settings, "apivoid_api_key", "test-key"),
            patch.object(health.httpx, "post", return_value=response),
        ):
            listed, checked, error = health._apivoid_blacklist("example.com")
        self.assertEqual((listed, checked), ([], []))
        self.assertIn("no blacklist engines", error)


if __name__ == "__main__":
    unittest.main()
