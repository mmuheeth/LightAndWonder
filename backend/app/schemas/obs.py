from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Both are lossless. BMP is by far the fastest to capture; PNG is for consumers that need it.
ScreenshotFormat = Literal["bmp", "png"]

# What gets captured. "scene": the composed scene at canvas size, exactly as OBS outputs it
# (constant image size). "native": the scene's single source at its own pixel size, without
# OBS rescaling it to the canvas; the image size then follows that source.
ScreenshotMode = Literal["native", "scene"]


class ObsStatus(BaseModel):
    obs_running: bool
    connected: bool
    recording: bool
    # Set while recording: where the video is being written.
    recording_path: str | None = None


class ScreenshotInfo(BaseModel):
    filename: str
    created_at: datetime
    size_bytes: int
    # API path (relative to the API prefix) the image can be fetched from.
    url: str


class RecordingResult(BaseModel):
    """Outcome of stopping a recording."""

    output_path: str | None = None


class ObsConfig(BaseModel):
    """The obs-websocket server this app talks to."""

    host: str = Field(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9._\-]+$")
    port: int = Field(ge=1, le=65535)


class ObsWindow(BaseModel):
    """A window OBS can capture."""

    # OBS's own identifier ("title:class:executable"); what gets sent back to select it.
    value: str = Field(min_length=1)
    # Human-readable label, e.g. "[FortuneOx.exe]: FortuneOx".
    name: str = ""


class ObsCaptureSetup(BaseModel):
    """The window being captured and how OBS is currently laid out for it."""

    window: ObsWindow | None = None
    canvas_width: int | None = None
    canvas_height: int | None = None
    # False when the saved window could not be applied (see `warning`).
    applied: bool = False
    warning: str | None = None
