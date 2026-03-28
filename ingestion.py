"""
PostgreSQL ingestion pipeline for MLB ABS challenge data.

Usage
-----
# Initialize tables and run daily update (yesterday's games):
    python ingestion.py

# Smoke test — ingest specific dates and print summary stats:
    python ingestion.py --smoke-test

Environment
-----------
Requires DATABASE_URL in the environment (or in a .env file at the project root).
Locally: copy .env.example to .env and fill in the value.
On Render: set DATABASE_URL in Settings → Environment.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from abs_tracker.fetcher import fetch_game_feed, fetch_games_for_date
from abs_tracker.parser import extract_catchers, extract_hp_umpire, parse_game
from abs_tracker.pg_models import Base, Game, Take

_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL environment variable is not set.")

engine = create_engine(_DATABASE_URL)


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they don't already exist, and run any column migrations."""
    Base.metadata.create_all(engine)
    # Add is_defense_challenge column if it was added after initial schema creation
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE takes ADD COLUMN IF NOT EXISTS is_defense_challenge BOOLEAN"
        ))
        conn.commit()
    print("Database tables ready.")


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------

def ingest_game(game_pk: int, force: bool = False) -> int:
    """
    Fetch, parse, and store one game in the PostgreSQL database.

    Returns the number of takes inserted, or 0 if the game was already stored.
    If force=True, deletes any existing record (cascades to takes) and re-ingests.
    Raises on unexpected errors (caller should catch and continue).
    """
    with Session(engine) as session:
        existing = session.get(Game, game_pk)
        if existing:
            if force:
                session.delete(existing)
                session.flush()
            else:
                print(f"  game {game_pk}: already in DB, skipping")
                return 0

        feed = fetch_game_feed(game_pk)
        pitches, missed_ops = parse_game(feed)
        hp_umpire = extract_hp_umpire(feed)
        catchers = extract_catchers(feed)

        game_data = feed.get("gameData", {})
        teams_data = game_data.get("teams", {})
        game_date_str = game_data.get("datetime", {}).get("officialDate", "")
        home_team = teams_data.get("home", {}).get("name", "Unknown")
        away_team = teams_data.get("away", {}).get("name", "Unknown")
        home_team_id = teams_data.get("home", {}).get("id")
        away_team_id = teams_data.get("away", {}).get("id")
        status = game_data.get("status", {}).get("abstractGameState", "Unknown")

        game_row = Game(
            game_pk=game_pk,
            game_date=date.fromisoformat(game_date_str),
            home_team=home_team,
            away_team=away_team,
            status=status,
            ingested_at=datetime.now(timezone.utc),
        )

        missed_keys = {
            (mo.pitch.at_bat_index, mo.pitch.pitch_number) for mo in missed_ops
        }

        take_rows = []
        for p in pitches:
            catcher_side = "home" if p.half_inning == "top" else "away"
            catcher_name = catchers.get(catcher_side)

            if p.has_review:
                challenge_outcome = "successful" if p.is_overturned else "failed"
                # Determine whether the challenging team was the defense (pitcher/catcher side).
                # When the top half is being played, the home team defends; bottom → away defends.
                if p.challenge_team_id and home_team_id and away_team_id:
                    defending_team_id = home_team_id if p.half_inning == "top" else away_team_id
                    is_defense_challenge = (p.challenge_team_id == defending_team_id)
                else:
                    is_defense_challenge = None
            else:
                challenge_outcome = None
                is_defense_challenge = None

            # Reconstruct the original umpire call. Despite documentation suggesting
            # otherwise, details.code (call_code) IS retroactively updated to the
            # final post-challenge result. For overturned pitches, invert the final
            # call: if the final call is a strike, the umpire originally called a ball.
            if p.is_overturned:
                umpire_call = "ball" if p.is_strike else "called_strike"
            else:
                umpire_call = "called_strike" if p.call_code == "C" else "ball"

            is_missed = (p.at_bat_index, p.pitch_number) in missed_keys

            take_rows.append(Take(
                game_pk=game_pk,
                game_date=date.fromisoformat(game_date_str),
                inning=p.inning,
                inning_half=p.half_inning,
                at_bat_index=p.at_bat_index,
                pitch_number=p.pitch_number,
                batter_id=p.batter_id,
                batter_name=p.batter_name,
                pitcher_id=p.pitcher_id,
                pitcher_name=p.pitcher_name,
                catcher_id=None,        # not available from current parsing
                catcher_name=catcher_name,
                umpire_id=None,         # not available from current parsing
                umpire_name=hp_umpire,
                px=p.px,
                pz=p.pz,
                abs_zone_top=p.abs_zone_top,
                abs_zone_bottom=p.abs_zone_bottom,
                umpire_call=umpire_call,
                in_abs_zone=p.in_abs_zone,
                challenge_outcome=challenge_outcome,
                is_defense_challenge=is_defense_challenge,
                missed_opportunity=is_missed,
            ))

        session.add(game_row)
        session.add_all(take_rows)
        session.commit()

    print(f"  + game {game_pk} ({away_team} @ {home_team}): {len(take_rows)} takes inserted")
    return len(take_rows)


