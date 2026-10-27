import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import db, deliverability_health as health, placement

# Mindaptive's ladder, as the owner set it on 2026-10-27.
LADDER = [
    {"name": "rehab", "cold": 5, "warm_min": 40, "warm_max": 45},
    {"name": "ramp_10", "cold": 10, "warm_min": 35, "warm_max": 40},
    {"name": "ramp_15", "cold": 15, "warm_min": 30, "warm_max": 35},
    {"name": "ramp_20", "cold": 20, "warm_min": 25, "warm_max": 30},
    {"name": "full", "cold": 25, "warm_min": 20, "warm_max": 25},
]


def ladder_policy(**overrides):
    policy = health._env_policy()
    policy.update(
        ladder=[dict(s) for s in LADDER],
        phases={s["name"]: {k: s[k] for k in ("cold", "warm_min", "warm_max")} for s in LADDER},
        custom_ladder=True, threshold=100, stable_days=2,
    )
    policy.update(overrides)
    return policy


class LadderTests(unittest.TestCase):
    def test_recovery_climbs_one_rung_every_two_perfect_days(self):
        policy = ladder_policy()
        state = {"phase": "full", "perfect_days": 0, "last_observation_day": "2026-10-01"}
        seen = []
        for day, rep in enumerate([99] + [100] * 8, start=2):
            phase, days, transition = health._next_phase(state, rep, f"2026-10-{day:02d}", policy)
            state = {"phase": phase, "perfect_days": days, "last_observation_day": f"2026-10-{day:02d}"}
            if transition:
                seen.append(transition)
        self.assertEqual(seen, [
            "full->rehab", "rehab->ramp_10", "ramp_10->ramp_15", "ramp_15->ramp_20", "ramp_20->full",
        ])

    def test_any_drop_below_100_sends_a_rung_back_to_rehab(self):
        state = {"phase": "ramp_15", "perfect_days": 1, "last_observation_day": "2026-10-01"}
        self.assertEqual(health._next_phase(state, 99, "2026-10-02", ladder_policy()), ("rehab", 0, "ramp_15->rehab"))

    def test_failed_placement_holds_rehab_despite_perfect_reputation(self):
        policy = ladder_policy()
        state = {"phase": "full", "perfect_days": 0, "last_observation_day": "2026-10-01"}
        self.assertEqual(health._next_phase(state, 100, "2026-10-02", policy, hold=True), ("rehab", 0, "full->rehab"))
        state = {"phase": "rehab", "perfect_days": 0, "last_observation_day": "2026-10-02"}
        for day in range(3, 9):
            phase, days, _ = health._next_phase(state, 100, f"2026-10-{day:02d}", policy, hold=True)
            state = {"phase": phase, "perfect_days": days, "last_observation_day": f"2026-10-{day:02d}"}
        self.assertEqual(state["phase"], "rehab")

    def test_first_sight_on_a_custom_ladder_reads_the_cold_cap(self):
        ladder = [dict(s) for s in LADDER]
        self.assertEqual(health._initial_phase({"message_per_day": 20}, ladder=ladder), "ramp_20")
        self.assertEqual(health._initial_phase({"message_per_day": 5}, ladder=ladder), "rehab")
        self.assertEqual(health._initial_phase({"message_per_day": 2}, ladder=ladder), "rehab")
        self.assertEqual(health._initial_phase({"message_per_day": 30}, ladder=ladder), "full")

    def test_old_comeback_rows_land_on_the_nearest_rung(self):
        state = {"phase": "comeback", "perfect_days": 0, "last_observation_day": "2026-10-01", "target_cold": 15}
        phase, _, _ = health._next_phase(state, 100, "2026-10-02", ladder_policy())
        self.assertEqual(phase, "ramp_15")


class PolicyLadderStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db.settings, "db_path", str(Path(self.temp.name) / "p.db"))
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_saved_ladder_round_trips_and_names_the_ends(self):
        rows = [dict(s) for s in LADDER]
        rows[0]["name"], rows[-1]["name"] = "bottom", "top"
        policy = health.save_policy({"ladder": rows, "threshold": 100, "stable_days": 2})
        self.assertTrue(policy["custom_ladder"])
        self.assertEqual([s["name"] for s in policy["ladder"]], ["rehab", "ramp_10", "ramp_15", "ramp_20", "full"])
        self.assertEqual(policy["phases"]["ramp_15"]["cold"], 15)

    def test_ladder_must_rise(self):
        rows = [dict(s) for s in LADDER]
        rows[2]["cold"] = 10
        with self.assertRaises(ValueError):
            health.save_policy({"ladder": rows})
        self.assertFalse(health.load_policy()["custom_ladder"])

    def test_default_clients_keep_their_three_stages(self):
        policy = health.load_policy()
        self.assertEqual([s["name"] for s in policy["ladder"]], ["rehab", "comeback", "full"])


def seed_rows(folders):
    return [{"email": "x@seed.test", "reply": {"mail_folder": f}} if f else {"email": "x@seed.test"} for f in folders]


class PlacementResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db.settings, "db_path", str(Path(self.temp.name) / "p.db"))
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_score_ignores_seeds_that_never_received_it(self):
        row = {"email": "Mia@Example.com", "details": seed_rows(["Inbox", "Spam", "Inbox", None])}
        self.assertEqual(placement._score(row), ("mia@example.com", 2, 1, 3))
        self.assertIsNone(placement._score({"email": "a@b.c", "details": seed_rows(["Inbox", None])}))

    def test_collect_reads_finished_tests_only_and_latest_result_wins(self):
        now = datetime.now(timezone.utc)
        tests = [
            {"spam_test_id": 1, "test_name": "old", "status": "COMPLETED", "created_at": (now - timedelta(days=6)).isoformat()},
            {"spam_test_id": 2, "test_name": "new", "status": "COMPLETED", "created_at": (now - timedelta(days=1)).isoformat()},
            {"spam_test_id": 3, "test_name": "running", "status": "ACTIVE", "created_at": (now - timedelta(hours=2)).isoformat()},
        ]
        reports = {
            1: [{"email": "a@x.com", "details": seed_rows(["Spam", "Spam", "Spam", "Inbox"])}],
            2: [{"email": "a@x.com", "details": seed_rows(["Inbox"] * 4)},
                {"email": "b@x.com", "details": seed_rows(["Inbox", "Spam", "Spam", "Spam"])}],
        }
        with (
            patch.object(placement.smartlead, "list_placement_tests", return_value=tests),
            patch.object(placement.smartlead, "placement_sender_report", side_effect=lambda t: reports[t]) as report,
        ):
            self.assertEqual(placement.collect_results(), {"tests_read": 2})
            self.assertEqual(placement.collect_results(), {"tests_read": 0})  # never re-read
        self.assertNotIn(3, [c.args[0] for c in report.call_args_list])
        with db.db_session() as conn:
            latest = placement.latest_by_email(conn)
            self.assertEqual(latest["a@x.com"]["inbox_pct"], 100)
            self.assertEqual(placement.failing_emails(conn, 90), {"b@x.com"})


class EnforceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db.settings, "db_path", str(Path(self.temp.name) / "p.db"))
        self.db_patch.start()
        db.init_db()
        with db.db_session() as conn:
            for email, pct in (("bad@x.com", 40), ("good@x.com", 100)):
                conn.execute(
                    "INSERT INTO mailbox_placement VALUES (?,?,?,?,?,?,?)",
                    (9, email, "2026-10-21T10:00:00+00:00", pct // 25, 4 - pct // 25, 4, pct),
                )

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def run_enforce(self, attached, *, auto_apply=True, dry_run=False):
        health.save_policy({"auto_apply": auto_apply})
        with (
            patch.object(placement.settings, "dry_run", dry_run),
            patch.object(placement.smartlead, "list_campaigns", return_value=[{"id": 5, "name": "Law", "status": "ACTIVE"}]),
            patch.object(placement.smartlead, "get_campaign_email_accounts", return_value=attached),
            patch.object(placement.smartlead, "remove_campaign_email_accounts") as remove,
            patch.object(placement.smartlead, "reallocate_campaign_mailboxes") as realloc,
            patch.object(health, "_notify"),
        ):
            result = placement.enforce()
        with db.db_session() as conn:
            actions = [r["action"] for r in conn.execute("SELECT action FROM placement_actions")]
        return result, remove, realloc, actions

    def test_failed_mailbox_leaves_campaign_and_its_leads_move(self):
        attached = [{"id": 1, "from_email": "bad@x.com"}, {"id": 2, "from_email": "good@x.com"}]
        result, remove, realloc, actions = self.run_enforce(attached)
        remove.assert_called_once_with(5, [1])
        realloc.assert_called_once_with(5, [1])
        self.assertEqual((result["removed"], actions), (1, ["removed"]))

    def test_a_campaign_is_never_emptied(self):
        _, remove, _, actions = self.run_enforce([{"id": 1, "from_email": "bad@x.com"}])
        remove.assert_not_called()
        self.assertEqual(actions, ["kept_last_mailboxes"])

    def test_switch_off_only_records_what_it_would_do(self):
        attached = [{"id": 1, "from_email": "bad@x.com"}, {"id": 2, "from_email": "good@x.com"}]
        _, remove, _, actions = self.run_enforce(attached, auto_apply=False)
        remove.assert_not_called()
        self.assertEqual(actions, ["would_remove"])

    def test_excluded_domains_are_never_touched(self):
        health.save_policy({"auto_apply": True, "exclude_domains": "x.com"})
        attached = [{"id": 1, "from_email": "bad@x.com"}, {"id": 2, "from_email": "good@x.com"}]
        result, remove, _, _ = self.run_enforce(attached)
        remove.assert_not_called()
        account = {"id": 1, "from_email": "bad@x.com", "message_per_day": 2,
                   "warmup_details": {"status": "ACTIVE", "warmup_reputation": "100%"}}
        with (
            patch.object(health.smartlead, "list_email_accounts", return_value=iter([account])),
            patch.object(health.settings, "dry_run", False),
            patch.object(health.smartlead, "update_email_account_limit") as limit,
        ):
            self.assertEqual(health.run_health_check()["mailboxes"], 0)
        limit.assert_not_called()

    def test_each_mailbox_is_tested_with_a_campaign_it_sends_in(self):
        campaigns = [
            {"id": 10, "status": "PAUSED"}, {"id": 20, "status": "ACTIVE"}, {"id": 30, "status": "DRAFTED"},
        ]
        attached = {10: [{"from_email": "a@x.com"}, {"from_email": "b@x.com"}], 20: [{"from_email": "a@x.com"}], 30: [{"from_email": "c@x.com"}]}
        with (
            patch.object(placement.smartlead, "list_campaigns", return_value=campaigns),
            patch.object(placement.smartlead, "get_campaign_email_accounts", side_effect=lambda c: attached[c]),
        ):
            home = placement._home_campaigns(["a@x.com", "b@x.com", "c@x.com"])
        self.assertEqual(home, {"a@x.com": 20, "b@x.com": 10})

    def test_health_check_puts_a_failed_mailbox_in_rehab(self):
        health.save_policy({"auto_apply": True, "ladder": LADDER, "threshold": 100, "stable_days": 2})
        account = {
            "id": 1, "from_email": "bad@x.com", "message_per_day": 20,
            "is_smtp_success": True, "is_imap_success": True,
            "warmup_details": {"status": "ACTIVE", "warmup_reputation": "100%", "warmup_min_count": 25, "warmup_max_count": 30},
        }
        auth = ({"mx": True, "spf": True, "dmarc": True, "dmarc_policy": "reject"}, None)
        with (
            patch.object(health.smartlead, "list_email_accounts", return_value=iter([account])),
            patch.object(health, "_authentication", return_value=auth),
            patch.object(health, "_apivoid_blacklist", return_value=([], ["x"], None)),
            patch.object(health.settings, "dry_run", False),
            patch.object(health.smartlead, "update_email_account_limit") as limit,
            patch.object(health.smartlead, "update_email_account_warmup", return_value=({}, True)) as warm,
        ):
            health.run_health_check()
        limit.assert_called_once_with(1, 5)
        warm.assert_called_once_with(1, minimum=40, maximum=45)
        row = health.snapshot()["mailboxes"][0]
        self.assertEqual(row["phase"], "rehab")
        self.assertFalse(row["placement"]["passed"])


if __name__ == "__main__":
    unittest.main()
