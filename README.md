# STK Speedrun Ranking

A small Python/SQLite archive and cross-track ranking calculator. Imports the
**23 allowlisted tracks, 1.x only**, with separate **Normal (forward)** and
**Reverse** boards. It keeps superseded runs as well as current PBs and exports
six speedrun rankings plus the Hall of Fame as static JSON.
The static website in `site/` displays all six rankings, player breakdowns, and the
Hall of Fame. No backend, JavaScript dependencies, or recurring sync is required.

Requires Python 3.11+; no third-party dependencies or API key. Run from this folder:

```bash
python3 -m stk_rankings sync
python3 -m stk_rankings status
python3 -m stk_rankings pbs
python3 -m stk_rankings wrs
python3 -m stk_rankings history
python3 -m stk_rankings export
```

Commands default to Old Mine. Select Gran Paradiso Island explicitly:

```bash
python3 -m stk_rankings sync --track gran-paradiso-island
python3 -m stk_rankings pbs --track gran-paradiso-island
python3 -m stk_rankings wrs --track gran-paradiso-island
python3 -m stk_rankings history --track gran-paradiso-island
```

The database is `data/stk.sqlite3`. Results print as JSON. To force an audit:

```bash
python3 -m stk_rankings sync --full
```

An alternate database/config can be passed **before** the command:

```bash
python3 -m stk_rankings --db /tmp/stk.sqlite3 --config config/tracks.toml sync
```

## Scope and API findings

The allowlist is in `config/tracks.toml`:

| Resource | speedrun.com ID |
| --- | --- |
| SuperTuxKart | `46w9mq1r` |
| Old Mine | `ldyxxp93` |
| Gran Paradiso Island | `rdn7759m` |
| 1.x IL category | `7kj1gq4k` |
| Mode variable | `j84kz64n` |
| Normal / Reverse | `4qyn7z31` / `mln5e86l` |
| Sub-version variable | `2lgry2qn` |
| Gran Paradiso Island Glitches variable | `ql690vjl` |
| Glitches Yes / No | `q65kdpnl` / `lmoj5py1` |

Sub-version (1.0, 1.4, 1.5, etc.) is retained as a variable, but does not split a
leaderboard: the API marks Mode as a subcategory and Sub-version as an ordinary
variable. Other version categories, Egg Hunt, Grand Prix and story mode are excluded.
The config explicitly allowlists 23 tracks; nothing automatically imports every
level returned by the API. Each sync command updates one track. The resource table
above lists the two tracks used by the offline import fixtures.

Gran Paradiso Island's **Glitches** variable is stored for every run in
`run_variable_values` and in the original JSON. Its Yes/No labels are retained in
the cached metadata. It is not an API subcategory and is not currently used to
filter or split PBs, WRs, or history: each direction combines Yes and No runs.

The source is the paginated `/runs` endpoint with game, level, category and verified
status filters, ordered by verification date descending. This includes obsolete PBs.
`embed=players` supplies names without requesting each user individually.

Live checks on **2026-09-19 UTC** found 26 verified Old Mine 1.x runs (22 Normal, 4 Reverse),
all with verification dates. The calculated PBs matched both complete live
leaderboards: 9 Normal players, 3 Reverse players. Current WRs were Haenschen's
1:32.338 Normal and trolli123's 1:32.671 Reverse. The reconstructed history has 18
record performances across the two boards.

Gran Paradiso Island's initial import added 32 verified 1.x runs (25 Normal,
7 Reverse) in one request using the existing metadata cache. All 32 have Glitches
values: 8 Yes and 24 No. Both tracks share the same database.

## Static rankings and website data

The agreed score for a PB is:

```text
gap_percent = 100 * (time_us - wr_time_us) / wr_time_us
points = 10 * 10 ** (-gap_percent / 2)
```