def ingest_recent_games(date_str: str, force: bool = False) -> dict:
    """
    Ingest all Final games for a given date (YYYY-MM-DD).

    Skips games already in the database unless force=True, which deletes and
    re-ingests existing records. Logs and continues on per-game errors.
    Returns a summary dict.
    """
    games = fetch_games_for_date(date_str)
    final_games = [g for g in games if g.get("status") == "Final"]

    if force:
        new_games = final_games
    else:
        with Session(engine) as session:
            stored_pks = {row[0] for row in session.execute(select(Game.game_pk))}
        new_games = [g for g in final_games if g["gamePk"] not in stored_pks]

    print(
        f"{date_str}: {len(final_games)} Final game(s), "
        f"{len(new_games)} {'to reingest' if force else 'new to ingest'}"
    )

    total_takes = 0
    errors = 0
    for game_meta in new_games:
        gk = game_meta["gamePk"]
        try:
            total_takes += ingest_game(gk, force=force)
        except Exception as exc:
            errors += 1
            print(f"  [ERROR] game {gk}: {exc}", file=sys.stderr)

    print(
        f"  done: {len(new_games)} game(s) processed, "
        f"{total_takes} takes inserted, {errors} error(s)\n"
    )
    return {"games_processed": len(new_games), "takes_inserted": total_takes, "errors": errors}


def daily_update() -> None:
    """Ingest yesterday's Final games. Designed for cron job use."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    print(f"Daily update for {yesterday}")
    ingest_recent_games(yesterday)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def smoke_test() -> None:
    """
    Ingest Opening Day (2026-03-26) and the following day, then print
    aggregate stats to verify the pipeline is working.
    """
    print("=== Smoke test: initialising DB ===")
    init_db()

    for d in ("2026-03-26", "2026-03-27"):
        ingest_recent_games(d)

    print("=== Query summary ===")
    with Session(engine) as session:
        total_takes = session.execute(
            select(func.count()).select_from(Take)
        ).scalar_one()

        missed = session.execute(
            select(func.count()).select_from(Take).where(Take.missed_opportunity == True)
        ).scalar_one()

        successful = session.execute(
            select(func.count()).select_from(Take).where(Take.challenge_outcome == "successful")
        ).scalar_one()

        failed = session.execute(
            select(func.count()).select_from(Take).where(Take.challenge_outcome == "failed")
        ).scalar_one()

        games_stored = session.execute(
            select(func.count()).select_from(Game)
        ).scalar_one()

    print(f"  Games stored       : {games_stored}")
    print(f"  Total takes        : {total_takes}")
    print(f"  Missed opportunities: {missed}")
    print(f"  Successful challenges: {successful}")
    print(f"  Failed challenges  : {failed}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ABS ingestion pipeline")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Ingest Opening Day + next day and print aggregate stats",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Create tables and exit",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Ingest a specific date instead of yesterday",
    )
    parser.add_argument(
        "--reingest-date",
        metavar="YYYY-MM-DD",
        help="Delete and re-ingest all Final games for a date (use after schema changes)",
    )
    args = parser.parse_args()

    if args.smoke_test:
        smoke_test()
    elif args.init_db:
        init_db()
    elif args.date:
        init_db()
        ingest_recent_games(args.date)
    elif args.reingest_date:
        init_db()
        ingest_recent_games(args.reingest_date, force=True)
    else:
        init_db()
        daily_update()
