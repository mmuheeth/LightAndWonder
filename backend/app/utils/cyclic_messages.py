"""Telling the messages of a cyclic message area apart in a series of frames of it, without reading them.

The game's message text is near white on a dark background and switches instantly (measured on FortuneOx: no
fading, and two showings of a message are pixel for pixel the same). So a frame is blank when it has hardly any
text pixels, and otherwise shows the same message as an earlier frame when the two are the same around the text,
pixel for pixel. That is enough to find out which messages an area has, in what order, and when it has come round
again, long before the (slow) OCR has read any of them.

The comparison is strict on purpose. A game can pay on 40 lines, and lines like "Line 16 Pays 80" and "Line 19 Pays 80"
differ by a few faint pixels at a 766 px capture (measured on a live 40-line win: the two most alike lines differ by
33 brightness levels on 16 pixels). Merging two messages would lose one, silently; telling one message apart from
itself would only show up as a duplicate.

It looks only at the text, not the rest of the area, because the game draws effects over the area during a win (a
yellow sparkle crossed the message line of a live win): they are not near white, and they are not where the text is,
so they neither make a blank area look like a message nor one message look like another.

Knows nothing about OBS, the game's log or OCR."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image

# Brightness (0-255, PIL's "L") from which a pixel is text. FortuneOx: text 196 and up, background 72 at most.
TEXT_LUMA = 110
# Text is white or grey, so its red, green and blue are close (at most 55 apart on the live game); a win's sparkle is
# yellow (at least 136 apart). Brighter pixels that are more colourful than this are not text.
TEXT_MAX_SPREAD = 90
# Fewer text pixels than this is a blank area, not a message (a message is ~70-100 pixels in a 766 px capture).
MIN_TEXT_PIXELS = 8
# Two frames show the same message unless some pixel, within this many pixels of the text of either, differs by more
# than DIFF_LUMA in brightness. Every difference between two lines is in the glyphs (measured: within 1 pixel of them).
FOOTPRINT_RADIUS = 2
# Measured on the live game: frames of one message are identical (no pixel moves, 240 pairs over 30 s, and a
# 100 s replay of 40 lines finds the same 40 messages at any threshold from 0 to 16), while the most alike two
# different lines differ by 33 levels. 40 here merged three lines of a 40-line win into earlier ones.
DIFF_LUMA = 8

CycleState = Literal["closed", "steady"]


def text_mask(image: Image.Image) -> np.ndarray:
    """Which pixels of `image` are text: bright, and white or grey rather than a colour."""
    rgb = np.asarray(image.convert("RGB")).astype(np.int16)
    luma = np.asarray(image.convert("L"))
    return (luma >= TEXT_LUMA) & ((rgb.max(axis=2) - rgb.min(axis=2)) <= TEXT_MAX_SPREAD)


def _grow(mask: np.ndarray, radius: int) -> np.ndarray:
    """`mask` and every pixel within `radius` of it, in a square."""
    height, width = mask.shape
    padded = np.pad(mask, radius)
    grown = np.zeros_like(mask)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            grown |= padded[dy : dy + height, dx : dx + width]
    return grown


@dataclass
class ShownMessage:
    """One distinct message an area has shown."""

    index: int
    luma: np.ndarray  # the frame it was first seen in, as brightness
    footprint: np.ndarray  # where its text is, and around it
    first_seen: float
    appearances: int = 0


class RegionTracker:
    """Follows one message area through frames taken at increasing times (seconds on any clock).

    Every frame either shows a message or is blank; a message is on show from the frame that brings it until a
    frame shows another message or none. `messages` are the distinct ones in the order they were first seen and
    `sequence` the order they were shown in, which repeats once the area cycles."""

    def __init__(self, started: float = 0.0) -> None:
        self.messages: list[ShownMessage] = []
        self.sequence: list[int] = []
        self.times: list[float] = []  # when each message of `sequence` appeared
        self.showing: int | None = None  # the message on show, or None while blank
        self.changed_at = started  # when what is on show last changed
        self.closed = False  # a message came round again: the cycle has been seen whole

    def add(self, at: float, image: Image.Image) -> ShownMessage | None:
        """Takes the next frame. Returns the message if it is one this area has not shown before."""
        mask = text_mask(image)
        if int(np.count_nonzero(mask)) < MIN_TEXT_PIXELS:
            self._show(None, at)
            return None
        luma = np.asarray(image.convert("L")).astype(np.int16)
        footprint = _grow(mask, FOOTPRINT_RADIUS)
        message = self._find(luma, footprint)
        created = None
        if message is None:
            message = created = ShownMessage(len(self.messages), luma, footprint, at)
            self.messages.append(message)
        if self._show(message.index, at):
            message.appearances += 1
            self.sequence.append(message.index)
            self.times.append(at)
            if message.appearances > 1:
                self.closed = True
        return created

    def appearances_before(self, at: float) -> int:
        """How many messages appeared before `at`."""
        return sum(1 for time in self.times if time < at)

    def state(self, now: float, since: float | None, steady_for: float) -> CycleState | None:
        """How far the area's cycle is known. "closed": a message came round again. "steady": since `since` (the
        moment it is known to cycle if it is going to, e.g. the game going idle) what is on show has not changed
        for `steady_for` seconds, so it is one message or none. None: neither yet."""
        if self.closed:
            return "closed"
        if since is not None and now - max(self.changed_at, since) >= steady_for:
            return "steady"
        return None

    def _show(self, index: int | None, at: float) -> bool:
        """Puts `index` on show; True when that is a change."""
        if index == self.showing:
            return False
        self.showing = index
        self.changed_at = at
        return index is not None

    def _find(self, luma: np.ndarray, footprint: np.ndarray) -> ShownMessage | None:
        for message in reversed(self.messages):  # the one just shown is the likeliest
            if message.luma.shape != luma.shape:
                continue
            differs = np.abs(message.luma - luma) > DIFF_LUMA
            if not (differs & (message.footprint | footprint)).any():
                return message
        return None
