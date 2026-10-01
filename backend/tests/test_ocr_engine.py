"""The real PaddleOCR models on real crops of the game. Loading them takes about a minute, so this only runs
when asked: RUN_OCR_ENGINE_TESTS=1 pytest tests/test_ocr_engine.py"""

import os
from difflib import SequenceMatcher
from pathlib import Path

import pytest
from PIL import Image

from app.utils.ocr_engine import PaddleOcrEngine
from app.utils.ocr_parse import parse_meter

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_OCR_ENGINE_TESTS") != "1", reason="loads the real OCR models; set RUN_OCR_ENGINE_TESTS=1"
)

FIXTURES = Path(__file__).parent / "fixtures" / "ocr"


@pytest.fixture(scope="module")
def engine():
    engine = PaddleOcrEngine(lanes=1)
    yield engine
    engine.close()


def meter(engine: PaddleOcrEngine, name: str, expected: str):
    with Image.open(FIXTURES / name) as image:
        return parse_meter(engine.read_boxes(image), expected)


def line(engine: PaddleOcrEngine, name: str):
    with Image.open(FIXTURES / name) as image:
        return engine.read_line(image)


def test_a_credit_meter_with_no_win(engine) -> None:
    parsed = meter(engine, "meter_credits_no_win.png", "credits")

    assert (parsed.balance.value, parsed.bet.value, parsed.win.value) == (99720.0, 88.0, None)
    assert parsed.issues == []


def test_a_cash_meter_with_a_win(engine) -> None:
    parsed = meter(engine, "meter_cash_win.png", "cash")

    assert (parsed.balance.value, parsed.win.value, parsed.bet.value) == (1039.55, 1.3, 0.88)
    assert parsed.balance.text == "$1,039.55"
    assert parsed.issues == []


def test_a_cash_meter_with_its_labels_left_of_the_amounts(engine) -> None:
    parsed = meter(engine, "meter_huff_cash_win.png", "cash")  # HuffNPuffHighRise

    assert (parsed.balance.value, parsed.win.value, parsed.bet.value) == (998.2, 3.0, 2.0)
    assert parsed.issues == []


@pytest.mark.parametrize(
    ("name", "cash"), [("meter_cash_no_win.png", 1040.01), ("meter_cash_no_win_clipped.png", 1039.13)]
)
def test_a_cash_meter_with_no_win(engine, name: str, cash: float) -> None:
    parsed = meter(engine, name, "cash")

    assert (parsed.balance.value, parsed.win.value, parsed.bet.value) == (cash, None, 0.88)
    assert parsed.issues == []


@pytest.mark.parametrize(
    ("name", "text"), [("line_pays.png", "Line 40 Pays 10"), ("line_game_pays.png", "Game Pays 255")]
)
def test_a_cyclic_message(engine, name: str, text: str) -> None:
    result = line(engine, name)

    assert result.text == text
    assert result.score > 0.9


def test_a_blank_message_area_reads_as_nothing(engine) -> None:
    assert line(engine, "line_blank.png").text == ""


def test_an_image_with_no_text_has_no_boxes(engine) -> None:
    assert engine.read_boxes(Image.new("RGB", (300, 80), (20, 20, 20))) == []


# A smaller window is captured at 766 px wide instead of 1080, where the meter's labels are ~9 px tall. These are
# the crops that read as "No CASH label was read. No BET label was read." before crops were scaled up.


@pytest.mark.parametrize(
    ("name", "expected", "values"),
    [
        ("meter_small_credits_no_win.png", "credits", (103867.0, None, 88.0)),
        ("meter_small_cash_no_win.png", "cash", (1038.67, None, 0.88)),
        ("meter_small_cash_win.png", "cash", (20614.0, 4.0, 20.0)),
    ],
)
def test_a_meter_captured_small_is_read_in_full(engine, name: str, expected: str, values: tuple) -> None:
    parsed = meter(engine, name, expected)

    assert (parsed.balance.value, parsed.win.value, parsed.bet.value) == values
    assert parsed.issues == []


def test_a_message_line_with_a_widely_spaced_font_reads_as_one_word(engine) -> None:
    assert line(engine, "line_play_credits.png").text == "Play 880 Credits"  # not "Play 880 Cred its"


def test_the_tiniest_message_area_reads_blank_when_blank_and_close_to_the_words_when_not(engine) -> None:
    assert line(engine, "line_tiny_blank.png").text == ""
    # 138x10 px, glyphs ~7 px tall: the best that is read is "Qama Over" or "Qama Ouer", not "Game Over".
    read = line(engine, "line_tiny_game_over.png").text
    assert SequenceMatcher(None, read.lower(), "game over").ratio() >= 0.6, read
