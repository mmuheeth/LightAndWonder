import asyncio
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.dependencies import get_obs_controller, get_roi_controller
from app.controllers.obs_controller import ObsController
from app.controllers.roi_controller import RoiController
from app.main import app
from app.schemas.game_context import GameContextUpdate, GameMode
from app.services.game_context_service import GameContextService
from app.services.obs_service import ObsService
from app.services.obs_window_service import ObsWindowService
from app.services.roi_service import RoiService
from app.utils import game_config as game_settings
from tests.fake_obs import FakeObs

URL = "/api/v1/roi"
GAME = "TestGame"
WHITE = (255, 255, 255)


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_config(**overrides) -> dict:
    config = {
        "name": GAME,
        "simulator": {
            "roi": {
                "reels": [0.1, 0.2, 0.9, 0.8],
                "cash_meter": [0.0, 0.9, 1.0, 1.0],
                "cyclic_message": [],
                "cyclic_message_2": [0.0, 0.85, 0.2, 0.9],
            }
        },
        "reel_bounds": {"rows": 3, "columns": 5, "inset": 0.1},
    }
    return {**config, **overrides}


def cell_color(row: int, column: int) -> tuple[int, int, int]:
    return column * 40 + 10, row * 80 + 10, 200


def game_screenshot(width: int = 1000, height: int = 2000) -> Image.Image:
    """A screenshot whose reel grid (the 0.1..0.9 x 0.2..0.8 area) is 5x3 cells of their own
    colour, each with a white border, on a grey background."""
    image = Image.new("RGB", (width, height), (90, 90, 90))
    left, top = 0.1 * width, 0.2 * height
    cell_w, cell_h = 0.8 * width / 5, 0.6 * height / 3
    border = 0.03
    for row in range(3):
        for column in range(5):
            x0, y0 = left + column * cell_w, top + row * cell_h
            image.paste(WHITE, (round(x0), round(y0), round(x0 + cell_w), round(y0 + cell_h)))
            image.paste(
                cell_color(row, column),
                (
                    round(x0 + border * cell_w),
                    round(y0 + border * cell_h),
                    round(x0 + (1 - border) * cell_w),
                    round(y0 + (1 - border) * cell_h),
                ),
            )
    return image


