import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.dependencies import get_obs_controller, get_roi_controller, get_symbol_controller
from app.controllers.obs_controller import ObsController
from app.controllers.roi_controller import RoiController
from app.controllers.symbol_controller import SymbolController
from app.main import app
from app.services.game_context_service import GameContextService
from app.services.obs_window_service import ObsWindowService
from app.services.roi_service import RoiService
from app.services.symbol_service import SymbolService
from app.utils import symbol_classifier
from tests.fake_obs import FakeObs
from tests.test_roi import (  # noqa: F401  (fixtures and helpers of the ROI tests, which this builds on)
    GAME,
    connected,
    fake_games,
    game_context,
    game_screenshot,
    make_config,
    png,
    roi_service,
)

URL = "/api/v1/symbols"
NAMES = {"S00": "Ox", "S01": "Pisces"}


class FakeClassifier:
    """Names a tile by the colour the test screenshot gives its grid position: row 1, reel 2 is S12."""

    def __init__(self) -> None:
        self.classes = ["S00"]

    def classify(self, images: list[Image.Image]) -> list[symbol_classifier.Prediction]:
        predictions = []
        for image in images:
            red, green, _ = image.getpixel((image.width // 2, image.height // 2))
            column, row = (red - 10) // 40, (green - 10) // 80
            predictions.append(
                symbol_classifier.Prediction(code=f"S{row}{column}", confidence=90.0 + column + row / 10)
            )
        return predictions


@pytest.fixture
def games_dir(tmp_path: Path) -> Path:
    for code in ("AA", "BB"):
        folder = tmp_path / "games" / GAME / "symbols" / code
        folder.mkdir(parents=True)
        for index in range(3):
            Image.new("RGBA", (8, 8)).save(folder / f"{code}_{index}.png")
    return tmp_path / "games"


@pytest.fixture
def trainer(monkeypatch: pytest.MonkeyPatch) -> "FakeTrainer":
    fake = FakeTrainer()
    monkeypatch.setattr(symbol_classifier, "train", fake.train)
    monkeypatch.setattr(symbol_classifier.SymbolClassifier, "load", classmethod(lambda cls, path: FakeClassifier()))
    return fake


class FakeTrainer:
    """Stands in for the network: `train` writes the weights, then waits for `release` so that a test can
    look at the service while it is training."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.release.set()
        self.error: Exception | None = None
        self.calls: list[list[str]] = []

    def train(self, artwork, weights_path, *, on_progress=None, **_):
        self.calls.append(sorted(artwork))
        if on_progress is not None:
            on_progress(1, 2, 0.5)
        assert self.release.wait(timeout=10)
        if self.error is not None:
            raise self.error
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        weights_path.write_bytes(b"weights")
        return symbol_classifier.TrainingReport(
            classes=sorted(artwork),
            image_count=sum(len(v) for v in artwork.values()),
            epochs=2,
            accuracy=87.5,
            floor=80.0,
            per_class={"AA": 80.0},
        )


@pytest.fixture
def symbol_service(
    roi_service: RoiService, game_context: GameContextService, games_dir: Path, tmp_path: Path
) -> SymbolService:
    return SymbolService(
        roi=roi_service,
        game_context=game_context,
        games_dir=games_dir,
        models_dir=tmp_path / "models",
        readings_dir=tmp_path / "readings",
        min_confidence=90.0,
    )


@pytest.fixture
def symbol_client(symbol_service: SymbolService, window_service: ObsWindowService, fake_obs: FakeObs):
    fake_obs.image = png(game_screenshot())
    app.dependency_overrides[get_symbol_controller] = lambda: SymbolController(symbol_service)
    app.dependency_overrides[get_roi_controller] = lambda: RoiController(symbol_service._roi)
    app.dependency_overrides[get_obs_controller] = lambda: ObsController(symbol_service._roi._obs, window_service)
    yield TestClient(app)
    app.dependency_overrides.clear()


def model_status(client: TestClient) -> dict:
    response = client.get(f"{URL}/model", params={"game": GAME})
    assert response.status_code == 200
    return response.json()["data"]


def train(client: TestClient):
    return client.post(f"{URL}/model/train", params={"game": GAME})


def wait_for(client: TestClient, state: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = model_status(client)
        if status["state"] == state:
            return status
        time.sleep(0.02)
    pytest.fail(f"the model never became {state}: {model_status(client)}")


def identify(client: TestClient, **params):
    return client.post(f"{URL}/identify", params={"game": GAME, **params})


# -------------------------------------------------------------------------- the model


def test_a_game_without_a_model_is_untrained_and_reports_its_artwork(symbol_client: TestClient) -> None:
    status = model_status(symbol_client)

    assert status["state"] == "untrained"
    assert status["model"] is None and status["progress"] is None
    assert (status["dataset_classes"], status["dataset_images"]) == (2, 6)
    assert status["min_confidence"] == 90.0


def test_an_unknown_game_is_not_found(symbol_client: TestClient) -> None:
    assert symbol_client.get(f"{URL}/model", params={"game": "Nope"}).status_code == 404


def test_training_runs_in_the_background_and_leaves_a_ready_model(
    symbol_client: TestClient, trainer: FakeTrainer
) -> None:
    trainer.release.clear()

    started = train(symbol_client)

    assert started.status_code == 200
    assert started.json()["data"]["state"] == "training"
    training = wait_for(symbol_client, "training")
    assert training["progress"] == {"epoch": 1, "epochs": 2, "loss": 0.5}
    trainer.release.set()
    ready = wait_for(symbol_client, "ready")
    assert ready["progress"] is None and ready["error"] is None
    assert trainer.calls == [["AA", "BB"]]
    model = ready["model"]
    assert model["architecture"] == "ResNet34"
    assert model["classes"] == ["AA", "BB"]
    assert (model["image_count"], model["epochs"]) == (6, 2)
    assert (model["accuracy"], model["floor"]) == (87.5, 80.0)
    # Only AA had held-out images to check.
    assert model["unchecked"] == ["BB"]


def test_the_trained_model_outlives_the_service(
    symbol_client: TestClient, trainer: FakeTrainer, symbol_service: SymbolService, tmp_path: Path
) -> None:
    train(symbol_client)
    wait_for(symbol_client, "ready")

    fresh = SymbolService(
        roi=symbol_service._roi,
        game_context=symbol_service._game_context,
        games_dir=symbol_service._games_dir,
        models_dir=tmp_path / "models",
        readings_dir=tmp_path / "readings",
        min_confidence=90.0,
    )

    assert fresh.model_status(GAME).state == "ready"


def test_only_one_model_trains_at_a_time(symbol_client: TestClient, trainer: FakeTrainer) -> None:
    trainer.release.clear()
    train(symbol_client)

    response = train(symbol_client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRAINING_BUSY"
    trainer.release.set()
    wait_for(symbol_client, "ready")


def test_a_failed_training_is_reported_and_can_be_retried(
    symbol_client: TestClient, trainer: FakeTrainer
) -> None:
    trainer.error = symbol_classifier.SymbolTrainingError("Could not load the pretrained ResNet34 weights")
    train(symbol_client)

    failed = wait_for(symbol_client, "failed")

    assert "pretrained ResNet34 weights" in failed["error"]
    assert failed["model"] is None
    trainer.error = None
    assert train(symbol_client).status_code == 200
    wait_for(symbol_client, "ready")


def test_training_needs_artwork_for_two_symbols(
    symbol_client: TestClient, trainer: FakeTrainer, games_dir: Path
) -> None:
    for image in (games_dir / GAME / "symbols" / "BB").iterdir():
        image.unlink()

    response = train(symbol_client)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SYMBOL_ARTWORK_MISSING"
    assert trainer.calls == []


# ----------------------------------------------------------------------- identifying


def test_identify_needs_a_trained_model_and_leaves_obs_alone(
    symbol_client: TestClient, connected, fake_obs: FakeObs
) -> None:
    response = identify(symbol_client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SYMBOL_MODEL_MISSING"
    assert fake_obs.calls("SaveSourceScreenshot") == []


def test_identify_names_every_tile_by_its_position(
    symbol_client: TestClient, trainer: FakeTrainer, connected, fake_obs: FakeObs, fake_games
) -> None:
    fake_games[GAME] = make_config(symbols=NAMES)
    train(symbol_client)
    wait_for(symbol_client, "ready")

    response = identify(symbol_client)

    assert response.status_code == 200
    reading = response.json()["data"]
    assert len(fake_obs.calls("SaveSourceScreenshot")) == 1
    assert (reading["game"], reading["mode"]) == (GAME, "simulator")
    assert (reading["rows"], reading["columns"]) == (3, 5)
    assert reading["id"].startswith("roi_")
    assert reading["model"]["classes"] == ["AA", "BB"]
    tiles = reading["tiles"]
    # Row by row, left to right, and each tile is the one at its own position.
    assert [(t["row"], t["column"]) for t in tiles] == [(r, c) for r in range(3) for c in range(5)]
    assert [t["code"] for t in tiles] == [f"S{r}{c}" for r in range(3) for c in range(5)]
    assert tiles[0]["confidence"] == 90.0
    assert tiles[4]["confidence"] == 94.0
    assert tiles[5]["confidence"] == 90.1
    # Named from the game config; a code the config does not name has no name.
    assert (tiles[0]["name"], tiles[1]["name"], tiles[2]["name"]) == ("Ox", "Pisces", None)


def test_identify_reuses_the_roi_extraction(
    symbol_client: TestClient, trainer: FakeTrainer, connected
) -> None:
    train(symbol_client)
    wait_for(symbol_client, "ready")

    reading = identify(symbol_client).json()["data"]

    records = symbol_client.get("/api/v1/roi/records").json()["data"]
    assert [r["id"] for r in records] == [reading["id"]]
    assert len(records[0]["tiles"]) == len(reading["tiles"]) == 15
    # The reading points at the reel grid the tiles were cut from, so the tab can show them in place.
    grid = next(c for c in records[0]["crops"] if c["name"] == "reels")
    assert reading["reels"] == {"url": grid["url"], "width": grid["width"], "height": grid["height"]}
    assert symbol_client.get(f"/api/v1{reading['reels']['url']}").status_code == 200


def test_identify_is_refused_without_a_reel_grid(
    symbol_client: TestClient, trainer: FakeTrainer, connected, fake_games
) -> None:
    train(symbol_client)
    wait_for(symbol_client, "ready")
    fake_games[GAME] = make_config(reel_bounds=None)

    response = identify(symbol_client)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SYMBOL_NO_TILES"


def test_identify_needs_an_obs_connection(symbol_client: TestClient, trainer: FakeTrainer) -> None:
    train(symbol_client)
    wait_for(symbol_client, "ready")

    assert identify(symbol_client).status_code == 503


def test_a_model_that_cannot_be_loaded_is_reported(
    symbol_client: TestClient, trainer: FakeTrainer, connected, monkeypatch: pytest.MonkeyPatch
) -> None:
    train(symbol_client)
    wait_for(symbol_client, "ready")

    def broken(cls, path):
        raise symbol_classifier.SymbolTrainingError("Cannot load the trained model")

    monkeypatch.setattr(symbol_classifier.SymbolClassifier, "load", classmethod(broken))

    response = identify(symbol_client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SYMBOL_MODEL_UNUSABLE"


def test_a_retrained_model_replaces_the_loaded_one(
    symbol_client: TestClient, trainer: FakeTrainer, connected, monkeypatch: pytest.MonkeyPatch
) -> None:
    loads = []

    def load(cls, path):
        loads.append(path)
        return FakeClassifier()

    monkeypatch.setattr(symbol_classifier.SymbolClassifier, "load", classmethod(load))
    train(symbol_client)
    wait_for(symbol_client, "ready")
    identify(symbol_client)
    identify(symbol_client)
    assert len(loads) == 1  # loaded once, then kept

    time.sleep(0.01)  # a later trained_at
    train(symbol_client)
    wait_for(symbol_client, "ready")
    identify(symbol_client)

    assert len(loads) == 2


# ------------------------------------------------------------------------- readings


def test_readings_are_kept_newest_first(
    symbol_client: TestClient, trainer: FakeTrainer, connected
) -> None:
    train(symbol_client)
    wait_for(symbol_client, "ready")
    assert symbol_client.get(f"{URL}/readings").json()["data"] == []
    first = identify(symbol_client).json()["data"]
    second = identify(symbol_client).json()["data"]

    latest = symbol_client.get(f"{URL}/readings").json()["data"]
    both = symbol_client.get(f"{URL}/readings", params={"limit": 5}).json()["data"]

    assert [r["id"] for r in latest] == [second["id"]]
    assert [r["id"] for r in both] == [second["id"], first["id"]]
    assert both[0] == second
