import copy
import json
import tempfile
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stk_rankings.database import connect, upsert_run
from stk_rankings.hall_of_fame import build_hall_of_fame, confirmed_players
from stk_rankings.rankings import build_rankings

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "config/tracks.toml").read_text())
FIXTURE = json.loads((ROOT / "tests/fixtures/old_mine.json").read_text())
NOW = datetime(2024, 7, 1, tzinfo=timezone.utc)
OFFICIAL = ("old-mine", "gran-paradiso-island", "black-forest", "candela-city")


class HallOfFameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / "archive.sqlite3")
        slugs = (*OFFICIAL, "drainage-dash", "freytra-peaks")
        self.config = {"game_id": CONFIG["game_id"], "tracks": {slug: CONFIG["tracks"][slug] for slug in slugs}}
        self.db.execute("INSERT INTO categories VALUES ('7kj1gq4k', '1.x')")
        for slug, track in self.config["tracks"].items():
            self.db.execute("INSERT INTO tracks VALUES (?, ?, ?)", (track["id"], slug, track["name"]))
            self.db.execute("INSERT INTO sync_state VALUES (?, NULL, ?, ?, 1, 0)",
                            (track["id"], NOW.isoformat(), NOW.isoformat()))
        self.db.commit()
        self.next_id = 0

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def add(self, player, seconds, date, track="old-mine", direction="forward", name=None, guest=False):
        self.next_id += 1
        run = copy.deepcopy(FIXTURE["runs"]["data"][0])
        run.update(id=f"run-{self.next_id}", level=self.config["tracks"][track]["id"], date="2010-01-01")
        identity = ({"rel": "guest", "name": player} if guest else
                    {"rel": "user", "id": player, "names": {"international": name or player}})
        run["players"] = {"data": [identity]}
        run["times"]["primary_t"] = seconds
        run["values"]["j84kz64n"] = "4qyn7z31" if direction == "forward" else "mln5e86l"
        run["status"]["verify-date"] = date + "T00:00:00Z" if date and len(date) == 10 else date
        upsert_run(self.db, run, FIXTURE["game"]["data"]["variables"]["data"], NOW.isoformat())
        return run["id"]

    def build(self, confirmed=(), now=NOW):
        online = {"online_top_three": [{"player_id": player, "name": player} for player in confirmed]}
        return build_hall_of_fame(self.db, self.config, online, now=now)

    def test_thirty_days_exact_boundary_not_calendar_month(self):
        self.add("a", 100, "2024-01-31T12:34:56Z")
        threshold = datetime(2024, 3, 1, 12, 34, 56, tzinfo=timezone.utc)
        before = self.build(now=threshold - timedelta(microseconds=1))["players"]["user:a"]
        exact = self.build(now=threshold)["players"]["user:a"]
        self.assertEqual(before["qualifying_track_count"], 0)
        self.assertEqual(exact["qualifying_track_count"], 1)
        self.assertEqual(exact["total_wr_hours"], 30 * 24)

    def test_early_reigns_qualify_and_lifetime_hours_are_preserved(self):
        self.add("early", 101, "2019-04-20")
        self.add("spanning", 100, "2019-07-01")
        self.add("spanning", 99, "2019-07-15")
        threshold = datetime(2019, 7, 31, tzinfo=timezone.utc)
        before = self.build(now=threshold - timedelta(microseconds=1))
        exact = self.build(now=threshold)
        early = exact["players"]["user:early"]
        self.assertEqual(early["qualifying_track_count"], 1)
        self.assertEqual(early["total_wr_hours"], 72 * 24)
        self.assertEqual(early["reigns"][0]["qualifies_at"], "2019-05-20T00:00:00.000000Z")
        self.assertEqual(before["players"]["user:spanning"]["qualifying_track_count"], 0)
        spanning = exact["players"]["user:spanning"]
        self.assertEqual(spanning["qualifying_track_count"], 1)
        self.assertEqual(spanning["total_wr_hours"], 30 * 24)
        self.assertEqual(len(spanning["reigns"]), 1)
        self.assertEqual(spanning["reigns"][0]["qualifies_at"], "2019-07-31T00:00:00.000000Z")
        self.assertNotIn("qualification_not_before", exact["rules"])

    def test_speedrun_qualification_can_be_earned_during_launch_period(self):
        for track in OFFICIAL[:3]:
            self.add("a", 100, "2019-04-20", track)
        threshold = datetime(2019, 5, 20, tzinfo=timezone.utc)
        before = self.build(confirmed=("a",), now=threshold - timedelta(microseconds=1))
        self.assertEqual(before["members"], [])
        exact = self.build(confirmed=("a",), now=threshold)
        self.assertEqual(len(exact["members"]), 1)
        a = exact["players"]["user:a"]
        self.assertEqual(a["speedrun_qualified_at"], "2019-05-20T00:00:00.000000Z")
        self.assertEqual(a["total_wr_hours"], 3 * 30 * 24)

    def test_self_improvements_and_equal_resubmissions_form_one_reign(self):
        self.add("a", 100, "2024-01-01")
        self.add("a", 99, "2024-02-01")
        self.add("a", 99, "2024-03-01")
        self.add("a", 98, "2024-04-01")
        player = self.build(now=datetime(2024, 4, 1, tzinfo=timezone.utc))["players"]["user:a"]
        self.assertEqual(player["qualifying_track_count"], 1)
        self.assertEqual(len(player["reigns"]), 1)
        self.assertEqual(len(player["reigns"][0]["records"]), 3)
        self.assertEqual(player["total_wr_hours"], 91 * 24)
        self.assertIsNone(player["reigns"][0]["ended_at"])

    def test_lost_and_reclaimed_wr_stays_separate_short_reigns_do_not_qualify(self):
        self.add("a", 100, "2024-01-01")
        self.add("b", 99, "2024-01-21")
        self.add("a", 98, "2024-04-01")
        self.add("b", 97, "2024-04-21")
        player = self.build()["players"]["user:a"]
        self.assertEqual(player["qualifying_track_count"], 0)
        self.assertEqual(len(player["reigns"]), 2)
        self.assertEqual(player["total_wr_hours"], (20 + 20) * 24)

    def test_shared_records_each_earn_full_hours_and_same_timestamp_faster_run_wins(self):
        self.add("a", 100, "2024-01-01")
        self.add("b", 100, "2024-02-01")
        self.add("c", 99, "2024-04-01")
        self.add("d", 100, "2024-04-01")
        h = self.build()
        self.assertEqual(h["players"]["user:a"]["total_wr_hours"], 91 * 24)
        self.assertEqual(h["players"]["user:b"]["total_wr_hours"], 60 * 24)
        self.assertEqual(h["players"]["user:c"]["total_wr_hours"], 91 * 24)
        self.assertNotIn("user:d", h["players"])

    def test_members_require_online_confirmation_and_three_tracks_and_include_all_hours(self):
        for track in OFFICIAL[:3]:
            self.add("a", 100, "2024-01-01", track)
            self.add("b", 100, "2024-01-01", track)
            self.add("c", 99, "2024-04-01", track)
        # Both established players have lost every WR, but remain qualified.
        # These two short reigns on a fourth track add hours without qualifying it.
        self.add("a", 100, "2024-01-01", OFFICIAL[3])
        self.add("other", 99, "2024-01-21", OFFICIAL[3])
        self.add("a", 98, "2024-05-01", OFFICIAL[3])
        self.add("other", 97, "2024-05-21", OFFICIAL[3])
        h = self.build(confirmed=("a",))
        self.assertEqual([r["player_key"] for r in h["members"]], ["user:a"])
        self.assertNotIn("apprentices", h)
        self.assertEqual(h["players"]["user:b"]["qualifying_track_count"], 3)
        self.assertEqual(h["players"]["user:c"]["qualifying_track_count"], 3)
        self.assertEqual(self.build()["members"], [])
        a = h["players"]["user:a"]
        self.assertEqual(a["qualifying_track_count"], 3)
        self.assertEqual(a["speedrun_qualified_at"], "2024-01-31T00:00:00.000000Z")
        self.assertEqual(a["total_wr_hours"], (3 * 91 + 20 + 20) * 24)
        self.assertEqual(len(a["reigns"]), 5)
        promoted = self.build(confirmed=("a", "b"))
        self.assertEqual({r["player_key"] for r in promoted["members"]}, {"user:a", "user:b"})
        self.assertEqual(promoted["players"]["user:b"]["total_wr_hours"], h["players"]["user:b"]["total_wr_hours"])

    def test_qualifying_reigns_need_not_overlap_and_repeated_track_counts_once(self):
        for index, track in enumerate(OFFICIAL[:3]):
            self.add("a", 100, f"202{index}-01-01", track)
            self.add("other", 99, f"202{index}-04-01", track)
        self.add("a", 98, "2023-01-01")
        self.add("other", 97, "2023-04-01")
        a = self.build(confirmed=("a",))["players"]["user:a"]
        self.assertEqual(a["qualifying_track_count"], 3)
        self.assertEqual(len(a["reigns"]), 4)
        self.assertEqual(a["speedrun_qualified_at"], "2022-01-31T00:00:00.000000Z")

    def test_reverse_bonus_other_categories_and_unconfigured_tracks_are_excluded(self):
        for track in OFFICIAL:
            self.add("reverse", 50, "2020-01-01", track, direction="reverse")
        for track in ("drainage-dash", "freytra-peaks"):
            self.add("bonus", 50, "2020-01-01", track)
        removed = self.add("deleted", 50, "2020-01-01")
        rejected = self.add("rejected", 49, "2020-01-01")
        wrong_category = self.add("other-category", 48, "2020-01-01")
        self.db.execute("UPDATE runs SET unavailable_since=? WHERE id=?", (NOW.isoformat(), removed))
        self.db.execute("UPDATE runs SET status='rejected' WHERE id=?", (rejected,))
        self.db.execute("INSERT INTO categories VALUES ('other', 'Other')")
        self.db.execute("UPDATE runs SET category_id='other' WHERE id=?", (wrong_category,))
        self.add("unconfigured", 50, "2020-01-01", OFFICIAL[3])
        del self.config["tracks"][OFFICIAL[3]]
        self.assertEqual(self.build()["players"], {})

    def test_unknown_dates_fail_instead_of_granting_unbounded_hours(self):
        self.add("a", 100, "2020-01-01")
        self.add("undated", 99, None)
        with self.assertRaisesRegex(ValueError, "missing forward verification dates"):
            self.build()

    def test_future_records_do_not_end_reigns_before_evaluation_time(self):
        self.add("a", 100, "2024-01-01")
        self.add("b", 99, "2025-01-01")
        h = self.build()
        self.assertNotIn("user:b", h["players"])
        self.assertEqual(h["players"]["user:a"]["total_wr_hours"], 182 * 24)
        self.assertIsNone(h["players"]["user:a"]["reigns"][0]["ended_at"])

    def test_ranking_uses_lifetime_hours_and_shared_ranks(self):
        for track in OFFICIAL:
            self.add("more-tracks", 100, "2024-04-01", track)
        for track in OFFICIAL[:3]:
            self.add("longer", 101, "2020-01-01", track)
            self.add("equal-a", 102, "2019-08-01", track)
            self.add("equal-b", 102, "2019-08-01", track)
            self.add("shorter", 103, "2019-07-12", track)
        rows = self.build(confirmed=("more-tracks", "longer", "equal-a", "equal-b", "shorter"))["members"]
        self.assertEqual([(r["player_key"], r["rank"]) for r in rows],
                         [("user:longer", 1), ("user:equal-a", 2), ("user:equal-b", 2), ("user:more-tracks", 4)])
        self.assertGreater(rows[0]["total_wr_hours"], rows[-1]["total_wr_hours"])
        self.assertLess(rows[0]["qualifying_track_count"], rows[-1]["qualifying_track_count"])

    def test_equal_hours_share_rank_even_with_different_qualifying_track_counts(self):
        for track in OFFICIAL:
            self.add("four", 100, "2024-03-03", track)
            self.add("end", 99, "2024-04-02", track)
        for track in OFFICIAL[:3]:
            self.add("three", 101, "2024-01-23", track)
        h = self.build(confirmed=("three", "four"))
        self.assertEqual(h["rules"]["ordering"], ["total_wr_hours descending"])
        self.assertEqual([r["rank"] for r in h["members"]], [1, 1])
        self.assertEqual({r["qualifying_track_count"] for r in h["members"]}, {3, 4})
        self.assertEqual({r["total_wr_hours"] for r in h["members"]}, {120 * 24})

    def test_confirmation_uses_id_not_name_and_does_not_admit_guest_namesakes(self):
        for track in OFFICIAL[:3]:
            self.add("registered", 100, "2024-01-01", track, name="Renamed")
            self.add("Renamed", 100, "2024-01-01", track, guest=True)
        h = self.build(confirmed=("registered",))
        self.assertEqual(h["members"][0]["player_name"], "Renamed")
        self.assertEqual(h["members"][0]["player_key"], "user:registered")
        self.assertEqual(len(h["members"]), 1)
        self.assertFalse(h["players"]["guest:Renamed"]["online_top_three_confirmed"])

    def test_bad_online_config_is_not_silently_treated_as_empty(self):
        for config in ({}, {"online_top_three": {}}, {"online_top_three": ["player"]},
                       {"online_top_three": [{"name": "a"}]},
                       {"online_top_three": [{"player_id": "a", "name": "a"}] * 2}):
            with self.assertRaisesRegex(ValueError, "Hall of Fame config"):
                confirmed_players(config)

    def test_full_export_has_only_hall_of_fame_and_preserves_caller_transaction(self):
        for track in OFFICIAL[:3]:
            self.add("a", 100, "2024-01-01", track)
        online = {"online_top_three": [{"player_id": "a", "name": "a"}]}
        payload = build_rankings(self.db, self.config, now=NOW, hall_of_fame_config=online)
        self.assertEqual(payload["hall_of_fame"]["as_of"], payload["generated_at"])
        self.assertEqual(len(payload["rankings"]), 6)
        self.assertEqual(len(payload["hall_of_fame"]["members"]), 1)
        self.assertNotIn("apprentices", payload["hall_of_fame"])
        self.db.rollback()
        self.assertEqual(self.build()["players"], {})


if __name__ == "__main__":
    unittest.main()
