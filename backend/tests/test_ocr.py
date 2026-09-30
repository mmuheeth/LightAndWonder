"""The OCR tab's API: capturing the meter and cyclic messages (toggling the meter through GAF), and reading them.
OBS is a fake that hands out a different screenshot per request, GAF is the real service on the fake NRobot,
and the OCR engine is a fake that answers by crop colour."""

import asyncio
import copy
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.dependencies import BACKEND_DIR, get_obs_controller, get_ocr_controller
from app.controllers.obs_controller import ObsController
from app.controllers.ocr_controller import OcrController
from app.main import app
from app.schemas.game_context import GameContextUpdate, GameMode
from app.services import gaf_service, ocr_service
from app.services.game_context_service import GameContextService
from app.services.gaf_service import GafService
from app.services.obs_window_service import ObsWindowService
from app.services.ocr_service import OcrService
from app.utils import game_config as game_settings
from app.utils.nrobot import NRobot
from app.utils.ocr_engine import OcrEngineError, TextLine
from tests.fake_gaf import FakeGaf
from tests.fake_obs import FakeObs
from tests.ocr_helpers import CASH_NO_WIN, CASH_WITH_WIN, CREDITS_NO_WIN, FakeOcrEngine

URL = "/api/v1/ocr"
GAME = "FortuneOx"  # the real config, so GAF has the game's actions; only its ROIs are replaced
SIZE = (1000, 1000)
ROIS = {
    "cash_meter": [0.0, 0.8, 1.0, 0.9],
    "cyclic_message": [0.0, 0.5, 0.2, 0.6],
    "cyclic_message_2": [0.0, 0.6, 0.2, 0.7],
}
# Where each region is in a screenshot, to paint it a colour the fake engine can recognise.
REGION_PIXELS = {name: (0, round(top * SIZE[1]), round(right * SIZE[0]), round(bottom * SIZE[1]))
                 for name, (_, top, right, bottom) in ROIS.items()}

CASH_METER, CREDIT_METER = (200, 10, 10), (100, 10, 10)
MESSAGE_1, MESSAGE_2 = (10, 200, 10), (10, 10, 200)
OTHER_MESSAGE_1, OTHER_MESSAGE_2 = (50, 200, 10), (10, 50, 200)


def screenshot(meter: tuple[int, int, int], message_1: tuple[int, int, int], message_2: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", SIZE, (90, 90, 90))
    for name, color in (("cash_meter", meter), ("cyclic_message", message_1), ("cyclic_message_2", message_2)):
        image.paste(color, REGION_PIXELS[name])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# The game showing cash, and the same game showing credits a moment later with its messages elsewhere in their cycle.
SHOWING_CASH = screenshot(CASH_METER, MESSAGE_1, MESSAGE_2)
SHOWING_CREDITS = screenshot(CREDIT_METER, OTHER_MESSAGE_1, OTHER_MESSAGE_2)


class SequencedObs(FakeObs):
    """Every screenshot is the next of `images`; `after_shot` runs after the nth one (1-based) is handed out."""

    def __init__(self, images: list[bytes]) -> None:
        super().__init__()
        self.images = list(images)
        self.shots = 0
        self.after_shot: dict[int, object] = {}

    def handle(self, request_type: str, data: dict | None) -> dict:
        if request_type in ("SaveSourceScreenshot", "GetSourceScreenshot"):
            self.shots += 1
            self.image = self.images[min(self.shots, len(self.images)) - 1]
        result = super().handle(request_type, data)
        if request_type in ("SaveSourceScreenshot", "GetSourceScreenshot") and (hook := self.after_shot.get(self.shots)):
            hook()
        return result


@pytest.fixture
def rois(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    """The ROIs of each game the tests use, by game; change them before extracting."""
    real = game_settings.load_game_config
    by_game = {GAME: dict(ROIS), "HuffNPuffHighRise": {"cash_meter": ROIS["cash_meter"], "cyclic_message": [], "cyclic_message_2": []}}

    def load(game: str):
        config = copy.deepcopy(real(game))
        if config is not None and game in by_game:
            config[GameMode.SIMULATOR.value]["roi"] = by_game[game]
        return config

    monkeypatch.setattr(game_settings, "load_game_config", load)
    return by_game


@pytest.fixture(autouse=True)
def fast_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr_service, "_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(gaf_service, "_POLL_INTERVAL", 0.001)
    monkeypatch.setattr(gaf_service, "_METER_TIMEOUT", 0.1)


@pytest.fixture
def engine() -> FakeOcrEngine:
    return FakeOcrEngine(
        meters={CASH_METER: CASH_WITH_WIN, CREDIT_METER: CREDITS_NO_WIN},
        lines={MESSAGE_1: TextLine("Line 14 Pays 10", 0.998), OTHER_MESSAGE_1: TextLine("Game Over", 0.97)},
    )


@pytest.fixture
def ocr(
    tmp_path: Path, rois, engine, config_file: Path, captures_dir: Path, window_file: Path
) -> SimpleNamespace:
    from tests.obs_helpers import make_service

    obs = SequencedObs([SHOWING_CASH, SHOWING_CREDITS])
    obs_service = make_service(obs, captures_dir, config_file)
    asyncio.run(obs_service.connect())

    fake_gaf = FakeGaf()
    context = GameContextService(state_file=tmp_path / "game_context.json")
    context.update_context(GameContextUpdate(game=GAME, mode=GameMode.SIMULATOR))
    gaf = GafService(
        nrobot=NRobot(fake_gaf.url, timeout=5),
        probe_nrobot=NRobot(fake_gaf.url, timeout=0.3),
        game_context=context,
        base_dir=BACKEND_DIR,
        settle_timeout=1.0,
        connect_attempts=3,
        connect_retry_delay=0.01,
    )
    service = OcrService(obs=obs_service, gaf=gaf, game_context=context, engine=engine, captures_dir=captures_dir)
    window_service = ObsWindowService(obs=obs_service, state_file=window_file)
    app.dependency_overrides[get_ocr_controller] = lambda: OcrController(service)
    app.dependency_overrides[get_obs_controller] = lambda: ObsController(obs_service, window_service)
    yield SimpleNamespace(obs=obs, gaf=gaf, fake_gaf=fake_gaf, service=service, client=TestClient(app))
    app.dependency_overrides.clear()
    fake_gaf.close()


def connect_gaf(ocr) -> None:
    asyncio.run(ocr.gaf.connect(GAME, GameMode.SIMULATOR))


def extract(ocr, **params):
    return ocr.client.post(f"{URL}/records", params={"game": GAME, **params})


def data(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["data"]


def crop_color(ocr, record: dict, name: str) -> tuple[int, int, int]:
    crop = next(crop for crop in record["crops"] if crop["name"] == name)
    response = ocr.client.get(f"/api/v1{crop['url']}")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    return Image.open(io.BytesIO(response.content)).convert("RGB").getpixel((0, 0))


def read(ocr, record: dict):
    return ocr.client.post(f"{URL}/records/{record['id']}/read")


def toggles(ocr) -> int:
    return len(ocr.fake_gaf.keywords("TOGGLEMETERVALUE"))


# -------------------------------------------------------------------------------- extracting


def test_extract_captures_both_meters_and_the_messages(ocr) -> None:
    connect_gaf(ocr)

    record = data(extract(ocr))

    assert [crop["name"] for crop in record["crops"]] == ["credit_meter", "cash_meter", "cyclic_message", "cyclic_message_2"]
    assert crop_color(ocr, record, "cash_meter") == CASH_METER  # as found
    assert crop_color(ocr, record, "credit_meter") == CREDIT_METER  # after the toggle
    # The messages are cut from the first screenshot only.
    assert crop_color(ocr, record, "cyclic_message") == MESSAGE_1
    assert crop_color(ocr, record, "cyclic_message_2") == MESSAGE_2
    assert record["notes"] == [] and record["readings"] is None
    assert [crop["roi"] for crop in record["crops"]][1] == ROIS["cash_meter"]
    assert len(record["screenshots"]) == 2 and ocr.obs.shots == 2


def test_the_game_is_left_showing_the_meter_it_was_found_showing(ocr) -> None:
    connect_gaf(ocr)

    data(extract(ocr))

    assert toggles(ocr) == 2
    assert ocr.fake_gaf.credit_as_cash is True


def test_a_game_found_showing_credits_has_its_meters_named_the_other_way_round(ocr) -> None:
    connect_gaf(ocr)
    ocr.fake_gaf.credit_as_cash = False
    ocr.obs.images = [SHOWING_CREDITS, SHOWING_CASH]

    record = data(extract(ocr))

    assert crop_color(ocr, record, "credit_meter") == CREDIT_METER
    assert crop_color(ocr, record, "cash_meter") == CASH_METER
    # What the game showed first is where the messages come from, here the second screenshot's.
    assert crop_color(ocr, record, "cyclic_message") == OTHER_MESSAGE_1
    assert ocr.fake_gaf.credit_as_cash is False


def test_without_a_gaf_session_only_the_meter_on_show_is_captured(ocr) -> None:
    record = data(extract(ocr))

    assert [crop["name"] for crop in record["crops"]] == ["meter", "cyclic_message", "cyclic_message_2"]
    assert crop_color(ocr, record, "meter") == CASH_METER
    assert len(record["screenshots"]) == 1 and ocr.obs.shots == 1
    assert len(record["notes"]) == 1
    assert record["notes"][0].startswith("Only the meter the game was showing was captured")
    assert "Not connected" in record["notes"][0]
    assert toggles(ocr) == 0


def test_a_toggle_the_game_ignores_leaves_one_capture_and_changes_nothing(ocr) -> None:
    connect_gaf(ocr)
    ocr.fake_gaf.ignore_input = True

    record = data(extract(ocr))

    assert [crop["name"] for crop in record["crops"]][0] == "meter"
    assert "did not change" in record["notes"][0]
    assert toggles(ocr) == 1  # nothing was switched, so there is nothing to switch back
    assert ocr.obs.shots == 1


def test_a_game_with_no_toggle_action_or_cyclic_messages_captures_just_its_meter(ocr) -> None:
    record = data(ocr.client.post(f"{URL}/records", params={"game": "HuffNPuffHighRise"}))

    assert [crop["name"] for crop in record["crops"]] == ["meter"]
    assert record["notes"]


def test_the_meter_is_switched_back_even_when_the_second_screenshot_fails(ocr) -> None:
    connect_gaf(ocr)
    ocr.obs.after_shot[1] = lambda: ocr.obs.rejected.update(SaveSourceScreenshot="Cannot capture")

    response = extract(ocr)

    assert response.status_code >= 400
    assert toggles(ocr) == 2 and ocr.fake_gaf.credit_as_cash is True
    assert ocr.service.list_records(5) == []  # no half-made record is left behind


def test_a_meter_that_cannot_be_switched_back_is_a_note_and_not_an_error(ocr) -> None:
    connect_gaf(ocr)
    ocr.obs.after_shot[2] = lambda: setattr(ocr.fake_gaf, "ignore_input", True)  # the game stops listening

    record = data(extract(ocr))

    assert len(record["crops"]) == 4  # the captures are good
    assert len(record["notes"]) == 1
    assert record["notes"][0].startswith("The meter could not be switched back and was left as it is now")


def test_the_crops_are_read_at_once_up_to_the_lanes_the_engine_has(ocr, engine) -> None:
    connect_gaf(ocr)
    record = data(extract(ocr))  # 2 meters and 2 message lines
    engine.delay = 0.05
    engine.lanes = 2

    readings = data(read(ocr, record))["readings"]

    assert engine.max_active == 2
    assert readings["cash_meter"]["cash"]["value"] == 1039.55  # in parallel, each crop still got its own reading
    assert readings["credit_meter"]["credits"]["value"] == 99720.0
    assert readings["cyclic_message"]["text"] == "Line 14 Pays 10"


def test_one_lane_reads_one_crop_at_a_time(ocr, engine) -> None:
    connect_gaf(ocr)
    record = data(extract(ocr))
    engine.delay = 0.02

    data(read(ocr, record))

    assert engine.max_active == 1


def test_warming_up_starts_the_engine_loading(ocr, engine) -> None:
    assert engine.preloaded is False

    response = ocr.client.post(f"{URL}/engine/warmup")

    assert data(response) == {"ready": True}  # the fake is ready as soon as it is told to load
    assert engine.preloaded is True


def test_the_engine_starts_loading_while_the_screenshots_are_taken(ocr, engine) -> None:
    data(extract(ocr))

    assert engine.preloaded


def test_a_game_without_a_meter_roi_is_refused_before_anything_is_touched(ocr, rois) -> None:
    del rois[GAME]["cash_meter"]
    connect_gaf(ocr)

    response = extract(ocr)

    assert response.status_code == 404
    assert ocr.obs.shots == 0 and toggles(ocr) == 0


def test_an_invalid_roi_is_refused_before_anything_is_touched(ocr, rois) -> None:
    rois[GAME]["cyclic_message"] = [0.5, 0.5, 0.1, 0.6]

    response = extract(ocr)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CONFIG_INVALID"
    assert ocr.obs.shots == 0


def test_an_unknown_game_is_not_found(ocr) -> None:
    assert ocr.client.post(f"{URL}/records", params={"game": "NoSuchGame"}).status_code == 404


# ----------------------------------------------------------------------------------- reading


def test_read_turns_the_crops_into_labelled_values(ocr) -> None:
    connect_gaf(ocr)
    record = data(extract(ocr))

    readings = data(read(ocr, record))["readings"]

    credits, cash = readings["credit_meter"], readings["cash_meter"]
    assert (credits["credits"]["value"], credits["win"]["value"], credits["bet"]["value"]) == (99720.0, None, 88.0)
    assert credits["win"]["text"] is None
    assert (cash["cash"]["text"], cash["cash"]["value"]) == ("$1,039.55", 1039.55)  # the currency is cleaned off
    assert (cash["win"]["value"], cash["bet"]["value"]) == (1.3, 0.88)
    assert credits["issues"] == [] and cash["issues"] == []
    assert readings["cyclic_message"] == {"text": "Line 14 Pays 10", "confidence": 99.8}
    # Nothing was showing in the second message area: blank, not a guess.
    assert readings["cyclic_message_2"] == {"text": "", "confidence": None}
    assert readings["issues"] == [] and readings["seconds"] >= 0


def test_a_reading_is_kept_with_its_record(ocr) -> None:
    connect_gaf(ocr)
    record = data(extract(ocr))
    data(read(ocr, record))

    [listed] = data(ocr.client.get(f"{URL}/records"))

    assert listed["id"] == record["id"]
    assert listed["readings"]["cash_meter"]["cash"]["value"] == 1039.55


def test_reading_again_replaces_the_reading(ocr, engine) -> None:
    connect_gaf(ocr)
    record = data(extract(ocr))
    data(read(ocr, record))
    engine.meters[CASH_METER] = CASH_NO_WIN

    readings = data(read(ocr, record))["readings"]

    assert readings["cash_meter"]["cash"]["value"] == 1039.13
    assert readings["cash_meter"]["win"]["value"] is None


def test_a_meter_of_unknown_mode_is_told_by_its_labels(ocr) -> None:
    record = data(extract(ocr))  # no GAF: one crop, named "meter"

    readings = data(read(ocr, record))["readings"]

    assert readings["cash_meter"]["cash"]["value"] == 1039.55
    assert readings["credit_meter"] is None


def test_a_meter_of_unknown_mode_showing_credits_is_read_as_the_credit_meter(ocr) -> None:
    ocr.obs.images = [SHOWING_CREDITS]
    record = data(extract(ocr))

    readings = data(read(ocr, record))["readings"]

    assert readings["credit_meter"]["credits"]["value"] == 99720.0
    assert readings["credit_meter"]["bet"]["value"] == 88.0
    assert readings["cash_meter"] is None


def test_a_meter_of_unknown_mode_that_cannot_be_identified_is_reported(ocr, engine) -> None:
    record = data(extract(ocr))
    engine.meters[CASH_METER] = []

    readings = data(read(ocr, record))["readings"]

    assert readings["cash_meter"] is None and readings["credit_meter"] is None
    assert readings["issues"][0].startswith("Neither a CASH nor a CREDITS label was read")


def test_a_crop_that_is_of_the_other_meter_is_reported_on_the_meter_it_was_meant_to_be(ocr, engine) -> None:
    connect_gaf(ocr)
    record = data(extract(ocr))
    engine.meters[CASH_METER] = CREDITS_NO_WIN  # the toggle was a no-op after all

    readings = data(read(ocr, record))["readings"]

    assert readings["cash_meter"]["cash"]["value"] is None
    assert readings["cash_meter"]["issues"] == ["The crop shows the credits meter, not the cash one."]


def test_a_game_without_message_areas_has_no_message_readings(ocr) -> None:
    record = data(ocr.client.post(f"{URL}/records", params={"game": "HuffNPuffHighRise"}))

    readings = data(read(ocr, record))["readings"]

    assert readings["cyclic_message"] is None and readings["cyclic_message_2"] is None


def test_an_engine_that_cannot_load_is_reported_as_unavailable(ocr, engine) -> None:
    record = data(extract(ocr))
    engine.failure = OcrEngineError("PaddleOCR is not installed")

    response = read(ocr, record)

    assert response.status_code == 503
    assert response.json()["error"] == {"code": "OCR_UNAVAILABLE", "message": "PaddleOCR is not installed", "details": None}
    assert data(ocr.client.get(f"{URL}/records"))[0]["readings"] is None  # nothing half-read is kept


@pytest.mark.parametrize("record_id", ["ocr_20200101_000000_000_abcdef", "../x", "roi_20260930_160333_213_be2a19"])
def test_reading_a_record_that_does_not_exist_is_not_found(ocr, record_id: str) -> None:
    assert ocr.client.post(f"{URL}/records/{record_id}/read").status_code == 404


# ------------------------------------------------------------------------------ records/images


def test_records_come_newest_first_and_honour_the_limit(ocr) -> None:
    first = data(extract(ocr))
    second = data(extract(ocr))

    assert [r["id"] for r in data(ocr.client.get(f"{URL}/records", params={"limit": 5}))] == [second["id"], first["id"]]
    assert [r["id"] for r in data(ocr.client.get(f"{URL}/records"))] == [second["id"]]


def test_there_are_no_records_before_the_first_extraction(ocr) -> None:
    assert data(ocr.client.get(f"{URL}/records")) == []


def test_only_the_images_of_a_record_can_be_fetched(ocr) -> None:
    record = data(extract(ocr))
    base = f"{URL}/records/{record['id']}/images"

    assert ocr.client.get(f"{base}/meter.png").status_code == 200
    assert ocr.client.get(f"{base}/record.json").status_code == 404
    assert ocr.client.get(f"{base}/nothing.png").status_code == 404
    assert ocr.client.get(f"{URL}/records/ocr_20200101_000000_000_abcdef/images/meter.png").status_code == 404
    assert ocr.client.get(f"{URL}/records/..%2F..%2Fdata/images/meter.png").status_code == 404
