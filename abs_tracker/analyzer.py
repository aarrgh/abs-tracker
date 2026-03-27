"""
Aggregate ABS challenge stats by player, defense, and overall umpire accuracy.

All aggregation uses pandas. Input is lists of Pitch and MissedOpportunity
objects from parser.py.

Note on umpire analysis: The HP umpire is in gameData.officials in the game
feed, not on individual pitch events. Umpire-per-pitch assignment requires
joining game-level umpire data (not yet implemented). analyze_umpires()
currently returns game-level accuracy aggregates only.
"""

from typing import Optional

import pandas as pd

from .models import MissedOpportunity, Pitch


def _pitches_to_df(pitches: list[Pitch]) -> pd.DataFrame:
    if not pitches:
        return pd.DataFrame()
    return pd.DataFrame([vars(p) for p in pitches])


def _missed_ops_to_df(missed_ops: list[MissedOpportunity]) -> pd.DataFrame:
    if not missed_ops:
        return pd.DataFrame()
    rows = []
    for mo in missed_ops:
        row = vars(mo.pitch).copy()
        row["opportunity_type"] = mo.opportunity_type
        row["umpire_call"] = mo.umpire_call
        row["abs_verdict"] = mo.abs_verdict
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_batters(
    pitches: list[Pitch],
    missed_ops: list[MissedOpportunity],
) -> pd.DataFrame:
    """
    Per-batter challenge stats.

    Columns:
      batter_id, batter_name
      takes                      — total takes (called balls + called strikes)
      called_strikes             — umpire-called strikes on takes
      called_balls               — umpire-called balls on takes
      challenges_made            — times batter challenged (called strike + hasReview)
      challenges_won             — overturned batter challenges
      missed_challenge_opps      — called strikes outside ABS zone, not challenged
    """
    df = _pitches_to_df(pitches)
    if df.empty:
        return pd.DataFrame()

    stats = (
        df.groupby(["batter_id", "batter_name"])
        .agg(
            takes=("pitch_number", "count"),
            called_strikes=("is_strike", "sum"),
            called_balls=("is_ball", "sum"),
        )
        .reset_index()
    )

    # Batter challenges are on called strikes
    batter_ch = (
        df[df["is_strike"] & df["has_review"]]
        .groupby(["batter_id", "batter_name"])
        .agg(
            challenges_made=("has_review", "count"),
            challenges_won=("is_overturned", "sum"),
        )
        .reset_index()
    )
    stats = stats.merge(batter_ch, on=["batter_id", "batter_name"], how="left")
    stats[["challenges_made", "challenges_won"]] = (
        stats[["challenges_made", "challenges_won"]].fillna(0).astype(int)
    )

    mo_df = _missed_ops_to_df(missed_ops)
    if not mo_df.empty:
        batter_mo = (
            mo_df[mo_df["opportunity_type"] == "batter_should_challenge"]
            .groupby(["batter_id", "batter_name"])
            .size()
            .reset_index(name="missed_challenge_opps")
        )
        stats = stats.merge(batter_mo, on=["batter_id", "batter_name"], how="left")
    else:
        stats["missed_challenge_opps"] = 0

    stats["missed_challenge_opps"] = stats["missed_challenge_opps"].fillna(0).astype(int)
    return stats.sort_values("batter_name").reset_index(drop=True)


def analyze_defense(
    pitches: list[Pitch],
    missed_ops: list[MissedOpportunity],
) -> pd.DataFrame:
    """
    Per-pitcher defense challenge stats.
    (Defense = pitcher + catcher side; challenges come on called balls.)

    Columns:
      pitcher_id, pitcher_name
      takes, called_strikes, called_balls
      challenges_made            — times defense challenged (called ball + hasReview)
      challenges_won             — overturned defense challenges
      missed_challenge_opps      — called balls inside ABS zone, not challenged
    """
    df = _pitches_to_df(pitches)
    if df.empty:
        return pd.DataFrame()

    stats = (
        df.groupby(["pitcher_id", "pitcher_name"])
        .agg(
            takes=("pitch_number", "count"),
            called_strikes=("is_strike", "sum"),
            called_balls=("is_ball", "sum"),
        )
        .reset_index()
    )

    # Defense challenges are on called balls
    def_ch = (
        df[df["is_ball"] & df["has_review"]]
        .groupby(["pitcher_id", "pitcher_name"])
        .agg(
            challenges_made=("has_review", "count"),
            challenges_won=("is_overturned", "sum"),
        )
        .reset_index()
    )
    stats = stats.merge(def_ch, on=["pitcher_id", "pitcher_name"], how="left")
    stats[["challenges_made", "challenges_won"]] = (
        stats[["challenges_made", "challenges_won"]].fillna(0).astype(int)
    )

    mo_df = _missed_ops_to_df(missed_ops)
    if not mo_df.empty:
        def_mo = (
            mo_df[mo_df["opportunity_type"] == "defense_should_challenge"]
            .groupby(["pitcher_id", "pitcher_name"])
            .size()
            .reset_index(name="missed_challenge_opps")
        )
        stats = stats.merge(def_mo, on=["pitcher_id", "pitcher_name"], how="left")
    else:
        stats["missed_challenge_opps"] = 0

    stats["missed_challenge_opps"] = stats["missed_challenge_opps"].fillna(0).astype(int)
    return stats.sort_values("pitcher_name").reset_index(drop=True)


def analyze_umpires(pitches: list[Pitch]) -> pd.DataFrame:
    """
    Overall umpire call accuracy across all takes with valid ABS zone data.

    ⚠️  HP umpire ID is in gameData.officials (game-level), not on individual
    pitch events. Umpire-per-pitch joining is not yet implemented. This
    function returns aggregate accuracy only.

    Columns:
      total_takes_evaluated   — takes with both pX/pZ coords and ABS zone
      correct_strikes         — called strike AND in ABS zone
      correct_balls           — called ball AND outside ABS zone
      wrong_strikes           — called strike AND outside ABS zone (batter robbed)
      wrong_balls             — called ball AND inside ABS zone (defense robbed)
      accuracy_pct
    """
    df = _pitches_to_df(pitches)
    if df.empty:
        return pd.DataFrame()

    ev = df[df["in_abs_zone"].notna()].copy()
    if ev.empty:
        return pd.DataFrame()

    in_zone = ev["in_abs_zone"].astype(bool)
    correct_strikes = int((ev["is_strike"] & in_zone).sum())
    correct_balls = int((ev["is_ball"] & ~in_zone).sum())
    wrong_strikes = int((ev["is_strike"] & ~in_zone).sum())
    wrong_balls = int((ev["is_ball"] & in_zone).sum())
    total = len(ev)
    accuracy = round((correct_strikes + correct_balls) / total * 100, 1) if total else None

    return pd.DataFrame([{
        "total_takes_evaluated": total,
        "correct_strikes": correct_strikes,
        "correct_balls": correct_balls,
        "wrong_strikes": wrong_strikes,
        "wrong_balls": wrong_balls,
        "accuracy_pct": accuracy,
    }])


def analyze_challenges(pitches: list[Pitch]) -> pd.DataFrame:
    """
    Flat table of every challenge made, with ABS zone evaluation.
    Useful for auditing individual challenge outcomes.
    """
    df = _pitches_to_df(pitches)
    if df.empty:
        return pd.DataFrame()

    challenged = df[df["has_review"]].copy()
    if challenged.empty:
        return pd.DataFrame()

    cols = [
        "game_pk", "game_date", "inning", "half_inning",
        "batter_name", "pitcher_name",
        "call_code", "call_description",
        "px", "pz",
        "abs_zone_bottom", "abs_zone_top", "in_abs_zone",
        "is_overturned", "challenge_team_id", "challenger_name", "review_type",
        "pitch_type", "start_speed", "statcast_zone",
        "stringer_zone_bottom", "stringer_zone_top",
    ]
    return challenged[cols].reset_index(drop=True)


def analyze_missed_opportunities(missed_ops: list[MissedOpportunity]) -> pd.DataFrame:
    """
    Flat table of all missed challenge opportunities with context.
    """
    df = _missed_ops_to_df(missed_ops)
    if df.empty:
        return pd.DataFrame()

    cols = [
        "opportunity_type", "umpire_call", "abs_verdict",
        "game_pk", "game_date", "inning", "half_inning",
        "batter_name", "pitcher_name",
        "px", "pz", "abs_zone_bottom", "abs_zone_top",
        "pitch_type", "start_speed", "statcast_zone",
    ]
    return df[cols].reset_index(drop=True)
