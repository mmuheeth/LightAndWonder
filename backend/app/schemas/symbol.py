from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.game_context import GameMode
from app.schemas.roi import RoiImage


class SymbolModelInfo(BaseModel):
    """A trained classifier, as it was when training finished."""

    architecture: str
    trained_at: datetime
    # Symbol codes it can name.
    classes: list[str]
    image_count: int
    epochs: int
    # Percent of the held-out artwork it named correctly, overall and for its worst symbol (the
    # "floor"). Null when no symbol had enough images to hold any out.
    accuracy: float | None = None
    floor: float | None = None
    # Symbols with too few images to check (they are trained on whole).
    unchecked: list[str] = []


class TrainingProgress(BaseModel):
    epoch: int
    epochs: int
    loss: float | None = None


class SymbolModelStatus(BaseModel):
    """Where a game's classifier stands. `model` is the last finished one, also while another is training."""

    game: str
    # untrained: no model yet; training: one is being fitted; ready: a model is usable;
    # failed: the last training failed (`model` is then the one from before, if any).
    state: Literal["untrained", "training", "ready", "failed"]
    # Artwork found under app/games/<game>/symbols, one folder per symbol code.
    dataset_classes: int
    dataset_images: int
    # Percent a tile must reach to be named; the UI's starting value.
    min_confidence: float
    model: SymbolModelInfo | None = None
    progress: TrainingProgress | None = None
    error: str | None = None


class SymbolTile(BaseModel):
    """What the classifier read in one grid position. Both indexes start at 0."""

    row: int
    column: int
    # Its best guess, however unsure it was.
    code: str
    # The code's name in the game config; null when the config does not name it.
    name: str | None = None
    # Percent (0-100) the classifier puts on `code`.
    confidence: float


class SymbolReading(BaseModel):
    """The symbols read off one result screenshot."""

    # The id of the ROI record (screenshot and tiles) that was read.
    id: str
    created_at: datetime
    game: str
    mode: GameMode
    rows: int
    columns: int
    # The reel grid as it was cut from the screenshot, for showing the tiles where they sit. Null in
    # readings saved before it was kept.
    reels: RoiImage | None = None
    model: SymbolModelInfo
    # Row by row, left to right.
    tiles: list[SymbolTile]