@pytest.fixture
def fake_games(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    """Game configs by name, ahead of the real ones."""
    games = {GAME: make_config()}
    real = game_settings.load_game_config
    monkeypatch.setattr(game_settings, "load_game_config", lambda game: games.get(game) or real(game))
    return games


@pytest.fixture
def game_context(tmp_path: Path) -> GameContextService:
    return GameContextService(state_file=tmp_path / "game_context.json")


@pytest.fixture
def roi_service(
    service: ObsService, game_context: GameContextService, captures_dir: Path, fake_games
) -> RoiService:
    return RoiService(obs=service, game_context=game_context, captures_dir=captures_dir)


@pytest.fixture
def roi_client(roi_service: RoiService, window_service: ObsWindowService, fake_obs: FakeObs):
    fake_obs.image = png(game_screenshot())
    controller = RoiController(roi_service)
    # The OBS routes serve the screenshot each record refers to, from the same service.
    obs_controller = ObsController(roi_service._obs, window_service)
    app.dependency_overrides[get_roi_controller] = lambda: controller
    app.dependency_overrides[get_obs_controller] = lambda: obs_controller
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def connected(roi_service: RoiService) -> None:
    asyncio.run(roi_service._obs.connect())


def extract(client: TestClient, **params):
    return client.post(f"{URL}/records", params={"game": GAME, **params})


def fetch(client: TestClient, url: str) -> Image.Image:
    response = client.get(f"/api/v1{url}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    return Image.open(io.BytesIO(response.content))


def roi_folders(captures_dir: Path) -> list[Path]:
    root = captures_dir / "roi"
    return [p for p in root.iterdir() if p.is_dir()] if root.exists() else []


# ----------------------------------------------------------------------- extraction


def test_extract_requires_an_obs_connection(roi_client: TestClient, captures_dir: Path) -> None:
    response = extract(roi_client)

    assert response.status_code == 503
    assert roi_folders(captures_dir) == []


def test_extract_takes_a_screenshot_and_cuts_the_configured_regions(
    roi_client: TestClient, connected, fake_obs: FakeObs
) -> None:
    response = extract(roi_client)

    assert response.status_code == 200
    record = response.json()["data"]
    assert len(fake_obs.calls("SaveSourceScreenshot")) == 1
    assert record["game"] == GAME
    assert record["mode"] == "simulator"
    # Grid first, then the rest in config order; the empty "cyclic_message" is left out.
    assert [c["name"] for c in record["crops"]] == ["reels", "cash_meter", "cyclic_message_2"]
    assert record["crops"][0]["roi"] == [0.1, 0.2, 0.9, 0.8]
    assert record["screenshot"]["url"].startswith("/obs/screenshots/")


def test_crops_are_the_configured_area_of_the_screenshot(
    roi_client: TestClient, connected
) -> None:
    record = extract(roi_client).json()["data"]

    by_name = {c["name"]: c for c in record["crops"]}
    assert (by_name["reels"]["width"], by_name["reels"]["height"]) == (800, 1200)
    assert (by_name["cash_meter"]["width"], by_name["cash_meter"]["height"]) == (1000, 200)
    assert (by_name["cyclic_message_2"]["width"], by_name["cyclic_message_2"]["height"]) == (200, 100)
    cash = fetch(roi_client, by_name["cash_meter"]["url"])
    assert cash.size == (1000, 200)
    assert cash.getpixel((500, 100)) == (90, 90, 90)  # the grey background, below the grid


def test_grid_is_split_into_tiles_by_position(roi_client: TestClient, connected) -> None:
    record = extract(roi_client).json()["data"]

    assert (record["rows"], record["columns"]) == (3, 5)
    assert len(record["tiles"]) == 15
    for tile in record["tiles"]:
        image = fetch(roi_client, tile["url"])
        assert image.size == (tile["width"], tile["height"])
        expected = cell_color(tile["row"], tile["column"])
        # The inset keeps the white border of the cell out of the tile: every pixel is the colour.
        assert image.getcolors() == [(image.width * image.height, expected)]


def test_tiles_are_cut_from_the_reels_crop_without_gap_or_overlap(
    roi_client: TestClient, connected, fake_games
) -> None:
    fake_games[GAME] = make_config(reel_bounds={"rows": 3, "columns": 5})

    record = extract(roi_client).json()["data"]

    tiles = record["tiles"]
    assert sum(t["width"] * t["height"] for t in tiles) == 800 * 1200
    assert {(t["width"], t["height"]) for t in tiles} == {(160, 400)}


def test_inset_may_be_given_per_axis(roi_client: TestClient, connected, fake_games) -> None:
    fake_games[GAME] = make_config(reel_bounds={"rows": 3, "columns": 5, "inset": [0.25, 0.0]})

    record = extract(roi_client).json()["data"]

    assert {(t["width"], t["height"]) for t in record["tiles"]} == {(80, 400)}


def test_no_tiles_without_reel_bounds(roi_client: TestClient, connected, fake_games) -> None:
    config = make_config()
    del config["reel_bounds"]
    fake_games[GAME] = config

    record = extract(roi_client).json()["data"]

    assert record["tiles"] == []
    assert (record["rows"], record["columns"]) == (0, 0)
    assert "reels" in [c["name"] for c in record["crops"]]


def test_no_tiles_without_a_reels_region(roi_client: TestClient, connected, fake_games) -> None:
    config = make_config()
    config["simulator"]["roi"]["reels"] = []
    fake_games[GAME] = config

    record = extract(roi_client).json()["data"]

    assert record["tiles"] == []
    assert [c["name"] for c in record["crops"]] == ["cash_meter", "cyclic_message_2"]


@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080), (800, 800), (3440, 1440), (97, 61)])
def test_regions_follow_the_fractions_on_any_aspect_ratio(
    roi_client: TestClient, connected, fake_obs: FakeObs, size: tuple[int, int]
) -> None:
    width, height = size
    fake_obs.image = png(game_screenshot(width, height))

    record = extract(roi_client).json()["data"]

    reels = record["crops"][0]
    assert abs(reels["width"] - 0.8 * width) <= 1
    assert abs(reels["height"] - 0.6 * height) <= 1
    assert len(record["tiles"]) == 15
    assert all(t["width"] >= 1 and t["height"] >= 1 for t in record["tiles"])