A WR earns 10 points, WR + 2% earns 1 point, and WR + 10% earns 0.0001
points. There is no hard cutoff. Each player contributes one current PB per track
and direction, compared with that board's current WR. Missing runs contribute
zero. Tied WRs each earn 10 points. Only available, verified runs in configured
categories count; Glitches Yes and No remain combined as on the archived boards.

Totals sum the unrounded scores. Combined totals include both directions, with no
averaging or participation bonus. Equal totals share competition ranks (1, 1, 3);
player keys give tied rows a stable display order. Players with no eligible runs
are omitted from that variant. Account IDs identify players across name changes;
guest identity still relies on the guest name.

Export the current database without any network calls or database changes:

```bash
python3 -m stk_rankings export
python3 -m stk_rankings export --output /tmp/rankings.json
```

The default output is `site/data/rankings.json`. It contains these six keys under
`rankings`:

- `forward-without-bonus`
- `reverse-without-bonus`
- `combined-without-bonus`
- `forward-with-bonus`
- `reverse-with-bonus`
- `combined-with-bonus`

Freytra Peaks and Drainage Dash have `bonus = true` in `config/tracks.toml`.
Including them changes only which tracks are summed, not the scoring formula.
Currently neither has reverse PBs in the archive, so the reverse variants match.

The JSON contract (`schema_version: 1`) is:

| Field | Contents |
| --- | --- |
| `generated_at` | UTC time this export was built; **not** the time the API was last checked |
| `source`, `scoring` | Public source attribution and the versioned scoring rule |
| `tracks` | Track IDs, slugs, names, categories, bonus flags, and per-track sync/audit timestamps |
| `boards` | Track slug, direction, and WR time in integer microseconds for each board with eligible PBs |
| `players` | Map keyed by stable player key, containing profile details and per-track point contributions |
| `rankings` | The six variants, each with direction, bonus flag, board count, maximum points, and ordered entries |
| `hall_of_fame` | Hall of Fame table, eligibility rules, confirmed online players, and audited reign breakdowns |

Each ranking entry contains `rank`, `player_key`, `player_name`, `points`,
`boards_played`, and `world_records`. Each player's `performances` list contains
track slug, direction, PB run ID, PB/WR times, gap percentage, points, and a source
link, together with profile statistics described below. This supports score breakdowns without shipping the private SQLite archive
or repeating every performance in all six rankings. Raw API JSON, moderator IDs,
and video metadata are not exported.

`board_count` and `max_points` count boards that actually have eligible PBs and a
reference WR. A synchronized track with no reverse runs does not create a phantom
reverse board. Every configured track must have a successful sync before export;
otherwise the command fails and leaves the previous JSON untouched. Export also
fails explicitly if a new subcategory needs a scoring decision. Publication uses
one consistent database snapshot and replaces the JSON file atomically.

## Website and GitHub Pages

The website is plain HTML, CSS, and JavaScript. Its default view is the forward
speedrun ranking without bonus tracks. It includes direction/bonus filters,
player search, shareable player profiles, expandable run and WR-reign histories,
and Hall of Fame and “How it works” pages. Blue accents, system light/dark mode,
and responsive tables keep the same information readable on desktop and mobile.

To preview it locally, run from this folder:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Then open <http://127.0.0.1:8000/>. Use an HTTP server rather than opening
`index.html` as a local file: the site loads `./data/rankings.json` with `fetch`.
All asset/data paths are relative, and hash links keep profile URLs refreshable
under a GitHub Pages repository subpath without server routing.

The workflow in `.github/workflows/pages.yml` publishes **only `site/`** when
its files change on `main`, or when run manually on `main`. To enable it in a
GitHub repository, choose **Settings → Pages → Build and deployment → Source:
GitHub Actions**, then push these files to `main`. If the publishing branch has
another name, change both branch checks in the workflow. The repository/Pages
settings must be configured on GitHub; adding the workflow locally does not
publish the website.

