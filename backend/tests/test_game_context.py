import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.schemas.game_context import GameMode
from app.services.game_context_service import GameContextService

URL = "/api/v1/game-context"


def test_get_returns_context_and_options(client: TestClient) -> None:
    body = client.get(URL).json()

    assert body["success"] is True
    data = body["data"]
    assert "FortuneOx" in data["options"]["games"]
    assert "HuffNPuffHighRise" in data["options"]["games"]
    assert "__pycache__" not in data["options"]["games"]
    assert data["options"]["modes"] == ["simulator", "egm"]
    assert data["context"]["game"] in data["options"]["games"]


def test_patch_updates_and_persists_state(client: TestClient) -> None:
    response = client.patch(URL, json={"game": "HuffNPuffHighRise", "mode": "egm"})

    assert response.status_code == 200
    assert response.json()["data"]["context"] == {"game": "HuffNPuffHighRise", "mode": "egm"}
    assert client.get(URL).json()["data"]["context"] == {"game": "HuffNPuffHighRise", "mode": "egm"}


def test_patch_is_partial(client: TestClient) -> None:
    client.patch(URL, json={"game": "FortuneOx", "mode": "simulator"})
    client.patch(URL, json={"mode": "egm"})

    assert client.get(URL).json()["data"]["context"] == {"game": "FortuneOx", "mode": "egm"}


def test_patch_rejects_unknown_game(client: TestClient) -> None:
    response = client.patch(URL, json={"game": "Nope"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_patch_rejects_invalid_mode(client: TestClient) -> None:
    response = client.patch(URL, json={"mode": "cloud"})

    assert response.status_code == 422


def test_selection_survives_restart(client: TestClient, game_context_file: Path) -> None:
    client.patch(URL, json={"game": "HuffNPuffHighRise", "mode": "egm"})

    # A new service instance over the same file simulates a backend restart.
    restarted = GameContextService(state_file=game_context_file)

    assert restarted.current_game == "HuffNPuffHighRise"
    assert restarted.current_mode == GameMode.EGM
    assert restarted.get_context().context.game == "HuffNPuffHighRise"


def test_default_is_pinned_on_first_update(client: TestClient, game_context_file: Path) -> None:
    client.patch(URL, json={"mode": "egm"})

    saved = json.loads(game_context_file.read_text(encoding="utf-8"))
    assert saved == {"game": "FortuneOx", "mode": "egm"}


def test_corrupt_state_file_falls_back_to_defaults(game_context_file: Path) -> None:
    game_context_file.write_text("{not json", encoding="utf-8")

    service = GameContextService(state_file=game_context_file)

    assert service.current_game is None
    assert service.get_context().context.mode == GameMode.SIMULATOR
