"""
Data models for MLB ABS (Automated Ball-Strike) challenge tracking.

ABS Zone note: MLB does not publish absZoneTop/absZoneBottom in the 2026 game feed.
Zone boundaries are computed from batter height via:
  top    = height_ft * 0.535
  bottom = height_ft * 0.27
  width  = ±0.708 ft from center (17-inch plate)
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ABSZone:
    """Computed ABS strike zone for a specific batter."""
    top: float
    bottom: float
    half_width: float = 0.708  # ±0.708 ft (17-inch plate)

    def contains(self, px: float, pz: float) -> bool:
        """Return True if any part of the ball overlaps this ABS strike zone.

        The pitch coordinates represent the ball's center. A ball 2.9" in diameter
        (radius = 1.45" = ~0.1208 ft) is a strike if its edge touches the zone,
        so each boundary is expanded by one ball radius.
        """
        r = 1.45 / 12  # ball radius in feet (~0.1208 ft)
        return abs(px) <= self.half_width + r and self.bottom - r <= pz <= self.top + r


@dataclass
class Pitch:
    """A single take pitch (called ball or called strike) with ABS zone evaluation."""

    # --- Game context ---
    game_pk: int
    game_date: str
    at_bat_index: int
    pitch_number: int
    play_id: Optional[str]

    # --- Inning ---
    inning: int
    half_inning: str  # 'top' or 'bottom'

    # --- Players ---
    batter_id: int
    batter_name: str
    pitcher_id: int
    pitcher_name: str

    # --- Umpire call ---
    call_code: str         # e.g. 'B', 'C', '*B'
    call_description: str  # e.g. 'Ball', 'Called Strike'
    is_strike: bool
    is_ball: bool
    is_in_play: bool
    is_take: bool          # True if call_code in TAKE_CALL_CODES

    # --- Pitch coordinates (feet, catcher's POV) ---
    px: Optional[float]  # horizontal position at plate
    pz: Optional[float]  # vertical position at plate

    # --- Stringer zone (from game feed pitchData — NOT the ABS zone) ---
    # ⚠️  These are set by a human data-entry operator; do NOT use for ABS evaluation.
    stringer_zone_top: Optional[float]
    stringer_zone_bottom: Optional[float]

    # --- ABS zone (computed from batter height via formula) ---
    abs_zone_top: Optional[float]     # height_ft * 0.535
    abs_zone_bottom: Optional[float]  # height_ft * 0.27
    batter_height_ft: Optional[float]

    # --- ABS evaluation (None if pitch coordinates unavailable) ---
    in_abs_zone: Optional[bool]

    # --- Challenge / review data ---
    has_review: bool
    is_overturned: Optional[bool]     # None if not challenged
    challenge_team_id: Optional[int]  # teamId of challenging team
    challenger_id: Optional[int]      # player.id from reviewDetails
    challenger_name: Optional[str]    # player.fullName from reviewDetails
    review_type: Optional[str]        # e.g. "MJ" (manager's challenge)

    # --- Pitch info ---
    pitch_type: Optional[str]       # e.g. "Four-Seam Fastball"
    pitch_type_code: Optional[str]  # e.g. "FF"
    start_speed: Optional[float]    # mph
    statcast_zone: Optional[int]    # Statcast zone 1-14

    # --- At-bat count after original umpire call (pre-review) ---
    count_balls: Optional[int] = None
    count_strikes: Optional[int] = None


@dataclass
class MissedOpportunity:
    """
    A take where the umpire's call was wrong per ABS zone and no challenge was made.

    Types:
      'batter_should_challenge'  — Called Strike but pitch is outside ABS zone
      'defense_should_challenge' — Called Ball but pitch is inside ABS zone
    """
    pitch: Pitch
    opportunity_type: str  # 'batter_should_challenge' or 'defense_should_challenge'
    umpire_call: str       # 'Called Strike' or 'Ball'
    abs_verdict: str       # 'ball' or 'strike'
    px: float
    pz: float


@dataclass
class Game:
    """Aggregated data for a single game."""
    game_pk: int
    game_date: str
    home_team_id: int
    home_team_name: str
    away_team_id: int
    away_team_name: str
    pitches: list = field(default_factory=list)              # list[Pitch]
    missed_opportunities: list = field(default_factory=list) # list[MissedOpportunity]
