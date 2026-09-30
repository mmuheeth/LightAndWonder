from datetime import datetime

from pydantic import BaseModel

from app.schemas.game_context import GameMode
from app.schemas.obs import ScreenshotInfo
from app.schemas.roi import RoiImage


class OcrCrop(RoiImage):
    """One image the OCR reads, cut out of a screenshot."""

    # "credit_meter" / "cash_meter" (the game's meter region while it showed that meter), "meter" (the
    # meter region when which meter it showed was not known), "cyclic_message" or "cyclic_message_2".
    name: str
    # Where it was cut, as [left, top, right, bottom] fractions of the screenshot.
    roi: list[float]


class AmountRead(BaseModel):
    """One amount of a meter. Nothing is set when the meter showed none (e.g. no win)."""

    # What was read, as the game shows it: "$1,039.55", "99720".
    text: str | None = None
    # The number in `text`, without the currency symbol and thousands separators: 1039.55, 99720.
    value: float | None = None
    # Percent the recognizer was sure of the text.
    confidence: float | None = None


class MeterFields(BaseModel):
    # May be empty: the game shows no win most of the time.
    win: AmountRead
    bet: AmountRead
    # What looked wrong: a required amount that was not found, or one read with little confidence.
    issues: list[str] = []


class CreditMeterReading(MeterFields):
    """The meter while it counts in credits."""

    credits: AmountRead


class CashMeterReading(MeterFields):
    """The meter while it counts in currency."""

    cash: AmountRead


class TextRead(BaseModel):
    # Empty when the message area showed nothing (cyclic messages blank between messages).
    text: str
    confidence: float | None = None


class OcrReadings(BaseModel):
    read_at: datetime
    # How long the OCR took.
    seconds: float
    # Each is null when the meter was not captured, or the crop was not of that meter.
    credit_meter: CreditMeterReading | None = None
    cash_meter: CashMeterReading | None = None
    # Null when the game has no such message area.
    cyclic_message: TextRead | None = None
    cyclic_message_2: TextRead | None = None
    # What went wrong with no meter to blame, e.g. a crop of the meter that could not be identified.
    issues: list[str] = []


class OcrEngineStatus(BaseModel):
    # The OCR models are loaded, so a read starts at once. Until then a read waits for them (~30-60 s).
    ready: bool


class OcrRecord(BaseModel):
    """One capture: the regions the OCR reads, and what it read once it has."""

    id: str
    created_at: datetime
    game: str
    mode: GameMode
    # What the crops were cut from: the screenshot of the meter as it was found, then (when the meter
    # could be toggled) the one of the other meter.
    screenshots: list[ScreenshotInfo]
    crops: list[OcrCrop]
    # Things worth telling the person: why only one meter was captured, or that the meter was left toggled.
    notes: list[str] = []
    # Null until the record has been read.
    readings: OcrReadings | None = None
