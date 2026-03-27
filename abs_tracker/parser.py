"""
Parse MLB game feed JSON into Pitch and MissedOpportunity objects.

ABS Zone computation
--------------------
The 2026 game feed does NOT include ABS-specific zone fields (absZoneTop,
absZoneBottom, etc. do not exist as of the 2026 season opener). Zone
boundaries are computed from batter height fetched via the people endpoint:

  top    = height_ft * 0.535
  bottom = height_ft * 0.27
  width  = ±0.708 ft from center (17-inch plate)

⚠️  pitchData.strikeZoneTop / strikeZoneBottom are stringer-estimated values
    set by a human operator mid-game. They are captured for reference but
    are NOT used for any ABS zone evaluation.

Challenge data (confirmed from 2026 live games)
-----------------------------------------------
  details.hasReview            — bool, True if pitch was challenged
  reviewDetails.isOverturned   — bool, whether call was reversed
  reviewDetails.reviewType     — "MJ" (manager's challenge)
  reviewDetails.challengeTeamId — teamId of challenging side
  reviewDetails.player         — {id, fullName} of player who challenged
"""

from typing import Optional

from .fetcher import get_batter_height_ft
from .models import ABSZone, MissedOpportunity, Pitch

# Call codes that represent a "take" (no swing involved)
# B  = Ball
# C  = Called Strike
# *B = Ball in dirt (still a ball, no swing)
TAKE_CALL_CODES = frozenset(["B", "C", "*B"])

ABS_HALF_WIDTH = 0.708  # ±0.708 ft (17-inch plate, catcher's POV)


def compute_abs_zone(height_ft: float) -> ABSZone:
    """
    Compute ABS strike zone from batter height in decimal feet.
    Formula per MLB ABS specification.
    """
    return ABSZone(
        top=height_ft * 0.535,
        bottom=height_ft * 0.27,
        half_width=ABS_HALF_WIDTH,
    )


def _build_pitch(
    *,
    game_pk: int,
    game_date: str,
    at_bat_index: int,
    inning: int,
    half_inning: str,
    batter_id: int,
    batter_name: str,
    pitcher_id: int,
    pitcher_name: str,
    event: dict,
    abs_zone: Optional[ABSZone],
    batter_height_ft: Optional[float],
    count_balls: Optional[int] = None,
    count_strikes: Optional[int] = None,
) -> Pitch:
    """Construct a Pitch dataclass from a raw playEvent dict."""
    details = event.get("details", {})
    pitch_data = event.get("pitchData", {})
    coords = pitch_data.get("coordinates", {})
    review = event.get("reviewDetails") or {}

    call = details.get("call", {})
    call_code = details.get("code") or call.get("code", "")
    call_description = call.get("description") or details.get("description", "")
    is_strike = bool(details.get("isStrike", False))
    is_ball = bool(details.get("isBall", False))
    is_in_play = bool(details.get("isInPlay", False))
    has_review = bool(details.get("hasReview", False))
    is_take = call_code in TAKE_CALL_CODES

    px: Optional[float] = coords.get("pX")
    pz: Optional[float] = coords.get("pZ")

    in_abs_zone: Optional[bool] = None
    if abs_zone is not None and px is not None and pz is not None:
        in_abs_zone = abs_zone.contains(px, pz)

    pitch_type_info = details.get("type") or {}

    return Pitch(
        game_pk=game_pk,
        game_date=game_date,
        at_bat_index=at_bat_index,
        pitch_number=event.get("pitchNumber", 0),
        play_id=event.get("playId"),
        inning=inning,
        half_inning=half_inning,
        batter_id=batter_id,
        batter_name=batter_name,
        pitcher_id=pitcher_id,
        pitcher_name=pitcher_name,
        call_code=call_code,
        call_description=call_description,
        is_strike=is_strike,
        is_ball=is_ball,
        is_in_play=is_in_play,
        is_take=is_take,
        px=px,
        pz=pz,
        stringer_zone_top=pitch_data.get("strikeZoneTop"),
        stringer_zone_bottom=pitch_data.get("strikeZoneBottom"),
        abs_zone_top=abs_zone.top if abs_zone else None,
        abs_zone_bottom=abs_zone.bottom if abs_zone else None,
        batter_height_ft=batter_height_ft,
        in_abs_zone=in_abs_zone,
        has_review=has_review,
        is_overturned=review.get("isOverturned"),
        challenge_team_id=review.get("challengeTeamId"),
        challenger_id=(review.get("player") or {}).get("id"),
        challenger_name=(review.get("player") or {}).get("fullName"),
        review_type=review.get("reviewType"),
        pitch_type=pitch_type_info.get("description"),
        pitch_type_code=pitch_type_info.get("code"),
        start_speed=pitch_data.get("startSpeed"),
        statcast_zone=pitch_data.get("zone"),
        count_balls=count_balls,
        count_strikes=count_strikes,
    )