def test_extract_uses_the_selected_game_and_mode_by_default(
    roi_client: TestClient, connected, game_context: GameContextService
) -> None:
    game_context.update_context(GameContextUpdate(game="HuffNPuffHighRise", mode=GameMode.EGM))

    record = roi_client.post(f"{URL}/records").json()["data"]

    assert (record["game"], record["mode"]) == ("HuffNPuffHighRise", "egm")


@pytest.mark.parametrize("mode", ["simulator", "egm"])
@pytest.mark.parametrize(
    "game,regions",
    [
        ("FortuneOx", ["reels", "cash_meter", "cyclic_message", "cyclic_message_2"]),
        ("HuffNPuffHighRise", ["reels", "cash_meter"]),
    ],
)
def test_the_real_game_configs_can_be_extracted(
    roi_client: TestClient, connected, game: str, regions: list[str], mode: str
) -> None:
    record = roi_client.post(f"{URL}/records", params={"game": game, "mode": mode}).json()["data"]

    assert [c["name"] for c in record["crops"]] == regions
    assert (record["rows"], record["columns"]) == (3, 5)
    assert len(record["tiles"]) == 15


# ------------------------------------------------------------- bad config / failures


def test_unknown_game_is_not_found(roi_client: TestClient, connected, fake_obs: FakeObs) -> None:
    response = roi_client.post(f"{URL}/records", params={"game": "NoSuchGame"})

    assert response.status_code == 404
    assert fake_obs.calls("SaveSourceScreenshot") == []


def test_game_without_regions_is_not_found_and_takes_no_screenshot(
    roi_client: TestClient, connected, fake_obs: FakeObs, fake_games
) -> None:
    fake_games[GAME] = make_config(simulator={"roi": {"cyclic_message": []}})

    response = extract(roi_client)

    assert response.status_code == 404
    assert "no ROI" in response.json()["error"]["message"]
    assert fake_obs.calls("SaveSourceScreenshot") == []


@pytest.mark.parametrize(
    "roi",
    [
        [0.5, 0.0, 0.5, 1.0],  # no width
        [0.0, 0.0, 1.5, 1.0],  # outside the screenshot
        [0.0, 0.0, 1.0],  # too short
        "not a region",
    ],
)
def test_invalid_region_is_reported_before_any_screenshot(
    roi_client: TestClient, connected, fake_obs: FakeObs, fake_games, roi
) -> None:
    fake_games[GAME] = make_config(simulator={"roi": {"reels": roi}})

    response = extract(roi_client)

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "CONFIG_INVALID"
    assert "reels" in error["message"]
    assert fake_obs.calls("SaveSourceScreenshot") == []


@pytest.mark.parametrize(
    "bounds",
    [
        {"rows": 0, "columns": 5},
        {"rows": 3},
        {"rows": 3, "columns": 5, "inset": 0.5},
        {"rows": 3, "columns": 5, "inset": [0.1, 0.2, 0.3]},
        "3x5",
    ],
)
def test_invalid_reel_bounds_are_reported_before_any_screenshot(
    roi_client: TestClient, connected, fake_obs: FakeObs, fake_games, bounds
) -> None:
    fake_games[GAME] = make_config(reel_bounds=bounds)

    response = extract(roi_client)

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "CONFIG_INVALID"
    assert "reel_bounds" in error["message"]
    assert fake_obs.calls("SaveSourceScreenshot") == []


def test_unreadable_screenshot_fails_cleanly_and_leaves_no_record(
    roi_client: TestClient, connected, fake_obs: FakeObs, captures_dir: Path
) -> None:
    fake_obs.image = b"not an image"

    response = extract(roi_client)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "ROI_FAILED"
    assert roi_folders(captures_dir) == []
    assert roi_client.get(f"{URL}/records").json()["data"] == []


