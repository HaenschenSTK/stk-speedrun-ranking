import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


def utc(value):
    """Keep missing dates missing; normalize timestamps for SQLite comparisons."""
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(Path(__file__).with_name("schema.sql").read_text())
    return db


def upsert_run(db, run, variables, seen_at):
    player, = run["players"]["data"]
    player_id = player.get("id")
    name = player["names"]["international"] if player["rel"] == "user" else player["name"]
    player_key = "user:" + player_id if player_id else "guest:" + name
    # Sub-version is retained, but it is not a separate leaderboard on speedrun.com.
    subcategories = {
        v["id"]: run["values"].get(v["id"])
        for v in variables
        if v["is-subcategory"] and v["category"] in (None, run["category"])
        and (v["scope"]["type"] == "all-levels"
             or v["scope"].get("level") == run["level"])
    }
    labels = [
        v["name"] + "=" + v["values"]["values"].get(subcategories[v["id"]], {}).get("label", "Unknown")
        for v in variables if v["id"] in subcategories
    ]
    row = {
        "id": run["id"], "track_id": run["level"], "category_id": run["category"],
        "board_key": json.dumps(subcategories, sort_keys=True), "board_label": ", ".join(labels),
        "player_key": player_key, "player_id": player_id, "player_name": name,
        "player_url": player.get("weblink") or player.get("uri"),
        "time_us": int(Decimal(str(run["times"]["primary_t"])) * 1_000_000),
        "played_on": run.get("date"), "submitted_at": utc(run.get("submitted")),
        "verified_at": utc(run["status"].get("verify-date")),
        "examiner_id": run["status"].get("examiner"), "status": run["status"]["status"],
        "source_url": run["weblink"], "videos_json": json.dumps(run.get("videos")),
        "raw_json": json.dumps(run, ensure_ascii=False),
        "first_seen_at": seen_at, "last_seen_at": seen_at, "unavailable_since": None,
    }
    updates = ", ".join(f"{key}=excluded.{key}" for key in row if key not in ("id", "first_seen_at"))
    db.execute(f"INSERT INTO runs ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)}) "
               f"ON CONFLICT(id) DO UPDATE SET {updates}", tuple(row.values()))
    db.execute("DELETE FROM run_variable_values WHERE run_id = ?", (run["id"],))
    db.executemany("INSERT INTO run_variable_values VALUES (?, ?, ?)",
                   [(run["id"], key, value) for key, value in run["values"].items()])
