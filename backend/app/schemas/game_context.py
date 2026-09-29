from enum import Enum

from pydantic import BaseModel


class GameMode(str, Enum):
    SIMULATOR = "simulator"
    EGM = "egm"


class GameContext(BaseModel):
    """The currently selected game and mode; every other feature depends on it."""

    game: str
    mode: GameMode


class GameContextOptions(BaseModel):
    games: list[str]
    modes: list[GameMode]


class GameContextResponse(BaseModel):
    context: GameContext
    options: GameContextOptions


class GameContextUpdate(BaseModel):
    """Partial update: omitted fields keep their current value."""

    game: str | None = None
    mode: GameMode | None = None
