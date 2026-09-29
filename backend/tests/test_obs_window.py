import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas.obs import ObsWindow
from app.services.obs_service import ObsService
from app.services.obs_window_service import ObsWindowService
from tests.fake_obs import GAME_WINDOW, MINIMISED_WINDOW, NOTES_WINDOW, FakeObs, scene_item

URL = "/api/v1/obs"


def connect(client: TestClient) -> None:
    assert client.post(f"{URL}/connect").status_code == 200


def select(client: TestClient, value: str, name: str = ""):
    return client.put(f"{URL}/window", json={"value": value, "name": name})


def test_windows_require_a_connection(obs_client: TestClient) -> None:
    assert obs_client.get(f"{URL}/windows").status_code == 503


def test_lists_windows_sorted_without_the_blank_entry(obs_client: TestClient) -> None:
    connect(obs_client)

    windows = obs_client.get(f"{URL}/windows").json()["data"]

    assert [w["value"] for w in windows] == [GAME_WINDOW, MINIMISED_WINDOW, NOTES_WINDOW]
    assert windows[0]["name"] == "[app.exe]: FortuneOx"


def test_creates_the_capture_source_when_the_scene_has_none(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    fake_obs.scene_items = []
    fake_obs.input_names = set()
    connect(obs_client)

    assert obs_client.get(f"{URL}/windows").status_code == 200

    (create,) = fake_obs.calls("CreateInput")
    assert create["sceneName"] == "Scene 1"
    assert create["inputKind"] == "window_capture"
    # The mouse cursor and title bar must not end up in the picture.
    assert create["inputSettings"]["cursor"] is False
    assert create["inputSettings"]["client_area"] is True


def test_reuses_an_existing_source_of_the_same_name_from_another_scene(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    fake_obs.scene_items = []  # the scene has no capture, but the input exists elsewhere
    connect(obs_client)

    assert obs_client.get(f"{URL}/windows").status_code == 200

    (add,) = fake_obs.calls("CreateSceneItem")
    assert add["sourceName"] == "Window Capture"


def test_selecting_a_window_fits_the_canvas_to_it(obs_client: TestClient, fake_obs: FakeObs) -> None:
    fake_obs.windows[NOTES_WINDOW] = (500, 400)
    connect(obs_client)

    response = select(obs_client, NOTES_WINDOW, "Notes")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "window": {"value": NOTES_WINDOW, "name": "Notes"},
        "canvas_width": 500,
        "canvas_height": 400,
        "applied": True,
        "warning": None,
    }
    assert fake_obs.window == NOTES_WINDOW
    assert fake_obs.video == {
        "baseWidth": 500,
        "baseHeight": 400,
        "outputWidth": 500,
        "outputHeight": 400,
    }
    # The source is shown 1:1, top-left, filling the canvas: nothing is rescaled.
    transform = fake_obs.item_transform
    assert (transform["positionX"], transform["positionY"]) == (0, 0)
    assert (transform["scaleX"], transform["scaleY"]) == (1, 1)
    assert transform["boundsType"] == "OBS_BOUNDS_NONE"
    assert fake_obs.item_enabled is True


def test_odd_window_sizes_round_the_canvas_up_to_even(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    connect(obs_client)

    data = select(obs_client, GAME_WINDOW).json()["data"]  # 766 x 1101

    assert (data["canvas_width"], data["canvas_height"]) == (766, 1102)
    assert fake_obs.video["outputHeight"] == 1102


def test_canvas_is_left_alone_when_it_already_fits(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    fake_obs.video = {"baseWidth": 766, "baseHeight": 1102, "outputWidth": 766, "outputHeight": 1102}
    connect(obs_client)

    select(obs_client, GAME_WINDOW)

    assert fake_obs.calls("SetVideoSettings") == []


def test_canvas_is_left_alone_when_obs_aligned_the_output_width(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    # OBS stores the output width of a 766 wide canvas as 764.
    fake_obs.video = {"baseWidth": 766, "baseHeight": 1102, "outputWidth": 764, "outputHeight": 1102}
    connect(obs_client)

    select(obs_client, GAME_WINDOW)

    assert fake_obs.calls("SetVideoSettings") == []


def test_output_that_differs_more_than_alignment_is_corrected(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    fake_obs.video = {"baseWidth": 766, "baseHeight": 1102, "outputWidth": 1280, "outputHeight": 720}
    connect(obs_client)

    select(obs_client, GAME_WINDOW)

    assert len(fake_obs.calls("SetVideoSettings")) == 1


def test_a_stale_size_from_the_previous_window_is_not_trusted(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    fake_obs.reported_size = (766, 1101)
    fake_obs.stale_polls = 2  # OBS keeps reporting the old size for a moment
    connect(obs_client)

    data = select(obs_client, NOTES_WINDOW).json()["data"]

    assert (data["canvas_width"], data["canvas_height"]) == (500, 400)


def test_a_window_that_cannot_be_captured_is_rejected_and_not_saved(
    obs_client: TestClient, fake_obs: FakeObs, window_file: Path
) -> None:
    connect(obs_client)

    response = select(obs_client, MINIMISED_WINDOW)

    assert response.status_code == 400
    assert "minimised" in response.json()["error"]["message"]
    assert fake_obs.calls("SetVideoSettings") == []
    assert not window_file.exists()


def test_selecting_requires_a_connection(obs_client: TestClient) -> None:
    assert select(obs_client, GAME_WINDOW).status_code == 503


def test_selecting_rejects_an_empty_window_value(obs_client: TestClient) -> None:
    connect(obs_client)

    assert select(obs_client, "").status_code == 422


def test_canvas_change_refused_by_obs_is_reported_and_not_saved(
    obs_client: TestClient, fake_obs: FakeObs, window_file: Path
) -> None:
    fake_obs.rejected["SetVideoSettings"] = "Cannot change while an output is active"
    connect(obs_client)

    response = select(obs_client, NOTES_WINDOW)

    assert response.status_code == 502
    assert "output is active" in response.json()["error"]["message"]
    assert not window_file.exists()


def test_selection_is_saved_and_survives_a_restart(
    obs_client: TestClient, service: ObsService, window_file: Path
) -> None:
    connect(obs_client)
    select(obs_client, NOTES_WINDOW, "Notes")

    assert json.loads(window_file.read_text()) == {"value": NOTES_WINDOW, "name": "Notes"}
    restarted = ObsWindowService(obs=service, state_file=window_file)
    assert restarted._selected.value == NOTES_WINDOW


def test_setup_before_any_selection(obs_client: TestClient) -> None:
    connect(obs_client)

    data = obs_client.get(f"{URL}/window").json()["data"]

    assert data["window"] is None
    assert data["applied"] is False
    assert (data["canvas_width"], data["canvas_height"]) == (1080, 1920)


def test_setup_without_a_connection_has_no_canvas(
    saved_notes_window, obs_client: TestClient
) -> None:
    data = obs_client.get(f"{URL}/window").json()["data"]

    assert data["canvas_width"] is None


# Listed before `obs_client` in the tests below so the file exists when the backend "starts".
@pytest.fixture
def saved_notes_window(window_file: Path) -> None:
    window_file.write_text(json.dumps({"value": NOTES_WINDOW, "name": "Notes"}))


@pytest.fixture
def saved_missing_window(window_file: Path) -> None:
    window_file.write_text(json.dumps({"value": MINIMISED_WINDOW, "name": "Gone"}))


def test_connecting_applies_the_saved_window(
    saved_notes_window, obs_client: TestClient, fake_obs: FakeObs
) -> None:
    connect(obs_client)

    assert fake_obs.window == NOTES_WINDOW
    assert (fake_obs.video["baseWidth"], fake_obs.video["baseHeight"]) == (500, 400)
    assert obs_client.get(f"{URL}/window").json()["data"]["applied"] is True


def test_connect_still_succeeds_when_the_saved_window_is_gone(
    saved_missing_window, obs_client: TestClient, fake_obs: FakeObs
) -> None:
    response = obs_client.post(f"{URL}/connect")

    assert response.status_code == 200
    assert response.json()["data"]["connected"] is True
    data = obs_client.get(f"{URL}/window").json()["data"]
    assert data["applied"] is False
    assert "cannot capture" in data["warning"]
    assert fake_obs.video["baseWidth"] == 1080  # canvas untouched


def test_connecting_without_a_saved_window_changes_nothing(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    connect(obs_client)

    assert fake_obs.calls("SetVideoSettings") == []
    assert fake_obs.calls("SetInputSettings") == []


def test_an_already_open_connection_does_not_reapply_on_connect(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    connect(obs_client)
    select(obs_client, NOTES_WINDOW)
    applied_before = len(fake_obs.calls("SetInputSettings"))

    connect(obs_client)

    assert len(fake_obs.calls("SetInputSettings")) == applied_before


async def until(condition, timeout: float = 2.0) -> None:
    """Waits for the background watcher to do its work."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "timed out waiting for the watcher"
        await asyncio.sleep(0.005)


def canvas(fake_obs: FakeObs) -> tuple[int, int]:
    return fake_obs.video["baseWidth"], fake_obs.video["baseHeight"]


def test_canvas_follows_the_window_when_it_is_resized(
    service: ObsService, window_service: ObsWindowService, fake_obs: FakeObs
) -> None:
    async def run() -> None:
        await service.connect()
        await window_service.select_window(ObsWindow(value=NOTES_WINDOW, name="Notes"))
        assert canvas(fake_obs) == (500, 400)

        fake_obs.windows[NOTES_WINDOW] = (640, 480)  # the user drags the window bigger

        await until(lambda: canvas(fake_obs) == (640, 480))
        assert (await window_service.get_setup()).canvas_width == 640

    asyncio.run(run())


def test_canvas_is_fitted_once_a_window_that_was_not_open_appears(
    saved_missing_window, service: ObsService, window_service: ObsWindowService, fake_obs: FakeObs
) -> None:
    async def run() -> None:
        await service.connect()  # the saved window cannot be captured yet
        assert (await window_service.get_setup()).applied is False
        assert canvas(fake_obs) == (1080, 1920)

        fake_obs.windows[MINIMISED_WINDOW] = (300, 200)  # the window is opened

        await until(lambda: canvas(fake_obs) == (300, 200))
        setup = await window_service.get_setup()
        assert setup.applied is True
        assert setup.warning is None

    asyncio.run(run())


def test_a_refused_canvas_change_is_retried_gently_and_then_succeeds(
    service: ObsService, window_service: ObsWindowService, fake_obs: FakeObs
) -> None:
    async def run() -> None:
        await service.connect()
        await window_service.select_window(ObsWindow(value=NOTES_WINDOW, name="Notes"))
        fake_obs.rejected["SetVideoSettings"] = "Cannot change while recording"
        fake_obs.windows[NOTES_WINDOW] = (640, 480)

        await until(lambda: (window_service._warning or "").startswith("OBS rejected"))
        await asyncio.sleep(0.2)
        # Retried every 50 ms at most, not on every 5 ms check.
        assert 1 <= len(fake_obs.calls("SetVideoSettings")) <= 8

        del fake_obs.rejected["SetVideoSettings"]  # the recording ended
        await until(lambda: canvas(fake_obs) == (640, 480))
        assert (await window_service.get_setup()).warning is None

    asyncio.run(run())


def test_the_watcher_stops_when_obs_disconnects(
    service: ObsService, window_service: ObsWindowService
) -> None:
    async def run() -> None:
        await service.connect()
        await window_service.select_window(ObsWindow(value=NOTES_WINDOW, name="Notes"))
        watcher = window_service._watcher
        assert watcher is not None and not watcher.done()

        await service.disconnect()

        await until(watcher.done)

    asyncio.run(run())


def test_the_watcher_never_creates_sources(
    service: ObsService, window_service: ObsWindowService, fake_obs: FakeObs
) -> None:
    async def run() -> None:
        await service.connect()
        await window_service.select_window(ObsWindow(value=NOTES_WINDOW, name="Notes"))
        fake_obs.scene_items = []  # e.g. the user switched to a scene without a capture
        fake_obs.requests.clear()

        await asyncio.sleep(0.1)

        assert fake_obs.calls("CreateInput") == []
        assert fake_obs.calls("CreateSceneItem") == []
        assert fake_obs.calls("SetVideoSettings") == []

    asyncio.run(run())


def test_an_unchanged_window_causes_no_writes_to_obs(
    service: ObsService, window_service: ObsWindowService, fake_obs: FakeObs
) -> None:
    async def run() -> None:
        await service.connect()
        await window_service.select_window(ObsWindow(value=NOTES_WINDOW, name="Notes"))
        fake_obs.requests.clear()

        await asyncio.sleep(0.1)

        writes = {"SetVideoSettings", "SetSceneItemTransform", "SetInputSettings"}
        assert writes.isdisjoint(name for name, _ in fake_obs.requests)

    asyncio.run(run())


def test_there_is_no_explicit_fit_endpoint(obs_client: TestClient) -> None:
    connect(obs_client)

    assert obs_client.post(f"{URL}/window/fit").status_code in (404, 405)


def test_capture_prefers_the_visible_window_capture(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    fake_obs.scene_items = [
        scene_item("Hidden capture", enabled=False, item_id=3),
        scene_item("Visible capture", item_id=4),
    ]
    connect(obs_client)

    select(obs_client, NOTES_WINDOW)

    (settings,) = fake_obs.calls("SetInputSettings")
    assert settings["inputName"] == "Visible capture"


def test_reads_after_disconnecting(obs_client: TestClient) -> None:
    connect(obs_client)
    obs_client.post(f"{URL}/disconnect")

    assert obs_client.get(f"{URL}/windows").status_code == 503
    setup = obs_client.get(f"{URL}/window")
    assert setup.status_code == 200
    assert setup.json()["data"]["canvas_width"] is None
