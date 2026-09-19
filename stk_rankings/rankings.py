"""Build the six static rankings from the local archive, without network access."""

import json
import math
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .database import utc
from .hall_of_fame import build_hall_of_fame
from .wr_reigns import merge_wr_reigns, summarize_wr_reigns

MODE_VARIABLE = "j84kz64n"
DIRECTIONS = {"4qyn7z31": "forward", "mln5e86l": "reverse"}


def points(time_us, wr_time_us):
    """10 at the WR, 1 at WR + 2%, with no artificial cutoff or rounding."""
    if wr_time_us <= 0 or time_us < wr_time_us:
        raise ValueError("Times must be positive and the run cannot beat its reference WR")
    return 10 * 10 ** (-50 * (time_us - wr_time_us) / wr_time_us)


def build_rankings(db, config, now=None, hall_of_fame_config=None):
    """Read a consistent snapshot. Only configured tracks/categories are eligible."""
    now = now or datetime.now(timezone.utc)
    tracks = []
    by_id = {}
    # Start the read snapshot before querying sync state and PBs together.
    db.execute("SAVEPOINT ranking_export")
    try:
        states = {r["track_id"]: dict(r) for r in db.execute("SELECT * FROM sync_state")}
        missing = [slug for slug, track in config["tracks"].items() if track["id"] not in states]
        if missing:
            raise ValueError("Sync configured tracks before exporting: " + ", ".join(missing))
        for slug, track in sorted(config["tracks"].items()):
            state = states[track["id"]]
            item = {
                "slug": slug, "id": track["id"], "name": track["name"],
                "category_id": track["category_id"], "bonus": track.get("bonus", False),
                "last_synced_at": state["last_success_at"], "last_full_audit_at": state["last_full_at"],
            }
            tracks.append(item)
            by_id[track["id"]] = item
        rows = [dict(r) for r in db.execute("SELECT * FROM current_pbs")]
        history = [dict(r) for r in db.execute("SELECT * FROM wr_history")
                   if r["track_id"] in by_id and r["category_id"] == by_id[r["track_id"]]["category_id"]]
        undated_boards = {tuple(r) for r in db.execute("""
            SELECT DISTINCT track_id, category_id, board_key FROM active_runs WHERE verified_at IS NULL
        """)}
        hall_of_fame = build_hall_of_fame(
            db, config, {"online_top_three": []} if hall_of_fame_config is None else hall_of_fame_config, now=now,
        )
    finally:
        db.execute("RELEASE SAVEPOINT ranking_export")

    boards = defaultdict(list)
    for row in rows:
        track = by_id.get(row["track_id"])
        if track is None or row["category_id"] != track["category_id"]:
            continue
        board = json.loads(row["board_key"])
        direction = DIRECTIONS.get(board.get(MODE_VARIABLE))
        if direction is None or set(board) != {MODE_VARIABLE}:
            raise ValueError(f"Unsupported leaderboard for {track['slug']}: {row['board_key']}")
        boards[track["slug"], direction].append(row)

    players = {}
    identities = {}
    board_records = []
    reigns = merge_wr_reigns(history, now)
    for (slug, direction), runs in sorted(boards.items()):
        wr_time = min(r["time_us"] for r in runs)
        board_records.append({
            "track": slug, "direction": direction, "wr_time_us": wr_time, "player_count": len(runs),
            "wr_holders": sorted(r["player_key"] for r in runs if r["time_us"] == wr_time),
        })
        previous_time = None
        board_rank = 0
        for position, run in enumerate(sorted(runs, key=lambda r: (r["time_us"], r["player_key"])), 1):
            if run["time_us"] != previous_time:
                board_rank = position
                previous_time = run["time_us"]
            key = run["player_key"]
            board_id = run["track_id"], run["category_id"], run["board_key"]
            # Account IDs survive name changes; prefer the most recently observed name.
            identity_order = (run["last_seen_at"], run["verified_at"] or "", run["id"])
            if key not in players:
                players[key] = {"performances": []}
            if key not in identities or identity_order > identities[key]:
                identities[key] = identity_order
                players[key].update(id=run["player_id"], name=run["player_name"], url=run["player_url"])
            players[key]["performances"].append({
                "track": slug, "direction": direction, "run_id": run["id"],
                "time_us": run["time_us"], "wr_time_us": wr_time,
                "gap_us": run["time_us"] - wr_time, "board_rank": board_rank, "is_wr": run["time_us"] == wr_time,
                "gap_percent": 100 * (run["time_us"] - wr_time) / wr_time,
                "points": points(run["time_us"], wr_time), "source_url": run["source_url"],
                "played_on": run["played_on"], "verified_at": run["verified_at"],
                "wr_history": summarize_wr_reigns(reigns.get((key, *board_id), []), board_id not in undated_boards),
            })

    rankings = {}
    for include_bonus in (False, True):
        eligible_tracks = {t["slug"] for t in tracks if include_bonus or not t["bonus"]}
        for direction in ("forward", "reverse", "combined"):
            def eligible(performance):
                return (performance["track"] in eligible_tracks
                        and (direction == "combined" or performance["direction"] == direction))

            entries = []
            for key, player in players.items():
                performances = [p for p in player["performances"] if eligible(p)]
                if not performances:
                    continue
                entries.append({
                    "player_key": key, "player_name": player["name"],
                    "points": math.fsum(p["points"] for p in performances),
                    "boards_played": len(performances),
                    "world_records": sum(p["time_us"] == p["wr_time_us"] for p in performances),
                })
            entries.sort(key=lambda r: (-r["points"], r["player_key"]))
            for position, entry in enumerate(entries, 1):
                previous = entries[position - 2] if position > 1 else None
                entry["rank"] = (previous["rank"] if previous and previous["points"] == entry["points"]
                                 else position)
            board_count = sum(eligible(b) for b in board_records)
            variant = direction + ("-with-bonus" if include_bonus else "-without-bonus")
            rankings[variant] = {
                "direction": direction, "include_bonus": include_bonus,
                "board_count": board_count, "max_points": 10 * board_count, "entries": entries,
            }

    return {
        "schema_version": 1,
        "generated_at": utc(now.isoformat()),
        "source": {"name": "speedrun.com", "url": "https://www.speedrun.com/stk"},
        "scoring": {
            "id": "exponential-v1", "formula": "10 * 10 ** (-50 * (time_us - wr_time_us) / wr_time_us)",
            "wr_points": 10, "gap_percent_for_one_point": 2,
            "aggregation": "sum of each player's best accepted run per track and direction",
            "ties": "equal unrounded totals share a rank; subsequent ranks skip tied positions",
        },
        "tracks": tracks, "boards": board_records,
        "players": dict(sorted(players.items())), "rankings": rankings, "hall_of_fame": hall_of_fame,
    }


def write_rankings(payload, path):
    """Replace the public snapshot only after its complete JSON has been written."""
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(serialized)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
