from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.game_context import GameMode


class CurrentPaytable(BaseModel):
    """What the game log currently says is in play. Cheap to build: never touches the disk."""

    game: str
    mode: GameMode
    log_path: str | None = Field(None, description="None when the game has no log for this mode.")
    log_unreadable: bool = Field(
        False, description="The log exists in the config but could not be opened or read."
    )
    paytable_id: str | None = Field(None, description="None until the log has reported one.")
    denom: float | None = Field(None, description="In cents, as written in the log.")
    supported_denoms: list[float] = []


class PaytableList(BaseModel):
    game: str
    mode: GameMode
    directory: str
    paytables: list[str]


class SymbolKind(str, Enum):
    REGULAR = "regular"
    WILD = "wild"
    SCATTER = "scatter"


class SymbolInfo(BaseModel):
    code: str
    name: str
    kind: SymbolKind


class PaytableSummary(BaseModel):
    display_name: str | None = None
    return_pct: float | None = None
    base_return_pct: float | None = None
    lines: int | None = None
    min_total_bet: int | None = None
    max_bets: list[int] = []


class PaylineSet(BaseModel):
    id: int
    # lines[n][reel] is the row line n crosses on that reel, 0 being the top row.
    lines: list[list[int]]


class WinGeometry(BaseModel):
    file: str
    reels: int
    rows: int
    active_set: int | None = Field(None, description="The set this paytable plays, if in the file.")
    sets: list[PaylineSet]


class PaylineComboRow(BaseModel):
    symbols: list[str] = Field(description="Symbols that pay exactly the same.")
    # payouts[i] is for a run of `PaylineCombos.lengths[i]` symbols; None when it pays nothing.
    payouts: list[float | None]


class PaylineCombos(BaseModel):
    lengths: list[int] = Field(description="Run lengths present, longest first.")
    rows: list[PaylineComboRow] = Field(description="Best paying first.")


class ReelStrip(BaseModel):
    id: str
    stops: list[str] = Field(description="Symbol code at each stop, in strip order.")
    weights: list[int] = Field(description="One per stop, in the same order.")


class ReelStripSet(BaseModel):
    id: str
    label: str | None = None
    visible_rows: int
    strip_ids: list[str] = Field(description="One per reel; ids may repeat.")


class OrbValue(BaseModel):
    label: str = Field(description="The value to display, e.g. '100' or 'JP3'.")
    jackpot: bool
    weight: int
    probability: float


class OrbTable(BaseModel):
    title: str
    table: str
    bet: int
    total_weight: int
    values: list[OrbValue]


class PaytableConfig(BaseModel):
    """Everything the Game Config tab shows for one paytable."""

    game: str
    mode: GameMode
    paytable_id: str
    summary: PaytableSummary
    symbols: list[SymbolInfo]
    win_geometry: WinGeometry | None = None
    payline_combos: PaylineCombos | None = None
    default_reel_strip_set: str | None = None
    reel_strip_sets: list[ReelStripSet]
    reel_strips: list[ReelStrip]
    orb_tables: list[OrbTable]
    warnings: list[str] = Field([], description="Sections that could not be built, and why.")
