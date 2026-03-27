"""
SQLite persistence layer for MLB ABS tracker.

Schema
------
  games          — one row per completed game that has been parsed
  pitches        — all take pitches (called balls + called strikes) per game
  player_heights — persistent cache of batter height lookups from the people API

Booleans are stored as INTEGER (0/1); Optional booleans use NULL for None.
Heights are stored in the player_heights table so re-runs don't re-hit the API
for players already seen.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .models import Pitch


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS games (
    game_pk          INTEGER PRIMARY KEY,
    game_date        TEXT    NOT NULL,
    away_team_id     INTEGER,
    away_team_name   TEXT,
    home_team_id     INTEGER,
    home_team_name   TEXT,
    takes_count      INTEGER,
    challenges_count INTEGER,
    parsed_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS pitches (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    game_pk              INTEGER NOT NULL REFERENCES games(game_pk),
    game_date            TEXT,
    at_bat_index         INTEGER,
    pitch_number         INTEGER,
    play_id              TEXT,
    inning               INTEGER,
    half_inning          TEXT,
    batter_id            INTEGER,
    batter_name          TEXT,
    pitcher_id           INTEGER,
    pitcher_name         TEXT,
    call_code            TEXT,
    call_description     TEXT,
    is_strike            INTEGER,
    is_ball              INTEGER,
    is_in_play           INTEGER,
    is_take              INTEGER,
    px                   REAL,
    pz                   REAL,
    stringer_zone_top    REAL,
    stringer_zone_bottom REAL,
    abs_zone_top         REAL,
    abs_zone_bottom      REAL,
    batter_height_ft     REAL,
    in_abs_zone          INTEGER,
    has_review           INTEGER,
    is_overturned        INTEGER,
    challenge_team_id    INTEGER,
    challenger_id        INTEGER,
    challenger_name      TEXT,
    review_type          TEXT,
    pitch_type           TEXT,
    pitch_type_code      TEXT,
    start_speed          REAL,
    statcast_zone        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_pitches_game_pk    ON pitches(game_pk);
CREATE INDEX IF NOT EXISTS idx_pitches_game_date  ON pitches(game_date);
CREATE INDEX IF NOT EXISTS idx_pitches_batter_id  ON pitches(batter_id);
CREATE INDEX IF NOT EXISTS idx_pitches_pitcher_id ON pitches(pitcher_id);
CREATE INDEX IF NOT EXISTS idx_pitches_has_review ON pitches(has_review);

CREATE TABLE IF NOT EXISTS player_heights (
    player_id  INTEGER PRIMARY KEY,
    height_ft  REAL,
    fetched_at TEXT NOT NULL
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    """
    Open (or create) the SQLite database at db_path and apply the schema.
    Returns an open Connection with row_factory set.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_DDL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Game-level operations
# ---------------------------------------------------------------------------

def get_stored_game_pks(conn: sqlite3.Connection) -> set[int]:
    """Return the set of all game_pks already stored in the database."""
    rows = conn.execute("SELECT game_pk FROM games").fetchall()
    return {r["game_pk"] for r in rows}


def store_game(
    conn: sqlite3.Connection,
    game_meta: dict,
    pitches: list[Pitch],
) -> None:
    """
    Persist a game and all its take pitches in a single transaction.
    If anything raises, the transaction rolls back and game_pk is not stored,
    so the next sync run will retry it.

    game_meta is the raw dict from the schedule API:
      {gamePk, teams: {away: {team: {id, name}}, home: ...}, ...}
    """
    teams = game_meta.get("teams", {})
    away = teams.get("away", {}).get("team", {})
    home = teams.get("home", {}).get("team", {})
    game_pk = game_meta["gamePk"]
    game_date = game_meta.get("officialDate") or game_meta.get("gameDate", "")[:10]
    parsed_at = datetime.now(timezone.utc).isoformat()

    challenges = sum(1 for p in pitches if p.has_review)

    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO games
              (game_pk, game_date, away_team_id, away_team_name,
               home_team_id, home_team_name, takes_count, challenges_count, parsed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                game_pk, game_date,
                away.get("id"), away.get("name"),
                home.get("id"), home.get("name"),
                len(pitches), challenges, parsed_at,
            ),
        )

        conn.executemany(
            """
            INSERT INTO pitches
              (game_pk, game_date, at_bat_index, pitch_number, play_id,
               inning, half_inning,
               batter_id, batter_name, pitcher_id, pitcher_name,
               call_code, call_description,
               is_strike, is_ball, is_in_play, is_take,
               px, pz,
               stringer_zone_top, stringer_zone_bottom,
               abs_zone_top, abs_zone_bottom, batter_height_ft, in_abs_zone,
               has_review, is_overturned,
               challenge_team_id, challenger_id, challenger_name, review_type,
               pitch_type, pitch_type_code, start_speed, statcast_zone)
            VALUES
              (?,?,?,?,?, ?,?, ?,?,?,?, ?,?, ?,?,?,?, ?,?, ?,?, ?,?,?,?, ?,?, ?,?,?,?, ?,?,?,?)
            """,
            [_pitch_to_row(p) for p in pitches],
        )


def _pitch_to_row(p: Pitch) -> tuple:
    def b(v: Optional[bool]) -> Optional[int]:
        return None if v is None else int(v)

    return (
        p.game_pk, p.game_date, p.at_bat_index, p.pitch_number, p.play_id,
        p.inning, p.half_inning,
        p.batter_id, p.batter_name, p.pitcher_id, p.pitcher_name,
        p.call_code, p.call_description,
        b(p.is_strike), b(p.is_ball), b(p.is_in_play), b(p.is_take),
        p.px, p.pz,
        p.stringer_zone_top, p.stringer_zone_bottom,
        p.abs_zone_top, p.abs_zone_bottom, p.batter_height_ft, b(p.in_abs_zone),
        b(p.has_review), b(p.is_overturned),
        p.challenge_team_id, p.challenger_id, p.challenger_name, p.review_type,
        p.pitch_type, p.pitch_type_code, p.start_speed, p.statcast_zone,
    )


# ---------------------------------------------------------------------------
# Player height cache (persistent across runs)
# ---------------------------------------------------------------------------

def load_stored_heights(conn: sqlite3.Connection) -> dict[int, Optional[float]]:
    """Return all player_id → height_ft entries from the DB."""
    rows = conn.execute("SELECT player_id, height_ft FROM player_heights").fetchall()
    return {r["player_id"]: r["height_ft"] for r in rows}


def save_heights(conn: sqlite3.Connection, heights: dict[int, Optional[float]]) -> None:
    """
    Upsert player heights into the persistent cache table.
    Pass the full in-memory height dict; only new entries are inserted.
    """
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO player_heights (player_id, height_ft, fetched_at)
            VALUES (?, ?, ?)
            """,
            [(pid, ht, now) for pid, ht in heights.items()],
        )


# ---------------------------------------------------------------------------
# Query / load
# ---------------------------------------------------------------------------

def load_pitches(
    conn: sqlite3.Connection,
    *,
    game_pk: Optional[int] = None,
    game_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[Pitch]:
    """
    Load stored take pitches as Pitch objects, with optional filters.
    At most one of (game_pk, game_date, start_date/end_date) should be set.
    """
    where_clauses = []
    params: list = []

    if game_pk is not None:
        where_clauses.append("game_pk = ?")
        params.append(game_pk)
    if game_date is not None:
        where_clauses.append("game_date = ?")
        params.append(game_date)
    if start_date is not None:
        where_clauses.append("game_date >= ?")
        params.append(start_date)
    if end_date is not None:
        where_clauses.append("game_date <= ?")
        params.append(end_date)

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    rows = conn.execute(f"SELECT * FROM pitches {where} ORDER BY game_pk, at_bat_index, pitch_number", params).fetchall()
    return [_row_to_pitch(r) for r in rows]


def _row_to_pitch(row: sqlite3.Row) -> Pitch:
    def ob(v) -> Optional[bool]:
        return None if v is None else bool(v)

    return Pitch(
        game_pk=row["game_pk"],
        game_date=row["game_date"] or "",
        at_bat_index=row["at_bat_index"] or 0,
        pitch_number=row["pitch_number"] or 0,
        play_id=row["play_id"],
        inning=row["inning"] or 0,
        half_inning=row["half_inning"] or "",
        batter_id=row["batter_id"] or 0,
        batter_name=row["batter_name"] or "Unknown",
        pitcher_id=row["pitcher_id"] or 0,
        pitcher_name=row["pitcher_name"] or "Unknown",
        call_code=row["call_code"] or "",
        call_description=row["call_description"] or "",
        is_strike=bool(row["is_strike"]),
        is_ball=bool(row["is_ball"]),
        is_in_play=bool(row["is_in_play"]),
        is_take=bool(row["is_take"]),
        px=row["px"],
        pz=row["pz"],
        stringer_zone_top=row["stringer_zone_top"],
        stringer_zone_bottom=row["stringer_zone_bottom"],
        abs_zone_top=row["abs_zone_top"],
        abs_zone_bottom=row["abs_zone_bottom"],
        batter_height_ft=row["batter_height_ft"],
        in_abs_zone=ob(row["in_abs_zone"]),
        has_review=bool(row["has_review"]),
        is_overturned=ob(row["is_overturned"]),
        challenge_team_id=row["challenge_team_id"],
        challenger_id=row["challenger_id"],
        challenger_name=row["challenger_name"],
        review_type=row["review_type"],
        pitch_type=row["pitch_type"],
        pitch_type_code=row["pitch_type_code"],
        start_speed=row["start_speed"],
        statcast_zone=row["statcast_zone"],
    )


def db_summary(conn: sqlite3.Connection) -> dict:
    """Return high-level counts for a status display."""
    games = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    pitches = conn.execute("SELECT COUNT(*) FROM pitches").fetchone()[0]
    challenges = conn.execute("SELECT COUNT(*) FROM pitches WHERE has_review = 1").fetchone()[0]
    heights = conn.execute("SELECT COUNT(*) FROM player_heights").fetchone()[0]
    date_range = conn.execute(
        "SELECT MIN(game_date), MAX(game_date) FROM games"
    ).fetchone()
    return {
        "games": games,
        "pitches": pitches,
        "challenges": challenges,
        "player_heights_cached": heights,
        "earliest_date": date_range[0],
        "latest_date": date_range[1],
    }
