from typing import Literal

from pydantic import BaseModel

from app.schemas.game_context import GameMode


class GafStatus(BaseModel):
    """Whether the selected game can be driven right now, and if not, why."""

    game: str
    mode: GameMode
    # Where NRobot listens, and where the game is (which NRobot connects to); None if the game has no GAF config.
    nrobot_url: str
    target: str | None = None
    # NRobot answers and has its keyword libraries loaded.
    reachable: bool
    # There is a live session to the selected game in the selected mode.
    connected: bool
    # The game's idle state machine, while connected (e.g. "stateIdleWithCredits").
    state: str | None = None
    # Why it is not reachable or not connected, or what is wrong with the game's GAF config.
    detail: str | None = None
    # What is holding the game connection right now (e.g. "Spin"). NRobot shares one connection to the game
    # between all its callers, so while this is set, other requests wait or are refused.
    busy: str | None = None


class GafActionParam(BaseModel):
    """An input an action takes, described so the UI can offer it without knowing the action."""

    name: str
    label: str
    kind: Literal["choice", "number"]
    default: str | float
    # For "choice": what may be picked. For "number": the range.
    options: list[str] = []
    min: float | None = None
    max: float | None = None


class GafActionInfo(BaseModel):
    id: str
    label: str
    description: str
    # "common" actions exist for every game; "game" ones only where the game's config lists them.
    scope: Literal["common", "game"]
    params: list[GafActionParam] = []


class GafActionRequest(BaseModel):
    """What an action is run with; anything the action declares but the request leaves out takes its default."""

    params: dict[str, str | float] = {}


class GafActionResult(BaseModel):
    action: str
    label: str
    # One line for a person, e.g. "Spin settled after 6.2s".
    message: str
    # What the action read or did, by name; the values are strings or lists of strings.
    values: dict[str, str | list[str]] = {}