def test_screenshot_too_small_for_the_grid_fails_cleanly(
    roi_client: TestClient, connected, fake_obs: FakeObs, captures_dir: Path
) -> None:
    # The reels crop of a 4x4 screenshot is 3x2 px, which cannot hold 5 columns.
    fake_obs.image = png(Image.new("RGB", (4, 4)))

    response = extract(roi_client)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ROI_INVALID"
    assert roi_folders(captures_dir) == []


# ------------------------------------------------------------------------ records


def test_records_are_listed_newest_first_and_limited(roi_client: TestClient, connected) -> None:
    ids = [extract(roi_client).json()["data"]["id"] for _ in range(4)]

    listed = roi_client.get(f"{URL}/records", params={"limit": 3}).json()["data"]

    assert [r["id"] for r in listed] == ids[::-1][:3]
    assert roi_client.get(f"{URL}/records").json()["data"][0]["id"] == ids[-1]


def test_listed_records_carry_everything_needed_to_show_them(
    roi_client: TestClient, connected
) -> None:
    created = extract(roi_client).json()["data"]

    (listed,) = roi_client.get(f"{URL}/records").json()["data"]

    assert listed == created


def test_records_survive_a_restart(
    roi_client: TestClient, connected, service: ObsService, game_context, captures_dir: Path
) -> None:
    created = extract(roi_client).json()["data"]

    reopened = RoiService(obs=service, game_context=game_context, captures_dir=captures_dir)

    assert [r.model_dump(mode="json") for r in reopened.list_records(5)] == [created]


def test_list_is_empty_before_the_first_extraction(roi_client: TestClient) -> None:
    assert roi_client.get(f"{URL}/records").json()["data"] == []


def test_list_skips_unfinished_and_foreign_folders(
    roi_client: TestClient, connected, captures_dir: Path
) -> None:
    created = extract(roi_client).json()["data"]
    (captures_dir / "roi" / "roi_29990101_000000_000_abcdef").mkdir()  # newer, but no record
    (captures_dir / "roi" / "junk").mkdir()
    (captures_dir / "roi" / "junk" / "record.json").write_text("{not json")

    listed = roi_client.get(f"{URL}/records").json()["data"]

    assert [r["id"] for r in listed] == [created["id"]]


def test_concurrent_extractions_never_overwrite_each_other(
    roi_service: RoiService, fake_obs: FakeObs, captures_dir: Path
) -> None:
    fake_obs.image = png(game_screenshot())

    async def run():
        await roi_service._obs.connect()
        return await asyncio.gather(*[roi_service.extract(GAME) for _ in range(10)])

    records = asyncio.run(run())

    assert len({r.id for r in records}) == 10
    assert len(roi_folders(captures_dir)) == 10
    assert all(len(r.tiles) == 15 for r in records)


# ----------------------------------------------------------------------- images


def test_images_are_served_as_png(roi_client: TestClient, connected) -> None:
    record = extract(roi_client).json()["data"]

    for image in [*record["crops"], *record["tiles"]]:
        assert fetch(roi_client, image["url"]).size == (image["width"], image["height"])


def test_the_full_screenshot_is_served_by_the_obs_route(roi_client: TestClient, connected) -> None:
    record = extract(roi_client).json()["data"]

    response = roi_client.get(f"/api/v1{record['screenshot']['url']}")

    assert response.status_code == 200
    assert Image.open(io.BytesIO(response.content)).size == (1000, 2000)


@pytest.mark.parametrize(
    "record_id,filename",
    [
        ("roi_20200101_000000_000_abcdef", "reels.png"),  # no such record
        ("..", "reels.png"),
        ("junk", "reels.png"),
        ("RECORD", "record.json"),
        ("RECORD", "notes.txt"),
        ("RECORD", "missing.png"),
        ("RECORD", "..%2Frecord.json"),
        ("RECORD", "..%5Creels.png"),
    ],
)
def test_image_route_rejects_unknown_or_unsafe_names(
    roi_client: TestClient, connected, record_id: str, filename: str
) -> None:
    record = extract(roi_client).json()["data"]
    record_id = record["id"] if record_id == "RECORD" else record_id

    assert roi_client.get(f"{URL}/records/{record_id}/images/{filename}").status_code == 404
