from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.game_config import PayKind
from app.schemas.game_context import GameMode
from app.schemas.roi import RoiImage


class PaylineCell(BaseModel):
    """What was read in one grid position. Both indexes start at 0; `column` is the reel."""

    row: int
    column: int
    # The symbol, or null when the classifier was under the confidence floor and the tile counts as unread.
    code: str | None = None
    # The classifier's best guess, however unsure it was.
    guess: str
    name: str | None = Field(None, description="The symbol's name in the game config.")
    confidence: float


class PaylineStep(BaseModel):
    """One reel's symbol on a line set against the next reel's."""

    # same: the two are the same symbol; wild: a wild stands in for the other; different: the run
    # ends here; unknown: one of them was unread.
    relation: Literal["same", "wild", "different", "unknown"]
    # Whether the step decided the run: the matches, and the one that ended it. Steps after that only
    # show how the remaining symbols compare, with no wild allowed for.
    counted: bool


class PaidCombo(BaseModel):
    """The payline combo a line was paid by."""

    id: int | None = Field(None, description="The ComboID in math.xml.")
    # One entry per reel: the run, then ANY for the reels that do not matter.
    pattern: list[str]
    value: float


class PaylineBet(BaseModel):
    """The bet the awards were worked out for, as the game log reported it."""

    denom: float = Field(description="In cents, as written in the log.")
    bets_per_unit: float = Field(
        description="Cents bet on each line (each way, for a ways paytable): the credits times the denom."
    )
    credits_per_unit: float = Field(
        description="Credits bet on each line (way): bets_per_unit / denom. A combo's value is multiplied by it."
    )
    total_bet: float = Field(description="Credits bet on the spin.")


class PaylineOutcome(BaseModel):
    """One payline of the win geometry, read left to right."""

    number: int = Field(description="1-based: the first line of the set is line 1.")
    # One per reel, left to right: the positions the line crosses.
    cells: list[PaylineCell]
    # Between neighbouring cells, so one fewer than the cells.
    steps: list[PaylineStep]
    # The symbol the run is of (the paying combo's, if it paid); null when the first cell was unread.
    symbol: str | None = None
    symbol_name: str | None = None
    # Reels in the run from the left, wilds included; 0 when the first cell was unread.
    matches: int
    combo: PaidCombo | None = None
    # What the combo pays for one credit bet on the line.
    pays: float
    # What the line pays at the bet that was played: `pays` times the credits bet on each line.
    credits: float
    # A run of two or more of a symbol that the paytable pays for other run lengths, but not this one
    # (and no unread tile could have made it longer).
    unpaid: bool = False
    # An unread tile on the line could make it pay, or pay more, than it does here.
    uncertain: bool = False


class WayOutcome(BaseModel):
    """One symbol of a ways paytable: the run it makes over neighbouring reels from the left, on any rows."""

    symbol: str
    symbol_name: str | None = None
    # One entry per reel counted, left to right: the cells that show the symbol or a wild standing in for it.
    reels: list[list[PaylineCell]]
    # Reels counted: the paying combo's length, or the whole run when nothing paid.
    matches: int
    # The routes over those reels: the cells that match, multiplied reel by reel.
    ways: int
    combo: PaidCombo | None = None
    # The combo's value for each way, times the ways: what the symbol pays for one credit bet on each way.
    pays: float
    # What the symbol pays at the bet that was played: `pays` times the credits bet on each way.
    credits: float
    # A run of two or more reels that the paytable pays for other run lengths, but not this one
    # (and no unread tile could have made it longer).
    unpaid: bool = False
    # An unread tile could make the symbol pay, or pay more, than it does here.
    uncertain: bool = False
    # The unread tiles that could change this outcome; empty unless it is uncertain.
    unread: list[PaylineCell] = []


class PaylineResult(BaseModel):
    """The paylines (or, for a game that pays by ways, the ways) of one result screenshot, and what they pay."""

    # The symbol reading (and so the ROI record) that was scored.
    reading_id: str
    created_at: datetime
    game: str
    mode: GameMode
    paytable_id: str
    # log: the paytable the game log reported last; request: the one asked for.
    paytable_source: Literal["log", "request"]
    # Whether the paytable pays along lines (`lines` is filled) or by ways (`ways` is).
    kind: PayKind = "lines"
    # The number of lines of the win geometry set that was used; for ways, the ways the grid holds.
    line_set: int
    # Percent a tile had to reach to be read.
    min_confidence: float
    rows: int
    columns: int
    # The reel grid as it was cut from the screenshot, for drawing the lines on.
    reels: RoiImage | None = None
    # Row by row, left to right.
    tiles: list[PaylineCell]
    lines: list[PaylineOutcome]
    ways: list[WayOutcome] = []
    # None when the log has reported no bet (or denom) yet: the awards are then for one credit on each line.
    bet: PaylineBet | None = None
    total_credits: float = Field(
        description="The credits of every line (or symbol, for ways) added up: what the paytable pays at the bet "
        "that was played, that is, its pays times the credits bet on each line."
    )
    # False when an unread tile could change the total, which is then the least it can be.
    complete: bool
