import copy
import json
import tempfile
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stk_rankings.api import Api
from stk_rankings.database import connect, upsert_run, utc
from stk_rankings.sync import sync

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/old_mine.json").read_text())
GRAN_FIXTURE = json.loads((ROOT / "tests/fixtures/gran_paradiso_island.json").read_text())
CONFIG = tomllib.loads((ROOT / "config/tracks.toml").read_text())
NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)


class FakeApi:
    def __init__(self, pages=None, fixture=FIXTURE, level_id="ldyxxp93"):
        self.requests = 0
        self.fixture = fixture
        self.level_id = level_id
        self.pages = pages if pages is not None else [fixture["runs"]["data"]]

    def get(self, path, **params):
        self.requests += 1
        return copy.deepcopy(self.fixture["game"])

    def run_pages(self, game_id, level_id, category_id):
        assert (game_id, level_id, category_id) == ("46w9mq1r", self.level_id, "7kj1gq4k")
        for i, page in enumerate(self.pages):
            self.requests += 1
            if isinstance(page, Exception):
                raise page
            yield copy.deepcopy(page), i == len(self.pages) - 1


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / "archive.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def load(self, api=None, **kwargs):
        return sync(self.db, api or FakeApi(), CONFIG, now=kwargs.pop("now", NOW), **kwargs)

    def test_import_scope_precision_and_repeat(self):
        first = self.load()
        self.assertEqual((first["fetched"], first["requests"]), (26, 2))
        run = self.db.execute("SELECT * FROM runs WHERE id='z04x4v8y'").fetchone()
        self.assertEqual((run["player_name"], run["time_us"]), ("gluteq", 93354000))
        self.assertEqual(run["verified_at"], "2026-09-13T23:06:11.000000Z")
        self.assertEqual(json.loads(run["raw_json"])["id"], run["id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM run_variable_values").fetchone()[0], 52)
        second = self.load(now=NOW + timedelta(days=7))
        self.assertEqual(second["requests"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 26)
        run2 = self.db.execute("SELECT * FROM runs WHERE id=?", (run["id"],)).fetchone()
        self.assertEqual(run2["first_seen_at"], run["first_seen_at"])
        self.assertNotEqual(run2["last_seen_at"], run["last_seen_at"])

    def test_known_world_records_and_obsolete_pbs(self):
        self.load()
        wrs = self.db.execute("SELECT player_name, time_us, board_label FROM current_wrs ORDER BY board_label").fetchall()
        self.assertEqual([tuple(r) for r in wrs], [
            ("Haenschen", 92338000, "Mode=Normal"),
            ("trolli123", 92671000, "Mode=Reverse"),
        ])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM current_pbs WHERE player_name='Elrit'").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM runs WHERE player_name='Elrit'").fetchone()[0], 3)

    def test_gran_paradiso_preserves_glitches_without_splitting_boards(self):
        self.load(FakeApi(pages=[FIXTURE["runs"]["data"]], fixture=GRAN_FIXTURE))
        old_runs = [tuple(r) for r in self.db.execute("SELECT * FROM runs ORDER BY id")]
        old_state = tuple(self.db.execute("SELECT * FROM sync_state").fetchone())
        for days in (0, 7):
            result = self.load(FakeApi(fixture=GRAN_FIXTURE, level_id="rdn7759m"),
                               slug="gran-paradiso-island", now=NOW + timedelta(days=days))
            self.assertEqual((result["fetched"], result["requests"]), (4, 1))
        rows = self.db.execute("""
            SELECT r.id, r.raw_json, v.value_id FROM runs r
            JOIN run_variable_values v ON v.run_id = r.id AND v.variable_id = 'ql690vjl'
            WHERE r.track_id = 'rdn7759m'
        """).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["value_id"] for r in rows}, {"q65kdpnl", "lmoj5py1"})
        for r in rows:
            self.assertEqual(r["value_id"], json.loads(r["raw_json"])["values"]["ql690vjl"])
        self.assertEqual({r[0] for r in self.db.execute(
            "SELECT board_label FROM current_pbs WHERE track_id='rdn7759m'"
        )}, {"Mode=Normal", "Mode=Reverse"})
        # This player has both Yes and No runs, but only one combined Normal PB.
        self.assertEqual(self.db.execute("""
            SELECT COUNT(*) FROM current_pbs
            WHERE track_id='rdn7759m' AND player_name='kozelIZhcr2'
        """).fetchone()[0], 1)
        self.assertEqual([tuple(r) for r in self.db.execute(
            "SELECT * FROM runs WHERE track_id='ldyxxp93' ORDER BY id"
        )], old_runs)
        self.assertEqual(tuple(self.db.execute(
            "SELECT * FROM sync_state WHERE track_id='ldyxxp93'"
        ).fetchone()), old_state)

    def test_full_audit_marks_missing_and_reappearance_clears_flag(self):
        self.load()
        original = dict(self.db.execute("SELECT * FROM runs WHERE id='y8g9251z'").fetchone())
        remaining = [r for r in FIXTURE["runs"]["data"] if r["id"] != "y8g9251z"]
        self.load(FakeApi([remaining]), now=NOW + timedelta(days=1))
        missing = self.db.execute("SELECT * FROM runs WHERE id='y8g9251z'").fetchone()
        self.assertIsNotNone(missing["unavailable_since"])
        self.assertEqual(missing["raw_json"], original["raw_json"])
        self.assertEqual(self.db.execute("SELECT player_name FROM current_wrs WHERE board_label='Mode=Normal'").fetchone()[0], "ElTuneado009")
        self.load(now=NOW + timedelta(days=2))
        self.assertIsNone(self.db.execute("SELECT unavailable_since FROM runs WHERE id='y8g9251z'").fetchone()[0])

    def test_incremental_cutoff_and_monthly_full_audit(self):
        self.load()
        pages = [[FIXTURE["runs"]["data"][0]], [FIXTURE["runs"]["data"][1]], FIXTURE["runs"]["data"][2:]]
        result = self.load(FakeApi(pages), now=NOW + timedelta(days=1))
        self.assertEqual((result["mode"], result["requests"]), ("incremental", 2))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM active_runs").fetchone()[0], 26)
        result = self.load(FakeApi(pages), now=NOW + timedelta(days=31))
        self.assertEqual((result["mode"], result["requests"]), ("full", 4))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM active_runs").fetchone()[0], 26)

    def test_equal_watermark_is_not_skipped(self):
        self.load()
        new = copy.deepcopy(FIXTURE["runs"]["data"][0])
        new["id"] = "same-timestamp"
        result = self.load(FakeApi([[new], FIXTURE["runs"]["data"]]), now=NOW + timedelta(days=1))
        self.assertEqual(result["requests"], 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM active_runs").fetchone()[0], 27)

    def test_failed_fetch_or_import_does_not_advance_state(self):
        self.load()
        state = tuple(self.db.execute("SELECT * FROM sync_state").fetchone())
        for pages in ([FIXTURE["runs"]["data"], OSError("network failed")],
                      [[dict(FIXTURE["runs"]["data"][0], players={"data": []})]]):
            with self.assertRaises((OSError, ValueError)):
                self.load(FakeApi(pages), full=True, now=NOW + timedelta(days=1))
            self.assertEqual(tuple(self.db.execute("SELECT * FROM sync_state").fetchone()), state)
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM active_runs").fetchone()[0], 26)

    def test_ties_guests_missing_dates_and_wr_intervals(self):
        self.load()
        self.db.execute("DELETE FROM run_variable_values")
        self.db.execute("DELETE FROM runs")
        variables = FIXTURE["game"]["data"]["variables"]["data"]
        def add(run_id, guest, seconds, date):
            run = copy.deepcopy(FIXTURE["runs"]["data"][0])
            run.update(id=run_id, players={"data": [{"rel": "guest", "name": guest}]})
            run["times"]["primary_t"] = seconds
            run["status"]["verify-date"] = date
            run["date"] = "2010-01-01"  # Played date must not control the reign.
            upsert_run(self.db, run, variables, "2026-09-19T00:00:00Z")
        add("a", "A", 100, "2020-01-01T01:00:00+01:00")
        add("b", "B", 100, "2020-01-02T00:00:00Z")
        add("c", "A", 100, "2020-01-03T00:00:00Z")
        add("d", "C", 99, "2020-01-04T00:00:00Z")
        add("e", "D", 99, "2020-01-04T00:00:00Z")
        add("f", "E", 101, "2020-01-04T00:00:00Z")
        add("unknown", "F", 98, None)
        rows = self.db.execute("SELECT id, wr_started_at, wr_ended_at FROM wr_history ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows], [
            ("a", "2020-01-01T00:00:00.000000Z", "2020-01-04T00:00:00.000000Z"),
            ("b", "2020-01-02T00:00:00.000000Z", "2020-01-04T00:00:00.000000Z"),
            ("d", "2020-01-04T00:00:00.000000Z", None),
            ("e", "2020-01-04T00:00:00.000000Z", None),
        ])
        self.assertEqual(self.db.execute("SELECT id FROM current_wrs").fetchone()[0], "unknown")
        self.db.execute("DELETE FROM run_variable_values WHERE run_id='unknown'")
        self.db.execute("DELETE FROM runs WHERE id='unknown'")
        self.assertEqual({r[0] for r in self.db.execute("SELECT id FROM current_wrs")}, {"d", "e"})


class ApiTests(unittest.TestCase):
    def test_timestamps_sort_chronologically_with_fractional_seconds(self):
        self.assertLess(utc("2020-01-01T00:00:00Z"), utc("2020-01-01T00:00:00.5Z"))

    def test_pagination_uses_next_link_and_embeds_players(self):
        api = Api()
        calls = []
        def get(path, **params):
            calls.append((path, params))
            if len(calls) == 1:
                return {"data": ["first"], "pagination": {"links": [{"rel": "next", "uri": "https://www.speedrun.com/api/v1/runs?offset=200"}]}}
            return {"data": ["second"], "pagination": {"links": []}}
        api.get = get
        self.assertEqual(list(api.run_pages("game", "level", "category")), [(["first"], False), (["second"], True)])
        self.assertEqual(calls[0][1]["embed"], "players")
        self.assertEqual(calls[0][1]["category"], "category")
        self.assertEqual(calls[1][0], "https://www.speedrun.com/api/v1/runs?offset=200")


if __name__ == "__main__":
    unittest.main()