Python and SQLite run locally before publication. The browser never queries
SQLite or speedrun.com, and the workflow does not sync or regenerate the data.
After refreshing the archive, export and publish the updated
`site/data/rankings.json`. Source-check timestamps are displayed separately from
the export timestamp and WR-hours cutoff. No automatic update schedule is set.
See [GitHub’s custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

Checks:

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_site.mjs
```

The JavaScript checks use Node’s built-in test runner, with no installation of
packages. They verify URL state, all six profile/score breakdowns, safe source
links, missing PBs, and the published Hall of Fame order. Browser checks should
also cover filters, history navigation, track expansion, and mobile layouts.

To refresh all configured tracks and rebuild the JSON locally:

```bash
python3 - <<'PY'
import subprocess
import sys
import tomllib
from pathlib import Path

config = tomllib.loads(Path('config/tracks.toml').read_text())
for slug in config['tracks']:
    subprocess.run([sys.executable, '-m', 'stk_rankings', 'sync', '--track', slug, '--full'], check=True)
subprocess.run([sys.executable, '-m', 'stk_rankings', 'export'], check=True)
PY
```

This stops if a sync fails, before generating a new public snapshot. The website
will change only after the newly generated files are published. Display the
per-track sync timestamps (or their range) so visitors can judge data freshness.

## Player profiles and website priority

The speedrun rankings are the website's main entry point; the Hall of Fame is a
secondary view. Clicking a player opens their profile while preserving the
selected direction and bonus-track setting. The combined ranking shows
separate forward and reverse rows, since each has its own PB, WR, and reigns.

Every player's `performances` rows now include:

| Field | Profile use |
| --- | --- |
| `time_us`, `wr_time_us`, `gap_percent`, `points` | PB, current WR, percentage behind WR, and point contribution |
| `gap_us` | Absolute time behind the WR, in microseconds |
| `board_rank`, `is_wr` | Current per-track rank (shared competition ranks for ties) and WR status |
| `played_on`, `verified_at`, `source_url` | PB date, acceptance timestamp, and link to the submitted run |
| `wr_history.total_days` | Sum of all WR reigns on this track and direction, without a minimum duration |
| `wr_history.longest_reign_days` | Longest uninterrupted WR reign on this track and direction |
| `wr_history.current_reign_days` | Duration of the ongoing reign, or zero if no ongoing reign is known |
| `wr_history.reign_count`, `wr_history.reigns` | Number of separate reigns and their dates, durations, and source records |

Use **Behind WR (%)** as the percentage heading: a time 2% slower than the WR is
shown as `2%`, rather than `102%`. `boards` also includes `player_count` and
`wr_holders` (player keys), so profiles can show the current record holder and
the PB's rank out of the board's players. Missing PB dates remain `null`.

WR statistics are calculated for **every ranking player**, including players
outside the Hall of Fame, for both directions and bonus tracks. A player with no
WR history has zero days and an empty reign list. A run with an unknown
verification date makes that board's chronology uncertain: `dates_complete` is
false, duration/count summaries are `null`, and no guessed reigns are shown.
The existing Hall of Fame validation still rejects missing dates on official
forward boards. Available history remains subject to deleted or missing runs.

Profiles and the Hall of Fame share the same reign-merging calculation. Improving
one's own WR continues the reign; losing and reclaiming it produces separate
reigns. Durations use exact microseconds internally; day values divide by 24
hours and should be rounded only for display. Current reigns accrue through
`generated_at`. The 30-day Hall of Fame threshold does not filter profile totals.

For a static client, resolve a clicked entry's `player_key` in `data.players`,
then filter that player's performances using the selected ranking's `direction`
and `include_bonus` values. Join track slugs to `data.tracks` for names and bonus
flags. Missing tracks can be shown as no PB and zero points. Summing displayed
rows' unrounded points reproduces the selected ranking's total.

The website implements this interaction. PB progression can later use the archived historical runs. A chart of past
overall ranks or points would need dated snapshots or an explicit reconstruction
policy; it cannot be inferred from this current export alone.

## STK Hall of Fame

The same `export` command also builds the Hall of Fame in `site/data/rankings.json`:

```javascript
const hallOfFameRows = data.hall_of_fame.members;
```

It uses **forward only, 1.x, the 21 official tracks without bonus tracks**.
Speedrun qualification requires **30 continuous days of WR ownership on each of
three distinct tracks**, at any time in the available history. There is **no
release-date cutoff**: early reigns qualify too. Total WR-hours also includes
the full lifetime history, including short reigns and the launch period.
The qualifying reigns need not overlap. Repeated qualifying reigns on one track
still count as one qualifying track. Tied records count for every holder.

Reigns start/end at verification timestamps. Improving your own WR continues the
same reign; losing and later reclaiming the WR starts a separate reign. Thirty
days means exactly 720 hours, with an inclusive threshold, rather than one
calendar month. Ongoing reigns accrue through the export's
`generated_at` timestamp, also recorded as `hall_of_fame.as_of`.

**Hall of Fame** contains speedrun-qualified players who also have owner-confirmed
online top-three qualification. A player appears in this table only after both
requirements are met. Losing current records does not remove historical
qualification. Corrections to the underlying run history can change the results.

The separate `config/hall_of_fame.toml` records online eligibility by stable
speedrun.com account ID. Being listed confirms a top-three placement **after the
online ranking's initial three months**. The seven initial entries were supplied
by the project owner; exact online placement dates were not supplied or inferred.
The display name is only a label and does not control matching. Players must
provide evidence of their online placement to the project owner. After accepting
that evidence, the owner adds the player to this config and reruns the export;
the player appears if the speedrun requirement is also satisfied. Add an entry with:

```toml
[[online_top_three]]
player_id = "speedrun-com-account-id"
name = "Player name"
```

For an alternate list, use:

```bash
python3 -m stk_rankings export --hall-of-fame-config /path/to/hall_of_fame.toml
```

The table sorts by **total lifetime WR-hours descending**, with shared competition
ranks for equal exact durations, even when qualifying-track counts differ.
Qualifying-track counts determine admission, not placement. Its entries
contain `rank`, `player_key`, `player_name`, `qualifying_track_count`, and
`total_wr_hours`. Hours include **every eligible reign**, even short ones, reigns
before qualification, the launch period, and tracks with no qualifying reign. Hours on different
tracks add together: two WRs held for 100 hours contribute 200 WR-hours. Only
overlapping/adjacent intervals for the same player on the same track are merged.

`hall_of_fame.players` provides every historical record holder's qualifying-track
list, the date the third track first qualified, online confirmation status, and
all merged reigns with source run links, exact lifetime durations, and
`qualifies_at` threshold dates.
This includes players who have not yet met the three-track requirement, for
profile and eligibility auditing. This audit data is not a separate ranking; the Hall of Fame
table contains only players meeting both the speedrun and online requirements.

Both speedrun and Hall of Fame results are built from one read-only database
snapshot and published in the same atomic JSON replacement. Missing or malformed
online config leaves the prior export intact. A missing verification date on an
eligible forward run also prevents export, because its effect on reigns cannot
be reconstructed reliably. Records deleted before archiving cannot be recovered;
totals describe the available verified history, not a complete moderation log.

## Updates

- Initial sync fetches game metadata and the full verified history, up to 200 runs
  per page, following the API's next-page links.
- Subsequent syncs reuse metadata for 30 days. They scan newest verifications first
  and stop after a complete page crosses a seven-day overlap before the saved
  verification watermark. Equal timestamps are included.
- If the response reaches the last page, it is a full audit. Currently each track's
  1.x runs fit in one page, so a repeat sync refreshes **that track in one request**.
  Initial import used two requests; a live repeat used one and kept exactly 26 rows.
- A full audit is forced after 30 days without one, or by `--full`. Missing runs are
  marked unavailable, retained in the archive, and excluded from the query views.
  If they reappear, the unavailable flag is cleared.
- Fetching completes before an atomic database transaction. Failed imports do not
  advance the watermark or partially replace the data. Errors are shown directly;
  requests are paced at least 0.65 seconds apart, with a 30-second timeout. There
  are no background retries, services, or detailed sync logs.

For larger datasets, a partial incremental scan cannot detect edits, removals, or
backdated verifications outside its overlap. Those are caught by the next full
audit. The local PB/WR views can be stale until then; use `--full` before publishing
rankings if exact reconciliation is needed. For the present single-page datasets,
every successful sync reconciles all runs of the selected track. The API responses inspected did not
include rate-limit headers; if throttled, wait and rerun the command.

## Data and queries

`runs` stores one player directly on each row: registered user ID (or a guest name
key), name, time in integer microseconds, played date, submitted/verified timestamps,
examiner, source URL, videos, original run JSON, first/last observation timestamps,
and an unavailable marker. All timestamps are UTC; missing dates remain NULL.
`run_variable_values` keeps every variable selection. `metadata` caches the API's
game/category/variable descriptions; `tracks`, `categories`, and `sync_state` provide
the small amount of supporting state. There is no `run_players` table.

SQLite views:

- `current_pbs`: one fastest available verified run per player, track, category and
  subcategory combination. A repeated equal PB uses the earliest known verification.
- `current_wrs`: all players tied for the fastest current PB on each board.
- `wr_history`: record performances ordered by **verification date**, with
  `wr_started_at` and the first strictly faster run's verification as `wr_ended_at`.
  A tie starts a shared reign and does not end another player's reign. Repeating
  one's own equal record does not create another record. A faster run ends the old
  performance's interval even when the same player improves their own WR.

Example using Python's built-in SQLite support:

```python
import sqlite3
db = sqlite3.connect("data/stk.sqlite3")
for row in db.execute("""
    SELECT player_name, board_label, time_us, wr_started_at, wr_ended_at
    FROM wr_history ORDER BY board_label, wr_started_at
"""):
    print(row)
```

History is reconstructed from currently available verified runs, not a complete
audit log of moderator decisions. Previously deleted runs cannot be recovered;
later removals remain stored but are excluded from the views. Unknown verification
dates cannot be placed in history and are excluded from `wr_history` while remaining
eligible for current PBs/WRs. In that case an open historical interval only means
no *dated* faster run is known. Guest identity relies on the supplied name, since
the API has no account ID for guests. Hall of Fame totals merge uninterrupted
ownership per player and track, while adding hours across different tracks.

## Tests and sources

```bash
python3 -m unittest discover -s tests -v
```

Tests run entirely offline using a reduced public API snapshot captured on
2026-09-19 UTC plus synthetic cases for pagination, ties, guests, missing dates,
incremental boundaries, deletion/reappearance, and transactional failures.
The Old Mine fixture deliberately includes older categories to test their exclusion.
The Gran Paradiso Island fixture contains four real runs covering both Glitches
values and both directions; tests check combined PBs and isolation between tracks.

- [SuperTuxKart on speedrun.com](https://www.speedrun.com/stk)
- [Old Mine runs API](https://www.speedrun.com/api/v1/runs?game=46w9mq1r&level=ldyxxp93&category=7kj1gq4k&status=verified)
- [API run documentation](https://github.com/speedruncomorg/api/blob/master/version1/runs.md)
- [Pagination](https://github.com/speedruncomorg/api/blob/master/version1/pagination.md)
- [Leaderboard filtering](https://github.com/speedruncomorg/api/blob/master/version1/leaderboards.md)

Run data is sourced from speedrun.com and its contributors. The API documentation
licenses original API content under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/);
linked images/videos belong to their respective owners. Keep source attribution
when using the data in the website.
