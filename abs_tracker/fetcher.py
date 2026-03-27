"""
MLB Stats API client for ABS challenge tracking.

Endpoints used:
  Schedule:  https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD
  Game feed: https://statsapi.mlb.com/api/v1.1/game/{gamePk}/feed/live
  Player:    https://statsapi.mlb.com/api/v1/people/{playerId}
"""

import re
import time
from datetime import date, timedelta
from typing import Optional

import requests

_BASE = "https://statsapi.mlb.com/api/v1"
_BASE_V11 = "https://statsapi.mlb.com/api/v1.1"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "mlb-abs-tracker/1.0"})

# In-memory height cache to avoid redundant API calls during a run
_height_cache: dict[int, Optional[float]] = {}


def _get(url: str, params: dict = None) -> dict:
    resp = _SESSION.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_schedule(game_date: str) -> list[dict]:
    """
    Fetch all games for a given date (YYYY-MM-DD).
    Returns raw game dicts from the schedule API.
    """
    data = _get(f"{_BASE}/schedule", params={"sportId": 1, "date": game_date})
    games = []
    for date_entry in data.get("dates", []):
        games.extend(date_entry.get("games", []))
    return games


def fetch_game_feed(game_pk: int) -> dict:
    """Fetch full live/final game feed for a gamePk."""
    return _get(f"{_BASE_V11}/game/{game_pk}/feed/live")


def fetch_games_for_date(game_date: str) -> list[dict]:
    """
    Return structured game info for every game on a given date (YYYY-MM-DD).

    Each dict contains:
      gamePk, game_date, home_team_id, home_team_name,
      away_team_id, away_team_name, status, detailed_status
    """
    return fetch_games_for_date_range(game_date, game_date)


def fetch_games_for_date_range(start_date: str, end_date: str) -> list[dict]:
    """
    Return structured game info for every game in an inclusive date range.
    Uses a single schedule API call with startDate/endDate.

    Each dict contains:
      gamePk, game_date, home_team_id, home_team_name,
      away_team_id, away_team_name, status, detailed_status
    """
    data = _get(f"{_BASE}/schedule",
                params={"sportId": 1, "startDate": start_date, "endDate": end_date})
    games = []
    for date_entry in data.get("dates", []):
        game_date = date_entry.get("date", "")
        for g in date_entry.get("games", []):
            status = g.get("status", {})
            teams = g.get("teams", {})
            home = teams.get("home", {}).get("team", {})
            away = teams.get("away", {}).get("team", {})
            games.append({
                "gamePk": g["gamePk"],
                "game_date": game_date,
                "home_team_id": home.get("id"),
                "home_team_name": home.get("name"),
                "away_team_id": away.get("id"),
                "away_team_name": away.get("name"),
                "status": status.get("abstractGameState"),
                "detailed_status": status.get("detailedState"),
            })
    return games


def fetch_player(player_id: int) -> dict:
    """Fetch player profile from the people endpoint. Returns {} on failure."""
    try:
        data = _get(f"{_BASE}/people/{player_id}")
        people = data.get("people", [])
        return people[0] if people else {}
    except requests.HTTPError:
        return {}


def parse_height_to_feet(height_str: str) -> Optional[float]:
    """
    Parse MLB height string (e.g. "6' 4\"") to decimal feet.
    Returns None if string is missing or unparseable.

    Examples:
      "6' 4\""  → 6.333...
      "5' 11\"" → 5.917...
    """
    if not height_str:
        return None
    match = re.match(r"(\d+)'\s*(\d+)", height_str)
    if match:
        return int(match.group(1)) + int(match.group(2)) / 12.0
    return None


def get_batter_height_ft(player_id: int) -> Optional[float]:
    """
    Return batter height in decimal feet.
    Fetches from the people endpoint on first call, then caches.
    Returns None if height is unavailable or unparseable.
    """
    if player_id in _height_cache:
        return _height_cache[player_id]

    player = fetch_player(player_id)
    height_ft = parse_height_to_feet(player.get("height", ""))
    _height_cache[player_id] = height_ft
    return height_ft


def seed_height_cache(heights: dict[int, Optional[float]]) -> None:
    """Bulk-load player heights into the in-memory cache (e.g. from DB)."""
    _height_cache.update(heights)


def dump_height_cache() -> dict[int, Optional[float]]:
    """Return the full in-memory height cache (e.g. to persist to DB)."""
    return dict(_height_cache)


def fetch_games_for_range(start_date: str, end_date: str) -> list[dict]:
    """
    Fetch all game dicts across an inclusive date range.
    Adds a small delay between dates to avoid hammering the API.
    """
    games = []
    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    while current <= end:
        games.extend(fetch_schedule(current.isoformat()))
        current += timedelta(days=1)
        if current <= end:
            time.sleep(0.1)
    return games
