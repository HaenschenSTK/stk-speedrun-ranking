import argparse
import json
import sqlite3
import sys
import tomllib
from pathlib import Path

from .api import Api
from .database import connect
from .rankings import build_rankings, write_rankings
from .sync import sync

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Local SuperTuxKart speedrun archive")
    parser.add_argument("--db", type=Path, default=ROOT / "data/stk.sqlite3")
    parser.add_argument("--config", type=Path, default=ROOT / "config/tracks.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    update = commands.add_parser("sync", help="Import verified runs; audit all history every 30 days")
    selection = update.add_mutually_exclusive_group()
    selection.add_argument("--track", default="old-mine")
    selection.add_argument("--all", action="store_true", help="Update every configured track, including bonus tracks")
    update.add_argument("--full", action="store_true", help="Read the entire verified run history")
    commands.add_parser("status", help="Show local archive and sync summary")
    export = commands.add_parser("export", help="Calculate six rankings and the Hall of Fame as static JSON")
    export.add_argument("--output", type=Path, default=ROOT / "site/data/rankings.json")
    export.add_argument("--hall-of-fame-config", type=Path, default=ROOT / "config/hall_of_fame.toml")
    for name in ("pbs", "wrs", "history"):
        command = commands.add_parser(name, help="Print local results as JSON")
        command.add_argument("--track", default="old-mine")
    args = parser.parse_args()
    if args.command != "sync" and not args.db.exists():
        parser.error("No database yet. Run sync first.")
    if args.command == "export":
        if args.output.resolve() in (args.db.resolve(), args.config.resolve(), args.hall_of_fame_config.resolve()):
            parser.error("The export output must not overwrite the database or config")
        db = sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
    else:
        db = connect(args.db)
    try:
        if args.command == "sync":
            config = tomllib.loads(args.config.read_text())
            if not args.all and args.track not in config["tracks"]:
                parser.error(f"Track is not allowlisted: {args.track}")
            api = Api()
            slugs = list(config["tracks"]) if args.all else [args.track]
            results = []
            for position, slug in enumerate(slugs, 1):
                if args.all:
                    print(f"[{position}/{len(slugs)}] Syncing {slug}…", file=sys.stderr, flush=True)
                try:
                    results.append(sync(db, api, config, slug, args.full))
                except (OSError, ValueError, sqlite3.Error) as error:
                    parser.exit(1, f"Sync failed for {slug}: {error}\n"
                                "Previously completed tracks are saved. Rerun the command to retry.\n")
            result = results if args.all else results[0]
        elif args.command == "export":
            try:
                config = tomllib.loads(args.config.read_text())
                hall_config = tomllib.loads(args.hall_of_fame_config.read_text())
                payload = build_rankings(db, config, hall_of_fame_config=hall_config)
                write_rankings(payload, args.output)
            except (ValueError, OSError) as error:
                parser.error(str(error))
            result = {"output": str(args.output.resolve()), "rankings": len(payload["rankings"]),
                      "players": len(payload["players"]), "boards": len(payload["boards"]),
                      "hall_of_fame_members": len(payload["hall_of_fame"]["members"])}
        elif args.command == "status":
            result = [dict(row) for row in db.execute("""
                SELECT t.name, s.*, COUNT(r.id) AS stored_runs,
                       SUM(CASE WHEN r.unavailable_since IS NULL AND r.status = 'verified' THEN 1 ELSE 0 END) AS active_runs,
                       SUM(CASE WHEN r.id IS NOT NULL AND r.verified_at IS NULL THEN 1 ELSE 0 END) AS missing_verification_dates
                FROM sync_state s JOIN tracks t ON t.id = s.track_id
                LEFT JOIN runs r ON r.track_id = t.id GROUP BY t.id
            """)]
        else:
            view = {"pbs": "current_pbs", "wrs": "current_wrs", "history": "wr_history"}[args.command]
            history_columns = ", r.wr_started_at, r.wr_ended_at" if args.command == "history" else ""
            ordering = "r.verified_at, r.id" if args.command == "history" else "r.time_us, r.id"
            result = [dict(row) for row in db.execute(f"""
                SELECT r.id, t.name AS track, c.name AS category, r.board_label,
                       r.player_name, r.time_us, r.played_on, r.verified_at, r.source_url
                       {history_columns}
                FROM {view} r JOIN tracks t ON t.id = r.track_id
                JOIN categories c ON c.id = r.category_id
                WHERE t.slug = ? ORDER BY c.name, r.board_label, {ordering}
            """, (args.track,))]
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
