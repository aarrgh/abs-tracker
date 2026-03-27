"""
Season sync: fetch all 2026 MLB games not yet in the database.

Run this daily to keep the database current. The process is fully idempotent —
games already stored are skipped based on game_pk.

Flow per run
------------
1. Open DB, load persistent player heights into the in-memory fetcher cache
   (avoids re-hitting the people API for already-seen batters).
2. Walk every date from OPENING_DAY_2026 through today.
3. For each date, fetch the schedule and filter to Final games not in the DB.
4. Fetch + parse + store each missing game.
5. After all dates, flush any newly fetched player heights back to the DB.

Error handling: a single-game failure is logged and skipped; the game will be
retried on the next run (it won't appear in get_stored_game_pks until stored).
"""

import sys
import time
from datetime import date, timedelta

import requests

from . import fetcher as _fetcher
from .db import (
    db_summary,
    get_stored_game_pks,
    init_db,
    load_stored_heights,
    save_heights,
    store_game,
)
from .fetcher import fetch_game_feed, fetch_schedule
from .parser import parse_game

OPENING_DAY_2026 = "2026-03-25"

# Seconds to wait between game feed requests (be polite to the public API)
_INTER_GAME_DELAY = 0.3


def sync_season(
    db_path: str,
    start_date: str = OPENING_DAY_2026,
    end_date: str | None = None,
    verbose: bool = True,
    dry_run: bool = False,
) -> dict:
    """
    Sync all Final games from start_date through end_date (default: today).

    Returns a summary dict with counts of dates checked, games added, errors.
    """
    if end_date is None:
        end_date = date.today().isoformat()

    conn = init_db(db_path)

    # Pre-load persistent height cache so we don't re-call the people API
    # for batters already seen in previous runs.
    stored_heights = load_stored_heights(conn)
    _fetcher._height_cache.update(stored_heights)
    if verbose and stored_heights:
        print(f"Loaded {len(stored_heights)} cached player heights from DB.")

    stored_pks = get_stored_game_pks(conn)
    if verbose:
        print(f"Database already contains {len(stored_pks)} game(s).")
        print(f"Syncing {start_date} -> {end_date} ...\n")

    dates = _date_range(start_date, end_date)
    total_added = 0
    total_errors = 0
    dates_with_new = 0
    dates_already_done = 0

    for game_date in dates:
        try:
            games = fetch_schedule(game_date)
        except Exception as exc:
            print(f"  [ERROR] Could not fetch schedule for {game_date}: {exc}", file=sys.stderr)
            continue

        final_games = [
            g for g in games
            if g.get("status", {}).get("abstractGameState") == "Final"
        ]
        missing = [g for g in final_games if g["gamePk"] not in stored_pks]

        if not missing:
            if verbose and final_games:
                print(f"{game_date}: {len(final_games):2d} Final  (all stored, skipping)")
            dates_already_done += 1
            continue

        print(f"{game_date}: {len(final_games):2d} Final  {len(missing)} new to fetch")
        dates_with_new += 1

        for game_meta in missing:
            gk = game_meta["gamePk"]
            away = game_meta.get("teams", {}).get("away", {}).get("team", {}).get("name", "?")
            home = game_meta.get("teams", {}).get("home", {}).get("team", {}).get("name", "?")
            label = f"{away} @ {home}"

            if dry_run:
                print(f"  [DRY RUN] would fetch game {gk} ({label})")
                continue

            t0 = time.monotonic()
            try:
                feed = fetch_game_feed(gk)
                pitches, _ = parse_game(feed)
                store_game(conn, game_meta, pitches)
                stored_pks.add(gk)
                elapsed = time.monotonic() - t0
                challenges = sum(1 for p in pitches if p.has_review)
                total_added += 1
                if verbose:
                    print(
                        f"  + game {gk} ({label}): "
                        f"{len(pitches)} takes, {challenges} challenges  "
                        f"[{elapsed:.1f}s]"
                    )
            except requests.HTTPError as exc:
                total_errors += 1
                print(f"  [ERROR] game {gk} ({label}): HTTP {exc.response.status_code}", file=sys.stderr)
            except Exception as exc:
                total_errors += 1
                print(f"  [ERROR] game {gk} ({label}): {exc}", file=sys.stderr)

            time.sleep(_INTER_GAME_DELAY)

    # Flush any newly fetched heights back to DB for future runs
    if not dry_run:
        save_heights(conn, _fetcher._height_cache)

    conn.close()

    summary = {
        "dates_checked": len(dates),
        "dates_with_new_games": dates_with_new,
        "dates_already_complete": dates_already_done,
        "games_added": total_added,
        "errors": total_errors,
    }

    print()
    if dry_run:
        print("Dry run complete — no data written.")
    else:
        print(
            f"Sync complete: {total_added} game(s) added, "
            f"{total_errors} error(s), "
            f"{len(dates)} date(s) checked."
        )

    return summary


def _date_range(start: str, end: str) -> list[str]:
    dates = []
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while current <= last:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates
