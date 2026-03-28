"""
SQLAlchemy ORM models for the PostgreSQL ABS challenge database.

Tables
------
games  — one row per ingested game
takes  — one row per take (called ball or called strike) with ABS evaluation

Notes
-----
- catcher_id and umpire_id are nullable because the current parsing
  infrastructure only exposes names, not IDs, for these roles.
- challenge_outcome is nullable: "successful" / "failed" / None (no challenge).
- umpire_call stores the ORIGINAL umpire decision ("called_strike" or "ball"),
  derived from call_code ('C' → called_strike; 'B'/'*B' → ball), which is
  NOT retroactively updated after a challenge (unlike is_strike / is_ball).
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    game_pk: int = Column(Integer, primary_key=True)
    game_date: date = Column(Date, nullable=False)
    home_team: str = Column(String, nullable=False)
    away_team: str = Column(String, nullable=False)
    status: str = Column(String, nullable=False)
    ingested_at: datetime = Column(DateTime, nullable=False)

    takes = relationship("Take", back_populates="game", cascade="all, delete-orphan")


class Take(Base):
    __tablename__ = "takes"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    game_pk: int = Column(Integer, ForeignKey("games.game_pk"), nullable=False, index=True)
    game_date: date = Column(Date, nullable=False)
    inning: int = Column(Integer)
    inning_half: str = Column(String)          # "top" or "bottom"
    at_bat_index: int = Column(Integer)
    pitch_number: int = Column(Integer)
    batter_id: int = Column(Integer, index=True)
    batter_name: str = Column(String)
    pitcher_id: int = Column(Integer, index=True)
    pitcher_name: str = Column(String)
    catcher_id: Optional[int] = Column(Integer, nullable=True)
    catcher_name: Optional[str] = Column(String, nullable=True)
    umpire_id: Optional[int] = Column(Integer, nullable=True)
    umpire_name: Optional[str] = Column(String, nullable=True)
    px: Optional[float] = Column(Float, nullable=True)
    pz: Optional[float] = Column(Float, nullable=True)
    abs_zone_top: Optional[float] = Column(Float, nullable=True)
    abs_zone_bottom: Optional[float] = Column(Float, nullable=True)
    umpire_call: str = Column(String)          # "called_strike" or "ball"
    in_abs_zone: Optional[bool] = Column(Boolean, nullable=True)
    challenge_outcome: Optional[str] = Column(String, nullable=True)  # "successful"/"failed"/None
    is_defense_challenge: Optional[bool] = Column(Boolean, nullable=True)  # True=defense, False=batter, None=no challenge
    missed_opportunity: bool = Column(Boolean, nullable=False, default=False)

    game = relationship("Game", back_populates="takes")
