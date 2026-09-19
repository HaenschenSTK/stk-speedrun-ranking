"""Lifetime forward WR achievements on the official, non-bonus tracks."""

import json
from datetime import datetime, timedelta, timezone

from .database import utc
from .wr_reigns import merge_wr_reigns

FORWARD_BOARD = {"j84kz64n": "4qyn7z31"}
REVERSE_BOARD = {"j84kz64n": "mln5e86l"}
HOUR_US = 3_600_000_000
MINIMUM_REIGN_DAYS = 30


def confirmed_players(config):
    entries = config.get("online_top_three")
    if not isinstance(entries, list):
        raise ValueError("Hall of Fame config: online_top_three must be an array of tables")
    confirmed = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Hall of Fame config: each online_top_three entry must be a table")
        player_id, name = entry.get("player_id"), entry.get("name")
        if not isinstance(player_id, str) or not player_id.strip() or not isinstance(name, str) or not name.strip():
            raise ValueError("Hall of Fame config: each entry needs a player_id and name")
        key = "user:" + player_id
        if key in confirmed:
            raise ValueError(f"Hall of Fame config: duplicate player_id {player_id}")
        confirmed[key] = {"player_id": player_id, "name": name}
    return confirmed


def build_hall_of_fame(db, config, online_config, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Hall of Fame evaluation time must include a timezone")
    now = now.astimezone(timezone.utc)
    confirmed = confirmed_players(online_config)
    tracks = {t["id"]: dict(t, slug=slug) for slug, t in config["tracks"].items() if not t.get("bonus", False)}

    def eligible(row):
        track = tracks.get(row["track_id"])
        if track is None or track["category_id"] != row["category_id"]:
            return False
        board = json.loads(row["board_key"])
        if board not in (FORWARD_BOARD, REVERSE_BOARD):
            raise ValueError(f"Unsupported leaderboard for Hall of Fame track {track['slug']}: {row['board_key']}")
        return board == FORWARD_BOARD

    # A savepoint preserves any caller transaction and allows the site export to
    # include both rankings and WR history from the same database snapshot.
    db.execute("SAVEPOINT hall_of_fame_export")
    try:
        states = {r["track_id"] for r in db.execute("SELECT track_id FROM sync_state")}
        missing = [t["slug"] for key, t in tracks.items() if key not in states]
        if missing:
            raise ValueError("Sync configured tracks before exporting Hall of Fame: " + ", ".join(sorted(missing)))
        active = [dict(r) for r in db.execute("SELECT * FROM active_runs") if eligible(r)]
        history = [dict(r) for r in db.execute("SELECT * FROM wr_history") if eligible(r)]
    finally:
        db.execute("RELEASE SAVEPOINT hall_of_fame_export")

    # An undated run could have ended a dated reign. Do not award guessed hours.
    undated = sorted(r["id"] for r in active if r["verified_at"] is None)
    if undated:
        raise ValueError("Cannot calculate Hall of Fame with missing forward verification dates: " + ", ".join(undated))
    identities = {}
    for run in sorted(active, key=lambda r: (r["last_seen_at"], r["verified_at"], r["id"])):
        identities[run["player_key"]] = {"id": run["player_id"], "name": run["player_name"], "url": run["player_url"]}

    players = {}
    merged = merge_wr_reigns(history, now)
    for (key, track_id, _, _), reigns in sorted(merged.items(), key=lambda item: (item[0][0], tracks[item[0][1]]["slug"])):
        slug = tracks[track_id]["slug"]
        player = players.setdefault(key, dict(identities[key], reigns=[]))
        for reign in reigns:
            threshold = datetime.fromisoformat(reign["started_at"]) + timedelta(days=MINIMUM_REIGN_DAYS)
            player["reigns"].append({
                **reign, "track": slug, "hours": reign["duration_us"] / HOUR_US,
                "qualifies": datetime.fromisoformat(reign["counted_until"]) >= threshold,
                "qualifies_at": utc(threshold.isoformat()),
            })

    members = []
    for key, player in players.items():
        qualifying = {}
        for reign in player["reigns"]:
            if reign["qualifies"]:
                qualifying[reign["track"]] = min(qualifying.get(reign["track"], reign["qualifies_at"]),
                                                 reign["qualifies_at"])
        total_us = sum(r["duration_us"] for r in player["reigns"])
        player.update(
            qualifying_tracks=sorted(qualifying), qualifying_track_count=len(qualifying),
            total_wr_duration_us=total_us, total_wr_hours=total_us / HOUR_US,
            speedrun_qualified_at=sorted(qualifying.values())[2] if len(qualifying) >= 3 else None,
            online_top_three_confirmed=key in confirmed,
        )
        if len(qualifying) >= 3 and key in confirmed:
            entry = {"player_key": key, "player_name": player["name"],
                     "qualifying_track_count": len(qualifying), "total_wr_hours": player["total_wr_hours"]}
            members.append(entry)

    def rank_table(entries):
        def score(entry):
            return players[entry["player_key"]]["total_wr_duration_us"]
        entries.sort(key=lambda e: (-score(e), e["player_key"]))
        for position, entry in enumerate(entries, 1):
            previous = entries[position - 2] if position > 1 else None
            entry["rank"] = previous["rank"] if previous and score(previous) == score(entry) else position

    rank_table(members)
    return {
        "as_of": utc(now.isoformat()),
        "rules": {
            "direction": "forward", "include_bonus": False, "track_count": len(tracks),
            "minimum_qualifying_tracks": 3, "minimum_reign_days": MINIMUM_REIGN_DAYS,
            "qualifying_reigns": "all lifetime reigns; no release-date cutoff",
            "reign_dates": "verification dates; successive self-improvements remain one continuous reign",
            "total_wr_hours": "all lifetime reigns on eligible tracks, including short reigns and the launch period, added across tracks",
            "online_requirement": "top three after the online ranking's initial three months; owner-confirmed config",
            "ordering": ["total_wr_hours descending"],
        },
        "online_top_three": dict(sorted(confirmed.items())),
        "members": members, "players": players,
    }
