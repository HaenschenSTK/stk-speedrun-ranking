PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    game_id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES tracks(id),
    category_id TEXT NOT NULL REFERENCES categories(id),
    board_key TEXT NOT NULL,
    board_label TEXT NOT NULL,
    player_key TEXT NOT NULL,
    player_id TEXT,
    player_name TEXT NOT NULL,
    player_url TEXT,
    time_us INTEGER NOT NULL CHECK(time_us > 0),
    played_on TEXT,
    submitted_at TEXT,
    verified_at TEXT,
    examiner_id TEXT,
    status TEXT NOT NULL,
    source_url TEXT NOT NULL,
    videos_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    unavailable_since TEXT
);
CREATE INDEX IF NOT EXISTS runs_board
    ON runs(track_id, category_id, board_key, time_us, verified_at);
CREATE TABLE IF NOT EXISTS run_variable_values (
    run_id TEXT NOT NULL REFERENCES runs(id),
    variable_id TEXT NOT NULL,
    value_id TEXT NOT NULL,
    PRIMARY KEY(run_id, variable_id)
);
CREATE TABLE IF NOT EXISTS sync_state (
    track_id TEXT PRIMARY KEY REFERENCES tracks(id),
    watermark TEXT,
    last_success_at TEXT NOT NULL,
    last_full_at TEXT NOT NULL,
    request_count INTEGER NOT NULL,
    fetched_count INTEGER NOT NULL
);

CREATE VIEW IF NOT EXISTS active_runs AS
    SELECT * FROM runs WHERE status = 'verified' AND unavailable_since IS NULL;

-- One best run per player per board. Equal PBs choose the earliest known verification.
CREATE VIEW IF NOT EXISTS current_pbs AS
    SELECT * FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY track_id, category_id, board_key, player_key
            ORDER BY time_us, verified_at IS NULL, verified_at, id
        ) AS pb_order FROM active_runs
    ) WHERE pb_order = 1;

CREATE VIEW IF NOT EXISTS current_wrs AS
    SELECT p.* FROM current_pbs p
    WHERE time_us = (
        SELECT MIN(q.time_us) FROM current_pbs q
        WHERE q.track_id = p.track_id AND q.category_id = p.category_id
          AND q.board_key = p.board_key
    );

-- Reconstruct records in verification order, not the date a run was played.
-- A tie starts a shared reign; only a strictly faster run ends it.
CREATE VIEW IF NOT EXISTS wr_history AS
    SELECT r.*, r.verified_at AS wr_started_at,
        (SELECT MIN(f.verified_at) FROM active_runs f
         WHERE f.track_id = r.track_id AND f.category_id = r.category_id
           AND f.board_key = r.board_key AND f.time_us < r.time_us
           AND f.verified_at > r.verified_at) AS wr_ended_at
    FROM active_runs r
    WHERE r.verified_at IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM active_runs f
        WHERE f.track_id = r.track_id AND f.category_id = r.category_id
          AND f.board_key = r.board_key AND f.time_us < r.time_us
          AND f.verified_at <= r.verified_at
      )
      AND NOT EXISTS (
        SELECT 1 FROM active_runs p
        WHERE p.track_id = r.track_id AND p.category_id = r.category_id
          AND p.board_key = r.board_key AND p.player_key = r.player_key
          AND p.time_us = r.time_us
          AND (p.verified_at < r.verified_at
               OR (p.verified_at = r.verified_at AND p.id < r.id))
      );

