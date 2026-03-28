# MLB ABS Tracker — Project Notes

## Deployment

- **GitHub**: https://github.com/aarrgh/abs-tracker
- **Render (production)**: https://abs-tracker.onrender.com

## Project Structure

```
abs_tracker/
  models.py    — dataclasses: Pitch, ABSZone, MissedOpportunity, Game
  pg_models.py — SQLAlchemy ORM: Game + Take tables (PostgreSQL)
  fetcher.py   — MLB Stats API client + height cache + parse_height_to_feet()
                 fetch_games_for_date() returns structured game list (gamePk, teams, status)
  parser.py    — parse_game() → (list[Pitch], list[MissedOpportunity])
                 extract_hp_umpire() / extract_catchers() — game-level context from feed
  analyzer.py  — pandas aggregations by batter, pitcher, umpire
  db.py        — SQLite schema + CRUD (init_db, store_game, load_pitches, etc.)
  sync.py      — season sync loop; OPENING_DAY_2026 = "2026-03-26"
  main.py      — CLI entry point; _HTML_TEMPLATE = inline SVG/JS for `plot` command
  server.py    — Flask web UI; _INDEX_HTML = single-page app with two tabs:
                 Tab 1 "Game View": auto-loaded game list + date/team filters + SVG plot
                 Tab 2 "Statistics": 4 sub-tabs (Batters/Pitchers/Catchers/Umpires) with
                   sortable tables fed from /api/stats/* PostgreSQL routes

ingestion.py    — PostgreSQL ingestion pipeline (standalone script, uses pg_models)
.env            — DATABASE_URL (never committed; listed in .gitignore)
requirements.txt — requests, pandas, flask, gunicorn, sqlalchemy, psycopg2-binary, python-dotenv
Procfile        — Render/gunicorn entry point: `web: gunicorn abs_tracker.server:app --bind 0.0.0.0:$PORT`
render.yaml     — Render service config (runtime: python, buildCommand, startCommand, PYTHON_VERSION=3.11.0)
.gitignore      — excludes __pycache__, *.pyc, .env, venv/, .DS_Store, *.db
```

## Web UI Tab Structure

`_INDEX_HTML` in `server.py` is a two-tab single-page app. Tab switching is JS-only (no reload).
URL hash updates on switch (`#game` / `#stats`) so direct links work.

**Game View tab** (`#game`): existing SVG plot + sidebar (unchanged).

**Statistics tab** (`#stats`): four sub-tabs — Batters, Pitchers, Catchers, Umpires.
- Data fetched from `/api/stats/<entity>` on first click, cached in `statsCache` for the session.
- Each table is sortable (click any column header; direction toggled; sort state per sub-tab).
- Name filter input above each table — client-side, real-time, no fetch.
- Default sort: total takes descending.
- Column alignment: name/team columns left-aligned (`lft:true` in `ECOLS`); all others right.
- Percentage columns (`pct:true`) display as `"12.3%"` or `"—"` if null (e.g. success rate with 0 challenges).

**Stats column definitions** (`ECOLS` object in JS):
- `batters`: Player, Team, Takes, Missed Opp, Challenges, Successful, Failed, Success%, Wrong Calls, Wrong%
- `pitchers`: Player, Team, Takes, Missed Opp, Challenges, Won, Lost, Wrong For, Wrong Against
- `catchers`: Player, Team, Takes, Challenges, Successful, Failed, Success%, Missed Opp, Wrong For, Wrong Against
- `umpires`: Umpire, Games, Takes, Correct, Incorrect, Accuracy%, Wrong Strikes, Wrong Balls, Challenges, Upheld, Overturned, Overturn%

**Stats logic** (inferred from `umpire_call` direction):
- Batter challenges = `umpire_call='called_strike'` + challenged (disputing a strike call)
- Defense challenges = `umpire_call='ball'` + challenged (disputing a ball call)
- `missed_opportunity=TRUE AND umpire_call='called_strike'` → batter-side missed opp
- `missed_opportunity=TRUE AND umpire_call='ball'` → defense-side missed opp
- Pitcher `challenges_won` = call upheld when batter challenged OR overturned in defense's favor
- `wrong_calls_for/against` (pitcher/catcher) = `missed_opportunity=TRUE` in each direction

