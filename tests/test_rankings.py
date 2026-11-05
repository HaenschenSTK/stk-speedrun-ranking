import copy
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stk_rankings.database import connect, upsert_run
from stk_rankings.rankings import build_rankings, points, write_rankings

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "config/tracks.toml").read_text())
FIXTURE = json.loads((ROOT / "tests/fixtures/old_mine.json").read_text())
NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)
STAMP = "2026-09-19T00:00:00.000000Z"


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "archive.sqlite3"
        self.db = connect(self.path)
        self.config = copy.deepcopy(CONFIG)
        slugs = ("old-mine", "gran-paradiso-island", "drainage-dash", "freytra-peaks")
        self.config["tracks"] = {slug: CONFIG["tracks"][slug] for slug in slugs}
        self.db.execute("INSERT INTO categories VALUES ('7kj1gq4k', '1.x')")
        for slug, track in self.config["tracks"].items():
            self.db.execute("INSERT INTO tracks VALUES (?, ?, ?)", (track["id"], slug, track["name"]))
            self.db.execute("INSERT INTO sync_state VALUES (?, NULL, ?, ?, 1, 0)",
                            (track["id"], STAMP, STAMP))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def add(self, player, seconds, track="old-mine", direction="forward", run_id=None, name=None,
            status="verified", unavailable=None):
        run = copy.deepcopy(FIXTURE["runs"]["data"][0])
        run.update(id=run_id or f"{player}-{track}-{direction}", level=self.config["tracks"][track]["id"])
        run["players"] = {"data": [{"rel": "user", "id": player,
                                    "names": {"international": name or player},
                                    "weblink": "https://www.speedrun.com/users/" + player}]}
        run["times"]["primary_t"] = seconds
        run["values"]["j84kz64n"] = "4qyn7z31" if direction == "forward" else "mln5e86l"
        run["status"] = {"status": status, "verify-date": STAMP, "examiner": "moderator"}
        upsert_run(self.db, run, FIXTURE["game"]["data"]["variables"]["data"], STAMP)
        if unavailable:
            self.db.execute("UPDATE runs SET unavailable_since=? WHERE id=?", (unavailable, run["id"]))
        return run["id"]

    def build(self):
        return build_rankings(self.db, self.config, now=NOW)

    def test_curve_calibration_and_slow_tail(self):
        for time, expected in ((100, 10), (101, 4.641588833612778), (103, 1),
                               (106, 0.1), (109, 0.01), (112, 0.001)):
            self.assertAlmostEqual(points(round(time * 1_000_000), 100_000_000), expected)
        self.assertGreater(points(120_000_000, 100_000_000), 0)
        for pair in ((0, 0), (99, 100), (-1, 100)):
            with self.assertRaises(ValueError):
                points(*pair)

    def test_all_six_variants_pb_selection_and_combined_totals(self):
        for player, seconds in (("a", 100), ("b", 102)):
            self.add(player, seconds)
            self.add(player, seconds * 4, track="gran-paradiso-island")
        self.add("a", 101, run_id="superseded")
        self.add("a", 210, direction="reverse")
        self.add("b", 200, direction="reverse")
        self.add("a", 51, track="drainage-dash")
        self.add("b", 50, track="drainage-dash")
        self.add("a", 60, track="freytra-peaks")
        payload = self.build()
        self.assertEqual(payload["generated_at"], STAMP)
        self.assertEqual(len(payload["rankings"]), 6)
        two_percent = 2.154434690031884
        five_percent = 0.2154434690031884
        expected = {
            "forward-without-bonus": {"a": 20, "b": 2 * two_percent},
            "reverse-without-bonus": {"a": five_percent, "b": 10},
            "combined-without-bonus": {"a": 20 + five_percent, "b": 10 + 2 * two_percent},
            "forward-with-bonus": {"a": 30 + two_percent, "b": 10 + 2 * two_percent},
            "reverse-with-bonus": {"a": five_percent, "b": 10},
            "combined-with-bonus": {"a": 30 + two_percent + five_percent, "b": 20 + 2 * two_percent},
        }
        for variant, totals in expected.items():
            ranking = payload["rankings"][variant]
            for row in ranking["entries"]:
                self.assertAlmostEqual(row["points"], totals[row["player_name"]])
        combined = payload["rankings"]["combined-with-bonus"]
        self.assertEqual((combined["board_count"], combined["max_points"]), (5, 50))
        self.assertEqual((combined["entries"][0]["boards_played"], combined["entries"][0]["world_records"]), (5, 3))
        self.assertEqual(len(payload["players"]["user:a"]["performances"]), 5)
        self.assertEqual(payload["rankings"]["reverse-with-bonus"]["entries"],
                         payload["rankings"]["reverse-without-bonus"]["entries"])

    def test_shared_records_competition_ranks_and_missing_runs(self):
        self.add("a", 100)
        self.add("b", 100)
        self.add("c", 102)
        self.add("bonus-only", 20, track="drainage-dash")
        payload = self.build()
        rows = payload["rankings"]["forward-without-bonus"]["entries"]
        self.assertEqual([(r["player_key"], r["rank"], r["points"]) for r in rows],
                         [("user:a", 1, 10), ("user:b", 1, 10), ("user:c", 3, points(102, 100))])
        self.assertEqual([r["world_records"] for r in rows], [1, 1, 0])
        self.assertEqual(payload["rankings"]["reverse-with-bonus"]["entries"], [])
        self.assertEqual(payload["rankings"]["combined-without-bonus"]["entries"], rows)

    def test_cutoff_uses_total_and_preserves_track_runs(self):
        self.add("a", 100)
        self.add("boundary", 109)
        self.add("below", 110)
        self.add("below", 110, track="gran-paradiso-island")
        self.add("a", 100, track="gran-paradiso-island")
        payload = self.build()
        entries = payload["rankings"]["forward-without-bonus"]["entries"]
        self.assertIn("user:boundary", [r["player_key"] for r in entries])
        self.assertNotIn("user:below", [r["player_key"] for r in entries])
        self.assertEqual(len(payload["players"]["user:below"]["performances"]), 2)

    def test_podium_counts_respect_ties_and_filters(self):
        for player, time in (("a", 100), ("b", 100), ("c", 103)):
            self.add(player, time)
        self.add("c", 100, direction="reverse")
        self.add("b", 103, direction="reverse")
        rows = {r["player_key"]: r for r in self.build()["rankings"]["combined-without-bonus"]["entries"]}
        self.assertEqual((rows["user:b"]["world_records"], rows["user:b"]["second_places"], rows["user:b"]["third_places"]), (1, 1, 0))
        self.assertEqual((rows["user:c"]["world_records"], rows["user:c"]["third_places"]), (1, 1))

    def test_glitch_labels_and_track_availability(self):
        game = copy.deepcopy(FIXTURE["game"]["data"])
        game["variables"]["data"].append({
            "id": "ql690vjl", "name": "Glitches",
            "scope": {"type": "single-level", "level": self.config["tracks"]["gran-paradiso-island"]["id"]},
            "values": {"values": {"lmoj5py1": {"label": "No"}}},
        })
        self.db.execute("INSERT INTO metadata VALUES (?, ?, ?)",
                        (self.config["game_id"], STAMP, json.dumps(game)))
        run_id = self.add("a", 100, track="gran-paradiso-island")
        self.db.execute("INSERT OR REPLACE INTO run_variable_values VALUES (?, ?, ?)",
                        (run_id, "ql690vjl", "lmoj5py1"))
        payload = self.build()
        track = next(t for t in payload["tracks"] if t["slug"] == "gran-paradiso-island")
        self.assertTrue(track["has_glitches"])
        self.assertEqual(payload["players"]["user:a"]["performances"][0]["glitches"], "No")

    def test_removals_and_rejections_change_wr_and_recalculate(self):
        self.add("a", 100)
        self.add("b", 102)
        self.add("rejected", 90, status="rejected")
        self.add("missing", 91, unavailable=STAMP)
        self.assertEqual(set(self.build()["players"]), {"user:a", "user:b"})
        self.db.execute("UPDATE runs SET unavailable_since=? WHERE player_key='user:a'", (STAMP,))
        payload = self.build()
        row = payload["rankings"]["forward-without-bonus"]["entries"][0]
        self.assertEqual((row["player_key"], row["points"]), ("user:b", 10))
        self.assertEqual(payload["boards"][0]["wr_time_us"], 102_000_000)

    def test_player_identity_uses_ids_and_totals_are_not_rounded(self):
        self.add("a", 100, name="same-name")
        self.add("b", 100.000001, name="same-name")
        self.add("a", 200, direction="reverse", name="renamed")
        self.db.execute("UPDATE runs SET last_seen_at='2026-09-20T00:00:00Z' WHERE board_label='Mode=Reverse'")
        payload = self.build()
        rows = payload["rankings"]["forward-without-bonus"]["entries"]
        self.assertEqual([r["player_name"] for r in rows], ["renamed", "same-name"])
        self.assertEqual([r["rank"] for r in rows], [1, 2])
        self.assertEqual(round(rows[0]["points"], 2), round(rows[1]["points"], 2))
        self.assertGreater(rows[0]["points"], rows[1]["points"])

    def test_other_categories_and_unconfigured_tracks_do_not_count(self):
        self.add("a", 100)
        run_id = self.add("b", 10)
        self.add("c", 10, track="gran-paradiso-island")
        self.db.execute("INSERT INTO categories VALUES ('other', 'Other version')")
        self.db.execute("UPDATE runs SET category_id='other' WHERE id=?", (run_id,))
        del self.config["tracks"]["gran-paradiso-island"]
        self.assertEqual(set(self.build()["players"]), {"user:a"})

    def test_profiles_include_scoring_and_independent_forward_reverse_bonus_reigns(self):
        def dated(player, seconds, days_ago, **kwargs):
            run_id = self.add(player, seconds, **kwargs)
            verified = (NOW - timedelta(days=days_ago)).isoformat(timespec="microseconds").replace("+00:00", "Z")
            self.db.execute("UPDATE runs SET verified_at=?, played_on=? WHERE id=?",
                            (verified, "2026-01-01", run_id))
            return run_id

        dated("a", 100, 100, run_id="first-wr")
        dated("a", 99, 80, run_id="self-improvement")
        dated("b", 98, 60)
        dated("a", 97, 20, run_id="reclaimed-wr")
        dated("c", 101, 90)
        dated("a", 200, 10, direction="reverse")
        dated("d", 200, 5, direction="reverse")
        dated("e", 202, 2, direction="reverse")
        dated("a", 50, 7, track="drainage-dash")
        dated("a", 60, 8, track="freytra-peaks")
        payload = self.build()
        performances = {(r["track"], r["direction"]): r for r in payload["players"]["user:a"]["performances"]}
        forward = performances["old-mine", "forward"]
        self.assertEqual((forward["run_id"], forward["points"], forward["board_rank"], forward["is_wr"]),
                         ("reclaimed-wr", 10, 1, True))
        self.assertEqual(forward["played_on"], "2026-01-01")
        self.assertEqual(forward["verified_at"], "2026-08-30T00:00:00.000000Z")
        stats = forward["wr_history"]
        self.assertEqual((stats["total_days"], stats["longest_reign_days"], stats["current_reign_days"], stats["reign_count"]),
                         (60, 40, 20, 2))
        self.assertEqual([r["days"] for r in stats["reigns"]], [40, 20])
        self.assertEqual(len(stats["reigns"][0]["records"]), 2)
        self.assertIsNone(stats["reigns"][1]["ended_at"])
        self.assertEqual(performances["old-mine", "reverse"]["wr_history"]["total_days"], 10)
        self.assertEqual(performances["drainage-dash", "forward"]["wr_history"]["total_days"], 7)
        self.assertEqual(performances["freytra-peaks", "forward"]["wr_history"]["total_days"], 8)
        # The Hall of Fame still uses only official forward reigns.
        self.assertEqual(payload["hall_of_fame"]["players"]["user:a"]["total_wr_hours"], 60 * 24)
        never_wr = payload["players"]["user:c"]["performances"][0]
        self.assertFalse(never_wr["is_wr"])
        self.assertEqual((never_wr["board_rank"], never_wr["gap_us"]), (3, 4_000_000))
        self.assertAlmostEqual(never_wr["gap_percent"], 400 / 97)
        self.assertEqual(never_wr["wr_history"]["total_days"], 0)
        self.assertEqual(never_wr["wr_history"]["longest_reign_days"], 0)
        self.assertEqual(never_wr["wr_history"]["reigns"], [])
        tied = payload["players"]["user:d"]["performances"][0]
        self.assertEqual((tied["board_rank"], tied["wr_history"]["total_days"]), (1, 5))
        third = payload["players"]["user:e"]["performances"][0]
        self.assertEqual(third["board_rank"], 3)
        board = next(b for b in payload["boards"] if (b["track"], b["direction"]) == ("old-mine", "reverse"))
        self.assertEqual((board["player_count"], board["wr_holders"]), (3, ["user:a", "user:d"]))

    def test_undated_reverse_run_marks_history_unknown_without_changing_scores(self):
        self.add("a", 100)
        self.add("a", 200, direction="reverse")
        unknown = self.add("b", 202, direction="reverse")
        self.db.execute("UPDATE runs SET verified_at=NULL WHERE id=?", (unknown,))
        payload = self.build()
        for player in payload["players"].values():
            for performance in player["performances"]:
                history = performance["wr_history"]
                if performance["direction"] == "reverse":
                    self.assertFalse(history["dates_complete"])
                    self.assertIsNone(history["total_days"])
                    self.assertIsNone(history["longest_reign_days"])
                    self.assertEqual(history["reigns"], [])
                else:
                    self.assertTrue(history["dates_complete"])
        self.assertEqual(payload["rankings"]["reverse-without-bonus"]["entries"][0]["points"], 10)

    def test_missing_sync_and_unsupported_boards_fail_explicitly(self):
        self.db.execute("DELETE FROM sync_state WHERE track_id=?", (self.config["tracks"]["old-mine"]["id"],))
        with self.assertRaisesRegex(ValueError, "Sync configured tracks.*old-mine"):
            self.build()
        self.db.rollback()
        self.add("a", 100)
        self.db.execute("UPDATE runs SET board_key=?", (json.dumps({"j84kz64n": "4qyn7z31", "other": "value"}),))
        with self.assertRaisesRegex(ValueError, "Unsupported leaderboard"):
            self.build()

    def test_export_reads_without_committing_callers_transaction(self):
        self.add("a", 100)
        self.assertIn("user:a", self.build()["players"])
        self.db.rollback()
        self.assertEqual(self.build()["players"], {})

    def test_json_replacement_and_serialization_failure_preserves_previous_export(self):
        output = Path(self.tmp.name) / "site/data/rankings.json"
        payload = self.build()
        write_rankings(payload, output)
        self.assertEqual(json.loads(output.read_text()), payload)
        original = output.read_bytes()
        with self.assertRaises(ValueError):
            write_rankings({"points": float("nan")}, output)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(list(output.parent.glob("*.tmp")), [])

    def test_cli_exports_existing_database_read_only(self):
        self.add("a", 100)
        self.db.commit()
        self.db.close()
        config_path = Path(self.tmp.name) / "tracks.toml"
        lines = [f'game_id = "{self.config["game_id"]}"']
        for slug, track in self.config["tracks"].items():
            lines.append(f"\n[tracks.{slug}]")
            lines.extend(f"{key} = {json.dumps(value)}" for key, value in track.items())
        config_path.write_text("\n".join(lines))
        output = Path(self.tmp.name) / "public/rankings.json"
        before = hashlib.sha256(self.path.read_bytes()).digest()
        command = [sys.executable, "-m", "stk_rankings", "--db", str(self.path),
                   "--config", str(config_path), "export", "--output", str(output)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["rankings"], 6)
        payload = json.loads(output.read_text())
        self.assertEqual(payload["rankings"]["forward-without-bonus"]["entries"][0]["points"], 10)
        self.assertEqual(set(payload["hall_of_fame"]["online_top_three"]), {
            "user:jp691l08", "user:xz2vge9x", "user:v8lg5q2j", "user:zx7v0z0x",
            "user:5j5k196j", "user:x72mkqq8", "user:qjnq43wj",
        })
        self.assertEqual(payload["hall_of_fame"]["members"], [])
        self.assertNotIn("apprentices", payload["hall_of_fame"])
        self.assertNotIn("apprentices", json.loads(result.stdout))
        self.assertNotIn("raw_json", output.read_text())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)
        protected = subprocess.run(command[:-1] + [str(self.path)], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(protected.returncode, 0)
        self.assertIn("must not overwrite", protected.stderr)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)
        old_export = output.read_bytes()
        alternate_hall = Path(self.tmp.name) / "hall.toml"
        for contents in (None, "[[online_top_three]]\nname = 'Missing ID'\n"):
            if contents is not None:
                alternate_hall.write_text(contents)
            invalid = subprocess.run(command + ["--hall-of-fame-config", str(alternate_hall)],
                                     cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertEqual(output.read_bytes(), old_export)
        alternate_hall.write_text('online_top_three = [{player_id = "a", name = "Manual label"}]\n')
        subprocess.run(command + ["--hall-of-fame-config", str(alternate_hall)],
                       cwd=ROOT, capture_output=True, text=True, check=True)
        custom = json.loads(output.read_text())["hall_of_fame"]
        self.assertEqual(set(custom["online_top_three"]), {"user:a"})
        self.assertTrue(custom["players"]["user:a"]["online_top_three_confirmed"])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)
        # The read-only connection is also supported directly by the builder.
        self.db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        self.assertEqual(self.build()["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
