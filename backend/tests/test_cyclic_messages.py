"""Telling cyclic messages apart from frames of their area: synthetic frames (a dark area, and white text that switches
instantly, which is what FortuneOx's message lines do, measured) and the real crops of a 40-line win."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.utils.cyclic_messages import MIN_TEXT_PIXELS, RegionTracker

SIZE = (138, 10)
DARK = (40, 10, 50)
WHITE = (230, 230, 230)


YELLOW = (255, 220, 10)


def frame(
    message: int | None = None, *, speck: int = 0, sparkle: bool = False, size: tuple[int, int] = SIZE
) -> Image.Image:
    """The area showing message `message` (a white block of its own, 40 pixels), or nothing. `speck` adds that
    many stray text pixels, which is what a flicker of the animation behind it looks like, and `sparkle` a yellow
    effect, like the one a win draws across the message line, well away from where the text is."""
    image = Image.new("RGB", size, DARK)
    if sparkle:
        image.paste(YELLOW, (100, 2, 130, 9))
    if message is not None:
        left = 4 + 12 * message
        image.paste(WHITE, (left, 3, left + 10, 7))
    for x in range(speck):
        image.putpixel((100 + x, 0), WHITE)
    return image


def feed(tracker: RegionTracker, frames: list[Image.Image], *, start: float = 0.0, step: float = 0.3) -> list:
    return [tracker.add(start + index * step, image) for index, image in enumerate(frames)]


def test_a_blank_area_has_no_messages() -> None:
    tracker = RegionTracker()

    feed(tracker, [frame(), frame(), frame()])

    assert tracker.messages == []
    assert tracker.sequence == []
    assert tracker.showing is None
    assert not tracker.closed


def test_a_message_shown_over_several_frames_is_one_appearance() -> None:
    tracker = RegionTracker()

    created = feed(tracker, [frame(), frame(0), frame(0), frame(0), frame()])

    assert [m.index if m else None for m in created] == [None, 0, None, None, None]
    assert [m.appearances for m in tracker.messages] == [1]
    assert tracker.sequence == [0]
    assert tracker.messages[0].first_seen == 0.3


def test_a_cycle_is_closed_when_a_message_comes_round_again() -> None:
    tracker = RegionTracker()

    feed(tracker, [frame(0), frame(), frame(1), frame(), frame(2), frame(), frame(0)])

    assert tracker.sequence == [0, 1, 2, 0]
    assert [m.appearances for m in tracker.messages] == [2, 1, 1]
    assert tracker.closed


def test_a_cycle_that_has_not_come_round_is_not_closed() -> None:
    tracker = RegionTracker()

    feed(tracker, [frame(0), frame(), frame(1), frame(), frame(2)])

    assert tracker.sequence == [0, 1, 2]
    assert not tracker.closed


def test_messages_that_follow_each_other_without_a_blank_are_each_an_appearance() -> None:
    tracker = RegionTracker()

    # The payline messages: "Line 1 Pays 2" gives way to "Line 2 Pays 2" at once.
    feed(tracker, [frame(0), frame(0), frame(1), frame(1), frame(0)])

    assert tracker.sequence == [0, 1, 0]
    assert tracker.closed


def test_the_same_message_after_a_blank_is_shown_again() -> None:
    tracker = RegionTracker()

    feed(tracker, [frame(0), frame(), frame(0)])

    assert tracker.sequence == [0, 0]
    assert tracker.closed


def test_a_few_stray_bright_pixels_are_not_a_message() -> None:
    tracker = RegionTracker()

    feed(tracker, [frame(speck=MIN_TEXT_PIXELS - 1), frame(speck=MIN_TEXT_PIXELS - 1)])

    assert tracker.messages == []
    assert tracker.showing is None


def test_a_tiny_shift_in_the_shading_behind_a_message_is_the_same_message() -> None:
    tracker = RegionTracker()
    shifted = frame(0)
    shifted.paste((46, 16, 56), (0, 0, 138, 3))  # 6 levels lighter above the text; the text is unchanged

    feed(tracker, [frame(0), shifted, frame(0)])

    assert [m.appearances for m in tracker.messages] == [1]


def test_a_faint_difference_makes_a_different_message() -> None:
    # What merged three lines of a live 40-line win into earlier ones: at a 766 px capture "Line 19 Pays 80" and
    # "Line 16 Pays 80" differ by a few pixels, some of them 33 levels brighter and none bright enough to be text.
    tracker = RegionTracker()
    other = frame(0)
    for x in range(6, 10):  # just below the text
        other.putpixel((x, 7), (73, 43, 83))

    feed(tracker, [frame(0), other])

    assert len(tracker.messages) == 2


def test_a_sparkle_in_a_blank_area_is_not_a_message() -> None:
    tracker = RegionTracker()

    feed(tracker, [frame(sparkle=True), frame(sparkle=True), frame()])

    assert tracker.messages == []
    assert tracker.showing is None


def test_a_sparkle_away_from_the_text_does_not_make_a_message_a_different_one() -> None:
    tracker = RegionTracker()

    feed(tracker, [frame(0), frame(0, sparkle=True), frame(0), frame(1), frame(0, sparkle=True)])

    assert len(tracker.messages) == 2
    assert tracker.sequence == [0, 1, 0]


def test_messages_a_couple_of_pixels_apart_are_different_messages() -> None:
    # Strict on purpose: "Line 36 Pays 10" and "Line 38 Pays 10" differ by about that much, and merging them
    # would lose a message.
    tracker = RegionTracker()
    other = frame(0)
    other.putpixel((50, 8), WHITE)
    other.putpixel((51, 8), WHITE)

    feed(tracker, [frame(0), other])

    assert len(tracker.messages) == 2


def test_messages_that_differ_by_a_glyph_are_different_messages() -> None:
    tracker = RegionTracker()
    one, other = frame(0), frame(0)
    other.paste(WHITE, (4, 8, 14, 9))  # 10 more text pixels: "Line 1 Pays 2" against "Line 2 Pays 2"

    feed(tracker, [one, other])

    assert len(tracker.messages) == 2


def test_areas_of_another_size_do_not_match() -> None:
    tracker = RegionTracker()

    feed(tracker, [frame(0), frame(0, size=(140, 10))])

    assert len(tracker.messages) == 2


def test_state_is_closed_whatever_the_time() -> None:
    tracker = RegionTracker()
    feed(tracker, [frame(0), frame(), frame(0)])

    assert tracker.state(now=0.6, since=None, steady_for=5) == "closed"


def test_state_is_unknown_until_the_game_is_idle_however_long_nothing_changes() -> None:
    tracker = RegionTracker()
    feed(tracker, [frame(0)])  # "Line 1 Pays 2" held while the win waits to be collected

    assert tracker.state(now=60, since=None, steady_for=5) is None


def test_state_is_steady_when_nothing_changed_for_long_enough_after_the_game_went_idle() -> None:
    tracker = RegionTracker()
    feed(tracker, [frame(0)])  # changed at 0, long before the game went idle at 50

    assert tracker.state(now=52, since=50, steady_for=5) is None
    assert tracker.state(now=55, since=50, steady_for=5) == "steady"


def test_a_change_after_the_game_went_idle_restarts_the_wait() -> None:
    tracker = RegionTracker()
    feed(tracker, [frame(0)])
    tracker.add(52.0, frame(1))  # the payline cycling has begun

    assert tracker.state(now=56, since=50, steady_for=5) is None
    assert tracker.state(now=57, since=50, steady_for=5) == "steady"


def test_an_area_that_stays_blank_is_steady() -> None:
    tracker = RegionTracker()
    feed(tracker, [frame(), frame()])

    assert tracker.state(now=5.0, since=0.0, steady_for=5) == "steady"


def line_message(text: str, size: int) -> Image.Image:
    """`text` rendered at font size `size` in an area as wide as a game's message line is at that size."""
    image = Image.new("RGB", (size * 19, size + 7), DARK)
    ImageDraw.Draw(image).text((4, 1), text, font=ImageFont.load_default(size), fill=(235, 235, 235))
    return image


