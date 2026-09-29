import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.obs_service import ObsService
from tests.fake_obs import PNG, FakeObs, scene_item
from tests.obs_helpers import make_service

URL = "/api/v1/obs"


def connect(client: TestClient) -> None:
    assert client.post(f"{URL}/connect").status_code == 200


def test_status_when_not_connected(obs_client: TestClient) -> None:
    data = obs_client.get(f"{URL}/status").json()["data"]

    assert data == {
        "obs_running": True,
        "connected": False,
        "recording": False,
        "recording_path": None,
    }


def test_connect_to_running_obs_does_not_launch(obs_client: TestClient, service) -> None:
    data = obs_client.post(f"{URL}/connect").json()["data"]

    assert data["connected"] is True
    assert service.launched == 0


def test_connect_launches_obs_when_not_running(
    obs_client: TestClient, service, fake_obs: FakeObs
) -> None:
    fake_obs.accepting = False

    data = obs_client.post(f"{URL}/connect").json()["data"]

    assert data["connected"] is True
    assert service.launched == 1


def test_connect_does_not_launch_when_obs_is_running_but_server_is_down(
    obs_client: TestClient, service, fake_obs: FakeObs, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_obs.accepting = False
    monkeypatch.setattr(service, "_is_obs_running", lambda: True)

    response = obs_client.post(f"{URL}/connect")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert service.launched == 0


def test_connect_is_idempotent(obs_client: TestClient, service) -> None:
    connect(obs_client)
    connect(obs_client)

    assert service.connected is True
    assert service.launched == 0


def test_disconnect(obs_client: TestClient) -> None:
    connect(obs_client)

    data = obs_client.post(f"{URL}/disconnect").json()["data"]

    assert data["connected"] is False


def test_disconnect_without_connection_is_fine(obs_client: TestClient) -> None:
    assert obs_client.post(f"{URL}/disconnect").status_code == 200


def test_screenshot_requires_connection(obs_client: TestClient) -> None:
    response = obs_client.post(f"{URL}/screenshots")

    assert response.status_code == 503


def test_screenshot_is_saved_by_obs_and_served(obs_client: TestClient, captures_dir: Path) -> None:
    connect(obs_client)

    data = obs_client.post(f"{URL}/screenshots").json()["data"]

    assert data["filename"].endswith(".bmp")
    assert (captures_dir / "screenshots" / data["filename"]).read_bytes() == PNG
    image = obs_client.get(f"{URL}/screenshots/{data['filename']}")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/bmp"
    assert image.content == PNG


def test_screenshot_asks_obs_to_write_the_file_itself(
    obs_client: TestClient, fake_obs: FakeObs, captures_dir: Path
) -> None:
    connect(obs_client)
    data = obs_client.post(f"{URL}/screenshots").json()["data"]

    (_, request), = [r for r in fake_obs.requests if r[0] == "SaveSourceScreenshot"]
    assert request == {
        "sourceName": "Scene 1",
        "imageFormat": "bmp",
        "imageFilePath": str(captures_dir / "screenshots" / data["filename"]),
    }
    # No image data is pulled over the websocket.
    assert "GetSourceScreenshot" not in [r[0] for r in fake_obs.requests]


def captured_source(fake_obs: FakeObs) -> str:
    (_, request), = [r for r in fake_obs.requests if r[0] == "SaveSourceScreenshot"]
    return request["sourceName"]


def test_native_mode_captures_the_source_not_the_rescaled_scene(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    connect(obs_client)
    obs_client.post(f"{URL}/screenshots", params={"mode": "native"})

    assert captured_source(fake_obs) == "Window Capture"


def test_default_mode_captures_the_composed_scene(obs_client: TestClient, fake_obs: FakeObs) -> None:
    connect(obs_client)
    obs_client.post(f"{URL}/screenshots")

    assert captured_source(fake_obs) == "Scene 1"


def test_native_mode_ignores_hidden_items(obs_client: TestClient, fake_obs: FakeObs) -> None:
    fake_obs.scene_items = [scene_item("Overlay", enabled=False), scene_item()]
    connect(obs_client)
    obs_client.post(f"{URL}/screenshots", params={"mode": "native"})

    assert captured_source(fake_obs) == "Window Capture"


@pytest.mark.parametrize(
    "items",
    [
        pytest.param([scene_item(), scene_item("Logo")], id="several-visible-items"),
        pytest.param([], id="empty-scene"),
        pytest.param([scene_item(enabled=False)], id="only-hidden-items"),
        pytest.param([scene_item(cropLeft=10)], id="cropped"),
        pytest.param([scene_item(rotation=90.0)], id="rotated"),
        pytest.param([scene_item(scaleX=-1.0)], id="flipped"),
        pytest.param([scene_item(sourceWidth=0.0, sourceHeight=0.0)], id="zero-size-source"),
        pytest.param([{**scene_item(), "isGroup": True}], id="group"),
        pytest.param(
            [{**scene_item(), "sourceType": "OBS_SOURCE_TYPE_SCENE"}], id="nested-scene"
        ),
    ],
)
def test_native_mode_falls_back_to_the_scene_when_the_source_alone_would_differ(
    obs_client: TestClient, fake_obs: FakeObs, items: list[dict]
) -> None:
    fake_obs.scene_items = items
    connect(obs_client)
    obs_client.post(f"{URL}/screenshots", params={"mode": "native"})

    assert captured_source(fake_obs) == "Scene 1"


def test_screenshot_rejects_unknown_mode(obs_client: TestClient) -> None:
    assert obs_client.post(f"{URL}/screenshots", params={"mode": "zoom"}).status_code == 422


def test_png_screenshot_is_uncompressed_for_speed(
    obs_client: TestClient, fake_obs: FakeObs
) -> None:
    connect(obs_client)

    data = obs_client.post(f"{URL}/screenshots", params={"format": "png"}).json()["data"]

    assert data["filename"].endswith(".png")
    (_, request), = [r for r in fake_obs.requests if r[0] == "SaveSourceScreenshot"]
    assert request["imageFormat"] == "png"
    assert request["imageCompressionQuality"] == 100
    served = obs_client.get(f"{URL}/screenshots/{data['filename']}")
    assert served.headers["content-type"] == "image/png"


def test_screenshot_rejects_unknown_format(obs_client: TestClient) -> None:
    assert obs_client.post(f"{URL}/screenshots", params={"format": "gif"}).status_code == 422


def test_configured_default_format_is_used(
    fake_obs: FakeObs, captures_dir: Path, config_file: Path
) -> None:
    svc = ObsService(
        host="localhost", port=4455, password="", exe_path=Path("obs64.exe"),
        launch_timeout=1, captures_dir=captures_dir, config_file=config_file,
        screenshot_format="png", client_factory=fake_obs.make_client,
    )

    async def run() -> str:
        await svc.connect()
        return (await svc.take_screenshot()).filename

    assert asyncio.run(run()).endswith(".png")


def test_concurrent_screenshots_never_overwrite_each_other(service: ObsService) -> None:
    async def run() -> list[str]:
        await service.connect()
        shots = await asyncio.gather(*[service.take_screenshot() for _ in range(25)])
        return [shot.filename for shot in shots]

    names = asyncio.run(run())

    assert len(set(names)) == 25
    assert len(service.list_screenshots(limit=50)) == 25


def test_remote_obs_screenshot_is_transferred_and_saved_as_png(
    obs_client: TestClient, fake_obs: FakeObs, captures_dir: Path
) -> None:
    obs_client.put(f"{URL}/config", json={"host": "10.0.0.5", "port": 4455})
    connect(obs_client)

    data = obs_client.post(f"{URL}/screenshots").json()["data"]

    assert data["filename"].endswith(".png")
    assert (captures_dir / "screenshots" / data["filename"]).read_bytes() == PNG
    assert "SaveSourceScreenshot" not in [r[0] for r in fake_obs.requests]


def test_list_screenshots_returns_newest_first_and_respects_limit(
    obs_client: TestClient, captures_dir: Path
) -> None:
    shots = captures_dir / "screenshots"
    shots.mkdir(parents=True)
    for index in range(7):
        path = shots / f"old_{index}.{'bmp' if index % 2 else 'png'}"
        path.write_bytes(PNG)
        # Distinct, increasing modification times.
        os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
    (shots / "notes.txt").write_text("ignored")

    data = obs_client.get(f"{URL}/screenshots", params={"limit": 3}).json()["data"]

    assert [item["filename"] for item in data] == ["old_6.png", "old_5.bmp", "old_4.png"]
    assert data[0]["url"] == "/obs/screenshots/old_6.png"


def test_list_screenshots_empty_when_folder_missing(obs_client: TestClient) -> None:
    assert obs_client.get(f"{URL}/screenshots").json()["data"] == []


def test_list_screenshots_rejects_bad_limit(obs_client: TestClient) -> None:
    assert obs_client.get(f"{URL}/screenshots", params={"limit": 0}).status_code == 422


@pytest.mark.parametrize("name", ["missing.png", "..%2Fsecret.png", "notes.txt"])
def test_get_screenshot_rejects_unknown_or_unsafe_names(
    obs_client: TestClient, captures_dir: Path, name: str
) -> None:
    (captures_dir / "screenshots").mkdir(parents=True)
    (captures_dir / "screenshots" / "notes.txt").write_text("x")
    (captures_dir / "secret.png").write_bytes(PNG)

    assert obs_client.get(f"{URL}/screenshots/{name}").status_code == 404


def test_recording_start_and_stop(obs_client: TestClient, fake_obs, captures_dir: Path) -> None:
    connect(obs_client)

    started = obs_client.post(f"{URL}/recording/start").json()["data"]

    assert started["recording"] is True
    recordings = captures_dir / "recordings"
    assert recordings.is_dir()
    assert ("SetRecordDirectory", {"recordDirectory": str(recordings.resolve())}) in (
        fake_obs.requests
    )
    assert obs_client.get(f"{URL}/status").json()["data"]["recording"] is True

    stopped = obs_client.post(f"{URL}/recording/stop").json()["data"]

    assert stopped == {"output_path": "C:/rec/a.mkv"}
    assert obs_client.get(f"{URL}/status").json()["data"]["recording"] is False


def test_recording_requires_connection(obs_client: TestClient) -> None:
    assert obs_client.post(f"{URL}/recording/start").status_code == 503
    assert obs_client.post(f"{URL}/recording/stop").status_code == 503


def test_obs_rejection_is_reported(obs_client: TestClient, fake_obs: FakeObs) -> None:
    connect(obs_client)
    fake_obs.rejected["StartRecord"] = "Recording is already active"

    response = obs_client.post(f"{URL}/recording/start")

    assert response.status_code == 502
    body = response.json()["error"]
    assert body["code"] == "OBS_REQUEST_FAILED"
    assert "already active" in body["message"]


def test_config_defaults_come_from_settings(obs_client: TestClient) -> None:
    assert obs_client.get(f"{URL}/config").json()["data"] == {"host": "localhost", "port": 4455}


def test_config_update_is_saved_and_survives_restart(
    obs_client: TestClient, fake_obs: FakeObs, captures_dir: Path, config_file: Path
) -> None:
    response = obs_client.put(f"{URL}/config", json={"host": "192.168.1.20", "port": 4466})

    assert response.json()["data"] == {"host": "192.168.1.20", "port": 4466}
    assert obs_client.get(f"{URL}/config").json()["data"] == {"host": "192.168.1.20", "port": 4466}
    restarted = make_service(fake_obs, captures_dir, config_file)
    assert restarted.get_config().model_dump() == {"host": "192.168.1.20", "port": 4466}


def test_config_update_disconnects(obs_client: TestClient) -> None:
    connect(obs_client)

    obs_client.put(f"{URL}/config", json={"host": "localhost", "port": 4460})

    assert obs_client.get(f"{URL}/status").json()["data"]["connected"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"host": "", "port": 4455},
        {"host": "ws://localhost", "port": 4455},
        {"host": "local host", "port": 4455},
        {"host": "localhost", "port": 0},
        {"host": "localhost", "port": 70000},
        {"host": "localhost"},
    ],
)
def test_config_update_rejects_invalid_values(obs_client: TestClient, body: dict) -> None:
    assert obs_client.put(f"{URL}/config", json=body).status_code == 422


def test_unreadable_config_file_falls_back_to_defaults(
    fake_obs: FakeObs, captures_dir: Path, config_file: Path
) -> None:
    config_file.write_text("{not json")

    svc = make_service(fake_obs, captures_dir, config_file)

    assert svc.get_config().model_dump() == {"host": "localhost", "port": 4455}


def test_connect_never_launches_obs_for_a_remote_host(
    obs_client: TestClient, service, fake_obs: FakeObs
) -> None:
    obs_client.put(f"{URL}/config", json={"host": "10.0.0.5", "port": 4455})
    fake_obs.accepting = False

    response = obs_client.post(f"{URL}/connect")

    assert response.status_code == 503
    assert "10.0.0.5:4455" in response.json()["error"]["message"]
    assert service.launched == 0
