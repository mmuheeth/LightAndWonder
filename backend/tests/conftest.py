from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_game_context_controller, get_obs_controller
from app.controllers.game_context_controller import GameContextController
from app.controllers.obs_controller import ObsController
from app.main import app
from app.services import obs_service, obs_window_service
from app.services.game_context_service import GameContextService
from app.services.obs_service import ObsService
from app.services.obs_window_service import ObsWindowService
from tests.fake_obs import FakeObs
from tests.obs_helpers import make_service


@pytest.fixture
def game_context_file(tmp_path: Path) -> Path:
    return tmp_path / "game_context.json"


@pytest.fixture
def client(game_context_file: Path) -> TestClient:
    # Isolated state file per test, so tests never touch the real saved selection.
    controller = GameContextController(GameContextService(state_file=game_context_file))
    app.dependency_overrides[get_game_context_controller] = lambda: controller
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def captures_dir(tmp_path: Path) -> Path:
    return tmp_path / "obs"


@pytest.fixture
def fake_obs() -> FakeObs:
    return FakeObs()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "obs_config.json"


@pytest.fixture
def window_file(tmp_path: Path) -> Path:
    return tmp_path / "obs_window.json"


@pytest.fixture(autouse=True)
def fast_obs_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs_service, "_RETRY_INTERVAL", 0.01)
    monkeypatch.setattr(obs_window_service, "_SIZE_POLL_INTERVAL", 0.001)
    monkeypatch.setattr(obs_window_service, "_SIZE_TIMEOUT", 0.2)
    monkeypatch.setattr(obs_window_service, "_WATCH_INTERVAL", 0.005)
    monkeypatch.setattr(obs_window_service, "_WATCH_RETRY_AFTER", 0.05)


@pytest.fixture
def service(
    fake_obs: FakeObs, captures_dir: Path, config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> ObsService:
    svc = make_service(fake_obs, captures_dir, config_file)
    svc.launched = 0
    monkeypatch.setattr(svc, "_is_obs_running", lambda: fake_obs.accepting)

    def fake_launch() -> None:
        svc.launched += 1
        fake_obs.accepting = True

    monkeypatch.setattr(svc, "_launch_obs", fake_launch)
    return svc


@pytest.fixture
def window_service(service: ObsService, window_file: Path) -> ObsWindowService:
    return ObsWindowService(obs=service, state_file=window_file)


@pytest.fixture
def obs_client(service: ObsService, window_service: ObsWindowService):
    controller = ObsController(service, window_service)
    app.dependency_overrides[get_obs_controller] = lambda: controller
    yield TestClient(app)
    app.dependency_overrides.clear()