@pytest.mark.parametrize("size", [8, 10, 16, 32])
def test_every_message_of_a_win_on_forty_lines_is_told_apart_and_recognised_again(size: int) -> None:
    # The hardest case for a cycle: 80 messages that differ by a digit or two ("Line 36 Pays 10", "Line 38 Pays 10"),
    # shown twice over with a blank between, as the upper line does when a win pays on 40 lines.
    texts = [f"Line {line} Pays {pays}" for line in range(1, 41) for pays in (5, 10)]
    blank = frame(size=line_message("", size).size)
    tracker = RegionTracker()
    frames = []
    for _ in range(2):
        for text in texts:
            frames += [line_message(text, size), line_message(text, size), blank]

    created = [m for m in feed(tracker, frames) if m is not None]

    assert len(created) == len(texts)
    assert tracker.sequence == list(range(len(texts))) * 2
    assert [m.appearances for m in tracker.messages] == [2] * len(texts)
    assert tracker.closed


FORTY_LINES = Path(__file__).parent / "fixtures" / "cyclic" / "forty_lines"


def test_the_forty_lines_of_a_real_win_are_all_told_apart() -> None:
    # The crops of the upper message line of a live FortuneOx win on 40 lines, one of each distinct message it
    # showed, at a 766 px capture (138x11 px). The two most alike differ by 33 levels; with the old limit of 40
    # three of them were taken for earlier ones and only 37 were found.
    images = [Image.open(path).convert("RGB") for path in sorted(FORTY_LINES.glob("line_*.png"))]
    assert len(images) == 40
    blank = Image.new("RGB", images[0].size, DARK)
    tracker = RegionTracker()

    created = [m for m in feed(tracker, [f for _ in range(2) for image in images for f in (image, image, blank)]) if m]

    assert len(created) == 40
    assert tracker.sequence == list(range(40)) * 2
    assert tracker.closed


SPARKLE = Path(__file__).parent / "fixtures" / "cyclic" / "sparkle"


def test_a_win_sparkle_over_a_real_message_line_is_not_a_different_message() -> None:
    # Crops of a live win's upper line: "Game Pays 30", the same with the yellow sparkle the win draws across the
    # line, and "Line 1 Pays 10". The sparkle made a second message of the first, and so a repeat (a cycle that had
    # not come round) when the first was shown again.
    game_pays, sparkled, line = (
        Image.open(SPARKLE / name).convert("RGB") for name in ("game_pays.png", "game_pays_with_sparkle.png", "line.png")
    )
    tracker = RegionTracker()

    feed(tracker, [game_pays, sparkled, line])

    assert len(tracker.messages) == 2
    assert tracker.sequence == [0, 1]
    assert not tracker.closed
