from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.game_context import GameMode
from app.schemas.roi import RoiImage

# How a message area's capture ended: "closed" - a message came round again, so the whole cycle was seen;
# "steady" - after the game went idle it kept showing the same thing (one message, or none); "open" - the capture
# ended before either, so the area may have had more messages.
CycleState = Literal["open", "closed", "steady"]
EventType = Literal["result", "first_cycle_done", "cycle_stopped", "game_over"]
# Why a round stopped being captured: "complete" - every area's first loop was seen (the game reported the first pass over
# the winning lines done, or it came round again, or it held steady once the game was idle); "next_spin" - the next
# spin began first; "timeout" - it took longer than the limit; "stopped" - tracking was stopped; "interrupted" -
# the backend stopped while it was being captured.
EndReason = Literal["complete", "next_spin", "timeout", "stopped", "interrupted"]
Phase = Literal["stopped", "waiting", "spinning", "capturing"]


class CyclicMessage(RoiImage):
    """One distinct message a message area showed."""

    # Position among the area's messages, in the order they were first seen.
    index: int
    # Seconds after the reels stopped that it first appeared.
    first_seen: float
    # How many times it was shown (more than once when the area cycled).
    appearances: int
    # What the OCR read. Null until it has; empty when it found no text.
    text: str | None = None
    confidence: float | None = None
    # Set when the OCR could not read it (e.g. its models did not load).
    read_error: str | None = None


class CyclicRegion(BaseModel):
    # The game config key: "cyclic_message" or "cyclic_message_2".
    name: str
    # Where it was cut, as [left, top, right, bottom] fractions of the screenshot.
    roi: list[float]
    messages: list[CyclicMessage] = []
    # The messages in the order they were shown, as indexes into `messages`: [0, 1, 2, 0, 1, 2] for a cycle of three.
    sequence: list[int] = []
    cycle: CycleState = "open"


class CyclicEvent(BaseModel):
    """Something the game's log said about the spin, placed on the capture's clock."""

    type: EventType
    # Seconds after the reels stopped.
    at: float
    # The game machine's clock, as written in the log.
    log_time: datetime | None = None


class CyclicRound(BaseModel):
    """What the message areas showed after one spin, from the moment its reels stopped."""

    id: str
    # When the spin started.
    created_at: datetime
    game: str
    mode: GameMode
    # From the log's result line; null until it has been seen.
    won: bool | None = None
    # The win in the game's smallest currency unit (400 is $4.00), as the log writes it.
    win_amount: float | None = None
    events: list[CyclicEvent] = []
    regions: list[CyclicRegion] = []
    # How many screenshots were taken, and how long the capture has run (seconds after the reels stopped).
    frames: int = 0
    seconds: float = 0.0
    # Null while the round is being captured.
    end_reason: EndReason | None = None


class CyclicStatus(BaseModel):
    tracking: bool
    # What is (or, when stopped, would be) tracked: the selected game and mode.
    game: str
    mode: GameMode
    # "waiting": for a spin; "spinning": the reels are turning; "capturing": screenshots are being taken.
    phase: Phase
    # Spins seen since tracking started.
    rounds: int
    # The round being captured, as far as it has got.
    current: CyclicRound | None = None
    log_path: str | None = None
    # The log cannot be read, so no spin will be noticed.
    log_unreadable: bool = False
    # What is wrong right now, e.g. OBS refusing screenshots.
    problem: str | None = None
    # The OCR models are loaded.
    ocr_ready: bool = False
