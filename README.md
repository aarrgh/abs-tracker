# MLB ABS Tracker

Tracks MLB Automatic Ball-Strike (ABS) system challenges in the 2026 season. Fetches live game data from the MLB Stats API, evaluates pitches against the ABS zone, identifies missed challenge opportunities, and visualizes results.

**Live app**: https://abs-tracker.onrender.com

## Features

- Parses every called pitch from MLB game feeds
- Computes ABS zone based on batter height (fetched and cached from MLB API)
- Identifies challenged pitches and whether they were overturned
- Flags missed opportunities (pitches outside the zone that weren't challenged)
- Interactive SVG pitch plot with filters by batter, pitcher, catcher, and umpire
- SQLite-backed sync for the full 2026 season
- Flask web UI with game browser, date/team filters, and live pitch plots

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Web UI (http://127.0.0.1:5000)
python -m abs_tracker serve

# Sync all 2026 games into local DB
python -m abs_tracker sync -v

# Reports
python -m abs_tracker report season
python -m abs_tracker report date 2026-03-26
python -m abs_tracker report game 823812

# Live fetch (no DB)
python -m abs_tracker plot 823812        # writes abs_plot_823812.html
python -m abs_tracker takes 823812       # JSON takes for a game
python -m abs_tracker games 2026-03-26   # JSON game list for a date
```

## ABS Zone Formula

```
abs_zone_top    = height_ft * 0.535
abs_zone_bottom = height_ft * 0.27
abs_half_width  = 0.708 ft  (17-inch plate)
ball_radius     = 1.45 / 12 ft
```

A pitch is in the zone if any part of the ball touches the zone boundary.

## Deployment

Deployed on Render via `render.yaml`. Build and start commands are pre-configured — connecting the GitHub repo in the Render dashboard is sufficient to deploy.

- **Build**: `pip install -r requirements.txt`
- **Start**: `gunicorn abs_tracker.server:app --bind 0.0.0.0:$PORT`
- **Python**: 3.11.0

---

[![GitHub](https://img.shields.io/badge/GitHub-abs--tracker-181717?logo=github)](https://github.com/aarrgh/abs-tracker)

*This tool is an independent fan project and is not affiliated with or endorsed by Major League Baseball. All team names, player names, and statistical data are the property of MLB and its member clubs.*