---

## API Endpoints (Flask)

| Route | Purpose |
|-------|---------|
| `GET /` | Single-page HTML app |
| `GET /games?from=&to=` | JSON game list (MLB API live) |
| `GET /takes?gamePk=` | JSON takes for one game (MLB API live) |
| `GET /api/stats/batters` | Season batter aggregates (PostgreSQL) |
| `GET /api/stats/pitchers` | Season pitcher aggregates (PostgreSQL) |
| `GET /api/stats/catchers` | Season catcher aggregates (PostgreSQL) |
| `GET /api/stats/umpires` | Season umpire aggregates (PostgreSQL) |

Stats routes return `503` if `DATABASE_URL` is not set. All aggregation is server-side (raw SQL with `FILTER` clauses). No date filtering yet — all rows are season-to-date.

---

## Render Deployment

- **Flask app object**: `abs_tracker.server:app` — gunicorn target
- **Port**: `server.py` reads `PORT` env var (Render-injected) when run directly; gunicorn uses `--bind 0.0.0.0:$PORT` from Procfile/render.yaml
- **Local dev**: unchanged — `python -m abs_tracker serve` still uses Flask dev server on 127.0.0.1:5000
- **Deploy**: push to Git repo connected to Render; build/start commands are in `render.yaml`

### Ingestion cron job

Scheduled via **Windows Task Scheduler** on a local PC (avoids Render cron costs).
`ingest_daily.bat` at the project root runs `python ingestion.py` and appends stdout/stderr to `ingest.log`.
Task is configured to run daily at a fixed time; `ingestion.py` ingests the previous day's Final games.

---

## MLB Stats API Endpoints

| Purpose | URL |
|---------|-----|
| Schedule | `https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD` |
| Game feed | `https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live` |
| Player | `https://statsapi.mlb.com/api/v1/people/{playerId}` |

---

## Game Feed JSON Structure (confirmed 2026-03-26)

```
liveData.plays.allPlays[]
  .about.inning / halfInning / atBatIndex
  .matchup.batter.{id, fullName}
  .matchup.pitcher.{id, fullName}
  .playEvents[]
    .isPitch                       ← filter to True
    .details.code                  ← B, C, *B, S, F, X, ...
    .details.call.{code, description}
    .details.isStrike / isBall / isInPlay  ← reflect FINAL post-challenge call
    .details.hasReview             ← True if challenged
    .count.balls / .count.strikes  ← FINAL post-challenge count
    .pitchData.coordinates.pX / pZ ← feet, catcher POV
    .pitchData.strikeZoneTop/Bottom ← stringer estimate, NOT ABS zone
    .pitchData.zone                ← Statcast zone 1–14
    .reviewDetails                 ← present ONLY on challenged pitches
      .isOverturned / .inProgress / .reviewType ("MJ")
      .challengeTeamId / .player.{id, fullName}
liveData.boxscore.officials[]      ← HP umpire lives HERE (gameData.officials is empty)
  .officialType == "Home Plate" → .official.fullName
liveData.boxscore.teams.{home,away}.players{}
  .position.abbreviation == "C" → catcher
```

### Takes (challengeable pitches)
Call codes: `B` (ball), `C` (called strike), `*B` (ball in dirt). All others are swings.

### ⚠️ Post-challenge feed state
After a challenge, the feed retroactively updates `isStrike`, `isBall`, `count`, and
`call_description` to reflect the **final** call — not the original umpire call.
To reconstruct the original call for a reversed pitch: if `is_overturned=True` and
`is_strike=True`, the original call was a **Ball** (and vice versa).

---

## ABS Zone — CRITICAL

The 2026 game feed has **no ABS zone fields** (`absZoneTop` etc. do not exist).
Zone is computed from batter height (fetched via people endpoint, cached):