def _classify_missed_opportunity(pitch: Pitch) -> Optional[MissedOpportunity]:
    """
    Return a MissedOpportunity if this non-challenged take was a missed challenge.

    Missed opportunity conditions:
      - Called Strike AND pitch is outside ABS zone → batter should have challenged
      - Called Ball AND pitch is inside ABS zone   → defense should have challenged
    """
    if pitch.has_review or pitch.in_abs_zone is None:
        return None

    if pitch.is_strike and not pitch.in_abs_zone:
        return MissedOpportunity(
            pitch=pitch,
            opportunity_type="batter_should_challenge",
            umpire_call=pitch.call_description,
            abs_verdict="ball",
            px=pitch.px,
            pz=pitch.pz,
        )
    if pitch.is_ball and pitch.in_abs_zone:
        return MissedOpportunity(
            pitch=pitch,
            opportunity_type="defense_should_challenge",
            umpire_call=pitch.call_description,
            abs_verdict="strike",
            px=pitch.px,
            pz=pitch.pz,
        )
    return None


def extract_hp_umpire(game_feed: dict) -> Optional[str]:
    """Return the home plate umpire's full name, or None if not found."""
    # Officials live in liveData.boxscore.officials (gameData.officials is empty in 2026 feeds)
    officials = (
        game_feed.get("liveData", {})
        .get("boxscore", {})
        .get("officials", [])
    )
    for official in officials:
        if official.get("officialType") == "Home Plate":
            return official.get("official", {}).get("fullName")
    return None


def extract_catchers(game_feed: dict) -> dict:
    """
    Return {"home": name_or_None, "away": name_or_None} for the catcher on each
    side, sourced from liveData.boxscore.teams.*.players.

    Only the first player with position abbreviation "C" on each side is returned.
    This will be the starting catcher; mid-game substitutes may not be reflected.
    """
    result: dict = {"home": None, "away": None}
    boxscore_teams = (
        game_feed.get("liveData", {})
        .get("boxscore", {})
        .get("teams", {})
    )
    for side in ("home", "away"):
        players = boxscore_teams.get(side, {}).get("players", {})
        for player_info in players.values():
            if player_info.get("position", {}).get("abbreviation") == "C":
                result[side] = player_info.get("person", {}).get("fullName")
                break
    return result


def derive_missed_ops(pitches: list[Pitch]) -> list[MissedOpportunity]:
    """
    Re-derive missed opportunities from a list of already-parsed Pitch objects.
    Useful when pitches are loaded from the database rather than from a live feed.
    """
    result = []
    for p in pitches:
        mo = _classify_missed_opportunity(p)
        if mo:
            result.append(mo)
    return result


def parse_game(game_feed: dict) -> tuple[list[Pitch], list[MissedOpportunity]]:
    """
    Parse all take pitch events from a game feed.

    Only called balls (B, *B) and called strikes (C) are returned — swings,
    fouls, and balls in play are excluded since they cannot be ABS-challenged.

    Returns:
        pitches           — all take pitches with ABS zone evaluation
        missed_opportunities — takes where umpire was wrong per ABS zone
                              and no challenge was made
    """
    game_data = game_feed.get("gameData", {})
    live_data = game_feed.get("liveData", {})
    game_pk = game_feed.get("gamePk", 0)
    game_date = game_data.get("datetime", {}).get("officialDate", "")

    pitches: list[Pitch] = []
    missed_opportunities: list[MissedOpportunity] = []

    all_plays = live_data.get("plays", {}).get("allPlays", [])

    for play in all_plays:
        about = play.get("about", {})
        matchup = play.get("matchup", {})

        inning = about.get("inning", 0)
        half_inning = about.get("halfInning", "")
        at_bat_index = about.get("atBatIndex", 0)

        batter = matchup.get("batter", {})
        pitcher = matchup.get("pitcher", {})
        batter_id = batter.get("id", 0)
        batter_name = batter.get("fullName", "Unknown")
        pitcher_id = pitcher.get("id", 0)
        pitcher_name = pitcher.get("fullName", "Unknown")

        # Fetch height once per at-bat (cached across the game)
        batter_height_ft = get_batter_height_ft(batter_id) if batter_id else None
        abs_zone = compute_abs_zone(batter_height_ft) if batter_height_ft is not None else None

        for event in play.get("playEvents", []):
            if not event.get("isPitch"):
                continue

            details = event.get("details", {})
            call_code = details.get("code") or (details.get("call") or {}).get("code", "")
            if call_code not in TAKE_CALL_CODES:
                continue

            count = event.get("count", {})
            pitch = _build_pitch(
                game_pk=game_pk,
                game_date=game_date,
                at_bat_index=at_bat_index,
                inning=inning,
                half_inning=half_inning,
                batter_id=batter_id,
                batter_name=batter_name,
                pitcher_id=pitcher_id,
                pitcher_name=pitcher_name,
                event=event,
                abs_zone=abs_zone,
                batter_height_ft=batter_height_ft,
                count_balls=count.get("balls"),
                count_strikes=count.get("strikes"),
            )
            pitches.append(pitch)

            mo = _classify_missed_opportunity(pitch)
            if mo:
                missed_opportunities.append(mo)

    return pitches, missed_opportunities
