"""How PaddleOcrEngine shares its worker processes ("lanes") between the images being read. The processes are
real (spawned, talking over pipes) but their models are stubs (tests/ocr_stub_lane.py), so no Paddle loads."""

import multiprocessing
import os
import threading
import time

import pytest
from PIL import Image

from app.utils import ocr_engine
from app.utils.ocr_engine import OcrEngineError, PaddleOcrEngine, TextBox
from tests.ocr_stub_lane import DIES, FAILS, HANGS, stub_lane

OK = Image.new("RGB", (40, 10), (10, 20, 30))


def solid(colour: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (40, 10), colour)


def make_engine(lanes: int) -> PaddleOcrEngine:
    return PaddleOcrEngine(lanes=lanes, target=stub_lane)


@pytest.fixture
def engines():
    """Engines made by a test, closed after it so no process outlives it."""
    made: list[PaddleOcrEngine] = []

    def make(lanes: int) -> PaddleOcrEngine:
        made.append(make_engine(lanes))
        return made[-1]

    yield make
    for engine in made:
        engine.close()


def span(engine: PaddleOcrEngine, image: Image.Image = OK) -> tuple[int, float, float]:
    """(process id, started, finished) of one read."""
    pid, started, finished, _size = engine.read_line(image).text.split(":")
    return int(pid), float(started), float(finished)


def read_together(engine: PaddleOcrEngine, count: int) -> list[tuple[int, float, float]]:
    spans: list[tuple[int, float, float]] = []
    threads = [threading.Thread(target=lambda: spans.append(span(engine))) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return spans


def overlap(a: tuple[int, float, float], b: tuple[int, float, float]) -> bool:
    return a[1] < b[2] and b[1] < a[2]


def test_a_line_is_read_in_another_process_and_its_text_trimmed(engines) -> None:
    engine = engines(1)

    line = engine.read_line(OK)

    assert line.score == 0.9
    assert int(line.text.split(":")[0]) != os.getpid()  # not in the server's own process


def test_a_meter_crop_is_scaled_up_to_about_130_px_and_its_boxes_placed_in_the_original(engines) -> None:
    # The stub detector finds one piece of text covering (nearly) the whole image it is given, and the
    # recognizer says how big a crop it was shown. 44 px tall is scaled x3: 132x150 was read from a 50x44 image.
    [box] = engines(1).read_boxes(Image.new("RGB", (50, 44), (10, 20, 30)))

    assert box == TextBox(text="132x150", score=0.95, left=0, top=0, right=50, bottom=44)


@pytest.mark.parametrize(
    ("height", "seen"), [(44, 132), (60, 180), (69, 138), (70, 70), (74, 74), (77, 77), (200, 200)]
)
def test_only_a_crop_under_70_px_is_scaled_up_and_then_to_about_130_px(engines, height, seen) -> None:
    [box] = engines(1).read_boxes(Image.new("RGB", (60, height), (10, 20, 30)))

    assert box.text.split("x")[0] == str(seen)


def test_a_meter_crop_is_never_scaled_up_more_than_four_times(engines) -> None:
    [box] = engines(1).read_boxes(Image.new("RGB", (60, 10), (10, 20, 30)))

    assert box.text == "40x240"


def test_a_message_line_is_padded_and_scaled_up_three_times(engines) -> None:
    line = engines(1).read_line(Image.new("RGB", (138, 10), (10, 20, 30)))

    assert line.text.endswith(":54x438")  # (10 + 2x4) x 3 by (138 + 2x4) x 3


def test_a_box_the_fast_recognizer_doubts_gets_a_second_opinion_and_the_surer_read_wins(engines, monkeypatch) -> None:
    monkeypatch.setenv("OCR_STUB_MOBILE_SCORE", "0.6")  # below 0.9; the line recognizer's stub says 0.9
    [box] = engines(1).read_boxes(Image.new("RGB", (60, 130), (10, 20, 30)))

    assert box.score == 0.9 and box.text.count(":") == 3  # the line recognizer's answer, not the fast one's


def test_a_confident_box_is_not_read_twice(engines) -> None:
    [box] = engines(1).read_boxes(Image.new("RGB", (60, 130), (10, 20, 30)))

    assert (box.text, box.score) == ("130x60", 0.95)


def test_reads_at_the_same_time_are_read_by_different_processes(engines, monkeypatch) -> None:
    monkeypatch.setenv("OCR_STUB_SECONDS", "0.4")
    engine = engines(2)
    span(engine)  # both lanes load in the background; the first read waits for one

    spans = read_together(engine, 2)

    assert len({pid for pid, _, _ in spans}) == 2
    assert overlap(spans[0], spans[1])


def test_one_lane_reads_one_image_at_a_time(engines, monkeypatch) -> None:
    monkeypatch.setenv("OCR_STUB_SECONDS", "0.2")
    engine = engines(1)

    spans = read_together(engine, 3)

    assert len({pid for pid, _, _ in spans}) == 1
    assert not any(overlap(a, b) for i, a in enumerate(spans) for b in spans[i + 1 :])


def test_a_read_that_fails_reports_it_and_leaves_the_lane_working(engines) -> None:
    engine = engines(1)
    first = span(engine)[0]

    with pytest.raises(OcrEngineError, match="PaddleOCR failed to read the image: a kernel that does not exist"):
        engine.read_line(solid(FAILS))

    assert span(engine)[0] == first  # the same process: it was not thrown away


def test_a_lane_that_dies_is_replaced(engines) -> None:
    engine = engines(1)
    first = span(engine)[0]

    with pytest.raises(OcrEngineError, match="stopped unexpectedly"):
        engine.read_line(solid(DIES))

    assert span(engine)[0] != first  # a new process, loaded on demand


def test_a_lane_that_hangs_is_killed_and_replaced(engines, monkeypatch) -> None:
    monkeypatch.setattr(ocr_engine, "_READ_TIMEOUT", 1.0)
    engine = engines(1)
    first = span(engine)[0]

    with pytest.raises(OcrEngineError, match="did not answer within 1s"):
        engine.read_line(solid(HANGS))

    assert span(engine)[0] != first


def test_models_that_cannot_load_are_reported_and_the_next_read_tries_again(engines, monkeypatch) -> None:
    monkeypatch.setenv("OCR_STUB_FAIL", "load")
    engine = engines(1)

    with pytest.raises(OcrEngineError, match="Could not load the OCR models: no network"):
        engine.read_line(OK)
    assert not engine.ready

    monkeypatch.delenv("OCR_STUB_FAIL")  # the network is back; the replacement process starts afresh
    assert span(engine)[0]
    assert engine.ready


def test_the_engine_is_ready_once_a_lane_has_loaded(engines) -> None:
    engine = engines(2)
    assert not engine.ready

    engine.preload()
    deadline = time.monotonic() + 30
    while not engine.ready and time.monotonic() < deadline:
        time.sleep(0.05)

    assert engine.ready


def test_closing_ends_the_processes(engines) -> None:
    engine = engines(2)
    span(engine)
    assert multiprocessing.active_children()

    engine.close()

    assert multiprocessing.active_children() == []
    assert not engine.ready


def test_the_lane_count_is_at_least_one() -> None:
    assert PaddleOcrEngine(lanes=0).lanes == 1
    assert PaddleOcrEngine(lanes=3).lanes == 3