```python
abs_zone_top    = height_ft * 0.535
abs_zone_bottom = height_ft * 0.27
abs_half_width  = 0.708  # ±0.708 ft (17-inch plate)
r = 1.45 / 12  # ball radius in feet (~0.1208 ft) — any part of ball touching zone = strike
in_zone = abs(pX) <= 0.708 + r and abs_zone_bottom - r <= pZ <= abs_zone_top + r
```

Height string format: `"6' 4\""` → parsed by `fetcher.parse_height_to_feet()`.

**Known discrepancy**: Formula may disagree with live ABS system by ~5-10% near zone
edges (observed: pitch our formula calls a strike was overturned as a ball). Possible
causes: coordinate offset, height measurement difference, or slightly different
coefficients. `pitchData.zone` (Statcast, 1-9 = strike) can serve as a cross-check.

---

## SVG Plot (shared between `plot` CLI and Flask web UI)

**Game list** (sidebar, web UI only): on page load, fetches all games from `OPENING_DAY`
(`2026-03-25`) through today via `/games?from=&to=`. `Preview` (not-yet-started) games are
excluded. Remaining games are sorted by date desc (most recent first). No Load button —
date and team are client-side filters applied on `change`.
- **Date input**: filters list to matching `game_date`; clearing shows all dates.
- **Team dropdown**: populated from all loaded games (`populateTeamFilter`); filters by team.
- Both filters are AND-combined in `getFilteredGames()`.
- Game rows show `game_date · detailed_status` in the subtitle.

Both `_HTML_TEMPLATE` (main.py) and `_INDEX_HTML` (server.py) use identical SVG/JS logic:

- `SCALE = 85` px/ft on both axes → square coordinate system → circles not ellipses
- SVG dimensions computed dynamically: `SW = 4*85 + 60 = 400px`, `SH = 5*85 + 56 = 481px`
- Plot range: pX ∈ [−2, 2] ft, pZ ∈ [0.5, 5.5] ft
- Dot radius: `2.9/24 * 85 ≈ 10.3px` (true baseball diameter at scale)
- **Reference zone rectangle** (dashed blue): drawn in `renderPlot()` (not `buildPlotBase()`).
  Defaults to 6'0" (`refT=6*0.535`, `refB=6*0.27`). When a single batter chip is selected
  (`activeFilter.role==='batter'`), uses that batter's `abs_zone_top`/`abs_zone_bottom` from
  their pitch data (no extra fetch needed — already in takes). Legend label (`id="zone-label"`)
  updates dynamically, e.g. `ABS zone (Aaron Judge, 6'7")`.
- **Participants filter panel** (client-side, no new API calls): rendered to the right of the
  legend; lists unique batters, pitchers, catchers, and umpires as clickable chips. Clicking
  a chip sets `activeFilter={role,name}` and re-renders only matching takes; clicking again
  clears. JS entry points: `buildParticipants(takes)`, `renderFilterPanel(participants)`,
  `getFilteredTakes(takes)`, `applyAndRender()`.
- Dot colors: green=overturned, red=upheld, yellow=missed opportunity, gray=correct/none
- Dot opacity: `challenge_outcome === 'none'` → `0.3` (faded); all others → `0.88`
- SVG z-order: takes are sorted before the draw loop (`none` first, challenged last) so
  challenge-action dots always render on top of faded correct calls
- Stroke: white outline = Called Strike, dark = Called Ball
- **Tooltip** "Challenged by:" line includes position tag — compares `challenger_name` against
  `catcher_name` → `(C)`, `pitcher_name` → `(P)`, `batter_name` → `(AB)`; omits tag if no match
- **Font**: `Verdana, Geneva, sans-serif` (body); all inputs/buttons inherit via `font-family:inherit`

### ⚠️ Raw string `\u` escape gotcha

`_INDEX_HTML` is a Python raw string (`r"""..."""`). `\uXXXX` sequences inside `<script>` tags
work fine — the browser's JS engine interprets them. But `\uXXXX` inside HTML (attributes,
element text) is rendered literally by the browser. Use HTML entities (`&#8230;` for `…`, etc.)
for any special characters that appear outside of `<script>`.

