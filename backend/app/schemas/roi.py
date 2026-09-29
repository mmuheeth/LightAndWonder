from datetime import datetime

from pydantic import BaseModel

from app.schemas.game_context import GameMode
from app.schemas.obs import ScreenshotInfo


class RoiImage(BaseModel):
    # API path (relative to the API prefix) the image can be fetched from.
    url: str
    width: int
    height: int


class RoiCrop(RoiImage):
    """One configured region, cut out of the screenshot."""

    # The game config key: "reels" (the whole grid), "cash_meter", "cyclic_message", ...
    name: str
    # Where it was cut, as [left, top, right, bottom] fractions of the screenshot.
    roi: list[float]


class RoiTile(RoiImage):
    """One symbol position of the grid, cut out of the "reels" crop. Both indexes start at 0."""

    row: int
    column: int


class RoiRecord(BaseModel):
    """One extraction: the screenshot, the regions cut out of it, and the grid's tiles."""

    id: str
    created_at: datetime
    game: str
    mode: GameMode
    screenshot: ScreenshotInfo
    crops: list[RoiCrop]
    # Empty when the game has no "reels" region or no reel bounds.
    rows: int = 0
    columns: int = 0
    tiles: list[RoiTile] = []
