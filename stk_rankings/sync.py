import json
from datetime import datetime, timedelta, timezone

from .database import upsert_run, utc


def sync(db, api, config, slug="old-mine", full=False, now=None):
    now = now or datetime.now(timezone.utc)
    seen_at = utc(now.isoformat())
    track = config["tracks"][slug]
    game_id = config["game_id"]
    state = db.execute("SELECT * FROM sync_state WHERE track_id = ?", (track["id"],)).fetchone()
    full = full or state is None or now - datetime.fromisoformat(state["last_full_at"]) >= timedelta(days=30)
    cutoff = None
    if not full and state["watermark"]:
        cutoff = utc((datetime.fromisoformat(state["watermark"]) - timedelta(days=7)).isoformat())
    cached = db.execute("SELECT * FROM metadata WHERE game_id = ?", (game_id,)).fetchone()
    refresh_metadata = cached is None or now - datetime.fromisoformat(cached["fetched_at"]) >= timedelta(days=30)
    requests_before = api.requests
    game = (api.get(f"games/{game_id}", embed="levels,categories,variables")["data"]
            if refresh_metadata else json.loads(cached["raw_json"]))
    categories = {c["id"]: c for c in game["categories"]["data"]}
    level = next(level for level in game["levels"]["data"] if level["id"] == track["id"])
    category_id = track["category_id"]
    if categories[category_id]["type"] != "per-level":
        raise ValueError(f"Not an IL category: {category_id}")

    fetched = {}
    exhausted = False
    for runs, last_page in api.run_pages(game_id, track["id"], category_id):
        for run in runs:
            if (run["game"] == game_id and run["level"] == track["id"]
                    and run["category"] == category_id and run["status"]["status"] == "verified"):
                fetched[run["id"]] = run
        exhausted = last_page
        # Process the entire boundary page. Equal timestamps never cut off a page early.
        dates = [utc(r["status"].get("verify-date")) for r in runs]
        if last_page or (cutoff and any(date is not None and date < cutoff for date in dates)):
            break

    dates = [utc(run["status"].get("verify-date")) for run in fetched.values()]
    watermark = max([date for date in dates if date] +
                    ([utc(state["watermark"])] if state and state["watermark"] else []), default=None)
    request_count = api.requests - requests_before
    # Nothing advances unless the entire fetch and import succeeded.
    with db:
        db.execute("INSERT INTO tracks VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE "
                   "SET slug=excluded.slug, name=excluded.name", (track["id"], slug, level["name"]))
        db.execute("INSERT INTO categories VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                   (category_id, categories[category_id]["name"]))
        if refresh_metadata:
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?, ?, ?)",
                       (game_id, seen_at, json.dumps(game)))
        if exhausted:
            # Preserve missing/rejected runs as evidence, but exclude them from current queries.
            # Upserts below clear this flag for everything still present in the verified feed.
            db.execute("UPDATE runs SET unavailable_since = COALESCE(unavailable_since, ?) WHERE track_id = ?",
                       (seen_at, track["id"]))
        for run in fetched.values():
            upsert_run(db, run, game["variables"]["data"], seen_at)
        db.execute("INSERT OR REPLACE INTO sync_state VALUES (?, ?, ?, ?, ?, ?)",
                   (track["id"], watermark, seen_at,
                    seen_at if exhausted else state["last_full_at"], request_count, len(fetched)))
    return {"track": slug, "mode": "full" if exhausted else "incremental",
            "fetched": len(fetched), "requests": request_count, "watermark": watermark}