---

## Database

### PostgreSQL (primary — for web/stats)

`DATABASE_URL` must be set in `.env` locally and in Render → Settings → Environment for production.

| Table | Key columns |
|-------|-------------|
| `games` | game_pk (PK), game_date, home_team, away_team, status, ingested_at |
| `takes` | id (PK), game_pk (FK), game_date, inning, inning_half, batter_id/name, pitcher_id/name, catcher_name, umpire_name, px, pz, abs_zone_top/bottom, umpire_call, in_abs_zone, challenge_outcome, missed_opportunity |

- `umpire_call`: original umpire decision ("called_strike" / "ball"), derived from `call_code` which is NOT retroactively updated after a challenge.
- `challenge_outcome`: "successful" / "failed" / NULL (no challenge).
- `catcher_id` and `umpire_id` are nullable — current parsing only exposes names, not IDs.
- Models live in `abs_tracker/pg_models.py` (SQLAlchemy declarative, independent of Flask).

**Ingestion pipeline**: `ingestion.py` (project root)

```bash
python ingestion.py                        # init DB + ingest yesterday's games (cron target)
python ingestion.py --date 2026-03-26      # ingest a specific date
python ingestion.py --init-db              # create tables only
python ingestion.py --smoke-test           # ingest Opening Day + next day, print stats
```

**Ingested range** (as of 2026-03-28): only 2026-03-26 confirmed (Opening Day) — 11 games, 1697 takes, 14 successful challenges, 5 failed, 103 missed opportunities. Dates 2026-03-27 onward need manual backfill.

### SQLite (legacy CLI/sync)

`abs_tracker.db` — used only by the CLI sync/report commands (`python -m abs_tracker sync`).

| Table | Contents |
|-------|----------|
| `games` | game_pk, date, teams, takes_count, challenges_count, parsed_at |
| `pitches` | all take pitches with ABS zone eval + challenge fields |
| `player_heights` | batter_id → height_ft cache |

Missed opportunities are derived on-the-fly from pitches (not stored).
Transactions per game — failed parse leaves game unstored and retryable.

---

## CLI Usage

```bash
pip install -r requirements.txt

# Web UI
python -m abs_tracker serve                          # http://127.0.0.1:5000/
python -m abs_tracker serve --port 8080

# Sync / DB
python -m abs_tracker sync -v                        # all 2026 games through today
python -m abs_tracker sync --from 2026-03-26 --to 2026-04-10 -v
python -m abs_tracker sync --dry-run -v
python -m abs_tracker status
python -m abs_tracker report season
python -m abs_tracker report date 2026-03-26
python -m abs_tracker report range 2026-03-26 2026-03-30
python -m abs_tracker report game 823812
python -m abs_tracker report season --output csv > season.csv
python -m abs_tracker sync --db /path/to/data.db -v  # custom DB path

# Live fetch (no DB)
python -m abs_tracker games 2026-03-26               # JSON game list
python -m abs_tracker takes 823812                   # JSON takes
python -m abs_tracker plot 823812                    # writes abs_plot_823812.html
python -m abs_tracker plot 823812 --output zone.html
python -m abs_tracker smoke 823812                   # dev/debug
python -m abs_tracker game 823812 --output csv
python -m abs_tracker date 2026-03-26 -v
python -m abs_tracker range 2026-03-26 2026-03-30
```

---

## Known Limitations

1. **Umpire per-pitch**: HP umpire attached at game level (same name on all takes).
   Per-game umpire stats would require storing umpire_name in the `games` table.

2. **Challenge initiator side**: Infer from `challengeTeamId` vs batter's team —
   no explicit "batter challenged" vs "defense challenged" field.

3. **In-progress games**: Only `abstractGameState == "Final"` games are synced.

4. **Ball-in-dirt (`*B`)**: Classified identically to `B`; can never trigger
   "batter should challenge" but theoretically challengeable by defense.

5. **Formula vs ABS discrepancy**: ~5-10% false positives near zone edges (see ABS Zone section).
