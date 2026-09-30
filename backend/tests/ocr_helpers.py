"""Stand-ins and real samples for the OCR tests: the boxes PaddleOCR produced on the game's own crops, and
an engine that answers with them, so no test loads the models (that takes a minute)."""

import threading
import time

from PIL import Image

from app.utils.ocr_engine import TextBox, TextLine


def box(text: str, left: float, top: float, right: float, bottom: float, score: float = 1.0) -> TextBox:
    return TextBox(text=text, score=score, left=left, top=top, right=right, bottom=bottom)


# FortuneOx in credit mode, nothing won (roi_20260930_105526).
CREDITS_NO_WIN = [
    box("Game Pays 0", 20, 21, 85, 38, 0.999),
    box("99720", 293, 12, 384, 45),
    box("CREDITS", 294, 42, 383, 62),
    box("WIN", 514, 51, 567, 73, 0.84),
    box("88", 718, 13, 762, 45),
    box("BET", 722, 43, 765, 61, 0.988),
    box("88 CREDIT GAMEACTIVE", 853, 7, 967, 23, 0.986),
]

# Cash mode with a win; the recognizer reads WIN as "W1N" (roi_20260930_160333).
CASH_WITH_WIN = [
    box("Play 880 Credits", 19, 20, 99, 38, 0.95),
    box("Line 14 Pays 10", 20, 6, 112, 22),
    box("$1,039.55", 258, 11, 409, 46),
    box("CASH", 308, 42, 370, 62, 0.999),
    box("$1.30", 477, 7, 597, 49),
    box("W1N", 514, 52, 567, 73, 0.826),
    box("$0.88", 697, 12, 782, 45),
    box("BET", 722, 43, 765, 61, 0.988),
    box("88 CREDIT GAMEACTIVE", 853, 7, 967, 23, 0.986),
    box("CHANGE DONO", 1007, 48, 1052, 61, 0.76),
]

# Cash mode, nothing won; "1" is the denomination button (roi_20260930_152438).
CASH_NO_WIN = [
    box("$1,039.13", 254, 11, 410, 47),
    box("CASH", 310, 42, 369, 63, 0.999),
    box("W1N", 516, 52, 567, 73, 0.877),
    box("$0.88", 697, 8, 822, 46),
    box("BET", 722, 43, 764, 61, 0.988),
    box("88 CREDITGAMEACTIVE", 854, 10, 966, 22, 0.979),
    box("1", 999, 11, 1068, 63, 0.985),
]


class FakeOcrEngine:
    """Answers by the colour of the image's top-left pixel, which is how a test says "this is the crop cut
    from that place in that screenshot"."""

    def __init__(
        self,
        meters: dict[tuple[int, int, int], list[TextBox]] | None = None,
        lines: dict[tuple[int, int, int], TextLine] | None = None,
    ) -> None:
        self.meters = meters or {}
        self.lines = lines or {}
        self.preloaded = False
        self.failure: Exception | None = None
        # How many reads it accepts at once, how long each takes, and the most that ever ran together.
        self.lanes = 1
        self.delay = 0.0
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self.preloaded

    def preload(self) -> None:
        self.preloaded = True

    def read_boxes(self, image: Image.Image) -> list[TextBox]:
        self._reading()
        return list(self.meters.get(_color(image), []))

    def read_line(self, image: Image.Image) -> TextLine:
        self._reading()
        return self.lines.get(_color(image), TextLine(text="", score=0.0))

    def _reading(self) -> None:
        if self.failure:
            raise self.failure
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(self.delay)
        finally:
            with self._lock:
                self._active -= 1


def _color(image: Image.Image) -> tuple[int, int, int]:
    return image.convert("RGB").getpixel((0, 0))
